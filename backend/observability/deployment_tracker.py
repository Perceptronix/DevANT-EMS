import asyncio
from typing import List, Dict, Any, Optional
from datetime import datetime

from core.causality import correlate_deployment_events
from .github_actions import GitHubActionsIngest


class DeploymentTracker:
    """Track and correlate deployments from multiple providers.

    Minimal implementation supporting GitHub Actions; placeholder hooks for
    Vercel, Railway, and Docker.
    """

    def __init__(self, github_token: Optional[str] = None):
        self.github = GitHubActionsIngest(token=github_token)

    async def fetch_recent_deployments(self, repo: str, limit: int = 50) -> List[Dict[str, Any]]:
        runs = await self.github.fetch_runs(repo, per_page=limit)
        # Normalize to deployment event format
        events = []
        for r in runs:
            data = r.model_dump() if hasattr(r, "model_dump") else dict(r)
            events.append({
                "provider": "github_actions",
                "deployment_id": data.get("deployment_id"),
                "workflow": data.get("workflow_name"),
                "commit_sha": data.get("commit_hash"),
                "actor": data.get("actor"),
                "status": data.get("status"),
                "timestamp": data.get("timestamp").isoformat() if hasattr(data.get("timestamp"), "isoformat") else data.get("timestamp"),
                "url": data.get("url"),
                "source_of_truth": data.get("source_of_truth"),
                "confidence_origin": data.get("confidence_origin"),
            })
        return events

    async def correlate_with_incident(self, incident: Dict[str, Any], repo: str) -> Dict[str, Any]:
        # Fetch recent deployments and find ones within timeframe
        events = await self.fetch_recent_deployments(repo)
        correlation = correlate_deployment_events(incident)
        matched = []
        for e in events:
            if e.get("commit_sha") and incident.get("commit_hash") and e.get("commit_sha") == incident.get("commit_hash"):
                matched.append(e)
        return {"matched": bool(matched) or correlation.get("matched", False), "events": matched or correlation.get("events", []), "score": correlation.get("score", 0.0)}
