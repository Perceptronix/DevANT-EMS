"""
Error Pipeline — connects deployment failure detection to alert output.

Called either by:
  1. The GitHub webhook handler when a deployment_status event arrives
  2. The manual trigger endpoint for on-demand scanning

This pipeline is async. The deployment failure detector is sync,
so it runs in an executor to avoid blocking the event loop.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


async def run_error_pipeline(
    repo_url: str,
    environment: str = "production",
    log_url: Optional[str] = None,
    since_hours: int = 24,
) -> Dict[str, Any]:
    """
    Run the full error detection and alert pipeline.
    
    Step 1: Detect deployment failures (sync, runs in executor)
    Step 2: Check suppression rules
    Step 3: Post Slack alert if needed
    Step 4: Record to IncidentGraph
    """
    try:
        # Step 1: Run deployment failure detection in executor
        from pipeline.deployment_failure_detector import detect_deployment_failures
        
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: detect_deployment_failures(
                repo_url, environment, since_hours
            )
        )
        
        if result.get("error"):
            logger.warning(f"Deployment detection failed: {result.get('error')}")
            result["alerted"] = False
            result["suppressed"] = False
            return result
        
        # Step 2: Early exit if no failures
        if not result.get("has_failures"):
            logger.info(f"No failures detected for {repo_url} in {environment}")
            result["alerted"] = False
            result["suppressed"] = False
            return result
        
        # Step 3: Check suppression
        from pipeline.suppression_engine import SuppressionEngine
        
        engine = SuppressionEngine()
        clusters = result.get("clusters", [])
        active_clusters = engine.filter(clusters)
        suppressed_count = len(clusters) - len(active_clusters)
        
        logger.info(
            f"Suppression: {len(clusters)} clusters → {len(active_clusters)} active "
            f"({suppressed_count} suppressed)"
        )
        
        # Step 4: Post Slack alert if any clusters survived
        alerted = False
        if active_clusters:
            result["clusters"] = active_clusters  # Update with non-suppressed
            
            from connectors.slack_connector import SlackConnector
            
            connector = SlackConnector()
            if connector.is_configured:
                try:
                    async with connector:
                        alerted = await connector.post_alert(result)
                except Exception as exc:
                    logger.error(f"Slack alert failed: {exc}", exc_info=True)
                    alerted = False
            else:
                logger.info(
                    "Slack not configured — skipping alert (log-only mode)"
                )
                alerted = False
        
        # Step 5: Record to IncidentGraph
        try:
            from memory.incident_graph import IncidentGraph
            
            graph = IncidentGraph()
            for cluster in active_clusters:
                incident_id = cluster.get(
                    "cluster_id", f"inc_{int(datetime.now().timestamp())}"
                )
                graph.add_incident(
                    incident_id=incident_id,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    repo=repo_url,
                    dominant_service=(
                        cluster.get("affected_services", ["unknown"])[0]
                    ),
                    blast_radius=cluster.get("error_count", 1),
                    operational_confidence=cluster.get("confidence", 0.5),
                    regression_risk=cluster.get("regression_probability", 0.3),
                    topology_hash=hashlib.md5(
                        ",".join(
                            sorted(cluster.get("affected_services", []))
                        ).encode()
                    ).hexdigest()[:8],
                )
        except Exception as exc:
            logger.warning(f"IncidentGraph update failed (non-fatal): {exc}")
        
        # Step 6: Return enriched result
        result["alerted"] = alerted
        result["suppressed_count"] = suppressed_count
        result["active_cluster_count"] = len(active_clusters)
        result["pipeline_completed_at"] = (
            datetime.now(timezone.utc).isoformat()
        )
        
        return result

    except Exception as exc:
        logger.error(
            f"Error pipeline failed for {repo_url}: {exc}", exc_info=True
        )
        return {
            "repo": repo_url,
            "environment": environment,
            "error": str(exc),
            "has_failures": False,
            "alerted": False,
        }
