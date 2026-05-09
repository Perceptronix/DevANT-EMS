"""
GitHub Connector — real GitHub API integration.

Fetches contextual evidence around operational incidents:
  - Recent commits near the incident window
  - Merged PRs that touch affected services
  - Blame data for files near stack-trace locations

Requires GITHUB_TOKEN in environment.
Fails gracefully (returns empty context) when token is absent.
"""
from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import quote

logger = logging.getLogger(__name__)

_GITHUB_API = "https://api.github.com"


def _parse_repo(repo_url: str) -> Optional[tuple[str, str]]:
    """Extract (owner, repo) from a github.com URL or 'owner/repo' string."""
    # https://github.com/owner/repo or https://github.com/owner/repo.git
    m = re.match(r"https?://github\.com/([^/]+)/([^/]+?)(?:\.git)?$", repo_url)
    if m:
        return m.group(1), m.group(2)
    # owner/repo shorthand
    m = re.match(r"^([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)$", repo_url)
    if m:
        return m.group(1), m.group(2)
    return None


class GitHubConnector:
    """
    Lightweight GitHub API client for operational context enrichment.

    All methods return empty lists / dicts when the token is missing or the
    API call fails — the orchestrator is never blocked by connector errors.
    """

    def __init__(self, token: Optional[str] = None):
        self.token = token or os.environ.get("GITHUB_TOKEN", "")
        self._headers: Dict[str, str] = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self.token:
            self._headers["Authorization"] = f"Bearer {self.token}"

    @property
    def is_configured(self) -> bool:
        return bool(self.token)

    # ------------------------------------------------------------------
    # Public enrichment methods
    # ------------------------------------------------------------------

    def get_recent_commits(
        self,
        repo_url: str,
        since_hours: int = 24,
        max_commits: int = 20,
    ) -> List[Dict[str, Any]]:
        """
        Return commits pushed in the last `since_hours` hours.

        Each dict: {sha, message, author, date, files_changed, url}
        """
        if not self.is_configured:
            return []

        parsed = _parse_repo(repo_url)
        if not parsed:
            return []
        owner, repo = parsed

        since = (datetime.now(timezone.utc) - timedelta(hours=since_hours)).isoformat()
        commits = self._get(
            f"/repos/{owner}/{repo}/commits",
            params={"since": since, "per_page": max_commits},
        )
        if not isinstance(commits, list):
            return []

        out: List[Dict[str, Any]] = []
        for c in commits[:max_commits]:
            commit = c.get("commit", {})
            author = commit.get("author", {})
            out.append({
                "sha": c.get("sha", "")[:12],
                "message": commit.get("message", "").split("\n")[0][:120],
                "author": author.get("name", "unknown"),
                "date": author.get("date", ""),
                "url": c.get("html_url", ""),
            })

        logger.info(f"GitHub: {len(out)} recent commits for {owner}/{repo}")
        return out

    def get_recent_prs(
        self,
        repo_url: str,
        since_hours: int = 48,
        max_prs: int = 10,
    ) -> List[Dict[str, Any]]:
        """
        Return recently merged PRs.

        Each dict: {number, title, author, merged_at, base_branch, head_branch,
                    changed_files, url}
        """
        if not self.is_configured:
            return []

        parsed = _parse_repo(repo_url)
        if not parsed:
            return []
        owner, repo = parsed

        prs = self._get(
            f"/repos/{owner}/{repo}/pulls",
            params={"state": "closed", "sort": "updated", "direction": "desc", "per_page": 30},
        )
        if not isinstance(prs, list):
            return []

        cutoff = datetime.now(timezone.utc) - timedelta(hours=since_hours)
        out: List[Dict[str, Any]] = []
        for pr in prs:
            merged_at = pr.get("merged_at")
            if not merged_at:
                continue
            try:
                merged_dt = datetime.fromisoformat(merged_at.replace("Z", "+00:00"))
            except Exception:
                continue
            if merged_dt < cutoff:
                continue

            out.append({
                "number": pr.get("number"),
                "title": pr.get("title", "")[:100],
                "author": (pr.get("user") or {}).get("login", "unknown"),
                "merged_at": merged_at,
                "base_branch": (pr.get("base") or {}).get("ref", ""),
                "head_branch": (pr.get("head") or {}).get("ref", ""),
                "url": pr.get("html_url", ""),
                "changed_files": pr.get("changed_files", 0),
            })
            if len(out) >= max_prs:
                break

        logger.info(f"GitHub: {len(out)} recent merged PRs for {owner}/{repo}")
        return out

    def get_repo_languages(self, repo_url: str) -> Dict[str, int]:
        """Return language byte-counts, e.g. {'Python': 123456, 'TypeScript': 78900}."""
        if not self.is_configured:
            return {}
        parsed = _parse_repo(repo_url)
        if not parsed:
            return {}
        owner, repo = parsed
        result = self._get(f"/repos/{owner}/{repo}/languages")
        return result if isinstance(result, dict) else {}

    def get_repo_metadata(self, repo_url: str) -> Dict[str, Any]:
        """Return core repo metadata: description, topics, default_branch, etc."""
        parsed = _parse_repo(repo_url)
        if not parsed:
            return {}
        owner, repo = parsed
        result = self._get(f"/repos/{owner}/{repo}")
        if not isinstance(result, dict):
            return {}
        return {
            "name": result.get("name", ""),
            "description": result.get("description", ""),
            "default_branch": result.get("default_branch", "main"),
            "topics": result.get("topics", []),
            "language": result.get("language", ""),
            "stars": result.get("stargazers_count", 0),
            "forks": result.get("forks_count", 0),
            "open_issues": result.get("open_issues_count", 0),
            "private": result.get("private", False),
            "size_kb": result.get("size", 0),
        }

    def search_related_issues(
        self,
        repo_url: str,
        query: str,
        max_issues: int = 5,
    ) -> List[Dict[str, Any]]:
        """
        Search for related issues by query (e.g., error message, exception name).
        
        Returns list of matching issues with metadata.
        """
        if not self.is_configured:
            return []
        
        parsed = _parse_repo(repo_url)
        if not parsed:
            return []
        owner, repo = parsed
        
        # Clean up query to avoid special characters
        safe_query = query.split("\n")[0][:100]
        search_query = f"repo:{owner}/{repo} is:issue {safe_query}"
        
        result = self._get(
            "/search/issues",
            params={
                "q": search_query,
                "sort": "updated",
                "order": "desc",
                "per_page": max_issues,
            }
        )
        
        if not isinstance(result, dict):
            return []
        
        issues = result.get("items", [])
        out = []
        for issue in issues[:max_issues]:
            out.append({
                "number": issue.get("number"),
                "title": issue.get("title", ""),
                "url": issue.get("html_url", ""),
                "author": (issue.get("user") or {}).get("login", ""),
                "body": issue.get("body", "")[:500],
                "updated_at": issue.get("updated_at", ""),
                "state": issue.get("state", ""),
            })
        
        return out

    def search_prs_by_service(
        self,
        repo_url: str,
        services: List[str],
        since_hours: int = 48,
        max_prs: int = 5,
    ) -> List[Dict[str, Any]]:
        """
        Search for PRs that touch files in the given services/paths.
        
        Returns recently merged PRs affecting specified services.
        """
        if not self.is_configured or not services:
            return []
        
        parsed = _parse_repo(repo_url)
        if not parsed:
            return []
        owner, repo = parsed
        
        # Get recent merged PRs and filter by service mentions in title/files
        prs = self._get(
            f"/repos/{owner}/{repo}/pulls",
            params={
                "state": "closed",
                "sort": "updated",
                "direction": "desc",
                "per_page": 50,
            }
        )
        
        if not isinstance(prs, list):
            return []
        
        cutoff = datetime.now(timezone.utc) - timedelta(hours=since_hours)
        out = []
        
        for pr in prs:
            merged_at = pr.get("merged_at")
            if not merged_at:
                continue
            
            try:
                merged_dt = datetime.fromisoformat(merged_at.replace("Z", "+00:00"))
            except Exception:
                continue
            
            if merged_dt < cutoff:
                continue
            
            # Check if PR mentions any service
            title = pr.get("title", "").lower()
            body = (pr.get("body") or "").lower()
            pr_text = f"{title} {body}"
            
            service_match = any(
                service.lower() in pr_text for service in services
            )
            
            if service_match:
                out.append({
                    "number": pr.get("number"),
                    "title": pr.get("title", ""),
                    "url": pr.get("html_url", ""),
                    "author": (pr.get("user") or {}).get("login", ""),
                    "merged_at": merged_at,
                    "changed_files": pr.get("changed_files", 0),
                    "additions": pr.get("additions", 0),
                    "deletions": pr.get("deletions", 0),
                })
            
            if len(out) >= max_prs:
                break
        
        return out

    def get_deployments(
        self,
        repo_url: str,
        environment: str = "production",
        per_page: int = 10,
    ) -> List[Dict[str, Any]]:
        """
        Get recent deployments for a repo and environment.
        
        Returns list of deployment dicts: {id, sha, ref, environment, created_at, updated_at, creator_login, description, task}
        """
        if not self.is_configured:
            return []
        
        parsed = _parse_repo(repo_url)
        if not parsed:
            return []
        owner, repo = parsed
        
        deployments = self._get(
            f"/repos/{owner}/{repo}/deployments",
            params={"environment": environment, "per_page": per_page}
        )
        if not isinstance(deployments, list):
            return []
        
        out = []
        for d in deployments:
            out.append({
                "id": d.get("id"),
                "sha": d.get("sha", ""),
                "ref": d.get("ref", ""),
                "environment": d.get("environment", ""),
                "created_at": d.get("created_at", ""),
                "updated_at": d.get("updated_at", ""),
                "creator_login": (d.get("creator") or {}).get("login", ""),
                "description": d.get("description", ""),
                "task": d.get("task", ""),
            })
        
        return out

    def get_deployment_statuses(
        self,
        repo_url: str,
        deployment_id: int,
    ) -> List[Dict[str, Any]]:
        """
        Get statuses for a specific deployment.
        
        Returns list of status dicts: {id, state, log_url, description, environment, created_at, creator_login}
        Statuses are ordered newest-first.
        """
        if not self.is_configured:
            return []
        
        parsed = _parse_repo(repo_url)
        if not parsed:
            return []
        owner, repo = parsed
        
        statuses = self._get(
            f"/repos/{owner}/{repo}/deployments/{deployment_id}/statuses"
        )
        if not isinstance(statuses, list):
            return []
        
        out = []
        for s in statuses:
            out.append({
                "id": s.get("id"),
                "state": s.get("state", ""),
                "log_url": s.get("log_url", ""),
                "description": s.get("description", ""),
                "environment": s.get("environment", ""),
                "created_at": s.get("created_at", ""),
                "creator_login": (s.get("creator") or {}).get("login", ""),
            })
        
        return out

    def get_commit_diff(
        self,
        repo_url: str,
        sha: str,
    ) -> Dict[str, Any]:
        """
        Get commit metadata and file diff info.
        
        Returns dict: {sha, message, author_name, author_date, files_changed, additions, deletions, files}
        where files is a list of {filename, status, additions, deletions, patch}
        """
        if not self.is_configured:
            return {}
        
        parsed = _parse_repo(repo_url)
        if not parsed:
            return {}
        owner, repo = parsed
        
        result = self._get(f"/repos/{owner}/{repo}/commits/{sha}")
        if not isinstance(result, dict):
            return {}
        
        commit = result.get("commit", {})
        stats = result.get("stats", {})
        files = result.get("files", [])
        
        return {
            "sha": result.get("sha", ""),
            "message": commit.get("message", "").split("\n")[0] if commit.get("message") else "",
            "author_name": (commit.get("author") or {}).get("name", ""),
            "author_date": (commit.get("author") or {}).get("date", ""),
            "files_changed": len(files),
            "additions": stats.get("additions", 0),
            "deletions": stats.get("deletions", 0),
            "files": [
                {
                    "filename": f.get("filename", ""),
                    "status": f.get("status", ""),
                    "additions": f.get("additions", 0),
                    "deletions": f.get("deletions", 0),
                    "patch": f.get("patch", "")[:500],
                }
                for f in files[:50]
            ]
        }

    def get_workflow_runs(
        self,
        repo_url: str,
        branch: str = "main",
        per_page: int = 5,
    ) -> List[Dict[str, Any]]:
        """
        Get workflow runs (CI/CD) for a repo.
        
        Returns only failed or in_progress runs.
        Each dict: {id, name, status, conclusion, head_sha, head_branch, created_at, updated_at, html_url, logs_url}
        """
        if not self.is_configured:
            return []
        
        parsed = _parse_repo(repo_url)
        if not parsed:
            return []
        owner, repo = parsed
        
        result = self._get(
            f"/repos/{owner}/{repo}/actions/runs",
            params={"branch": branch, "per_page": per_page, "event": "push"}
        )
        if not isinstance(result, dict):
            return []
        
        runs = result.get("workflow_runs", [])
        out = []
        
        for run in runs:
            # Only include failed or in_progress runs
            if run.get("conclusion") == "failure" or run.get("status") == "in_progress":
                out.append({
                    "id": run.get("id"),
                    "name": run.get("name", ""),
                    "status": run.get("status", ""),
                    "conclusion": run.get("conclusion"),
                    "head_sha": run.get("head_sha", ""),
                    "head_branch": run.get("head_branch", ""),
                    "created_at": run.get("created_at", ""),
                    "updated_at": run.get("updated_at", ""),
                    "html_url": run.get("html_url", ""),
                    "logs_url": run.get("logs_url", ""),
                })
        
        return out

    def fetch_log_text(
        self,
        log_url: str,
        max_chars: int = 8000,
    ) -> str:
        """
        Fetch log text from a full URL (e.g., Vercel, Render, GitHub Actions logs).
        
        Returns decoded text, truncated to max_chars from the END (end has failure reason).
        Returns empty string on any error.
        """
        if not log_url:
            return ""
        
        try:
            import urllib.request
            import urllib.parse
            
            req = urllib.request.Request(log_url, headers=self._headers)
            with urllib.request.urlopen(req, timeout=10) as resp:
                text = resp.read().decode('utf-8', errors='replace')
                # Truncate from the end to preserve error messages
                if len(text) > max_chars:
                    text = text[-max_chars:]
                return text
        except Exception as exc:
            logger.warning(f"Failed to fetch log from {log_url}: {exc}")
            return ""

    # ------------------------------------------------------------------
    # Internal HTTP helper
    # ------------------------------------------------------------------

    def _get(
        self, path: str, params: Optional[Dict[str, Any]] = None
    ) -> Any:
        """Make a GET request to the GitHub API. Returns parsed JSON or {}."""
        try:
            import urllib.request
            import urllib.parse
            import json as _json

            url = _GITHUB_API + path
            if params:
                url += "?" + urllib.parse.urlencode(params)

            req = urllib.request.Request(url, headers=self._headers)
            with urllib.request.urlopen(req, timeout=10) as resp:
                return _json.loads(resp.read().decode())
        except Exception as exc:
            logger.warning(f"GitHub API {path} failed: {exc}")
            return {}
