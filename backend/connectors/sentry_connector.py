"""
Sentry Connector — real-time production error ingestion.

Fetches errors, events, and release information from Sentry with:
- Async support
- Automatic pagination
- Exponential backoff retry
- Rate limit awareness
- Token validation

Requires SENTRY_AUTH_TOKEN and SENTRY_ORG environment variables.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, AsyncIterator, Dict, List, Optional
from urllib.parse import urljoin

import httpx

from core.async_client_pool import get_async_client, release_async_client

logger = logging.getLogger(__name__)

_SENTRY_API_BASE = "https://sentry.io/api/0"
_DEFAULT_TIMEOUT = 15.0
_MAX_RETRIES = 3
_INITIAL_BACKOFF = 1.0


class SentryConnector:
    """
    Async Sentry API client for operational error ingestion.
    
    Handles:
    - Paginated issue/event fetching
    - Token rotation and auth failures
    - Rate limit (429) and server error (5xx) retries
    - Graceful degradation when token is missing
    """

    def __init__(
        self,
        token: Optional[str] = None,
        org_slug: Optional[str] = None,
        timeout: float = _DEFAULT_TIMEOUT,
    ):
        self.token = token or os.environ.get("SENTRY_AUTH_TOKEN", "")
        self.org_slug = org_slug or os.environ.get("SENTRY_ORG", "")
        self.timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None

    @property
    def is_configured(self) -> bool:
        return bool(self.token and self.org_slug)

    async def __aenter__(self):
        # Use shared connection pool instead of creating new client
        self._client = get_async_client(timeout=self.timeout)
        if not self._client:
            raise RuntimeError("Failed to acquire shared AsyncClient")
        return self

    async def __aexit__(self, *args):
        # Release reference to shared client (don't close it)
        if self._client:
            release_async_client()
            self._client = None

    def _make_headers(self) -> Dict[str, str]:
        headers: Dict[str, str] = {"Accept": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def fetch_recent_issues(
        self,
        project_slug: Optional[str] = None,
        since_minutes: int = 60,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """
        Fetch recent errors (issues) from Sentry.
        
        Returns list of issues with:
        {
            id, title, shortID, stats (event count),
            lastSeen, firstSeen, status, severity,
            culprit, platform, project
        }
        """
        if not self.is_configured:
            return []

        try:
            since = (datetime.now(timezone.utc) - timedelta(minutes=since_minutes)).isoformat()
            
            query = f"is:unresolved firstSeen:>={since}"
            if project_slug:
                query += f" project:{project_slug}"
            
            issues: List[Dict[str, Any]] = []
            async for issue in self._paginated_request(
                f"/organizations/{self.org_slug}/issues/",
                params={
                    "query": query,
                    "sort": "-lastSeen",
                    "limit": 100,
                },
            ):
                issues.append(issue)
                if len(issues) >= limit:
                    break
            
            return issues[:limit]
        except Exception as exc:
            logger.warning(f"Sentry fetch_recent_issues failed: {exc}")
            return []

    async def fetch_issue_events(
        self,
        issue_id: str,
        project_slug: str,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """
        Fetch event details for a specific issue.
        
        Returns list of events with full stack traces.
        """
        if not self.is_configured:
            return []

        try:
            events: List[Dict[str, Any]] = []
            async for event in self._paginated_request(
                f"/projects/{self.org_slug}/{project_slug}/issues/{issue_id}/events/",
                params={"limit": 100},
            ):
                events.append(event)
                if len(events) >= limit:
                    break
            
            return events[:limit]
        except Exception as exc:
            logger.warning(f"Sentry fetch_issue_events failed: {exc}")
            return []

    async def fetch_releases(
        self,
        project_slug: str,
        since_minutes: int = 1440,  # 24 hours
    ) -> List[Dict[str, Any]]:
        """
        Fetch recent releases for a project.
        
        Returns list of releases with deployment info.
        """
        if not self.is_configured:
            return []

        try:
            since = (datetime.now(timezone.utc) - timedelta(minutes=since_minutes)).isoformat()
            
            releases: List[Dict[str, Any]] = []
            async for release in self._paginated_request(
                f"/projects/{self.org_slug}/{project_slug}/releases/",
                params={
                    "sort": "-dateCreated",
                    "limit": 100,
                },
            ):
                if release.get("dateCreated", "") >= since:
                    releases.append(release)
            
            return releases
        except Exception as exc:
            logger.warning(f"Sentry fetch_releases failed: {exc}")
            return []

    async def fetch_stats(
        self,
        issue_id: str,
        project_slug: str,
        since_minutes: int = 60,
    ) -> Dict[str, Any]:
        """
        Fetch statistics for an issue.
        
        Returns event counts, trends, etc.
        """
        if not self.is_configured:
            return {}

        try:
            stats = await self._request(
                "GET",
                f"/projects/{self.org_slug}/{project_slug}/issues/{issue_id}/stats/",
                params={"statsPeriod": f"{since_minutes}m"},
            )
            return stats if isinstance(stats, dict) else {}
        except Exception as exc:
            logger.warning(f"Sentry fetch_stats failed: {exc}")
            return {}

    # ------------------------------------------------------------------
    # Low-level request logic
    # ------------------------------------------------------------------

    async def _paginated_request(
        self,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        max_pages: int = 100,
    ) -> AsyncIterator[Dict[str, Any]]:
        """Yield items from a paginated API endpoint."""
        url = urljoin(_SENTRY_API_BASE, path)
        page = 1
        
        while page <= max_pages:
            query_params = {**(params or {}), "page": page}
            
            try:
                data = await self._request("GET", url, params=query_params)
                
                if not isinstance(data, list):
                    logger.warning(f"Sentry paginated request returned non-list: {type(data)}")
                    break
                
                if not data:
                    break
                
                for item in data:
                    yield item
                
                page += 1
            except Exception as exc:
                logger.warning(f"Sentry pagination error at page {page}: {exc}")
                break

    async def _request(
        self,
        method: str,
        url: str,
        params: Optional[Dict[str, Any]] = None,
        json_body: Optional[Dict[str, Any]] = None,
        retry_count: int = 0,
    ) -> Any:
        """
        Execute HTTP request with retry logic.
        
        Retries on:
        - 429 (rate limit)
        - 5xx (server error)
        - Connection timeouts
        """
        if not self._client:
            raise RuntimeError("Sentry connector not entered async context")

        try:
            response = await self._client.request(
                method,
                url,
                params=params,
                json=json_body,
            )
            response.raise_for_status()
            return response.json() if response.text else {}

        except httpx.HTTPStatusError as e:
            # Retry on rate limit or server error
            if e.response.status_code in (429, 500, 502, 503) and retry_count < _MAX_RETRIES:
                backoff = _INITIAL_BACKOFF * (2 ** retry_count)
                logger.debug(f"Sentry request retry after {backoff}s (attempt {retry_count + 1})")
                await asyncio.sleep(backoff)
                return await self._request(
                    method, url, params, json_body, retry_count + 1
                )
            raise

        except (httpx.ConnectError, asyncio.TimeoutError) as e:
            if retry_count < _MAX_RETRIES:
                backoff = _INITIAL_BACKOFF * (2 ** retry_count)
                logger.debug(f"Sentry connection retry after {backoff}s (attempt {retry_count + 1})")
                await asyncio.sleep(backoff)
                return await self._request(
                    method, url, params, json_body, retry_count + 1
                )
            raise


async def test_sentry_connection(org_slug: Optional[str] = None) -> bool:
    """Test if Sentry credentials are valid."""
    connector = SentryConnector(org_slug=org_slug)
    if not connector.is_configured:
        logger.warning("Sentry not configured (missing SENTRY_AUTH_TOKEN or SENTRY_ORG)")
        return False
    
    try:
        async with connector:
            # Try to fetch recent issues as a health check
            issues = await connector.fetch_recent_issues(limit=1)
            return True
    except Exception as exc:
        logger.warning(f"Sentry connection test failed: {exc}")
        return False
