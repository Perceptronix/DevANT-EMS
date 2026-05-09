from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List

from core.normalization import normalize_timestamp, normalize_text

from .operational_signal import OperationalSignal, SignalType


def _classify_signal_type(payload: Dict[str, Any]) -> SignalType:
    event_type = normalize_text(payload.get("event_type") or payload.get("type") or payload.get("kind"))
    message = normalize_text(payload.get("message") or payload.get("summary") or payload.get("title"))
    stacktrace = normalize_text(payload.get("stack_trace") or payload.get("stacktrace"))
    text = " ".join(part for part in (event_type, message, stacktrace) if part)

    if any(token in text for token in ("rollback", "rolled back")):
        return SignalType.rollback_detected
    if any(token in text for token in ("hotfix", "patch release")):
        return SignalType.hotfix_detected
    if any(token in text for token in ("workflow timeout", "timed out", "deadline exceeded")):
        return SignalType.workflow_timeout
    if any(token in text for token in ("build failed", "compilation failed", "ci failed")):
        return SignalType.build_failed
    if any(token in text for token in ("deployment failed", "release failed", "rollout failed")):
        return SignalType.deployment_failed
    if any(token in text for token in ("dependency break", "dependency update", "package upgrade", "lockfile")):
        return SignalType.dependency_break
    if any(token in text for token in ("recurring", "regression", "reopened")):
        return SignalType.recurring_incident
    return SignalType.runtime_error


def normalize_operational_signal(payload: Dict[str, Any], source: str = "unknown") -> OperationalSignal:
    timestamp = normalize_timestamp(payload.get("timestamp")) or datetime.now(timezone.utc)
    evidence = payload.get("evidence") or []
    if isinstance(evidence, dict):
        evidence = [evidence]

    return OperationalSignal(
        type=_classify_signal_type(payload),
        source=str(payload.get("source", source)),
        timestamp=timestamp,
        repo=str(payload.get("repo") or payload.get("repository") or "unknown"),
        service=str(payload.get("service") or payload.get("component") or payload.get("container") or "unknown"),
        severity=str(payload.get("severity") or payload.get("impact") or "informational"),
        deployment_id=payload.get("deployment_id") or payload.get("release_id"),
        commit_sha=payload.get("commit_sha") or payload.get("commit") or payload.get("sha"),
        evidence=[{"source": source, "payload": payload}] if not evidence else list(evidence),
        confidence=float(payload.get("confidence", 0.5)),
    )


class OperationalSignalNormalizer:
    """Normalize connector payloads into shared operational signals."""

    def normalize(self, payloads: Iterable[Dict[str, Any]], source: str = "unknown") -> List[OperationalSignal]:
        return [normalize_operational_signal(payload, source=source) for payload in payloads]