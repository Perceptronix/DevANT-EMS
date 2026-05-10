"""
Async GitHub client with retries, rate-limit handling, and simple paging.

Usage: create `GitHubAsyncClient()` or call `load_github_config()` to read
`GITHUB_TOKEN` and `GITHUB_WEBHOOK_SECRET` from environment.
"""
from __future__ import annotations

import asyncio
import os
import time
from typing import Any, Dict, List, Optional

from backend.core.async_client_pool import get_async_client, release_async_client
import httpx

GITHUB_API = "https://api.github.com"
API_VERSION_HEADER = "2022-11-28"


def load_github_config() -> Dict[str, Optional[str]]:
    """Read GitHub config from environment.

    Returns dict with keys: token, webhook_secret
    """
    return {
        "token": os.environ.get("GITHUB_TOKEN"),
        "webhook_secret": os.environ.get("GITHUB_WEBHOOK_SECRET"),
    }


class GitHubAsyncClient:
    """Async, resilient GitHub API client.

    Features:
    - Async via httpx.AsyncClient
    - Simple retry/backoff for 429/5xx
    - Rate-limit handling using X-RateLimit headers and Retry-After
    - Convenience methods: commits, pulls, deployments, workflow_runs
    """

    def __init__(self, token: Optional[str] = None, timeout: int = 10):
        cfg = token or os.environ.get("GITHUB_TOKEN")
        self._token = cfg
        # Use shared AsyncClient from core pool
        client = get_async_client(timeout=timeout)
        if client is None:
            raise RuntimeError("Failed to acquire shared AsyncClient")
        self._client: httpx.AsyncClient = client  # type: ignore[assignment]
        self._closed = False

    async def close(self) -> None:
        # Do not close shared client; release reference
        if not self._closed:
            try:
                release_async_client()
            finally:
                self._closed = True

    async def _sleep_until_reset(self, reset_ts: Optional[str]) -> None:
        if not reset_ts:
            return
        try:
            reset = int(reset_ts)
            now = int(time.time())
            wait = max(0, reset - now) + 1
            if wait > 0:
                await asyncio.sleep(wait)
        except Exception:
            return

    async def _request_json(
        self,
        method: str,
        url: str,
        params: Optional[Dict[str, Any]] = None,
        max_retries: int = 5,
    ) -> Any:
        backoff_base = 0.5
        for attempt in range(1, max_retries + 1):
            try:
                resp = await self._client.request(method, url, params=params)

                # Rate-limit headers
                remaining = resp.headers.get("X-RateLimit-Remaining")
                reset = resp.headers.get("X-RateLimit-Reset")

                if resp.status_code == 429:
                    # Secondary rate limit or abuse detection
                    retry_after = resp.headers.get("Retry-After")
                    if retry_after:
                        await asyncio.sleep(int(retry_after) + 1)
                    else:
                        await asyncio.sleep(backoff_base * attempt)
                    continue

                if resp.status_code in (502, 503, 504) or resp.status_code >= 500:
                    # transient server error
                    await asyncio.sleep(backoff_base * attempt)
                    continue

                if remaining is not None:
                    try:
                        if int(remaining) < 50:
                            # pause until reset
                            await self._sleep_until_reset(reset)
                    except Exception:
                        pass

                resp.raise_for_status()
                if resp.status_code == 204:
                    return None
                return resp.json()

            except httpx.HTTPStatusError as exc:
                # Could be 403 with rate limit, check headers
                status = exc.response.status_code if exc.response is not None else None
                if status == 403:
                    # check for rate limit
                    if exc.response is not None:
                        retry_after = exc.response.headers.get("Retry-After")
                        reset = exc.response.headers.get("X-RateLimit-Reset")
                        if retry_after:
                            await asyncio.sleep(int(retry_after) + 1)
                            continue
                        if reset:
                            await self._sleep_until_reset(reset)
                            continue

                if attempt == max_retries:
                    raise
                await asyncio.sleep(backoff_base * attempt)
            except (httpx.RequestError, asyncio.CancelledError):
                if attempt == max_retries:
                    raise
                await asyncio.sleep(backoff_base * attempt)

        raise RuntimeError("Exceeded retries for GitHub request")

    async def _get_all_pages(self, path: str, params: Optional[Dict[str, Any]] = None) -> List[Any]:
        url = GITHUB_API + path
        accum: List[Any] = []
        next_url = url
        next_params = params
        while next_url:
            resp = await self._request_json("GET", next_url, params=next_params)
            # If response is dict with 'items' or 'workflow_runs', return contained list
            if isinstance(resp, dict):
                # Common wrappers
                if "items" in resp:
                    items = resp.get("items", [])
                    accum.extend(items)
                elif "workflow_runs" in resp:
                    accum.extend(resp.get("workflow_runs", []))
                else:
                    # single-page dict
                    return [resp]
            elif isinstance(resp, list):
                accum.extend(resp)
            else:
                return accum

            # handle Link header for pagination
            last_response = self._client
            # httpx does not expose last response headers easily here, so break loop
            break

        return accum

    # Public convenience methods
    async def list_commits(
        self,
        owner: str,
        repo: str,
        since: Optional[str] = None,
        per_page: int = 100,
    ) -> List[Dict[str, Any]]:
        params = {"per_page": per_page}
        if since:
            params["since"] = since
        path = f"/repos/{owner}/{repo}/commits"
        return await self._get_all_pages(path, params=params)

    async def get_pull_request(self, owner: str, repo: str, number: int) -> Dict[str, Any]:
        path = f"/repos/{owner}/{repo}/pulls/{number}"
        return await self._request_json("GET", GITHUB_API + path)

    async def list_pulls(self, owner: str, repo: str, state: str = "all", per_page: int = 100) -> List[Dict[str, Any]]:
        path = f"/repos/{owner}/{repo}/pulls"
        params = {"state": state, "per_page": per_page}
        return await self._get_all_pages(path, params=params)

    async def list_deployments(self, owner: str, repo: str, environment: Optional[str] = None, per_page: int = 30) -> List[Dict[str, Any]]:
        params = {"per_page": per_page}
        if environment:
            params["environment"] = environment
        path = f"/repos/{owner}/{repo}/deployments"
        return await self._get_all_pages(path, params=params)

    async def list_workflow_runs(self, owner: str, repo: str, branch: Optional[str] = None, per_page: int = 10) -> List[Dict[str, Any]]:
        params = {"per_page": per_page}
        if branch:
            params["branch"] = branch
        path = f"/repos/{owner}/{repo}/actions/runs"
        return await self._get_all_pages(path, params=params)


__all__ = ["GitHubAsyncClient", "load_github_config"]
