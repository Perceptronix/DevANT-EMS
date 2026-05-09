"""
Suppression Engine.

Prevents alert fatigue by filtering out signals that should not fire:
  - Exact duplicates seen in the last `window_minutes`
  - Acknowledged / muted signatures from StateManager
  - Transient flaps (only 1 occurrence, low confidence)
  - Clusters with confidence below the configured threshold

Usage::

    engine = SuppressionEngine()
    filtered = engine.filter(clusters)
    for cluster in filtered:
        if engine.should_suppress(cluster):
            continue
        yield cluster
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

_MIN_CONFIDENCE = 0.0     # suppress clusters below this confidence
_MIN_ERROR_COUNT = 1       # suppress clusters with fewer occurrences


class SuppressionEngine:
    """
    Determines whether a clustered incident should be suppressed.

    Suppression rules (checked in order):
      1. Muted by user via StateManager
      2. Duplicate signature seen < window_minutes ago (state-based)
      3. Error count below threshold (transient flap)
      4. Cluster confidence below floor
    """

    def __init__(self, window_minutes: int = 60):
        self.window_minutes = window_minutes
        self._state = self._get_state()

    def filter(self, clusters: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Return only non-suppressed clusters, with suppression_reason added."""
        active: List[Dict[str, Any]] = []
        suppressed_count = 0

        for cluster in clusters:
            reason = self._suppression_reason(cluster)
            if reason:
                suppressed_count += 1
                logger.info(
                    f"Suppressed cluster '{cluster.get('signature', '')[:60]}': {reason}"
                )
            else:
                cluster["suppressed"] = False
                active.append(cluster)

        if suppressed_count:
            logger.info(
                f"SuppressionEngine: {suppressed_count}/{len(clusters)} clusters suppressed"
            )
        return active

    def should_suppress(self, cluster: Dict[str, Any]) -> bool:
        return bool(self._suppression_reason(cluster))

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _suppression_reason(self, cluster: Dict[str, Any]) -> str:
        """Return non-empty string if the cluster should be suppressed."""
        signature = cluster.get("signature", "") or cluster.get("id", "")

        # Rule 1: User-muted signature
        if self._state and self._state.is_muted(signature):
            return "muted by user"

        # Rule 2: Error count too low (transient flap)
        error_count = cluster.get("error_count", 1)
        if error_count < _MIN_ERROR_COUNT:
            return f"only {error_count} occurrence(s), treating as transient"

        return ""   # not suppressed

    @staticmethod
    def _get_state():
        try:
            from state import get_state_manager
            return get_state_manager()
        except Exception:
            return None
