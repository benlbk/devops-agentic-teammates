"""EventBridge client for agent inter-communication."""

from __future__ import annotations

import json
import uuid
from typing import Any

import boto3
import structlog

from shared.config import settings

logger = structlog.get_logger()


class EventPublisher:
    """Publishes events to EventBridge for inter-agent communication."""

    def __init__(self) -> None:
        self._client = boto3.client("events", region_name=settings.aws_region)

    async def publish_task_requested(
        self,
        agent_type: str,
        task_type: str,
        context: dict[str, Any],
        policy: dict[str, Any] | None = None,
    ) -> str:
        """Publish a task request event."""
        task_id = str(uuid.uuid4())
        entry = {
            "Source": "devops-agentic-teammates",
            "DetailType": "agent.task.requested",
            "EventBusName": settings.event_bus_name,
            "Detail": json.dumps({
                "taskId": task_id,
                "agentType": agent_type,
                "taskType": task_type,
                "context": context,
                "policy": policy or {},
            }),
        }

        self._client.put_events(Entries=[entry])
        logger.info(
            "Published task request",
            task_id=task_id,
            agent_type=agent_type,
            task_type=task_type,
        )
        return task_id

    async def publish_task_completed(
        self,
        agent_type: str,
        task_id: str,
        task_type: str,
        status: str,
        output: dict[str, Any],
        next_actions: list[dict[str, Any]] | None = None,
    ) -> None:
        """Publish a task completion event."""
        entry = {
            "Source": f"agent.{agent_type}",
            "DetailType": "agent.task.completed",
            "EventBusName": settings.event_bus_name,
            "Detail": json.dumps({
                "taskId": task_id,
                "agentType": agent_type,
                "taskType": task_type,
                "status": status,
                "output": output,
                "nextActions": next_actions or [],
            }),
        }

        self._client.put_events(Entries=[entry])
        logger.info(
            "Published task completion",
            task_id=task_id,
            agent_type=agent_type,
            status=status,
        )

    async def publish_approval_request(
        self,
        agent_type: str,
        task_id: str,
        action: str,
        context: dict[str, Any],
        approvers: list[str],
    ) -> None:
        """Publish an approval request event."""
        entry = {
            "Source": f"agent.{agent_type}",
            "DetailType": "agent.approval.requested",
            "EventBusName": settings.event_bus_name,
            "Detail": json.dumps({
                "taskId": task_id,
                "agentType": agent_type,
                "action": action,
                "context": context,
                "approvers": approvers,
            }),
        }

        self._client.put_events(Entries=[entry])
        logger.info(
            "Published approval request",
            task_id=task_id,
            agent_type=agent_type,
            action=action,
        )


event_publisher = EventPublisher()
