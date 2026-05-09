"""Canonical intelligence namespace."""

from core.root_cause_clusterer import RootCauseClusterer, ErrorCluster
from core.context_enricher import ContextEnricher, EnrichedCluster
from core.scoring import combine_evidence_score, infer_severity, severity_priority, severity_emoji, assess_operational_severity
from core.confidence import clamp_confidence, derive_evidence_confidence
from core.causality import correlate_deployment_events
from intelligence.root_cause_engine import RootCauseEngine, RootCauseHypothesis

__all__ = [
    "RootCauseClusterer",
    "ErrorCluster",
    "ContextEnricher",
    "EnrichedCluster",
    "combine_evidence_score",
    "infer_severity",
    "severity_priority",
    "severity_emoji",
    "assess_operational_severity",
    "clamp_confidence",
    "derive_evidence_confidence",
    "correlate_deployment_events",
    "RootCauseEngine",
    "RootCauseHypothesis",
]
