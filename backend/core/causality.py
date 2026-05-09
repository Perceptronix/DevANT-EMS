from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from .normalization import normalize_timestamp


def correlate_deployment_events(incident: Dict[str, Any], window_minutes: int = 30) -> Dict[str, Any]:
    now = datetime.utcnow()
    timestamp = normalize_timestamp(incident.get("timestamp") or incident.get("occurred_at")) or now
    window = timedelta(minutes=window_minutes)
    correlation = {"matched": False, "score": 0.0, "events": []}

    def consider(event_type: str, event_time: Any, payload: Optional[Dict[str, Any]] = None, score: float = 0.0) -> None:
        parsed = normalize_timestamp(event_time)
        if parsed is None:
            return
        delta = timestamp - parsed
        if timedelta(0) <= delta <= window:
            correlation["matched"] = True
            correlation["score"] = max(correlation["score"], score)
            event = {"type": event_type, "time": parsed.isoformat()}
            if payload:
                event.update(payload)
            correlation["events"].append(event)

    consider("deployment", incident.get("deployment_time") or incident.get("last_deploy_time"), score=1.0)
    consider("commit", incident.get("commit_time"), {"hash": incident.get("commit_hash")}, score=0.8)
    consider("pr_merge", incident.get("pr_merged_time"), score=0.75)

    return correlation