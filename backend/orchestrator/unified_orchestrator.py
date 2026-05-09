"""
Unified Operational Orchestrator — coordinates all intelligence systems.

Manages the complete incident analysis pipeline:

RAW ERRORS
    ↓
[INGESTION] ← Sentry, Datadog, GitHub, Slack
    ↓
[CLUSTERING] ← Stack trace, deployment, semantic similarity
    ↓
[ENRICHMENT] ← GitHub context, Slack discussions, history
    ↓
[DEPLOYMENT CORRELATION] ← Link to releases
    ↓
[TEMPORAL ANALYSIS] ← Recurring patterns, MTTR estimates
    ↓
[SYNTHESIS] ← LLM-generated reasoning
    ↓
[SUPPRESSION] ← Dedup, acknowledge, low-confidence
    ↓
[ALERTING] ← Smart notifications
    ↓
[FRONTEND] ← Live operational brief

Usage:

    orchestrator = UnifiedOperationalOrchestrator(config)
    result = await orchestrator.analyze_repository(repo_url)
    
    # result contains:
    {
        clusters: [ErrorCluster],
        enriched_clusters: [EnrichedCluster],
        deployment_correlations: [DeploymentCorrelation],
        operational_brief: str,
        alerts: [OperationalAlert],
        metadata: {
            processing_time_ms,
            data_quality_score,
            confidence,
        }
    }
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from core.root_cause_clusterer import RootCauseClusterer, ErrorCluster
from core.context_enricher import ContextEnricher, EnrichedCluster
from core.deployment_correlation import DeploymentCorrelationEngine, Deployment
from core.temporal_memory import TemporalMemoryEngine, TemporalIncidentMemory
from core.ai_synthesizer import AISynthesisEngine
from connectors.sentry_connector import SentryConnector
from connectors.datadog_connector import DatadogConnector
from connectors.slack_connector import SlackConnector
from connectors.github_connector import GitHubConnector
from ingestion.unified_ingestor import UnifiedIngestor, NormalizedSignal

logger = logging.getLogger(__name__)


@dataclass
class OperationalAlert:
    """An actionable alert from the intelligence system."""
    alert_id: str
    severity: str  # S1-S4
    title: str
    description: str
    root_cause: str
    affected_services: List[str]
    recommended_action: str
    deployment_related: bool
    blast_radius: int
    historical_similarity: float  # 0-1: how similar to past incidents
    confidence: float
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    context_attachments: Dict[str, Any] = field(default_factory=dict)


@dataclass
class OperationalBrief:
    """Live operational intelligence summary."""
    timestamp: str
    total_incidents: int
    critical_clusters: List[str]
    deployment_correlation_detected: bool
    recurring_patterns: List[str]
    recommended_escalations: List[str]
    current_operational_status: str  # "normal" | "degraded" | "critical"
    narrative: str  # LLM-generated summary


class UnifiedOperationalOrchestrator:
    """
    Orchestrates the complete error monitoring and operational intelligence
    pipeline.
    
    Integrates:
    - Multi-source ingestion (Sentry, Datadog, GitHub, Slack)
    - Intelligent clustering
    - Context enrichment
    - Deployment correlation
    - Temporal memory and pattern recognition
    - Dynamic synthesis
    - Suppression and deduplication
    - Live alerting
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        
        # Initialize components
        self.ingestor = UnifiedIngestor()
        self.clusterer = RootCauseClusterer()
        self.enricher = ContextEnricher()
        self.deployment_correlator = DeploymentCorrelationEngine()
        self.temporal_memory = TemporalMemoryEngine()
        self.ai_synthesizer = AISynthesisEngine(
            api_key=self.config.get("groq_api_key"),
        )
        
        # Connectors (for data fetching)
        self.sentry = SentryConnector()
        self.datadog = DatadogConnector()
        self.slack = SlackConnector()
        self.github = GitHubConnector()
        
        # Statistics
        self._total_incidents_analyzed = 0
        self._average_processing_time_ms = 0.0

    # ------------------------------------------------------------------
    # Main API
    # ------------------------------------------------------------------

    async def analyze_repository(
        self,
        repo_url: str,
        services: Optional[List[str]] = None,
        since_minutes: int = 60,
    ) -> Dict[str, Any]:
        """
        Complete operational analysis for a repository.
        
        Runs the full pipeline with overall timeout to ensure response within 60 seconds:
        1. Ingest errors from all sources
        2. Cluster by root cause
        3. Enrich with context
        4. Correlate with deployments
        5. Analyze temporal patterns
        6. Generate operational brief
        7. Create alerts
        
        Returns comprehensive operational intelligence.
        """
        # Wrap entire pipeline with timeout to prevent indefinite hangs
        try:
            return await asyncio.wait_for(
                self._analyze_repository_impl(repo_url, services, since_minutes),
                timeout=60.0,  # ← TOTAL PIPELINE TIMEOUT
            )
        except asyncio.TimeoutError:
            logger.error(f"Analysis pipeline timed out after 60 seconds for {repo_url}")
            return self._timeout_response(repo_url)
        except Exception as e:
            logger.error(f"Analysis pipeline failed: {e}")
            return self._error_response(repo_url, str(e))
    
    async def _analyze_repository_impl(
        self,
        repo_url: str,
        services: Optional[List[str]] = None,
        since_minutes: int = 60,
    ) -> Dict[str, Any]:
        """Implementation of analysis pipeline (called with timeout wrapper)."""
        start_time = time.time()
        
        try:
            logger.info(f"Starting operational analysis for {repo_url}")
            
            # Step 1: Ingest
            signals = await self._ingest_signals(since_minutes)
            logger.info(f"Ingested {len(signals)} signals")
            
            # Step 2: Normalize
            errors = self._normalize_signals_to_errors(signals)
            logger.info(f"Normalized to {len(errors)} error objects")
            
            # Step 3: Cluster
            deployment_info = await self._fetch_deployment_info(repo_url)
            clusters = self.clusterer.cluster_errors(errors, deployment_info)
            logger.info(f"Clustered into {len(clusters)} groups")
            
            # Step 4: Enrich
            enriched_clusters = await self.enricher.enrich_batch(
                [asdict(c) for c in clusters],
                repo_url=repo_url,
            )
            logger.info(f"Enriched {len(enriched_clusters)} clusters")
            
            # Step 5: Update temporal memory
            for cluster in enriched_clusters:
                similar = self.temporal_memory.find_similar_historical_incident(
                    asdict(cluster)
                )
                if similar:
                    cluster.regression_probability = min(
                        1.0,
                        cluster.regression_probability + 0.3,
                    )
            
            # Step 6: Synthesize operational brief
            brief = await self._synthesize_operational_brief(
                enriched_clusters,
                repo_url,
            )
            
            # Step 7: Generate alerts
            alerts = self._generate_operational_alerts(enriched_clusters)
            
            # Compute metrics
            processing_time_ms = (time.time() - start_time) * 1000
            data_quality = self._compute_data_quality(errors)
            
            result = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "repository": repo_url,
                "clusters": [asdict(c) for c in clusters],
                "enriched_clusters": [asdict(c) for c in enriched_clusters],
                "deployment_correlations": [
                    asdict(c) for c in [
                        self.deployment_correlator.correlate_incident_cluster(
                            asdict(cluster)
                        )
                        for cluster in enriched_clusters
                    ]
                ],
                "operational_brief": asdict(brief),
                "alerts": [asdict(a) for a in alerts],
                "metadata": {
                    "total_signals_ingested": len(signals),
                    "total_errors_analyzed": len(errors),
                    "cluster_count": len(clusters),
                    "enriched_cluster_count": len(enriched_clusters),
                    "alert_count": len(alerts),
                    "processing_time_ms": processing_time_ms,
                    "data_quality_score": data_quality,
                },
            }
            
            logger.info(f"Analysis complete in {processing_time_ms:.1f}ms")
            return result
        
        except Exception as e:
            logger.error(f"Analysis failed: {e}", exc_info=True)
            return {
                "error": str(e),
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "repository": repo_url,
            }

    # ------------------------------------------------------------------
    # Pipeline stages
    # ------------------------------------------------------------------

    async def _ingest_signals(self, since_minutes: int = 60) -> List[NormalizedSignal]:
        """Ingest signals from all configured sources."""
        try:
            # Synchronous ingestion from UnifiedIngestor
            signals = self.ingestor.ingest(
                window_minutes=since_minutes,
                limit=500,
            )
            return signals
        except Exception as e:
            logger.warning(f"Signal ingestion failed: {e}")
            return []

    def _normalize_signals_to_errors(self, signals: List[NormalizedSignal]) -> List[Dict[str, Any]]:
        """Convert normalized signals to error objects for clustering."""
        errors = []
        
        for signal in signals:
            if signal.signal_type != "error":
                continue
            
            error = {
                "id": signal.trace_id or f"err_{len(errors)}",
                "signature": self._compute_signature(signal),
                "service": signal.service,
                "stack_trace": signal.payload.get("stack_trace", ""),
                "exception_type": signal.payload.get("exception_type", "Unknown"),
                "timestamp": signal.timestamp,
                "affected_orgs": [signal.org_name] if signal.org_name else [],
                "metadata": signal.payload,
                "severity": signal.severity,
            }
            errors.append(error)
        
        return errors

    async def _fetch_deployment_info(self, repo_url: str) -> Dict[str, Any]:
        """Fetch recent deployment information."""
        try:
            # This would fetch from actual deployment systems
            # For now, return structured info for correlation
            return {
                "recent_deployments": [],  # Would be populated from API
                "services": [],
            }
        except Exception as e:
            logger.warning(f"Deployment info fetch failed: {e}")
            return {"recent_deployments": [], "services": []}

    async def _synthesize_operational_brief(
        self,
        clusters: List[EnrichedCluster],
        repo_url: str,
    ) -> OperationalBrief:
        """Generate operational intelligence brief using AI synthesis."""
        if not clusters:
            return OperationalBrief(
                timestamp=datetime.now(timezone.utc).isoformat(),
                total_incidents=0,
                critical_clusters=[],
                deployment_correlation_detected=False,
                recurring_patterns=[],
                recommended_escalations=[],
                current_operational_status="normal",
                narrative="No incidents detected.",
            )
        
        # Get repository info for context-aware synthesis
        repo_info = self.github.get_repo_metadata(repo_url) if self.github.is_configured else {}
        
        # Use AI synthesizer
        synthesis = await self.ai_synthesizer.synthesize_operational_brief(
            [asdict(c) for c in clusters],
            repo_info,
        )
        
        # Analyze clusters for status
        critical = [c for c in clusters if c.severity in ("S1", "S2")]
        deployment_correlated = [c for c in clusters if c.deployment_related]
        recurring = []
        
        for cluster in clusters:
            similar = self.temporal_memory.find_similar_historical_incident(asdict(cluster))
            if similar and similar.occurrence_count > 1:
                recurring.append(cluster.cluster_id)
        
        # Determine status
        if len(critical) >= 2 or (critical and sum(c.error_count for c in critical) > 100):
            status = "critical"
        elif critical or deployment_correlated:
            status = "degraded"
        else:
            status = "normal"
        
        return OperationalBrief(
            timestamp=datetime.now(timezone.utc).isoformat(),
            total_incidents=len(clusters),
            critical_clusters=[c.cluster_id for c in critical],
            deployment_correlation_detected=bool(deployment_correlated),
            recurring_patterns=recurring,
            recommended_escalations=[
                c.cluster_id for c in critical if c.regression_probability > 0.7
            ],
            current_operational_status=status,
            narrative=synthesis.get("narrative", ""),
        )

    def _generate_operational_alerts(self, clusters: List[EnrichedCluster]) -> List[OperationalAlert]:
        """Generate actionable alerts from clusters."""
        alerts = []
        
        for cluster in clusters:
            # Skip low-severity if confident
            if cluster.severity == "S4" and cluster.confidence < 0.5:
                continue
            
            # Find relevant context
            context = {}
            if cluster.context_attachments:
                relevant_context = cluster.context_attachments[:3]
                context = {
                    "recent_discussions": [
                        {
                            "type": c.type,
                            "title": c.title,
                            "url": c.url,
                        }
                        for c in relevant_context
                    ]
                }
            
            alert = OperationalAlert(
                alert_id=f"alert_{cluster.cluster_id}",
                severity=cluster.severity,
                title=self._generate_alert_title(cluster),
                description=f"{cluster.error_count} errors in {', '.join(cluster.affected_services[:3])}",
                root_cause=cluster.root_cause,
                affected_services=cluster.affected_services,
                recommended_action=cluster.suggested_action or "Investigate",
                deployment_related=cluster.deployment_related,
                blast_radius=len(cluster.affected_services),
                historical_similarity=cluster.confidence,
                confidence=cluster.confidence,
                context_attachments=context,
            )
            
            alerts.append(alert)
        
        # Sort by severity
        severity_rank = {"S1": 1, "S2": 2, "S3": 3, "S4": 4}
        alerts.sort(key=lambda a: severity_rank.get(a.severity, 4))
        
        return alerts

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    def _compute_signature(self, signal: NormalizedSignal) -> str:
        """Compute error signature from signal."""
        # Use exception type + service as basic signature
        exc_type = signal.payload.get("exception_type", "Unknown")
        return f"{signal.service}:{exc_type}"

    def _compute_data_quality(self, errors: List[Dict[str, Any]]) -> float:
        """Compute overall data quality score 0-1."""
        if not errors:
            return 0.0
        
        with_traces = sum(1 for e in errors if e.get("stack_trace"))
        with_metadata = sum(1 for e in errors if e.get("metadata"))
        
        trace_quality = with_traces / len(errors)
        metadata_quality = with_metadata / len(errors)
        
        return (trace_quality * 0.6) + (metadata_quality * 0.4)

    def _generate_alert_title(self, cluster: EnrichedCluster) -> str:
        """Generate a concise alert title."""
        return f"[{cluster.severity}] {cluster.root_cause[:60]}"
    
    def _timeout_response(self, repo_url: str) -> Dict[str, Any]:
        """Response when pipeline times out."""
        return {
            "clusters": [],
            "enriched_clusters": [],
            "deployment_correlations": [],
            "operational_brief": {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "total_incidents": 0,
                "critical_clusters": [],
                "deployment_correlation_detected": False,
                "recurring_patterns": [],
                "recommended_escalations": [],
                "current_operational_status": "unknown",
                "narrative": "Analysis pipeline timed out after 60 seconds. Please try again.",
            },
            "alerts": [],
            "metadata": {
                "processing_time_ms": 60000,
                "data_quality_score": 0.0,
                "confidence": 0.0,
                "error": "timeout",
            },
        }
    
    def _error_response(self, repo_url: str, error_msg: str) -> Dict[str, Any]:
        """Response when pipeline errors."""
        return {
            "clusters": [],
            "enriched_clusters": [],
            "deployment_correlations": [],
            "operational_brief": {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "total_incidents": 0,
                "critical_clusters": [],
                "deployment_correlation_detected": False,
                "recurring_patterns": [],
                "recommended_escalations": [],
                "current_operational_status": "unknown",
                "narrative": f"Analysis failed: {error_msg}",
            },
            "alerts": [],
            "metadata": {
                "processing_time_ms": 0,
                "data_quality_score": 0.0,
                "confidence": 0.0,
                "error": error_msg,
            },
        }
