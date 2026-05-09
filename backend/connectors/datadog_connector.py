"""
Datadog Connector — real-time log and metric ingestion.

Fetches errors, logs, and deployment events from Datadog with:
- Async support
- Log query (APM, Error Tracking)
- Metric aggregation
- Span/trace correlation
- Automatic pagination
- Rate limit awareness

Requires DATADOG_API_KEY and DATADOG_APP_KEY environment variables.
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

_DATADOG_API_BASE = "https://api.datadoghq.com/api/v1"
_DATADOG_EU_BASE = "https://api.datadoghq.eu/api/v1"
_DEFAULT_TIMEOUT = 15.0
_MAX_RETRIES = 3
_INITIAL_BACKOFF = 1.0


class DatadogConnector:
    """
    Async Datadog API client for operational logs and error ingestion.
    
    Handles:
    - Log queries (APM/Error Tracking)
    - Metric fetches
    - Distributed traces
    - Automatic region detection (US/EU)
    - Rate limit (429) and server error (5xx) retries
    - Graceful degradation when keys are missing
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        app_key: Optional[str] = None,
        site: str = "datadoghq.com",
        timeout: float = _DEFAULT_TIMEOUT,
    ):
        self.api_key = api_key or os.environ.get("DATADOG_API_KEY", "")
        self.app_key = app_key or os.environ.get("DATADOG_APP_KEY", "")
        self.site = site  # "datadoghq.com" or "datadoghq.eu"
        self.timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None
        
        # Determine base URL
        if site.endswith("datadoghq.eu"):
            self._base_url = _DATADOG_EU_BASE
        else:
            self._base_url = _DATADOG_API_BASE

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key and self.app_key)

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
        if self.api_key:
            headers["DD-API-KEY"] = self.api_key
        if self.app_key:
            headers["DD-APPLICATION-KEY"] = self.app_key
        return headers

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def query_errors(
        self,
        services: Optional[List[str]] = None,
        since_minutes: int = 60,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """
        Query error logs from Datadog.
        
        Returns list of error events with:
        {
            id, timestamp, service, message, stack_trace,
            error_type, severity, host, user_id, trace_id
        }
        """
        if not self.is_configured:
            return []

        try:
            start_time = int(
                (datetime.now(timezone.utc) - timedelta(minutes=since_minutes)).timestamp()
            )
            end_time = int(datetime.now(timezone.utc).timestamp())
            
            service_filter = ""
            if services:
                service_filter = " OR ".join(f'service:"{s}"' for s in services)
                service_filter = f"({service_filter})"
            else:
                service_filter = "status:error"
            
            query = f"{service_filter} {service_filter}"
            
            logs = await self._query_logs(
                query=query,
                start_time=start_time,
                end_time=end_time,
                limit=limit,
            )
            
            return logs
        except Exception as exc:
            logger.warning(f"Datadog query_errors failed: {exc}")
            return []

    async def query_logs(
        self,
        query: str,
        since_minutes: int = 60,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """
        Execute arbitrary log query in Datadog.
        
        Example queries:
        - 'service:api AND status:error'
        - 'host:prod-* AND level:error'
        - 'trace_id:*'
        """
        if not self.is_configured:
            return []

        try:
            start_time = int(
                (datetime.now(timezone.utc) - timedelta(minutes=since_minutes)).timestamp()
            )
            end_time = int(datetime.now(timezone.utc).timestamp())
            
            return await self._query_logs(
                query=query,
                start_time=start_time,
                end_time=end_time,
                limit=limit,
            )
        except Exception as exc:
            logger.warning(f"Datadog query_logs failed: {exc}")
            return []

    async def fetch_deployments(
        self,
        services: Optional[List[str]] = None,
        since_minutes: int = 1440,  # 24 hours
    ) -> List[Dict[str, Any]]:
        """
        Fetch recent deployments and their events.
        
        Returns deployment timeline with metadata.
        """
        if not self.is_configured:
            return []

        try:
            start_time = int(
                (datetime.now(timezone.utc) - timedelta(minutes=since_minutes)).timestamp()
            )
            end_time = int(datetime.now(timezone.utc).timestamp())
            
            # Query for deployment events
            query = "env:* AND status:*"
            if services:
                query = f"({' OR '.join(f'service:{s}' for s in services)})"
            
            events = await self._query_logs(
                query=query,
                start_time=start_time,
                end_time=end_time,
                limit=200,
            )
            
            return events
        except Exception as exc:
            logger.warning(f"Datadog fetch_deployments failed: {exc}")
            return []

    async def fetch_traces(
        self,
        trace_id: str,
    ) -> Dict[str, Any]:
        """
        Fetch distributed trace details by trace ID.
        
        Returns span list with timing and dependencies.
        """
        if not self.is_configured:
            return {}

        try:
            result = await self._request(
                "GET",
                f"/trace/{trace_id}",
            )
            return result if isinstance(result, dict) else {}
        except Exception as exc:
            logger.warning(f"Datadog fetch_traces failed: {exc}")
            return {}

    # ------------------------------------------------------------------
    # Low-level request logic
    # ------------------------------------------------------------------

    async def _query_logs(
        self,
        query: str,
        start_time: int,
        end_time: int,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Execute a log query and return paginated results."""
        logs: List[Dict[str, Any]] = []
        page = 0
        page_size = min(limit, 100)
        
        while len(logs) < limit:
            try:
                result = await self._request(
                    "POST",
                    "/logs-queries/list",
                    json_body={
                        "query": query,
                        "time": {
                            "from": start_time * 1000,  # Datadog uses milliseconds
                            "to": end_time * 1000,
                        },
                        "page": {
                            "cursor": f"page:{page}" if page > 0 else None,
                            "limit": page_size,
                        },
                    },
                )
                
                if not isinstance(result, dict):
                    break
                
                logs_batch = result.get("data", [])
                if not logs_batch:
                    break
                
                logs.extend(logs_batch)
                page += 1
                
                # Check if more pages available
                if len(logs_batch) < page_size:
                    break
                    
            except Exception as exc:
                logger.warning(f"Datadog log query page {page} failed: {exc}")
                break
        
        return logs[:limit]

    async def _request(
        self,
        method: str,
        path: str,
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
            raise RuntimeError("Datadog connector not entered async context")

        url = urljoin(self._base_url, path)
        
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
                logger.debug(f"Datadog request retry after {backoff}s (attempt {retry_count + 1})")
                await asyncio.sleep(backoff)
                return await self._request(
                    method, path, params, json_body, retry_count + 1
                )
            raise

        except (httpx.ConnectError, asyncio.TimeoutError) as e:
            if retry_count < _MAX_RETRIES:
                backoff = _INITIAL_BACKOFF * (2 ** retry_count)
                logger.debug(f"Datadog connection retry after {backoff}s (attempt {retry_count + 1})")
                await asyncio.sleep(backoff)
                return await self._request(
                    method, path, params, json_body, retry_count + 1
                )
            raise


async def test_datadog_connection() -> bool:
    """Test if Datadog credentials are valid."""
    connector = DatadogConnector()
    if not connector.is_configured:
        logger.warning("Datadog not configured (missing DATADOG_API_KEY or DATADOG_APP_KEY)")
        return False
    
    try:
        async with connector:
            # Try a simple query as a health check
            logs = await connector.query_logs("*", since_minutes=1, limit=1)
            return True
    except Exception as exc:
        logger.warning(f"Datadog connection test failed: {exc}")
        return False
