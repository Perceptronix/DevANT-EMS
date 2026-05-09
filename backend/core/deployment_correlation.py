"""
Deployment Correlation Engine — link incidents to deployments.

Tracks:
- Recent deployments and their metadata
- Incident timing relative to deployments
- Service overlap between deployments and incidents
- Regression probabilities post-deployment
- Correlation strength scoring

Output:
{
    deployment_related: bool,
    deployment_ids: [id],
    correlation_strength: float (0-1),
    likely_cause: "new deployment" | "rollback effect" | "none",
    affected_services: [service],
    previous_deployments: [prior_deployment_info]
}
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class Deployment:
    """Represents a production deployment."""
    id: str
    timestamp: str  # ISO-8601 UTC
    service: str
    version: str
    commit_sha: str
    author: Optional[str] = None
    status: str = "success"  # "success" | "rollback" | "failed"
    services_touched: List[str] = field(default_factory=list)
    files_changed: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class DeploymentCorrelation:
    """Correlation between incident and deployment(s)."""
    deployment_related: bool
    deployment_ids: List[str] = field(default_factory=list)
    correlation_strength: float = 0.0  # 0-1
    likely_cause: str = "none"  # "new_deployment" | "rollback" | "none"
    time_delta_minutes: int = 0
    service_overlap: List[str] = field(default_factory=list)
    confidence: float = 0.0


class DeploymentCorrelationEngine:
    """
    Correlate incidents with deployments.
    
    Determines if an incident is likely caused by a recent deployment by:
    1. Checking temporal proximity (typically 0-60 minutes)
    2. Analyzing service overlap
    3. Checking deployment status (rollback vs success)
    4. Computing correlation strength
    """

    def __init__(self):
        self._deployment_history: List[Deployment] = []
        self._correlation_cache: Dict[str, DeploymentCorrelation] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def register_deployment(self, deployment: Deployment):
        """Register a new deployment."""
        self._deployment_history.append(deployment)
        self._deployment_history.sort(
            key=lambda d: d.timestamp,
            reverse=True,
        )

    def register_deployments_batch(self, deployments: List[Deployment]):
        """Register multiple deployments."""
        for deployment in deployments:
            self.register_deployment(deployment)

    def correlate_incident(
        self,
        incident_timestamp: str,
        affected_services: List[str],
        incident_id: str,
    ) -> DeploymentCorrelation:
        """
        Check if an incident correlates with recent deployments.
        
        Returns DeploymentCorrelation with correlation strength.
        """
        # Check cache
        cache_key = f"{incident_id}:{incident_timestamp}"
        if cache_key in self._correlation_cache:
            return self._correlation_cache[cache_key]
        
        # Parse incident timestamp
        try:
            incident_dt = datetime.fromisoformat(
                incident_timestamp.replace("Z", "+00:00")
            )
        except Exception:
            return DeploymentCorrelation(deployment_related=False)
        
        # Find nearby deployments
        nearby_deployments = self._find_nearby_deployments(
            incident_dt,
            window_minutes=120,
        )
        
        if not nearby_deployments:
            correlation = DeploymentCorrelation(deployment_related=False)
            self._correlation_cache[cache_key] = correlation
            return correlation
        
        # Analyze correlation with each deployment
        best_correlation = DeploymentCorrelation(deployment_related=False)
        
        for deployment in nearby_deployments:
            correlation = self._analyze_deployment_correlation(
                incident_dt,
                affected_services,
                deployment,
            )
            
            if correlation.correlation_strength > best_correlation.correlation_strength:
                best_correlation = correlation
        
        # Cache result
        self._correlation_cache[cache_key] = best_correlation
        
        return best_correlation

    def correlate_incident_cluster(
        self,
        cluster: Dict[str, Any],
    ) -> DeploymentCorrelation:
        """
        Correlate an entire error cluster with deployments.
        
        Input cluster should have:
        {
            last_seen: ISO timestamp,
            affected_services: [service],
            cluster_id: str,
            ...
        }
        """
        return self.correlate_incident(
            cluster.get("last_seen", ""),
            cluster.get("affected_services", []),
            cluster.get("cluster_id", ""),
        )

    # ------------------------------------------------------------------
    # Analysis logic
    # ------------------------------------------------------------------

    def _find_nearby_deployments(
        self,
        incident_dt: datetime,
        window_minutes: int = 120,
    ) -> List[Deployment]:
        """Find deployments within +/- window around incident time."""
        nearby = []
        cutoff_before = incident_dt + timedelta(minutes=window_minutes)
        cutoff_after = incident_dt - timedelta(minutes=window_minutes)
        
        for deployment in self._deployment_history:
            try:
                dep_dt = datetime.fromisoformat(
                    deployment.timestamp.replace("Z", "+00:00")
                )
                if cutoff_after <= dep_dt <= cutoff_before:
                    nearby.append(deployment)
            except Exception:
                continue
        
        return nearby[:20]  # Limit to 20 recent deployments

    def _analyze_deployment_correlation(
        self,
        incident_dt: datetime,
        affected_services: List[str],
        deployment: Deployment,
    ) -> DeploymentCorrelation:
        """Analyze correlation between incident and specific deployment."""
        try:
            dep_dt = datetime.fromisoformat(
                deployment.timestamp.replace("Z", "+00:00")
            )
        except Exception:
            return DeploymentCorrelation(deployment_related=False)
        
        time_delta = abs((incident_dt - dep_dt).total_seconds() / 60)
        
        # Scoring: temporal proximity
        if time_delta > 120:
            return DeploymentCorrelation(deployment_related=False)
        
        # High correlation: incident 0-15 minutes after deployment
        temporal_score = self._score_temporal_proximity(time_delta)
        
        # Service overlap
        affected_set = set(s.lower() for s in affected_services)
        deployment_set = set(s.lower() for s in deployment.services_touched)
        service_overlap = list(affected_set & deployment_set)
        
        service_score = len(service_overlap) / max(len(affected_set), 1) if affected_set else 0.0
        
        # Deployment status impact
        status_score = 1.0 if deployment.status == "success" else 0.5
        
        # Overall correlation strength
        correlation_strength = (
            temporal_score * 0.5
            + service_score * 0.35
            + status_score * 0.15
        )
        
        # Determine likely cause
        likely_cause = "none"
        if correlation_strength > 0.6 and service_overlap:
            likely_cause = "new_deployment" if deployment.status == "success" else "rollback"
        
        confidence = min(1.0, correlation_strength)
        
        return DeploymentCorrelation(
            deployment_related=correlation_strength > 0.5,
            deployment_ids=[deployment.id],
            correlation_strength=correlation_strength,
            likely_cause=likely_cause,
            time_delta_minutes=int(time_delta),
            service_overlap=service_overlap,
            confidence=confidence,
        )

    def _score_temporal_proximity(self, delta_minutes: float) -> float:
        """
        Score temporal proximity.
        
        Higher score for incidents very close to deployment.
        """
        # Peak at 5 minutes post-deployment
        if delta_minutes <= 5:
            return 1.0
        # Decay linearly to 0 at 120 minutes
        elif delta_minutes <= 120:
            return 1.0 - (delta_minutes - 5) / (120 - 5)
        else:
            return 0.0

    # ------------------------------------------------------------------
    # Data enrichment
    # ------------------------------------------------------------------

    def analyze_deployment_trend(
        self,
        service: str,
        since_hours: int = 24,
    ) -> Dict[str, Any]:
        """
        Analyze deployment patterns for a service.
        
        Returns deployment frequency, success rate, etc.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(hours=since_hours)
        
        recent_deployments = [
            d for d in self._deployment_history
            if d.service == service
            and datetime.fromisoformat(d.timestamp.replace("Z", "+00:00")) >= cutoff
        ]
        
        if not recent_deployments:
            return {
                "service": service,
                "deployment_count": 0,
                "success_rate": 0.0,
                "frequency_per_hour": 0.0,
            }
        
        successful = sum(1 for d in recent_deployments if d.status == "success")
        success_rate = successful / len(recent_deployments) if recent_deployments else 0.0
        frequency = len(recent_deployments) / since_hours
        
        return {
            "service": service,
            "deployment_count": len(recent_deployments),
            "success_rate": success_rate,
            "frequency_per_hour": frequency,
            "recent_deployments": [
                {
                    "id": d.id,
                    "timestamp": d.timestamp,
                    "status": d.status,
                    "version": d.version,
                }
                for d in recent_deployments[:5]
            ],
        }

    def find_problematic_deployments(
        self,
        service: str,
        incidents: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """
        Identify deployments that seem to trigger incidents.
        
        Returns list of deployments with associated incidents.
        """
        problematic = []
        
        for deployment in self._deployment_history:
            if deployment.service != service:
                continue
            
            # Find incidents correlated with this deployment
            associated_incidents = [
                inc for inc in incidents
                if self.correlate_incident(
                    inc.get("timestamp", ""),
                    inc.get("affected_services", []),
                    inc.get("id", ""),
                ).deployment_ids and deployment.id in self.correlate_incident(
                    inc.get("timestamp", ""),
                    inc.get("affected_services", []),
                    inc.get("id", ""),
                ).deployment_ids
            ]
            
            if associated_incidents:
                problematic.append({
                    "deployment_id": deployment.id,
                    "timestamp": deployment.timestamp,
                    "version": deployment.version,
                    "commit_sha": deployment.commit_sha,
                    "status": deployment.status,
                    "incident_count": len(associated_incidents),
                    "incidents": associated_incidents[:3],
                })
        
        return problematic
