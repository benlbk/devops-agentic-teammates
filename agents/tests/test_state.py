"""Tests for the State Manager (mocked DynamoDB)."""

import pytest
from unittest.mock import MagicMock, patch
from shared.state import AgentTask, TaskStatus, StateManager


@pytest.fixture
def mock_dynamo():
    with patch("shared.state.boto3") as mock_boto:
        mock_resource = MagicMock()
        mock_table = MagicMock()
        mock_audit_table = MagicMock()
        mock_resource.Table.side_effect = lambda name: (
            mock_table if "state" in name else mock_audit_table
        )
        mock_boto.resource.return_value = mock_resource
        yield mock_table, mock_audit_table


@pytest.fixture
def state_manager(mock_dynamo):
    with patch("shared.config.settings") as mock_settings:
        mock_settings.aws_region = "ap-southeast-1"
        mock_settings.dynamodb_state_table = "agent-state"
        mock_settings.dynamodb_audit_table = "agent-audit"
        return StateManager()


@pytest.mark.asyncio
async def test_create_task(state_manager, mock_dynamo):
    table, audit = mock_dynamo
    table.put_item = MagicMock()
    audit.put_item = MagicMock()

    task = AgentTask(
        agent_type="code-build",
        task_type="code-review",
        context={"repository": "org/repo", "prNumber": 1},
    )

    result = await state_manager.create_task(task)
    assert result.task_id == task.task_id
    assert result.status == TaskStatus.PENDING
    table.put_item.assert_called_once()
    audit.put_item.assert_called_once()


@pytest.mark.asyncio
async def test_update_task(state_manager, mock_dynamo):
    table, audit = mock_dynamo
    table.update_item = MagicMock()
    audit.put_item = MagicMock()

    task = AgentTask(
        agent_type="code-build",
        task_type="code-review",
        status=TaskStatus.COMPLETED,
    )

    result = await state_manager.update_task(task)
    assert result.status == TaskStatus.COMPLETED
    table.update_item.assert_called_once()


@pytest.mark.asyncio
async def test_get_task_found(state_manager, mock_dynamo):
    table, _ = mock_dynamo
    table.query.return_value = {
        "Items": [{
            "task_id": "test-123",
            "agent_type": "code-build",
            "task_type": "code-review",
            "status": "completed",
            "context": {},
            "created_at": "2026-01-01T00:00:00Z",
        }]
    }

    result = await state_manager.get_task("code-build", "test-123")
    assert result is not None
    assert result.task_id == "test-123"


@pytest.mark.asyncio
async def test_get_task_not_found(state_manager, mock_dynamo):
    table, _ = mock_dynamo
    table.query.return_value = {"Items": []}

    result = await state_manager.get_task("code-build", "nonexistent")
    assert result is None


@pytest.mark.asyncio
async def test_idempotency_key_dedup(state_manager, mock_dynamo):
    table, audit = mock_dynamo
    table.query.return_value = {
        "Items": [{
            "task_id": "existing-task",
            "agent_type": "code-build",
            "task_type": "code-review",
            "status": "completed",
            "context": {},
            "idempotency_key": "key-1",
            "created_at": "2026-01-01T00:00:00Z",
        }]
    }
    table.put_item = MagicMock()

    task = AgentTask(
        agent_type="code-build",
        task_type="code-review",
        idempotency_key="key-1",
    )

    result = await state_manager.create_task(task)
    assert result.task_id == "existing-task"
    table.put_item.assert_not_called()
