from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from core.normalization import normalize_text


CACHE_FAILURE = "CACHE_FAILURE"
NETWORK_TIMEOUT = "NETWORK_TIMEOUT"
DB_SATURATION = "DB_SATURATION"
QUEUE_BACKPRESSURE = "QUEUE_BACKPRESSURE"
RATE_LIMITING = "RATE_LIMITING"
AUTH_FAILURE = "AUTH_FAILURE"
DEPENDENCY_UNAVAILABLE = "DEPENDENCY_UNAVAILABLE"
RESOURCE_EXHAUSTION = "RESOURCE_EXHAUSTION"
DEPLOYMENT_REGRESSION = "DEPLOYMENT_REGRESSION"

FAILURE_CLASSES = {
    CACHE_FAILURE,
    NETWORK_TIMEOUT,
    DB_SATURATION,
    QUEUE_BACKPRESSURE,
    RATE_LIMITING,
    AUTH_FAILURE,
    DEPENDENCY_UNAVAILABLE,
    RESOURCE_EXHAUSTION,
    DEPLOYMENT_REGRESSION,
}


@dataclass(frozen=True)
class OperationalFingerprint:
    canonical_failure_class: str
    infrastructure_layer: str
    dependency_type: str
    propagation_pattern: str
    normalized_signature: str


class OperationalFingerprintEngine:
    """Normalize incidents into operational signatures that survive wording drift."""

    REDACTIONS = (
        re.compile(r"\brequest[_-]?id\s*[:=]\s*\S+", re.IGNORECASE),
        re.compile(r"\btrace[_-]?id\s*[:=]\s*\S+", re.IGNORECASE),
        re.compile(r"\bcorrelation[_-]?id\s*[:=]\s*\S+", re.IGNORECASE),
        re.compile(r"\bsession[_-]?id\s*[:=]\s*\S+", re.IGNORECASE),
        re.compile(r"\buuid\b[:=\s]*[0-9a-fA-F-]{8,}", re.IGNORECASE),
        re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.IGNORECASE),
        re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"),
        re.compile(r"\b(?:0x)?[0-9a-f]{8,}\b", re.IGNORECASE),
        re.compile(r"\bline\s+\d+\b", re.IGNORECASE),
        re.compile(r"(?<=[:@])\d{2,5}\b"),
        re.compile(r"\b(?:deployment|commit|release|rollout|build)[-_]?[0-9a-f]{6,}\b", re.IGNORECASE),
        re.compile(r"\b\d{4}-\d{2}-\d{2}[T\s]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?\b", re.IGNORECASE),
        re.compile(r"\b\d{1,2}:\d{2}:\d{2}(?:\.\d+)?\b"),
    )

    FAILURE_RULES: Sequence[Tuple[str, Sequence[str], Sequence[str]]] = (
        (AUTH_FAILURE, ("unauthorized", "forbidden", "auth failed", "invalid token", "permission denied", "401", "403"), ("auth", "token", "credential", "login", "permission")),
        (RATE_LIMITING, ("rate limit", "too many requests", "throttle", "throttled", "429"), ("rate", "limit", "throttle", "quota")),
        (DEPLOYMENT_REGRESSION, ("deployment", "deploy", "rollout", "canary", "rollback", "release"), ("regression", "introduced", "after deploy", "post-deploy")),
        (RESOURCE_EXHAUSTION, ("out of memory", "oom", "no space left", "resource exhausted", "file descriptors", "cpu saturation"), ("exhausted", "saturation", "out of memory", "oom")),
        (QUEUE_BACKPRESSURE, ("queue full", "backpressure", "queue saturation", "consumer lag", "enqueue failed"), ("queue", "backpressure", "consumer", "buffer")),
        (DB_SATURATION, ("too many connections", "connection pool", "pool exhaustion", "database overloaded", "db saturation"), ("database", "db", "postgres", "mysql", "sql", "pool")),
        (CACHE_FAILURE, ("cache", "redis", "memcached", "cache backend", "cache service"), ("cache", "redis", "memcached")),
        (NETWORK_TIMEOUT, ("timeout", "timed out", "deadline exceeded", "connection reset by peer", "socket timeout"), ("timeout", "deadline", "reset by peer", "socket")),
        (DEPENDENCY_UNAVAILABLE, ("unavailable", "unreachable", "connection refused", "cannot connect", "service down", "offline"), ("dependency", "service", "backend", "upstream", "downstream", "unreachable")),
    )

    def fingerprint_incident(self, incident: Dict[str, Any]) -> OperationalFingerprint:
        text = self._incident_text(incident)
        normalized_text = self._normalize_operational_text(text)
        tokens = self._semantic_tokens(normalized_text, incident)

        failure_class = self._infer_failure_class(tokens, normalized_text, incident)
        infrastructure_layer = self._infer_infrastructure_layer(tokens, failure_class)
        dependency_type = self._infer_dependency_type(tokens, failure_class)
        propagation_pattern = self._infer_propagation_pattern(tokens, incident, failure_class)

        normalized_signature = self._build_signature(
            failure_class=failure_class,
            infrastructure_layer=infrastructure_layer,
            dependency_type=dependency_type,
            propagation_pattern=propagation_pattern,
            tokens=tokens,
        )

        return OperationalFingerprint(
            canonical_failure_class=failure_class,
            infrastructure_layer=infrastructure_layer,
            dependency_type=dependency_type,
            propagation_pattern=propagation_pattern,
            normalized_signature=normalized_signature,
        )

    def compare(self, left: OperationalFingerprint, right: OperationalFingerprint) -> Dict[str, Any]:
        left_tokens = self._signature_tokens(left.normalized_signature)
        right_tokens = self._signature_tokens(right.normalized_signature)
        token_similarity = self._jaccard(left_tokens, right_tokens)

        class_overlap = 1.0 if left.canonical_failure_class == right.canonical_failure_class else 0.0
        layer_overlap = 1.0 if left.infrastructure_layer == right.infrastructure_layer else 0.0
        dependency_overlap = 1.0 if left.dependency_type == right.dependency_type else 0.0
        propagation_overlap = 1.0 if left.propagation_pattern == right.propagation_pattern else 0.0

        taxonomy_overlap = self._taxonomy_overlap(left, right)
        similarity = (
            class_overlap * 0.30
            + taxonomy_overlap * 0.20
            + token_similarity * 0.20
            + layer_overlap * 0.10
            + dependency_overlap * 0.10
            + propagation_overlap * 0.10
        )

        return {
            "similarity": similarity,
            "taxonomy_overlap": taxonomy_overlap,
            "class_overlap": class_overlap,
            "layer_overlap": layer_overlap,
            "dependency_overlap": dependency_overlap,
            "propagation_overlap": propagation_overlap,
            "token_similarity": token_similarity,
        }

    def _incident_text(self, incident: Dict[str, Any]) -> str:
        parts = [
            incident.get("sample_message"),
            incident.get("stacktrace"),
            incident.get("error_signature"),
            incident.get("message"),
            incident.get("reason"),
        ]
        return "\n".join(str(part) for part in parts if part)

    def _normalize_operational_text(self, text: str) -> str:
        normalized = normalize_text(text)
        for pattern in self.REDACTIONS:
            normalized = pattern.sub(" [REDACTED] ", normalized)
        normalized = re.sub(r"\s+", " ", normalized).strip()
        return normalized

    def _semantic_tokens(self, normalized_text: str, incident: Dict[str, Any]) -> Set[str]:
        tokens = set(re.findall(r"[a-z0-9_]+", normalized_text.lower()))
        for key in ("service", "dependency", "component", "layer"):
            value = incident.get(key)
            if value:
                tokens.update(re.findall(r"[a-z0-9_]+", normalize_text(value)))
        metrics = incident.get("metrics_anomalies") or []
        for metric in metrics:
            metric_name = metric.get("metric_name") or metric.get("name")
            if metric_name:
                tokens.update(re.findall(r"[a-z0-9_]+", normalize_text(metric_name)))
        return {token for token in tokens if token and token != "redacted"}

    def _infer_failure_class(self, tokens: Set[str], normalized_text: str, incident: Dict[str, Any]) -> str:
        text = normalized_text.lower()
        for failure_class, phrases, keywords in self.FAILURE_RULES:
            if any(phrase in text for phrase in phrases) or any(keyword in tokens for keyword in keywords):
                return failure_class

        if any(word in tokens for word in ("retry", "retries", "backoff")) and any(word in tokens for word in ("timeout", "unavailable", "refused")):
            return NETWORK_TIMEOUT

        return DEPENDENCY_UNAVAILABLE if any(word in tokens for word in ("dependency", "service", "backend", "upstream", "downstream")) else "UNKNOWN"

    def _infer_infrastructure_layer(self, tokens: Set[str], failure_class: str) -> str:
        if failure_class in {CACHE_FAILURE, DB_SATURATION}:
            return "data"
        if failure_class in {QUEUE_BACKPRESSURE, RATE_LIMITING}:
            return "messaging"
        if failure_class in {AUTH_FAILURE}:
            return "identity"
        if failure_class in {RESOURCE_EXHAUSTION}:
            return "runtime"
        if failure_class in {DEPLOYMENT_REGRESSION}:
            return "platform"
        if any(word in tokens for word in ("redis", "memcached", "cache")):
            return "data"
        if any(word in tokens for word in ("queue", "backpressure", "broker")):
            return "messaging"
        if any(word in tokens for word in ("auth", "token", "login")):
            return "identity"
        if any(word in tokens for word in ("timeout", "socket", "network", "connection")):
            return "network"
        return "application"

    def _infer_dependency_type(self, tokens: Set[str], failure_class: str) -> str:
        if failure_class == CACHE_FAILURE or any(word in tokens for word in ("redis", "memcached", "cache")):
            return "cache"
        if failure_class == DB_SATURATION or any(word in tokens for word in ("database", "db", "postgres", "mysql", "sql")):
            return "database"
        if failure_class == QUEUE_BACKPRESSURE or any(word in tokens for word in ("queue", "broker", "consumer")):
            return "queue"
        if failure_class == RATE_LIMITING:
            return "external_api"
        if failure_class == AUTH_FAILURE:
            return "identity"
        if failure_class == DEPLOYMENT_REGRESSION:
            return "deployment"
        if any(word in tokens for word in ("timeout", "refused", "unavailable", "unreachable", "reset")):
            return "dependency"
        return "unknown"

    def _infer_propagation_pattern(self, tokens: Set[str], incident: Dict[str, Any], failure_class: str) -> str:
        propagation_chain = incident.get("propagation_chain") or incident.get("propagation_path") or []
        if propagation_chain:
            if len(propagation_chain) > 2:
                return "cascade"
            return "propagated"
        if any(word in tokens for word in ("retry", "backoff", "retries")):
            return "retry-loop"
        if any(word in tokens for word in ("saturation", "full", "exhausted", "backpressure")):
            return "backpressure"
        if failure_class == DEPLOYMENT_REGRESSION:
            return "post-deploy-regression"
        if failure_class in {CACHE_FAILURE, DEPENDENCY_UNAVAILABLE, NETWORK_TIMEOUT}:
            return "dependency-brownout"
        if failure_class == RESOURCE_EXHAUSTION:
            return "resource-collapse"
        return "direct-failure"

    def _build_signature(
        self,
        failure_class: str,
        infrastructure_layer: str,
        dependency_type: str,
        propagation_pattern: str,
        tokens: Iterable[str],
    ) -> str:
        salient = []
        for token in sorted(set(tokens)):
            if token in {"error", "exception", "traceback", "failed", "failure", "warning"}:
                continue
            if len(salient) >= 8:
                break
            salient.append(token)
        return "|".join([
            failure_class,
            infrastructure_layer,
            dependency_type,
            propagation_pattern,
            ",".join(salient),
        ])

    def _signature_tokens(self, signature: str) -> Set[str]:
        return {part for part in re.split(r"[|,]", signature.lower()) if part}

    def _taxonomy_overlap(self, left: OperationalFingerprint, right: OperationalFingerprint) -> float:
        score = 0.0
        if left.canonical_failure_class == right.canonical_failure_class:
            score += 0.5
        if left.infrastructure_layer == right.infrastructure_layer:
            score += 0.2
        if left.dependency_type == right.dependency_type:
            score += 0.15
        if left.propagation_pattern == right.propagation_pattern:
            score += 0.15
        return score

    def _jaccard(self, left: Set[str], right: Set[str]) -> float:
        if not left or not right:
            return 0.0
        intersection = left.intersection(right)
        union = left.union(right)
        return len(intersection) / len(union)


__all__ = [
    "OperationalFingerprint",
    "OperationalFingerprintEngine",
    "CACHE_FAILURE",
    "NETWORK_TIMEOUT",
    "DB_SATURATION",
    "QUEUE_BACKPRESSURE",
    "RATE_LIMITING",
    "AUTH_FAILURE",
    "DEPENDENCY_UNAVAILABLE",
    "RESOURCE_EXHAUSTION",
    "DEPLOYMENT_REGRESSION",
]