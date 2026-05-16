"""Tests for the GitHub Client."""

import pytest
from unittest.mock import MagicMock, patch, AsyncMock


@pytest.fixture
def github_client():
    with patch("shared.github_client.Github") as mock_gh:
        mock_repo = MagicMock()
        mock_gh.return_value.get_repo.return_value = mock_repo
        from shared.github_client import GitHubClient
        client = GitHubClient()
        yield client, mock_repo


def test_get_file_content(github_client):
    client, mock_repo = github_client
    mock_file = MagicMock()
    mock_file.decoded_content = b"file content here"
    mock_repo.get_contents.return_value = mock_file

    content = client.get_file_content("org/repo", "src/main.py")
    assert content == "file content here"


def test_create_branch(github_client):
    client, mock_repo = github_client
    mock_ref = MagicMock()
    mock_ref.object.sha = "abc123"
    mock_repo.get_git_ref.return_value = mock_ref
    mock_repo.create_git_ref = MagicMock()

    client.create_branch("org/repo", "feat/new-branch", "main")
    mock_repo.create_git_ref.assert_called_once()


def test_create_pull_request(github_client):
    client, mock_repo = github_client
    mock_pr = MagicMock()
    mock_pr.number = 42
    mock_pr.html_url = "https://github.com/org/repo/pull/42"
    mock_repo.create_pull.return_value = mock_pr

    result = client.create_pull_request(
        "org/repo", "Test PR", "Body", "feat/branch", "main"
    )
    assert result["number"] == 42


def test_get_pr_diff(github_client):
    client, mock_repo = github_client
    mock_pr = MagicMock()
    mock_file = MagicMock()
    mock_file.filename = "src/app.py"
    mock_file.patch = "@@ -1 +1 @@\n-old\n+new"
    mock_pr.get_files.return_value = [mock_file]
    mock_repo.get_pull.return_value = mock_pr

    diff = client.get_pr_diff("org/repo", 1)
    assert "src/app.py" in diff


def test_create_issue(github_client):
    client, mock_repo = github_client
    mock_issue = MagicMock()
    mock_issue.number = 10
    mock_issue.html_url = "https://github.com/org/repo/issues/10"
    mock_repo.create_issue.return_value = mock_issue

    result = client.create_issue("org/repo", "Bug", "Description", ["bug"])
    assert result["number"] == 10


def test_create_release(github_client):
    client, mock_repo = github_client
    mock_release = MagicMock()
    mock_release.html_url = "https://github.com/org/repo/releases/v1.0.0"
    mock_release.tag_name = "v1.0.0"
    mock_repo.create_git_release.return_value = mock_release

    result = client.create_release("org/repo", "v1.0.0", "Release v1.0.0", "Changelog")
    assert result["tag"] == "v1.0.0"
