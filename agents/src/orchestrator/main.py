"""Agent Orchestrator — FastAPI application and main entry point."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

import structlog
import uvicorn
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel

from shared.config import settings
from shared.events import event_publisher
from shared.policy import PolicyDecision, policy_engine
from shared.state import AgentTask, TaskStatus, state_manager

logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):  # type: ignore[no-untyped-def]
    logger.info(
        "Starting Agent Orchestrator",
        environment=settings.environment,
        project=settings.project_name,
    )
    yield
    logger.info("Shutting down Agent Orchestrator")


app = FastAPI(
    title="DevOps Agentic Teammates - Orchestrator",
    version="1.0.0",
    lifespan=lifespan,
)


# ---- Health & Info ----

@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "healthy"}


@app.get("/info")
async def info() -> dict[str, Any]:
    return {
        "project": settings.project_name,
        "environment": settings.environment,
        "version": "1.0.0",
    }


# ---- Task Management ----

class TaskRequest(BaseModel):
    agent_type: str
    task_type: str
    context: dict[str, Any] = {}
    idempotency_key: str | None = None


class TaskResponse(BaseModel):
    task_id: str
    agent_type: str
    task_type: str
    status: str
    message: str


@app.post("/api/tasks", response_model=TaskResponse)
async def create_task(request: TaskRequest) -> TaskResponse:
    """Create a new agent task after policy evaluation."""
    # Evaluate policy
    policy_result = policy_engine.evaluate(
        agent=request.agent_type,
        action=request.task_type,
        context=request.context,
    )

    if policy_result.decision == PolicyDecision.DENY:
        raise HTTPException(
            status_code=403,
            detail=f"Policy denied: {policy_result.reason}",
        )

    # Create task
    task = AgentTask(
        agent_type=request.agent_type,
        task_type=request.task_type,
        context=request.context,
        idempotency_key=request.idempotency_key,
    )

    if policy_result.decision == PolicyDecision.REQUIRE_APPROVAL:
        task.status = TaskStatus.AWAITING_APPROVAL
        await state_manager.create_task(task)
        await event_publisher.publish_approval_request(
            agent_type=task.agent_type,
            task_id=task.task_id,
            action=task.task_type,
            context=task.context,
            approvers=policy_result.approvers or [],
        )
        return TaskResponse(
            task_id=task.task_id,
            agent_type=task.agent_type,
            task_type=task.task_type,
            status=task.status.value,
            message=f"Awaiting approval from: {', '.join(policy_result.approvers or [])}",
        )

    # Allowed — dispatch to agent
    await state_manager.create_task(task)
    await event_publisher.publish_task_requested(
        agent_type=task.agent_type,
        task_type=task.task_type,
        context=task.context,
        policy={"constraints": policy_result.constraints} if policy_result.constraints else None,
    )

    return TaskResponse(
        task_id=task.task_id,
        agent_type=task.agent_type,
        task_type=task.task_type,
        status=task.status.value,
        message="Task dispatched to agent",
    )


@app.get("/api/tasks/{agent_type}/{task_id}")
async def get_task(agent_type: str, task_id: str) -> dict[str, Any]:
    """Get task status and details."""
    task = await state_manager.get_task(agent_type, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task.model_dump()


@app.get("/api/tasks/status/{status}")
async def get_tasks_by_status(status: str) -> list[dict[str, Any]]:
    """Get all tasks with a given status."""
    task_status = TaskStatus(status)
    tasks = await state_manager.get_tasks_by_status(task_status)
    return [t.model_dump() for t in tasks]


@app.get("/api/tasks/repo/{owner}/{repo}")
async def get_tasks_by_repo(owner: str, repo: str) -> list[dict[str, Any]]:
    """Get all tasks for a repository."""
    tasks = await state_manager.get_tasks_by_repository(f"{owner}/{repo}")
    return [t.model_dump() for t in tasks]


# ---- Approval Handling ----

class ApprovalRequest(BaseModel):
    task_id: str
    agent_type: str
    approved: bool
    approver: str
    comment: str = ""


@app.post("/api/approvals")
async def handle_approval(request: ApprovalRequest) -> dict[str, str]:
    """Handle a human approval or rejection."""
    task = await state_manager.get_task(request.agent_type, request.task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if task.status != TaskStatus.AWAITING_APPROVAL:
        raise HTTPException(
            status_code=400,
            detail=f"Task is not awaiting approval (status: {task.status.value})",
        )

    if request.approved:
        task.status = TaskStatus.PENDING
        await state_manager.update_task(task)
        await event_publisher.publish_task_requested(
            agent_type=task.agent_type,
            task_type=task.task_type,
            context=task.context,
        )
        return {"message": f"Task approved by {request.approver} and dispatched"}
    else:
        task.status = TaskStatus.CANCELLED
        task.error = f"Rejected by {request.approver}: {request.comment}"
        await state_manager.update_task(task)
        return {"message": f"Task rejected by {request.approver}"}


# ---- Webhook Handler ----

@app.post("/webhooks/github")
async def github_webhook(request: Request) -> dict[str, str]:
    """Receive and route GitHub webhook events."""
    event_type = request.headers.get("X-GitHub-Event", "")
    payload = await request.json()

    logger.info("Received GitHub webhook", event_type=event_type)

    routing_map = {
        "pull_request": "code-build",
        "push": "code-build",
        "issues": "plan-collaborate",
        "issue_comment": "plan-collaborate",
        "check_run": "test-secure",
        "workflow_run": "test-secure",
        "release": "release-deploy",
    }

    agent_type = routing_map.get(event_type, "code-build")
    action = payload.get("action", "")
    task_type = f"{event_type}.{action}" if action else event_type

    repo = payload.get("repository", {}).get("full_name", "unknown")
    pr_number = (
        payload.get("pull_request", {}).get("number")
        or payload.get("number")
    )

    task = AgentTask(
        agent_type=agent_type,
        task_type=task_type,
        context={
            "repository": repo,
            "prNumber": pr_number,
            "githubEvent": event_type,
            "action": action,
            "sender": payload.get("sender", {}).get("login"),
        },
        input_data={"payload": payload},
        idempotency_key=f"{repo}/{event_type}/{action}/{pr_number}/{payload.get('after', '')}",
    )

    await state_manager.create_task(task)
    await event_publisher.publish_task_requested(
        agent_type=agent_type,
        task_type=task_type,
        context=task.context,
    )

    return {"message": f"Routed to {agent_type} agent"}


# ---- Metrics ----

@app.get("/api/metrics/dora")
async def dora_metrics() -> dict[str, Any]:
    """Return DORA metrics summary."""
    # This would query real data in production
    return {
        "deployment_frequency": {"value": 0, "unit": "per_day"},
        "lead_time_for_changes": {"value": 0, "unit": "hours"},
        "change_failure_rate": {"value": 0, "unit": "percent"},
        "mean_time_to_recovery": {"value": 0, "unit": "minutes"},
    }


def main() -> None:
    uvicorn.run(
        "orchestrator.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=settings.environment == "dev",
    )


if __name__ == "__main__":
    main()
