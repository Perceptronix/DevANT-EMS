from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence

from core.embeddings_cache import get_embedder
from core.normalization import normalize_text
from core.signal_fusion import SignalFusionEngine, SignalType as FusionSignalType
from memory.incident_graph import get_incident_graph
from memory.operational_fingerprint import OperationalFingerprintEngine

from signals import OperationalSignal, OperationalSignalNormalizer, SignalType as OperationalSignalType


@dataclass
class RootCauseHypothesis:
    summary: str
    likely_cause: str
    confidence: float
    severity: str
    recommended_actions: List[str] = field(default_factory=list)
    risk_assessment: str = "unknown"
    evidence: List[Dict[str, Any]] = field(default_factory=list)
    correlated_deployments: List[str] = field(default_factory=list)
    commit_evidence: List[Dict[str, Any]] = field(default_factory=list)
    suspected_files: List[str] = field(default_factory=list)
    likely_culprit_commit: Optional[str] = None
    likely_developer_owner: Optional[str] = None
    deployment_attribution: Dict[str, Any] = field(default_factory=dict)
    regression_warnings: List[str] = field(default_factory=list)
    affected_services: List[str] = field(default_factory=list)
    recurrence_score: float = 0.0
    blast_radius: int = 0


class RootCauseEngine:
    """Operational correlation engine for deployment-to-failure reasoning."""

    def __init__(self, embedding_model: str = "all-MiniLM-L6-v2", embedder: Optional[Any] = None):
        self._embedder = embedder if embedder is not None else get_embedder(embedding_model)
        self._fingerprints = OperationalFingerprintEngine()
        self._signal_normalizer = OperationalSignalNormalizer()
        self._incident_graph = get_incident_graph()

    def analyze_cluster(self, cluster: Dict[str, Any]) -> RootCauseHypothesis:
        signals = self._collect_signals(cluster)
        deployment_evidence = self._deployment_evidence(cluster, signals)
        commit_evidence = self._commit_evidence(cluster)
        commit_records = self._commit_records(cluster)
        topology_evidence = self._topology_evidence(cluster)
        recurrence = self._recurrence_evidence(cluster, signals)
        suspected_files = self._suspected_files(cluster, commit_records)
        likely_culprit_commit = self._likely_commit(commit_records, deployment_evidence)
        likely_developer_owner = self._likely_owner(cluster, commit_records)
        deployment_attribution = self._deployment_attribution(cluster, deployment_evidence, commit_records)
        regression_warnings = self._regression_warnings(cluster, recurrence, commit_records, deployment_evidence)

        likely_cause = self._infer_likely_cause(cluster, deployment_evidence, commit_evidence, topology_evidence, recurrence)
        severity = self._assess_severity(cluster, signals, recurrence)
        confidence = self._compute_confidence(cluster, signals, deployment_evidence, commit_evidence, topology_evidence, recurrence)
        risk_assessment = self._risk_assessment(severity, recurrence)

        summary = self._summary(cluster, likely_cause, deployment_evidence, topology_evidence)
        actions = self._recommended_actions(cluster, severity, deployment_evidence, recurrence, regression_warnings)

        self._update_memory(cluster, signals, recurrence)

        return RootCauseHypothesis(
            summary=summary,
            likely_cause=likely_cause,
            confidence=confidence,
            severity=severity,
            recommended_actions=actions,
            risk_assessment=risk_assessment,
            evidence=[signal.to_dict() for signal in signals],
            correlated_deployments=[item.get("deployment_id", "") for item in deployment_evidence if item.get("deployment_id")],
            commit_evidence=commit_records,
            suspected_files=suspected_files,
            likely_culprit_commit=likely_culprit_commit,
            likely_developer_owner=likely_developer_owner,
            deployment_attribution=deployment_attribution,
            regression_warnings=regression_warnings,
            affected_services=self._affected_services(cluster),
            recurrence_score=recurrence,
            blast_radius=self._blast_radius(cluster),
        )

    def analyze_signals(self, signals: Sequence[Dict[str, Any] | OperationalSignal]) -> RootCauseHypothesis:
        normalized: List[OperationalSignal] = []
        for signal in signals:
            if isinstance(signal, OperationalSignal):
                normalized.append(signal)
            else:
                normalized.append(OperationalSignal.from_dict(signal))

        cluster = {
            "signature": "signal_batch",
            "affected_services": [signal.service for signal in normalized if signal.service != "unknown"],
            "deployment_ids": [signal.deployment_id for signal in normalized if signal.deployment_id],
            "commit_shas": [signal.commit_sha for signal in normalized if signal.commit_sha],
            "error_count": len(normalized),
            "signals": [signal.to_dict() for signal in normalized],
            "last_seen": max((signal.timestamp for signal in normalized), default=datetime.now(timezone.utc)).isoformat(),
        }
        return self.analyze_cluster(cluster)

    def _collect_signals(self, cluster: Dict[str, Any]) -> List[OperationalSignal]:
        if cluster.get("signals"):
            normalized: List[OperationalSignal] = []
            for signal in cluster["signals"]:
                if isinstance(signal, OperationalSignal):
                    normalized.append(signal)
                elif isinstance(signal, dict):
                    normalized.append(OperationalSignal.from_dict(signal))
            return normalized

        evidence_payloads = cluster.get("errors") or cluster.get("evidence") or []
        if evidence_payloads and isinstance(evidence_payloads, list):
            return self._signal_normalizer.normalize(evidence_payloads, source=str(cluster.get("source", "cluster")))

        return self._signal_normalizer.normalize([
            {
                "message": cluster.get("signature") or cluster.get("root_cause") or "incident",
                "stacktrace": cluster.get("sample_message") or cluster.get("root_cause") or "",
                "timestamp": cluster.get("last_seen") or cluster.get("timestamp") or datetime.now(timezone.utc).isoformat(),
                "service": (cluster.get("affected_services") or ["unknown"])[0],
                "repo": cluster.get("repo") or "unknown",
                "deployment_id": (cluster.get("deployment_ids") or [None])[0],
                "commit_sha": cluster.get("commit_sha"),
                "severity": cluster.get("severity") or "informational",
                "confidence": cluster.get("confidence", 0.5),
            }
        ], source="cluster")

    def _deployment_evidence(self, cluster: Dict[str, Any], signals: Sequence[OperationalSignal]) -> List[Dict[str, Any]]:
        deployment_evidence: List[Dict[str, Any]] = []
        for signal in signals:
            if signal.deployment_id:
                deployment_evidence.append({
                    "deployment_id": signal.deployment_id,
                    "service": signal.service,
                    "timestamp": signal.timestamp.isoformat(),
                    "signal_type": signal.type.value,
                    "confidence": signal.confidence,
                })
        for deployment_id in cluster.get("deployment_ids") or []:
            if deployment_id and deployment_id not in {item.get("deployment_id") for item in deployment_evidence}:
                deployment_evidence.append({
                    "deployment_id": deployment_id,
                    "service": self._affected_services(cluster)[0] if self._affected_services(cluster) else "unknown",
                    "confidence": 0.7,
                })
        return deployment_evidence

    def _commit_evidence(self, cluster: Dict[str, Any]) -> List[str]:
        commits: List[str] = []
        for key in ("commit_sha", "commit_hash", "commit"):
            value = cluster.get(key)
            if isinstance(value, str) and value:
                commits.append(value)
            elif isinstance(value, list):
                commits.extend([str(item) for item in value if item])
        commits.extend([str(item) for item in cluster.get("commit_shas", []) if item])
        return list(dict.fromkeys(commits))

    def _commit_records(self, cluster: Dict[str, Any]) -> List[Dict[str, Any]]:
        records: List[Dict[str, Any]] = []
        candidates = cluster.get("commit_correlations") or cluster.get("incident_commit_correlations") or cluster.get("commits") or []

        if isinstance(candidates, dict):
            candidates = [candidates]

        for candidate in candidates:
            if not isinstance(candidate, dict):
                candidate = {"commit_sha": str(candidate)}

            commit_sha = candidate.get("commit_sha") or candidate.get("sha") or candidate.get("hash")
            if not commit_sha:
                continue

            files = candidate.get("suspect_files") or candidate.get("changed_files") or candidate.get("files") or []
            if isinstance(files, str):
                files = [files]

            records.append({
                "commit_sha": str(commit_sha),
                "author": candidate.get("author") or candidate.get("developer_owner") or candidate.get("owner"),
                "message": candidate.get("message") or candidate.get("title") or candidate.get("summary"),
                "confidence": float(candidate.get("confidence", candidate.get("score", 0.0)) or 0.0),
                "deployment_id": candidate.get("deployment_id") or candidate.get("deployment") or candidate.get("deployment_sha"),
                "files": [str(item) for item in files if item],
            })

        return records

    def _suspected_files(self, cluster: Dict[str, Any], commit_records: Sequence[Dict[str, Any]]) -> List[str]:
        files: List[str] = []
        for key in ("suspect_files", "changed_files", "files"):
            value = cluster.get(key) or []
            if isinstance(value, str):
                value = [value]
            for item in value:
                if item:
                    files.append(str(item))

        for record in commit_records:
            for item in record.get("files", []) or []:
                if item:
                    files.append(str(item))

        return list(dict.fromkeys(files))[:8]

    def _likely_commit(self, commit_records: Sequence[Dict[str, Any]], deployment_evidence: Sequence[Dict[str, Any]]) -> Optional[str]:
        if commit_records:
            ranked = sorted(commit_records, key=lambda item: float(item.get("confidence", 0.0) or 0.0), reverse=True)
            return ranked[0].get("commit_sha")
        for deployment in deployment_evidence:
            commit_sha = deployment.get("commit_sha") or deployment.get("commit_hash")
            if commit_sha:
                return str(commit_sha)
        return None

    def _likely_owner(self, cluster: Dict[str, Any], commit_records: Sequence[Dict[str, Any]]) -> Optional[str]:
        for key in ("developer_owner", "owner", "commit_owner"):
            value = cluster.get(key)
            if value:
                return str(value)
        for record in commit_records:
            owner = record.get("author")
            if owner:
                return str(owner)
        return None

    def _deployment_attribution(
        self,
        cluster: Dict[str, Any],
        deployment_evidence: Sequence[Dict[str, Any]],
        commit_records: Sequence[Dict[str, Any]],
    ) -> Dict[str, Any]:
        deployment = deployment_evidence[0] if deployment_evidence else {}
        return {
            "matched": bool(deployment_evidence),
            "deployment_id": deployment.get("deployment_id") or cluster.get("deployment_id"),
            "provider": deployment.get("provider") or cluster.get("deployment_provider"),
            "environment": deployment.get("environment") or cluster.get("deployment_environment"),
            "service": deployment.get("service") or (self._affected_services(cluster)[0] if self._affected_services(cluster) else None),
            "commit_sha": deployment.get("commit_sha") or (commit_records[0].get("commit_sha") if commit_records else cluster.get("commit_sha")),
            "score": float(deployment.get("confidence", deployment.get("score", 0.0)) or 0.0),
        }

    def _regression_warnings(
        self,
        cluster: Dict[str, Any],
        recurrence: float,
        commit_records: Sequence[Dict[str, Any]],
        deployment_evidence: Sequence[Dict[str, Any]],
    ) -> List[str]:
        warnings: List[str] = []
        if recurrence >= 0.6:
            warnings.append("High recurrence score indicates a likely regression pattern")
        if cluster.get("historical_matches"):
            warnings.append(f"Matches {len(cluster.get('historical_matches', []))} historical incident(s)")
        if len(commit_records) >= 2:
            warnings.append("Multiple correlated commits may indicate a repeated fix failure")
        if deployment_evidence and commit_records:
            warnings.append("Deployment and commit evidence align; verify whether the triggering deployment was rolled back")
        return warnings

    def _topology_evidence(self, cluster: Dict[str, Any]) -> List[str]:
        services = self._affected_services(cluster)
        topology = cluster.get("topology_affected") or cluster.get("critical_paths") or []
        paths = []
        for path in topology:
            if isinstance(path, list):
                paths.append(" -> ".join(str(step) for step in path if step))
            elif path:
                paths.append(str(path))
        return list(dict.fromkeys(services + paths))

    def _recurrence_evidence(self, cluster: Dict[str, Any], signals: Sequence[OperationalSignal]) -> float:
        recurrence = float(cluster.get("historical_recurrence", 0.0) or 0.0)
        if cluster.get("historical_matches"):
            recurrence = max(recurrence, min(1.0, len(cluster["historical_matches"]) / 4.0))
        if any(signal.type == OperationalSignalType.recurring_incident for signal in signals):
            recurrence = max(recurrence, 0.7)
        return min(1.0, recurrence)

    def _infer_likely_cause(
        self,
        cluster: Dict[str, Any],
        deployment_evidence: Sequence[Dict[str, Any]],
        commit_evidence: Sequence[str],
        topology_evidence: Sequence[str],
        recurrence: float,
    ) -> str:
        if deployment_evidence:
            deployment_ids = ", ".join(item.get("deployment_id", "") for item in deployment_evidence[:2] if item.get("deployment_id"))
            if commit_evidence:
                return f"Deployment {deployment_ids or 'unknown'} likely introduced the failure through commit {commit_evidence[0]}"
            return f"Deployment {deployment_ids or 'unknown'} is the most likely trigger for the failure"

        if commit_evidence:
            return f"Commit {commit_evidence[0]} likely changed the failing code path"

        if recurrence >= 0.6:
            return "Recurring incident pattern matches prior operational regression"

        if topology_evidence:
            return f"Failure propagated through {topology_evidence[0]}"

        return cluster.get("root_cause") or cluster.get("signature") or "Operational failure detected"

    def _assess_severity(self, cluster: Dict[str, Any], signals: Sequence[OperationalSignal], recurrence: float) -> str:
        blast_radius = self._blast_radius(cluster)
        criticality = 0.0
        if any(signal.type in {OperationalSignalType.deployment_failed, OperationalSignalType.workflow_timeout, OperationalSignalType.build_failed} for signal in signals):
            criticality += 0.3
        if any(signal.severity.lower() in {"critical", "high", "sev1", "s1"} for signal in signals):
            criticality += 0.2
        if recurrence >= 0.6:
            criticality += 0.2
        if len(self._affected_services(cluster)) >= 3:
            criticality += 0.2
        if blast_radius >= 8 or criticality >= 0.5:
            return "outage-risk"
        if blast_radius >= 5 or criticality >= 0.3:
            return "critical"
        if blast_radius >= 2 or criticality >= 0.15:
            return "degraded"
        return "informational"

    def _compute_confidence(
        self,
        cluster: Dict[str, Any],
        signals: Sequence[OperationalSignal],
        deployment_evidence: Sequence[Dict[str, Any]],
        commit_evidence: Sequence[str],
        topology_evidence: Sequence[str],
        recurrence: float,
    ) -> float:
        text = self._cluster_text(cluster)
        signal_texts = [self._signal_text(signal) for signal in signals[:4]]
        embed_score = 0.0
        if self._embedder and text and signal_texts:
            try:
                embeddings = self._embedder.encode([text, *signal_texts], normalize_embeddings=True)
                similarities = [float(embeddings[0] @ embedding) for embedding in embeddings[1:]]
                embed_score = sum(similarities) / max(1, len(similarities))
            except Exception:
                embed_score = 0.0

        signal_fusion = SignalFusionEngine()
        if any(signal.type == OperationalSignalType.recurring_incident for signal in signals):
            signal_fusion.add_signal(FusionSignalType.HISTORICAL_RECURRENCE, 0.7, "recurrence")
        if deployment_evidence:
            signal_fusion.add_signal(FusionSignalType.TEMPORAL_CORRELATION, min(1.0, 0.6 + 0.1 * len(deployment_evidence)), "deployment")
        if topology_evidence:
            signal_fusion.add_signal(FusionSignalType.PROPAGATION_ALIGNMENT, min(1.0, 0.5 + 0.1 * len(topology_evidence)), "topology")
        if commit_evidence:
            signal_fusion.add_signal(FusionSignalType.REGRESSION_SIMILARITY, 0.7, "commit")

        fusion = signal_fusion.fuse()
        evidence_score = min(1.0, 0.25 + 0.25 * bool(deployment_evidence) + 0.15 * bool(commit_evidence) + 0.15 * bool(topology_evidence) + 0.20 * recurrence)
        confidence = max(0.0, min(1.0, 0.4 * evidence_score + 0.35 * embed_score + 0.25 * fusion["confidence"]))
        return round(confidence, 3)

    def _risk_assessment(self, severity: str, recurrence: float) -> str:
        if severity == "outage-risk":
            return "Immediate rollback or mitigation required"
        if severity == "critical":
            return "High risk of user-visible outage or cascading failure"
        if recurrence >= 0.6:
            return "Known regression pattern with elevated recurrence risk"
        if severity == "degraded":
            return "Service degradation likely to continue without intervention"
        return "Low operational risk"

    def _summary(self, cluster: Dict[str, Any], likely_cause: str, deployment_evidence: Sequence[Dict[str, Any]], topology_evidence: Sequence[str]) -> str:
        service_text = ", ".join(self._affected_services(cluster)[:3]) or "unknown services"
        deployment_text = deployment_evidence[0].get("deployment_id", "unknown deployment") if deployment_evidence else "no deployment correlation"
        topology_text = topology_evidence[0] if topology_evidence else "no significant propagation path"
        return f"Failure in {service_text} aligns with {likely_cause}. Deployment context: {deployment_text}. Propagation context: {topology_text}."

    def _recommended_actions(self, cluster: Dict[str, Any], severity: str, deployment_evidence: Sequence[Dict[str, Any]], recurrence: float, regression_warnings: Sequence[str]) -> List[str]:
        actions: List[str] = []
        if deployment_evidence:
            actions.append("Compare failing revision against the last successful deployment")
            actions.append("Evaluate rollback or hotfix for the triggering deployment")
        if recurrence >= 0.6:
            actions.append("Search historical incidents for the same regression lineage")
        if regression_warnings:
            actions.append("Review regression warnings and confirm whether the same fix already failed before")
        if severity in {"critical", "outage-risk"}:
            actions.append("Escalate to on-call and verify downstream blast radius")
        if not actions:
            actions.append("Inspect the earliest failing signal and validate dependency health")
        return actions[:4]

    def _update_memory(self, cluster: Dict[str, Any], signals: Sequence[OperationalSignal], recurrence: float) -> None:
        incident_id = str(cluster.get("cluster_id") or cluster.get("signature") or f"incident-{datetime.now(timezone.utc).isoformat()}")
        services = self._affected_services(cluster)
        topology_text = self._topology_evidence(cluster)
        self._incident_graph.add_incident(
            incident_id=incident_id,
            timestamp=(cluster.get("last_seen") or cluster.get("timestamp") or datetime.now(timezone.utc).isoformat()),
            repo=str(cluster.get("repo") or "unknown"),
            dominant_service=services[0] if services else "unknown",
            blast_radius=self._blast_radius(cluster),
            operational_confidence=max(float(cluster.get("confidence", 0.5)), 0.5),
            regression_risk=max(float(cluster.get("regression_probability", 0.0) or 0.0), recurrence),
            topology_hash=normalize_text("|".join(services + topology_text))[:64] or "unknown",
            critical_paths=[topology_text] if topology_text else [],
            upstream_risk=min(1.0, recurrence + 0.1),
            downstream_risk=min(1.0, recurrence + 0.2),
        )

    def _signal_text(self, signal: OperationalSignal) -> str:
        return " ".join(part for part in [signal.type.value, signal.source, signal.repo, signal.service, signal.deployment_id or "", signal.commit_sha or ""] if part)

    def _cluster_text(self, cluster: Dict[str, Any]) -> str:
        parts = [
            cluster.get("signature"),
            cluster.get("root_cause"),
            cluster.get("sample_message"),
            cluster.get("summary"),
            " ".join(cluster.get("affected_services", []) or []),
            " ".join(cluster.get("deployment_ids", []) or []),
            " ".join(cluster.get("commit_shas", []) or []),
            " ".join(cluster.get("changed_files", []) or []),
        ]
        return normalize_text(" ".join(str(part) for part in parts if part))

    def _affected_services(self, cluster: Dict[str, Any]) -> List[str]:
        services = []
        for key in ("affected_services", "services", "service_paths", "topology_affected"):
            value = cluster.get(key) or []
            for item in value:
                if isinstance(item, list):
                    services.extend(str(step) for step in item if step)
                elif item:
                    services.append(str(item))
        if cluster.get("service"):
            services.append(str(cluster.get("service")))
        return list(dict.fromkeys([service for service in services if service and service != "unknown"]))

    def _blast_radius(self, cluster: Dict[str, Any]) -> int:
        if isinstance(cluster.get("blast_radius"), int):
            return max(0, cluster["blast_radius"])
        services = self._affected_services(cluster)
        orgs = cluster.get("affected_orgs") or []
        count = int(cluster.get("error_count", 1) or 1)
        return min(10, max(1, len(services) + len(orgs) + (2 if count >= 10 else 1 if count >= 3 else 0)))


__all__ = ["RootCauseEngine", "RootCauseHypothesis"]