"""Scheduled clustering job orchestrator using APScheduler.

Runs cluster processing pipeline every 5 minutes with error handling and retry safety.
"""
import time
import logging
from typing import Optional
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger(__name__)

_scheduler: Optional[BackgroundScheduler] = None
_MAX_RETRIES = 1
_RETRY_DELAY_SECONDS = 2


def get_cluster_scheduler() -> BackgroundScheduler:
    """Get or create background scheduler instance."""
    global _scheduler
    if _scheduler is None:
        _scheduler = BackgroundScheduler()
    return _scheduler


def _cluster_job_worker() -> None:
    """Execute cluster processing job with retry safety."""
    job_start = datetime.utcnow().isoformat()
    last_error: Optional[Exception] = None

    for attempt in range(_MAX_RETRIES + 1):
        try:
            from pipeline.cluster_processing import get_cluster_processing_pipeline

            pipeline = get_cluster_processing_pipeline(
                min_cluster_size=2,
                min_samples=1,
                merge_similarity_threshold=0.90,
                fetch_limit=500,
                lookback_minutes=5,
            )

            result = pipeline.process_recent_unclustered_events()

            logger.info(
                "Cluster job success [%s] attempt=%d: fetched=%d embedded=%d created=%d updated=%d assigned=%d noise=%d",
                job_start,
                attempt + 1,
                result.get("fetched_events", 0),
                result.get("embedded_events", 0),
                result.get("created_event_groups", 0),
                result.get("updated_event_groups", 0),
                result.get("assigned_events", 0),
                result.get("noise_ignored", 0),
            )

            if result.get("error"):
                logger.warning("Cluster job error payload [%s]: %s", job_start, result["error"])
            return

        except Exception as exc:
            last_error = exc
            logger.error(
                "Cluster job failed [%s] attempt=%d/%d: %s",
                job_start,
                attempt + 1,
                _MAX_RETRIES + 1,
                exc,
                exc_info=True,
            )
            if attempt < _MAX_RETRIES:
                time.sleep(_RETRY_DELAY_SECONDS)

    logger.error("Cluster job exhausted retries [%s]: %s", job_start, last_error)


def start_scheduler() -> None:
    """Start cluster scheduler on app startup."""
    scheduler = get_cluster_scheduler()
    
    # Avoid duplicate scheduler start and duplicate job registration on reload
    if scheduler.running and scheduler.get_job("cluster_processing_job"):
        logger.info("Cluster scheduler already running")
        return
    
    try:
        # Schedule job every 5 minutes
        scheduler.add_job(
            _cluster_job_worker,
            trigger=IntervalTrigger(minutes=5),
            id="cluster_processing_job",
            name="Cluster Processing Pipeline",
            misfire_grace_time=60,  # Allow 60s grace for missed triggers
            coalesce=True,  # Skip missed runs if backed up
            max_instances=1,  # Only one instance at a time
        )
        
        if not scheduler.running:
            scheduler.start()
        logger.info("Cluster scheduler started: interval=5min job=cluster_processing")
    
    except Exception as exc:
        logger.error("Failed to start cluster scheduler: %s", exc, exc_info=True)


def stop_scheduler() -> None:
    """Stop cluster scheduler on app shutdown."""
    scheduler = get_cluster_scheduler()
    
    if scheduler.running:
        try:
            scheduler.shutdown(wait=True)
            logger.info("Cluster scheduler stopped")
        except Exception as exc:
            logger.error("Error stopping cluster scheduler: %s", exc, exc_info=True)


__all__ = [
    "get_cluster_scheduler",
    "start_scheduler",
    "stop_scheduler",
]
