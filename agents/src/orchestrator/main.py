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
    try:
        from shared.github_client import github_client
        owner, repo = issues_repo.split("/")
        issues = await github_client.list_issues(owner=owner, repo=repo, labels=["agent-generated"], state="open")
        if not issues:
            # Try without label filter for new repos
            issues = await github_client.list_issues(owner=owner, repo=repo, state="open", per_page=30)
        for issue in issues[:30]:  # Limit to 30 issues
            issues_text += f"- #{issue.get('number', '?')}: {issue.get('title', '')} (labels: {', '.join(l.get('name', '') for l in issue.get('labels', []))})\n"
    except Exception as e:
        logger.warning("Failed to fetch issues for sprint planning", error=str(e), repo=issues_repo)
        issues_text = "Could not fetch issues — provide general guidance based on sprint goal."

    messages = [
        SystemMessage(content="""You are an agile coach helping plan a sprint. Given the sprint goal, team capacity, 
and available backlog issues, suggest which issues to include in the sprint.
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
    task.output_data = output
    task.tokens_used = llm_provider.tokens_used
    await state_manager.update_task(task)
    logger.info("Sprint planning completed", task_id=task.task_id)

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

            else:
                await _run_generic_task(task)

        elif agent_type == "test-secure":
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
                # ADR generation
                from agents.plan_collaborate import adr_generator
                from shared.github_client import github_client as gh_client
                description = context.get("description", "") or context.get("decision", "")
                adr_context = context.get("context", "")

                task.status = TaskStatus.IN_PROGRESS
                task.started_at = __import__("datetime").datetime.now(
                    __import__("datetime").timezone.utc
                ).isoformat()
                await state_manager.update_task(task)

                adr_content = await adr_generator.generate(adr_context, description)

                # Commit ADR to repo
                try:
                    slug = description[:40].lower().replace(" ", "-")
                    await gh_client.create_or_update_file(
                        owner=repository.split("/")[0],
                        repo=repository.split("/")[1],
                        path=f".bk/adrs/{slug}.md",
                        content=adr_content,
                        message=f"docs: add ADR for {slug}",
                        branch="main",
                    )
                except Exception as e:
                    logger.warning("Failed to commit ADR", error=str(e))

                task.status = TaskStatus.COMPLETED
                task.completed_at = __import__("datetime").datetime.now(
                    __import__("datetime").timezone.utc
                ).isoformat()
                task.output_data = {"adr_generated": True}
                await state_manager.update_task(task)
                logger.info("ADR generation completed", task_id=task.task_id)

            else:
                await _run_generic_task(task)

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


def main() -> None:
    uvicorn.run(
        "orchestrator.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=settings.environment == "dev",
    )


if __name__ == "__main__":
    main()
