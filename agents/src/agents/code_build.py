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
    spec_files: list[dict[str, str]]
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

    # Normalize recommendation to valid GitHub review event
    valid_events = {"APPROVE", "REQUEST_CHANGES", "COMMENT"}
    event = state["recommendation"].upper().replace(" ", "_")
    if event not in valid_events:
        event = "COMMENT"

    try:
        await github_client.create_pr_review(
            owner=owner,
            repo=repo,
            pr_number=state["pr_number"],
            body=review_body,
            event=event,
        )
    except Exception as e:
        logger.warning("Failed to post review with event, retrying as COMMENT", review_event=event, error=str(e))
        # GitHub rejects REQUEST_CHANGES on own PRs — fall back to COMMENT
        try:
            await github_client.create_pr_review(
                owner=owner,
                repo=repo,
                pr_number=state["pr_number"],
                body=review_body,
                event="COMMENT",
            )
        except Exception as e2:
            logger.error("Failed to post review as comment, using issue comment", error=str(e2))
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
        "reviewSummary": state["review_summary"],
        "tokensUsed": llm_provider.tokens_used,
    }
    task.tokens_used = llm_provider.tokens_used
    await state_manager.update_task(task)

    next_actions = []
    if state["recommendation"] == "APPROVE":
        # Create merge-approval task requiring human sign-off
        merge_task = AgentTask(
            agent_type="code-build",
            task_type="merge-approval",
            status=TaskStatus.AWAITING_APPROVAL,
            context={
                "repository": state["repository"],
                "pr_number": state["pr_number"],
                "prNumber": state["pr_number"],
                "review_task_id": task.task_id,
                "review_summary": state["review_summary"],
                "recommendation": "APPROVE",
            },
            output_data={
                "review_summary": state["review_summary"],
                "review_comments_count": len(state["review_comments"]),
            },
        )
        await state_manager.create_task(merge_task)
        logger.info("Merge approval requested", pr_number=state["pr_number"], task_id=merge_task.task_id)

        next_actions.append({
            "agent": "code-build",
            "taskType": "merge-approval",
            "context": {"repository": state["repository"], "prNumber": state["pr_number"]},
        })
    elif state["recommendation"] == "REQUEST_CHANGES":
        # Auto-chain: trigger code-fix to address review findings
        next_actions.append({
            "agent": "code-build",
            "taskType": "code-generation",
            "context": {
                "repository": state["repository"],
                "fix_mode": True,
                "fix_pr_number": state["pr_number"],
                "review_summary": state["review_summary"],
                "review_task_id": task.task_id,
            },
        })

    await event_publisher.publish_task_completed(
        agent_type="code-build",
        task_id=task.task_id,
        task_type="code-review",
        status="completed",
        output=task.output_data,
        next_actions=next_actions,
    )

    # Execute fix chain immediately if REQUEST_CHANGES — but only if not already fixed
    if state["recommendation"] == "REQUEST_CHANGES":
        # Loop prevention: check if latest commit on PR is already an auto-fix
        should_fix = True
        try:
            repo_parts = state["repository"].split("/")
            owner, repo = repo_parts[0], repo_parts[1]
            pr_data = await github_client.get_pull_request(
                owner=owner, repo=repo, pr_number=int(state["pr_number"])
            )
            branch = pr_data.get("head", {}).get("ref", "")
            if branch:
                commits = await github_client.list_commits(
                    owner=owner, repo=repo, branch=branch, per_page=1
                )
                if commits and commits[0].get("commit", {}).get("message", "").startswith("fix: address review findings"):
                    should_fix = False
                    logger.info("Skipping auto-fix: latest commit is already a fix",
                                branch=branch, pr=state["pr_number"])
        except Exception as e:
            logger.warning("Failed to check latest commit for loop prevention", error=str(e))

        if should_fix:
            fix_task = AgentTask(
                agent_type="code-build",
                task_type="code-generation",
                context={
                    "repository": state["repository"],
                    "fix_mode": True,
                    "fix_pr_number": state["pr_number"],
                    "review_summary": state["review_summary"],
                    "review_task_id": task.task_id,
                },
            )
            await state_manager.create_task(fix_task)
            await event_publisher.publish_task_requested(
                agent_type="code-build",
                task_type="code-generation",
                context=fix_task.context,
            )
            import asyncio
            from orchestrator.main import execute_agent_task
            asyncio.ensure_future(execute_agent_task(fix_task))
            logger.info("Chained code-fix task for review findings",
                        fix_task_id=fix_task.task_id, review_task_id=task.task_id)

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

    spec = state["spec"]
    fix_mode = spec.get("fix_mode", False)

    # In fix mode, fetch the PR diff as context so LLM can see current code
    if fix_mode and spec.get("fix_pr_number"):
        try:
            repo_parts = state["repository"].split("/")
            owner, repo = repo_parts[0], repo_parts[1]
            diff = await github_client.get_pr_diff(
                owner=owner, repo=repo, pr_number=int(spec["fix_pr_number"])
            )
            # Convert diff into context items
            context = [{"file_path": "PR_DIFF", "content": diff[:12000]}]
            return {"codebase_context": context}
        except Exception as e:
            logger.warning("Failed to fetch PR diff for fix mode", error=str(e))

    spec_description = json.dumps(spec)
    try:
        context = await rag_pipeline.search(
            query=spec_description[:500],
            repository=state["repository"],
            top_k=5,
        )
    except Exception:
        context = []

    return {"codebase_context": context}


SPEC_DRIVEN_PROMPT = """You are a senior software architect following spec-driven development.
Given a feature specification, generate three markdown documents that will guide implementation:

1. **requirements.md** — Functional & non-functional requirements as user stories:
   - "As a [user], I want [goal] so that [benefit]"
   - Acceptance criteria for each story
   - Constraints and success criteria

2. **design.md** — System architecture & technical design:
   - Component interactions and data flow
   - Technology choices and rationale
   - Security, scalability, error handling considerations
   - API contracts if applicable

3. **tasks.md** — Actionable implementation tasks:
   - Ordered by priority and dependency
   - Include estimates (S/M/L) and completion criteria
   - Each task should be independently deliverable

Return as JSON array:
[
  {"path": ".bk/specs/FEATURE_NAME/requirements.md", "content": "..."},
  {"path": ".bk/specs/FEATURE_NAME/design.md", "content": "..."},
  {"path": ".bk/specs/FEATURE_NAME/tasks.md", "content": "..."}
]

Replace FEATURE_NAME with a kebab-case name derived from the feature.
Return ONLY valid JSON. No markdown code fences."""


async def generate_specs(state: CodeGenState) -> dict[str, Any]:
    """Generate spec-driven development documents before code generation."""
    import re

    # Skip spec generation in fix mode (we're fixing existing code, not creating new)
    if state["spec"].get("fix_mode"):
        logger.info("Skipping spec generation (fix mode)")
        return {"spec_files": []}

    spec = state["spec"]
    feature_name = spec.get("name", "feature").lower().replace(" ", "-")[:30]

    messages = [
        SystemMessage(content=SPEC_DRIVEN_PROMPT),
        HumanMessage(content=f"""Generate spec documents for this feature:

Feature: {spec.get('name', 'Unknown')}
Description: {spec.get('description', '')}

Labels: {spec.get('labels', [])}
Target Path: {spec.get('target_path', '')}
Stories: {json.dumps(spec.get('stories', []))}"""),
    ]

    spec_files = []
    for attempt in range(2):
        response = await llm_provider.ainvoke(messages)
        try:
            content = response.content
            if isinstance(content, list):
                content = "".join(
                    block.get("text", "") if isinstance(block, dict) else str(block)
                    for block in content
                )
            if isinstance(content, str):
                # Strip markdown code fences
                content = re.sub(r'^```(?:json)?\s*\n?', '', content.strip())
                content = re.sub(r'\n?```\s*$', '', content.strip())
                # Fix invalid JSON escapes (e.g. \d, \w from regex in content)
                content = re.sub(r'\\([^"\\/bfnrtu])', r'\\\\\\1', content)
                # Try to extract JSON array starting with [{ pattern
                match = re.search(r'\[\s*\{.*\}\s*\]', content, re.DOTALL)
                if match:
                    content = match.group(0)
                elif content.lstrip().startswith('{'):
                    # LLM returned individual JSON objects — wrap in array
                    content = '[' + content + ']'
            spec_files = json.loads(content, strict=False)
            if isinstance(spec_files, list) and len(spec_files) > 0:
                break
            spec_files = []
        except (json.JSONDecodeError, TypeError) as e:
            logger.warning("Failed to parse spec docs", attempt=attempt + 1, error=str(e),
                           response_preview=str(response.content)[:200] if response else "")
            spec_files = []

    logger.info("Generated spec documents", count=len(spec_files), feature=feature_name)
    return {"spec_files": spec_files}


async def generate_code(state: CodeGenState) -> dict[str, Any]:
    """Generate code from the spec."""
    import re

    spec = state["spec"]
    fix_mode = spec.get("fix_mode", False)
    context_str = "\n\n".join(
        f"// {c['file_path']}\n{c['content']}" for c in state["codebase_context"]
    )

    if fix_mode:
        # Fix mode: generate fixes based on review findings
        review_summary = spec.get("review_summary", "")
        system_prompt = """You are an expert developer fixing code review findings.
Given the review feedback and existing code context, generate FIXED versions of the files.
Focus on addressing the specific issues raised in the review.
Only include files that need changes — provide the complete corrected file content.

Return ONLY a JSON array of file objects: [{"path": "src/...", "content": "complete file content"}]
Do not wrap in markdown code fences."""

        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=f"""Review Findings to Fix:
{review_summary}

Existing code context:
{context_str[:8000]}

Generate the fixed files addressing all review findings. Return ONLY valid JSON array."""),
        ]
    else:
        # Normal mode: generate new code from spec
        # Include spec documents as additional context for code generation
        specs_context = ""
        for sf in state.get("spec_files", []):
            specs_context += f"\n\n--- {sf['path']} ---\n{sf['content']}"

        # Determine which stack to generate for
        spec_type = spec.get("type", "frontend")
        target_path = spec.get("target_path", "")
        system_prompt = NEXTJS_SYSTEM_PROMPT if spec_type == "frontend" else DOTNET_SYSTEM_PROMPT

        # Add target path guidance if provided
        path_hint = f"\nPlace files under: {target_path}/" if target_path else ""

        messages = [
            SystemMessage(content=system_prompt + path_hint),
            HumanMessage(content=f"""Generate code for the following specification:

{json.dumps(spec, indent=2)}

Spec-driven design documents (follow these closely):
{specs_context[:4000]}

Existing codebase context for reference:
{context_str[:5000]}

Return ONLY a JSON array of file objects. Do not wrap in markdown code fences."""),
        ]

    response = await llm_provider.ainvoke(messages)
    try:
        content = response.content
        # Handle list content blocks (Claude Bedrock format)
        if isinstance(content, list):
            content = "".join(
                block.get("text", "") if isinstance(block, dict) else str(block)
                for block in content
            )
        if isinstance(content, str):
            # Strip markdown code fences
            content = re.sub(r'^```(?:json)?\s*\n?', '', content.strip())
            content = re.sub(r'\n?```\s*$', '', content.strip())
            # Fix invalid JSON escapes (e.g. \d, \w from regex in code)
            content = re.sub(
                r'\\([^"\\/bfnrtu])',
                r'\\\\\\1',
                content,
            )
        files = json.loads(content, strict=False)
        if not isinstance(files, list):
            files = []
    except (json.JSONDecodeError, TypeError) as parse_err:
        logger.warning("JSON parse error", error=str(parse_err)[:200])
        # Try regex extraction of JSON array from raw content
        raw = response.content
        if isinstance(raw, list):
            raw = "".join(
                block.get("text", "") if isinstance(block, dict) else str(block)
                for block in raw
            )
        try:
            # Fix invalid escapes in fallback too
            fixed = re.sub(r'\\([^"\\/bfnrtu])', r'\\\\\\1', raw)
            match = re.search(r'\[[\s\S]*\]', fixed)
            if match:
                files = json.loads(match.group(0), strict=False)
            else:
                files = []
        except (json.JSONDecodeError, TypeError):
            files = []
        if not files:
            logger.warning("Failed to parse generated code from LLM",
                           response_preview=repr(raw[:500]) if isinstance(raw, str) else repr(str(raw)[:500]))

    return {"generated_files": files}


async def create_pr(state: CodeGenState) -> dict[str, Any]:
    """Create a branch, commit spec files + generated code, and open a PR."""
    repo_parts = state["repository"].split("/")
    if len(repo_parts) != 2:
        return {"pr_url": ""}

    owner, repo = repo_parts
    spec = state["spec"]
    fix_mode = spec.get("fix_mode", False)

    # In fix mode, push to existing PR branch
    if fix_mode and state.get("branch_name"):
        branch = state["branch_name"]
        try:
            for file_info in state["generated_files"]:
                await github_client.create_or_update_file(
                    owner=owner,
                    repo=repo,
                    path=file_info["path"],
                    content=file_info["content"],
                    message=f"fix: address review findings in {file_info['path']}",
                    branch=branch,
                )
            # Post a comment on the PR noting the fix
            fix_pr_number = spec.get("fix_pr_number")
            if fix_pr_number:
                await github_client.create_issue_comment(
                    owner=owner,
                    repo=repo,
                    issue_number=fix_pr_number,
                    body=f"""## 🔧 Auto-Fix Applied

The Code & Build Agent has pushed fixes to address the review findings:

### Files Updated
{chr(10).join(f'- `{f["path"]}`' for f in state['generated_files'])}

### Review Findings Addressed
{spec.get('review_summary', 'N/A')[:500]}

---
*Fixed by DevOps Agentic Teammates — Code & Build Agent*
""",
                )
            logger.info("Pushed fixes to existing branch", branch=branch, files=len(state["generated_files"]))
            return {"pr_url": f"https://github.com/{owner}/{repo}/pull/{fix_pr_number}", "branch_name": branch}
        except Exception as e:
            logger.error("Failed to push fixes", error=str(e))
            return {"pr_url": "", "branch_name": branch}

    # Normal mode: create new branch and PR
    spec_name = spec.get("name", "feature")
    branch = f"agent/{spec_name.lower().replace(' ', '-')}"

    try:
        try:
            await github_client.create_branch(owner=owner, repo=repo, branch=branch)
        except Exception as branch_err:
            if "422" in str(branch_err):
                logger.info("Branch already exists, reusing", branch=branch)
            else:
                raise

        # Commit spec documents first (spec-driven development)
        for spec_file in state.get("spec_files", []):
            await github_client.create_or_update_file(
                owner=owner,
                repo=repo,
                path=spec_file["path"],
                content=spec_file["content"],
                message=f"docs: add spec {spec_file['path']}",
                branch=branch,
            )

        # Then commit implementation code
        for file_info in state["generated_files"]:
            await github_client.create_or_update_file(
                owner=owner,
                repo=repo,
                path=file_info["path"],
                content=file_info["content"],
                message=f"feat: add {file_info['path']}",
                branch=branch,
            )

        all_files = state.get("spec_files", []) + state["generated_files"]
        issue_number = spec.get("issue_number")
        closes_line = f"\n\nCloses #{issue_number}" if issue_number else ""
        pr = await github_client.create_pull_request(
            owner=owner,
            repo=repo,
            title=f"feat: {spec_name}",
            body=f"""## Generated by Code & Build Agent (Spec-Driven)

### Specification
{json.dumps(state['spec'], indent=2)[:2000]}

### Spec Documents
{chr(10).join(f'- `{f["path"]}`' for f in state.get('spec_files', []))}

### Implementation Files
{chr(10).join(f'- `{f["path"]}`' for f in state['generated_files'])}

---
*Generated by DevOps Agentic Teammates — Code & Build Agent*{closes_line}
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
    graph.add_node("generate_specs", generate_specs)
    graph.add_node("generate_code", generate_code)
    graph.add_node("create_pr", create_pr)
    graph.add_node("finalize", finalize_codegen)

    graph.add_edge(START, "retrieve_context")
    graph.add_edge("retrieve_context", "generate_specs")
    graph.add_edge("generate_specs", "generate_code")
    graph.add_edge("generate_code", "create_pr")
    graph.add_edge("create_pr", "finalize")
    graph.add_edge("finalize", END)
    return graph


code_review_agent = build_review_graph().compile()
code_gen_agent = build_codegen_graph().compile()
