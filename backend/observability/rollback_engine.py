from typing import Dict, Any, List, Optional


class RollbackEngine:
    """Suggest rollback candidates using deployment history and incident memory."""

    def __init__(self, deployment_history: List[Dict[str, Any]] = None):
        self.deployment_history = deployment_history or []

    def suggest(self, incident: Dict[str, Any]) -> List[Dict[str, Any]]:
        # Suggest recent deployments near incident timestamp as candidates
        ts = incident.get("timestamp")
        candidates = []
        for d in self.deployment_history:
            if d.get("commit_sha") and incident.get("commit_hash"):
                if d.get("commit_sha") == incident.get("commit_hash"):
                    candidates.append({"deployment": d, "reason": "commit match"})

        # fallback: return last successful deployment
        if not candidates and self.deployment_history:
            last = sorted(self.deployment_history, key=lambda x: x.get("timestamp"), reverse=True)[0]
            candidates.append({"deployment": last, "reason": "most recent"})

        return candidates
