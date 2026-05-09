from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from core.normalization import normalize_timestamp
from ontology.models import Deployment, Incident, MetricAnomaly, PropagationEvent, RCAHypothesis


@dataclass
class PropagationSummary:
    final_state: str
    summary: str
    recommended_action: str


class PropagationEngine:
    """Infer causal propagation from deployment and operational signals.

    The engine is intentionally rule-based so the first-order causal path stays
    stable and testable: deployment -> latency -> retries -> saturation -> timeout -> outage.
    """

    def infer(
        self,
        incident: Dict[str, Any],
        deployment_correlation: Optional[Dict[str, Any]] = None,
        metrics_anomalies: Optional[List[Dict[str, Any]]] = None,
        regression_history: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        incident_ts = normalize_timestamp(incident.get("timestamp") or incident.get("occurred_at")) or datetime.utcnow()
        deployment_correlation = deployment_correlation or {}
        metrics_anomalies = metrics_anomalies or []
        regression_history = regression_history or []

        deployment = self._infer_deployment(incident, deployment_correlation)
        chain: List[PropagationEvent] = []
        chain.append(self._event(
            event_id=f"{incident.get('incident_id', 'incident')}:deployment",
            timestamp=self._offset(incident_ts, minutes=0),
            source_service=deployment.service if deployment else self._service_name(incident),
            target_service=self._service_name(incident),
            mechanism="deployment",
            severity="info",
            description="Deployment introduced the first observed change",
            source_of_truth="observability.propagation_engine",
            evidence_origin=self._evidence_origin(incident, deployment_correlation),
        ))

        if self._has_signal(incident, metrics_anomalies, ["latency", "slow", "response time", "p95", "p99"]):
            chain.append(self._event(
                event_id=f"{incident.get('incident_id', 'incident')}:latency",
                timestamp=self._offset(incident_ts, minutes=5),
                source_service=self._service_name(incident),
                target_service=self._service_name(incident),
                mechanism="latency increase",
                severity="warning",
                description="Latency increased before downstream retries",
                source_of_truth="observability.propagation_engine",
                evidence_origin=self._evidence_origin(incident, deployment_correlation, metrics_anomalies),
            ))

        if self._has_signal(incident, metrics_anomalies, ["retry", "backoff", "storm", "throttle"]):
            chain.append(self._event(
                event_id=f"{incident.get('incident_id', 'incident')}:retries",
                timestamp=self._offset(incident_ts, minutes=10),
                source_service=self._service_name(incident),
                target_service=self._service_name(incident),
                mechanism="retry storm",
                severity="warning",
                description="Retries amplified the original latency issue",
                source_of_truth="observability.propagation_engine",
                evidence_origin=self._evidence_origin(incident, metrics_anomalies),
            ))

        if self._has_signal(incident, metrics_anomalies, ["saturation", "exhaust", "pool", "oom", "memory", "queue"]):
            chain.append(self._event(
                event_id=f"{incident.get('incident_id', 'incident')}:saturation",
                timestamp=self._offset(incident_ts, minutes=15),
                source_service=self._service_name(incident),
                target_service=self._service_name(incident),
                mechanism="saturation",
                severity="critical",
                description="Retries and load saturated the service",
                source_of_truth="observability.propagation_engine",
                evidence_origin=self._evidence_origin(incident, metrics_anomalies),
            ))

        if self._has_signal(incident, metrics_anomalies, ["timeout", "unavailable", "503", "down", "outage"]):
            chain.append(self._event(
                event_id=f"{incident.get('incident_id', 'incident')}:timeout",
                timestamp=self._offset(incident_ts, minutes=20),
                source_service=self._service_name(incident),
                target_service=self._service_name(incident),
                mechanism="downstream timeout",
                severity="critical",
                description="Downstream requests started timing out",
                source_of_truth="observability.propagation_engine",
                evidence_origin=self._evidence_origin(incident, metrics_anomalies),
            ))

        final_state = "outage" if self._has_signal(incident, metrics_anomalies, ["outage", "down", "503", "unavailable"]) else (
            "timeout" if self._has_signal(incident, metrics_anomalies, ["timeout"]) else (
                "saturation" if self._has_signal(incident, metrics_anomalies, ["saturation", "exhaust", "pool", "oom"]) else (
                    "retry_storm" if self._has_signal(incident, metrics_anomalies, ["retry", "backoff", "storm"]) else (
                        "latency" if self._has_signal(incident, metrics_anomalies, ["latency", "slow", "p95", "p99"]) else "stable"
                    )
                )
            )
        )

        if final_state == "outage":
            summary = "Deployment propagated through latency, retries, saturation, and downstream timeouts into outage"
            recommended_action = "Trace the deployment delta, then rollback or disable the causal change"
            likelihood = 0.92
        elif final_state == "timeout":
            summary = "Latency and retry amplification cascaded into downstream timeouts"
            recommended_action = "Reduce retries and validate the degraded downstream dependency"
            likelihood = 0.82
        elif final_state == "saturation":
            summary = "Retry amplification saturated service resources"
            recommended_action = "Stabilize load, cap retries, and relieve saturation"
            likelihood = 0.74
        elif final_state == "retry_storm":
            summary = "Initial latency increase triggered a retry storm"
            recommended_action = "Inspect retry policy and upstream latency regression"
            likelihood = 0.66
        elif final_state == "latency":
            summary = "Latency increased after the deployment window"
            recommended_action = "Verify the deployment for latency regressions"
            likelihood = 0.58
        else:
            summary = "No multi-hop propagation chain inferred"
            recommended_action = "Use the incident timeline to collect stronger causal evidence"
            likelihood = 0.35

        hypothesis = RCAHypothesis(
            source_of_truth="observability.propagation_engine",
            timestamp=incident_ts,
            confidence_origin="rule_based_causal_inference",
            evidence_origin=self._evidence_origin(incident, deployment_correlation, metrics_anomalies),
            persistence_rules={
                "retention": "indefinite",
                "mutability": "append-only",
                "rewrite_policy": "source-driven",
            },
            hypothesis_id=f"{incident.get('incident_id', 'incident')}:rca",
            incident_id=str(incident.get("incident_id", incident.get("signature", "incident"))),
            hypothesis=summary,
            likelihood=likelihood,
            supporting_evidence_ids=[event.event_id for event in chain],
            counter_evidence_ids=[entry.get("evidence_id") for entry in regression_history if entry.get("evidence_id")],
            conclusion=summary,
        )

        return {
            "incident": incident,
            "deployment": deployment.model_dump() if deployment else None,
            "metrics_anomalies": metrics_anomalies,
            "regression_history": regression_history,
            "propagation_chain": [event.model_dump() for event in chain],
            "final_state": final_state,
            "summary": summary,
            "recommended_action": recommended_action,
            "hypothesis": hypothesis.model_dump(),
        }

    def _infer_deployment(self, incident: Dict[str, Any], deployment_correlation: Dict[str, Any]) -> Optional[Deployment]:
        if not deployment_correlation.get("matched") and not any(incident.get(key) for key in ["deployment_id", "commit_hash", "deployment_time", "last_deploy_time"]):
            return None

        deployment_time = deployment_correlation.get("events", [{}])[0].get("time") if deployment_correlation.get("events") else incident.get("deployment_time")
        deployment_time = normalize_timestamp(deployment_time) or normalize_timestamp(incident.get("timestamp")) or datetime.utcnow()

        return Deployment(
            source_of_truth="observability.propagation_engine",
            timestamp=deployment_time,
            confidence_origin="deployment_correlation",
            evidence_origin=self._evidence_origin(incident, deployment_correlation),
            persistence_rules={
                "retention": "indefinite",
                "mutability": "append-only",
                "rewrite_policy": "source-driven",
            },
            deployment_id=str(incident.get("deployment_id") or incident.get("commit_hash") or "deployment:unknown"),
            service=self._service_name(incident),
            environment=incident.get("environment", "production"),
            status=str(incident.get("deployment_status", deployment_correlation.get("status", "deployed"))),
            commit_hash=incident.get("commit_hash"),
            workflow_name=incident.get("workflow_name"),
            rollback_of=incident.get("rollback_of"),
            actor=incident.get("actor"),
            url=incident.get("deployment_url") or incident.get("url"),
        )

    def _event(self, **kwargs: Any) -> PropagationEvent:
        return PropagationEvent(
            source_of_truth=kwargs.pop("source_of_truth"),
            timestamp=kwargs.pop("timestamp"),
            confidence_origin="rule_based_causal_inference",
            evidence_origin=kwargs.pop("evidence_origin"),
            persistence_rules={
                "retention": "indefinite",
                "mutability": "append-only",
                "rewrite_policy": "source-driven",
            },
            event_id=kwargs.pop("event_id"),
            source_service=kwargs.pop("source_service"),
            target_service=kwargs.pop("target_service"),
            mechanism=kwargs.pop("mechanism"),
            severity=kwargs.pop("severity"),
            latency_ms=kwargs.pop("latency_ms", None),
            impact_summary=kwargs.pop("description"),
        )

    def _offset(self, timestamp: datetime, minutes: int) -> datetime:
        return timestamp + timedelta(minutes=minutes)

    def _has_signal(self, incident: Dict[str, Any], metrics_anomalies: List[Dict[str, Any]], words: List[str]) -> bool:
        haystack = " ".join(
            [
                str(incident.get("signature", "")),
                str(incident.get("summary", "")),
                str(incident.get("sample_message", "")),
                " ".join(str(error.get("message", "")) for error in incident.get("errors", [])),
                " ".join(str(anomaly.get("metric_name", "")) for anomaly in metrics_anomalies),
            ]
        ).lower()
        return any(word in haystack for word in words)

    def _service_name(self, incident: Dict[str, Any]) -> str:
        if incident.get("service"):
            return str(incident["service"])
        modules = incident.get("modules") or []
        return str(modules[0] if modules else incident.get("module", "unknown"))

    def _evidence_origin(self, incident: Dict[str, Any], *bundles: Any) -> List[str]:
        origins: List[str] = []
        for bundle in bundles:
            if isinstance(bundle, dict):
                for key in ["source_of_truth", "incident_id", "deployment_id", "commit_hash"]:
                    value = bundle.get(key)
                    if value:
                        origins.append(str(value))
                for event in bundle.get("events", []):
                    if isinstance(event, dict):
                        label = event.get("type") or event.get("time")
                        if label:
                            origins.append(str(label))
            elif isinstance(bundle, list):
                for item in bundle:
                    if isinstance(item, dict):
                        if item.get("evidence_id"):
                            origins.append(str(item["evidence_id"]))
                        elif item.get("metric_name"):
                            origins.append(str(item["metric_name"]))

        if incident.get("id"):
            origins.append(str(incident["id"]))
        if incident.get("signature"):
            origins.append(str(incident["signature"]))
        return origins