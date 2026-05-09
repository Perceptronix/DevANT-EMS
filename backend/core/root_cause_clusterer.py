"""
Root Cause Clustering Engine — semantic error grouping and operational analysis.

This keeps the public RootCauseClusterer API stable while replacing the
exact-signature-first flow with hybrid semantic clustering based on:
- embeddings
- stacktrace/fingerprint similarity
- deployment context
- temporal proximity
"""
from __future__ import annotations

import hashlib
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import numpy as np

from core.embeddings_cache import get_embedder
from core.normalization import normalize_text, normalize_timestamp
from intelligence.root_cause_engine import RootCauseEngine
from memory.operational_fingerprint import OperationalFingerprintEngine

logger = logging.getLogger(__name__)


@dataclass
class ErrorCluster:
    cluster_id: str
    root_cause: str
    affected_services: List[str]
    error_signatures: List[str]
    error_count: int
    affected_orgs: List[str]
    severity: str
    frequency_trend: str
    regression_probability: float
    deployment_related: bool
    deployment_ids: List[str] = field(default_factory=list)
    confidence: float = 0.9
    historical_matches: List[str] = field(default_factory=list)
    last_seen: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    topology_affected: List[str] = field(default_factory=list)
    evidence_score: float = 0.0
    signature: str = ""
    operational_severity: str = "informational"
    semantic_similarity: float = 0.0
    stacktrace_similarity: float = 0.0
    deployment_context: float = 0.0
    temporal_proximity: float = 0.0
    historical_recurrence: float = 0.0
    signal_types: List[str] = field(default_factory=list)
    representative_evidence: List[Dict[str, Any]] = field(default_factory=list)
    centroid_text: str = ""


class RootCauseClusterer:
    """Production-grade error clustering engine."""

    def __init__(self, embedding_model: str = "all-MiniLM-L6-v2", embedder: Optional[Any] = None):
        self.embedding_model_name = embedding_model
        self._embedder = embedder if embedder is not None else get_embedder(embedding_model)
        self._fingerprints = OperationalFingerprintEngine()
        self._root_cause_engine = RootCauseEngine(embedding_model=embedding_model, embedder=embedder)
        self._cluster_cache: Dict[str, ErrorCluster] = {}
        self._signature_to_clusters: Dict[str, str] = {}
        self._deployment_map: Dict[str, List[str]] = defaultdict(list)

    def cluster_errors(
        self,
        errors: List[Dict[str, Any]],
        deployment_info: Optional[Dict[str, Any]] = None,
    ) -> List[ErrorCluster]:
        if not errors:
            return []

        prepared = [self._prepare_error(error, deployment_info) for error in errors]
        clusters = self._build_hybrid_clusters(prepared)

        if deployment_info:
            clusters = self._correlate_deployments(clusters, deployment_info)

        for cluster in clusters:
            hypothesis = self._root_cause_engine.analyze_cluster(self._cluster_to_payload(cluster))
            cluster.root_cause = hypothesis.likely_cause
            cluster.operational_severity = hypothesis.severity
            cluster.severity = self._map_operational_severity(hypothesis.severity)
            cluster.confidence = max(cluster.confidence, hypothesis.confidence)
            cluster.historical_recurrence = max(cluster.historical_recurrence, hypothesis.recurrence_score)
            cluster.representative_evidence = (cluster.representative_evidence + hypothesis.evidence[:5])[:10]
            cluster.signature = cluster.signature or (cluster.error_signatures[0] if cluster.error_signatures else cluster.root_cause)
            cluster.historical_matches = list(dict.fromkeys(cluster.historical_matches))

        clusters.sort(
            key=lambda c: (
                self._severity_rank(c.severity),
                -c.error_count,
                -c.confidence,
            )
        )
        return clusters

    def update_cluster_history(
        self,
        cluster: ErrorCluster,
        historical_incidents: List[Dict[str, Any]],
    ) -> ErrorCluster:
        if not historical_incidents:
            return cluster

        matches = self._find_historical_matches(cluster, historical_incidents)
        cluster.historical_matches = [match["incident_id"] for match in matches if match.get("incident_id")]
        if len(matches) >= 2:
            cluster.regression_probability = min(1.0, cluster.regression_probability + 0.3)
            cluster.historical_recurrence = min(1.0, cluster.historical_recurrence + 0.3)
        return cluster

    def _prepare_error(self, error: Dict[str, Any], deployment_info: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        prepared = dict(error)
        prepared["_cluster_text"] = normalize_text(" ".join(str(part) for part in [
            error.get("signature"),
            error.get("message"),
            error.get("stack_trace"),
            error.get("stacktrace"),
            error.get("error_type"),
            error.get("exception_type"),
            " ".join(error.get("changed_files", []) or []),
            error.get("commit_message"),
            error.get("deployment_message"),
        ] if part))
        prepared["_timestamp"] = normalize_timestamp(error.get("timestamp")) or datetime.now(timezone.utc)
        prepared["_fingerprint"] = self._fingerprints.fingerprint_incident(error)
        prepared["_deployment_info"] = deployment_info or {}
        return prepared

    def _build_hybrid_clusters(self, errors: List[Dict[str, Any]]) -> List[ErrorCluster]:
        clusters: List[ErrorCluster] = []
        for error in errors:
            best_cluster = None
            best_score = 0.0
            for cluster in clusters:
                score = self._error_cluster_similarity(error, cluster)
                if score > best_score:
                    best_cluster = cluster
                    best_score = score

            if best_cluster is not None and best_score >= 0.72:
                self._attach_error(best_cluster, error, best_score)
            else:
                clusters.append(self._new_cluster(error))

        return self._merge_similar_clusters(clusters)

    def _new_cluster(self, error: Dict[str, Any]) -> ErrorCluster:
        signature = error.get("signature") or error.get("message") or error.get("_fingerprint").normalized_signature
        cluster_id = f"cluster_{hashlib.md5(signature.encode('utf-8')).hexdigest()[:12]}"
        services = self._error_services(error)
        orgs = list(dict.fromkeys(error.get("affected_orgs", []) or []))
        root_cause = self._generate_preliminary_root_cause([error])
        evidence_score = self._compute_evidence_score([error])
        return ErrorCluster(
            cluster_id=cluster_id,
            root_cause=root_cause,
            affected_services=services,
            error_signatures=[signature],
            error_count=1,
            affected_orgs=orgs,
            severity=self._infer_severity([error], services),
            frequency_trend="stable",
            regression_probability=self._estimate_regression_probability([error]),
            deployment_related=False,
            confidence=min(1.0, 0.65 + (evidence_score * 0.25)),
            topology_affected=services[:],
            evidence_score=evidence_score,
            signature=signature,
            centroid_text=error["_cluster_text"],
            signal_types=[self._signal_type(error)],
            representative_evidence=[self._cluster_evidence(error)],
            last_seen=error["_timestamp"].isoformat(),
        )

    def _attach_error(self, cluster: ErrorCluster, error: Dict[str, Any], similarity: float) -> None:
        signature = error.get("signature") or error.get("message") or error.get("_fingerprint").normalized_signature
        if signature not in cluster.error_signatures:
            cluster.error_signatures.append(signature)
        cluster.error_count += 1
        cluster.affected_services = list(dict.fromkeys(cluster.affected_services + self._error_services(error)))
        cluster.affected_orgs = list(dict.fromkeys(cluster.affected_orgs + (error.get("affected_orgs") or [])))
        if error.get("deployment_id"):
            cluster.deployment_ids = list(dict.fromkeys(cluster.deployment_ids + [error["deployment_id"]]))
        if error.get("commit_sha"):
            cluster.representative_evidence.append({"commit_sha": error.get("commit_sha")})
        if error.get("changed_files"):
            cluster.representative_evidence.append({"changed_files": error.get("changed_files")})
        if error.get("stack_trace") or error.get("stacktrace"):
            cluster.representative_evidence.append({"stack_trace": error.get("stack_trace") or error.get("stacktrace")})
        cluster.representative_evidence = cluster.representative_evidence[:10]
        cluster.confidence = min(1.0, max(cluster.confidence, similarity, self._confidence_from_error(error)))
        cluster.evidence_score = min(1.0, max(cluster.evidence_score, self._compute_evidence_score([error])))
        cluster.temporal_proximity = max(cluster.temporal_proximity, self._temporal_similarity(error, cluster))
        cluster.stacktrace_similarity = max(cluster.stacktrace_similarity, self._stacktrace_similarity(error, cluster))
        cluster.deployment_context = max(cluster.deployment_context, self._deployment_similarity(error, cluster))
        cluster.semantic_similarity = max(cluster.semantic_similarity, self._semantic_similarity_text(error["_cluster_text"], cluster.centroid_text or cluster.root_cause))
        cluster.historical_recurrence = min(1.0, cluster.historical_recurrence + (0.15 if cluster.error_count > 1 else 0.0))
        cluster.last_seen = max(cluster.last_seen, error["_timestamp"].isoformat())

    def _merge_similar_clusters(self, clusters: List[ErrorCluster]) -> List[ErrorCluster]:
        if len(clusters) <= 1:
            return clusters

        merged: List[ErrorCluster] = []
        consumed = set()
        for index, cluster in enumerate(clusters):
            if index in consumed:
                continue

            current = cluster
            for other_index in range(index + 1, len(clusters)):
                if other_index in consumed:
                    continue
                other = clusters[other_index]
                if self._cluster_similarity(current, other) >= 0.78:
                    current = self._merge_two_clusters(current, other)
                    consumed.add(other_index)
            merged.append(current)

        return merged

    def _merge_two_clusters(self, cluster_a: ErrorCluster, cluster_b: ErrorCluster) -> ErrorCluster:
        return ErrorCluster(
            cluster_id=cluster_a.cluster_id,
            root_cause=cluster_a.root_cause,
            affected_services=list(dict.fromkeys(cluster_a.affected_services + cluster_b.affected_services)),
            error_signatures=list(dict.fromkeys(cluster_a.error_signatures + cluster_b.error_signatures)),
            error_count=cluster_a.error_count + cluster_b.error_count,
            affected_orgs=list(dict.fromkeys(cluster_a.affected_orgs + cluster_b.affected_orgs)),
            severity=self._merge_severities(cluster_a.severity, cluster_b.severity),
            frequency_trend="increasing" if cluster_a.error_count + cluster_b.error_count > 10 else "stable",
            regression_probability=max(cluster_a.regression_probability, cluster_b.regression_probability),
            deployment_related=cluster_a.deployment_related or cluster_b.deployment_related,
            deployment_ids=list(dict.fromkeys(cluster_a.deployment_ids + cluster_b.deployment_ids)),
            confidence=min(1.0, max(cluster_a.confidence, cluster_b.confidence)),
            historical_matches=list(dict.fromkeys(cluster_a.historical_matches + cluster_b.historical_matches)),
            last_seen=max(cluster_a.last_seen, cluster_b.last_seen),
            topology_affected=list(dict.fromkeys(cluster_a.topology_affected + cluster_b.topology_affected)),
            evidence_score=max(cluster_a.evidence_score, cluster_b.evidence_score),
            signature=cluster_a.signature or cluster_b.signature,
            operational_severity=cluster_a.operational_severity or cluster_b.operational_severity,
            semantic_similarity=max(cluster_a.semantic_similarity, cluster_b.semantic_similarity),
            stacktrace_similarity=max(cluster_a.stacktrace_similarity, cluster_b.stacktrace_similarity),
            deployment_context=max(cluster_a.deployment_context, cluster_b.deployment_context),
            temporal_proximity=max(cluster_a.temporal_proximity, cluster_b.temporal_proximity),
            historical_recurrence=max(cluster_a.historical_recurrence, cluster_b.historical_recurrence),
            signal_types=list(dict.fromkeys(cluster_a.signal_types + cluster_b.signal_types)),
            representative_evidence=(cluster_a.representative_evidence + cluster_b.representative_evidence)[:10],
            centroid_text=cluster_a.centroid_text or cluster_b.centroid_text,
        )

    def _correlate_deployments(self, clusters: List[ErrorCluster], deployment_info: Dict[str, Any]) -> List[ErrorCluster]:
        recent_deployments = deployment_info.get("recent_deployments", [])
        deployment_window_minutes = 30

        for cluster in clusters:
            for deployment in recent_deployments:
                if self._is_deployment_correlated(cluster, deployment, deployment_window_minutes):
                    cluster.deployment_related = True
                    deployment_id = deployment.get("id", "")
                    if deployment_id:
                        cluster.deployment_ids.append(deployment_id)
                    cluster.deployment_ids = list(dict.fromkeys(cluster.deployment_ids))
                    cluster.regression_probability = min(1.0, cluster.regression_probability + 0.2)
                    cluster.deployment_context = max(cluster.deployment_context, 0.85)
        return clusters

    def _is_deployment_correlated(self, cluster: ErrorCluster, deployment: Dict[str, Any], window_minutes: int) -> bool:
        try:
            cluster_time = normalize_timestamp(cluster.last_seen)
            deployment_time = normalize_timestamp(deployment.get("timestamp", ""))
            if not cluster_time or not deployment_time:
                return False
            time_diff = abs((cluster_time - deployment_time).total_seconds() / 60)
            deployment_services = set(deployment.get("services", []) or deployment.get("services_touched", []) or [])
            cluster_services = set(cluster.affected_services)
            service_overlap = bool(deployment_services & cluster_services)
            return time_diff <= window_minutes and service_overlap
        except Exception:
            return False

    def _cluster_similarity(self, cluster_a: ErrorCluster, cluster_b: ErrorCluster) -> float:
        semantic_similarity = self._semantic_similarity_text(cluster_a.centroid_text or cluster_a.root_cause, cluster_b.centroid_text or cluster_b.root_cause)
        stacktrace_similarity = self._stacktrace_cluster_similarity(cluster_a, cluster_b)
        deployment_context = self._deployment_cluster_similarity(cluster_a, cluster_b)
        temporal_proximity = self._temporal_cluster_similarity(cluster_a, cluster_b)
        return max(0.0, min(1.0, semantic_similarity * 0.6 + stacktrace_similarity * 0.2 + deployment_context * 0.1 + temporal_proximity * 0.1))

    def _error_cluster_similarity(self, error: Dict[str, Any], cluster: ErrorCluster) -> float:
        semantic_similarity = self._semantic_similarity_text(error["_cluster_text"], cluster.centroid_text or cluster.root_cause)
        stacktrace_similarity = self._stacktrace_similarity(error, cluster)
        deployment_context = self._deployment_similarity(error, cluster)
        temporal_proximity = self._temporal_similarity(error, cluster)
        return max(0.0, min(1.0, semantic_similarity * 0.6 + stacktrace_similarity * 0.2 + deployment_context * 0.1 + temporal_proximity * 0.1))

    def _semantic_similarity_text(self, left: str, right: str) -> float:
        if not left or not right:
            return 0.0
        if self._embedder:
            try:
                embeddings = self._embedder.encode([left, right], normalize_embeddings=True)
                return max(0.0, min(1.0, float(np.dot(embeddings[0], embeddings[1]))))
            except Exception as exc:
                logger.debug("Embedding similarity failed: %s", exc)
        return self._token_similarity(left, right)

    def _stacktrace_cluster_similarity(self, cluster_a: ErrorCluster, cluster_b: ErrorCluster) -> float:
        fp_a = self._fingerprints.fingerprint_incident({"message": cluster_a.root_cause, "stacktrace": cluster_a.centroid_text, "service": cluster_a.affected_services[:1] or ["unknown"]})
        fp_b = self._fingerprints.fingerprint_incident({"message": cluster_b.root_cause, "stacktrace": cluster_b.centroid_text, "service": cluster_b.affected_services[:1] or ["unknown"]})
        comparison = self._fingerprints.compare(fp_a, fp_b)
        return float(comparison["similarity"])

    def _stacktrace_similarity(self, error: Dict[str, Any], cluster: ErrorCluster) -> float:
        text = error.get("stack_trace") or error.get("stacktrace") or error.get("message") or ""
        return self._token_similarity(text, cluster.centroid_text or cluster.root_cause)

    def _deployment_cluster_similarity(self, cluster_a: ErrorCluster, cluster_b: ErrorCluster) -> float:
        deployments_a = set(cluster_a.deployment_ids)
        deployments_b = set(cluster_b.deployment_ids)
        if deployments_a and deployments_b:
            return len(deployments_a & deployments_b) / len(deployments_a | deployments_b)
        services_a = set(cluster_a.affected_services)
        services_b = set(cluster_b.affected_services)
        if not services_a or not services_b:
            return 0.0
        return len(services_a & services_b) / len(services_a | services_b)

    def _deployment_similarity(self, error: Dict[str, Any], cluster: ErrorCluster) -> float:
        if error.get("deployment_id") and error.get("deployment_id") in cluster.deployment_ids:
            return 1.0
        if error.get("service") and error.get("service") in cluster.affected_services:
            return 0.6
        changed_files = set(error.get("changed_files") or [])
        if changed_files and any(changed_files.intersection(set(item.get("changed_files", []) or [])) for item in cluster.representative_evidence):
            return 0.7
        return 0.0

    def _temporal_cluster_similarity(self, cluster_a: ErrorCluster, cluster_b: ErrorCluster) -> float:
        time_a = normalize_timestamp(cluster_a.last_seen)
        time_b = normalize_timestamp(cluster_b.last_seen)
        if not time_a or not time_b:
            return 0.0
        delta_minutes = abs((time_a - time_b).total_seconds() / 60.0)
        if delta_minutes <= 30:
            return 1.0
        if delta_minutes <= 120:
            return 0.7
        if delta_minutes <= 720:
            return 0.4
        if delta_minutes <= 1440:
            return 0.2
        return 0.0

    def _temporal_similarity(self, error: Dict[str, Any], cluster: ErrorCluster) -> float:
        error_time = error.get("_timestamp") or normalize_timestamp(error.get("timestamp"))
        cluster_time = normalize_timestamp(cluster.last_seen)
        if not error_time or not cluster_time:
            return 0.0
        delta_minutes = abs((error_time - cluster_time).total_seconds() / 60.0)
        if delta_minutes <= 15:
            return 1.0
        if delta_minutes <= 60:
            return 0.7
        if delta_minutes <= 360:
            return 0.4
        return 0.0

    def _find_historical_matches(self, cluster: ErrorCluster, historical_incidents: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        matches = []
        cluster_signature = normalize_text(cluster.signature or cluster.root_cause)
        for incident in historical_incidents:
            historical_signature = normalize_text(incident.get("signature") or incident.get("root_cause") or incident.get("summary") or "")
            service_overlap = set(cluster.affected_services) & set(incident.get("affected_services", []) or incident.get("services", []) or [])
            incident_deployment_ids = []
            if incident.get("deployment_id"):
                incident_deployment_ids.append(incident["deployment_id"])
            incident_deployment_ids.extend(incident.get("deployment_ids", []) or [])
            deployment_overlap = set(cluster.deployment_ids) & set(incident_deployment_ids)
            if service_overlap or deployment_overlap or self._token_similarity(cluster_signature, historical_signature) >= 0.45:
                matches.append(incident)
        return matches

    def _cluster_evidence(self, error: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "signature": error.get("signature"),
            "message": error.get("message"),
            "stack_trace": error.get("stack_trace") or error.get("stacktrace"),
            "deployment_id": error.get("deployment_id"),
            "commit_sha": error.get("commit_sha"),
            "changed_files": error.get("changed_files", []),
            "timestamp": error.get("timestamp"),
        }

    def _cluster_to_payload(self, cluster: ErrorCluster) -> Dict[str, Any]:
        commit_shas = [item.get("commit_sha") for item in cluster.representative_evidence if item.get("commit_sha")]
        changed_files = [file for item in cluster.representative_evidence for file in item.get("changed_files", [])] if cluster.representative_evidence else []
        return {
            "cluster_id": cluster.cluster_id,
            "signature": cluster.signature or (cluster.error_signatures[0] if cluster.error_signatures else cluster.root_cause),
            "root_cause": cluster.root_cause,
            "affected_services": cluster.affected_services,
            "affected_orgs": cluster.affected_orgs,
            "error_count": cluster.error_count,
            "deployment_ids": cluster.deployment_ids,
            "commit_shas": commit_shas,
            "changed_files": changed_files,
            "topology_affected": cluster.topology_affected,
            "last_seen": cluster.last_seen,
            "confidence": cluster.confidence,
            "regression_probability": cluster.regression_probability,
            "historical_recurrence": cluster.historical_recurrence,
            "errors": cluster.representative_evidence,
        }

    def _generate_preliminary_root_cause(self, errors: List[Dict[str, Any]]) -> str:
        exception_types = defaultdict(int)
        services = []
        for error in errors:
            exception_types[error.get("exception_type", "Unknown")] += 1
            if error.get("service"):
                services.append(error["service"])
        most_common_exc = max(exception_types.items(), key=lambda item: item[1])[0]
        service_str = ", ".join(list(dict.fromkeys(services))[:3]) or "unknown service"
        return f"{most_common_exc} failures in {service_str}"

    def _error_services(self, error: Dict[str, Any]) -> List[str]:
        services = []
        if error.get("service"):
            services.append(str(error["service"]))
        for path in error.get("service_paths", []) or []:
            if isinstance(path, list):
                services.extend(str(step) for step in path if step)
            elif path:
                services.append(str(path))
        return list(dict.fromkeys([service for service in services if service and service != "unknown"]))

    def _infer_severity(self, errors: List[Dict[str, Any]], services: List[str]) -> str:
        error_count = len(errors)
        if error_count >= 50 and len(services) >= 3:
            return "S1"
        if error_count >= 20 and len(services) >= 2:
            return "S2"
        if error_count >= 5:
            return "S3"
        return "S4"

    def _estimate_regression_probability(self, errors: List[Dict[str, Any]]) -> float:
        error_count = len(errors)
        probability = 0.3 if error_count >= 10 else 0.1
        recent_errors = [error for error in errors if error.get("_timestamp") and (datetime.now(timezone.utc) - error["_timestamp"]).total_seconds() < 300]
        if len(recent_errors) / max(error_count, 1) > 0.5:
            probability += 0.3
        return min(1.0, probability)

    def _compute_evidence_score(self, errors: List[Dict[str, Any]]) -> float:
        score = 0.0
        error_count = len(errors)
        score += min(1.0, error_count / 50.0) * 0.3
        with_traces = sum(1 for error in errors if error.get("stack_trace") or error.get("stacktrace"))
        score += (with_traces / max(error_count, 1)) * 0.3
        with_metadata = sum(1 for error in errors if error.get("metadata"))
        score += (with_metadata / max(error_count, 1)) * 0.2
        services = set(error.get("service", "") for error in errors)
        score += (1.0 if len(services) == 1 else 0.5) * 0.2
        return min(1.0, score)

    def _confidence_from_error(self, error: Dict[str, Any]) -> float:
        confidence = 0.45
        if error.get("stack_trace") or error.get("stacktrace"):
            confidence += 0.2
        if error.get("deployment_id"):
            confidence += 0.15
        if error.get("commit_sha") or error.get("changed_files"):
            confidence += 0.15
        if error.get("signal_type"):
            confidence += 0.05
        return min(1.0, confidence)

    def _merge_severities(self, severity_a: str, severity_b: str) -> str:
        severity_rank = {"S1": 1, "S2": 2, "S3": 3, "S4": 4}
        return severity_a if severity_rank.get(severity_a, 4) <= severity_rank.get(severity_b, 4) else severity_b

    def _severity_rank(self, severity: str) -> int:
        return {"S1": 1, "S2": 2, "S3": 3, "S4": 4}.get(severity, 4)

    def _map_operational_severity(self, operational_severity: str) -> str:
        return {
            "outage-risk": "S1",
            "critical": "S2",
            "degraded": "S3",
            "informational": "S4",
        }.get(operational_severity, "S4")

    def _signal_type(self, error: Dict[str, Any]) -> str:
        message = normalize_text(" ".join(str(part) for part in [error.get("signature"), error.get("message"), error.get("stack_trace"), error.get("stacktrace")] if part))
        if any(token in message for token in ("deploy", "rollout", "release")):
            return "deployment_failed"
        if any(token in message for token in ("build", "compile", "ci")):
            return "build_failed"
        if any(token in message for token in ("timeout", "deadline exceeded")):
            return "workflow_timeout"
        if any(token in message for token in ("rollback",)):
            return "rollback_detected"
        if any(token in message for token in ("hotfix",)):
            return "hotfix_detected"
        if any(token in message for token in ("dependency", "package", "lockfile")):
            return "dependency_break"
        return "runtime_error"

    def _token_similarity(self, left: str, right: str) -> float:
        left_tokens = set(normalize_text(left).split())
        right_tokens = set(normalize_text(right).split())
        if not left_tokens or not right_tokens:
            return 0.0
        return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


__all__ = ["RootCauseClusterer", "ErrorCluster"]
