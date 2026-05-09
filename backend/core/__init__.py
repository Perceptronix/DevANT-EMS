"""Shared operational core helpers."""

from .causality import correlate_deployment_events
from .confidence import derive_evidence_confidence, clamp_confidence
from .identity import incident_identity, deployment_identity, same_incident
from .normalization import normalize_signature, normalize_text, normalize_timestamp
from .scoring import (
    combine_evidence_score,
    assess_operational_severity,
    infer_severity,
    severity_priority,
    severity_emoji,
)

__all__ = [
    "correlate_deployment_events",
    "derive_evidence_confidence",
    "clamp_confidence",
    "incident_identity",
    "deployment_identity",
    "same_incident",
    "normalize_signature",
    "normalize_text",
    "normalize_timestamp",
    "combine_evidence_score",
    "assess_operational_severity",
    "infer_severity",
    "severity_priority",
    "severity_emoji",
]