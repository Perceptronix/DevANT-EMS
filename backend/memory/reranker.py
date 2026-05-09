from typing import List, Dict, Any
from .retrieval import stacktrace_score


class RetrievalReranker:
    """Rerank retrieved evidence items according to operational relevance."""

    def __init__(self, weights: Dict[str, float] = None):
        # Default weights if not provided will be applied in HybridRetriever
        self.weights = weights or {}

    def rerank(self, evidences: List[Dict[str, Any]], incident: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Apply additional reranking heuristics and return sorted list."""
        for e in evidences:
            # boost for exact stacktrace overlap
            st_score = 0.0
            if incident.get("stack_trace") and e.get("stack_trace"):
                st_score = stacktrace_score(incident.get("stack_trace"), e.get("stack_trace"))

            # deployment proximity bonus
            dep_bonus = 0.1 if e.get("deployment_correlation") else 0.0

            # historical match bonus
            hist_bonus = 0.1 if e.get("historical") else 0.0

            base = e.get("base_score", 0.0)
            # combine with fixed heuristics
            final = base + (st_score * 0.3) + dep_bonus + hist_bonus
            e["final_score"] = final

        return sorted(evidences, key=lambda x: x.get("final_score", 0), reverse=True)
