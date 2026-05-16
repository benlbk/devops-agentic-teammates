"""Agent state management using DynamoDB."""

from __future__ import annotations

import json
import time
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any

import boto3
import structlog
from pydantic import BaseModel, Field

from shared.config import settings

logger = structlog.get_logger()


class TaskStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in-progress"
    AWAITING_APPROVAL = "awaiting-approval"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class AgentTask(BaseModel):
    """Represents an agent task with its state."""

    task_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    agent_type: str
    task_type: str
    status: TaskStatus = TaskStatus.PENDING
    context: dict[str, Any] = Field(default_factory=dict)
    input_data: dict[str, Any] = Field(default_factory=dict)
    output_data: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    idempotency_key: str | None = None
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    started_at: str | None = None
    completed_at: str | None = None
    tokens_used: int = 0
    ttl: int = Field(
        default_factory=lambda: int(time.time()) + 86400 * 30  # 30 days
    )


class StateManager:
    """DynamoDB-backed state manager for agent tasks."""

    def __init__(self) -> None:
        self._dynamodb = boto3.resource("dynamodb", region_name=settings.aws_region)
        self._table = self._dynamodb.Table(settings.dynamodb_state_table)
        self._audit_table = self._dynamodb.Table(settings.dynamodb_audit_table)

    def _make_pk(self, agent_type: str) -> str:
        return f"AGENT#{agent_type}"

    def _make_sk(self, task: AgentTask) -> str:
        return f"TASK#{task.created_at}#{task.task_id}"

    async def create_task(self, task: AgentTask) -> AgentTask:
        """Create a new agent task. Checks idempotency if key provided."""
        if task.idempotency_key:
            existing = await self.get_by_idempotency_key(
                task.agent_type, task.idempotency_key
            )
            if existing:
                logger.info(
                    "Duplicate task detected",
                    idempotency_key=task.idempotency_key,
                    existing_task_id=existing.task_id,
                )
                return existing

        item = {
            "PK": self._make_pk(task.agent_type),
            "SK": self._make_sk(task),
            "GSI1PK": f"REPO#{task.context.get('repository', 'unknown')}",
            "GSI1SK": f"TASK#{task.created_at}",
            "GSI2PK": f"STATUS#{task.status.value}",
            "GSI2SK": f"TASK#{task.created_at}#{task.task_id}",
            **task.model_dump(),
        }

        self._table.put_item(Item=json.loads(json.dumps(item, default=str)))
        await self._audit_log("task.created", task)
        return task

    async def update_task(self, task: AgentTask) -> AgentTask:
        """Update an existing task's status and data."""
        self._table.update_item(
            Key={
                "PK": self._make_pk(task.agent_type),
                "SK": self._make_sk(task),
            },
            UpdateExpression=(
                "SET #status = :status, output_data = :output, "
                "started_at = :started, completed_at = :completed, "
                "tokens_used = :tokens, #error = :error, "
                "GSI2PK = :gsi2pk"
            ),
            ExpressionAttributeNames={
                "#status": "status",
                "#error": "error",
            },
            ExpressionAttributeValues={
                ":status": task.status.value,
                ":output": task.output_data,
                ":started": task.started_at,
                ":completed": task.completed_at,
                ":tokens": task.tokens_used,
                ":error": task.error,
                ":gsi2pk": f"STATUS#{task.status.value}",
            },
        )
        await self._audit_log("task.updated", task)
        return task

    async def get_task(self, agent_type: str, task_id: str) -> AgentTask | None:
        """Retrieve a task by agent type and task ID."""
        response = self._table.query(
            KeyConditionExpression="PK = :pk",
            FilterExpression="task_id = :tid",
            ExpressionAttributeValues={
                ":pk": self._make_pk(agent_type),
                ":tid": task_id,
            },
        )
        items = response.get("Items", [])
        return AgentTask(**items[0]) if items else None

    async def get_by_idempotency_key(
        self, agent_type: str, key: str
    ) -> AgentTask | None:
        """Find a task by its idempotency key."""
        response = self._table.query(
            KeyConditionExpression="PK = :pk",
            FilterExpression="idempotency_key = :key",
            ExpressionAttributeValues={
                ":pk": self._make_pk(agent_type),
                ":key": key,
            },
        )
        items = response.get("Items", [])
        return AgentTask(**items[0]) if items else None

    async def get_tasks_by_status(self, status: TaskStatus) -> list[AgentTask]:
        """Get all tasks with a given status."""
        response = self._table.query(
            IndexName="GSI2-Status",
            KeyConditionExpression="GSI2PK = :pk",
            ExpressionAttributeValues={
                ":pk": f"STATUS#{status.value}",
            },
        )
        return [AgentTask(**item) for item in response.get("Items", [])]

    async def get_tasks_by_repository(self, repository: str) -> list[AgentTask]:
        """Get all tasks for a repository."""
        response = self._table.query(
            IndexName="GSI1-Repository",
            KeyConditionExpression="GSI1PK = :pk",
            ExpressionAttributeValues={
                ":pk": f"REPO#{repository}",
            },
            ScanIndexForward=False,
            Limit=50,
        )
        return [AgentTask(**item) for item in response.get("Items", [])]

    async def get_all_tasks_recent(self, hours: int = 24) -> list[AgentTask]:
        """Get all tasks from the last N hours (scan-based, use sparingly)."""
        cutoff = (
            datetime.now(timezone.utc)
            - __import__("datetime").timedelta(hours=hours)
        ).isoformat()
        response = self._table.scan(
            FilterExpression="created_at >= :cutoff",
            ExpressionAttributeValues={":cutoff": cutoff},
            Limit=200,
        )
        return [AgentTask(**item) for item in response.get("Items", [])]

    async def _audit_log(self, event_type: str, task: AgentTask) -> None:
        """Write an audit log entry."""
        try:
            self._audit_table.put_item(
                Item={
                    "PK": f"AUDIT#{task.agent_type}",
                    "SK": f"{datetime.now(timezone.utc).isoformat()}#{uuid.uuid4()}",
                    "eventType": event_type,
                    "taskId": task.task_id,
                    "agentType": task.agent_type,
                    "taskType": task.task_type,
                    "status": task.status.value,
                    "repository": task.context.get("repository", "unknown"),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "TTL": int(time.time()) + 86400 * 90,  # 90 days
                }
            )
        except Exception as e:
            logger.error("Failed to write audit log", error=str(e))


state_manager = StateManager()
