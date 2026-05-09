"""
GitHub Issues client.

Creates and updates GitHub issues for operational incidents.
"""
import logging
from dataclasses import dataclass
from typing import Optional, List, Dict, Any

import httpx

from config import get_config

logger = logging.getLogger(__name__)


@dataclass
class GitHubIssue:
    """Represents a GitHub issue."""
    id: str
    identifier: str
    title: str
    url: str
    status: str
    is_preview: bool = False


class GitHubIssuesClient:
    """GitHub Issues REST API client."""

    def __init__(self, token: str, owner: str, repo: str):
        self.owner = owner
        self.repo = repo
        self.client = httpx.AsyncClient(
            base_url="https://api.github.com",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=15,
        )

    async def create_issue(self, title: str, body: str, labels: Optional[List[str]] = None) -> GitHubIssue:
        payload = {
            "title": title,
            "body": body,
            "labels": labels or [],
        }

        r = await self.client.post(f"/repos/{self.owner}/{self.repo}/issues", json=payload)
        r.raise_for_status()
        return self._to_issue(r.json())

    async def update_issue(
        self,
        issue_number: int | str,
        title: Optional[str] = None,
        body: Optional[str] = None,
        labels: Optional[List[str]] = None,
        state: Optional[str] = None,
    ) -> GitHubIssue:
        payload: Dict[str, Any] = {}
        if title is not None:
            payload["title"] = title
        if body is not None:
            payload["body"] = body
        if labels is not None:
            payload["labels"] = labels
        if state is not None:
            payload["state"] = state

        r = await self.client.patch(f"/repos/{self.owner}/{self.repo}/issues/{issue_number}", json=payload)
        r.raise_for_status()
        return self._to_issue(r.json())

    async def comment_on_issue(self, issue_number: int | str, body: str):
        r = await self.client.post(
            f"/repos/{self.owner}/{self.repo}/issues/{issue_number}/comments",
            json={"body": body},
        )
        r.raise_for_status()
        return r.json()

    async def add_labels(self, issue_number: int | str, labels: List[str]):
        r = await self.client.post(
            f"/repos/{self.owner}/{self.repo}/issues/{issue_number}/labels",
            json={"labels": labels},
        )
        r.raise_for_status()
        return r.json()

    async def aclose(self):
        await self.client.aclose()

    def _to_issue(self, data: Dict[str, Any]) -> GitHubIssue:
        number = data.get("number")
        return GitHubIssue(
            id=str(number),
            identifier=f"#{number}",
            title=data.get("title", ""),
            url=data.get("html_url", ""),
            status=data.get("state", "open").title(),
            is_preview=False,
        )


_github_issues_client: Optional[GitHubIssuesClient] = None


def get_github_issues_client() -> GitHubIssuesClient:
    global _github_issues_client
    if _github_issues_client is None:
        config = get_config()
        github = config.github
        if not github.is_configured:
            raise RuntimeError("GitHub Issues provider not configured")
        _github_issues_client = GitHubIssuesClient(
            token=github.token,
            owner=github.owner,
            repo=github.repo,
        )
    return _github_issues_client