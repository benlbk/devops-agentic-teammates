"""Agent state management using DynamoDB."""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any

import boto3
import structlog
from boto3.dynamodb.conditions import Key
from pydantic import BaseModel, Field

from shared.config import settings

logger = structlog.get_logger()


# Genesis hash for the audit chain (NFR-2)
_AUDIT_GENESIS_HASH = "0" * 64


class TaskStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in-progress"
    AWAITING_APPROVAL = "awaiting-approval"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Project(BaseModel):
    """Represents a project with its configuration."""

    project_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    description: str = ""
    repository: str  # primary repo e.g. "benlbk/online-shopping-app"
    repositories: list[str] = Field(default_factory=list)  # all tracked repos
    default_branch: str = "main"
    environments: dict[str, Any] = Field(default_factory=dict)
    config: dict[str, Any] = Field(default_factory=dict)
    created_by: str = ""
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    updated_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


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

        self._table.put_item(Item=json.loads(json.dumps(item, default=str), parse_float=Decimal))
        await self._audit_log("task.created", task)
        return task

    async def update_task(self, task: AgentTask) -> AgentTask:
        """Update an existing task's status and data."""
        output = json.loads(json.dumps(task.output_data, default=str), parse_float=Decimal)
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
                ":output": output,
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
        kwargs = {
            "KeyConditionExpression": "PK = :pk",
            "FilterExpression": "task_id = :tid",
            "ExpressionAttributeValues": {
                ":pk": self._make_pk(agent_type),
                ":tid": task_id,
            },
        }
        while True:
            response = self._table.query(**kwargs)
            items = response.get("Items", [])
            if items:
                return AgentTask(**items[0])
            if "LastEvaluatedKey" not in response:
                return None
            kwargs["ExclusiveStartKey"] = response["LastEvaluatedKey"]

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
        tasks = []
        for item in response.get("Items", []):
            try:
                tasks.append(AgentTask(**item))
            except Exception:
                continue
        return tasks

    async def _audit_log(self, event_type: str, task: AgentTask) -> None:
        """Write a hash-chained, tamper-evident audit log entry (NFR-2).

        Each entry stores ``prev_hash`` (the hash of the previous entry for
        the same agent_type) plus a SHA-256 ``hash`` over its own canonical
        payload + ``prev_hash``. The per-agent chain head is tracked in a
        ``CHAIN#HEAD`` item; verification walks entries in order and
        recomputes the hash to detect tampering or deletion.
        """
        try:
            pk_chain = f"AUDIT#{task.agent_type}"
            head_key = {"PK": pk_chain, "SK": "CHAIN#HEAD"}
            head = self._audit_table.get_item(Key=head_key).get("Item") or {}
            prev_hash = head.get("hash", _AUDIT_GENESIS_HASH)
            seq = int(head.get("seq", 0)) + 1

            ts = datetime.now(timezone.utc).isoformat()
            entry_id = str(uuid.uuid4())
            payload = {
                "eventType": event_type,
                "taskId": task.task_id,
                "agentType": task.agent_type,
                "taskType": task.task_type,
                "status": task.status.value,
                "repository": task.context.get("repository", "unknown"),
                "timestamp": ts,
                "seq": seq,
                "prev_hash": prev_hash,
                "entry_id": entry_id,
            }
            canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
            entry_hash = hashlib.sha256(canonical.encode()).hexdigest()

            item = {
                "PK": pk_chain,
                "SK": f"ENTRY#{seq:012d}#{ts}#{entry_id}",
                **payload,
                "hash": entry_hash,
                "canonical": canonical,
                # No TTL: audit entries are immutable & permanent (NFR-2 / SOC2)
            }
            # ConditionExpression makes the put append-only — once an SK is
            # written, it cannot be overwritten by a later call.
            self._audit_table.put_item(
                Item=item,
                ConditionExpression="attribute_not_exists(PK) AND attribute_not_exists(SK)",
            )
            # Update chain head (head is mutable on purpose; verification
            # ignores it and walks the ENTRY# items in seq order).
            self._audit_table.put_item(Item={
                **head_key,
                "hash": entry_hash, "seq": seq,
                "last_event": event_type, "last_ts": ts,
            })
        except Exception as e:
            logger.error("Failed to write audit log", error=str(e))

    async def list_audit_entries(
        self, agent_type: str, limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Return audit chain entries for an agent_type in seq order."""
        try:
            resp = self._audit_table.query(
                KeyConditionExpression=Key("PK").eq(f"AUDIT#{agent_type}")
                & Key("SK").begins_with("ENTRY#"),
                Limit=limit,
                ScanIndexForward=True,
            )
            return [
                {k: (int(v) if isinstance(v, Decimal) else v)
                 for k, v in item.items()}
                for item in resp.get("Items", [])
            ]
        except Exception as e:
            logger.error("Failed to list audit entries", error=str(e))
            return []

    async def verify_audit_chain(
        self, agent_type: str, limit: int = 1000,
    ) -> dict[str, Any]:
        """Replay the chain & verify each hash. Returns a tamper report."""
        entries = await self.list_audit_entries(agent_type, limit=limit)
        prev_hash = _AUDIT_GENESIS_HASH
        expected_seq = 1
        tampered: list[dict[str, Any]] = []
        for e in entries:
            seq = int(e.get("seq", 0))
            if seq != expected_seq:
                tampered.append({"seq": seq, "expected_seq": expected_seq,
                                 "issue": "seq-gap-or-out-of-order"})
            if e.get("prev_hash") != prev_hash:
                tampered.append({"seq": seq, "issue": "prev-hash-mismatch",
                                 "expected_prev": prev_hash, "got": e.get("prev_hash")})
            payload = {
                "eventType": e.get("eventType"),
                "taskId": e.get("taskId"),
                "agentType": e.get("agentType"),
                "taskType": e.get("taskType"),
                "status": e.get("status"),
                "repository": e.get("repository"),
                "timestamp": e.get("timestamp"),
                "seq": seq,
                "prev_hash": e.get("prev_hash"),
                "entry_id": e.get("entry_id"),
            }
            canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
            recomputed = hashlib.sha256(canonical.encode()).hexdigest()
            if recomputed != e.get("hash"):
                tampered.append({"seq": seq, "issue": "hash-mismatch",
                                 "expected_hash": recomputed, "got": e.get("hash")})
            prev_hash = e.get("hash") or prev_hash
            expected_seq += 1
        return {
            "agent_type": agent_type,
            "entries_checked": len(entries),
            "tamper_count": len(tampered),
            "verified": len(tampered) == 0,
            "head_hash": prev_hash,
            "head_seq": expected_seq - 1,
            "issues": tampered[:20],
        }

    # ---- Project CRUD ----

    async def create_project(self, project: Project) -> Project:
        """Create a new project."""
        item = {
            "PK": "PROJECT",
            "SK": f"PROJECT#{project.project_id}",
            **project.model_dump(),
        }
        self._table.put_item(Item=json.loads(json.dumps(item, default=str)))
        return project

    async def get_project(self, project_id: str) -> Project | None:
        """Get a project by ID."""
        response = self._table.get_item(
            Key={"PK": "PROJECT", "SK": f"PROJECT#{project_id}"}
        )
        item = response.get("Item")
        return Project(**item) if item else None

    async def list_projects(self) -> list[Project]:
        """List all projects."""
        response = self._table.query(
            KeyConditionExpression="PK = :pk",
            ExpressionAttributeValues={":pk": "PROJECT"},
        )
        return [Project(**item) for item in response.get("Items", [])]

    async def update_project(self, project: Project) -> Project:
        """Update an existing project."""
        project.updated_at = datetime.now(timezone.utc).isoformat()
        item = {
            "PK": "PROJECT",
            "SK": f"PROJECT#{project.project_id}",
            **project.model_dump(),
        }
        self._table.put_item(Item=json.loads(json.dumps(item, default=str)))
        return project

    async def delete_project(self, project_id: str) -> bool:
        """Delete a project."""
        self._table.delete_item(
            Key={"PK": "PROJECT", "SK": f"PROJECT#{project_id}"}
        )
        return True


state_manager = StateManager()
