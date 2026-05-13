"""Operate & Monitor Agent — Monitors, self-heals, and optimizes the platform."""

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

class IncidentState(TypedDict):
    messages: Annotated[list, add_messages]
    task: AgentTask
    repository: str
    alert_data: dict[str, Any]
    diagnosis: str
    remediation_plan: list[dict[str, str]]
    actions_taken: list[str]
    resolved: bool
    postmortem: str


class CostAnalysisState(TypedDict):
    messages: Annotated[list, add_messages]
    task: AgentTask
    repository: str
    cost_data: dict[str, Any]
    recommendations: list[dict[str, Any]]
    savings_estimate: float
    report: str


class PerformanceState(TypedDict):
    messages: Annotated[list, add_messages]
    task: AgentTask
    repository: str
    metrics: dict[str, Any]
    bottlenecks: list[dict[str, Any]]
    optimization_plan: list[dict[str, str]]


# ---- Incident Response ----

INCIDENT_DIAGNOSIS_PROMPT = """You are an expert SRE / incident responder. Analyze the alert data and:
1. Identify the root cause category (infrastructure, application, network, capacity, deployment)
2. Assess severity (SEV1-critical, SEV2-high, SEV3-medium, SEV4-low)
3. Determine blast radius
4. Suggest immediate remediation steps as JSON:
{
  "diagnosis": "Root cause analysis",
  "severity": "SEV1|SEV2|SEV3|SEV4",
  "category": "infrastructure|application|network|capacity|deployment",
  "blast_radius": "description",
  "remediation_steps": [
    {"action": "description", "type": "automated|manual", "risk": "low|medium|high"}
  ]
}"""


async def diagnose_incident(state: IncidentState) -> dict[str, Any]:
    """Diagnose the incident from alert data."""
    task = state["task"]
    task.status = TaskStatus.IN_PROGRESS
    task.started_at = datetime.now(timezone.utc).isoformat()
    await state_manager.update_task(task)

    messages = [
        SystemMessage(content=INCIDENT_DIAGNOSIS_PROMPT),
        HumanMessage(content=f"Alert data:\n{json.dumps(state['alert_data'], indent=2)}"),
    ]
    response = await llm_provider.ainvoke(messages)

    try:
        result = json.loads(response.content.strip("```json").strip("```"))
    except json.JSONDecodeError:
        result = {"diagnosis": response.content, "severity": "SEV3", "remediation_steps": []}

    return {
        "diagnosis": result.get("diagnosis", ""),
        "remediation_plan": result.get("remediation_steps", []),
    }


async def execute_remediation(state: IncidentState) -> dict[str, Any]:
    """Execute automated remediation steps."""
    actions_taken: list[str] = []

    for step in state["remediation_plan"]:
        if step.get("type") == "automated" and step.get("risk") == "low":
            action = step.get("action", "")
            logger.info("Executing automated remediation", action=action)

            # In production, these would be real actions:
            # - kubectl scale deployment
            # - kubectl rollout undo
            # - aws autoscaling update-auto-scaling-group
            # - aws rds failover
            actions_taken.append(f"Executed: {action}")
        else:
            logger.info("Skipping non-automated or risky step", step=step)

    return {"actions_taken": actions_taken, "resolved": len(actions_taken) > 0}


async def generate_postmortem(state: IncidentState) -> dict[str, Any]:
    """Generate a postmortem document."""
    messages = [
        SystemMessage(content="""Generate a blameless postmortem in the following format:

## Incident Postmortem

### Summary
### Timeline
### Root Cause
### Impact
### Remediation Actions Taken
### Lessons Learned
### Action Items (with owners)"""),
        HumanMessage(content=f"""Incident details:
Diagnosis: {state['diagnosis']}
Alert Data: {json.dumps(state['alert_data'])}
Actions Taken: {json.dumps(state['actions_taken'])}
Resolved: {state['resolved']}"""),
    ]
    response = await llm_provider.ainvoke(messages)

    # Commit the postmortem
    repo_parts = state["repository"].split("/")
    if len(repo_parts) == 2:
        owner, repo = repo_parts
        ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        try:
            await github_client.create_or_update_file(
                owner=owner,
                repo=repo,
                path=f"docs/postmortems/{ts}.md",
                content=response.content,
                message=f"docs: postmortem {ts}",
                branch="main",
            )
        except Exception as e:
            logger.error("Failed to commit postmortem", error=str(e))

    return {"postmortem": response.content}


async def finalize_incident(state: IncidentState) -> dict[str, Any]:
    task = state["task"]
    task.status = TaskStatus.COMPLETED
    task.completed_at = datetime.now(timezone.utc).isoformat()
    task.output_data = {
        "resolved": state["resolved"],
        "actions_taken": len(state["actions_taken"]),
        "has_postmortem": bool(state.get("postmortem")),
    }
    task.tokens_used = llm_provider.tokens_used
    await state_manager.update_task(task)

    await event_publisher.publish_task_completed(
        agent_type="operate-monitor",
        task_id=task.task_id,
        task_type="incident-response",
        status="completed",
        output=task.output_data,
    )
    return {}


# ---- Cost Analysis ----

COST_ANALYSIS_PROMPT = """You are an AWS cost optimization expert. Analyze the cost data and provide:
1. Top cost drivers
2. Optimization recommendations with estimated savings
3. Right-sizing suggestions
4. Reserved Instance / Savings Plan opportunities
5. Unused resource identification

Return JSON:
{
  "recommendations": [
    {"category": "...", "description": "...", "estimated_monthly_savings": 0, "effort": "low|medium|high", "risk": "low|medium|high"}
  ],
  "total_estimated_savings": 0
}"""


async def analyze_costs(state: CostAnalysisState) -> dict[str, Any]:
    task = state["task"]
    task.status = TaskStatus.IN_PROGRESS
    task.started_at = datetime.now(timezone.utc).isoformat()
    await state_manager.update_task(task)

    messages = [
        SystemMessage(content=COST_ANALYSIS_PROMPT),
        HumanMessage(content=f"Cost data:\n{json.dumps(state['cost_data'], indent=2)}"),
    ]
    response = await llm_provider.ainvoke(messages)

    try:
        result = json.loads(response.content.strip("```json").strip("```"))
    except json.JSONDecodeError:
        result = {"recommendations": [], "total_estimated_savings": 0}

    return {
        "recommendations": result.get("recommendations", []),
        "savings_estimate": result.get("total_estimated_savings", 0),
    }


async def generate_cost_report(state: CostAnalysisState) -> dict[str, Any]:
    recs = state["recommendations"]
    report = f"""## 💰 Cost Optimization Report

**Estimated Monthly Savings: ${state['savings_estimate']:,.2f}**

### Recommendations

| # | Category | Description | Savings | Effort | Risk |
|---|----------|-------------|---------|--------|------|
"""
    for i, rec in enumerate(recs, 1):
        report += (
            f"| {i} | {rec.get('category', '')} "
            f"| {rec.get('description', '')} "
            f"| ${rec.get('estimated_monthly_savings', 0):,.2f} "
            f"| {rec.get('effort', '')} "
            f"| {rec.get('risk', '')} |\n"
        )

    report += "\n---\n*Generated by DevOps Agentic Teammates — Operate & Monitor Agent*\n"

    task = state["task"]
    task.status = TaskStatus.COMPLETED
    task.completed_at = datetime.now(timezone.utc).isoformat()
    task.output_data = {
        "recommendations_count": len(recs),
        "total_savings": state["savings_estimate"],
    }
    task.tokens_used = llm_provider.tokens_used
    await state_manager.update_task(task)

    return {"report": report}


# ---- Performance Optimization ----

PERF_ANALYSIS_PROMPT = """You are a performance engineering expert. Analyze the metrics and identify:
1. Performance bottlenecks (latency, throughput, resource utilization)
2. Root cause for each bottleneck
3. Optimization recommendations

Return JSON:
{
  "bottlenecks": [
    {"component": "...", "metric": "...", "current_value": "...", "target_value": "...", "root_cause": "..."}
  ],
  "optimization_plan": [
    {"action": "...", "component": "...", "expected_improvement": "...", "priority": "high|medium|low"}
  ]
}"""


async def analyze_performance(state: PerformanceState) -> dict[str, Any]:
    task = state["task"]
    task.status = TaskStatus.IN_PROGRESS
    task.started_at = datetime.now(timezone.utc).isoformat()
    await state_manager.update_task(task)

    messages = [
        SystemMessage(content=PERF_ANALYSIS_PROMPT),
        HumanMessage(content=f"Metrics:\n{json.dumps(state['metrics'], indent=2)}"),
    ]
    response = await llm_provider.ainvoke(messages)

    try:
        result = json.loads(response.content.strip("```json").strip("```"))
    except json.JSONDecodeError:
        result = {"bottlenecks": [], "optimization_plan": []}

    return {
        "bottlenecks": result.get("bottlenecks", []),
        "optimization_plan": result.get("optimization_plan", []),
    }


async def finalize_performance(state: PerformanceState) -> dict[str, Any]:
    task = state["task"]
    task.status = TaskStatus.COMPLETED
    task.completed_at = datetime.now(timezone.utc).isoformat()
    task.output_data = {
        "bottlenecks": len(state["bottlenecks"]),
        "optimizations": len(state["optimization_plan"]),
    }
    task.tokens_used = llm_provider.tokens_used
    await state_manager.update_task(task)
    return {}


# ---- Build Graphs ----

def build_incident_graph() -> StateGraph:
    graph = StateGraph(IncidentState)
    graph.add_node("diagnose", diagnose_incident)
    graph.add_node("remediate", execute_remediation)
    graph.add_node("postmortem", generate_postmortem)
    graph.add_node("finalize", finalize_incident)
    graph.add_edge(START, "diagnose")
    graph.add_edge("diagnose", "remediate")
    graph.add_edge("remediate", "postmortem")
    graph.add_edge("postmortem", "finalize")
    graph.add_edge("finalize", END)
    return graph


def build_cost_analysis_graph() -> StateGraph:
    graph = StateGraph(CostAnalysisState)
    graph.add_node("analyze", analyze_costs)
    graph.add_node("report", generate_cost_report)
    graph.add_edge(START, "analyze")
    graph.add_edge("analyze", "report")
    graph.add_edge("report", END)
    return graph


def build_performance_graph() -> StateGraph:
    graph = StateGraph(PerformanceState)
    graph.add_node("analyze", analyze_performance)
    graph.add_node("finalize", finalize_performance)
    graph.add_edge(START, "analyze")
    graph.add_edge("analyze", "finalize")
    graph.add_edge("finalize", END)
    return graph


incident_agent = build_incident_graph().compile()
cost_analysis_agent = build_cost_analysis_graph().compile()
performance_agent = build_performance_graph().compile()
