"""Plan & Collaborate Agent — Transforms designs into actionable development plans."""

from __future__ import annotations

from typing import Any, Annotated

import structlog
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field
from typing_extensions import TypedDict

from shared.events import event_publisher
from shared.github_client import github_client
from shared.llm import llm_provider
from shared.state import AgentTask, TaskStatus, state_manager

logger = structlog.get_logger()

# ---- State ----

class PlanState(TypedDict):
    messages: Annotated[list, add_messages]
    task: AgentTask
    repository: str
    feature_description: str
    components: list[dict[str, Any]]
    user_stories: list[dict[str, Any]]
    api_contracts: list[dict[str, Any]]
    specs_committed: bool


# ---- Tools ----

class DesignParser:
    """Parse design descriptions into structured components."""

    async def parse(self, description: str, codebase_context: str = "") -> dict[str, Any]:
        messages = [
            SystemMessage(content="""You are an expert software architect. Parse the given feature description
and extract a structured breakdown. Return a JSON object with:
- components: list of {name, type (page|component|service|model|migration), description, dependencies}
- data_models: list of {name, fields: [{name, type, constraints}], relationships}
- api_endpoints: list of {method, path, description, request_body, response_body}
- ui_pages: list of {route, title, components, description}
Respond ONLY with valid JSON. Do not wrap in markdown code fences."""),
            HumanMessage(content=f"""Feature Description:
{description}

Existing Codebase Context:
{codebase_context}"""),
        ]
        response = await llm_provider.ainvoke(messages)
        import json
        import re
        try:
            content = response.content
            # Strip markdown code fences if present
            if isinstance(content, str):
                content = re.sub(r'^```(?:json)?\s*\n?', '', content.strip())
                content = re.sub(r'\n?```\s*$', '', content.strip())
            result = json.loads(content)
            if isinstance(result, dict):
                return result
            return {"components": [], "data_models": [], "api_endpoints": [], "ui_pages": []}
        except (json.JSONDecodeError, TypeError):
            return {"components": [], "data_models": [], "api_endpoints": [], "ui_pages": []}


class StoryGenerator:
    """Generate user stories from feature descriptions."""

    async def generate(
        self, description: str, components: dict[str, Any]
    ) -> list[dict[str, Any]]:
        messages = [
            SystemMessage(content="""You are a product manager creating user stories. Generate user stories from
the feature description and component breakdown. Each story should have:
- title: concise story title
- story: "As a [user], I want [goal] so that [benefit]"
- acceptance_criteria: list of testable criteria
- priority: P0/P1/P2/P3
- story_points: fibonacci (1,2,3,5,8,13)
- labels: list of relevant labels
- dependencies: list of story titles this depends on
Return a JSON array of story objects. Do not wrap in markdown code fences."""),
            HumanMessage(content=f"""Feature: {description}

Components: {components}"""),
        ]
        response = await llm_provider.ainvoke(messages)
        import json
        import re
        try:
            content = response.content
            if isinstance(content, str):
                content = re.sub(r'^```(?:json)?\s*\n?', '', content.strip())
                content = re.sub(r'\n?```\s*$', '', content.strip())
            result = json.loads(content)
            if isinstance(result, list):
                return result
            return []
        except (json.JSONDecodeError, TypeError):
            return []


class ADRGenerator:
    """Generate Architecture Decision Records."""

    async def generate(self, context: str, decision: str) -> str:
        messages = [
            SystemMessage(content="""Generate an Architecture Decision Record (ADR) in the following format:
# ADR-XXX: [Title]
## Status: Proposed
## Context: [What is the issue?]
## Decision: [What was decided?]
## Consequences: [What are the results?]
## Alternatives Considered: [What other options were explored?]"""),
            HumanMessage(content=f"Context: {context}\nDecision: {decision}"),
        ]
        response = await llm_provider.ainvoke(messages)
        return response.content


# ---- Workflow Nodes ----

design_parser = DesignParser()
story_generator = StoryGenerator()
adr_generator = ADRGenerator()


async def parse_design(state: PlanState) -> dict[str, Any]:
    """Parse the feature description into components."""
    task = state["task"]
    task.status = TaskStatus.IN_PROGRESS
    task.started_at = __import__("datetime").datetime.now(
        __import__("datetime").timezone.utc
    ).isoformat()
    await state_manager.update_task(task)

    result = await design_parser.parse(state["feature_description"])
    return {
        "components": result.get("components", []),
        "api_contracts": result.get("api_endpoints", []),
        "messages": [HumanMessage(content=f"Parsed {len(result.get('components', []))} components")],
    }


async def generate_stories(state: PlanState) -> dict[str, Any]:
    """Generate user stories from parsed design."""
    stories = await story_generator.generate(
        state["feature_description"],
        {"components": state["components"], "api_contracts": state["api_contracts"]},
    )
    return {
        "user_stories": stories,
        "messages": [HumanMessage(content=f"Generated {len(stories)} user stories")],
    }


async def create_github_issues(state: PlanState) -> dict[str, Any]:
    """Create GitHub issues from user stories."""
    repo_parts = state["repository"].split("/")
    if len(repo_parts) != 2:
        return {"messages": [HumanMessage(content="Invalid repository format")]}

    owner, repo = repo_parts
    created_issues = []

    for story in state["user_stories"]:
        body = f"""## User Story
{story.get('story', '')}

## Acceptance Criteria
{chr(10).join(f'- [ ] {ac}' for ac in story.get('acceptance_criteria', []))}

## Details
- **Priority:** {story.get('priority', 'P2')}
- **Story Points:** {story.get('story_points', 3)}
- **Dependencies:** {', '.join(story.get('dependencies', []))}

---
*Generated by DevOps Agentic Teammates — Plan & Collaborate Agent*
"""
        try:
            issue = await github_client.create_issue(
                owner=owner,
                repo=repo,
                title=story.get("title", "Untitled Story"),
                body=body,
                labels=story.get("labels", []) + ["agent-generated"],
            )
            created_issues.append(issue)
        except Exception as e:
            logger.error("Failed to create issue", error=str(e), story=story.get("title"))

    return {
        "messages": [HumanMessage(content=f"Created {len(created_issues)} GitHub issues")],
    }


async def commit_specs(state: PlanState) -> dict[str, Any]:
    """Commit spec-driven development documents to the repository."""
    repo_parts = state["repository"].split("/")
    if len(repo_parts) != 2:
        return {"specs_committed": False}

    owner, repo = repo_parts
    import json

    feature_slug = state["feature_description"][:50].lower().replace(" ", "-")
    # Clean slug of special characters
    feature_slug = "".join(c for c in feature_slug if c.isalnum() or c == "-").strip("-")

    # Generate requirements.md
    stories_md = ""
    for story in state["user_stories"]:
        stories_md += f"\n### {story.get('title', 'Story')}\n"
        stories_md += f"- **Story:** {story.get('story', '')}\n"
        stories_md += f"- **Priority:** {story.get('priority', 'P2')}\n"
        stories_md += f"- **Story Points:** {story.get('story_points', 3)}\n"
        stories_md += "- **Acceptance Criteria:**\n"
        for ac in story.get("acceptance_criteria", []):
            stories_md += f"  - [ ] {ac}\n"

    requirements_md = f"""# Requirements: {state['feature_description'][:80]}

## Overview
{state['feature_description']}

## User Stories
{stories_md}

## Non-Functional Requirements
- Performance: API response times < 200ms
- Security: Follow OWASP Top 10 guidelines
- Scalability: Support horizontal scaling

---
*Generated by DevOps Agentic Teammates — Plan & Collaborate Agent*
"""

    # Generate design.md
    components_md = ""
    for comp in state["components"]:
        components_md += f"- **{comp.get('name', '')}** ({comp.get('type', '')}): {comp.get('description', '')}\n"

    api_md = ""
    for api in state["api_contracts"]:
        api_md += f"- `{api.get('method', 'GET')} {api.get('path', '')}` — {api.get('description', '')}\n"

    design_md = f"""# Design: {state['feature_description'][:80]}

## Architecture

### Components
{components_md}

### API Contracts
{api_md}

### Data Flow
1. Client sends request to API gateway
2. API routes to appropriate service
3. Service processes business logic
4. Data persisted to database
5. Response returned to client

## Technology Stack
- Frontend: Next.js 14+ with TypeScript, React, Tailwind CSS
- Backend: ASP.NET Core 8+ with C#, Entity Framework Core
- Database: PostgreSQL
- Infrastructure: AWS EKS, Terraform

## Security Considerations
- Input validation on all endpoints
- Authentication via JWT tokens
- Rate limiting on public APIs
- Encrypted data at rest and in transit

---
*Generated by DevOps Agentic Teammates — Plan & Collaborate Agent*
"""

    # Generate tasks.md
    tasks_md = ""
    for i, story in enumerate(state["user_stories"], 1):
        size = "S" if story.get("story_points", 3) <= 2 else "M" if story.get("story_points", 3) <= 5 else "L"
        deps = ", ".join(story.get("dependencies", [])) or "None"
        tasks_md += f"""
### Task {i}: {story.get('title', 'Task')}
- **Size:** {size}
- **Priority:** {story.get('priority', 'P2')}
- **Dependencies:** {deps}
- **Completion Criteria:** All acceptance criteria met, tests passing
"""

    tasks_content = f"""# Implementation Tasks: {state['feature_description'][:80]}

## Task Breakdown
{tasks_md}

## Implementation Sequence
1. Set up project structure and dependencies
2. Implement data models and database migrations
3. Build backend API endpoints
4. Create frontend components and pages
5. Add integration tests
6. Security review and hardening

---
*Generated by DevOps Agentic Teammates — Plan & Collaborate Agent*
"""

    spec_path = f".bk/specs/{feature_slug}"
    committed = False
    try:
        await github_client.create_or_update_file(
            owner=owner, repo=repo,
            path=f"{spec_path}/requirements.md",
            content=requirements_md,
            message=f"docs: add spec {spec_path}/requirements.md",
            branch="main",
        )
        await github_client.create_or_update_file(
            owner=owner, repo=repo,
            path=f"{spec_path}/design.md",
            content=design_md,
            message=f"docs: add spec {spec_path}/design.md",
            branch="main",
        )
        await github_client.create_or_update_file(
            owner=owner, repo=repo,
            path=f"{spec_path}/tasks.md",
            content=tasks_content,
            message=f"docs: add spec {spec_path}/tasks.md",
            branch="main",
        )
        committed = True
        logger.info("Committed spec documents", repo=state["repository"], path=spec_path)
    except Exception as e:
        logger.error("Failed to commit specs", error=str(e))

    return {"specs_committed": committed}


async def finalize(state: PlanState) -> dict[str, Any]:
    """Finalize the planning task."""
    task = state["task"]
    task.status = TaskStatus.COMPLETED
    task.completed_at = __import__("datetime").datetime.now(
        __import__("datetime").timezone.utc
    ).isoformat()
    task.output_data = {
        "components_count": len(state["components"]),
        "stories_count": len(state["user_stories"]),
        "specs_committed": state["specs_committed"],
    }
    task.tokens_used = llm_provider.tokens_used
    await state_manager.update_task(task)

    await event_publisher.publish_task_completed(
        agent_type="plan-collaborate",
        task_id=task.task_id,
        task_type=task.task_type,
        status="completed",
        output=task.output_data,
        next_actions=[
            {
                "agent": "code-build",
                "taskType": "code-generation",
                "context": {
                    "repository": state["repository"],
                    "stories": state["user_stories"],
                },
            }
        ],
    )
    return {"messages": [HumanMessage(content="Planning complete")]}


# ---- Graph ----

def build_plan_graph() -> StateGraph:
    graph = StateGraph(PlanState)

    graph.add_node("parse_design", parse_design)
    graph.add_node("generate_stories", generate_stories)
    graph.add_node("create_github_issues", create_github_issues)
    graph.add_node("commit_specs", commit_specs)
    graph.add_node("finalize", finalize)

    graph.add_edge(START, "parse_design")
    graph.add_edge("parse_design", "generate_stories")
    graph.add_edge("generate_stories", "create_github_issues")
    graph.add_edge("create_github_issues", "commit_specs")
    graph.add_edge("commit_specs", "finalize")
    graph.add_edge("finalize", END)

    return graph


plan_agent = build_plan_graph().compile()
