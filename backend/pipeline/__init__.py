"""
Error monitoring pipeline components.

The pipeline processes errors through these stages:
1. Clustering - Group similar errors together (multi-stage)
2. Enrichment - Add context from Airweave (code, tickets, docs)
3. Analysis - Determine severity and status
4. Matching - Find relevant tickets and mutes
5. Actions - Create tickets and send alerts
"""
from .clustering import ErrorClusterer
from .search import ContextSearcher
from .analysis import ErrorAnalyzer
from .actions import get_action_executor
# from .enrichment import ErrorEnricher, get_enricher
# from .semantic_matcher import SemanticMatcher, get_semantic_matcher

__all__ = [
    "ErrorClusterer",
    "ContextSearcher",
    "ErrorAnalyzer",
    "get_action_executor",
    # "ErrorEnricher",
    # "get_enricher",
    # "SemanticMatcher",
    # "get_semantic_matcher",
    # "ActionExecutor",
]

# Backwards-compatibility: ensure ContextSearcher exposes an async `search` method
if not hasattr(ContextSearcher, "search"):
    async def _compat_search(self, query: str, limit: int = 5, **kwargs):
        # If configured, delegate to the client
        try:
            if getattr(self, "configured", False) and getattr(self, "client", None):
                results = await self.client.search(query=query, source_filter=kwargs.get("source_filter"), limit=limit)
                formatted = []
                for r in results:
                    formatted.append({
                        "content": r.get("content", ""),
                        "metadata": r.get("metadata", {}),
                        "score": r.get("score", 0),
                    })
                return formatted
        except Exception:
            return []

        # Fallback to mock search
        try:
            cluster = {"signature": query, "modules": []}
            context = self._mock_search(cluster)
            out = []
            for src in ("code_snippets", "related_tickets", "documentation"):
                for item in context.get(src, []):
                    out.append({
                        "content": item.get("content"),
                        "metadata": {"title": item.get("title"), "url": item.get("url")},
                        "score": item.get("score", 0),
                    })
            return out
        except Exception:
            return []

    setattr(ContextSearcher, "search", _compat_search)
