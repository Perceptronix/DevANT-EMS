"""
Context Enrichment Engine — dynamically attach operational context to error clusters.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from connectors.github_connector import GitHubConnector
from connectors.slack_connector import SlackConnector
from memory.incident_graph import get_incident_graph

logger = logging.getLogger(__name__)

_ENRICHMENT_SEMAPHORE_LIMIT = 10


@dataclass
class ContextAttachment:
    type: str
    source: str
    title: str
    url: Optional[str] = None
    timestamp: Optional[str] = None
    author: Optional[str] = None
    relevance_score: float = 0.0
    snippet: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class EnrichedCluster:
    cluster_id: str
    root_cause: str
    affected_services: List[str]
    severity: str
    error_count: int
    confidence: float
    context_attachments: List[ContextAttachment] = field(default_factory=list)
    suggested_action: Optional[str] = None
    deployment_related: bool = False
    regression_probability: float = 0.0


class ContextEnricher:
    def __init__(
        self,
        github_token: Optional[str] = None,
        slack_token: Optional[str] = None,
        incident_graph: Optional[Any] = None,
    ):
        self.github = GitHubConnector(token=github_token)
        self.slack = SlackConnector(token=slack_token)
        self.incident_graph = incident_graph or get_incident_graph()
        self._cache: Dict[str, List[ContextAttachment]] = {}
        self._semaphore = asyncio.Semaphore(_ENRICHMENT_SEMAPHORE_LIMIT)

    async def enrich_cluster(
        self,
        cluster: Dict[str, Any],
        repo_url: Optional[str] = None,
        services: Optional[List[str]] = None,
    ) -> EnrichedCluster:
        enriched = EnrichedCluster(
            cluster_id=str(cluster.get("cluster_id", "unknown")),
            root_cause=str(cluster.get("root_cause", "")),
            affected_services=list(cluster.get("affected_services", []) or []),
            severity=str(cluster.get("severity", "S4")),
            error_count=int(cluster.get("error_count", 0) or 0),
            confidence=float(cluster.get("confidence", 0.0) or 0.0),
            deployment_related=bool(cluster.get("deployment_related", False)),
            regression_probability=float(cluster.get("regression_probability", 0.0) or 0.0),
        )

        tasks = []
        if repo_url and self.github.is_configured:
            tasks.append(self._bounded(self._enrich_github_context(enriched, repo_url, services or [])))
        if self.slack.is_configured:
            tasks.append(self._bounded(self._enrich_slack_context(enriched, cluster)))
        if self.incident_graph:
            tasks.append(self._bounded(self._enrich_historical_context(enriched, cluster)))

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

        enriched.suggested_action = self._suggest_action(enriched)
        return enriched

    async def enrich_batch(
        self,
        clusters: List[Dict[str, Any]],
        repo_url: Optional[str] = None,
    ) -> List[EnrichedCluster]:
        results = await asyncio.gather(
            *(self.enrich_cluster(cluster, repo_url=repo_url) for cluster in clusters),
            return_exceptions=True,
        )
        return [result for result in results if isinstance(result, EnrichedCluster)]

    async def _bounded(self, coro):
        async with self._semaphore:
            return await coro

    async def _enrich_github_context(self, enriched: EnrichedCluster, repo_url: str, services: List[str]) -> None:
        try:
            commits_task = asyncio.to_thread(self.github.get_recent_commits, repo_url, 24, 10)
            issues_task = asyncio.to_thread(self.github.search_related_issues, repo_url, enriched.root_cause, 5)
            prs_task = asyncio.to_thread(self.github.search_prs_by_service, repo_url, services, 24, 5)
            commits, issues, prs = await asyncio.gather(commits_task, issues_task, prs_task, return_exceptions=True)

            if isinstance(commits, list):
                for commit in commits:
                    enriched.context_attachments.append(ContextAttachment(
                        type="commit",
                        source="github",
                        title=commit.get("message", "Unnamed commit"),
                        url=commit.get("url", ""),
                        timestamp=commit.get("date", ""),
                        author=commit.get("author", ""),
                        relevance_score=0.6,
                        snippet=(commit.get("sha", "") or "")[:12],
                    ))

            if isinstance(issues, list):
                for issue in issues:
                    enriched.context_attachments.append(ContextAttachment(
                        type="issue",
                        source="github",
                        title=issue.get("title", "Unnamed issue"),
                        url=issue.get("url", ""),
                        timestamp=issue.get("updated_at", ""),
                        author=issue.get("author", ""),
                        relevance_score=0.5,
                        snippet=issue.get("body", "")[:180],
                    ))

            if isinstance(prs, list):
                for pr in prs:
                    enriched.context_attachments.append(ContextAttachment(
                        type="pr",
                        source="github",
                        title=pr.get("title", "Unnamed PR"),
                        url=pr.get("url", ""),
                        timestamp=pr.get("merged_at", ""),
                        author=pr.get("author", ""),
                        relevance_score=0.7,
                        snippet=f"Files changed: {pr.get('changed_files', 0)}",
                    ))
        except Exception as exc:
            logger.warning("GitHub context enrichment failed: %s", exc)

    async def _enrich_slack_context(self, enriched: EnrichedCluster, cluster: Dict[str, Any]) -> None:
        try:
            query = enriched.root_cause or cluster.get("signature", "")
            if not query:
                return
            messages = await self.slack.search_messages(query, since_minutes=1440, limit=5)
            for message in messages[:5]:
                enriched.context_attachments.append(ContextAttachment(
                    type="slack",
                    source="slack",
                    title=message.get("text", "Slack message")[:120],
                    url=message.get("permalink") or message.get("url", ""),
                    timestamp=message.get("ts", ""),
                    author=message.get("user", ""),
                    relevance_score=0.45,
                    snippet=message.get("text", "")[:180],
                ))
        except Exception as exc:
            logger.warning("Slack context enrichment failed: %s", exc)

    async def _enrich_historical_context(self, enriched: EnrichedCluster, cluster: Dict[str, Any]) -> None:
        try:
            if hasattr(self.incident_graph, "find_similar"):
                matches = self.incident_graph.find_similar(cluster.get("signature", enriched.root_cause))
                for match in matches[:5]:
                    if isinstance(match, dict):
                        title = str(match.get("incident_id", "Historical incident"))
                        timestamp = str(match.get("timestamp", ""))
                        snippet = str(match.get("resolution", match.get("root_cause", "")))
                    else:
                        title = str(getattr(match, "incident_id", "Historical incident"))
                        timestamp = str(getattr(match, "timestamp", ""))
                        snippet = str(getattr(match, "resolution", ""))
                    enriched.context_attachments.append(ContextAttachment(
                        type="historical",
                        source="incident_graph",
                        title=title,
                        timestamp=timestamp,
                        relevance_score=0.55,
                        snippet=snippet[:180],
                    ))
                    enriched.regression_probability = min(1.0, enriched.regression_probability + 0.1)
            elif isinstance(self.incident_graph, dict):
                history = self.incident_graph.get("incidents", [])
                for entry in history[:5]:
                    enriched.context_attachments.append(ContextAttachment(
                        type="historical",
                        source="incident_graph",
                        title=str(entry.get("incident_id", "Historical incident")),
                        timestamp=str(entry.get("timestamp", "")),
                        relevance_score=0.5,
                        snippet=str(entry.get("root_cause", ""))[:180],
                    ))
        except Exception as exc:
            logger.warning("Historical context enrichment failed: %s", exc)

    def _suggest_action(self, enriched: EnrichedCluster) -> str:
        if enriched.deployment_related:
            return "Check recent deployment diff and consider rollback"
        if enriched.severity in ("S1", "S2"):
            return "Escalate to on-call and inspect high-signal attachments"
        if enriched.context_attachments:
            return "Review attached commits, issues, and messages for shared failure pattern"
        return "Investigate failing service path and compare with prior incidents"


__all__ = ["ContextEnricher", "EnrichedCluster", "ContextAttachment"]