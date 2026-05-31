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
from shared.state import AgentTask, Project, TaskStatus, state_manager

logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):  # type: ignore[no-untyped-def]
    logger.info(
        "Starting Agent Orchestrator",
        environment=settings.environment,
        project=settings.project_name,
    )
    # Load policies
    from pathlib import Path
    policy_path = Path(__file__).parent.parent.parent / "config" / "policies.yaml"
    if policy_path.exists():
        policy_engine.load_from_file(policy_path)
        logger.info("Loaded policies from file", path=str(policy_path))
    yield
    logger.info("Shutting down Agent Orchestrator")


app = FastAPI(
    title="DevOps Agentic Teammates - Orchestrator",
    version="1.0.0",
    lifespan=lifespan,
)


# ---- Prometheus metrics (best-effort instrumentation) ----
try:
    from prometheus_fastapi_instrumentator import Instrumentator  # type: ignore[import-not-found]

    Instrumentator().instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)
    logger.info("Prometheus /metrics endpoint mounted")
except ImportError:
    logger.warning("prometheus_fastapi_instrumentator not installed; /metrics disabled")

try:
    from prometheus_client import Counter, Histogram  # type: ignore[import-not-found]

    AGENT_TASKS_STARTED = Counter(
        "agent_tasks_started_total",
        "Agent tasks started",
        ["agent_type", "task_type"],
    )
    AGENT_TASKS_COMPLETED = Counter(
        "agent_tasks_completed_total",
        "Agent tasks completed (terminal status)",
        ["agent_type", "task_type", "status"],
    )
    AGENT_TASK_DURATION = Histogram(
        "agent_task_duration_seconds",
        "Agent task wall-clock duration",
        ["agent_type", "task_type"],
        buckets=(1, 5, 10, 30, 60, 120, 300, 600, 1800),
    )
    AGENT_LLM_TOKENS = Counter(
        "agent_llm_tokens_total",
        "Estimated LLM tokens consumed by agent tasks",
        ["agent_type", "task_type"],
    )
    AGENT_LLM_TOKENS_BY_MODEL = Counter(
        "agent_llm_tokens_by_model_total",
        "Estimated LLM tokens consumed by agent tasks, broken down by model",
        ["agent_type", "task_type", "model"],
    )
except ImportError:
    AGENT_TASKS_STARTED = None  # type: ignore[assignment]
    AGENT_TASKS_COMPLETED = None  # type: ignore[assignment]
    AGENT_TASK_DURATION = None  # type: ignore[assignment]
    AGENT_LLM_TOKENS = None  # type: ignore[assignment]
    AGENT_LLM_TOKENS_BY_MODEL = None  # type: ignore[assignment]


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
async def create_task(request: TaskRequest, background_tasks: BackgroundTasks) -> TaskResponse:
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

    # Execute agent in background (in-process for EKS deployment)
    background_tasks.add_task(execute_agent_task, task)

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


@app.get("/api/reviews")
async def list_terraform_reviews(repository: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    """List terraform-review tasks, optionally filtered by repository."""
    if repository:
        tasks = await state_manager.get_tasks_by_repository(repository)
    else:
        # Fall back to completed status (TF reviews always complete)
        tasks = await state_manager.get_tasks_by_status(TaskStatus.COMPLETED)
    reviews = [
        {
            "task_id": t.task_id,
            "repository": t.context.get("repository", ""),
            "pr_number": t.context.get("prNumber") or t.context.get("pr_number"),
            "risk_level": (t.output_data or {}).get("risk_level", "UNKNOWN"),
            "review_summary": (t.output_data or {}).get("review_summary", ""),
            "pr_comment_url": (t.output_data or {}).get("pr_comment_url", ""),
            "created_at": t.created_at,
            "completed_at": t.completed_at,
            "status": t.status.value if hasattr(t.status, "value") else str(t.status),
        }
        for t in tasks
        if t.task_type == "terraform-review"
    ]
    reviews.sort(key=lambda r: r["created_at"], reverse=True)
    return reviews[:limit]


@app.get("/api/github/{owner}/{repo}/latest-release")
async def get_github_latest_release(owner: str, repo: str) -> dict[str, Any]:
    """Return the latest release tag for a repo (helper for the Pipeline UI)."""
    from shared.github_client import github_client
    try:
        latest = await github_client.get_latest_release(owner=owner, repo=repo)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"GitHub API error: {e}") from e
    if not latest:
        return {"tag_name": "", "version": "0.0.0", "html_url": "", "exists": False}
    tag = latest.get("tag_name", "")
    return {
        "tag_name": tag,
        "version": tag.lstrip("v") if tag else "0.0.0",
        "html_url": latest.get("html_url", ""),
        "exists": True,
    }


# ---- Approval Handling ----

class ApprovalRequest(BaseModel):
    task_id: str
    agent_type: str
    approved: bool
    approver: str
    comment: str = ""


@app.get("/api/approvals")
async def list_pending_approvals() -> list[dict[str, Any]]:
    """List all tasks awaiting human approval."""
    tasks = await state_manager.get_tasks_by_status(TaskStatus.AWAITING_APPROVAL)
    results = []
    for t in tasks:
        results.append({
            "task_id": t.task_id,
            "agent_type": t.agent_type,
            "task_type": t.task_type,
            "repository": t.context.get("repository", ""),
            "pr_number": t.context.get("prNumber") or t.context.get("pr_number"),
            "issue_number": t.context.get("issue_number") or t.context.get("issueNumber"),
            "created_at": t.created_at,
            "context": t.context,
            "output_data": t.output_data,
        })
    return results


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
        # For merge-approval tasks, trigger the actual merge
        if task.task_type == "merge-approval":
            from shared.github_client import github_client
            repository = task.context.get("repository", "")
            pr_number = task.context.get("pr_number") or task.context.get("prNumber")

            try:
                owner, repo = repository.split("/")
                result = await github_client.merge_pull_request(
                    owner=owner,
                    repo=repo,
                    pr_number=int(pr_number),
                    merge_method="squash",
                    commit_title=f"Merge PR #{pr_number} (approved by {request.approver})",
                )
                task.status = TaskStatus.COMPLETED
                task.completed_at = __import__("datetime").datetime.now(
                    __import__("datetime").timezone.utc
                ).isoformat()
                task.output_data = task.output_data or {}
                task.output_data["merged"] = True
                task.output_data["approved_by"] = request.approver
                task.output_data["merge_sha"] = result.get("sha", "")
                await state_manager.update_task(task)
                logger.info("PR merged after approval", pr_number=pr_number, approver=request.approver)
                return {"message": f"PR #{pr_number} merged (approved by {request.approver})"}
            except Exception as e:
                task.status = TaskStatus.FAILED
                task.error = f"Merge failed: {str(e)}"
                await state_manager.update_task(task)
                return {"message": f"Approval accepted but merge failed: {str(e)}"}
        else:
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


async def _fail_task(task: AgentTask, error_msg: str) -> None:
    """Mark a task as failed with an error message."""
    task.status = TaskStatus.FAILED
    task.error = error_msg
    task.started_at = task.started_at or __import__("datetime").datetime.now(
        __import__("datetime").timezone.utc
    ).isoformat()
    await state_manager.update_task(task)
    logger.warning("Task failed", task_id=task.task_id, error=error_msg)


async def _run_sprint_planning(task: AgentTask, context: dict, repository: str) -> None:
    """Run sprint planning using LLM to analyze issues and suggest scope."""
    from langchain_core.messages import HumanMessage, SystemMessage
    from shared.llm import llm_provider
    import json, re

    task.status = TaskStatus.IN_PROGRESS
    task.started_at = __import__("datetime").datetime.now(
        __import__("datetime").timezone.utc
    ).isoformat()
    await state_manager.update_task(task)

    sprint_goal = context.get("sprint_goal", "")
    capacity_days = context.get("capacity_days", "10")
    team_size = context.get("team_size", "3")

    # Determine which repo to fetch issues from
    # If project_repo is specified (as full owner/repo), use that; otherwise use the default repo
    project_repo = context.get("project_repo", "").strip()
    if project_repo:
        if "/" in project_repo:
            issues_repo = project_repo
        else:
            issues_repo = f"{repository.split('/')[0]}/{project_repo}" if "/" in repository else f"benlbk/{project_repo}"
    else:
        issues_repo = repository

    # Fetch open issues from the issues repository
    issues_text = ""
    velocity_text = ""
    velocity_points = 0
    velocity_window_days = int(context.get("velocity_window_days", 30))
    try:
        from shared.github_client import github_client
        owner, repo = issues_repo.split("/")
        issues = await github_client.list_issues(owner=owner, repo=repo, labels=["agent-generated"], state="open")
        if not issues:
            # Try without label filter for new repos
            issues = await github_client.list_issues(owner=owner, repo=repo, state="open", per_page=30)
        for issue in issues[:30]:  # Limit to 30 issues
            issues_text += f"- #{issue.get('number', '?')}: {issue.get('title', '')} (labels: {', '.join(l.get('name', '') for l in issue.get('labels', []))})\n"

        # Velocity proxy: count closed issues in last N days, extract story points from body where present
        from datetime import datetime, timezone, timedelta
        cutoff = datetime.now(timezone.utc) - timedelta(days=velocity_window_days)
        closed = await github_client.list_issues(owner=owner, repo=repo, state="closed", per_page=100)
        closed_count = 0
        for issue in closed:
            closed_at = issue.get("closed_at")
            if not closed_at:
                continue
            try:
                ts = datetime.fromisoformat(closed_at.replace("Z", "+00:00"))
            except ValueError:
                continue
            if ts < cutoff:
                continue
            closed_count += 1
            body = issue.get("body", "") or ""
            m = __import__("re").search(r"story\s*points?\s*[:=]?\s*\**\s*(\d+)", body, __import__("re").IGNORECASE)
            if m:
                try:
                    velocity_points += int(m.group(1))
                except ValueError:
                    pass
        velocity_text = (
            f"Last {velocity_window_days} days: {closed_count} issues closed, "
            f"~{velocity_points} story points delivered."
        )
    except Exception as e:
        logger.warning("Failed to fetch issues for sprint planning", error=str(e), repo=issues_repo)
        issues_text = "Could not fetch issues — provide general guidance based on sprint goal."
        velocity_text = "Velocity unknown — no historical data available."

    messages = [
        SystemMessage(content="""You are an agile coach helping plan a sprint. Given the sprint goal, team capacity, 
historical velocity, and available backlog issues, suggest which issues to include in the sprint.
Return a JSON object with:
- sprint_name: a short sprint name
- selected_issues: list of issue numbers to include
- total_story_points: estimated total
- rationale: why these issues were selected
- risks: potential risks or blockers
- recommendations: suggestions for the team
Respond ONLY with valid JSON. Do not wrap in markdown code fences."""),
        HumanMessage(content=f"""Sprint Goal: {sprint_goal}
Capacity: {capacity_days} days
Team Size: {team_size} developers
Historical Velocity: {velocity_text}

Available Backlog Issues:
{issues_text}"""),
    ]

    response = await llm_provider.ainvoke(messages)
    try:
        content = response.content
        if isinstance(content, str):
            content = re.sub(r'^```(?:json)?\s*\n?', '', content.strip())
            content = re.sub(r'\n?```\s*$', '', content.strip())
        output = json.loads(content)
        if not isinstance(output, dict):
            output = {"sprint_plan": content}
    except (json.JSONDecodeError, TypeError):
        output = {"sprint_plan": response.content if hasattr(response, 'content') else str(response)}

    task.status = TaskStatus.COMPLETED
    task.completed_at = __import__("datetime").datetime.now(
        __import__("datetime").timezone.utc
    ).isoformat()
    output.setdefault("velocity", {
        "window_days": velocity_window_days,
        "story_points_delivered": velocity_points,
        "summary": velocity_text,
    })
    task.output_data = output
    task.tokens_used = llm_provider.tokens_used
    await state_manager.update_task(task)
    logger.info("Sprint planning completed", task_id=task.task_id)

    # Commit sprint summary doc to issues repo (docs/sprints/<name>.md)
    sprint_name = output.get("sprint_name") or f"sprint-{task.task_id[:8]}"
    sprint_slug = "".join(c for c in sprint_name.lower().replace(" ", "-") if c.isalnum() or c == "-")[:60].strip("-") or "sprint"
    summary_md = f"""# Sprint Plan: {sprint_name}

## Goal
{sprint_goal or "(not specified)"}

## Capacity
- Team size: {team_size}
- Capacity (days): {capacity_days}

## Historical Velocity
{velocity_text}

## Scope
- Selected issues: {', '.join('#' + str(i).lstrip('#') for i in output.get('selected_issues', [])) or '(none)'}
- Total story points: {output.get('total_story_points', 'N/A')}

## Rationale
{output.get('rationale', '(not provided)')}

## Risks
{output.get('risks', '(not provided)')}

## Recommendations
{output.get('recommendations', '(not provided)')}

---
*Generated by DevOps Agentic Teammates — Plan & Collaborate Agent (task `{task.task_id}`)*
"""
    try:
        from shared.github_client import github_client as gh
        s_owner, s_repo = issues_repo.split("/")
        await gh.create_or_update_file(
            owner=s_owner, repo=s_repo,
            path=f"docs/sprints/{sprint_slug}.md",
            content=summary_md,
            message=f"docs(sprint): plan {sprint_name}",
            branch="main",
        )
        logger.info("Sprint summary committed", path=f"docs/sprints/{sprint_slug}.md", repo=issues_repo)
    except Exception as e:
        logger.warning("Failed to commit sprint summary", error=str(e))

    # Auto-chain: trigger code generation for each selected issue
    selected_issues = output.get("selected_issues", [])
    if selected_issues and repository:
        # Determine target repo for code generation
        project_repo = context.get("project_repo", "").strip()
        target_repository = repository  # default: source issue repo
        if project_repo:
            # Parse project_repo — may be "owner/repo" or just "repo"
            if "/" in project_repo:
                pr_owner, pr_name = project_repo.split("/", 1)
            else:
                pr_owner = repository.split("/")[0]
                pr_name = project_repo
            try:
                from shared.github_client import github_client as gh
                repo_data = await gh.ensure_repository(
                    owner=pr_owner,
                    repo=pr_name,
                    description=f"Auto-created for sprint: {output.get('sprint_name', '')}",
                )
                target_repository = repo_data.get("full_name", f"{pr_owner}/{pr_name}")
                logger.info("Using project repository", target_repo=target_repository)
            except Exception as e:
                logger.warning("Failed to create project repo, using source repo", error=str(e))

        logger.info(
            "Chaining code generation for sprint issues",
            task_id=task.task_id,
            issues=selected_issues,
            target_repo=target_repository,
        )
        for issue_num in selected_issues:
            # Strip '#' prefix if LLM included it (e.g. "#1" -> "1")
            issue_num_clean = str(issue_num).lstrip('#')
            try:
                chained_task = AgentTask(
                    agent_type="code-build",
                    task_type="code-generation",
                    context={
                        "repository": target_repository,
                        "issue_number": issue_num_clean,
                        "source_repository": issues_repo,
                        "sprint_task_id": task.task_id,
                    },
                )
                await state_manager.create_task(chained_task)
                await event_publisher.publish_task_requested(
                    agent_type="code-build",
                    task_type="code-generation",
                    context=chained_task.context,
                )
                # Execute in background
                asyncio.ensure_future(execute_agent_task(chained_task))
                logger.info(
                    "Chained code-gen task created",
                    issue=issue_num,
                    chained_task_id=chained_task.task_id,
                )
            except Exception as e:
                logger.error("Failed to chain code-gen task", issue=issue_num, error=str(e))


async def _run_generic_task(task: AgentTask) -> None:
    """Generic LLM-based task handler for task types without dedicated graphs."""
    from langchain_core.messages import HumanMessage, SystemMessage
    from shared.llm import llm_provider
    import json, re

    task.status = TaskStatus.IN_PROGRESS
    task.started_at = __import__("datetime").datetime.now(
        __import__("datetime").timezone.utc
    ).isoformat()
    await state_manager.update_task(task)

    context_str = json.dumps(task.context, indent=2, default=str)
    messages = [
        SystemMessage(content=f"""You are an AI DevOps agent handling a '{task.task_type}' task for the '{task.agent_type}' team.
Analyze the context provided and produce actionable output.
Return a JSON object with your analysis, recommendations, and any actions taken.
Respond ONLY with valid JSON. Do not wrap in markdown code fences."""),
        HumanMessage(content=f"""Task Type: {task.task_type}
Agent: {task.agent_type}

Context:
{context_str}"""),
    ]

    response = await llm_provider.ainvoke(messages)
    try:
        content = response.content
        if isinstance(content, str):
            content = re.sub(r'^```(?:json)?\s*\n?', '', content.strip())
            content = re.sub(r'\n?```\s*$', '', content.strip())
        output = json.loads(content)
        if not isinstance(output, dict):
            output = {"result": content}
    except (json.JSONDecodeError, TypeError):
        output = {"result": response.content if hasattr(response, 'content') else str(response)}

    task.status = TaskStatus.COMPLETED
    task.completed_at = __import__("datetime").datetime.now(
        __import__("datetime").timezone.utc
    ).isoformat()
    task.output_data = output
    task.tokens_used = llm_provider.tokens_used
    await state_manager.update_task(task)
    logger.info("Generic task completed", task_id=task.task_id, task_type=task.task_type)


async def execute_agent_task(task: AgentTask) -> None:
    """Execute an agent workflow in-process (EKS deployment mode)."""
    import time as _time
    _start_ts = _time.monotonic()
    try:
        from shared.llm import start_task_token_tracking
        start_task_token_tracking()
    except Exception:
        pass
    if AGENT_TASKS_STARTED is not None:
        try:
            AGENT_TASKS_STARTED.labels(agent_type=task.agent_type, task_type=task.task_type).inc()
        except Exception:
            pass
    try:
        agent_type = task.agent_type
        task_type = task.task_type
        context = task.context

        if agent_type == "code-build":
            from agents.code_build import code_review_agent, code_gen_agent

            repository = context.get("repository", "")
            pr_number = context.get("prNumber") or context.get("pr_number")

            if "pull_request" in task_type or "code-review" in task_type:
                if not pr_number or not repository:
                    await _fail_task(task, "Missing PR number or repository for code review")
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

            elif "code-generation" in task_type:
                spec = context.get("spec", {})
                fix_mode = context.get("fix_mode", False)
                branch_name = ""

                if fix_mode:
                    # Fix mode: build spec from review findings, get PR branch
                    review_summary = context.get("review_summary", "")
                    fix_pr_number = context.get("fix_pr_number")
                    if fix_pr_number and repository:
                        try:
                            from shared.github_client import github_client as gh
                            owner, repo_name = repository.split("/")
                            pr_data = await gh.get_pull_request(
                                owner=owner, repo=repo_name, pr_number=int(fix_pr_number)
                            )
                            branch_name = pr_data.get("head", {}).get("ref", "")
                            logger.info("Fix mode: targeting branch", branch=branch_name, pr=fix_pr_number)
                        except Exception as e:
                            logger.warning("Failed to fetch PR for fix mode", error=str(e))
                    spec = {
                        "name": f"fix-review-{fix_pr_number}",
                        "description": f"Fix review findings:\n\n{review_summary}",
                        "fix_mode": True,
                        "fix_pr_number": fix_pr_number,
                        "review_summary": review_summary,
                    }

                elif not spec:
                    # If issue_number provided, fetch issue from GitHub for spec
                    issue_number = context.get("issue_number") or context.get("issueNumber")
                    # Issues live in source_repository (if chained), otherwise same repo
                    issue_repo = context.get("source_repository") or repository
                    if issue_number and issue_repo:
                        try:
                            from shared.github_client import github_client as gh
                            owner, repo_name = issue_repo.split("/")
                            issue_data = await gh.get_issue(
                                owner=owner, repo=repo_name, issue_number=int(issue_number)
                            )
                            issue_title = issue_data.get("title", "")
                            issue_body = issue_data.get("body", "")
                            issue_labels = [l.get("name", "") for l in issue_data.get("labels", [])]
                            spec = {
                                "description": f"{issue_title}\n\n{issue_body}",
                                "name": issue_title[:50],
                                "issue_number": issue_number,
                                "labels": issue_labels,
                                "target_path": context.get("target_path", ""),
                            }
                            logger.info("Built spec from GitHub issue", issue=issue_number, title=issue_title)
                        except Exception as e:
                            logger.warning("Failed to fetch issue, using context", error=str(e))
                            spec = None

                    if not spec:
                        # Build spec from various context field names
                        description = (
                            context.get("specification", "")
                            or context.get("description", "")
                            or context.get("featureDescription", "")
                        )
                        spec = {
                            "description": description,
                            "name": description[:50] if description else "feature",
                            "target_path": context.get("target_path", ""),
                            "stories": context.get("stories", []),
                            "issue_number": context.get("issueNumber") or context.get("issue_number"),
                        }
                initial_state = {
                    "messages": [],
                    "task": task,
                    "repository": repository or "benlbk/devops-agentic-teammates",
                    "spec": spec,
                    "codebase_context": [],
                    "spec_files": [],
                    "generated_files": [],
                    "branch_name": branch_name,
                    "pr_url": "",
                }
                await code_gen_agent.ainvoke(initial_state)
                logger.info("Code generation completed", task_id=task.task_id)

            elif "dependency" in task_type or "deps" in task_type:
                from agents.dep_build import run_dependency_update
                await run_dependency_update(task, context)
                logger.info("Dependency update completed", task_id=task.task_id)

            elif "build-optim" in task_type or "build_optim" in task_type or "ci-optim" in task_type:
                from agents.dep_build import run_build_optimization
                await run_build_optimization(task, context)
                logger.info("Build optimization completed", task_id=task.task_id)

            else:
                await _run_generic_task(task)

        elif agent_type == "test-secure":
            # FR-3.1/3.3/3.4/3.5 extensions: route advanced task_types first.
            if (
                "e2e" in task_type or "playwright" in task_type or "contract" in task_type
                or "coverage" in task_type or "merge-queue" in task_type or "merge_queue" in task_type
                or "test-optim" in task_type or "test_optim" in task_type
                or "flaky" in task_type or "feature-flag" in task_type or "feature_flag" in task_type
            ):
                from agents.test_secure_ext import (
                    run_e2e_generation, run_contract_tests, run_coverage_enforce,
                    run_merge_queue, run_test_optimization, run_feature_flag,
                )
                if "e2e" in task_type or "playwright" in task_type:
                    await run_e2e_generation(task, context)
                elif "contract" in task_type:
                    await run_contract_tests(task, context)
                elif "coverage" in task_type:
                    await run_coverage_enforce(task, context)
                elif "merge-queue" in task_type or "merge_queue" in task_type:
                    await run_merge_queue(task, context)
                elif "test-optim" in task_type or "test_optim" in task_type or "flaky" in task_type:
                    await run_test_optimization(task, context)
                elif "feature-flag" in task_type or "feature_flag" in task_type:
                    await run_feature_flag(task, context)
                logger.info("test-secure ext task completed", task_id=task.task_id, task_type=task_type)
                return

            from agents.test_secure import test_gen_agent, security_scan_agent

            pr_number = context.get("prNumber")
            repository = context.get("repository", "benlbk/devops-agentic-teammates")

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

            elif "test" in task_type:
                initial_state = {
                    "messages": [],
                    "task": task,
                    "repository": repository,
                    "pr_number": pr_number or 0,
                    "source_files": [],
                    "codebase_context": [],
                    "generated_tests": [],
                    "coverage_estimate": 0.0,
                }
                await test_gen_agent.ainvoke(initial_state)
                logger.info("Test generation completed", task_id=task.task_id)

            else:
                await _run_generic_task(task)

        elif agent_type == "release-deploy":
            # FR-4.1/4.2/4.3/4.4 extension dispatch (must come before legacy graphs)
            tt = task_type.lower()
            if any(k in tt for k in (
                "cost-guard", "cost_guard",
                "argo-rollout", "argo_rollout", "rollout-canary",
                "tf-module", "tf_module", "terraform-module",
                "rightsize", "right-size", "right_size",
                "release-notes", "release_notes",
            )):
                from agents.release_deploy_ext import (
                    run_ephemeral_cost_guard, run_argo_rollout,
                    run_tf_module_generate, run_rightsize_report, run_release_notes,
                )
                if "cost-guard" in tt or "cost_guard" in tt:
                    await run_ephemeral_cost_guard(task, context)
                elif "argo-rollout" in tt or "argo_rollout" in tt or "rollout-canary" in tt:
                    await run_argo_rollout(task, context)
                elif "tf-module" in tt or "tf_module" in tt or "terraform-module" in tt:
                    await run_tf_module_generate(task, context)
                elif "rightsize" in tt or "right-size" in tt or "right_size" in tt:
                    await run_rightsize_report(task, context)
                elif "release-notes" in tt or "release_notes" in tt:
                    await run_release_notes(task, context)
                logger.info("release-deploy ext task completed", task_id=task.task_id, task_type=task_type)
                return

            from agents.release_deploy import (
                build_release_graph, build_deploy_graph,
                build_ephemeral_graph, build_tf_review_graph,
            )

            repository = context.get("repository", "benlbk/devops-agentic-teammates")

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

            elif "deploy" in task_type or "rollback" in task_type:
                deploy_agent = build_deploy_graph().compile()
                initial_state = {
                    "messages": [],
                    "task": task,
                    "repository": repository,
                    "environment": context.get("environment", "staging"),
                    "version": context.get("version", "latest"),
                    "strategy": context.get("strategy", "canary"),
                    "deploy_status": "",
                    "rollback_triggered": "rollback" in task_type,
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
                await _run_generic_task(task)

        elif agent_type == "plan-collaborate":
            from agents.plan_collaborate import plan_agent

            repository = context.get("repository", "benlbk/devops-agentic-teammates")

            # Ensure target repo exists before creating issues
            if repository != "benlbk/devops-agentic-teammates":
                try:
                    from shared.github_client import github_client as gh
                    owner, repo_name = repository.split("/")
                    await gh.ensure_repository(
                        owner=owner,
                        repo=repo_name,
                        description=f"Project repository for feature planning",
                    )
                    logger.info("Ensured repository exists", repository=repository)
                except Exception as e:
                    logger.warning("Failed to ensure repo exists", repository=repository, error=str(e))

            if "feature" in task_type:
                description = context.get("featureDescription", "") or context.get("description", "")
                if not description:
                    input_data = task.input_data or {}
                    payload = input_data.get("payload", {})
                    issue = payload.get("issue", {})
                    description = issue.get("body", issue.get("title", ""))

                if description:
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
                    logger.info("Feature planning completed", task_id=task.task_id)
                else:
                    await _fail_task(task, "Missing feature description")

            elif "sprint" in task_type:
                # Sprint planning — use LLM to suggest sprint scope
                await _run_sprint_planning(task, context, repository)

            elif "adr" in task_type:
                # ADR generation — auto-numbered, stored at docs/adr/, links back to PR
                from agents.plan_collaborate import adr_generator
                from shared.github_client import github_client as gh_client
                description = context.get("description", "") or context.get("decision", "")
                adr_context = context.get("context", "")
                pr_number = context.get("pr_number") or context.get("prNumber")
                pr_title = context.get("pr_title", "")
                pr_body = context.get("pr_body", "")
                changed_paths = context.get("changed_paths", [])

                # Enrich context from PR if invoked from webhook
                if pr_number and not description:
                    description = pr_title or f"PR #{pr_number}"
                    adr_context = (
                        f"PR Title: {pr_title}\n\n"
                        f"PR Description:\n{pr_body}\n\n"
                        f"Files changed (sample): {', '.join(changed_paths[:20])}"
                    )

                task.status = TaskStatus.IN_PROGRESS
                task.started_at = __import__("datetime").datetime.now(
                    __import__("datetime").timezone.utc
                ).isoformat()
                await state_manager.update_task(task)

                owner = repository.split("/")[0]
                repo_name = repository.split("/")[1]

                # Determine next ADR number from docs/adr/
                next_num = 1
                try:
                    existing = await gh_client.list_directory(owner=owner, repo=repo_name, path="docs/adr")
                    nums = []
                    for f in existing:
                        name = f.get("name", "")
                        m = __import__("re").match(r"^ADR-(\d{4})-", name)
                        if m:
                            nums.append(int(m.group(1)))
                    if nums:
                        next_num = max(nums) + 1
                except Exception as e:
                    logger.info("docs/adr/ not found or unreadable, starting at 0001", error=str(e))

                adr_content = await adr_generator.generate(adr_context, description)

                # Slugify and number
                slug = "".join(c for c in description.lower().replace(" ", "-") if c.isalnum() or c == "-")[:50].strip("-") or "decision"
                adr_id = f"ADR-{next_num:04d}"
                adr_filename = f"{adr_id}-{slug}.md"
                adr_path = f"docs/adr/{adr_filename}"

                # Prepend ID to content if not already present
                if not adr_content.lstrip().startswith("# ADR-"):
                    adr_content = f"# {adr_id}: {description}\n\n{adr_content}"
                else:
                    adr_content = adr_content.replace("# ADR-XXX", f"# {adr_id}", 1)

                # Append PR link if available
                if pr_number:
                    adr_content += f"\n\n---\n*Linked PR:* https://github.com/{repository}/pull/{pr_number}\n"

                adr_committed = False
                try:
                    await gh_client.create_or_update_file(
                        owner=owner, repo=repo_name,
                        path=adr_path,
                        content=adr_content,
                        message=f"docs(adr): {adr_id} {description[:60]}",
                        branch="main",
                    )
                    adr_committed = True
                except Exception as e:
                    logger.warning("Failed to commit ADR", error=str(e))

                # Comment on PR with ADR link
                if pr_number and adr_committed:
                    try:
                        adr_url = f"https://github.com/{repository}/blob/main/{adr_path}"
                        await gh_client.create_issue_comment(
                            owner=owner, repo=repo_name, issue_number=int(pr_number),
                            body=(
                                f"### Architecture Decision Recorded — {adr_id}\n\n"
                                f"This merge introduced architecturally significant changes. "
                                f"An ADR has been auto-generated:\n\n"
                                f"- **{adr_id}:** {description}\n"
                                f"- **File:** [`{adr_path}`]({adr_url})\n\n"
                                f"*Generated by DevOps Agentic Teammates — Plan & Collaborate Agent*"
                            ),
                        )
                    except Exception as e:
                        logger.warning("Failed to post ADR PR comment", error=str(e))

                task.status = TaskStatus.COMPLETED
                task.completed_at = __import__("datetime").datetime.now(
                    __import__("datetime").timezone.utc
                ).isoformat()
                task.output_data = {
                    "adr_id": adr_id,
                    "adr_path": adr_path,
                    "adr_committed": adr_committed,
                    "pr_number": pr_number,
                }
                await state_manager.update_task(task)
                logger.info("ADR generation completed", task_id=task.task_id, adr_id=adr_id, pr=pr_number)

            else:
                await _run_generic_task(task)

        elif agent_type == "operate-monitor":
            # FR-5.1/5.2/5.3/5.4 extension dispatch
            tt = task_type.lower()
            if any(k in tt for k in (
                "incident-correlate", "incident_correlate", "alert-correlate",
                "runbook",
                "slo-report", "slo_report",
                "hpa-pdb", "hpa_pdb", "pdb-tune",
                "dora-snapshot", "dora_snapshot", "dora-report",
            )):
                from agents.operate_monitor_ext import (
                    run_incident_correlate, run_runbook_execute,
                    run_slo_report, run_hpa_pdb_tune, run_dora_snapshot,
                )
                if "incident-correlate" in tt or "incident_correlate" in tt or "alert-correlate" in tt:
                    await run_incident_correlate(task, context)
                elif "runbook" in tt:
                    await run_runbook_execute(task, context)
                elif "slo-report" in tt or "slo_report" in tt:
                    await run_slo_report(task, context)
                elif "hpa-pdb" in tt or "hpa_pdb" in tt or "pdb-tune" in tt:
                    await run_hpa_pdb_tune(task, context)
                elif "dora-snapshot" in tt or "dora_snapshot" in tt or "dora-report" in tt:
                    await run_dora_snapshot(task, context)
                logger.info("operate-monitor ext task completed", task_id=task.task_id, task_type=task_type)
                return

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
                    "cost_data": {
                        "scope": context.get("scope", "all"),
                        "period": context.get("period", "last-30-days"),
                        **(context.get("costData") or {}),
                    },
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
                await _run_generic_task(task)

        else:
            await _run_generic_task(task)

    except Exception as e:
        logger.error("Agent task execution failed", error=str(e), task_id=task.task_id)
        task.status = TaskStatus.FAILED
        task.error = str(e)
        try:
            await state_manager.update_task(task)
        except Exception:
            pass
    finally:
        if AGENT_TASK_DURATION is not None:
            try:
                AGENT_TASK_DURATION.labels(
                    agent_type=task.agent_type, task_type=task.task_type
                ).observe(_time.monotonic() - _start_ts)
            except Exception:
                pass
        if AGENT_TASKS_COMPLETED is not None:
            try:
                AGENT_TASKS_COMPLETED.labels(
                    agent_type=task.agent_type,
                    task_type=task.task_type,
                    status=getattr(task.status, "value", str(task.status)),
                ).inc()
            except Exception:
                pass
        if AGENT_LLM_TOKENS is not None:
            try:
                from shared.llm import get_task_tokens, get_task_tokens_by_model
                _delta = get_task_tokens()
                if _delta > 0:
                    AGENT_LLM_TOKENS.labels(
                        agent_type=task.agent_type, task_type=task.task_type
                    ).inc(_delta)
                if AGENT_LLM_TOKENS_BY_MODEL is not None:
                    for _model, _n in get_task_tokens_by_model().items():
                        if _n > 0:
                            AGENT_LLM_TOKENS_BY_MODEL.labels(
                                agent_type=task.agent_type,
                                task_type=task.task_type,
                                model=_model,
                            ).inc(_n)
            except Exception:
                pass


@app.post("/webhooks/github")
async def github_webhook(request: Request, background_tasks: BackgroundTasks) -> dict[str, str]:
    """Receive and route GitHub webhook events with smart automation triggers."""
    import hmac
    import hashlib

    event_type = request.headers.get("X-GitHub-Event", "")
    body = await request.body()

    # Verify webhook signature if secret is configured
    webhook_secret = getattr(settings, "github_webhook_secret", None)
    if webhook_secret:
        signature = request.headers.get("X-Hub-Signature-256", "")
        expected = "sha256=" + hmac.new(
            webhook_secret.encode(), body, hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(signature, expected):
            logger.warning("Invalid webhook signature")
            return {"message": "Invalid signature"}

    payload = __import__("json").loads(body)
    action = payload.get("action", "")
    repo = payload.get("repository", {}).get("full_name", "unknown")
    sender = payload.get("sender", {}).get("login", "")

    logger.info("Received GitHub webhook", event_type=event_type, action=action, repo=repo, sender=sender)

    # --- Push events: RAG indexing only ---
    if event_type == "push":
        background_tasks.add_task(index_push_changes, repo, payload)
        return {"message": "Push event — RAG indexing only"}

    # --- Pull Request events: auto-review ---
    if event_type == "pull_request":
        pr = payload.get("pull_request", {})
        pr_number = pr.get("number")

        # PR merged: auto-trigger ADR if architecturally significant
        if action == "closed" and pr.get("merged"):
            pr_labels = {l.get("name", "").lower() for l in pr.get("labels", [])}
            pr_body = pr.get("body") or ""
            pr_title = pr.get("title") or ""
            adr_label_match = bool(pr_labels & {"adr", "architecture", "design"})
            adr_marker_match = "adr:" in pr_body.lower() or "[adr]" in pr_title.lower()

            # Path heuristic: did the PR touch infra/architecture-relevant paths?
            arch_paths = ("terraform/", "helm/", "infra/", "gitops/", "monitoring/", "agents/src/agents/", ".github/workflows/")
            changed_paths: list[str] = []
            path_match = False
            try:
                owner_l, repo_l = repo.split("/")
                files = await github_client.list_pull_request_files(owner=owner_l, repo=repo_l, pr_number=pr_number)
                changed_paths = [f.get("filename", "") for f in files]
                path_match = any(p.startswith(arch_paths) for p in changed_paths)
            except Exception as e:
                logger.warning("Failed to list PR files for ADR detection", error=str(e))

            if adr_label_match or adr_marker_match or path_match:
                adr_task = AgentTask(
                    agent_type="plan-collaborate",
                    task_type="adr-generation",
                    context={
                        "repository": repo,
                        "pr_number": pr_number,
                        "prNumber": pr_number,
                        "pr_title": pr_title,
                        "pr_body": pr_body,
                        "changed_paths": changed_paths,
                        "description": pr_title,
                        "context": (
                            f"Merged PR #{pr_number} touched architecturally significant areas. "
                            f"Trigger: {'label' if adr_label_match else 'marker' if adr_marker_match else 'paths'}."
                        ),
                        "githubEvent": event_type,
                        "action": action,
                    },
                    input_data={"payload": payload},
                    idempotency_key=f"{repo}/adr/{pr_number}/{pr.get('merge_commit_sha', '')}",
                )
                original_adr_id = adr_task.task_id
                adr_task = await state_manager.create_task(adr_task)
                if adr_task.task_id == original_adr_id:
                    background_tasks.add_task(execute_agent_task, adr_task)
                    logger.info("ADR auto-generation triggered", pr_number=pr_number, trigger="label" if adr_label_match else "marker" if adr_marker_match else "paths")
                    return {"message": f"ADR generation triggered for merged PR #{pr_number}"}
                return {"message": f"Duplicate ADR task for PR #{pr_number} — skipped"}
            logger.info("Merged PR not ADR-worthy", pr_number=pr_number)
            return {"message": f"Merged PR #{pr_number} — no ADR triggered"}

        # Only trigger on opened or synchronize (new commits pushed)
        if action not in ("opened", "synchronize"):
            logger.info("PR event ignored (action not reviewable)", action=action)
            return {"message": f"PR event '{action}' — no action needed"}

        # Skip draft PRs
        if pr.get("draft", False):
            logger.info("Skipping draft PR", pr_number=pr_number)
            return {"message": "Draft PR — skipping auto-review"}

        # Skip bot-authored PRs to avoid infinite loops
        if sender.endswith("[bot]") or sender in ("dependabot", "renovate"):
            logger.info("Skipping bot PR", sender=sender)
            return {"message": f"Bot PR from {sender} — skipping"}

        task = AgentTask(
            agent_type="code-build",
            task_type="code-review",
            context={
                "repository": repo,
                "prNumber": pr_number,
                "pr_number": pr_number,
                "githubEvent": event_type,
                "action": action,
                "sender": sender,
            },
            input_data={"payload": payload},
            idempotency_key=f"{repo}/pr-review/{pr_number}/{pr.get('head', {}).get('sha', '')}",
        )

        original_id = task.task_id
        task = await state_manager.create_task(task)
        if task.task_id != original_id:
            logger.info("Duplicate PR review skipped", pr_number=pr_number, existing_task=task.task_id)
            return {"message": f"Duplicate — PR #{pr_number} review already in progress"}

        await event_publisher.publish_task_requested(
            agent_type="code-build", task_type="code-review", context=task.context,
        )
        background_tasks.add_task(execute_agent_task, task)
        logger.info("Auto-review triggered for PR", pr_number=pr_number, repo=repo)

        # Also trigger security scan in parallel
        sec_task = AgentTask(
            agent_type="test-secure",
            task_type="security-scan",
            context={
                "repository": repo,
                "prNumber": pr_number,
                "pr_number": pr_number,
                "githubEvent": event_type,
                "action": action,
                "sender": sender,
            },
            input_data={},
            idempotency_key=f"{repo}/pr-security/{pr_number}/{pr.get('head', {}).get('sha', '')}",
        )
        sec_original_id = sec_task.task_id
        sec_task = await state_manager.create_task(sec_task)
        if sec_task.task_id == sec_original_id:
            background_tasks.add_task(execute_agent_task, sec_task)
            logger.info("Security scan triggered for PR", pr_number=pr_number, repo=repo)

        return {"message": f"Auto-review + security scan triggered for PR #{pr_number}"}

    # --- Issue events: auto-codegen or feature planning ---
    if event_type == "issues":
        issue = payload.get("issue", {})
        issue_number = issue.get("number")
        issue_labels = [l.get("name", "") for l in issue.get("labels", [])]

        # Trigger code generation when issue has 'codegen' label
        codegen_labels = {"codegen", "auto-codegen", "auto-implement"}
        should_codegen = bool(codegen_labels & set(issue_labels))

        if action in ("opened", "labeled") and should_codegen:
            # Skip if issue was opened by a bot
            issue_author = issue.get("user", {}).get("login", "")
            if issue_author.endswith("[bot]"):
                return {"message": "Bot-created issue — skipping"}

            task = AgentTask(
                agent_type="code-build",
                task_type="code-generation",
                context={
                    "repository": repo,
                    "issue_number": issue_number,
                    "issueNumber": issue_number,
                    "githubEvent": event_type,
                    "action": action,
                    "sender": sender,
                },
                input_data={"payload": payload},
                idempotency_key=f"{repo}/issue-codegen/{issue_number}",
            )

            original_id = task.task_id
            task = await state_manager.create_task(task)
            if task.task_id != original_id:
                logger.info("Duplicate codegen skipped", issue_number=issue_number, existing_task=task.task_id)
                return {"message": f"Duplicate — issue #{issue_number} codegen already in progress"}

            await event_publisher.publish_task_requested(
                agent_type="code-build", task_type="code-generation", context=task.context,
            )
            background_tasks.add_task(execute_agent_task, task)
            logger.info("Auto-codegen triggered for issue", issue_number=issue_number, repo=repo)
            return {"message": f"Auto-codegen triggered for issue #{issue_number}"}

        # Feature planning for issues with 'feature' or 'enhancement' labels
        planning_labels = {"feature", "enhancement", "agent-generated"}
        should_plan = bool(planning_labels & set(issue_labels))

        if action == "opened" and should_plan:
            task = AgentTask(
                agent_type="plan-collaborate",
                task_type="feature-planning",
                context={
                    "repository": repo,
                    "issue_number": issue_number,
                    "featureDescription": f"{issue.get('title', '')}\n\n{issue.get('body', '')}",
                    "githubEvent": event_type,
                    "action": action,
                    "sender": sender,
                },
                input_data={"payload": payload},
                idempotency_key=f"{repo}/issue-plan/{issue_number}",
            )

            original_id = task.task_id
            task = await state_manager.create_task(task)
            if task.task_id != original_id:
                logger.info("Duplicate planning skipped", issue_number=issue_number, existing_task=task.task_id)
                return {"message": f"Duplicate — issue #{issue_number} planning already in progress"}

            await event_publisher.publish_task_requested(
                agent_type="plan-collaborate", task_type="feature-planning", context=task.context,
            )
            background_tasks.add_task(execute_agent_task, task)
            logger.info("Feature planning triggered for issue", issue_number=issue_number, repo=repo)
            return {"message": f"Feature planning triggered for issue #{issue_number}"}

        logger.info("Issue event ignored (no matching labels/action)", action=action, labels=issue_labels)
        return {"message": f"Issue event '{action}' — no automation labels found"}

    # --- Fallback: generic routing for other event types ---
    routing_map = {
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
    task_type = f"{event_type}.{action}" if action else event_type
    pr_number = payload.get("pull_request", {}).get("number") or payload.get("number")

    task = AgentTask(
        agent_type=agent_type,
        task_type=task_type,
        context={
            "repository": repo,
            "prNumber": pr_number,
            "githubEvent": event_type,
            "action": action,
            "sender": sender,
        },
        input_data={"payload": payload},
        idempotency_key=f"{repo}/{event_type}/{action}/{pr_number}/{payload.get('after', '')}",
    )

    await state_manager.create_task(task)
    await event_publisher.publish_task_requested(
        agent_type=agent_type, task_type=task_type, context=task.context,
    )
    background_tasks.add_task(execute_agent_task, task)

    return {"message": f"Routed to {agent_type} agent"}


@app.get("/webhooks/github/info")
async def webhook_info() -> dict:
    """Return webhook automation config for diagnostics."""
    return {
        "webhook_url": "/orchestrator/webhooks/github",
        "supported_events": ["pull_request", "issues", "push", "issue_comment",
                             "check_run", "check_suite", "workflow_run",
                             "release", "deployment", "deployment_status", "status"],
        "automation_rules": [
            {
                "trigger": "pull_request.opened / pull_request.synchronize",
                "action": "Auto code review",
                "conditions": "Non-draft, non-bot author",
            },
            {
                "trigger": "issues.opened / issues.labeled",
                "action": "Auto code generation",
                "conditions": "Issue has label: codegen, auto-codegen, or auto-implement",
            },
            {
                "trigger": "issues.opened",
                "action": "Feature planning",
                "conditions": "Issue has label: feature, enhancement, or agent-generated",
            },
            {
                "trigger": "push",
                "action": "RAG indexing of changed files",
                "conditions": "Always (code files only)",
            },
        ],
        "signature_verification": bool(settings.github_webhook_secret),
    }


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
    from datetime import datetime, timezone, timedelta

    now = datetime.now(timezone.utc)
    all_completed = await state_manager.get_tasks_by_status(TaskStatus.COMPLETED)
    all_failed = await state_manager.get_tasks_by_status(TaskStatus.FAILED)

    # Deployment frequency: count merge/deploy tasks in last 24h
    day_ago = now - timedelta(hours=24)
    week_ago = now - timedelta(days=7)
    deploy_types = {"deploy", "release", "merge-approval"}
    deploy_tasks = [t for t in all_completed if any(dt in t.task_type for dt in deploy_types)]
    failed_deploys = [t for t in deploy_tasks if t.output_data and t.output_data.get("rollback")]

    recent_deploys_24h = [
        t for t in deploy_tasks
        if t.completed_at and datetime.fromisoformat(t.completed_at) > day_ago
    ]
    recent_deploys_7d = [
        t for t in deploy_tasks
        if t.completed_at and datetime.fromisoformat(t.completed_at) > week_ago
    ]
    deploy_freq = len(recent_deploys_7d) / 7.0 if recent_deploys_7d else len(recent_deploys_24h)

    # Lead time for changes: time from task created to completed (code-review + merge-approval cycle)
    review_tasks = [t for t in all_completed if t.task_type in ("code-review", "merge-approval")]
    lead_times: list[float] = []
    for t in review_tasks:
        if t.created_at and t.completed_at:
            try:
                created = datetime.fromisoformat(t.created_at)
                completed = datetime.fromisoformat(t.completed_at)
                lead_times.append((completed - created).total_seconds() / 3600.0)
            except (ValueError, TypeError):
                pass
    avg_lead_time = round(sum(lead_times) / len(lead_times), 1) if lead_times else 0

    # Change failure rate
    cfr = round(len(failed_deploys) / max(len(deploy_tasks), 1) * 100, 1)

    # Mean time to recovery: time from failure to next success
    all_tasks_sorted = sorted(
        all_completed + all_failed,
        key=lambda t: t.completed_at or t.started_at or "",
    )
    recovery_times: list[float] = []
    for i, t in enumerate(all_tasks_sorted):
        if t.status == TaskStatus.FAILED and t.completed_at:
            # Find next completed task of same type
            for later in all_tasks_sorted[i + 1:]:
                if later.agent_type == t.agent_type and later.status == TaskStatus.COMPLETED and later.completed_at:
                    try:
                        failed_at = datetime.fromisoformat(t.completed_at)
                        recovered_at = datetime.fromisoformat(later.completed_at)
                        recovery_times.append((recovered_at - failed_at).total_seconds() / 60.0)
                    except (ValueError, TypeError):
                        pass
                    break
    avg_mttr = round(sum(recovery_times) / len(recovery_times), 1) if recovery_times else 0

    # Performance level classification (DORA 2023 benchmarks)
    def classify_freq(v: float) -> str:
        if v >= 1: return "elite"
        if v >= 0.14: return "high"  # ~weekly
        if v >= 0.03: return "medium"  # ~monthly
        return "low"

    def classify_lead(v: float) -> str:
        if v < 1: return "elite"
        if v < 24: return "high"
        if v < 168: return "medium"
        return "low"

    def classify_cfr(v: float) -> str:
        if v <= 5: return "elite"
        if v <= 10: return "high"
        if v <= 15: return "medium"
        return "low"

    def classify_mttr(v: float) -> str:
        if v < 60: return "elite"
        if v < 1440: return "high"  # <1 day
        if v < 10080: return "medium"  # <1 week
        return "low"

    return {
        "deployment_frequency": {
            "value": round(deploy_freq, 2),
            "unit": "per_day",
            "level": classify_freq(deploy_freq),
            "total_7d": len(recent_deploys_7d),
        },
        "lead_time_for_changes": {
            "value": avg_lead_time,
            "unit": "hours",
            "level": classify_lead(avg_lead_time),
            "sample_size": len(lead_times),
        },
        "change_failure_rate": {
            "value": cfr,
            "unit": "percent",
            "level": classify_cfr(cfr),
            "failed": len(failed_deploys),
            "total": len(deploy_tasks),
        },
        "mean_time_to_recovery": {
            "value": avg_mttr,
            "unit": "minutes",
            "level": classify_mttr(avg_mttr),
            "sample_size": len(recovery_times),
        },
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


# ---- Dependency Management ----

class DependencyCheckRequest(BaseModel):
    repository: str
    auto_pr: bool = False


@app.post("/api/dependencies/check")
async def check_dependencies(request: DependencyCheckRequest, background_tasks: BackgroundTasks) -> dict[str, str]:
    """Trigger dependency vulnerability/update check for a repository."""
    task = AgentTask(
        agent_type="code-build",
        task_type="dependency-check",
        context={
            "repository": request.repository,
            "auto_pr": request.auto_pr,
        },
    )
    await state_manager.create_task(task)
    background_tasks.add_task(execute_agent_task, task)
    return {"message": f"Dependency check dispatched (task_id: {task.task_id})"}


# ---- Merge Coordinator ----

class MergeRequest(BaseModel):
    repository: str
    pr_number: int
    merge_method: str = "squash"  # squash, merge, rebase


@app.post("/api/merge")
async def merge_pr(request: MergeRequest) -> dict[str, Any]:
    """Coordinate merging a PR after all checks pass."""
    from shared.github_client import github_client

    try:
        owner, repo = request.repository.split("/")

        # Fetch PR details
        pr = await github_client.get_pull_request(
            owner=owner, repo=repo, pr_number=request.pr_number
        )

        # Validate mergeable
        if pr.get("mergeable") is False:
            return {"success": False, "error": "PR is not mergeable (conflicts or failing checks)"}

        # Merge
        result = await github_client.merge_pull_request(
            owner=owner,
            repo=repo,
            pr_number=request.pr_number,
            merge_method=request.merge_method,
            commit_title=f"{pr['title']} (#{pr['number']})",
        )

        logger.info("PR merged", repository=request.repository, pr=request.pr_number)
        return {"success": True, "sha": result.get("sha", ""), "message": result.get("message", "Merged")}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ---- Runbook Execution ----

class RunbookRequest(BaseModel):
    runbook_name: str
    context: dict[str, Any] = {}


@app.post("/api/runbooks/execute")
async def execute_runbook_endpoint(request: RunbookRequest) -> dict[str, Any]:
    """Execute an automated runbook."""
    from shared.runbooks import execute_runbook
    result = await execute_runbook(request.runbook_name, request.context)
    return result


@app.get("/api/runbooks")
async def list_runbooks() -> dict[str, Any]:
    """List available runbooks."""
    from shared.runbooks import RUNBOOK_REGISTRY
    return {
        "runbooks": [
            {"name": name, "description": fn.__doc__ or ""}
            for name, fn in RUNBOOK_REGISTRY.items()
        ]
    }


@app.get("/api/pipeline/{owner}/{repo}")
async def pipeline_status(owner: str, repo: str) -> dict[str, Any]:
    """Get pipeline status per issue for a repository."""
    import re as _re
    repository = f"{owner}/{repo}"
    tasks = await state_manager.get_tasks_by_repository(repository)

    # Index all tasks and build PR→issue mapping
    issues: dict[int, dict[str, Any]] = {}
    pr_to_issue: dict[int, int] = {}  # pr_number → issue_number
    review_tasks: list = []  # tasks with task_type == code-review
    fix_tasks: list = []  # fix-mode code-generation tasks

    for t in tasks:
        issue_num = t.context.get("issue_number")
        pr_num = t.context.get("pr_number")

        # Track code-generation tasks (they link issue → PR)
        if t.task_type == "code-generation" and not t.context.get("fix_mode") and issue_num:
            issue_num = int(issue_num)
            if issue_num not in issues:
                issues[issue_num] = {
                    "issue_number": issue_num,
                    "title": t.context.get("title", ""),
                    "stages": {},
                }
            # Extract PR number from output
            output_pr_url = (t.output_data or {}).get("pr_url", "")
            pr_match = _re.search(r'/pull/(\d+)', output_pr_url)
            if pr_match:
                linked_pr = int(pr_match.group(1))
                pr_to_issue[linked_pr] = issue_num

            existing = issues[issue_num]["stages"].get("code_generation")
            if not existing or (t.created_at > existing.get("created_at", "")):
                issues[issue_num]["stages"]["code_generation"] = {
                    "status": t.status.value,
                    "task_id": t.task_id,
                    "created_at": t.created_at,
                    "completed_at": t.completed_at,
                    "output": t.output_data or {},
                }

        elif t.task_type in ("sprint-planning", "feature-planning") and issue_num:
            issue_num = int(issue_num)
            if issue_num not in issues:
                issues[issue_num] = {"issue_number": issue_num, "title": "", "stages": {}}
            issues[issue_num]["stages"]["planning"] = {
                "status": t.status.value,
                "task_id": t.task_id,
                "created_at": t.created_at,
                "completed_at": t.completed_at,
                "output": {},
            }

        elif t.task_type == "code-review":
            review_tasks.append(t)

        elif t.task_type == "code-generation" and t.context.get("fix_mode"):
            fix_tasks.append(t)

    # Correlate review tasks via PR number
    for t in review_tasks:
        pr_num = t.context.get("pr_number")
        if pr_num and int(pr_num) in pr_to_issue:
            issue_num = pr_to_issue[int(pr_num)]
            existing = issues[issue_num]["stages"].get("review")
            if not existing or (t.created_at > existing.get("created_at", "")):
                issues[issue_num]["stages"]["review"] = {
                    "status": t.status.value,
                    "task_id": t.task_id,
                    "created_at": t.created_at,
                    "completed_at": t.completed_at,
                    "output": t.output_data or {},
                }

    # Correlate fix tasks via PR number
    for t in fix_tasks:
        pr_num = t.context.get("fix_pr_number") or t.context.get("pr_number")
        if pr_num and int(pr_num) in pr_to_issue:
            issue_num = pr_to_issue[int(pr_num)]
            existing = issues[issue_num]["stages"].get("fix")
            if not existing or (t.created_at > existing.get("created_at", "")):
                issues[issue_num]["stages"]["fix"] = {
                    "status": t.status.value,
                    "task_id": t.task_id,
                    "created_at": t.created_at,
                    "completed_at": t.completed_at,
                    "output": t.output_data or {},
                }

    # Enrich from GitHub: titles, states, and infer merged stage
    try:
        from shared.github_client import github_client
        gh_issues = await github_client.list_issues(owner, repo, state="all")
        for gi in gh_issues:
            if "pull_request" in gi:
                continue  # skip PRs returned by issues API
            num = gi["number"]
            labels = [l["name"] for l in gi.get("labels", [])]
            if num in issues:
                issues[num]["title"] = gi["title"]
                issues[num]["state"] = gi["state"]
                issues[num]["labels"] = labels
                # Infer planning completed if issue has agent-generated label
                if "agent-generated" in labels and "planning" not in issues[num]["stages"]:
                    issues[num]["stages"]["planning"] = {
                        "status": "completed",
                        "task_id": "",
                        "created_at": gi.get("created_at", ""),
                        "completed_at": gi.get("created_at", ""),
                        "output": {},
                    }
                # If issue is closed and has code_generation, infer merged
                if gi["state"] == "closed" and "code_generation" in issues[num]["stages"]:
                    issues[num]["stages"]["merge"] = {
                        "status": "completed",
                        "task_id": "",
                        "created_at": gi.get("closed_at", ""),
                        "completed_at": gi.get("closed_at", ""),
                        "output": {},
                    }
            elif gi["state"] == "open":
                planning_stage = {}
                if "agent-generated" in labels:
                    planning_stage = {"planning": {
                        "status": "completed", "task_id": "",
                        "created_at": gi.get("created_at", ""),
                        "completed_at": gi.get("created_at", ""), "output": {},
                    }}
                issues[num] = {
                    "issue_number": num,
                    "title": gi["title"],
                    "state": gi["state"],
                    "labels": labels,
                    "stages": planning_stage,
                }
    except Exception:
        pass

    # Sort by issue number
    sorted_issues = sorted(issues.values(), key=lambda x: x["issue_number"])
    return {"repository": repository, "issues": sorted_issues}


@app.get("/api/metrics/performance")
async def performance_metrics(hours: int = 168) -> dict[str, Any]:
    """Return agent performance metrics: tokens, success rates, cycle times."""
    from datetime import datetime, timezone, timedelta

    tasks = await state_manager.get_all_tasks_recent(hours=hours)

    # Per-agent aggregation
    agents: dict[str, dict[str, Any]] = {}
    total_tokens = 0
    total_completed = 0
    total_failed = 0
    cycle_times: list[float] = []

    for t in tasks:
        agent = t.agent_type
        if agent not in agents:
            agents[agent] = {
                "total": 0, "completed": 0, "failed": 0,
                "tokens_used": 0, "cycle_times_sec": [],
            }
        agents[agent]["total"] += 1
        agents[agent]["tokens_used"] += t.tokens_used
        total_tokens += t.tokens_used

        if t.status == TaskStatus.COMPLETED:
            agents[agent]["completed"] += 1
            total_completed += 1
            # Calculate cycle time
            if t.started_at and t.completed_at:
                try:
                    start = datetime.fromisoformat(t.started_at)
                    end = datetime.fromisoformat(t.completed_at)
                    duration = (end - start).total_seconds()
                    if 0 < duration < 3600:  # sanity: under 1 hour
                        agents[agent]["cycle_times_sec"].append(duration)
                        cycle_times.append(duration)
                except (ValueError, TypeError):
                    pass
        elif t.status == TaskStatus.FAILED:
            agents[agent]["failed"] += 1
            total_failed += 1

    # Build per-agent summary
    agent_summary = {}
    for name, data in agents.items():
        ct = data["cycle_times_sec"]
        agent_summary[name] = {
            "total_tasks": data["total"],
            "completed": data["completed"],
            "failed": data["failed"],
            "success_rate": round(data["completed"] / max(data["total"], 1) * 100, 1),
            "tokens_used": data["tokens_used"],
            "avg_cycle_time_sec": round(sum(ct) / len(ct), 1) if ct else 0,
            "p95_cycle_time_sec": round(sorted(ct)[int(len(ct) * 0.95)] if ct else 0, 1),
        }

    # By task type
    task_types: dict[str, dict[str, Any]] = {}
    for t in tasks:
        tt = t.task_type
        if tt not in task_types:
            task_types[tt] = {"total": 0, "completed": 0, "failed": 0, "tokens": 0, "cycle_times": []}
        task_types[tt]["total"] += 1
        task_types[tt]["tokens"] += t.tokens_used
        if t.status == TaskStatus.COMPLETED:
            task_types[tt]["completed"] += 1
            if t.started_at and t.completed_at:
                try:
                    dur = (datetime.fromisoformat(t.completed_at) - datetime.fromisoformat(t.started_at)).total_seconds()
                    if 0 < dur < 3600:
                        task_types[tt]["cycle_times"].append(dur)
                except (ValueError, TypeError):
                    pass
        elif t.status == TaskStatus.FAILED:
            task_types[tt]["failed"] += 1

    task_type_summary = {}
    for tt, data in task_types.items():
        ct = data["cycle_times"]
        task_type_summary[tt] = {
            "total": data["total"],
            "completed": data["completed"],
            "failed": data["failed"],
            "success_rate": round(data["completed"] / max(data["total"], 1) * 100, 1),
            "tokens_used": data["tokens"],
            "avg_cycle_time_sec": round(sum(ct) / len(ct), 1) if ct else 0,
        }

    # Timeline (recent tasks for chart)
    timeline = []
    for t in sorted(tasks, key=lambda x: x.created_at)[-50:]:
        timeline.append({
            "task_id": t.task_id,
            "agent_type": t.agent_type,
            "task_type": t.task_type,
            "status": t.status.value,
            "tokens_used": t.tokens_used,
            "created_at": t.created_at,
            "cycle_time_sec": round(
                (datetime.fromisoformat(t.completed_at) - datetime.fromisoformat(t.started_at)).total_seconds(), 1
            ) if t.started_at and t.completed_at else None,
        })

    return {
        "period_hours": hours,
        "total_tasks": len(tasks),
        "total_completed": total_completed,
        "total_failed": total_failed,
        "overall_success_rate": round(total_completed / max(total_completed + total_failed, 1) * 100, 1),
        "total_tokens_used": total_tokens,
        "avg_cycle_time_sec": round(sum(cycle_times) / len(cycle_times), 1) if cycle_times else 0,
        "agents": agent_summary,
        "task_types": task_type_summary,
        "timeline": timeline,
    }


# ---- Project Management API ----


class ProjectCreate(BaseModel):
    name: str
    description: str = ""
    repository: str
    repositories: list[str] = []
    default_branch: str = "main"
    environments: dict[str, Any] = {}
    config: dict[str, Any] = {}
    created_by: str = ""


class ProjectUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    repository: str | None = None
    repositories: list[str] | None = None
    default_branch: str | None = None
    environments: dict[str, Any] | None = None
    config: dict[str, Any] | None = None


@app.post("/api/projects")
async def create_project(body: ProjectCreate) -> dict[str, Any]:
    """Create a new project."""
    # Auto-populate repositories list with primary repo if not provided
    repos = body.repositories if body.repositories else [body.repository]
    if body.repository not in repos:
        repos.insert(0, body.repository)
    project = Project(
        name=body.name,
        description=body.description,
        repository=body.repository,
        repositories=repos,
        default_branch=body.default_branch,
        environments=body.environments,
        config=body.config,
        created_by=body.created_by,
    )
    created = await state_manager.create_project(project)
    return {"project": created.model_dump()}


@app.get("/api/projects")
async def list_projects() -> dict[str, Any]:
    """List all projects."""
    projects = await state_manager.list_projects()
    return {"projects": [p.model_dump() for p in projects]}


@app.get("/api/projects/{project_id}")
async def get_project(project_id: str) -> dict[str, Any]:
    """Get a project by ID."""
    project = await state_manager.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return {"project": project.model_dump()}


@app.put("/api/projects/{project_id}")
async def update_project(project_id: str, body: ProjectUpdate) -> dict[str, Any]:
    """Update an existing project."""
    project = await state_manager.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    if body.name is not None:
        project.name = body.name
    if body.description is not None:
        project.description = body.description
    if body.repository is not None:
        project.repository = body.repository
    if body.repositories is not None:
        project.repositories = body.repositories
    if body.default_branch is not None:
        project.default_branch = body.default_branch
    if body.environments is not None:
        project.environments = body.environments
    if body.config is not None:
        project.config = body.config

    updated = await state_manager.update_project(project)
    return {"project": updated.model_dump()}


@app.delete("/api/projects/{project_id}")
async def delete_project(project_id: str) -> dict[str, str]:
    """Delete a project."""
    project = await state_manager.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    await state_manager.delete_project(project_id)
    return {"status": "deleted"}


# ---- Project Repository Management ----

class RepoAddRequest(BaseModel):
    repository: str  # e.g. "owner/repo"


@app.post("/api/projects/{project_id}/repos")
async def add_project_repo(project_id: str, body: RepoAddRequest) -> dict[str, Any]:
    """Add a repository to the project."""
    project = await state_manager.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Ensure primary repo is in list (backward compat for pre-multi-repo projects)
    if not project.repositories and project.repository:
        project.repositories = [project.repository]

    repo = body.repository.strip()
    if "/" not in repo:
        raise HTTPException(status_code=400, detail="Invalid repository format. Use owner/repo")
    if repo in project.repositories:
        raise HTTPException(status_code=409, detail="Repository already added to this project")

    project.repositories.append(repo)
    await state_manager.update_project(project)
    return {"status": "added", "repositories": project.repositories}


@app.delete("/api/projects/{project_id}/repos/{owner}/{repo}")
async def remove_project_repo(project_id: str, owner: str, repo: str) -> dict[str, Any]:
    """Remove a repository from the project (also removes its webhook)."""
    from shared.github_client import github_client

    project = await state_manager.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    full_repo = f"{owner}/{repo}"
    if full_repo not in project.repositories:
        raise HTTPException(status_code=404, detail="Repository not found in this project")
    if full_repo == project.repository and len(project.repositories) <= 1:
        raise HTTPException(status_code=400, detail="Cannot remove the primary repository")

    # Remove webhook if registered
    webhooks = project.config.get("webhooks", {})
    hook_id = webhooks.get(full_repo)
    if hook_id:
        try:
            await github_client.delete_webhook(owner, repo, int(hook_id))
        except Exception as e:
            logger.warning("Failed to delete webhook during repo removal", error=str(e))
        webhooks.pop(full_repo, None)
        project.config["webhooks"] = webhooks

    project.repositories.remove(full_repo)
    # If removing primary, update primary to first remaining
    if full_repo == project.repository and project.repositories:
        project.repository = project.repositories[0]
    await state_manager.update_project(project)
    return {"status": "removed", "repositories": project.repositories}


# ---- Project Webhook Registration (multi-repo) ----

@app.post("/api/projects/{project_id}/webhook")
async def register_project_webhook(project_id: str, body: RepoAddRequest | None = None) -> dict[str, Any]:
    """Register a GitHub webhook for a specific repo (or the primary repo)."""
    from shared.github_client import github_client

    project = await state_manager.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Determine target repo
    target_repo = body.repository.strip() if body and body.repository else project.repository
    if "/" not in target_repo:
        raise HTTPException(status_code=400, detail="Invalid repository format. Use owner/repo")

    owner, repo_name = target_repo.split("/", 1)
    webhook_url = f"https://devops.13.215.130.82.nip.io/orchestrator/webhooks/github"
    secret = settings.github_webhook_secret or ""

    # Check if webhook already registered for this repo
    webhooks = project.config.get("webhooks", {})
    # Migrate legacy webhook_id into webhooks dict
    if not webhooks and project.config.get("webhook_id"):
        webhooks = {project.repository: project.config["webhook_id"]}
    if target_repo in webhooks:
        raise HTTPException(status_code=409, detail=f"Webhook already registered for {target_repo}")

    try:
        # Auto-create repo if it doesn't exist on GitHub
        await github_client.ensure_repository(owner=owner, repo=repo_name)

        hook = await github_client.create_webhook(
            owner=owner,
            repo=repo_name,
            webhook_url=webhook_url,
            secret=secret,
        )
        webhooks[target_repo] = hook["id"]
        project.config["webhooks"] = webhooks
        # Backward compat: keep legacy fields for primary repo
        if target_repo == project.repository:
            project.config["webhook_id"] = hook["id"]
            project.config["webhook_active"] = True
        await state_manager.update_project(project)
        return {"status": "registered", "webhook_id": hook["id"], "webhook_url": webhook_url, "repository": target_repo}
    except Exception as e:
        logger.error("Failed to register webhook", error=str(e), repo=target_repo)
        raise HTTPException(status_code=500, detail=f"Failed to register webhook: {str(e)}")


@app.get("/api/projects/{project_id}/webhook")
async def get_project_webhook(project_id: str) -> dict[str, Any]:
    """Get webhook status for all repos in the project."""
    project = await state_manager.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    webhooks = project.config.get("webhooks", {})

    # Backward compat: if no webhooks dict but legacy webhook_id exists, migrate
    if not webhooks and project.config.get("webhook_id"):
        webhooks = {project.repository: project.config["webhook_id"]}

    repo_statuses = []
    all_repos = project.repositories if project.repositories else [project.repository]
    # Ensure primary repo always appears
    if project.repository and project.repository not in all_repos:
        all_repos = [project.repository] + all_repos
    for repo in all_repos:
        hook_id = webhooks.get(repo)
        repo_statuses.append({
            "repository": repo,
            "registered": hook_id is not None,
            "webhook_id": hook_id,
        })

    return {"repositories": repo_statuses}


@app.delete("/api/projects/{project_id}/webhook")
async def remove_project_webhook(project_id: str, body: RepoAddRequest | None = None) -> dict[str, str]:
    """Remove the webhook from a specific repo (or the primary repo)."""
    from shared.github_client import github_client

    project = await state_manager.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    target_repo = body.repository.strip() if body and body.repository else project.repository
    if "/" not in target_repo:
        raise HTTPException(status_code=400, detail="Invalid repository format")

    webhooks = project.config.get("webhooks", {})
    # Backward compat
    if not webhooks and project.config.get("webhook_id"):
        webhooks = {project.repository: project.config["webhook_id"]}

    hook_id = webhooks.get(target_repo)
    if not hook_id:
        raise HTTPException(status_code=404, detail=f"No webhook registered for {target_repo}")

    owner, repo_name = target_repo.split("/", 1)
    try:
        await github_client.delete_webhook(owner, repo_name, int(hook_id))
    except Exception as e:
        logger.warning("Failed to delete webhook from GitHub (may already be removed)", error=str(e))

    webhooks.pop(target_repo, None)
    project.config["webhooks"] = webhooks
    # Clear legacy fields if primary
    if target_repo == project.repository:
        project.config.pop("webhook_id", None)
        project.config.pop("webhook_active", None)
    await state_manager.update_project(project)
    return {"status": "removed"}


def main() -> None:
    uvicorn.run(
        "orchestrator.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=settings.environment == "dev",
    )


if __name__ == "__main__":
    main()
