"""Normalize stacktraces to preserve operational semantics while ignoring ephemeral data."""

from __future__ import annotations

import re
from typing import List, Dict, Any, Tuple


class StacktraceNormalizer:
    """Normalize stacktraces for regression detection.

    Strips:
    - Timestamps and dates
    - Request IDs, trace IDs, correlation IDs
    - Dynamic tokens (UUIDs, hex values, memory addresses)
    - Line numbers and byte offsets
    - Ephemeral identifiers (PID, TID, session IDs)

    Preserves:
    - Function/method names
    - Module paths (deduplicated)
    - Error types
    - File names (without paths)
    - Operational keywords (timeout, retry, connection, saturation, etc.)
    """

    # Regex patterns for ephemeral data
    PATTERNS = {
        "uuid": re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.IGNORECASE),
        "hex": re.compile(r"0x[0-9a-f]+", re.IGNORECASE),
        "timestamp": re.compile(r"\d{4}-\d{2}-\d{2}[T\s]\d{2}:\d{2}:\d{2}(\.\d+)?"),
        "date": re.compile(r"\d{2}/\d{2}/\d{4}|\d{4}-\d{2}-\d{2}"),
        "line_number": re.compile(r"line\s+\d+|:\d{4,}[:\s)]"),
        "memory_address": re.compile(r"0x[0-9a-f]{8,}"),
        "pid_tid": re.compile(r"pid[=:\s]+\d+|tid[=:\s]+\d+|process[=:\s]+\d+|thread[=:\s]+\d+"),
        "request_id": re.compile(r"request[_-]?id[=:\s]+\S+|correlation[_-]?id[=:\s]+\S+|trace[_-]?id[=:\s]+\S+"),
        "session_id": re.compile(r"session[_-]?id[=:\s]+\S+|cookie[=:\s]+\S+"),
        "numeric_literal": re.compile(r"\b\d{5,}\b"),  # Long numeric literals
    }

    # Operational keywords to preserve
    OPERATIONAL_KEYWORDS = {
        "timeout", "retry", "connection", "saturation", "deadlock",
        "cascade", "propagation", "degradation", "latency", "spike",
        "outage", "failure", "error", "panic", "crash", "hang",
        "leak", "exhausted", "exceeded", "limit", "quota", "throttle",
        "backoff", "circuit", "breaker", "fallback", "circuit-break",
        "rollback", "deployment", "rollout", "canary", "blue-green",
        # Common error types
        "attributeerror", "typeerror", "keyerror", "valueerror",
        "connectionerror", "timeouterror", "ioerror", "oserror",
        "exception", "error", "fault", "failed", "failure",
        # Config-related
        "config", "configuration", "setting", "property",
        # Null/None-related
        "none", "null", "nil", "undefined",
    }

    def normalize(self, stacktrace: str) -> str:
        """Normalize a stacktrace by removing ephemeral data."""
        if not stacktrace:
            return ""

        lines = stacktrace.split("\n")
        normalized_lines = [self._normalize_line(line) for line in lines if line.strip()]
        return "\n".join(normalized_lines)

    def signature(self, stacktrace: str) -> str:
        """Generate a canonical signature from a normalized stacktrace.

        Returns a deduplicated, canonical form suitable for regression detection.
        """
        normalized = self.normalize(stacktrace)
        tokens = self._extract_canonical_tokens(normalized)
        return " ".join(sorted(set(tokens)))

    def similarity(self, trace_a: str, trace_b: str, threshold: float = 0.5) -> Tuple[float, Dict[str, Any]]:
        """Compute similarity between two stacktraces.

        Returns:
            (similarity_score, metadata) where score in [0.0, 1.0]
        """
        sig_a = self.signature(trace_a)
        sig_b = self.signature(trace_b)

        tokens_a = set(sig_a.split())
        tokens_b = set(sig_b.split())

        if not tokens_a or not tokens_b:
            return 0.0, {"reason": "empty_signature"}

        intersection = tokens_a.intersection(tokens_b)
        union = tokens_a.union(tokens_b)

        jaccard = len(intersection) / max(1, len(union))

        # Boost score if operational keywords match
        keywords_a = tokens_a.intersection(self.OPERATIONAL_KEYWORDS)
        keywords_b = tokens_b.intersection(self.OPERATIONAL_KEYWORDS)
        keyword_match = len(keywords_a.intersection(keywords_b)) / max(1, len(keywords_a.union(keywords_b)))

        combined_score = (jaccard * 0.7) + (keyword_match * 0.3)

        return combined_score, {
            "jaccard": jaccard,
            "keyword_match": keyword_match,
            "common_tokens": list(intersection)[:10],
            "trace_a_tokens": len(tokens_a),
            "trace_b_tokens": len(tokens_b),
        }

    def _normalize_line(self, line: str) -> str:
        """Normalize a single line of stacktrace."""
        normalized = line
        for pattern in self.PATTERNS.values():
            normalized = pattern.sub("[REDACTED]", normalized)

        # Clean up repeated [REDACTED] and whitespace
        normalized = re.sub(r"\[REDACTED\](\s+\[REDACTED\])+", "[REDACTED]", normalized)
        normalized = re.sub(r"\s+", " ", normalized)
        return normalized.strip()

    def _extract_canonical_tokens(self, normalized: str) -> List[str]:
        """Extract canonical tokens from normalized stacktrace."""
        tokens = []

        lines = normalized.split("\n")
        for line in lines:
            # Split on whitespace and punctuation, but keep function/file names
            parts = re.split(r"[\s\(\)\[\]<>,:]", line)
            for part in parts:
                part = part.strip()
                if not part or part == "[REDACTED]":
                    continue

                # Keep tokens that look like identifiers or operational keywords
                if (
                    re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", part)  # Valid identifier
                    or part in self.OPERATIONAL_KEYWORDS
                    or re.match(r"^(Error|Exception|Panic|Crash|Timeout|Retry)", part)
                ):
                    tokens.append(part.lower())

        return tokens
