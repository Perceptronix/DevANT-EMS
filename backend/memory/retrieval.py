import re
from functools import lru_cache
from typing import List, Tuple, Optional

try:
    from ..contracts.retrieval import BaseRetriever
except Exception:
    # fallback path when executed as script from backend/
    try:
        from contracts.retrieval import BaseRetriever
    except Exception:
        BaseRetriever = None


@lru_cache(maxsize=1024)
def normalize_stacktrace(trace: str) -> str:
    """Normalize a stack trace for matching.

    - remove timestamps
    - remove line numbers
    - normalize hashes to <HASH>
    - preserve function and service names
    """
    if not trace:
        return ""

    # Remove timestamps like 2026-05-07T12:34:56 or 12:34:56.123
    trace = re.sub(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z?", "", trace)
    trace = re.sub(r"\d{1,2}:\d{2}:\d{2}(?:\.\d+)?", "", trace)

    # Normalize hex hashes (commit, object ids)
    trace = re.sub(r"0x[a-fA-F0-9]{6,}", "<HASH>", trace)
    trace = re.sub(r"\b[a-f0-9]{7,40}\b", "<HASH>", trace)

    # Remove file:line patterns
    trace = re.sub(r"[:@]\d+", "", trace)

    # Strip stray brackets and extra whitespace
    trace = re.sub(r"\s+", " ", trace).strip()

    return trace


def extract_function_tokens(normalized_trace: str) -> List[str]:
    """Extract probable function or symbol names from a normalized stack trace."""
    if not normalized_trace:
        return []
    # Simple heuristic: words that look like identifiers
    tokens = re.findall(r"[A-Za-z_][A-Za-z0-9_\.]+", normalized_trace)
    # Filter common words
    filtered = [t for t in tokens if len(t) > 2]
    return filtered


def stacktrace_score(a: str, b: str) -> float:
    """Compute a lightweight overlap score between two stack traces."""
    na = normalize_stacktrace(a)
    nb = normalize_stacktrace(b)
    if not na or not nb:
        return 0.0
    ta = set(extract_function_tokens(na))
    tb = set(extract_function_tokens(nb))
    if not ta or not tb:
        return 0.0
    overlap = ta.intersection(tb)
    score = len(overlap) / max(len(ta), len(tb))
    return float(score)


class ContractRetriever:
    """Thin adapter that conforms to the BaseRetriever contract (if available).

    This adapter wraps any object exposing an async `search(query, limit)` method.
    """

    def __init__(self, inner):
        self.inner = inner

    async def search(self, query: str, limit: int = 10):
        # Delegate if async
        if hasattr(self.inner, "search"):
            res = self.inner.search(query=query, limit=limit)
            # If result is awaitable, await it
            if hasattr(res, "__await__"):
                return await res
            return res
        return []



# ---------------------------------------------------------------------------
# Compatibility shim for tests: SemanticRetriever
# ---------------------------------------------------------------------------
class SemanticRetriever:
    """Minimal compatibility wrapper around a ChromaClient instance.

    This class exists only to satisfy test imports and provides a thin
    async `search` method delegating to a provided chroma client.
    """
    def __init__(self, chroma_client=None):
        self.chroma_client = chroma_client

    async def search(self, query: str, limit: int = 5):
        if not self.chroma_client:
            return []

        return await self.chroma_client.search(query=query, limit=limit)
