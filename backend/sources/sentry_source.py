"""
Sentry data source.

Fetches errors from Sentry using their API.
Requires Sentry auth token and org/project slugs.
"""
import logging
from datetime import datetime, timedelta
from typing import List, Optional

import httpx

from .base import DataSource
from schemas import RawError
from config import get_config

logger = logging.getLogger(__name__)


class SentrySource(DataSource):
    """
    Fetch errors from Sentry.
    
    Requires the following environment variables:
    - SENTRY_AUTH_TOKEN
    - SENTRY_ORG_SLUG
    - SENTRY_PROJECT_SLUG (optional - fetches all projects if not set)
    """
    
    def __init__(self):
        config = get_config()
        self.auth_token = config.data_source.sentry_auth_token
        self.org_slug = config.data_source.sentry_org_slug
        self.project_slug = config.data_source.sentry_project_slug
        self.base_url = config.data_source.sentry_url
        
        if self.is_configured:
            logger.info(f"Sentry source configured (org: {self.org_slug})")
        else:
            logger.info("Sentry source not configured")
    
    @property
    def name(self) -> str:
        return "Sentry"
    
    @property
    def source_type(self) -> str:
        return "sentry"
    
    @property
    def is_configured(self) -> bool:
        return bool(self.auth_token and self.org_slug)
    
    async def fetch_errors(
        self,
        window_minutes: int = 30,
        limit: int = 100
    ) -> List[RawError]:
        """Fetch issues from Sentry."""
        if not self.is_configured:
            logger.warning("Sentry source not configured, returning empty list")
            return []
        
        # Build query
        start_time = datetime.utcnow() - timedelta(minutes=window_minutes)
        
        url = f"{self.base_url}/api/0/organizations/{self.org_slug}/issues/"
        params = {
            "query": f"is:unresolved lastSeen:>{start_time.isoformat()}",
            "limit": limit,
            "statsPeriod": f"{window_minutes}m",
        }
        
        if self.project_slug:
            params["project"] = self.project_slug
        
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(
                    url,
                    headers={"Authorization": f"Bearer {self.auth_token}"},
                    params=params,
                )
                response.raise_for_status()
                issues = response.json()
            
            errors = []
            for issue in issues:
                error = self._issue_to_error(issue)
                if error:
                    errors.append(error)
            
            logger.info(f"Fetched {len(errors)} errors from Sentry")
            return errors
            
        except httpx.HTTPStatusError as e:
            logger.error(f"Sentry API error: {e.response.status_code} - {e.response.text}")
            return []
        except Exception as e:
            logger.error(f"Failed to fetch from Sentry: {e}", exc_info=True)
            return []
    
    def _issue_to_error(self, issue: dict) -> Optional[RawError]:
        """Convert Sentry issue to RawError."""
        try:
            # Parse culprit (usually "module.function" or file path)
            culprit = issue.get("culprit", "")
            module, function = None, None
            
            if culprit:
                if "." in culprit:
                    parts = culprit.rsplit(".", 1)
                    module, function = parts[0], parts[1]
                elif " in " in culprit:
                    parts = culprit.split(" in ")
                    function = parts[-1] if parts else culprit
                    module = parts[0] if len(parts) > 1 else None
                else:
                    function = culprit
            
            # Get latest event timestamp
            last_seen = issue.get("lastSeen")
            if last_seen:
                timestamp = datetime.fromisoformat(last_seen.replace("Z", "+00:00"))
            else:
                timestamp = datetime.utcnow()
            
            # Extract tags for org info
            tags = {}
            for tag in issue.get("tags", []):
                if isinstance(tag, dict):
                    tags[tag.get("key", "")] = tag.get("value", "")
            
            # Get metadata
            metadata = issue.get("metadata", {})
            
            # Build message from title or metadata
            message = issue.get("title", metadata.get("value", "Unknown error"))
            
            # Map Sentry level to standard levels
            level = issue.get("level", "error").upper()
            if level == "FATAL":
                level = "CRITICAL"
            
            return RawError(
                id=f"sentry-{issue['id']}",
                timestamp=timestamp,
                level=level,
                message=message,
                module=module,
                function=function,
                container=issue.get("project", {}).get("slug"),
                environment=tags.get("environment", "production"),
                org_id=tags.get("organization_id"),
                org_name=tags.get("organization_name"),
                metadata={
                    "sentry_id": issue["id"],
                    "short_id": issue.get("shortId"),
                    "count": issue.get("count", 0),
                    "user_count": issue.get("userCount", 0),
                    "type": issue.get("type"),
                    "platform": issue.get("platform"),
                    "first_seen": issue.get("firstSeen"),
                    "last_seen": last_seen,
                },
                source_type="sentry",
                source_url=self._get_issue_url(issue),
            )
        except Exception as e:
            logger.error(f"Failed to parse Sentry issue: {e}")
            return None
    
    def _get_issue_url(self, issue: dict) -> Optional[str]:
        """Get Sentry issue URL."""
        short_id = issue.get("shortId")
        if short_id:
            return f"{self.base_url}/organizations/{self.org_slug}/issues/{short_id}/"
        
        issue_id = issue.get("id")
        if issue_id:
            return f"{self.base_url}/organizations/{self.org_slug}/issues/{issue_id}/"
        
        return None
    
    def get_error_url(self, error: RawError) -> Optional[str]:
        """Get Sentry issue URL."""
        # Try to get from source_url first
        if error.source_url:
            return error.source_url
        
        # Try to reconstruct from metadata
        short_id = error.metadata.get("short_id")
        if short_id:
            return f"{self.base_url}/organizations/{self.org_slug}/issues/{short_id}/"
        
        sentry_id = error.metadata.get("sentry_id")
        if sentry_id:
            return f"{self.base_url}/organizations/{self.org_slug}/issues/{sentry_id}/"
        
        return None
