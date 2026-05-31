"""Reference plugin demonstrating the (NFR-6) plugin protocol.

Adds a ``repo-stats`` task_type to the ``operate-monitor`` agent that
fetches basic GitHub repo stats and writes them to the task output.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import structlog

from shared.events import event_publisher
from shared.github_client import github_client
from shared.state import AgentTask, TaskStatus, state_manager

logger = structlog.get_logger()


async def run_repo_stats(task: AgentTask, context: dict[str, Any]) -> dict[str, Any]:
    repository = context.get("repository") or "benlbk/devops-agentic-teammates"
    owner, repo = repository.split("/", 1)

    task.status = TaskStatus.IN_PROGRESS
    task.started_at = datetime.now(timezone.utc).isoformat()
    await state_manager.update_task(task)

    try:
        headers = await github_client._auth_headers()
        resp = await github_client._http.get(
            f"/repos/{owner}/{repo}", headers=headers,
        )
        resp.raise_for_status()
        data = resp.json()
        out = {
            "repository": repository,
            "stars": data.get("stargazers_count", 0),
            "forks": data.get("forks_count", 0),
            "open_issues": data.get("open_issues_count", 0),
            "default_branch": data.get("default_branch", "main"),
            "language": data.get("language"),
            "pushed_at": data.get("pushed_at"),
        }
    except Exception as e:
        out = {"repository": repository, "error": str(e)}

    task.status = TaskStatus.COMPLETED
    task.completed_at = datetime.now(timezone.utc).isoformat()
    task.output_data = out
    await state_manager.update_task(task)
    await event_publisher.publish_task_completed(
        agent_type="operate-monitor",
        task_id=task.task_id,
        task_type="repo-stats",
        status="completed",
        output=out,
    )
    return out


PLUGIN = {
    "name": "repo-stats",
    "version": "1.0.0",
    "description": "Reference plugin: fetches basic GitHub repo statistics.",
    "author": "devops-agentic-teammates",
    "handlers": [
        {
            "agent_type": "operate-monitor",
            "task_type": "repo-stats",
            "function": run_repo_stats,
        },
    ],
}
