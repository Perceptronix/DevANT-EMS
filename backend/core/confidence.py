from __future__ import annotations

from collections import Counter
from typing import Any, Dict, Iterable, List, Optional


def clamp_confidence(value: float, minimum: float = 0.0, maximum: float = 0.999) -> float:
    return max(minimum, min(maximum, float(value)))


def _most_common_source_fraction(evidences: Optional[Iterable[Dict[str, Any]]]) -> float:
    if not evidences:
        return 0.0
    sources = []
    for e in evidences:
        s = e.get("source") or e.get("module") or e.get("service") or e.get("title")
        if s:
            sources.append(str(s))
    if not sources:
        return 0.0
    counts = Counter(sources)
    top = counts.most_common(1)[0][1]
    return top / float(len(sources))


def derive_evidence_confidence(
    top_score: float,
    deployment_correlated: bool = False,
    ownership: bool = False,
    rollback: bool = False,
    anomalies: bool = False,
    evidences: Optional[List[Dict[str, Any]]] = None,
    correlation: Optional[Dict[str, Any]] = None,
    history: Optional[List[Dict[str, Any]]] = None,
    propagation_consistency: Optional[float] = None,
    regression_similarity: Optional[float] = None,
    retrieval_overlap: Optional[float] = None,
    trace_correlation: Optional[float] = None,
    topology_consistency: Optional[float] = None,
) -> float:
    """Calibrated evidence confidence.

    The function aggregates multiple, independently measurable signals into a
    calibrated confidence score in [0, 0.999). It intentionally avoids
    using LLM wording/semantic-similarity alone as a source of truth.

    Inputs are best-effort; missing signals are simply ignored and weights
    renormalized so callers can incrementally provide better telemetry.
    """

    # Normalize primary signals to [0,1]
    top = max(0.0, min(1.0, float(top_score or 0.0)))

    # Deployment correlation score (0-1) if available in correlation dict
    dep_score = 0.0
    if correlation:
        try:
            dep_score = float(correlation.get("score", 0.0))
            if not correlation.get("matched"):
                dep_score = 0.0
        except Exception:
            dep_score = 0.0

    # Propagation consistency: prefer explicit value, else derive weakly from dep_score
    prop_score = None
    if propagation_consistency is not None:
        prop_score = max(0.0, min(1.0, float(propagation_consistency)))
    elif dep_score > 0:
        prop_score = min(1.0, dep_score * 0.8)

    # Regression similarity - how well past incidents match this one
    reg_score = None
    if regression_similarity is not None:
        reg_score = max(0.0, min(1.0, float(regression_similarity)))
    elif history:
        # simple heuristic: presence of historical matches gives weak signal
        reg_score = min(0.6, min(1.0, len(history) / 5.0))

    # Retrieval overlap: either provided, or estimate from evidence sources
    if retrieval_overlap is None:
        retrieval_overlap = _most_common_source_fraction(evidences)

    # Trace and topology signals: optional floats 0-1
    trace_score = None
    if trace_correlation is not None:
        trace_score = max(0.0, min(1.0, float(trace_correlation)))
    topo_score = None
    if topology_consistency is not None:
        topo_score = max(0.0, min(1.0, float(topology_consistency)))

    # Simple anomaly / ownership / rollback as binary signals
    anomalies_score = 1.0 if anomalies else 0.0
    ownership_score = 1.0 if ownership else 0.0
    rollback_score = 1.0 if rollback else 0.0

    # Define component weights (these will be renormalized based on availability)
    components = {}
    components["top"] = (top, 0.30)
    components["deployment"] = (dep_score, 0.25)
    if prop_score is not None:
        components["propagation"] = (prop_score, 0.15)
    components["anomalies"] = (anomalies_score, 0.06)
    components["retrieval_overlap"] = (float(retrieval_overlap or 0.0), 0.05)
    if reg_score is not None:
        components["regression"] = (reg_score, 0.05)
    if trace_score is not None:
        components["trace"] = (trace_score, 0.06)
    if topo_score is not None:
        components["topology"] = (topo_score, 0.06)
    components["ownership"] = (ownership_score, 0.02)
    components["rollback"] = (rollback_score, 0.0)  # rollback suggests but is weak alone

    # Compute weighted average over available components
    weighted_sum = 0.0
    weight_total = 0.0
    for v, w in components.values():
        # v may be None for some optional components; skip if None
        if v is None:
            continue
        weighted_sum += float(v) * float(w)
        weight_total += float(w)

    if weight_total <= 0:
        return clamp_confidence(0.0)

    raw = weighted_sum / weight_total

    # Small penalties / adjustments to avoid overconfidence when signals conflict
    # If retrieval overlap is very low (diverse sources) but top score is also low,
    # reduce confidence further.
    if retrieval_overlap is not None and retrieval_overlap < 0.4 and top < 0.5:
        raw *= 0.7

    # If deployment correlation absent but propagation and traces both strong,
    # boost slightly (we can infer propagation without explicit deploy metadata).
    if dep_score == 0 and prop_score is not None and prop_score > 0.7 and trace_score and trace_score > 0.6:
        raw = min(1.0, raw + 0.08)

    return clamp_confidence(raw)


__all__ = ["derive_evidence_confidence", "clamp_confidence"]