from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from core.normalization import normalize_timestamp


@dataclass
class CausalNode:
    node_id: str
    kind: str
    label: str
    timestamp: datetime
    payload: Dict[str, Any] = field(default_factory=dict)
    source_of_truth: str = "memory.causal_graph"
    confidence_origin: str = "causal_graph"
    evidence_origin: List[str] = field(default_factory=list)
    persistence_rules: Dict[str, Any] = field(default_factory=lambda: {
        "retention": "indefinite",
        "mutability": "append-only",
        "rewrite_policy": "source-driven",
    })


@dataclass
class CausalEdge:
    source_id: str
    target_id: str
    relationship: str
    confidence: float
    timestamp: datetime
    source_of_truth: str = "memory.causal_graph"
    confidence_origin: str = "causal_graph"
    evidence_origin: List[str] = field(default_factory=list)


class CausalGraph:
    """Temporal causal graph for operational reasoning."""

    def __init__(self):
        self.nodes: Dict[str, CausalNode] = {}
        self.edges: List[CausalEdge] = []

    def add_node(
        self,
        node_id: str,
        kind: str,
        label: str,
        timestamp: Any,
        payload: Optional[Dict[str, Any]] = None,
        evidence_origin: Optional[List[str]] = None,
        source_of_truth: str = "memory.causal_graph",
        confidence_origin: str = "causal_graph",
    ) -> CausalNode:
        node = CausalNode(
            node_id=node_id,
            kind=kind,
            label=label,
            timestamp=normalize_timestamp(timestamp) or datetime.utcnow(),
            payload=payload or {},
            source_of_truth=source_of_truth,
            confidence_origin=confidence_origin,
            evidence_origin=evidence_origin or [],
        )
        self.nodes[node_id] = node
        return node

    def add_edge(
        self,
        source_id: str,
        target_id: str,
        relationship: str,
        confidence: float = 0.75,
        evidence_origin: Optional[List[str]] = None,
        source_of_truth: str = "memory.causal_graph",
    ) -> CausalEdge:
        edge = CausalEdge(
            source_id=source_id,
            target_id=target_id,
            relationship=relationship,
            confidence=max(0.0, min(1.0, float(confidence))),
            timestamp=self.nodes[target_id].timestamp if target_id in self.nodes else datetime.utcnow(),
            source_of_truth=source_of_truth,
            confidence_origin="causal_graph",
            evidence_origin=evidence_origin or [],
        )
        self.edges.append(edge)
        return edge

    def add_propagation_chain(self, propagation_chain: List[Dict[str, Any]]) -> None:
        previous_id: Optional[str] = None
        for event in propagation_chain:
            node_id = str(event.get("event_id") or event.get("phase") or len(self.nodes))
            self.add_node(
                node_id=node_id,
                kind="propagation_event",
                label=str(event.get("description") or event.get("mechanism") or node_id),
                timestamp=event.get("timestamp"),
                payload=event,
                evidence_origin=list(event.get("evidence_origin") or []),
            )
            if previous_id is not None:
                self.add_edge(previous_id, node_id, "propagates_to", confidence=0.9, evidence_origin=list(event.get("evidence_origin") or []))
            previous_id = node_id

    def build_from_incident(
        self,
        incident: Dict[str, Any],
        propagation_chain: List[Dict[str, Any]],
        deployment_correlation: Optional[Dict[str, Any]] = None,
        metrics_anomalies: Optional[List[Dict[str, Any]]] = None,
        regression_history: Optional[List[Dict[str, Any]]] = None,
    ) -> "CausalGraph":
        incident_id = str(incident.get("incident_id") or incident.get("signature") or "incident")
        incident_node = self.add_node(
            node_id=incident_id,
            kind="incident",
            label=str(incident.get("summary") or incident.get("signature") or incident_id),
            timestamp=incident.get("timestamp"),
            payload=incident,
            evidence_origin=list(incident.get("evidence_origin") or []),
            source_of_truth=str(incident.get("source_of_truth", "pipeline.analysis")),
            confidence_origin=str(incident.get("confidence_origin", "causal_grounding")),
        )

        if deployment_correlation and deployment_correlation.get("events"):
            for idx, event in enumerate(deployment_correlation.get("events", [])):
                node_id = f"deployment:{idx}"
                self.add_node(
                    node_id=node_id,
                    kind="deployment",
                    label=str(event.get("type", "deployment")),
                    timestamp=event.get("time"),
                    payload=event,
                    evidence_origin=[str(event.get("type", "deployment"))],
                )
                self.add_edge(node_id, incident_node.node_id, "correlates_with", confidence=float(deployment_correlation.get("score", 0.5)), evidence_origin=[str(event.get("type", "deployment"))])

        if metrics_anomalies:
            for idx, anomaly in enumerate(metrics_anomalies):
                node_id = f"metric:{idx}"
                self.add_node(
                    node_id=node_id,
                    kind="metric_anomaly",
                    label=str(anomaly.get("metric_name", "metric_anomaly")),
                    timestamp=incident.get("timestamp"),
                    payload=anomaly,
                    evidence_origin=[str(anomaly.get("metric_name", "metric"))],
                )
                self.add_edge(incident_node.node_id, node_id, "observed_as", confidence=0.65, evidence_origin=[str(anomaly.get("metric_name", "metric"))])

        if regression_history:
            for idx, regression in enumerate(regression_history):
                node_id = f"regression:{idx}"
                self.add_node(
                    node_id=node_id,
                    kind="regression",
                    label=str(regression.get("summary") or regression.get("incident_id") or node_id),
                    timestamp=regression.get("timestamp") or incident.get("timestamp"),
                    payload=regression,
                    evidence_origin=[str(regression.get("incident_id") or node_id)],
                )
                self.add_edge(node_id, incident_node.node_id, "recurred_as", confidence=0.6, evidence_origin=[str(regression.get("incident_id") or node_id)])

        self.add_propagation_chain(propagation_chain)
        return self

    def timeline(self) -> List[Dict[str, Any]]:
        ordered = sorted(self.nodes.values(), key=lambda node: node.timestamp)
        return [
            {
                "node_id": node.node_id,
                "kind": node.kind,
                "label": node.label,
                "timestamp": node.timestamp.isoformat(),
                "payload": node.payload,
            }
            for node in ordered
        ]

    def summary(self) -> Dict[str, Any]:
        return {
            "node_count": len(self.nodes),
            "edge_count": len(self.edges),
            "node_kinds": sorted({node.kind for node in self.nodes.values()}),
            "relationships": sorted({edge.relationship for edge in self.edges}),
        }
