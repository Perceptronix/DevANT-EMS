import os
from typing import List, Optional
import httpx
from datetime import datetime

from ontology import Deployment

class GitHubActionsIngest:
    """Fetch GitHub Actions workflow runs for a repository and emit DeploymentEvents."""

    def __init__(self, token: Optional[str] = None):
        self.token = token or os.getenv("GITHUB_TOKEN")
        self.base = "https://api.github.com"

    async def fetch_runs(self, repo: str, per_page: int = 50) -> List[Deployment]:
        headers = {"Accept": "application/vnd.github+json"}
        if self.token:
            headers["Authorization"] = f"token {self.token}"

        url = f"{self.base}/repos/{repo}/actions/runs?per_page={per_page}"
        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                resp = await client.get(url, headers=headers)
                resp.raise_for_status()
                data = resp.json()
            except Exception:
                # Return empty if fails
                return []
                
            runs = data.get("workflow_runs", [])
            out = []
            for r in runs:
                # Infer basic properties from GitHub Actions run
                env = "production" if "prod" in r.get("name", "").lower() or r.get("event") == "push" else "staging"
                service = repo.split("/")[-1] # Default to repo name
                
                # Parse timestamp
                ts_str = r.get("updated_at") or r.get("created_at")
                if ts_str:
                    try:
                        ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                    except ValueError:
                        ts = datetime.utcnow()
                else:
                    ts = datetime.utcnow()

                # Infer rollback if name implies it
                workflow_name = r.get("name", "Unknown")
                rollback_of = None
                if "revert" in workflow_name.lower() or "rollback" in workflow_name.lower():
                    rollback_of = "previous"

                out.append(Deployment(
                    source_of_truth="github_actions",
                    timestamp=ts,
                    confidence_origin="workflow_run_metadata",
                    evidence_origin=[r.get("html_url", ""), repo],
                    deployment_id=str(r.get("id", "")),
                    commit_hash=r.get("head_sha", ""),
                    workflow_name=workflow_name,
                    service=service,
                    environment=env,
                    status=r.get("conclusion") or r.get("status") or "unknown",
                    rollback_of=rollback_of,
                    actor=r.get("actor", {}).get("login") if isinstance(r.get("actor"), dict) else None,
                    url=r.get("html_url"),
                ))
            return out
