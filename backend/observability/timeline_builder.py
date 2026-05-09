from typing import List, Dict, Any


class TimelineBuilder:
    """Build an operational timeline from events (deployments, metrics, logs)."""

    def __init__(self):
        pass

    def build(self, events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Sort events by timestamp and return a simple timeline.

        Events should have a `timestamp` field (ISO string).
        """
        def _ts(e):
            return e.get("timestamp") or e.get("time") or ""

        sorted_events = sorted(events, key=lambda e: _ts(e))
        timeline = []
        for e in sorted_events:
            timeline.append({
                "time": e.get("timestamp"),
                "type": e.get("type") or e.get("provider"),
                "desc": e.get("description") or e.get("workflow") or e.get("metric"),
                "meta": e,
            })
        return timeline
