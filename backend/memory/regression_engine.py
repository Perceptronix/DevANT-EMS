"""Production regression intelligence engine with temporal and causal correlation."""

from __future__ import annotations

from typing import Dict, List, Any, Optional
from datetime import datetime, timezone

from memory.regression_memory import RegressionMemoryGraph, RegressionIncident, RegressionMatch
from memory.stacktrace_normalizer import StacktraceNormalizer
from memory.operational_fingerprint import OperationalFingerprintEngine
from core.normalization import normalize_timestamp
from core.signal_fusion import SignalFusionEngine, SignalType


class RegressionIntelligenceEngine:
    """Detect regressions through multi-signal temporal and causal correlation.

    Correlates:
    - Deployment events
    - Recurring failure patterns (normalized stacktraces)
    - Metric degradation timelines
    - Propagation path consistency
    - Historical remediation patterns
    """

    def __init__(self):
        self.memory_graph = RegressionMemoryGraph()
        self.normalizer = StacktraceNormalizer()
        self.fingerprint_engine = OperationalFingerprintEngine()

    def analyze_incident(
        self,
        incident: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Analyze incident for regression signals.

        Returns analysis with:
        - is_regression: bool
        - regression_confidence: float [0.0, 1.0]
        - related_incidents: list of historical incident IDs
        - root_cause_hint: inferred from historical patterns
        - remediation_hint: suggested fix based on history
        """
        context = context or {}

        # Extract incident data
        incident_id = incident.get("incident_id", f"incident-{datetime.now(timezone.utc).isoformat()}")
        service = incident.get("service", "unknown")
        error_signature = incident.get("error_signature", "")
        stacktrace = incident.get("sample_message") or incident.get("stacktrace", "")
        deployment_id = incident.get("deployment_id")
        deployment_time = incident.get("deployment_time")
        timestamp = incident.get("timestamp")
        metrics_anomalies = incident.get("metrics_anomalies") or context.get("metrics_anomalies") or []
        propagation_path = incident.get("propagation_chain") or context.get("propagation_chain") or []

        # Normalize incident
        normalized_stacktrace = self.normalizer.normalize(stacktrace)

        # Check for regression
        regression_match = self.memory_graph.detect_regression(
            {
                "service": service,
                "error_signature": error_signature,
                "stacktrace": stacktrace,  # This is already extracted above
                "deployment_id": deployment_id,
                "deployment_time": deployment_time,
                "timestamp": timestamp,
                "metrics_anomalies": [m.get("metric_name", m.get("name", "metric")) for m in metrics_anomalies],
                "propagation_path": [p.get("service", p.get("description", "unknown")) for p in propagation_path],
            },
            threshold=0.4,  # Lower threshold: stacktrace + temporal similarity often sufficient
        )

        # Find related incidents
        related = self.memory_graph.find_related_incidents(service, stacktrace, hours_back=720)
        related_ids = [inc.incident_id for inc in related[:5]]

        # Infer root cause from historical patterns
        root_cause_hint = ""
        remediation_hint = ""
        if regression_match.is_regression:
            matched_incident = self.memory_graph.incidents.get(regression_match.matched_incident_id)
            if matched_incident:
                root_cause_hint = matched_incident.root_cause or "Recurring pattern from prior incident"
                remediation_hint = matched_incident.remediation or "Review prior remediation for this incident type"

        # Build analysis result
        analysis = {
            "is_regression": regression_match.is_regression,
            "regression_confidence": regression_match.confidence,
            "regression_reason": regression_match.reason,
            "matched_incident_id": regression_match.matched_incident_id,
            "related_incidents": related_ids,
            "regression_signals": {
                "stacktrace_similarity": round(regression_match.stacktrace_similarity, 3),
                "deployment_correlation": round(regression_match.deployment_overlap, 3),
                "metric_anomaly_overlap": round(regression_match.metric_overlap, 3),
                "temporal_proximity_minutes": regression_match.temporal_proximity_minutes,
                "propagation_alignment": round(regression_match.propagation_alignment, 3),
            },
            "root_cause_hint": root_cause_hint,
            "remediation_hint": remediation_hint,
            "recurrence_risk": "HIGH" if regression_match.confidence >= 0.75 else "MEDIUM" if regression_match.confidence >= 0.5 else "LOW",
        }

        # Add signal fusion analysis if regression detected
        if regression_match.is_regression and regression_match.matched_incident_id:
            fusion_analysis = self._compute_evidence_grounded_confidence(incident, context or {})
            analysis["signal_fusion"] = fusion_analysis

        return analysis

    def record_resolution(
        self,
        incident: Dict[str, Any],
        remediation: str,
        root_cause: str,
    ) -> str:
        """Record a resolved incident for future regression detection."""
        incident_id = incident.get("incident_id", f"resolved-{datetime.now(timezone.utc).isoformat()}")
        service = incident.get("service", "unknown")
        error_signature = incident.get("error_signature", "")
        stacktrace = incident.get("sample_message") or incident.get("stacktrace", "")
        normalized = self.normalizer.normalize(stacktrace)
        deployment_id = incident.get("deployment_id")
        metrics = incident.get("metrics_anomalies") or []
        propagation = incident.get("propagation_chain") or []

        timestamp = normalize_timestamp(incident.get("timestamp")) or datetime.now(timezone.utc)

        resolved_incident = RegressionIncident(
            incident_id=incident_id,
            error_signature=error_signature,
            service=service,
            normalized_stacktrace=normalized,
            timestamp=timestamp,
            deployment_id=deployment_id,
            root_cause=root_cause,
            remediation=remediation,
            severity=incident.get("severity"),
            associated_metrics=[m.get("metric_name", m.get("name", "metric")) for m in metrics],
            propagation_path=[p.get("service", p.get("description", "unknown")) for p in propagation],
        )

        self.memory_graph.insert_resolved(resolved_incident)
        return incident_id

    def record_metric_observation(
        self,
        service: str,
        timestamp: Any,
        metrics: List[str],
    ) -> None:
        """Record metric anomalies for temporal correlation."""
        dt = normalize_timestamp(timestamp) or datetime.utcnow()
        self.memory_graph.insert_metrics_observation(service, dt, metrics)

    def record_deployment_event(
        self,
        service: str,
        timestamp: Any,
        deployment_id: str,
    ) -> None:
        """Record deployment event for temporal correlation."""
        dt = normalize_timestamp(timestamp) or datetime.utcnow()
        self.memory_graph.insert_deployment_event(service, dt, deployment_id)

    def get_regression_summary(self) -> Dict[str, Any]:
        """Get a summary of the regression memory."""
        resolved_count = sum(1 for inc in self.memory_graph.incidents.values() if inc.status == "resolved")
        reopened_count = sum(1 for inc in self.memory_graph.incidents.values() if inc.status == "reopened")
        total_reoccurrences = sum(inc.reopened_count for inc in self.memory_graph.incidents.values())

        return {
            "total_resolved_incidents": resolved_count,
            "reopened_incidents": reopened_count,
            "total_reoccurrences": total_reoccurrences,
            "memory_size": len(self.memory_graph.incidents),
            "services_tracked": len(set(inc.service for inc in self.memory_graph.incidents.values())),
        }

    def _compute_evidence_grounded_confidence(
        self,
        incident: Dict[str, Any],
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Compute evidence-grounded confidence from multi-signal convergence.

        Uses signal fusion to combine:
        - Regression similarity (stacktrace, semantics)
        - Temporal correlation (deployment, recurrence window)
        - Telemetry convergence (same metrics degrading)
        - Propagation alignment (same service path failing)
        - Topology consistency (same dependencies affected)
        """
        fusion = SignalFusionEngine()

        # Signal 1: Regression similarity
        try:
            new_fp = self.fingerprint_engine.fingerprint_incident(incident)
            if new_fp.canonical_failure_class != "UNKNOWN":
                # Fingerprint-based similarity is strong evidence
                fusion.add_signal(
                    SignalType.REGRESSION_SIMILARITY,
                    0.8,  # Strong if fingerprint classified
                    "operational_fingerprint",
                )
        except Exception:
            pass

        # Signal 2: Temporal correlation (from prior detect_regression)
        temporal_sim = context.get("temporal_proximity", 0.0)
        if temporal_sim > 0:
            fusion.add_signal(
                SignalType.TEMPORAL_CORRELATION,
                temporal_sim,
                "temporal_recurrence_window",
            )

        # Signal 3: Telemetry convergence
        metrics_overlap = context.get("metrics_overlap", 0.0)
        if metrics_overlap > 0:
            fusion.add_signal(
                SignalType.TELEMETRY_CONVERGENCE,
                metrics_overlap,
                "metric_anomaly_overlap",
            )

        # Signal 4: Propagation alignment
        propagation_sim = context.get("propagation_alignment", 0.0)
        if propagation_sim > 0:
            fusion.add_signal(
                SignalType.PROPAGATION_ALIGNMENT,
                propagation_sim,
                "propagation_path_consistency",
            )

        # Signal 5: Anomaly alignment (infer from metrics)
        anomalies = incident.get("metrics_anomalies") or context.get("metrics_anomalies") or []
        if len(anomalies) >= 2:
            fusion.add_signal(
                SignalType.ANOMALY_ALIGNMENT,
                0.6,
                "multi_metric_anomaly",
            )

        # Fuse signals
        result = fusion.fuse()

        return {
            "evidence_confidence": result["confidence"],
            "signal_count": result["signal_count"],
            "convergence_score": result["convergence_score"],
            "uncertainty": result["uncertainty"],
            "sparse_evidence": result["sparse_evidence"],
            "reasoning": result["reason"],
        }


# Singleton instance
_engine: Optional[RegressionIntelligenceEngine] = None


def get_regression_engine() -> RegressionIntelligenceEngine:
    """Get or create the singleton regression intelligence engine."""
    global _engine
    if _engine is None:
        _engine = RegressionIntelligenceEngine()
    return _engine
