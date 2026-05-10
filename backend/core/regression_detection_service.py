from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from core.embeddings_cache import get_embedder
from core.normalization import normalize_text
from memory.operational_fingerprint import OperationalFingerprint, OperationalFingerprintEngine

logger = logging.getLogger(__name__)


@dataclass
class RegressionCandidate:
    incident_id: str
    cluster_id: str
    title: str
    service: str
    fingerprint: Optional[str] = None
    stack_signature: Optional[str] = None
    semantic_similarity: float = 0.0
    fingerprint_similarity: float = 0.0
    service_overlap: float = 0.0
    deployment_overlap: float = 0.0
    temporal_proximity: float = 0.0
    confidence_score: float = 0.0
    reason: str = ""
    affected_services: List[str] = field(default_factory=list)
    matched_deployment_ids: List[str] = field(default_factory=list)
    is_reopened: bool = False


@dataclass
class RegressionResult:
    is_regression: bool = False
    regression_confidence: float = 0.0
    confidence_score: float = 0.0
    linked_historical_incidents: List[RegressionCandidate] = field(default_factory=list)
    reasoning: str = ""
    regression_type: str = ""  # recurring_bug, reopened_incident, recurring_deployment
    affected_services: List[str] = field(default_factory=list)
    semantic_similarity: float = 0.0
    fingerprint_similarity: float = 0.0
    service_overlap_score: float = 0.0
    deployment_overlap_score: float = 0.0
    temporal_proximity_score: float = 0.0

    @property
    def linked_incidents(self) -> List[RegressionCandidate]:
        return self.linked_historical_incidents


class RegressionDetectionService:
    """Detect regressions from incident history."""

    def __init__(
        self,
        lookback_days: int = 90,
        min_similarity_threshold: float = 0.45,
        embedding_model: str = "all-MiniLM-L6-v2",
        embedder: Optional[Any] = None,
    ):
        self.lookback_days = lookback_days
        self.min_similarity_threshold = min_similarity_threshold
        self._embedder = embedder if embedder is not None else get_embedder(embedding_model)
        self._fingerprints = OperationalFingerprintEngine()

    def detect_regression(
        self,
        current_incident: Any,
        historical_incidents: Sequence[Any],
        recent_deployments: Optional[Sequence[Any]] = None,
    ) -> RegressionResult:
        current_data = self._as_dict(current_incident)
        current_ts = self._incident_timestamp(current_data)
        if current_ts is None:
            return RegressionResult(reasoning="current incident timestamp missing")

        current_fp = self._fingerprint(current_data)
        current_text = self._incident_text(current_data)
        current_embedding = self._encode_text(current_text)
        current_services = self._incident_services(current_data)

        candidates: List[RegressionCandidate] = []
        for historical in historical_incidents:
            hist_data = self._as_dict(historical)
            hist_ts = self._incident_timestamp(hist_data)
            if hist_ts is None:
                continue
            if (current_ts - hist_ts).days > self.lookback_days:
                continue

            candidate = self._score_historical_incident(
                current_data=current_data,
                historical_data=hist_data,
                current_ts=current_ts,
                historical_ts=hist_ts,
                current_fingerprint=current_fp,
                current_embedding=current_embedding,
                current_services=current_services,
                recent_deployments=recent_deployments or [],
            )
            if candidate.confidence_score >= self.min_similarity_threshold:
                candidates.append(candidate)

        if not candidates:
            return RegressionResult(reasoning="no similar historical incidents found")

        candidates.sort(key=lambda item: item.confidence_score, reverse=True)
        top_candidates = candidates[:5]
        confidence = self._overall_confidence(top_candidates)
        regression_type = self._determine_regression_type(top_candidates)
        affected_services = self._merge_services(current_services, *(candidate.affected_services for candidate in top_candidates))

        reasoning = self._build_reasoning(top_candidates, confidence)
        top_candidate = top_candidates[0]

        return RegressionResult(
            is_regression=confidence >= 0.55,
            regression_confidence=confidence,
            confidence_score=confidence,
            linked_historical_incidents=top_candidates,
            reasoning=reasoning,
            regression_type=regression_type,
            affected_services=affected_services,
            semantic_similarity=top_candidate.semantic_similarity,
            fingerprint_similarity=top_candidate.fingerprint_similarity,
            service_overlap_score=top_candidate.service_overlap,
            deployment_overlap_score=top_candidate.deployment_overlap,
            temporal_proximity_score=top_candidate.temporal_proximity,
        )

    def analyze_regression(
        self,
        current_incident: Any,
        historical_incidents: Sequence[Any],
        recent_deployments: Optional[Sequence[Any]] = None,
    ) -> RegressionResult:
        return self.detect_regression(current_incident, historical_incidents, recent_deployments)

    def _score_historical_incident(
        self,
        current_data: Dict[str, Any],
        historical_data: Dict[str, Any],
        current_ts: datetime,
        historical_ts: datetime,
        current_fingerprint: OperationalFingerprint,
        current_embedding: Optional[List[float]],
        current_services: Sequence[str],
        recent_deployments: Sequence[Any],
    ) -> RegressionCandidate:
        historical_text = self._incident_text(historical_data)
        historical_embedding = self._encode_text(historical_text)
        historical_fingerprint = self._fingerprint(historical_data)
        historical_services = self._incident_services(historical_data)

        semantic_similarity = self._embedding_similarity_or_text(
            self._incident_text(current_data),
            historical_text,
            current_embedding,
            historical_embedding,
        )
        fingerprint_similarity = self._fingerprint_similarity(current_fingerprint, historical_fingerprint)
        service_overlap = self._service_overlap(current_services, historical_services)
        temporal_proximity = self._temporal_proximity_score(current_ts, historical_ts)
        deployment_overlap, matched_deployments = self._deployment_overlap(
            current_data=current_data,
            historical_data=historical_data,
            current_ts=current_ts,
            historical_ts=historical_ts,
            recent_deployments=recent_deployments,
        )

        reopened_bonus = 0.0
        if self._is_reopened(current_data, historical_data, fingerprint_similarity, temporal_proximity):
            reopened_bonus = 0.12

        confidence = self._clamp(
            (semantic_similarity * 0.30)
            + (fingerprint_similarity * 0.30)
            + (service_overlap * 0.15)
            + (deployment_overlap * 0.15)
            + (temporal_proximity * 0.10)
            + reopened_bonus,
        )

        reason_parts = []
        if semantic_similarity >= 0.6:
            reason_parts.append("semantic")
        if fingerprint_similarity >= 0.6:
            reason_parts.append("fingerprint")
        if service_overlap >= 0.5:
            reason_parts.append("services")
        if deployment_overlap >= 0.6:
            reason_parts.append("deployment")
        if temporal_proximity >= 0.5:
            reason_parts.append("temporal")
        if reopened_bonus > 0:
            reason_parts.append("reopened")

        return RegressionCandidate(
            incident_id=str(historical_data.get("id") or historical_data.get("incident_id") or ""),
            cluster_id=str(historical_data.get("cluster_id") or ""),
            title=historical_data.get("title") or historical_data.get("summary") or historical_data.get("message") or "Unknown",
            service=self._primary_service(historical_data),
            fingerprint=historical_fingerprint.normalized_signature,
            stack_signature=historical_fingerprint.normalized_signature,
            semantic_similarity=semantic_similarity,
            fingerprint_similarity=fingerprint_similarity,
            service_overlap=service_overlap,
            deployment_overlap=deployment_overlap,
            temporal_proximity=temporal_proximity,
            confidence_score=confidence,
            reason="matched: " + (", ".join(reason_parts) if reason_parts else "low similarity"),
            affected_services=historical_services,
            matched_deployment_ids=matched_deployments,
            is_reopened=reopened_bonus > 0,
        )

    def _overall_confidence(self, candidates: Sequence[RegressionCandidate]) -> float:
        if not candidates:
            return 0.0

        top = candidates[0].confidence_score
        support = sum(candidate.confidence_score for candidate in candidates[1:]) / max(len(candidates) - 1, 1)
        multiplicity_boost = min(0.12, max(0, len(candidates) - 1) * 0.04)
        return self._clamp(top * 0.8 + support * 0.2 + multiplicity_boost)

    def _determine_regression_type(self, candidates: Sequence[RegressionCandidate]) -> str:
        if not candidates:
            return ""

        top = candidates[0]
        if top.deployment_overlap >= 0.75:
            return "recurring_deployment"
        if top.is_reopened:
            return "reopened_incident"
        return "recurring_bug"

    def _build_reasoning(self, candidates: Sequence[RegressionCandidate], confidence: float) -> str:
        top = candidates[0]
        bits = [f"top_match={top.incident_id or 'unknown'}", f"confidence={confidence:.2f}"]
        if top.reason:
            bits.append(top.reason)
        if len(candidates) > 1:
            bits.append(f"linked={len(candidates)}")
        return "; ".join(bits)

    def _is_reopened(
        self,
        current: Dict[str, Any],
        historical: Dict[str, Any],
        fingerprint_similarity: float,
        temporal_proximity: float,
    ) -> bool:
        current_status = str(current.get("status") or current.get("state") or "").lower()
        historical_status = str(historical.get("status") or historical.get("state") or "").lower()
        if current_status == "reopened" or historical_status == "reopened":
            return fingerprint_similarity >= 0.7 and temporal_proximity >= 0.3
        return False

    def _deployment_overlap(
        self,
        current_data: Dict[str, Any],
        historical_data: Dict[str, Any],
        current_ts: datetime,
        historical_ts: datetime,
        recent_deployments: Sequence[Any],
    ) -> Tuple[float, List[str]]:
        current_deployments = self._deployment_records(current_data)
        historical_deployments = self._deployment_records(historical_data)
        recent_records = [self._as_dict(item) for item in recent_deployments]
        matched_ids: List[str] = []

        all_deployments = current_deployments + historical_deployments + recent_records
        if not all_deployments:
            return 0.0, matched_ids

        current_keys = self._deployment_keys(current_deployments)
        historical_keys = self._deployment_keys(historical_deployments)

        for record in all_deployments:
            record_keys = self._deployment_keys([record])
            if current_keys & record_keys and historical_keys & record_keys:
                matched_ids.extend(self._record_identifier(record))
                return 1.0, self._unique(matched_ids)

        if current_keys & historical_keys:
            for item in current_deployments:
                if self._deployment_keys([item]) & historical_keys:
                    matched_ids.extend(self._record_identifier(item))
            return 0.9, self._unique(matched_ids)

        for record in recent_records:
            record_ts = self._incident_timestamp(record)
            if record_ts is None:
                continue
            delta_current = abs((current_ts - record_ts).total_seconds()) / 3600.0
            delta_hist = abs((historical_ts - record_ts).total_seconds()) / 3600.0
            if delta_current <= 24 and delta_hist <= 24:
                if self._incident_services(record) and set(self._incident_services(record)).intersection(self._incident_services(current_data)):
                    matched_ids.extend(self._record_identifier(record))
                    return 0.75, self._unique(matched_ids)

        current_deployment_id = self._first_string(current_data, ["deployment_id", "deploymentId", "release_id", "release", "rollout_id"])
        historical_deployment_id = self._first_string(historical_data, ["deployment_id", "deploymentId", "release_id", "release", "rollout_id"])
        if current_deployment_id and historical_deployment_id and current_deployment_id == historical_deployment_id:
            return 1.0, [current_deployment_id]

        current_provider = self._first_string(current_data, ["provider", "deployment_provider", "deploy_provider"])
        historical_provider = self._first_string(historical_data, ["provider", "deployment_provider", "deploy_provider"])
        if current_provider and historical_provider and current_provider.lower() == historical_provider.lower():
            deployment_gap = abs((current_ts - historical_ts).total_seconds()) / 3600.0
            if deployment_gap <= 24:
                return 0.6, []

        return 0.0, []

    def _temporal_proximity_score(self, current_ts: datetime, historical_ts: datetime) -> float:
        delta_days = abs((current_ts - historical_ts).total_seconds()) / 86400.0
        if delta_days <= 1:
            return 1.0
        if delta_days <= 7:
            return 0.85
        if delta_days <= 30:
            return 0.65
        if delta_days <= self.lookback_days:
            return max(0.2, 1.0 - (delta_days / float(max(self.lookback_days, 1))))
        return 0.0

    def _fingerprint(self, incident: Dict[str, Any]) -> OperationalFingerprint:
        enriched = dict(incident)
        enriched.setdefault("sample_message", self._incident_text(incident))
        enriched.setdefault("stacktrace", incident.get("stack_trace") or incident.get("stacktrace") or incident.get("sample_message") or "")
        enriched.setdefault("error_signature", self._first_string(incident, ["error_signature", "fingerprint", "signature"]) or "")
        return self._fingerprints.fingerprint_incident(enriched)

    def _fingerprint_similarity(self, current: OperationalFingerprint, historical: OperationalFingerprint) -> float:
        comparison = self._fingerprints.compare(current, historical)
        return self._clamp(comparison.get("similarity", 0.0))

    def _incident_text(self, incident: Dict[str, Any]) -> str:
        parts = [
            incident.get("sample_message"),
            incident.get("stacktrace"),
            incident.get("stack_trace"),
            incident.get("message"),
            incident.get("summary"),
            incident.get("title"),
            incident.get("root_cause"),
            incident.get("reason"),
        ]
        return "\n".join(str(part) for part in parts if part)

    def _incident_timestamp(self, incident: Dict[str, Any]) -> Optional[datetime]:
        for key in ("created_at", "occurred_at", "timestamp", "first_seen", "updated_at"):
            parsed = self._parse_timestamp(incident.get(key))
            if parsed is not None:
                return parsed
        return None

    def _incident_services(self, incident: Dict[str, Any]) -> List[str]:
        services: List[str] = []
        for key in ("affected_services", "services", "service_paths", "topology_affected"):
            value = incident.get(key)
            if isinstance(value, list):
                for item in value:
                    if isinstance(item, str) and item:
                        services.append(item)
                    elif isinstance(item, dict):
                        name = item.get("service") or item.get("name") or item.get("component")
                        if name:
                            services.append(str(name))
        for key in ("service", "dominant_service", "owner", "component", "app", "project"):
            value = incident.get(key)
            if isinstance(value, str) and value:
                services.append(value)
        for key in ("propagation_chain", "propagation_path"):
            value = incident.get(key)
            if isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        name = item.get("service") or item.get("name") or item.get("component")
                        if name:
                            services.append(str(name))
                    elif isinstance(item, str) and item:
                        services.append(item)
            elif isinstance(value, str) and value:
                services.extend(re.findall(r"[A-Za-z0-9_.-]+", value))
        return self._unique([service for service in services if service])

    def _primary_service(self, incident: Dict[str, Any]) -> str:
        services = self._incident_services(incident)
        return services[0] if services else str(incident.get("service") or "unknown")

    def _service_overlap(self, left: Sequence[str], right: Sequence[str]) -> float:
        left_set = {service.lower() for service in left if service}
        right_set = {service.lower() for service in right if service}
        if not left_set or not right_set:
            return 0.0
        intersection = left_set.intersection(right_set)
        union = left_set.union(right_set)
        return len(intersection) / float(len(union)) if union else 0.0

    def _deployment_records(self, incident: Dict[str, Any]) -> List[Dict[str, Any]]:
        records: List[Dict[str, Any]] = []
        keys = (
            "deployment_id",
            "deploymentId",
            "release_id",
            "release",
            "rollout_id",
            "deployment_sha",
            "deployment_hash",
            "deployment_provider",
            "provider",
            "deployed_at",
            "deployment_time",
        )
        if any(key in incident for key in keys):
            records.append({key: incident.get(key) for key in keys if incident.get(key) is not None})
        for key in ("deployments", "recent_deployments"):
            value = incident.get(key)
            if isinstance(value, list):
                for item in value:
                    records.append(self._as_dict(item))
        return records

    def _deployment_keys(self, deployments: Sequence[Dict[str, Any]]) -> Set[str]:
        keys: Set[str] = set()
        for deployment in deployments:
            for key in ("deployment_id", "deploymentId", "release_id", "release", "rollout_id", "deployment_sha", "deployment_hash"):
                value = deployment.get(key)
                if isinstance(value, str) and value:
                    keys.add(value.lower())
            provider = deployment.get("provider") or deployment.get("deployment_provider")
            service = deployment.get("service") or deployment.get("app") or deployment.get("project")
            if isinstance(provider, str) and provider and isinstance(service, str) and service:
                keys.add(f"{provider.lower()}::{service.lower()}")
        return keys

    def _record_identifier(self, deployment: Dict[str, Any]) -> List[str]:
        values: List[str] = []
        for key in ("deployment_id", "deploymentId", "release_id", "release", "rollout_id", "deployment_sha", "deployment_hash"):
            value = deployment.get(key)
            if isinstance(value, str) and value:
                values.append(value)
        return values

    def _encode_text(self, text: str) -> Optional[List[float]]:
        if not text or self._embedder is None:
            return None
        try:
            encoded = self._embedder.encode([text], normalize_embeddings=True)
            vector = encoded[0] if hasattr(encoded, "__getitem__") else encoded
            return [float(value) for value in vector]
        except Exception:
            logger.debug("Embedding encode failed; falling back to lexical similarity", exc_info=True)
            return None

    def _embedding_similarity(self, left: Optional[List[float]], right: Optional[List[float]]) -> float:
        if not left or not right:
            return 0.0
        length = min(len(left), len(right))
        if length == 0:
            return 0.0
        left_vec = left[:length]
        right_vec = right[:length]
        dot = sum(a * b for a, b in zip(left_vec, right_vec))
        left_norm = math.sqrt(sum(value * value for value in left_vec))
        right_norm = math.sqrt(sum(value * value for value in right_vec))
        if left_norm == 0.0 or right_norm == 0.0:
            return 0.0
        return self._clamp(dot / (left_norm * right_norm))

    def _embedding_similarity_or_text(self, left_text: str, right_text: str, left: Optional[List[float]], right: Optional[List[float]]) -> float:
        similarity = self._embedding_similarity(left, right)
        if similarity > 0.0:
            return similarity
        return self._text_similarity(left_text, right_text)

    def _text_similarity(self, text1: str, text2: str) -> float:
        left_tokens = set(re.findall(r"[a-z0-9_]+", normalize_text(text1).lower()))
        right_tokens = set(re.findall(r"[a-z0-9_]+", normalize_text(text2).lower()))
        if not left_tokens or not right_tokens:
            return 0.0
        return len(left_tokens.intersection(right_tokens)) / float(len(left_tokens.union(right_tokens)))

    def _parse_timestamp(self, value: Any) -> Optional[datetime]:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        if not isinstance(value, str):
            return None
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except Exception:
            return None

    def _as_dict(self, value: Any) -> Dict[str, Any]:
        if isinstance(value, dict):
            return value
        if hasattr(value, "to_dict"):
            try:
                data = value.to_dict()
                if isinstance(data, dict):
                    return data
            except Exception:
                pass
        data: Dict[str, Any] = {}
        for key in (
            "id",
            "incident_id",
            "cluster_id",
            "title",
            "summary",
            "service",
            "affected_services",
            "services",
            "stack_trace",
            "stacktrace",
            "sample_message",
            "message",
            "reason",
            "fingerprint",
            "error_signature",
            "deployment_id",
            "deployment_time",
            "provider",
            "status",
            "state",
            "created_at",
            "occurred_at",
            "timestamp",
            "first_seen",
            "updated_at",
            "deployments",
            "recent_deployments",
            "propagation_chain",
            "propagation_path",
            "root_cause",
        ):
            if hasattr(value, key):
                data[key] = getattr(value, key)
        return data

    def _first_string(self, data: Dict[str, Any], keys: Sequence[str]) -> Optional[str]:
        for key in keys:
            value = data.get(key)
            if isinstance(value, str) and value:
                return value
        return None

    def _unique(self, values: Iterable[str]) -> List[str]:
        seen: Set[str] = set()
        unique: List[str] = []
        for value in values:
            if value not in seen:
                seen.add(value)
                unique.append(value)
        return unique

    def _merge_services(self, *groups: Sequence[str]) -> List[str]:
        merged: List[str] = []
        for group in groups:
            merged.extend(group)
        return self._unique([service for service in merged if service])

    def _clamp(self, value: float) -> float:
        return max(0.0, min(1.0, float(value)))