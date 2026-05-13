"""Code & Build Agent — Generates code, reviews PRs, and optimizes builds."""

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
from shared.rag import rag_pipeline
from shared.state import AgentTask, TaskStatus, state_manager

logger = structlog.get_logger()


# ---- State ----

class CodeReviewState(TypedDict):
    messages: Annotated[list, add_messages]
    task: AgentTask
    repository: str
    pr_number: int
    diff: str
    review_comments: list[dict[str, Any]]
    review_summary: str
    recommendation: str


class CodeGenState(TypedDict):
    messages: Annotated[list, add_messages]
    task: AgentTask
    repository: str
    spec: dict[str, Any]
    codebase_context: list[dict[str, Any]]
    generated_files: list[dict[str, str]]
    branch_name: str
    pr_url: str


# ---- Code Review Workflow ----

REVIEW_SYSTEM_PROMPT = """You are an expert code reviewer for a modern web application stack:
- Frontend: Next.js 14+ with TypeScript, React, Tailwind CSS
- Backend: ASP.NET Core 8+ with C#, Entity Framework Core, PostgreSQL
- Infrastructure: Terraform, Kubernetes, Helm

Review the PR diff for:
1. **Bugs**: Logic errors, null references, race conditions, off-by-one errors
2. **Security**: SQL injection, XSS, CSRF, hardcoded secrets, insecure defaults
3. **Performance**: N+1 queries, unnecessary re-renders, missing indexes, memory leaks
4. **Style**: Naming conventions, code organization, dead code, complexity
5. **Testing**: Missing test coverage, untested edge cases

For each issue found, return a JSON array of review comments:
[{
  "path": "file/path.ts",
  "line": 42,
  "severity": "error|warning|info",
  "category": "bug|security|performance|style|testing",
  "body": "Detailed explanation with suggested fix"
}]

After comments, provide a JSON summary:
{
  "recommendation": "APPROVE|REQUEST_CHANGES|COMMENT",
  "summary": "Overall review summary",
  "stats": {"errors": 0, "warnings": 0, "info": 0}
}

Return comments and summary separated by ===SUMMARY==="""


async def fetch_pr_diff(state: CodeReviewState) -> dict[str, Any]:
    """Fetch the PR diff from GitHub."""
    task = state["task"]
    task.status = TaskStatus.IN_PROGRESS
    task.started_at = datetime.now(timezone.utc).isoformat()
    await state_manager.update_task(task)

    repo_parts = state["repository"].split("/")
    owner, repo = repo_parts[0], repo_parts[1]

    diff = await github_client.get_pr_diff(
        owner=owner, repo=repo, pr_number=state["pr_number"]
    )
    return {"diff": diff}


async def review_code(state: CodeReviewState) -> dict[str, Any]:
    """Perform AI code review on the diff."""
    messages = [
        SystemMessage(content=REVIEW_SYSTEM_PROMPT),
        HumanMessage(content=f"Review this PR diff:\n\n```diff\n{state['diff'][:15000]}\n```"),
    ]

    response = await llm_provider.ainvoke(messages)
    content = response.content

    comments = []
    summary = ""
    recommendation = "COMMENT"

    if "===SUMMARY===" in content:
        parts = content.split("===SUMMARY===")
        try:
            comments = json.loads(parts[0].strip().strip("```json").strip("```"))
        except json.JSONDecodeError:
            comments = []
        try:
            summary_data = json.loads(parts[1].strip().strip("```json").strip("```"))
            summary = summary_data.get("summary", "")
            recommendation = summary_data.get("recommendation", "COMMENT")
        except json.JSONDecodeError:
            summary = parts[1].strip()

    return {
        "review_comments": comments,
        "review_summary": summary,
        "recommendation": recommendation,
    }


async def post_review(state: CodeReviewState) -> dict[str, Any]:
    """Post review comments and summary to the PR."""
    repo_parts = state["repository"].split("/")
    owner, repo = repo_parts[0], repo_parts[1]

    # Post individual inline comments would require commit SHA
    # For now, post a summary review
    review_body = f"""## 🤖 AI Code Review

{state['review_summary']}

### Findings
| Severity | Category | File | Line | Issue |
|---|---|---|---|---|
"""
    for comment in state["review_comments"]:
        review_body += (
            f"| {comment.get('severity', 'info')} "
            f"| {comment.get('category', 'style')} "
            f"| `{comment.get('path', '')}` "
            f"| L{comment.get('line', 0)} "
            f"| {comment.get('body', '')[:100]} |\n"
        )

    review_body += f"""
### Recommendation: **{state['recommendation']}**

---
*Reviewed by DevOps Agentic Teammates — Code & Build Agent*
"""

    try:
        await github_client.create_pr_review(
            owner=owner,
            repo=repo,
            pr_number=state["pr_number"],
            body=review_body,
            event=state["recommendation"],
        )
    except Exception as e:
        logger.error("Failed to post review", error=str(e))
        # Fall back to a comment
        await github_client.create_issue_comment(
            owner=owner,
            repo=repo,
            issue_number=state["pr_number"],
            body=review_body,
        )

    return {"messages": [HumanMessage(content="Review posted")]}


async def finalize_review(state: CodeReviewState) -> dict[str, Any]:
    """Finalize the code review task."""
    task = state["task"]
    task.status = TaskStatus.COMPLETED
    task.completed_at = datetime.now(timezone.utc).isoformat()
    task.output_data = {
        "reviewComments": len(state["review_comments"]),
        "recommendation": state["recommendation"],
        "tokensUsed": llm_provider.tokens_used,
    }
    task.tokens_used = llm_provider.tokens_used
    await state_manager.update_task(task)

    next_actions = []
    if state["recommendation"] == "APPROVE":
        next_actions.append({
            "agent": "test-secure",
            "taskType": "generate-tests",
            "context": {"repository": state["repository"], "prNumber": state["pr_number"]},
        })

    await event_publisher.publish_task_completed(
        agent_type="code-build",
        task_id=task.task_id,
        task_type="code-review",
        status="completed",
        output=task.output_data,
        next_actions=next_actions,
    )
    return {}


# ---- Code Generation Workflow ----

NEXTJS_SYSTEM_PROMPT = """You are an expert Next.js/React/TypeScript developer. Generate production-quality code
following these conventions:
- Use Next.js App Router (app/ directory)
- TypeScript strict mode, proper types (no `any`)
- Tailwind CSS for styling
- Server Components by default, 'use client' only when needed
- Follow React best practices (proper hooks, memoization where needed)
- Include proper error handling and loading states

Return code as JSON: [{"path": "src/...", "content": "file content"}]"""

DOTNET_SYSTEM_PROMPT = """You are an expert ASP.NET Core/C# developer. Generate production-quality code
following clean architecture:
- ASP.NET Core 8 minimal APIs or controllers
- Entity Framework Core with PostgreSQL
- Repository pattern for data access
- DTOs for API contracts (no exposing entities directly)
- Proper dependency injection
- Input validation with FluentValidation or DataAnnotations
- Proper async/await patterns

Return code as JSON: [{"path": "src/...", "content": "file content"}]"""


async def retrieve_context(state: CodeGenState) -> dict[str, Any]:
    """Retrieve relevant codebase context via RAG."""
    task = state["task"]
    task.status = TaskStatus.IN_PROGRESS
    task.started_at = datetime.now(timezone.utc).isoformat()
    await state_manager.update_task(task)

    spec_description = json.dumps(state["spec"])
    try:
        context = await rag_pipeline.search(
            query=spec_description[:500],
            repository=state["repository"],
            top_k=5,
        )
    except Exception:
        context = []

    return {"codebase_context": context}


async def generate_code(state: CodeGenState) -> dict[str, Any]:
    """Generate code from the spec."""
    spec = state["spec"]
    context_str = "\n\n".join(
        f"// {c['file_path']}\n{c['content']}" for c in state["codebase_context"]
    )

    # Determine which stack to generate for
    spec_type = spec.get("type", "frontend")
    system_prompt = NEXTJS_SYSTEM_PROMPT if spec_type == "frontend" else DOTNET_SYSTEM_PROMPT

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=f"""Generate code for the following specification:

{json.dumps(spec, indent=2)}

Existing codebase context for reference:
{context_str[:5000]}"""),
    ]

    response = await llm_provider.ainvoke(messages)
    try:
        files = json.loads(response.content.strip("```json").strip("```"))
    except json.JSONDecodeError:
        files = []

    return {"generated_files": files}


async def create_pr(state: CodeGenState) -> dict[str, Any]:
    """Create a branch, commit files, and open a PR."""
    repo_parts = state["repository"].split("/")
    if len(repo_parts) != 2:
        return {"pr_url": ""}

    owner, repo = repo_parts
    spec_name = state["spec"].get("name", "feature")
    branch = f"agent/{spec_name.lower().replace(' ', '-')}"

    try:
        await github_client.create_branch(owner=owner, repo=repo, branch=branch)

        for file_info in state["generated_files"]:
            await github_client.create_or_update_file(
                owner=owner,
                repo=repo,
                path=file_info["path"],
                content=file_info["content"],
                message=f"feat: add {file_info['path']}",
                branch=branch,
            )

        pr = await github_client.create_pull_request(
            owner=owner,
            repo=repo,
            title=f"feat: {spec_name}",
            body=f"""## Generated by Code & Build Agent

### Specification
{json.dumps(state['spec'], indent=2)[:2000]}

### Files Generated
{chr(10).join(f'- `{f["path"]}`' for f in state['generated_files'])}

---
*Generated by DevOps Agentic Teammates — Code & Build Agent*
""",
            head=branch,
        )
        return {"pr_url": pr.get("html_url", ""), "branch_name": branch}
    except Exception as e:
        logger.error("Failed to create PR", error=str(e))
        return {"pr_url": ""}


async def finalize_codegen(state: CodeGenState) -> dict[str, Any]:
    """Finalize code generation task."""
    task = state["task"]
    task.status = TaskStatus.COMPLETED
    task.completed_at = datetime.now(timezone.utc).isoformat()
    task.output_data = {
        "files_generated": len(state["generated_files"]),
        "branch": state["branch_name"],
        "pr_url": state["pr_url"],
    }
    task.tokens_used = llm_provider.tokens_used
    await state_manager.update_task(task)

    await event_publisher.publish_task_completed(
        agent_type="code-build",
        task_id=task.task_id,
        task_type="code-generation",
        status="completed",
        output=task.output_data,
    )
    return {}


# ---- Build Graphs ----

def build_review_graph() -> StateGraph:
    graph = StateGraph(CodeReviewState)
    graph.add_node("fetch_diff", fetch_pr_diff)
    graph.add_node("review", review_code)
    graph.add_node("post_review", post_review)
    graph.add_node("finalize", finalize_review)

    graph.add_edge(START, "fetch_diff")
    graph.add_edge("fetch_diff", "review")
    graph.add_edge("review", "post_review")
    graph.add_edge("post_review", "finalize")
    graph.add_edge("finalize", END)
    return graph


def build_codegen_graph() -> StateGraph:
    graph = StateGraph(CodeGenState)
    graph.add_node("retrieve_context", retrieve_context)
    graph.add_node("generate_code", generate_code)
    graph.add_node("create_pr", create_pr)
    graph.add_node("finalize", finalize_codegen)

    graph.add_edge(START, "retrieve_context")
    graph.add_edge("retrieve_context", "generate_code")
    graph.add_edge("generate_code", "create_pr")
    graph.add_edge("create_pr", "finalize")
    graph.add_edge("finalize", END)
    return graph


code_review_agent = build_review_graph().compile()
code_gen_agent = build_codegen_graph().compile()
