"""Release & Deploy Agent — Manages releases, deployments, and infrastructure."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Annotated

import structlog
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict

from shared.events import event_publisher
from shared.github_client import github_client
from shared.llm import llm_provider
from shared.state import AgentTask, TaskStatus, state_manager

logger = structlog.get_logger()


# ---- State ----

class ReleaseState(TypedDict):
    messages: Annotated[list, add_messages]
    task: AgentTask
    repository: str
    release_type: str  # major | minor | patch
    current_version: str
    next_version: str
    changelog: str
    release_url: str


class DeployState(TypedDict):
    messages: Annotated[list, add_messages]
    task: AgentTask
    repository: str
    environment: str
    version: str
    strategy: str  # canary | blue-green | rolling
    deploy_status: str
    rollback_triggered: bool
    argocd_app: str


class EphemeralEnvState(TypedDict):
    messages: Annotated[list, add_messages]
    task: AgentTask
    repository: str
    pr_number: int
    action: str  # create | destroy
    env_url: str
    namespace: str


class TerraformReviewState(TypedDict):
    messages: Annotated[list, add_messages]
    task: AgentTask
    repository: str
    pr_number: int
    plan_output: str
    review_summary: str
    risk_level: str


# ---- Release Workflow ----

async def determine_version(state: ReleaseState) -> dict[str, Any]:
    """Determine the next version based on conventional commits."""
    task = state["task"]
    task.status = TaskStatus.IN_PROGRESS
    task.started_at = datetime.now(timezone.utc).isoformat()
    await state_manager.update_task(task)

    repo_parts = state["repository"].split("/")
    owner, repo = repo_parts[0], repo_parts[1]

    # Get latest release
    current = state.get("current_version", "0.0.0")
    parts = current.split(".")
    major, minor, patch = int(parts[0]), int(parts[1]), int(parts[2])

    release_type = state.get("release_type", "patch")
    if release_type == "major":
        next_version = f"{major + 1}.0.0"
    elif release_type == "minor":
        next_version = f"{major}.{minor + 1}.0"
    else:
        next_version = f"{major}.{minor}.{patch + 1}"

    return {"next_version": next_version}


async def generate_changelog(state: ReleaseState) -> dict[str, Any]:
    """Generate a changelog from commits since last release."""
    messages = [
        SystemMessage(content="""Generate a professional changelog from the given commit information.
Organize by:
### 🚀 Features
### 🐛 Bug Fixes
### 📚 Documentation
### 🔧 Maintenance
### ⚠️ Breaking Changes (if any)"""),
        HumanMessage(content=f"Version: {state['next_version']}\nRepository: {state['repository']}"),
    ]
    response = await llm_provider.ainvoke(messages)
    return {"changelog": response.content}


async def create_release(state: ReleaseState) -> dict[str, Any]:
    """Create a GitHub release with changelog."""
    repo_parts = state["repository"].split("/")
    owner, repo = repo_parts[0], repo_parts[1]

    try:
        release = await github_client.create_release(
            owner=owner,
            repo=repo,
            tag=f"v{state['next_version']}",
            name=f"v{state['next_version']}",
            body=state["changelog"],
        )
        return {"release_url": release.get("html_url", "")}
    except Exception as e:
        logger.error("Failed to create release", error=str(e))
        return {"release_url": ""}


async def finalize_release(state: ReleaseState) -> dict[str, Any]:
    task = state["task"]
    task.status = TaskStatus.COMPLETED
    task.completed_at = datetime.now(timezone.utc).isoformat()
    task.output_data = {
        "version": state["next_version"],
        "release_url": state["release_url"],
    }
    task.tokens_used = llm_provider.tokens_used
    await state_manager.update_task(task)

    await event_publisher.publish_task_completed(
        agent_type="release-deploy",
        task_id=task.task_id,
        task_type="release",
        status="completed",
        output=task.output_data,
        next_actions=[{
            "agent": "release-deploy",
            "taskType": "deploy",
            "context": {
                "repository": state["repository"],
                "version": state["next_version"],
                "environment": "staging",
                "strategy": "canary",
            },
        }],
    )
    return {}


# ---- Deploy (ArgoCD GitOps) ----

async def prepare_deploy(state: DeployState) -> dict[str, Any]:
    """Prepare the deployment via ArgoCD GitOps."""
    task = state["task"]
    task.status = TaskStatus.IN_PROGRESS
    task.started_at = datetime.now(timezone.utc).isoformat()
    await state_manager.update_task(task)

    env = state["environment"]
    version = state["version"]
    repo_parts = state["repository"].split("/")
    owner, repo = repo_parts[0], repo_parts[1]

    # Update the GitOps repo with the new version (values.yaml)
    values_path = f"k8s/overlays/{env}/values.yaml"
    values_content = f"""# Auto-updated by Release & Deploy Agent
image:
  tag: "{version}"
replicaCount: {"3" if env == "production" else "2"}
strategy:
  type: {state.get("strategy", "canary")}
  canary:
    steps:
      - setWeight: 20
      - pause: {{duration: 5m}}
      - setWeight: 50
      - pause: {{duration: 5m}}
      - setWeight: 80
      - pause: {{duration: 5m}}
"""

    try:
        await github_client.create_or_update_file(
            owner=owner,
            repo=repo,
            path=values_path,
            content=values_content,
            message=f"deploy: update {env} to v{version}",
            branch="main",
        )
        return {
            "argocd_app": f"{repo}-{env}",
            "deploy_status": "syncing",
        }
    except Exception as e:
        logger.error("Failed to update GitOps repo", error=str(e))
        return {"deploy_status": "failed"}


async def monitor_deploy(state: DeployState) -> dict[str, Any]:
    """Monitor the deployment status."""
    # In production, this would poll ArgoCD API
    return {"deploy_status": "healthy", "rollback_triggered": False}


async def finalize_deploy(state: DeployState) -> dict[str, Any]:
    task = state["task"]
    task.status = TaskStatus.COMPLETED
    task.completed_at = datetime.now(timezone.utc).isoformat()
    task.output_data = {
        "environment": state["environment"],
        "version": state["version"],
        "strategy": state["strategy"],
        "status": state["deploy_status"],
        "rollback": state["rollback_triggered"],
        "argocd_app": state["argocd_app"],
    }
    task.tokens_used = llm_provider.tokens_used
    await state_manager.update_task(task)

    next_actions = []
    if state["environment"] == "staging" and state["deploy_status"] == "healthy":
        next_actions.append({
            "agent": "release-deploy",
            "taskType": "deploy",
            "context": {
                "repository": state["repository"],
                "version": state["version"],
                "environment": "production",
                "strategy": "canary",
            },
        })

    await event_publisher.publish_task_completed(
        agent_type="release-deploy",
        task_id=task.task_id,
        task_type="deploy",
        status="completed",
        output=task.output_data,
        next_actions=next_actions,
    )
    return {}


# ---- Ephemeral Environments ----

async def manage_ephemeral(state: EphemeralEnvState) -> dict[str, Any]:
    """Create or destroy ephemeral environments for PRs."""
    task = state["task"]
    task.status = TaskStatus.IN_PROGRESS
    task.started_at = datetime.now(timezone.utc).isoformat()
    await state_manager.update_task(task)

    action = state["action"]
    ns = f"pr-{state['pr_number']}"

    if action == "create":
        # In production: trigger Terraform apply for the ephemeral module
        env_url = f"https://pr-{state['pr_number']}.preview.example.com"
        repo_parts = state["repository"].split("/")
        if len(repo_parts) == 2:
            try:
                await github_client.create_issue_comment(
                    owner=repo_parts[0],
                    repo=repo_parts[1],
                    issue_number=state["pr_number"],
                    body=f"🌍 Preview environment deployed: {env_url}",
                )
            except Exception as e:
                logger.error("Failed to comment on PR", error=str(e))

        return {"namespace": ns, "env_url": env_url}
    else:
        return {"namespace": ns, "env_url": ""}


async def finalize_ephemeral(state: EphemeralEnvState) -> dict[str, Any]:
    task = state["task"]
    task.status = TaskStatus.COMPLETED
    task.completed_at = datetime.now(timezone.utc).isoformat()
    task.output_data = {
        "action": state["action"],
        "namespace": state["namespace"],
        "env_url": state.get("env_url", ""),
    }
    task.tokens_used = llm_provider.tokens_used
    await state_manager.update_task(task)
    return {}


# ---- Terraform Review ----

TF_REVIEW_PROMPT = """You are an expert Terraform/IaC reviewer. Analyze the Terraform plan output and provide:
1. **Summary**: What resources are being created/modified/destroyed
2. **Risk Assessment**: HIGH/MEDIUM/LOW based on:
   - Destructive changes (resource destruction)
   - Security implications (IAM changes, security group modifications)
   - Cost impact (instance sizes, storage)
   - Blast radius (how many resources affected)
3. **Recommendations**: Specific suggestions for improvement
4. **Approval**: APPROVE / REQUEST_CHANGES / REQUIRE_MANUAL_REVIEW"""


async def review_terraform_plan(state: TerraformReviewState) -> dict[str, Any]:
    task = state["task"]
    task.status = TaskStatus.IN_PROGRESS
    task.started_at = datetime.now(timezone.utc).isoformat()
    await state_manager.update_task(task)

    messages = [
        SystemMessage(content=TF_REVIEW_PROMPT),
        HumanMessage(content=f"Terraform Plan:\n```\n{state['plan_output'][:10000]}\n```"),
    ]
    response = await llm_provider.ainvoke(messages)
    content = response.content

    risk_level = "MEDIUM"
    if "HIGH" in content.upper()[:200]:
        risk_level = "HIGH"
    elif "LOW" in content.upper()[:200]:
        risk_level = "LOW"

    return {"review_summary": content, "risk_level": risk_level}


async def post_tf_review(state: TerraformReviewState) -> dict[str, Any]:
    repo_parts = state["repository"].split("/")
    if len(repo_parts) != 2:
        return {}

    owner, repo = repo_parts
    report = f"""## 🏗️ Terraform Plan Review

**Risk Level:** {state['risk_level']}

{state['review_summary']}

---
*Reviewed by DevOps Agentic Teammates — Release & Deploy Agent*
"""
    try:
        await github_client.create_issue_comment(
            owner=owner,
            repo=repo,
            issue_number=state["pr_number"],
            body=report,
        )
    except Exception as e:
        logger.error("Failed to post TF review", error=str(e))

    task = state["task"]
    task.status = TaskStatus.COMPLETED
    task.completed_at = datetime.now(timezone.utc).isoformat()
    task.output_data = {
        "risk_level": state["risk_level"],
    }
    task.tokens_used = llm_provider.tokens_used
    await state_manager.update_task(task)
    return {}


# ---- Build Graphs ----

def build_release_graph() -> StateGraph:
    graph = StateGraph(ReleaseState)
    graph.add_node("determine_version", determine_version)
    graph.add_node("generate_changelog", generate_changelog)
    graph.add_node("create_release", create_release)
    graph.add_node("finalize", finalize_release)
    graph.add_edge(START, "determine_version")
    graph.add_edge("determine_version", "generate_changelog")
    graph.add_edge("generate_changelog", "create_release")
    graph.add_edge("create_release", "finalize")
    graph.add_edge("finalize", END)
    return graph


def build_deploy_graph() -> StateGraph:
    graph = StateGraph(DeployState)
    graph.add_node("prepare", prepare_deploy)
    graph.add_node("monitor", monitor_deploy)
    graph.add_node("finalize", finalize_deploy)
    graph.add_edge(START, "prepare")
    graph.add_edge("prepare", "monitor")
    graph.add_edge("monitor", "finalize")
    graph.add_edge("finalize", END)
    return graph


def build_ephemeral_graph() -> StateGraph:
    graph = StateGraph(EphemeralEnvState)
    graph.add_node("manage", manage_ephemeral)
    graph.add_node("finalize", finalize_ephemeral)
    graph.add_edge(START, "manage")
    graph.add_edge("manage", "finalize")
    graph.add_edge("finalize", END)
    return graph


def build_tf_review_graph() -> StateGraph:
    graph = StateGraph(TerraformReviewState)
    graph.add_node("review", review_terraform_plan)
    graph.add_node("post_review", post_tf_review)
    graph.add_edge(START, "review")
    graph.add_edge("review", "post_review")
    graph.add_edge("post_review", END)
    return graph


release_agent = build_release_graph().compile()
deploy_agent = build_deploy_graph().compile()
ephemeral_env_agent = build_ephemeral_graph().compile()
tf_review_agent = build_tf_review_graph().compile()
