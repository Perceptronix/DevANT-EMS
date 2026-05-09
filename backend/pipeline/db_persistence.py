"""
Persist unified orchestrator results to Supabase database.

Transforms pipeline output into database records for:
- raw_events (ingested signals)
- error_clusters (clustered incidents)
- cluster_embeddings (vector data)
- deployments (inferred from topology)
- etc.
"""
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime

logger = logging.getLogger(__name__)


def persist_orchestrator_result(run_id: str, result: Dict[str, Any]) -> Dict[str, int]:
    """
    Persist unified orchestrator result to all relevant database tables.
    
    Args:
        run_id: The analysis run ID
        result: Output dict from UnifiedOrchestrator.run()
    
    Returns:
        Dict with counts of records persisted: {table_name: count}
    """
    from database.client import get_database_client
    from database.repositories.entities import (
        ProjectRepository,
        RawEventRepository,
        ErrorClusterRepository,
        ClusterEmbeddingRepository,
    )
    
    counts = {
        "projects": 0,
        "raw_events": 0,
        "error_clusters": 0,
        "cluster_embeddings": 0,
    }
    
    try:
        client = get_database_client()
        session = client.get_session()
        
        try:
            # 1. Ensure project exists
            proj_repo = ProjectRepository(session)
            repo_url = result.get("repo_url", "unknown")
            proj_name = repo_url.split("/")[-1] if repo_url else f"run-{run_id}"
            
            project = proj_repo.get_by_github_repo(repo_url)
            if not project:
                project = proj_repo.create(
                    name=proj_name,
                    github_repo=repo_url,
                )
                counts["projects"] = 1
            
            project_id = project.id
            logger.info(f"[persist] Using project_id={project_id}")
            
            # 2. Persist raw events from signals (embedded in evidence)
            raw_event_repo = RawEventRepository(session)
            evidence = result.get("evidence", {})
            
            # Evidence may contain live_error details
            live_errors = evidence.get("live_errors", [])
            if live_errors:
                for i, error in enumerate(live_errors):
                    try:
                        fingerprint = error.get("signature") or error.get("id") or f"error-{i}"
                        message_text = error.get("sample_messages", [error.get("message", "")])[0] if error.get("sample_messages") or error.get("message") else "Unknown error"
                        raw_event = raw_event_repo.create(
                            project_id=project_id,
                            source_type="devant_orchestrator",
                            service=error.get("module", "unknown"),
                            environment="production",
                            message=message_text,
                            stack_trace=error.get("stack_trace", None),
                            fingerprint=fingerprint,
                            occurred_at=datetime.utcnow(),
                            extra_metadata={
                                "error_count": error.get("error_count", 0),
                                "org_count": error.get("org_count", 0),
                                "severity": error.get("severity", "error"),
                                "signature": error.get("signature", ""),
                                "function": error.get("function", ""),
                                "container": error.get("container", ""),
                            },
                        )
                        counts["raw_events"] += 1
                    except Exception as e:
                        logger.warning(f"[persist] Failed to save raw_event {i}: {e}")
            
            # 3. Persist error clusters
            cluster_repo = ErrorClusterRepository(session)
            active_clusters = evidence.get("live_errors", [])
            
            for cluster in active_clusters:
                try:
                    signature = cluster.get("signature") or cluster.get("id", "")
                    cluster_rec = cluster_repo.create(
                        project_id=project_id,
                        title=f"[{cluster.get('severity', 'error')}] {signature[:80]}",
                        event_count=cluster.get("error_count", 0),
                        severity=cluster.get("severity", "error").upper(),
                        status="OPEN",
                        confidence=float(cluster.get("confidence", 0.0)),
                    )
                    counts["error_clusters"] += 1
                except Exception as e:
                    logger.warning(f"[persist] Failed to save cluster {cluster.get('signature', 'unknown')}: {e}")
            
            session.commit()
            logger.info(f"[persist] Persisted to DB: {counts}")
            
        finally:
            session.close()
    
    except Exception as e:
        logger.error(f"[persist] Failed to persist orchestrator result: {e}", exc_info=True)
    
    return counts
