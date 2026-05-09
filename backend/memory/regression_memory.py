"""Regression memory graph with temporal, deployment, and telemetry tracking."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Optional, Any, Set

from memory.stacktrace_normalizer import StacktraceNormalizer


@dataclass
class RegressionIncident:
    """Historical incident with full operational context."""

    incident_id: str
    error_signature: str
    service: str
    normalized_stacktrace: str
    timestamp: datetime
    deployment_id: Optional[str] = None
    commit_hash: Optional[str] = None
    status: str = "open"  # open, closed, reopened, resolved
    severity: Optional[str] = None
    root_cause: Optional[str] = None
    remediation: Optional[str] = None
    resolved_at: Optional[datetime] = None
    reopened_count: int = 0
    associated_metrics: List[str] = field(default_factory=list)
    propagation_path: List[str] = field(default_factory=list)
    owner: Optional[str] = None
    related_ticket_id: Optional[str] = None


@dataclass
class RegressionMatch:
    """Result of regression detection matching."""

    is_regression: bool
    matched_incident_id: Optional[str] = None
    confidence: float = 0.0
    reason: str = ""
    stacktrace_similarity: float = 0.0
    deployment_overlap: float = 0.0
    metric_overlap: float = 0.0
    temporal_proximity_minutes: Optional[int] = None
    propagation_alignment: float = 0.0


class RegressionMemoryGraph:
    """Track historical incidents and detect regressions through multi-signal correlation.

    Tracks:
    - Recurring incidents (same error signature)
    - Deployment-correlated regressions
    - Metric-anomaly-driven regressions
    - Propagation path regressions
    - Prior remediation history
    """

    def __init__(self):
        self.incidents: Dict[str, RegressionIncident] = {}
        self.normalized_stacktraces: Dict[str, str] = {}
        self.normalizer = StacktraceNormalizer()
        self.metrics_timeline: Dict[str, List[Tuple[datetime, List[str]]]] = {}
        self.deployment_timeline: Dict[str, List[Tuple[datetime, str]]] = {}

    def insert_resolved(self, incident: RegressionIncident) -> None:
        """Mark an incident as resolved and store in history."""
        from core.normalization import normalize_timestamp
        
        incident.status = "resolved"
        incident.resolved_at = normalize_timestamp(datetime.now(timezone.utc).isoformat()) or datetime.now(timezone.utc)
        self.incidents[incident.incident_id] = incident
        normalized = self.normalizer.normalize(incident.normalized_stacktrace)
        self.normalized_stacktraces[incident.incident_id] = normalized

    def insert_metrics_observation(self, service: str, timestamp: datetime, metrics: List[str]) -> None:
        """Record metric anomalies at a timestamp for a service."""
        key = service
        if key not in self.metrics_timeline:
            self.metrics_timeline[key] = []
        self.metrics_timeline[key].append((timestamp, metrics))

    def insert_deployment_event(self, service: str, timestamp: datetime, deployment_id: str) -> None:
        """Record deployment event for temporal correlation."""
        key = service
        if key not in self.deployment_timeline:
            self.deployment_timeline[key] = []
        self.deployment_timeline[key].append((timestamp, deployment_id))

    def detect_regression(
        self,
        new_incident: Dict[str, Any],
        threshold: float = 0.6,
    ) -> RegressionMatch:
        """Detect if a new incident is a regression.

        Multi-signal detection:
        1. Stacktrace similarity (normalized)
        2. Deployment correlation (deployed shortly before)
        3. Metric overlap (similar anomalies)
        4. Temporal proximity (reoccurrence within expected window)
        5. Propagation path alignment
        """
        service = new_incident.get("service", "unknown")
        new_signature = new_incident.get("error_signature", "")
        new_stacktrace = new_incident.get("stacktrace", "")
        new_deployment_id = new_incident.get("deployment_id")
        new_deployment_time = new_incident.get("deployment_time")
        new_metrics = new_incident.get("metrics_anomalies", [])
        new_timestamp = new_incident.get("timestamp")
        new_propagation = new_incident.get("propagation_path", [])

        best_match = None
        best_confidence = 0.0

        for incident in self.incidents.values():
            if incident.service != service or incident.status != "resolved":
                continue

            # Signal 1: Stacktrace similarity
            stacktrace_sim, _ = self.normalizer.similarity(
                new_stacktrace,
                incident.normalized_stacktrace,
            )

            # Signal 2: Deployment correlation
            deployment_overlap = self._deployment_overlap_score(
                new_deployment_id,
                new_deployment_time,
                incident.deployment_id,
                incident.timestamp,
            )

            # Signal 3: Metric anomaly overlap
            metric_overlap = self._metric_overlap_score(new_metrics, incident.associated_metrics)

            # Signal 4: Temporal proximity
            temporal_proximity = self._temporal_proximity_score(new_timestamp, incident.timestamp)

            # Signal 5: Propagation path alignment
            propagation_sim = self._propagation_alignment_score(new_propagation, incident.propagation_path)

            # Weighted confidence -- emphasize stacktrace + temporal proximity
            # Weighted confidence
            confidence = (
                (stacktrace_sim * 0.35)
                + (deployment_overlap * 0.25)
                + (metric_overlap * 0.15)
                + (temporal_proximity * 0.15)
                + (propagation_sim * 0.10)
            )

            # Small heuristic boost: if stacktrace nearly identical and temporal proximity strong,
            # increase confidence to reflect recurring exact failures across time.
            if stacktrace_sim > 0.9 and temporal_proximity >= 0.7:
                confidence = min(1.0, confidence + 0.15)

            if confidence > best_confidence:
                best_confidence = confidence
                best_match = incident
                best_stacktrace_sim = stacktrace_sim
                best_deployment_overlap = deployment_overlap
                best_metric_overlap = metric_overlap
                best_propagation_sim = propagation_sim

        if best_match and best_confidence >= threshold:
            best_match.reopened_count += 1
            best_match.status = "reopened"

            return RegressionMatch(
                is_regression=True,
                matched_incident_id=best_match.incident_id,
                confidence=min(1.0, best_confidence),
                reason=f"Matched historical incident {best_match.incident_id} via multi-signal correlation",
                stacktrace_similarity=stacktrace_sim,
                deployment_overlap=deployment_overlap,
                metric_overlap=metric_overlap,
                temporal_proximity_minutes=self._temporal_distance_minutes(new_timestamp, best_match.timestamp),
                propagation_alignment=propagation_sim,
            )

        return RegressionMatch(is_regression=False, reason="No high-confidence historical match found")

    def find_related_incidents(
        self,
        service: str,
        stacktrace: str,
        hours_back: int = 720,
    ) -> List[RegressionIncident]:
        """Find all incidents related to a given stacktrace within a time window."""
        from core.normalization import normalize_timestamp
        
        # Get current time with timezone
        now = normalize_timestamp(datetime.now(timezone.utc).isoformat()) or datetime.now(timezone.utc)
        cutoff = now - timedelta(hours=hours_back)
        related = []

        for incident in self.incidents.values():
            if incident.service != service or incident.timestamp < cutoff:
                continue

            sim, _ = self.normalizer.similarity(stacktrace, incident.normalized_stacktrace)
            if sim >= 0.5:
                related.append(incident)

        return sorted(related, key=lambda i: i.timestamp, reverse=True)

    def _deployment_overlap_score(
        self,
        new_deployment_id: Optional[str],
        new_deployment_time: Optional[str],
        prev_deployment_id: Optional[str],
        prev_incident_time: datetime,
    ) -> float:
        """Score deployment correlation."""
        if not new_deployment_id or not prev_deployment_id:
            return 0.0 if new_deployment_id != prev_deployment_id else 0.3

        if new_deployment_id == prev_deployment_id:
            return 0.9

        # Check temporal proximity
        if new_deployment_time:
            from core.normalization import normalize_timestamp
            new_time = normalize_timestamp(new_deployment_time)
            if new_time:
                delta_minutes = abs((prev_incident_time - new_time).total_seconds() / 60)
                if delta_minutes < 30:
                    return 0.7
                elif delta_minutes < 120:
                    return 0.4

        return 0.0

    def _metric_overlap_score(self, new_metrics: List[str], prev_metrics: List[str]) -> float:
        """Score metric anomaly overlap."""
        if not new_metrics or not prev_metrics:
            return 0.0

        new_set = set(m.lower() for m in new_metrics)
        prev_set = set(m.lower() for m in prev_metrics)

        intersection = new_set.intersection(prev_set)
        union = new_set.union(prev_set)

        if not union:
            return 0.0

        return len(intersection) / len(union)

    def _temporal_proximity_score(self, new_time: Optional[Any], prev_time: datetime) -> float:
        """Score temporal proximity (expected reoccurrence within ~30 days)."""
        if not new_time:
            return 0.0

        from core.normalization import normalize_timestamp
        new_dt = normalize_timestamp(new_time)
        if not new_dt:
            return 0.0

        delta_days = (new_dt - prev_time).days
        if delta_days < 0:
            return 0.0

        if delta_days <= 1:
            return 1.0
        elif delta_days <= 7:
            return 0.9
        elif delta_days <= 30:
            return 0.7
        elif delta_days <= 90:
            return 0.4
        else:
            return 0.0

    def _propagation_alignment_score(self, new_path: List[str], prev_path: List[str]) -> float:
        """Score alignment of propagation paths."""
        if not new_path or not prev_path:
            return 0.0

        new_set = set(p.lower() for p in new_path)
        prev_set = set(p.lower() for p in prev_path)

        intersection = new_set.intersection(prev_set)
        union = new_set.union(prev_set)

        if not union:
            return 0.0

        return len(intersection) / len(union)

    def _temporal_distance_minutes(self, time_a: Optional[Any], time_b: datetime) -> Optional[int]:
        """Calculate temporal distance in minutes."""
        if not time_a:
            return None

        from core.normalization import normalize_timestamp
        time_a_dt = normalize_timestamp(time_a)
        if not time_a_dt:
            return None

        delta = abs((time_a_dt - time_b).total_seconds() / 60)
        return int(delta)
