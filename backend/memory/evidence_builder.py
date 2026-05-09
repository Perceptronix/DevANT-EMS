from typing import List, Dict, Any

from core.confidence import derive_evidence_confidence


class EvidenceBuilder:
    """Assemble retrieved pieces into a grounded evidence bundle."""

    def __init__(self):
        pass

    def build(
        self,
        evidences: List[Dict[str, Any]],
        correlation: Dict[str, Any],
        incident: Dict[str, Any],
        history: List[Dict[str, Any]] = None,
        deployments: List[Dict[str, Any]] = None,
        ownership: List[str] = None,
        rollback_candidates: List[Dict[str, Any]] = None,
        metrics_anomalies: List[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Return a structured evidence bundle for LLM reasoning.

        The returned dict aggregates:
        - evidences: list of evidence items with source and score
        - deployment events: recent deployments near incident
        - ownership: list of service owners
        - rollback_candidates: suggested rollbacks
        - metrics_anomalies: anomalies detected for the incident
        - deployment_correlation: correlation dict
        - incident: original incident summary
        - metadata: counts and confidence estimate
        """
        evidence_count = len(evidences)
        deployment_corr = bool(correlation.get("matched"))
        top_score = max((e.get("final_score", 0) for e in evidences), default=0)

        confidence = derive_evidence_confidence(
            top_score=top_score,
            deployment_correlated=deployment_corr,
            ownership=bool(ownership),
            rollback=bool(rollback_candidates),
            anomalies=bool(metrics_anomalies),
            evidences=evidences,
            correlation=correlation,
            history=history,
            retrieval_overlap=None,
        )

        bundle = {
            "evidences": evidences,
            "history": history or [],
            "deployment_events": deployments or [],
            "ownership": ownership or [],
            "rollback_candidates": rollback_candidates or [],
            "metrics_anomalies": metrics_anomalies or [],
            "deployment_correlation": correlation,
            "incident": incident,
            "metadata": {
                "confidence": confidence,
                "evidence_count": evidence_count,
                "deployment_correlated": deployment_corr,
                "confidence_origin": "core.confidence.derive_evidence_confidence",
            }
        }

        return bundle

    def build_bundle(
        self,
        errors: List[Dict[str, Any]],
        clusters: List[Dict[str, Any]],
        search_results: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Compatibility wrapper used by the older pipeline tests."""
        evidence_items = []

        for error in errors:
            evidence_items.append({
                "error_id": error.get("id") or error.get("error_id"),
                "source": error.get("source") or error.get("source_type", "unknown"),
                "title": error.get("message", "Unknown error")[:120],
                "content": error.get("message", ""),
                "module": error.get("module"),
                "timestamp": error.get("timestamp"),
            })

        for result in search_results:
            evidence_items.append({
                "source": result.get("source") or result.get("metadata", {}).get("source", "search"),
                "title": result.get("title") or result.get("metadata", {}).get("title", "Search result"),
                "content": result.get("content", ""),
                "url": result.get("url") or result.get("metadata", {}).get("url"),
            })

        summary = {
            "error_count": len(errors),
            "cluster_count": len(clusters),
            "search_result_count": len(search_results),
        }

        return {
            "evidence_items": evidence_items,
            "summary": summary,
        }
