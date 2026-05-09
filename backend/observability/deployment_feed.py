"""
Live deployment feed ingestion.

Tracks:
- GitHub Actions deployments
- Kubernetes rollouts
- Rollback events
- Canary deployments
- Failed deploys

Enables deployment-to-incident correlation.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from datetime import datetime, timezone, timedelta
from enum import Enum
import logging
import hashlib

logger = logging.getLogger(__name__)


class DeploymentStatus(Enum):
    """Deployment execution status."""
    INITIATED = "initiated"
    IN_PROGRESS = "in_progress"
    CANARY = "canary"
    ROLLING = "rolling"
    COMPLETED = "completed"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"


class DeploymentSource(Enum):
    """Source system."""
    GITHUB_ACTIONS = "github_actions"
    KUBERNETES = "kubernetes"
    MANUAL = "manual"
    TERRAFORM = "terraform"
    OTHER = "other"


@dataclass
class DeploymentEvent:
    """
    Single deployment operation.
    
    Represents deployment of service version to environment.
    """
    deployment_id: str
    service_name: str
    version: str
    environment: str
    
    status: DeploymentStatus = DeploymentStatus.IN_PROGRESS
    source: DeploymentSource = DeploymentSource.OTHER
    
    # Timing
    start_time: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    end_time: Optional[datetime] = None
    
    # Details
    region: Optional[str] = None
    replicas: int = 0
    rollout_strategy: str = "rolling"  # "rolling", "canary", "blue-green"
    
    # Context
    commit_sha: Optional[str] = None
    commit_message: Optional[str] = None
    author: Optional[str] = None
    
    # Result
    success: bool = False
    error_message: Optional[str] = None
    duration_seconds: Optional[float] = None
    
    # Tracking
    ingestion_timestamp: Optional[datetime] = None
    
    def __post_init__(self):
        # Normalize timestamps
        if self.start_time.tzinfo is None:
            self.start_time = self.start_time.replace(tzinfo=timezone.utc)
        if self.end_time and self.end_time.tzinfo is None:
            self.end_time = self.end_time.replace(tzinfo=timezone.utc)
        if self.ingestion_timestamp is None:
            self.ingestion_timestamp = datetime.now(timezone.utc)
    
    def duration_or_active(self) -> float:
        """Duration in seconds (or active duration if ongoing)."""
        end = self.end_time or datetime.now(timezone.utc)
        return (end - self.start_time).total_seconds()
    
    def is_in_progress(self) -> bool:
        """Deployment still executing."""
        return self.status in (
            DeploymentStatus.INITIATED,
            DeploymentStatus.IN_PROGRESS,
            DeploymentStatus.CANARY,
            DeploymentStatus.ROLLING,
        )
    
    def is_completed(self) -> bool:
        """Deployment completed (success or failure)."""
        return self.status in (
            DeploymentStatus.COMPLETED,
            DeploymentStatus.FAILED,
            DeploymentStatus.ROLLED_BACK,
        )
    
    def identifier(self) -> str:
        """Unique deployment identifier."""
        # Use content hash for deduplication
        data = f"{self.service_name}:{self.version}:{self.start_time.isoformat()}:{self.commit_sha}"
        return hashlib.md5(data.encode()).hexdigest()


@dataclass
class RollbackEvent:
    """Rollback of failed deployment."""
    rollback_id: str
    deployment_id: str
    service_name: str
    from_version: str
    to_version: str
    
    reason: Optional[str] = None
    triggered_by: Optional[str] = None  # "auto" or username
    
    start_time: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    end_time: Optional[datetime] = None
    
    success: bool = False
    error_message: Optional[str] = None
    
    ingestion_timestamp: Optional[datetime] = None
    
    def __post_init__(self):
        if self.start_time.tzinfo is None:
            self.start_time = self.start_time.replace(tzinfo=timezone.utc)
        if self.end_time and self.end_time.tzinfo is None:
            self.end_time = self.end_time.replace(tzinfo=timezone.utc)
        if self.ingestion_timestamp is None:
            self.ingestion_timestamp = datetime.now(timezone.utc)


class DeploymentFeed:
    """
    Live deployment event ingestion.
    
    Tracks deployments for incident correlation.
    """
    
    def __init__(self, retention_days: int = 30):
        self.retention_days = retention_days
        
        # Deployment events: deployment_id -> DeploymentEvent
        self.deployments: Dict[str, DeploymentEvent] = {}
        
        # Rollback events: rollback_id -> RollbackEvent
        self.rollbacks: Dict[str, RollbackEvent] = {}
        
        # Service version history: service -> [versions]
        self.version_history: Dict[str, List[str]] = {}
        
        # Deduplication
        self.seen_event_hashes: set = set()
        
        # Statistics
        self.stats = {
            "total_deployments": 0,
            "successful_deployments": 0,
            "failed_deployments": 0,
            "total_rollbacks": 0,
            "successful_rollbacks": 0,
            "ingestions": 0,
        }
    
    def ingest_deployment(self, event: DeploymentEvent) -> bool:
        """
        Ingest deployment event.
        
        Returns True if new, False if duplicate.
        """
        # Deduplication
        event_hash = event.identifier()
        if event_hash in self.seen_event_hashes:
            return False
        self.seen_event_hashes.add(event_hash)
        
        # Store
        self.deployments[event.deployment_id] = event
        
        # Track version
        if event.service_name not in self.version_history:
            self.version_history[event.service_name] = []
        if event.version not in self.version_history[event.service_name]:
            self.version_history[event.service_name].append(event.version)
        
        # Update stats
        self.stats["total_deployments"] += 1
        if event.is_completed():
            if event.status == DeploymentStatus.COMPLETED or event.success:
                self.stats["successful_deployments"] += 1
            else:
                self.stats["failed_deployments"] += 1
        
        # Cleanup old deployments
        self._cleanup_old_events()
        
        return True
    
    def ingest_batch(self, events: List[Dict[str, Any]]) -> Dict[str, int]:
        """Ingest batch of deployment events."""
        result = {"ingested": 0, "duplicates": 0, "failed": 0}
        
        for event_dict in events:
            try:
                deployment_id = event_dict.get("deployment_id")
                service_name = event_dict.get("service_name", "unknown")
                version = event_dict.get("version", "unknown")
                environment = event_dict.get("environment", "production")
                
                # Parse status
                status_str = event_dict.get("status", "in_progress").lower()
                try:
                    status = DeploymentStatus[status_str.upper()]
                except KeyError:
                    status = DeploymentStatus.IN_PROGRESS
                
                # Parse source
                source_str = event_dict.get("source", "other").lower()
                try:
                    source = DeploymentSource[source_str.upper().replace(" ", "_")]
                except KeyError:
                    source = DeploymentSource.OTHER
                
                # Parse timestamps
                start_time = self._parse_timestamp(event_dict.get("start_time"))
                end_time = self._parse_timestamp(event_dict.get("end_time"))
                
                event = DeploymentEvent(
                    deployment_id=deployment_id or f"{service_name}_{version}_{datetime.now(timezone.utc).timestamp()}",
                    service_name=service_name,
                    version=version,
                    environment=environment,
                    status=status,
                    source=source,
                    start_time=start_time,
                    end_time=end_time,
                    region=event_dict.get("region"),
                    replicas=int(event_dict.get("replicas", 0)),
                    rollout_strategy=event_dict.get("rollout_strategy", "rolling"),
                    commit_sha=event_dict.get("commit_sha"),
                    commit_message=event_dict.get("commit_message"),
                    author=event_dict.get("author"),
                    success=event_dict.get("success", False),
                    error_message=event_dict.get("error_message"),
                )
                
                if self.ingest_deployment(event):
                    result["ingested"] += 1
                else:
                    result["duplicates"] += 1
                    
            except Exception as e:
                result["failed"] += 1
                logger.error(f"Failed to ingest deployment: {e}")
        
        self.stats["ingestions"] += 1
        return result

    # Helpers to ingest from Kubernetes event / webhook
    def ingest_k8s_rollout(self, k8s_event: Dict[str, Any]) -> bool:
        """Parse and ingest Kubernetes rollout event dict."""
        try:
            # Example expected keys: namespace, name, version, status, start_time
            service = k8s_event.get('name') or k8s_event.get('service')
            version = k8s_event.get('version') or k8s_event.get('image')
            status = k8s_event.get('status', 'in_progress').lower()
            try:
                status_enum = DeploymentStatus[status.upper()]
            except Exception:
                status_enum = DeploymentStatus.IN_PROGRESS
            event = DeploymentEvent(
                deployment_id=k8s_event.get('uid') or f"k8s_{service}_{datetime.now(timezone.utc).timestamp()}",
                service_name=service or 'unknown',
                version=version or 'unknown',
                environment=k8s_event.get('namespace', 'production'),
                status=status_enum,
                start_time=self._parse_timestamp(k8s_event.get('start_time')),
                end_time=self._parse_timestamp(k8s_event.get('end_time')) if k8s_event.get('end_time') else None,
                success=k8s_event.get('success', False),
            )
            return self.ingest_deployment(event)
        except Exception as e:
            logger.exception("Failed to ingest k8s rollout: %s", e)
            return False

    # Helpers to ingest GitHub Actions deployment events
    def ingest_github_action(self, gha_event: Dict[str, Any]) -> bool:
        """Parse GitHub Actions deployment webhook payload."""
        try:
            # Example keys: workflow, repository, ref, sha, environment, status
            repo = gha_event.get('repository', {}).get('name') if isinstance(gha_event.get('repository'), dict) else gha_event.get('repository')
            service = repo or gha_event.get('service') or 'unknown'
            version = gha_event.get('sha') or gha_event.get('ref')
            status = gha_event.get('status', 'in_progress').lower()
            try:
                status_enum = DeploymentStatus[status.upper()]
            except Exception:
                status_enum = DeploymentStatus.IN_PROGRESS
            event = DeploymentEvent(
                deployment_id=gha_event.get('id') or f"gha_{service}_{datetime.now(timezone.utc).timestamp()}",
                service_name=service,
                version=version or 'unknown',
                environment=gha_event.get('environment', 'production'),
                status=status_enum,
                start_time=self._parse_timestamp(gha_event.get('started_at')),
                end_time=self._parse_timestamp(gha_event.get('completed_at')) if gha_event.get('completed_at') else None,
                success=gha_event.get('conclusion') == 'success',
            )
            return self.ingest_deployment(event)
        except Exception as e:
            logger.exception("Failed to ingest GitHub Actions event: %s", e)
            return False
    
    def ingest_rollback(self, rollback: RollbackEvent) -> bool:
        """Ingest rollback event."""
        self.rollbacks[rollback.rollback_id] = rollback
        
        self.stats["total_rollbacks"] += 1
        if rollback.success:
            self.stats["successful_rollbacks"] += 1
        
        return True
    
    def get_deployment(self, deployment_id: str) -> Optional[DeploymentEvent]:
        """Get deployment by ID."""
        return self.deployments.get(deployment_id)
    
    def get_recent_deployments(self, service_name: Optional[str] = None,
                              hours: int = 24) -> List[DeploymentEvent]:
        """
        Get recent deployments.
        
        Optional filter by service.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        recent = [
            d for d in self.deployments.values()
            if d.start_time >= cutoff
            and (service_name is None or d.service_name == service_name)
        ]
        
        # Sort by start time descending
        recent.sort(key=lambda d: d.start_time, reverse=True)
        return recent
    
    def get_failed_deployments(self, service_name: Optional[str] = None,
                              hours: int = 24) -> List[DeploymentEvent]:
        """Get failed deployments in recent window."""
        recent = self.get_recent_deployments(service_name, hours)
        return [d for d in recent if not d.success and d.is_completed()]
    
    def deployments_during_window(self, service_name: str,
                                 start_time: datetime,
                                 end_time: datetime) -> List[DeploymentEvent]:
        """Get deployments during time window."""
        window_deploys = [
            d for d in self.deployments.values()
            if d.service_name == service_name
            and d.start_time <= end_time
            and (d.end_time is None or d.end_time >= start_time)
        ]
        return sorted(window_deploys, key=lambda d: d.start_time)
    
    def get_version_by_date(self, service_name: str,
                           timestamp: datetime) -> Optional[str]:
        """Get active version of service at given time."""
        # Find deployment that was active at timestamp
        active = None
        for deploy in self.deployments.values():
            if deploy.service_name != service_name:
                continue
            if deploy.start_time <= timestamp and deploy.status == DeploymentStatus.COMPLETED:
                if active is None or deploy.start_time > active.start_time:
                    active = deploy
        
        return active.version if active else None
    
    def _parse_timestamp(self, value: Any) -> datetime:
        """Parse timestamp, default to now."""
        if value is None:
            return datetime.now(timezone.utc)
        if isinstance(value, datetime):
            return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value)
            except:
                return datetime.now(timezone.utc)
        return datetime.now(timezone.utc)
    
    def _cleanup_old_events(self) -> None:
        """Remove deployments older than retention."""
        cutoff = datetime.now(timezone.utc) - timedelta(days=self.retention_days)
        to_remove = [
            did for did, d in self.deployments.items()
            if d.end_time and d.end_time < cutoff
        ]
        for did in to_remove:
            del self.deployments[did]
    
    def health_check(self) -> Dict[str, Any]:
        """Feed health."""
        success_rate = 0.0
        if self.stats["total_deployments"] > 0:
            success_rate = self.stats["successful_deployments"] / self.stats["total_deployments"]
        
        return {
            "total_deployments": self.stats["total_deployments"],
            "successful": self.stats["successful_deployments"],
            "failed": self.stats["failed_deployments"],
            "success_rate": success_rate,
            "total_rollbacks": self.stats["total_rollbacks"],
            "services_tracked": len(self.version_history),
        }
    
    def export_state(self) -> Dict[str, Any]:
        """Export for debugging."""
        return {
            "services": list(self.version_history.keys()),
            "recent_deployments": [
                {
                    "service": d.service_name,
                    "version": d.version,
                    "status": d.status.value,
                    "start_time": d.start_time.isoformat(),
                }
                for d in sorted(
                    self.deployments.values(),
                    key=lambda d: d.start_time,
                    reverse=True
                )[:20]
            ],
            "stats": self.stats,
        }


# Convenience: global instance
_default_feed: Optional[DeploymentFeed] = None


def get_deployment_feed() -> DeploymentFeed:
    """Get or create default deployment feed."""
    global _default_feed
    if _default_feed is None:
        _default_feed = DeploymentFeed()
    return _default_feed
