import asyncio
from datetime import datetime, timedelta
from typing import Dict, Any

from core.causality import correlate_deployment_events


class DeploymentCorrelator:
    """Correlate incidents with recent deployments, commits, and PR merges.

    This is a lightweight component that queries available metadata (via the
    provided incident payloads or external systems) and returns a correlation
    score. In production this should consult a CI/CD events datastore.
    """

    def __init__(self, window_minutes: int = 30):
        self.window = timedelta(minutes=window_minutes)

    def correlate(self, incident: Dict[str, Any]) -> Dict[str, Any]:
        """Return a normalized correlation dict for the incident."""
        return correlate_deployment_events(incident, window_minutes=int(self.window.total_seconds() / 60))
