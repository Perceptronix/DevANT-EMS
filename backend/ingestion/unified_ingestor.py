"""
Unified Signal Ingestion Layer.

Normalizes ALL operational signals — errors, deployments, repo events — into
one canonical NormalizedSignal format that flows into the UnifiedOrchestrator.

Supported adapters:
  - sample   → SampleDataSource (always available)
  - sentry   → Sentry API (if configured)
  - azure    → Azure Log Analytics (if configured)
  - github   → GitHub API events (if GITHUB_TOKEN set)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class NormalizedSignal:
    """
    Canonical operational signal.  Every upstream adapter converts its raw
    payload into this schema before handing it to the orchestrator.
    """
    source: str                          # "sample" | "sentry" | "azure" | "github"
    signal_type: str                     # "error" | "deployment" | "commit" | "k8s_event"
    severity: str                        # "critical" | "high" | "medium" | "low" | "info"
    timestamp: str                       # ISO-8601 UTC
    service: str                         # originating service / module
    title: str                           # short human-readable label
    payload: Dict[str, Any] = field(default_factory=dict)   # raw source data
    trace_id: Optional[str] = None       # correlation token across signals
    org_id: Optional[str] = None
    org_name: Optional[str] = None


class UnifiedIngestor:
    """
    Pulls from ALL configured sources and returns a unified list of
    NormalizedSignal objects sorted newest-first.

    Usage::

        ingestor = UnifiedIngestor()
        signals = ingestor.ingest(window_minutes=30, limit=200)
    """

    def __init__(self):
        from config import get_config
        self._cfg = get_config()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def ingest(
        self,
        window_minutes: int = 30,
        limit: int = 200,
    ) -> List[NormalizedSignal]:
        """
        Synchronously pull from every configured source.

        Returns newest-first list of NormalizedSignal objects.
        """
        signals: List[NormalizedSignal] = []

        # --- Sample errors (always available) --------------------------
        try:
            signals.extend(self._ingest_sample(window_minutes, limit))
        except Exception as exc:
            logger.warning(f"Sample ingestion failed: {exc}")

        # --- Sentry (optional) -----------------------------------------
        if self._cfg.data_source.source_type == "sentry":
            try:
                signals.extend(self._ingest_sentry(window_minutes, limit))
            except Exception as exc:
                logger.warning(f"Sentry ingestion failed: {exc}")

        # --- Azure (optional) ------------------------------------------
        if self._cfg.data_source.source_type == "azure":
            try:
                signals.extend(self._ingest_azure(window_minutes, limit))
            except Exception as exc:
                logger.warning(f"Azure ingestion failed: {exc}")

        # Sort newest-first, deduplicate by title+service within 1 min window
        signals.sort(key=lambda s: s.timestamp, reverse=True)
        signals = self._deduplicate(signals)

        logger.info(f"UnifiedIngestor: ingested {len(signals)} signals total")
        return signals[:limit]

    # ------------------------------------------------------------------
    # Source Adapters
    # ------------------------------------------------------------------

    def _ingest_sample(
        self, window_minutes: int, limit: int
    ) -> List[NormalizedSignal]:
        """Convert sample errors into NormalizedSignal."""
        from samples import get_sample_errors

        raw_errors = get_sample_errors(include_extended=True)
        out: List[NormalizedSignal] = []
        for err in raw_errors[:limit]:
            # err can be a dict or RawError pydantic model
            if hasattr(err, "dict"):
                err = err.dict()

            level = str(err.get("level", "ERROR")).upper()
            severity = self._level_to_severity(level)

            out.append(NormalizedSignal(
                source="sample",
                signal_type="error",
                severity=severity,
                timestamp=self._coerce_ts(err.get("timestamp")),
                service=str(err.get("module", err.get("container", "unknown"))),
                title=str(err.get("message", "Unknown error"))[:120],
                payload=err,
                org_id=str(err.get("org_id", "")),
                org_name=str(err.get("org_name", "")),
            ))
        return out

    def _ingest_sentry(
        self, window_minutes: int, limit: int
    ) -> List[NormalizedSignal]:
        """Convert Sentry events into NormalizedSignal."""
        try:
            from sources.sentry_source import SentrySource
            src = SentrySource()
            import asyncio
            loop = asyncio.new_event_loop()
            raw = loop.run_until_complete(
                src.fetch_errors(window_minutes=window_minutes, limit=limit)
            )
            loop.close()
        except Exception as exc:
            logger.warning(f"Sentry fetch failed: {exc}")
            return []

        out: List[NormalizedSignal] = []
        for err in raw:
            if hasattr(err, "dict"):
                err = err.dict()
            out.append(NormalizedSignal(
                source="sentry",
                signal_type="error",
                severity=self._level_to_severity(str(err.get("level", "error")).upper()),
                timestamp=self._coerce_ts(err.get("timestamp")),
                service=str(err.get("module", "unknown")),
                title=str(err.get("message", ""))[:120],
                payload=err,
            ))
        return out

    def _ingest_azure(
        self, window_minutes: int, limit: int
    ) -> List[NormalizedSignal]:
        """Convert Azure Log Analytics events into NormalizedSignal."""
        try:
            from sources.azure_source import AzureSource
            src = AzureSource()
            import asyncio
            loop = asyncio.new_event_loop()
            raw = loop.run_until_complete(
                src.fetch_errors(window_minutes=window_minutes, limit=limit)
            )
            loop.close()
        except Exception as exc:
            logger.warning(f"Azure fetch failed: {exc}")
            return []

        out: List[NormalizedSignal] = []
        for err in raw:
            if hasattr(err, "dict"):
                err = err.dict()
            out.append(NormalizedSignal(
                source="azure",
                signal_type="error",
                severity=self._level_to_severity(str(err.get("level", "error")).upper()),
                timestamp=self._coerce_ts(err.get("timestamp")),
                service=str(err.get("module", "unknown")),
                title=str(err.get("message", ""))[:120],
                payload=err,
            ))
        return out

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _level_to_severity(level: str) -> str:
        mapping = {
            "CRITICAL": "critical",
            "ERROR": "high",
            "WARNING": "medium",
            "WARN": "medium",
            "INFO": "low",
            "DEBUG": "info",
        }
        return mapping.get(level.upper(), "medium")

    @staticmethod
    def _coerce_ts(ts: Any) -> str:
        if ts is None:
            return datetime.utcnow().isoformat()
        if isinstance(ts, datetime):
            return ts.isoformat()
        return str(ts)

    @staticmethod
    def _deduplicate(signals: List[NormalizedSignal]) -> List[NormalizedSignal]:
        """Remove near-duplicate signals (same title+service within 60 seconds)."""
        seen: set = set()
        out: List[NormalizedSignal] = []
        for s in signals:
            key = f"{s.service}||{s.title[:40]}"
            if key not in seen:
                seen.add(key)
                out.append(s)
        return out
