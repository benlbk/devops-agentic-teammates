"""GitHub Personal Access Token integration for agent-to-GitHub communication."""

from __future__ import annotations

from typing import Any

import boto3
import httpx
import structlog

from shared.config import settings

logger = structlog.get_logger()


class GitHubClient:
    """GitHub PAT client for authenticated API access (personal free account)."""

    BASE_URL = "https://api.github.com"

    def __init__(self) -> None:
        self._token: str | None = None
        self._http = httpx.AsyncClient(
            base_url=self.BASE_URL,
            headers={"Accept": "application/vnd.github+json"},
            timeout=30.0,
        )

    async def _get_token(self) -> str:
        if self._token is None:
            if settings.github_token:
                self._token = settings.github_token
            else:
                secrets = boto3.client(
                    "secretsmanager", region_name=settings.aws_region
                )
                response = secrets.get_secret_value(
                    SecretId=settings.github_token_secret
                )
                self._token = response["SecretString"]
        return self._token

    async def _auth_headers(self) -> dict[str, str]:
        token = await self._get_token()
        return {"Authorization": f"Bearer {token}"}

    # ---- Repository Management ----

    async def create_repository(
        self, name: str, description: str = "", private: bool = False,
        auto_init: bool = True,
    ) -> dict[str, Any]:
        """Create a new GitHub repository under the authenticated user."""
        headers = await self._auth_headers()
        payload: dict[str, Any] = {
            "name": name,
            "description": description,
            "private": private,
            "auto_init": auto_init,
        }
        response = await self._http.post(
            "/user/repos",
            headers=headers,
            json=payload,
        )
        response.raise_for_status()
        return response.json()

    async def ensure_repository(
        self, owner: str, repo: str, description: str = "",
    ) -> dict[str, Any]:
        """Get existing repo or create it if it doesn't exist."""
        headers = await self._auth_headers()
        response = await self._http.get(
            f"/repos/{owner}/{repo}",
            headers=headers,
        )
        if response.status_code == 200:
            return response.json()
        # Repo doesn't exist, create it
        return await self.create_repository(
            name=repo, description=description, auto_init=True,
        )

    # ---- Repository Operations ----

    async def get_file_content(
        self, owner: str, repo: str, path: str, ref: str = "main",
    ) -> str:
        headers = await self._auth_headers()
        response = await self._http.get(
            f"/repos/{owner}/{repo}/contents/{path}",
            params={"ref": ref},
            headers=headers,
        )
        response.raise_for_status()
        import base64
        return base64.b64decode(response.json()["content"]).decode()

    async def create_branch(
        self, owner: str, repo: str, branch: str, from_ref: str = "main",
    ) -> dict[str, Any]:
        headers = await self._auth_headers()
        # Get SHA of source branch
        ref_response = await self._http.get(
            f"/repos/{owner}/{repo}/git/ref/heads/{from_ref}",
            headers=headers,
        )
        ref_response.raise_for_status()
        sha = ref_response.json()["object"]["sha"]

        response = await self._http.post(
            f"/repos/{owner}/{repo}/git/refs",
            headers=headers,
            json={"ref": f"refs/heads/{branch}", "sha": sha},
        )
        response.raise_for_status()
        return response.json()

    async def create_or_update_file(
        self, owner: str, repo: str, path: str, content: str,
        message: str, branch: str,
    ) -> dict[str, Any]:
        import base64
        headers = await self._auth_headers()

        # Check if file exists to get SHA
        sha = None
        try:
            existing = await self._http.get(
                f"/repos/{owner}/{repo}/contents/{path}",
                params={"ref": branch},
                headers=headers,
            )
            if existing.status_code == 200:
                sha = existing.json()["sha"]
        except Exception:
            pass

        body: dict[str, Any] = {
            "message": message,
            "content": base64.b64encode(content.encode()).decode(),
            "branch": branch,
        }
        if sha:
            body["sha"] = sha

        response = await self._http.put(
            f"/repos/{owner}/{repo}/contents/{path}",
            headers=headers,
            json=body,
        )
        response.raise_for_status()
        return response.json()

    # ---- Pull Request Operations ----

    async def create_pull_request(
        self, owner: str, repo: str, title: str, body: str,
        head: str, base: str = "main",
    ) -> dict[str, Any]:
        headers = await self._auth_headers()
        response = await self._http.post(
            f"/repos/{owner}/{repo}/pulls",
            headers=headers,
            json={"title": title, "body": body, "head": head, "base": base},
        )
        response.raise_for_status()
        return response.json()

    async def get_pull_request(
        self, owner: str, repo: str, pr_number: int,
    ) -> dict[str, Any]:
        headers = await self._auth_headers()
        response = await self._http.get(
            f"/repos/{owner}/{repo}/pulls/{pr_number}",
            headers=headers,
        )
        response.raise_for_status()
        return response.json()

    async def get_pr_diff(
        self, owner: str, repo: str, pr_number: int,
    ) -> str:
        headers = await self._auth_headers()
        headers["Accept"] = "application/vnd.github.v3.diff"
        response = await self._http.get(
            f"/repos/{owner}/{repo}/pulls/{pr_number}",
            headers=headers,
        )
        response.raise_for_status()
        return response.text

    async def create_review_comment(
        self, owner: str, repo: str, pr_number: int,
        body: str, commit_id: str, path: str, line: int,
    ) -> dict[str, Any]:
        headers = await self._auth_headers()
        response = await self._http.post(
            f"/repos/{owner}/{repo}/pulls/{pr_number}/comments",
            headers=headers,
            json={
                "body": body,
                "commit_id": commit_id,
                "path": path,
                "line": line,
            },
        )
        response.raise_for_status()
        return response.json()

    async def create_pr_review(
        self, owner: str, repo: str, pr_number: int,
        body: str, event: str = "COMMENT",
    ) -> dict[str, Any]:
        headers = await self._auth_headers()
        response = await self._http.post(
            f"/repos/{owner}/{repo}/pulls/{pr_number}/reviews",
            headers=headers,
            json={"body": body, "event": event},
        )
        response.raise_for_status()
        return response.json()

    async def create_issue_comment(
        self, owner: str, repo: str, issue_number: int, body: str,
    ) -> dict[str, Any]:
        headers = await self._auth_headers()
        response = await self._http.post(
            f"/repos/{owner}/{repo}/issues/{issue_number}/comments",
            headers=headers,
            json={"body": body},
        )
        response.raise_for_status()
        return response.json()

    # ---- Issue Operations ----

    async def get_issue(
        self, owner: str, repo: str, issue_number: int,
    ) -> dict[str, Any]:
        headers = await self._auth_headers()
        response = await self._http.get(
            f"/repos/{owner}/{repo}/issues/{issue_number}",
            headers=headers,
        )
        response.raise_for_status()
        return response.json()

    async def list_issues(
        self, owner: str, repo: str,
        labels: list[str] | None = None,
        state: str = "open",
        per_page: int = 30,
    ) -> list[dict[str, Any]]:
        headers = await self._auth_headers()
        params: dict[str, Any] = {"state": state, "per_page": per_page}
        if labels:
            params["labels"] = ",".join(labels)

        response = await self._http.get(
            f"/repos/{owner}/{repo}/issues",
            headers=headers,
            params=params,
        )
        response.raise_for_status()
        return response.json()

    async def create_issue(
        self, owner: str, repo: str, title: str, body: str,
        labels: list[str] | None = None,
        assignees: list[str] | None = None,
    ) -> dict[str, Any]:
        headers = await self._auth_headers()
        payload: dict[str, Any] = {"title": title, "body": body}
        if labels:
            payload["labels"] = labels
        if assignees:
            payload["assignees"] = assignees

        response = await self._http.post(
            f"/repos/{owner}/{repo}/issues",
            headers=headers,
            json=payload,
        )
        response.raise_for_status()
        return response.json()

    # ---- Release Operations ----

    async def create_release(
        self, owner: str, repo: str, tag_name: str, name: str,
        body: str, target: str = "main",
    ) -> dict[str, Any]:
        headers = await self._auth_headers()
        response = await self._http.post(
            f"/repos/{owner}/{repo}/releases",
            headers=headers,
            json={
                "tag_name": tag_name,
                "target_commitish": target,
                "name": name,
                "body": body,
            },
        )
        response.raise_for_status()
        return response.json()

    # ---- Workflow Operations ----

    async def get_workflow_runs(
        self, owner: str, repo: str, workflow_id: str | None = None,
        status: str | None = None, per_page: int = 30,
    ) -> list[dict[str, Any]]:
        headers = await self._auth_headers()
        params: dict[str, Any] = {"per_page": per_page}
        if status:
            params["status"] = status

        if workflow_id:
            url = f"/repos/{owner}/{repo}/actions/workflows/{workflow_id}/runs"
        else:
            url = f"/repos/{owner}/{repo}/actions/runs"

        response = await self._http.get(url, headers=headers, params=params)
        response.raise_for_status()
        return response.json().get("workflow_runs", [])

    async def close(self) -> None:
        await self._http.aclose()


github_client = GitHubClient()
