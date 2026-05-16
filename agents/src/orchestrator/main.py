"""Agent Orchestrator — FastAPI application and main entry point."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Any

import structlog
import uvicorn
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
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


async def execute_agent_task(task: AgentTask) -> None:
    """Execute an agent workflow in-process (EKS deployment mode)."""
    try:
        agent_type = task.agent_type
        task_type = task.task_type
        context = task.context

        if agent_type == "code-build" and "pull_request" in task_type:
            from agents.code_build import code_review_agent

            pr_number = context.get("prNumber")
            repository = context.get("repository", "")
            if not pr_number or not repository:
                logger.warning("Missing PR number or repository for code review")
                return

            initial_state = {
                "messages": [],
                "task": task,
                "repository": repository,
                "pr_number": pr_number,
                "diff": "",
                "review_comments": [],
                "review_summary": "",
                "recommendation": "",
            }
            await code_review_agent.ainvoke(initial_state)
            logger.info("Code review completed", task_id=task.task_id)

        elif agent_type == "test-secure":
            from agents.test_secure import test_gen_agent, security_scan_agent

            pr_number = context.get("prNumber")
            repository = context.get("repository", "")

            if "security" in task_type or "check_run" in task_type:
                initial_state = {
                    "messages": [],
                    "task": task,
                    "repository": repository,
                    "pr_number": pr_number or 0,
                    "scan_results": {},
                    "fix_prs": [],
                    "security_report": "",
                }
                await security_scan_agent.ainvoke(initial_state)
                logger.info("Security scan completed", task_id=task.task_id)
            elif pr_number and repository:
                initial_state = {
                    "messages": [],
                    "task": task,
                    "repository": repository,
                    "pr_number": pr_number,
                    "source_files": [],
                    "codebase_context": [],
                    "generated_tests": [],
                    "coverage_estimate": 0.0,
                }
                await test_gen_agent.ainvoke(initial_state)
                logger.info("Test generation completed", task_id=task.task_id)
            else:
                logger.warning("Missing context for test-secure agent", task_id=task.task_id)

        elif agent_type == "release-deploy":
            from agents.release_deploy import (
                build_release_graph, build_deploy_graph,
                build_ephemeral_graph, build_tf_review_graph,
            )

            repository = context.get("repository", "")

            if "release" in task_type:
                release_agent = build_release_graph().compile()
                initial_state = {
                    "messages": [],
                    "task": task,
                    "repository": repository,
                    "release_type": context.get("releaseType", "patch"),
                    "current_version": context.get("currentVersion", "0.0.0"),
                    "next_version": "",
                    "changelog": "",
                    "release_url": "",
                }
                await release_agent.ainvoke(initial_state)
                logger.info("Release completed", task_id=task.task_id)
            elif "deploy" in task_type:
                deploy_agent = build_deploy_graph().compile()
                initial_state = {
                    "messages": [],
                    "task": task,
                    "repository": repository,
                    "environment": context.get("environment", "staging"),
                    "version": context.get("version", "latest"),
                    "strategy": context.get("strategy", "canary"),
                    "deploy_status": "",
                    "rollback_triggered": False,
                    "argocd_app": "",
                }
                await deploy_agent.ainvoke(initial_state)
                logger.info("Deploy completed", task_id=task.task_id)
            elif "ephemeral" in task_type or "pull_request" in task_type:
                ephemeral_agent = build_ephemeral_graph().compile()
                action = "destroy" if context.get("action") == "closed" else "create"
                initial_state = {
                    "messages": [],
                    "task": task,
                    "repository": repository,
                    "pr_number": context.get("prNumber", 0),
                    "action": action,
                    "env_url": "",
                    "namespace": "",
                }
                await ephemeral_agent.ainvoke(initial_state)
                logger.info("Ephemeral env managed", task_id=task.task_id, action=action)
            elif "terraform" in task_type:
                tf_agent = build_tf_review_graph().compile()
                initial_state = {
                    "messages": [],
                    "task": task,
                    "repository": repository,
                    "pr_number": context.get("prNumber", 0),
                    "plan_output": context.get("planOutput", ""),
                    "review_summary": "",
                    "risk_level": "",
                }
                await tf_agent.ainvoke(initial_state)
                logger.info("Terraform review completed", task_id=task.task_id)
            else:
                logger.info("Unhandled release-deploy task", task_type=task_type, task_id=task.task_id)

        elif agent_type == "plan-collaborate":
            from agents.plan_collaborate import plan_agent

            repository = context.get("repository", "")
            description = context.get("featureDescription", "")

            if not description:
                # Extract description from issue body if available
                input_data = task.input_data or {}
                payload = input_data.get("payload", {})
                issue = payload.get("issue", {})
                description = issue.get("body", issue.get("title", ""))

            if repository and description:
                initial_state = {
                    "messages": [],
                    "task": task,
                    "repository": repository,
                    "feature_description": description,
                    "components": [],
                    "user_stories": [],
                    "api_contracts": [],
                    "specs_committed": False,
                }
                await plan_agent.ainvoke(initial_state)
                logger.info("Planning completed", task_id=task.task_id)
            else:
                logger.warning("Missing context for plan-collaborate", task_id=task.task_id)

        elif agent_type == "operate-monitor":
            from agents.operate_monitor import (
                incident_agent, cost_analysis_agent, build_performance_graph,
            )

            repository = context.get("repository", "")

            if "incident" in task_type or "alert" in task_type:
                initial_state = {
                    "messages": [],
                    "task": task,
                    "repository": repository,
                    "alert_data": context.get("alertData", {}),
                    "diagnosis": "",
                    "remediation_plan": [],
                    "actions_taken": [],
                    "resolved": False,
                    "postmortem": "",
                }
                await incident_agent.ainvoke(initial_state)
                logger.info("Incident response completed", task_id=task.task_id)
            elif "cost" in task_type:
                initial_state = {
                    "messages": [],
                    "task": task,
                    "repository": repository,
                    "cost_data": context.get("costData", {}),
                    "recommendations": [],
                    "savings_estimate": 0.0,
                    "report": "",
                }
                await cost_analysis_agent.ainvoke(initial_state)
                logger.info("Cost analysis completed", task_id=task.task_id)
            elif "performance" in task_type:
                perf_agent = build_performance_graph().compile()
                initial_state = {
                    "messages": [],
                    "task": task,
                    "repository": repository,
                    "metrics": context.get("metrics", {}),
                    "bottlenecks": [],
                    "optimization_plan": [],
                }
                await perf_agent.ainvoke(initial_state)
                logger.info("Performance analysis completed", task_id=task.task_id)
            else:
                logger.info("Unhandled operate-monitor task", task_type=task_type, task_id=task.task_id)

        else:
            logger.info("Unknown agent type", agent_type=agent_type, task_id=task.task_id)

    except Exception as e:
        logger.error("Agent task execution failed", error=str(e), task_id=task.task_id)
        task.status = TaskStatus.FAILED
        task.error = str(e)
        try:
            await state_manager.update_task(task)
        except Exception:
            pass


@app.post("/webhooks/github")
async def github_webhook(request: Request, background_tasks: BackgroundTasks) -> dict[str, str]:
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
        "check_suite": "test-secure",
        "workflow_run": "test-secure",
        "release": "release-deploy",
        "deployment": "release-deploy",
        "deployment_status": "release-deploy",
        "status": "operate-monitor",
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

    # Execute agent in background (in-process for EKS deployment)
    background_tasks.add_task(execute_agent_task, task)

    # RAG indexing on push events
    if event_type == "push":
        background_tasks.add_task(index_push_changes, repo, payload)

    return {"message": f"Routed to {agent_type} agent"}


async def index_push_changes(repository: str, payload: dict[str, Any]) -> None:
    """Index changed files from a push event into the RAG pipeline."""
    try:
        from shared.rag import RAGPipeline
        import httpx

        rag = RAGPipeline()
        rag.ensure_index()

        commits = payload.get("commits", [])
        files_to_index: set[str] = set()
        for commit in commits:
            files_to_index.update(commit.get("added", []))
            files_to_index.update(commit.get("modified", []))

        if not files_to_index:
            return

        # Fetch file contents from GitHub
        ref = payload.get("after", "main")
        async with httpx.AsyncClient() as client:
            for file_path in list(files_to_index)[:20]:  # Limit to 20 files per push
                # Skip binary/non-code files
                if not any(file_path.endswith(ext) for ext in [
                    ".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".java",
                    ".tf", ".yaml", ".yml", ".md", ".sql",
                ]):
                    continue

                url = f"https://api.github.com/repos/{repository}/contents/{file_path}?ref={ref}"
                resp = await client.get(
                    url,
                    headers={
                        "Accept": "application/vnd.github.raw+json",
                        "Authorization": f"token {settings.github_token}",
                    },
                    timeout=10.0,
                )
                if resp.status_code == 200:
                    content = resp.text
                    ext = file_path.rsplit(".", 1)[-1] if "." in file_path else "unknown"
                    await rag.index_file(
                        repository=repository,
                        file_path=file_path,
                        content=content,
                        language=ext,
                    )

        logger.info("RAG indexing completed", repository=repository, files=len(files_to_index))
    except Exception as e:
        logger.warning("RAG indexing failed (non-fatal)", error=str(e))


# ---- Metrics ----

@app.get("/api/metrics/dora")
async def dora_metrics() -> dict[str, Any]:
    """Return DORA metrics computed from task history."""
    tasks = await state_manager.get_tasks_by_status(TaskStatus.COMPLETED)
    deploy_tasks = [t for t in tasks if "deploy" in t.task_type]
    failed_tasks = [t for t in deploy_tasks if t.output_data and t.output_data.get("rollback")]

    from datetime import datetime, timezone, timedelta
    now = datetime.now(timezone.utc)
    day_ago = now - timedelta(hours=24)

    recent_deploys = [
        t for t in deploy_tasks
        if t.completed_at and datetime.fromisoformat(t.completed_at) > day_ago
    ]

    return {
        "deployment_frequency": {"value": len(recent_deploys), "unit": "per_day"},
        "lead_time_for_changes": {"value": 0, "unit": "hours"},
        "change_failure_rate": {
            "value": round(len(failed_tasks) / max(len(deploy_tasks), 1) * 100, 1),
            "unit": "percent",
        },
        "mean_time_to_recovery": {"value": 0, "unit": "minutes"},
    }


@app.get("/api/metrics/agents")
async def agent_metrics() -> dict[str, Any]:
    """Return agent activity metrics."""
    all_tasks = await state_manager.get_all_tasks_recent(hours=24)
    by_agent: dict[str, dict[str, int]] = {}
    for t in all_tasks:
        agent = t.agent_type
        if agent not in by_agent:
            by_agent[agent] = {"total": 0, "completed": 0, "failed": 0, "in_progress": 0}
        by_agent[agent]["total"] += 1
        if t.status == TaskStatus.COMPLETED:
            by_agent[agent]["completed"] += 1
        elif t.status == TaskStatus.FAILED:
            by_agent[agent]["failed"] += 1
        elif t.status == TaskStatus.IN_PROGRESS:
            by_agent[agent]["in_progress"] += 1

    return {"agents": by_agent, "total_tasks_24h": len(all_tasks)}


@app.get("/api/metrics/events")
async def recent_events() -> list[dict[str, Any]]:
    """Return recent agent events for the dashboard."""
    tasks = await state_manager.get_all_tasks_recent(hours=24)
    events = []
    for t in sorted(tasks, key=lambda x: x.completed_at or x.started_at or "", reverse=True)[:20]:
        events.append({
            "agent": t.agent_type,
            "task_type": t.task_type,
            "status": t.status.value,
            "timestamp": t.completed_at or t.started_at or "",
            "output": t.output_data or {},
        })
    return events


# ---- Alert Webhook (CloudWatch / Prometheus Alertmanager) ----

class AlertPayload(BaseModel):
    source: str = "cloudwatch"
    alert_name: str = ""
    severity: str = "warning"
    repository: str = ""
    data: dict[str, Any] = {}


@app.post("/webhooks/alerts")
async def alert_webhook(payload: AlertPayload, background_tasks: BackgroundTasks) -> dict[str, str]:
    """Receive infrastructure alerts and route to operate-monitor agent."""
    logger.info("Received alert", alert_name=payload.alert_name, severity=payload.severity)

    task = AgentTask(
        agent_type="operate-monitor",
        task_type=f"incident.{payload.source}",
        context={
            "repository": payload.repository or f"benlbk/devops-agentic-teammates",
            "alertData": {
                "alert_name": payload.alert_name,
                "severity": payload.severity,
                "source": payload.source,
                **payload.data,
            },
        },
    )

    await state_manager.create_task(task)
    background_tasks.add_task(execute_agent_task, task)

    return {"message": f"Alert routed to operate-monitor agent (task_id: {task.task_id})"}


def main() -> None:
    uvicorn.run(
        "orchestrator.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=settings.environment == "dev",
    )


if __name__ == "__main__":
    main()
