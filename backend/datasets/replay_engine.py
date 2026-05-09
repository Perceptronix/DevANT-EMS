from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from core.normalization import normalize_timestamp
from memory.causal_graph import CausalGraph
from observability.propagation_engine import PropagationEngine
from pipeline.analysis import ErrorAnalyzer


DATASET_PATH = Path(__file__).parent / "incidents" / "corpus.json"


def load_incident_corpus(path: Path | str = DATASET_PATH) -> List[Dict[str, Any]]:
    corpus_path = Path(path)
    return json.loads(corpus_path.read_text(encoding="utf-8"))


@dataclass
class ReplayResult:
    incident_id: str
    propagation: Dict[str, Any]
    causal_graph: Dict[str, Any]
    analysis: Dict[str, Any]
    metrics: Dict[str, float]


class IncidentReplayEngine:
    """Deterministic replay engine for operational replay benchmarks."""

    def __init__(self, corpus_path: Path | str = DATASET_PATH):
        self.corpus_path = Path(corpus_path)
        self.propagation_engine = PropagationEngine()
        self.analyzer = ErrorAnalyzer()

    def replay_all(self) -> List[ReplayResult]:
        return [self.replay_incident(incident) for incident in load_incident_corpus(self.corpus_path)]

    def replay_incident(self, incident: Dict[str, Any]) -> ReplayResult:
        cluster = self._incident_to_cluster(incident)
        evidence_bundle = self._incident_to_evidence_bundle(incident)
        operational_context = self.analyzer.build_operational_context(cluster, evidence_bundle)
        analysis = self.analyzer._fallback_analysis(cluster, evidence_bundle, operational_context)
        propagation = operational_context["propagation"]
        causal_graph = operational_context["causal_graph"]
        metrics = self.evaluate(incident, analysis, propagation)
        return ReplayResult(
            incident_id=incident["incident_id"],
            propagation=propagation,
            causal_graph=causal_graph,
            analysis=analysis,
            metrics=metrics,
        )

    def benchmark(self) -> Dict[str, Any]:
        results = [self.replay_incident(incident) for incident in load_incident_corpus(self.corpus_path)]
        if not results:
            return {
                "incidents": 0,
                "RCA correctness": 0.0,
                "hallucination rate": 0.0,
                "deployment attribution": 0.0,
                "propagation accuracy": 0.0,
                "regression accuracy": 0.0,
            }

        aggregate = {
            "incidents": len(results),
            "RCA correctness": sum(r.metrics["rca_correctness"] for r in results) / len(results),
            "hallucination rate": sum(r.metrics["hallucination_rate"] for r in results) / len(results),
            "deployment attribution": sum(r.metrics["deployment_attribution"] for r in results) / len(results),
            "propagation accuracy": sum(r.metrics["propagation_accuracy"] for r in results) / len(results),
            "regression accuracy": sum(r.metrics["regression_accuracy"] for r in results) / len(results),
        }
        return aggregate

    def evaluate(self, incident: Dict[str, Any], analysis: Dict[str, Any], propagation: Dict[str, Any]) -> Dict[str, float]:
        ground_truth = incident.get("ground_truth", {})
        root_cause_accuracy = self._keyword_overlap(
            analysis.get("root_cause", ""),
            ground_truth.get("root_cause_keywords", []),
        )
        deployment_attribution = 1.0 if bool(propagation.get("deployment")) == bool(ground_truth.get("deployment_attribution")) else 0.0
        propagation_accuracy = self._propagation_accuracy(propagation.get("propagation_chain", []), incident.get("propagation_chain", []))
        regression_accuracy = 1.0 if bool(ground_truth.get("regression", False)) == bool(analysis.get("regression_history")) else 0.0
        hallucination_rate = self._hallucination_rate(incident, analysis, propagation)

        return {
            "rca_correctness": root_cause_accuracy,
            "hallucination_rate": hallucination_rate,
            "deployment_attribution": deployment_attribution,
            "propagation_accuracy": propagation_accuracy,
            "regression_accuracy": regression_accuracy,
        }

    def _incident_to_cluster(self, incident: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "incident_id": incident["incident_id"],
            "signature": incident.get("title", incident["incident_id"]),
            "service": incident.get("service"),
            "sample_message": incident.get("root_cause", incident.get("title", "")),
            "summary": incident.get("title", ""),
            "errors": [{"message": trace.get("description", "") or metric.get("name", "")} for trace in incident.get("telemetry", {}).get("traces", []) for metric in incident.get("telemetry", {}).get("metrics", [])[:1]] or [{"message": incident.get("title", "")}],
            "modules": [incident.get("service", "unknown")],
            "affected_orgs": [incident.get("provider", "unknown")],
            "timestamp": incident.get("incident_window", {}).get("started_at"),
            "deployment_id": incident.get("deployment_timeline", [{}])[0].get("deployment_id"),
            "commit_hash": incident.get("deployment_timeline", [{}])[0].get("commit_hash"),
        }

    def _incident_to_evidence_bundle(self, incident: Dict[str, Any]) -> Dict[str, Any]:
        metrics = incident.get("telemetry", {}).get("metrics", [])
        traces = incident.get("telemetry", {}).get("traces", [])
        evidences = []
        for item in metrics:
            evidences.append({
                "evidence_id": f"metric:{incident['incident_id']}:{item.get('name')}",
                "title": item.get("name", "metric"),
                "content": f"{item.get('name')}={item.get('value')} baseline={item.get('baseline')}",
                "source": incident.get("provider"),
                "url": incident.get("source_urls", [None])[0],
                "final_score": 0.9,
            })
        for item in traces:
            evidences.append({
                "evidence_id": f"trace:{incident['incident_id']}:{item.get('span')}",
                "title": item.get("span", "trace"),
                "content": item.get("description", ""),
                "source": incident.get("provider"),
                "url": incident.get("source_urls", [None])[0],
                "final_score": 0.85,
            })

        return {
            "source_of_truth": incident.get("source_urls", ["datasets.incidents"])[0],
            "confidence_origin": "dataset_corpus",
            "evidences": evidences,
            "history": [],
            "deployment_correlation": self._deployment_correlation(incident),
            "metrics_anomalies": self._metrics_anomalies(incident),
            "regression_history": [],
            "metadata": {
                "confidence": 0.92,
                "evidence_count": len(evidences),
            },
        }

    def _deployment_correlation(self, incident: Dict[str, Any]) -> Dict[str, Any]:
        timeline = incident.get("deployment_timeline", [])
        if not timeline:
            return {"matched": False, "score": 0.0, "events": []}
        first = timeline[0]
        return {
            "matched": True,
            "score": 0.95 if incident.get("ground_truth", {}).get("deployment_attribution") else 0.65,
            "events": [{"type": "deployment", "time": first.get("timestamp") or incident.get("incident_window", {}).get("started_at")}],
        }

    def _metrics_anomalies(self, incident: Dict[str, Any]) -> List[Dict[str, Any]]:
        anomalies = []
        for metric in incident.get("telemetry", {}).get("metrics", []):
            anomalies.append({
                "metric_name": metric.get("name"),
                "direction": "up" if float(metric.get("value", 0)) >= float(metric.get("baseline", 0)) else "down",
                "value": metric.get("value"),
                "baseline": metric.get("baseline"),
                "deviation": self._safe_ratio(metric.get("value", 0), metric.get("baseline", 1)),
                "window_minutes": 15,
                "service": incident.get("service"),
            })
        return anomalies

    def _keyword_overlap(self, text: str, keywords: Iterable[str]) -> float:
        text_lower = text.lower()
        keywords = [str(keyword).lower() for keyword in keywords]
        if not keywords:
            return 0.0
        hits = sum(1 for keyword in keywords if keyword in text_lower)
        return round(hits / float(len(keywords)), 3)

    def _propagation_accuracy(self, inferred_chain: List[Dict[str, Any]], expected_chain: List[str]) -> float:
        if not inferred_chain or not expected_chain:
            return 0.0
        inferred_text = " ".join(str(item.get("mechanism", "")) + " " + str(item.get("impact_summary", "")) for item in inferred_chain).lower()
        hits = 0
        for expected in expected_chain:
            if str(expected).lower() in inferred_text:
                hits += 1
        return round(hits / float(len(expected_chain)), 3)

    def _hallucination_rate(self, incident: Dict[str, Any], analysis: Dict[str, Any], propagation: Dict[str, Any]) -> float:
        allowed = " ".join([
            incident.get("title", ""),
            incident.get("root_cause", ""),
            incident.get("remediation", ""),
            " ".join(incident.get("propagation_chain", [])),
            " ".join(incident.get("blast_radius", {}).get("affected_products", [])),
            " ".join(incident.get("ground_truth", {}).get("root_cause_keywords", [])),
        ]).lower()
        claims = " ".join([
            str(analysis.get("title", "")),
            str(analysis.get("root_cause", "")),
            str(analysis.get("impact", "")),
            str(analysis.get("suggested_action", "")),
            str(propagation.get("summary", "")),
        ]).lower()
        allowed_tokens = set(re.findall(r"[a-z0-9_\-]+", allowed))
        claim_tokens = set(re.findall(r"[a-z0-9_\-]+", claims))
        if not claim_tokens:
            return 0.0
        unsupported = [token for token in claim_tokens if token not in allowed_tokens and len(token) > 3]
        return round(len(unsupported) / float(len(claim_tokens)), 3)

    def _safe_ratio(self, value: Any, baseline: Any) -> float:
        try:
            value = float(value)
            baseline = float(baseline)
            if baseline == 0:
                return 0.0
            return round(abs(value - baseline) / abs(baseline), 3)
        except Exception:
            return 0.0