"""Tests for the Agent Orchestrator API."""

import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    with patch("orchestrator.main.state_manager") as mock_sm, \
         patch("orchestrator.main.event_publisher") as mock_ep, \
         patch("orchestrator.main.policy_engine") as mock_pe:
        mock_sm.create_task = AsyncMock()
        mock_sm.update_task = AsyncMock()
        mock_sm.get_task = AsyncMock(return_value=None)
        mock_sm.get_all_tasks_recent = AsyncMock(return_value=[])
        mock_ep.publish_task_requested = AsyncMock()
        mock_ep.publish_task_completed = AsyncMock()
        from orchestrator.main import app
        yield TestClient(app)


def test_health_endpoint(client):
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"


def test_info_endpoint(client):
    response = client.get("/info")
    assert response.status_code == 200
    data = response.json()
    assert "agents" in data
    assert "version" in data


def test_create_task(client):
    with patch("orchestrator.main.state_manager") as mock_sm:
        from shared.state import AgentTask, TaskStatus
        mock_task = AgentTask(
            agent_type="code-build",
            task_type="code-review",
            status=TaskStatus.PENDING,
            context={"repository": "org/repo"},
        )
        mock_sm.create_task = AsyncMock(return_value=mock_task)

        response = client.post("/api/tasks", json={
            "agent_type": "code-build",
            "task_type": "code-review",
            "context": {"repository": "org/repo"},
        })
        assert response.status_code == 202


def test_github_webhook_ping(client):
    response = client.post(
        "/webhooks/github",
        json={"zen": "testing"},
        headers={"X-GitHub-Event": "ping"},
    )
    assert response.status_code == 200


def test_github_webhook_pr_opened(client):
    with patch("orchestrator.main.execute_agent_task") as mock_exec:
        mock_exec.return_value = None
        response = client.post(
            "/webhooks/github",
            json={
                "action": "opened",
                "pull_request": {
                    "number": 42,
                    "title": "Test PR",
                    "user": {"login": "dev"},
                    "head": {"ref": "feat/test", "sha": "abc123"},
                    "base": {"ref": "main"},
                },
                "repository": {
                    "full_name": "org/repo",
                    "default_branch": "main",
                },
            },
            headers={"X-GitHub-Event": "pull_request"},
        )
        assert response.status_code in (200, 202)


def test_dora_metrics(client):
    with patch("orchestrator.main.state_manager") as mock_sm:
        mock_sm.get_all_tasks_recent = AsyncMock(return_value=[])
        response = client.get("/api/metrics/dora")
        assert response.status_code == 200
        data = response.json()
        assert "deployment_frequency" in data


def test_agent_metrics(client):
    with patch("orchestrator.main.state_manager") as mock_sm:
        mock_sm.get_all_tasks_recent = AsyncMock(return_value=[])
        response = client.get("/api/metrics/agents")
        assert response.status_code == 200
        data = response.json()
        assert "agents" in data
