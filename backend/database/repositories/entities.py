"""
Specific repository implementations for each entity.
"""
import logging
from typing import List, Optional, Any
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, desc

from database.models import (
    Project, RawEvent, ErrorCluster, ClusterEmbedding,
    Incident, Alert, GitHubEvent, Deployment, Ticket, Mute,
    SignalFusionMetadata
)
from database.repositories.base import BaseRepository

logger = logging.getLogger(__name__)


class ProjectRepository(BaseRepository[Project]):
    """Repository for Project entity."""

    def __init__(self, db: Session):
        super().__init__(db, Project)

    def get_by_name(self, name: str) -> Optional[Project]:
        """Get project by name."""
        return self.db.query(Project).filter(Project.name == name).first()

    def get_by_github_repo(self, github_repo: str) -> Optional[Project]:
        """Get project by GitHub repository."""
        return self.db.query(Project).filter(Project.github_repo == github_repo).first()


class RawEventRepository(BaseRepository[RawEvent]):
    """Repository for RawEvent entity."""

    def __init__(self, db: Session):
        super().__init__(db, RawEvent)

    def get_by_project(self, project_id: Any, skip: int = 0, limit: int = 100) -> List[RawEvent]:
        """Get events for a project."""
        return (
            self.db.query(RawEvent)
            .filter(RawEvent.project_id == project_id)
            .order_by(desc(RawEvent.occurred_at))
            .offset(skip)
            .limit(limit)
            .all()
        )

    def get_by_fingerprint(self, fingerprint: str) -> List[RawEvent]:
        """Get events by fingerprint."""
        return self.db.query(RawEvent).filter(RawEvent.fingerprint == fingerprint).all()

    def get_recent(self, project_id: Any, minutes: int = 60) -> List[RawEvent]:
        """Get events from the last N minutes."""
        since = datetime.utcnow() - timedelta(minutes=minutes)
        return (
            self.db.query(RawEvent)
            .filter(
                and_(
                    RawEvent.project_id == project_id,
                    RawEvent.occurred_at >= since,
                )
            )
            .order_by(desc(RawEvent.occurred_at))
            .all()
        )


class ErrorClusterRepository(BaseRepository[ErrorCluster]):
    """Repository for ErrorCluster entity."""

    def __init__(self, db: Session):
        super().__init__(db, ErrorCluster)

    def get_by_project(self, project_id: Any, skip: int = 0, limit: int = 100) -> List[ErrorCluster]:
        """Get clusters for a project."""
        return (
            self.db.query(ErrorCluster)
            .filter(ErrorCluster.project_id == project_id)
            .order_by(desc(ErrorCluster.updated_at))
            .offset(skip)
            .limit(limit)
            .all()
        )

    def get_by_status(self, project_id: Any, status: str) -> List[ErrorCluster]:
        """Get clusters by status (NEW, REGRESSION, ONGOING)."""
        return (
            self.db.query(ErrorCluster)
            .filter(
                and_(
                    ErrorCluster.project_id == project_id,
                    ErrorCluster.status == status,
                )
            )
            .all()
        )

    def get_by_severity(self, project_id: Any, severity: str) -> List[ErrorCluster]:
        """Get clusters by severity (S1, S2, S3, S4)."""
        return (
            self.db.query(ErrorCluster)
            .filter(
                and_(
                    ErrorCluster.project_id == project_id,
                    ErrorCluster.severity == severity,
                )
            )
            .all()
        )

    def get_critical(self, project_id: Any) -> List[ErrorCluster]:
        """Get critical clusters (S1, S2)."""
        return (
            self.db.query(ErrorCluster)
            .filter(
                and_(
                    ErrorCluster.project_id == project_id,
                    ErrorCluster.severity.in_(["S1", "S2"]),
                )
            )
            .all()
        )


class ClusterEmbeddingRepository(BaseRepository[ClusterEmbedding]):
    """Repository for ClusterEmbedding entity (vector search)."""

    def __init__(self, db: Session):
        super().__init__(db, ClusterEmbedding)

    def get_by_cluster_id(self, cluster_id: Any) -> Optional[ClusterEmbedding]:
        """Get embedding for a cluster."""
        return self.db.query(ClusterEmbedding).filter(
            ClusterEmbedding.cluster_id == cluster_id
        ).first()

    def create_or_update(self, cluster_id: Any, embedding: List[float]) -> ClusterEmbedding:
        """Create or update embedding."""
        existing = self.get_by_cluster_id(cluster_id)
        if existing:
            existing.embedding = embedding
            self.db.commit()
            self.db.refresh(existing)
            return existing
        else:
            return self.create(cluster_id=cluster_id, embedding=embedding)

    def semantic_search(self, embedding: List[float], limit: int = 10) -> List[tuple]:
        """Search for similar clusters using vector similarity."""
        try:
            from embeddings import get_similarity_search_service

            service = get_similarity_search_service(session=self.db)
            return service.search_similar_events(
                embedding=embedding,
                similarity_threshold=0.0,
                limit=limit,
            )
        except Exception as exc:
            logger.warning("Semantic search failed: %s", exc)
            return []


class IncidentRepository(BaseRepository[Incident]):
    """Repository for Incident entity."""

    def __init__(self, db: Session):
        super().__init__(db, Incident)

    def get_by_cluster(self, cluster_id: Any) -> Optional[Incident]:
        """Get incident for a cluster."""
        return self.db.query(Incident).filter(Incident.cluster_id == cluster_id).first()

    def get_recent(self, project_id: Any, days: int = 7) -> List[Incident]:
        """Get recent incidents."""
        since = datetime.utcnow() - timedelta(days=days)
        return (
            self.db.query(Incident)
            .filter(Incident.created_at >= since)
            .order_by(desc(Incident.created_at))
            .all()
        )


class AlertRepository(BaseRepository[Alert]):
    """Repository for Alert entity."""

    def __init__(self, db: Session):
        super().__init__(db, Alert)

    def get_by_incident(self, incident_id: Any) -> List[Alert]:
        """Get alerts for an incident."""
        return self.db.query(Alert).filter(Alert.incident_id == incident_id).all()

    def get_by_channel(self, channel: str, skip: int = 0, limit: int = 100) -> List[Alert]:
        """Get alerts by channel."""
        return (
            self.db.query(Alert)
            .filter(Alert.channel == channel)
            .order_by(desc(Alert.created_at))
            .offset(skip)
            .limit(limit)
            .all()
        )

    def get_pending(self) -> List[Alert]:
        """Get pending alerts."""
        return self.db.query(Alert).filter(Alert.status == "pending").all()

    def mark_sent(self, alert_id: Any) -> Optional[Alert]:
        """Mark alert as sent."""
        return self.update(alert_id, status="sent", sent_at=datetime.utcnow())


class GitHubEventRepository(BaseRepository[GitHubEvent]):
    """Repository for GitHubEvent entity."""

    def __init__(self, db: Session):
        super().__init__(db, GitHubEvent)

    def get_by_project(self, project_id: Any, skip: int = 0, limit: int = 100) -> List[GitHubEvent]:
        """Get GitHub events for a project."""
        return (
            self.db.query(GitHubEvent)
            .filter(GitHubEvent.project_id == project_id)
            .order_by(desc(GitHubEvent.created_at))
            .offset(skip)
            .limit(limit)
            .all()
        )

    def get_by_type(self, project_id: Any, event_type: str) -> List[GitHubEvent]:
        """Get GitHub events by type."""
        return (
            self.db.query(GitHubEvent)
            .filter(
                and_(
                    GitHubEvent.project_id == project_id,
                    GitHubEvent.event_type == event_type,
                )
            )
            .all()
        )


class DeploymentRepository(BaseRepository[Deployment]):
    """Repository for Deployment entity."""

    def __init__(self, db: Session):
        super().__init__(db, Deployment)

    def get_by_project(self, project_id: Any, skip: int = 0, limit: int = 100) -> List[Deployment]:
        """Get deployments for a project."""
        return (
            self.db.query(Deployment)
            .filter(Deployment.project_id == project_id)
            .order_by(desc(Deployment.deployed_at))
            .offset(skip)
            .limit(limit)
            .all()
        )

    def get_recent(self, project_id: Any, hours: int = 24) -> List[Deployment]:
        """Get deployments from the last N hours."""
        since = datetime.utcnow() - timedelta(hours=hours)
        return (
            self.db.query(Deployment)
            .filter(
                and_(
                    Deployment.project_id == project_id,
                    Deployment.deployed_at >= since,
                )
            )
            .order_by(desc(Deployment.deployed_at))
            .all()
        )


class TicketRepository(BaseRepository[Ticket]):
    """Repository for Ticket entity."""

    def __init__(self, db: Session):
        super().__init__(db, Ticket)

    def get_by_incident(self, incident_id: Any) -> List[Ticket]:
        """Get tickets for an incident."""
        return self.db.query(Ticket).filter(Ticket.incident_id == incident_id).all()

    def get_by_external_id(self, provider: str, external_id: str) -> Optional[Ticket]:
        """Get ticket by provider and external ID."""
        return (
            self.db.query(Ticket)
            .filter(
                and_(
                    Ticket.provider == provider,
                    Ticket.external_id == external_id,
                )
            )
            .first()
        )


class MuteRepository(BaseRepository[Mute]):
    """Repository for Mute (suppression rules) entity."""

    def __init__(self, db: Session):
        super().__init__(db, Mute)

    def get_by_cluster(self, cluster_id: Any) -> Optional[Mute]:
        """Get mute rule for a cluster."""
        return self.db.query(Mute).filter(Mute.cluster_id == cluster_id).first()

    def get_active(self) -> List[Mute]:
        """Get active mutes (muted_until > now)."""
        now = datetime.utcnow()
        return (
            self.db.query(Mute)
            .filter(Mute.muted_until > now)
            .all()
        )

    def is_muted(self, cluster_id: Any) -> bool:
        """Check if a cluster is currently muted."""
        mute = self.get_by_cluster(cluster_id)
        if not mute or not mute.muted_until:
            return False
        return mute.muted_until > datetime.utcnow()


class SignalFusionMetadataRepository(BaseRepository[SignalFusionMetadata]):
    """Repository for SignalFusionMetadata entity."""

    def __init__(self, db: Session):
        super().__init__(db, SignalFusionMetadata)

    def get_by_cluster(self, cluster_id: Any) -> Optional[SignalFusionMetadata]:
        """Get signal fusion metadata for a cluster."""
        return (
            self.db.query(SignalFusionMetadata)
            .filter(SignalFusionMetadata.cluster_id == cluster_id)
            .first()
        )

    def get_high_confidence(self, threshold: float = 0.8) -> List[SignalFusionMetadata]:
        """Get signal fusion metadata with high deployment correlation."""
        return (
            self.db.query(SignalFusionMetadata)
            .filter(SignalFusionMetadata.deployment_correlation >= threshold)
            .all()
        )


class SignatureStateRepository(BaseRepository):
    """Repository for signature_states compatibility table."""

    def __init__(self, db: Session):
        from database.models import SignatureState
        super().__init__(db, SignatureState)
        self._logger = logging.getLogger(__name__)

    def get(self, signature: str) -> Optional[dict]:
        rec = self.db.query(self.model).filter(self.model.signature == signature).first()
        return rec.data if rec else None

    def upsert(self, signature: str, data: dict) -> dict:
        rec = self.db.query(self.model).filter(self.model.signature == signature).first()
        if rec:
            self._logger.info(f"SignatureStateRepository.upsert: updating signature={signature}")
            rec.data = data
            rec.updated_at = datetime.utcnow()
            self.db.commit()
            self.db.refresh(rec)
            return rec.data
        else:
            self._logger.info(f"SignatureStateRepository.upsert: inserting signature={signature}")
            inst = self.model(signature=signature, data=data)
            self.db.add(inst)
            self.db.commit()
            self.db.refresh(inst)
            return inst.data
