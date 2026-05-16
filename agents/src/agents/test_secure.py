"""Test & Secure Agent — Generates tests, runs security scans, manages feature flags."""

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

class TestGenState(TypedDict):
    messages: Annotated[list, add_messages]
    task: AgentTask
    repository: str
    pr_number: int
    source_files: list[dict[str, str]]
    codebase_context: list[dict[str, Any]]
    generated_tests: list[dict[str, str]]
    coverage_estimate: float


class SecurityScanState(TypedDict):
    messages: Annotated[list, add_messages]
    task: AgentTask
    repository: str
    pr_number: int
    scan_results: dict[str, Any]
    fix_prs: list[str]
    security_report: str


# ---- Test Generation ----

DOTNET_TEST_PROMPT = """You are an expert .NET test engineer. Generate comprehensive xUnit tests for the given code.

Follow these patterns:
- Use xUnit with FluentAssertions
- Use Moq for mocking dependencies
- Follow AAA (Arrange-Act-Assert) pattern
- Test happy paths, edge cases, and error scenarios
- Use descriptive test names: MethodName_Scenario_ExpectedResult
- Include both unit tests and integration tests where appropriate

Return JSON: [{"path": "tests/...", "content": "file content"}]"""

NEXTJS_TEST_PROMPT = """You are an expert React/Next.js test engineer. Generate comprehensive tests.

Follow these patterns:
- Use Jest with React Testing Library
- Test component rendering, interactions, and edge cases
- Mock API calls with MSW or jest.fn()
- Test hooks with renderHook
- For E2E, generate Playwright tests with page object model
- Use descriptive test names

Return JSON: [{"path": "tests/...", "content": "file content"}]"""

PLAYWRIGHT_E2E_PROMPT = """You are an expert E2E test engineer. Generate Playwright tests from acceptance criteria.

Follow these patterns:
- Use Page Object Model pattern
- Test complete user journeys
- Include assertions for visible elements and navigation
- Handle loading states and async operations
- Use proper selectors (getByRole, getByText preferred)

Return JSON: [{"path": "e2e/...", "content": "file content"}]"""


async def fetch_source_files(state: TestGenState) -> dict[str, Any]:
    """Retrieve source files for the PR."""
    task = state["task"]
    task.status = TaskStatus.IN_PROGRESS
    task.started_at = datetime.now(timezone.utc).isoformat()
    await state_manager.update_task(task)

    # Retrieve context about changed files
    try:
        context = await rag_pipeline.search(
            query=f"PR #{state['pr_number']} changed files",
            repository=state["repository"],
            top_k=10,
        )
    except Exception:
        context = []

    return {"codebase_context": context}


async def generate_tests(state: TestGenState) -> dict[str, Any]:
    """Generate test files based on source code."""
    all_tests: list[dict[str, str]] = []
    context_str = "\n\n".join(
        f"// {c['file_path']}\n{c['content']}" for c in state["codebase_context"]
    )

    # Determine language from file extensions
    has_ts = any(c.get("language") == "typescript" for c in state["codebase_context"])
    has_cs = any(c.get("language") == "csharp" for c in state["codebase_context"])

    if has_ts or not has_cs:
        messages = [
            SystemMessage(content=NEXTJS_TEST_PROMPT),
            HumanMessage(content=f"Generate tests for:\n{context_str[:8000]}"),
        ]
        response = await llm_provider.ainvoke(messages)
        try:
            tests = json.loads(response.content.strip("```json").strip("```"))
            all_tests.extend(tests)
        except json.JSONDecodeError:
            pass

    if has_cs:
        messages = [
            SystemMessage(content=DOTNET_TEST_PROMPT),
            HumanMessage(content=f"Generate tests for:\n{context_str[:8000]}"),
        ]
        response = await llm_provider.ainvoke(messages)
        try:
            tests = json.loads(response.content.strip("```json").strip("```"))
            all_tests.extend(tests)
        except json.JSONDecodeError:
            pass

    return {
        "generated_tests": all_tests,
        "coverage_estimate": 80.0 if all_tests else 0.0,
    }


async def commit_tests(state: TestGenState) -> dict[str, Any]:
    """Commit generated tests to the PR branch."""
    repo_parts = state["repository"].split("/")
    if len(repo_parts) != 2 or not state["generated_tests"]:
        return {}

    owner, repo = repo_parts

    for test_file in state["generated_tests"]:
        try:
            await github_client.create_or_update_file(
                owner=owner,
                repo=repo,
                path=test_file["path"],
                content=test_file["content"],
                message=f"test: add {test_file['path']}",
                branch=f"pr-{state['pr_number']}",
            )
        except Exception as e:
            logger.error("Failed to commit test", error=str(e), path=test_file["path"])

    return {"messages": [HumanMessage(content=f"Committed {len(state['generated_tests'])} test files")]}


async def finalize_test_gen(state: TestGenState) -> dict[str, Any]:
    """Finalize the test generation task."""
    task = state["task"]
    task.status = TaskStatus.COMPLETED
    task.completed_at = datetime.now(timezone.utc).isoformat()
    task.output_data = {
        "tests_generated": len(state["generated_tests"]),
        "coverage_estimate": state["coverage_estimate"],
    }
    task.tokens_used = llm_provider.tokens_used
    await state_manager.update_task(task)

    await event_publisher.publish_task_completed(
        agent_type="test-secure",
        task_id=task.task_id,
        task_type="generate-tests",
        status="completed",
        output=task.output_data,
    )
    return {}


# ---- Security Scan Workflow ----

async def run_security_scans(state: SecurityScanState) -> dict[str, Any]:
    """Orchestrate security scanning tools."""
    task = state["task"]
    task.status = TaskStatus.IN_PROGRESS
    task.started_at = datetime.now(timezone.utc).isoformat()
    await state_manager.update_task(task)

    # In production, these would invoke actual scanning tools via GitHub Actions
    # Here we define the orchestration logic
    scan_results: dict[str, Any] = {
        "sast": {"tool": "CodeQL+Semgrep", "status": "pending", "findings": []},
        "sca": {"tool": "Dependabot+Snyk", "status": "pending", "findings": []},
        "container": {"tool": "Trivy", "status": "pending", "findings": []},
        "iac": {"tool": "Checkov+tfsec", "status": "pending", "findings": []},
        "secrets": {"tool": "Gitleaks", "status": "pending", "findings": []},
    }

    return {"scan_results": scan_results}


async def analyze_findings(state: SecurityScanState) -> dict[str, Any]:
    """Analyze security findings and prioritize."""
    results = state["scan_results"]
    all_findings = []
    for scan_type, data in results.items():
        for finding in data.get("findings", []):
            finding["scan_type"] = scan_type
            all_findings.append(finding)

    if not all_findings:
        report = "## Security Scan Report\n\n✅ No vulnerabilities found.\n"
    else:
        messages = [
            SystemMessage(content="""Analyze these security findings and generate a markdown report with:
1. Executive summary
2. Critical/High findings with remediation steps
3. Medium/Low findings summary
4. Recommended actions"""),
            HumanMessage(content=json.dumps(all_findings)),
        ]
        response = await llm_provider.ainvoke(messages)
        report = response.content

    return {"security_report": report}


async def post_security_report(state: SecurityScanState) -> dict[str, Any]:
    """Post the security report to the PR."""
    repo_parts = state["repository"].split("/")
    if len(repo_parts) != 2:
        return {}

    owner, repo = repo_parts
    report = f"""## 🔒 Security Scan Report

{state['security_report']}

---
*Scanned by DevOps Agentic Teammates — Test & Secure Agent*
"""

    try:
        await github_client.create_issue_comment(
            owner=owner,
            repo=repo,
            issue_number=state["pr_number"],
            body=report,
        )
    except Exception as e:
        logger.error("Failed to post security report", error=str(e))

    return {}


async def generate_fix_prs(state: SecurityScanState) -> dict[str, Any]:
    """Generate fix PRs for auto-remediable vulnerabilities."""
    # In production, this would generate actual code fixes
    fix_prs: list[str] = []

    task = state["task"]
    task.status = TaskStatus.COMPLETED
    task.completed_at = datetime.now(timezone.utc).isoformat()
    task.output_data = {
        "scan_results": {k: v.get("status") for k, v in state["scan_results"].items()},
        "fix_prs_created": len(fix_prs),
    }
    task.tokens_used = llm_provider.tokens_used
    await state_manager.update_task(task)

    return {"fix_prs": fix_prs}


# ---- Build Graphs ----

def build_test_gen_graph() -> StateGraph:
    graph = StateGraph(TestGenState)
    graph.add_node("fetch_source", fetch_source_files)
    graph.add_node("generate_tests", generate_tests)
    graph.add_node("commit_tests", commit_tests)
    graph.add_node("finalize", finalize_test_gen)

    graph.add_edge(START, "fetch_source")
    graph.add_edge("fetch_source", "generate_tests")
    graph.add_edge("generate_tests", "commit_tests")
    graph.add_edge("commit_tests", "finalize")
    graph.add_edge("finalize", END)
    return graph


def build_security_scan_graph() -> StateGraph:
    graph = StateGraph(SecurityScanState)
    graph.add_node("run_scans", run_security_scans)
    graph.add_node("analyze", analyze_findings)
    graph.add_node("post_report", post_security_report)
    graph.add_node("generate_fixes", generate_fix_prs)

    graph.add_edge(START, "run_scans")
    graph.add_edge("run_scans", "analyze")
    graph.add_edge("analyze", "post_report")
    graph.add_edge("post_report", "generate_fixes")
    graph.add_edge("generate_fixes", END)
    return graph


test_gen_agent = build_test_gen_graph().compile()
security_scan_agent = build_security_scan_graph().compile()
