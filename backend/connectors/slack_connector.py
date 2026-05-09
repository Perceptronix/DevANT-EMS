"""
Slack Connector — operational context and discussion enrichment.

Searches Slack threads, conversations, and alerts for:
- Bug reports and discussions
- Deployment announcements
- Incident postmortems
- On-call rotations and escalations
- Incident channel updates

Requires SLACK_BOT_TOKEN environment variable.
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin

import httpx

logger = logging.getLogger(__name__)

_SLACK_API_BASE = "https://slack.com/api"
_DEFAULT_TIMEOUT = 15.0
_MAX_RETRIES = 3
_INITIAL_BACKOFF = 1.0


class SlackConnector:
    """
    Async Slack API client for operational context enrichment.
    
    Handles:
    - Thread and message search
    - Channel history queries
    - User/team resolution
    - Automatic pagination
    - Rate limit (429) and server error (5xx) retries
    - Graceful degradation when token is missing
    """

    def __init__(
        self,
        token: Optional[str] = None,
        timeout: float = _DEFAULT_TIMEOUT,
    ):
        self.token = token or os.environ.get("SLACK_BOT_TOKEN", "")
        self.timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None

    @property
    def is_configured(self) -> bool:
        return bool(self.token)

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

    async def search_messages(
        self,
        query: str,
        channels: Optional[List[str]] = None,
        since_minutes: int = 1440,  # 24 hours
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """
        Search Slack messages for context.
        
        Returns list of messages with:
        {
            text, ts, channel, user, thread_ts,
            reactions, reply_count, author_name
        }
        """
        if not self.is_configured:
            return []

        try:
            since = (datetime.now(timezone.utc) - timedelta(minutes=since_minutes)).timestamp()
            
            # Build search query
            search_query = f"{query} after:{int(since)}"
            if channels:
                channel_filter = " OR ".join(f"in:{c}" for c in channels)
                search_query += f" ({channel_filter})"
            
            result = await self._request(
                "GET",
                "/search.messages",
                params={
                    "query": search_query,
                    "sort": "timestamp",
                    "sort_dir": "desc",
                    "count": limit,
                },
            )
            
            if not isinstance(result, dict):
                return []
            
            messages = result.get("messages", {}).get("matches", [])
            return messages[:limit]

        except Exception as exc:
            logger.warning(f"Slack search_messages failed: {exc}")
            return []

    async def fetch_channel_history(
        self,
        channel_id: str,
        since_minutes: int = 60,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """
        Fetch recent messages from a Slack channel.
        
        Returns list of messages with full context.
        """
        if not self.is_configured:
            return []

        try:
            since = (datetime.now(timezone.utc) - timedelta(minutes=since_minutes)).timestamp()
            
            messages: List[Dict[str, Any]] = []
            cursor = None
            
            while len(messages) < limit:
                params = {
                    "channel": channel_id,
                    "limit": min(100, limit - len(messages)),
                    "inclusive": True,
                }
                if cursor:
                    params["cursor"] = cursor
                
                result = await self._request(
                    "GET",
                    "/conversations.history",
                    params=params,
                )
                
                if not isinstance(result, dict):
                    break
                
                batch = result.get("messages", [])
                if not batch:
                    break
                
                # Filter by time
                for msg in batch:
                    msg_ts = float(msg.get("ts", 0))
                    if msg_ts >= since:
                        messages.append(msg)
                
                if not result.get("has_more"):
                    break
                
                cursor = result.get("response_metadata", {}).get("next_cursor")
                if not cursor:
                    break
            
            return messages[:limit]

        except Exception as exc:
            logger.warning(f"Slack fetch_channel_history failed: {exc}")
            return []

    async def fetch_thread_replies(
        self,
        channel_id: str,
        thread_ts: str,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """
        Fetch all replies in a Slack thread.
        
        Returns list of threaded messages.
        """
        if not self.is_configured:
            return []

        try:
            result = await self._request(
                "GET",
                "/conversations.replies",
                params={
                    "channel": channel_id,
                    "ts": thread_ts,
                    "limit": limit,
                },
            )
            
            if not isinstance(result, dict):
                return []
            
            return result.get("messages", [])[:limit]

        except Exception as exc:
            logger.warning(f"Slack fetch_thread_replies failed: {exc}")
            return []

    async def resolve_user_info(
        self,
        user_id: str,
    ) -> Dict[str, Any]:
        """
        Resolve Slack user details by ID.
        
        Returns user profile with name, email, etc.
        """
        if not self.is_configured:
            return {}

        try:
            result = await self._request(
                "GET",
                "/users.info",
                params={"user": user_id},
            )
            
            if not isinstance(result, dict):
                return {}
            
            user = result.get("user", {})
            return {
                "id": user.get("id"),
                "name": user.get("name"),
                "real_name": user.get("real_name"),
                "email": user.get("profile", {}).get("email"),
                "title": user.get("profile", {}).get("title"),
            }

        except Exception as exc:
            logger.warning(f"Slack resolve_user_info failed: {exc}")
            return {}

    async def get_channel_info(
        self,
        channel_id: str,
    ) -> Dict[str, Any]:
        """
        Get Slack channel details.
        
        Returns channel metadata.
        """
        if not self.is_configured:
            return {}

        try:
            result = await self._request(
                "GET",
                "/conversations.info",
                params={"channel": channel_id},
            )
            
            if not isinstance(result, dict):
                return {}
            
            channel = result.get("channel", {})
            return {
                "id": channel.get("id"),
                "name": channel.get("name"),
                "topic": channel.get("topic", {}).get("value"),
                "purpose": channel.get("purpose", {}).get("value"),
                "created": channel.get("created"),
                "creator": channel.get("creator"),
            }

        except Exception as exc:
            logger.warning(f"Slack get_channel_info failed: {exc}")
            return {}

    async def post_alert(
        self,
        failure_result: Dict[str, Any],
        channel: Optional[str] = None,
    ) -> bool:
        """
        Post a deployment failure alert to Slack.
        
        Uses Block Kit format with severity emoji and structured layout.
        """
        if not self.is_configured:
            logger.warning("Slack not configured, skipping alert")
            return False
        
        # Default channel
        if not channel:
            channel = os.environ.get("SLACK_ALERT_CHANNEL", "#devant-alerts")
        
        try:
            # Severity emoji and top cluster
            severity_emoji = {"S1": "🔴", "S2": "🟠", "S3": "🟡", "S4": "🔵"}
            
            clusters = failure_result.get("clusters", [])
            top_cluster = clusters[0] if clusters else {}
            severity = top_cluster.get("severity", "S3")
            emoji = severity_emoji.get(severity, "⚪")
            
            failed = failure_result.get("failed_deployments", [])
            repo = failure_result.get("repo", "unknown")
            environment = failure_result.get("environment", "production")
            
            # Build Block Kit message
            blocks = [
                {
                    "type": "header",
                    "text": {
                        "type": "plain_text",
                        "text": f"{emoji} {severity} Deployment Failure — {repo.split('/')[-1]}",
                        "emoji": True,
                    }
                },
                {
                    "type": "section",
                    "fields": [
                        {"type": "mrkdwn", "text": f"*Repository:*\n{repo}"},
                        {"type": "mrkdwn", "text": f"*Environment:*\n{environment}"},
                        {"type": "mrkdwn", "text": f"*Failed Deployments:*\n{len(failed)}"},
                        {"type": "mrkdwn", "text": f"*Severity:*\n{severity}"},
                    ]
                },
            ]
            
            # Add each failed deployment as a section (max 3)
            for f in failed[:3]:
                sha = f.get("sha_short", "unknown")
                msg = f.get("commit_message", "No message")[:80]
                files = f.get("files_changed", 0)
                changed = ", ".join(f.get("changed_files", [])[:3]) or "unknown files"
                log_url = f.get("log_url", "")
                link = f" <{log_url}|View Logs>" if log_url else ""
                
                blocks.append({
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": (
                            f"*Commit `{sha}`:* {msg}\n"
                            f"*Files changed:* {files} ({changed}){link}"
                        )
                    }
                })
            
            # Add root cause from top cluster
            if top_cluster.get("root_cause"):
                blocks.append({
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*Root Cause Analysis:*\n{top_cluster.get('root_cause', '')[:200]}"
                    }
                })
            
            # Footer
            blocks.append({
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": f"DevANT | {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"
                    }
                ]
            })
            
            payload = {
                "channel": channel,
                "blocks": blocks,
                "text": f"{emoji} Deployment failure in {repo} ({severity})",  # fallback
            }
            
            # Post to Slack
            result = await self._request(
                "POST",
                "/chat.postMessage",
                json_body=payload,
            )
            
            if not isinstance(result, dict) or not result.get("ok"):
                logger.warning(f"Slack post_alert failed: {result.get('error', 'unknown')}")
                return False
            
            logger.info(f"Posted alert to {channel}")
            return True

        except Exception as exc:
            logger.error(f"Slack post_alert exception: {exc}", exc_info=True)
            return False

    # ------------------------------------------------------------------
    # Low-level request logic
    # ------------------------------------------------------------------

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
            raise RuntimeError("Slack connector not entered async context")

        url = urljoin(_SLACK_API_BASE, path)
        
        try:
            response = await self._client.request(
                method,
                url,
                params=params,
                json=json_body,
            )
            response.raise_for_status()
            
            data = response.json() if response.text else {}
            
            # Check Slack error response
            if not data.get("ok"):
                error = data.get("error", "unknown error")
                raise RuntimeError(f"Slack API error: {error}")
            
            return data

        except httpx.HTTPStatusError as e:
            # Retry on rate limit or server error
            if e.response.status_code in (429, 500, 502, 503) and retry_count < _MAX_RETRIES:
                backoff = _INITIAL_BACKOFF * (2 ** retry_count)
                logger.debug(f"Slack request retry after {backoff}s (attempt {retry_count + 1})")
                await asyncio.sleep(backoff)
                return await self._request(
                    method, path, params, json_body, retry_count + 1
                )
            raise

        except (httpx.ConnectError, asyncio.TimeoutError) as e:
            if retry_count < _MAX_RETRIES:
                backoff = _INITIAL_BACKOFF * (2 ** retry_count)
                logger.debug(f"Slack connection retry after {backoff}s (attempt {retry_count + 1})")
                await asyncio.sleep(backoff)
                return await self._request(
                    method, path, params, json_body, retry_count + 1
                )
            raise


async def test_slack_connection() -> bool:
    """Test if Slack credentials are valid."""
    connector = SlackConnector()
    if not connector.is_configured:
        logger.warning("Slack not configured (missing SLACK_BOT_TOKEN)")
        return False
    
    try:
        async with connector:
            # Try to get auth test
            result = await connector._request("GET", "/auth.test")
            return result.get("ok", False)
    except Exception as exc:
        logger.warning(f"Slack connection test failed: {exc}")
        return False
