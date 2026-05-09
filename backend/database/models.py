"""
SQLAlchemy ORM models for Phase 2 Supabase integration.

Provides type-safe database abstraction for all DevANT entities.
"""
from datetime import datetime
from typing import Optional, Dict, Any, List
from sqlalchemy import (
    Column, String, Integer, Float, DateTime, 
    ForeignKey, JSON, Index, Text, TIMESTAMP
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from pgvector.sqlalchemy import Vector
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
import uuid

Base = declarative_base()


class Project(Base):
    """Project entity - top-level organization unit."""
    __tablename__ = "projects"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)
    github_repo = Column(String(255), nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at = Column(TIMESTAMP(timezone=True), nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    raw_events = relationship("RawEvent", back_populates="project", cascade="all, delete-orphan")
    error_clusters = relationship("ErrorCluster", back_populates="project", cascade="all, delete-orphan")
    github_events = relationship("GitHubEvent", back_populates="project", cascade="all, delete-orphan")
    deployments = relationship("Deployment", back_populates="project", cascade="all, delete-orphan")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": str(self.id),
            "name": self.name,
            "github_repo": self.github_repo,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class RawEvent(Base):
    """Raw events from external sources (Sentry, Datadog, etc.)."""
    __tablename__ = "raw_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    source_type = Column(String(50), nullable=False)  # 'sentry', 'datadog', 'azure', 'sample'
    service = Column(String(255), nullable=True)
    environment = Column(String(50), default="production")
    message = Column(Text, nullable=True)
    stack_trace = Column(Text, nullable=True)
    embedding = Column(Vector(384), nullable=True)
    cluster_id = Column(UUID(as_uuid=True), ForeignKey("error_clusters.id", ondelete="SET NULL"), nullable=True)
    fingerprint = Column(String(255), nullable=True)
    extra_metadata = Column(JSONB, default={})
    occurred_at = Column(TIMESTAMP(timezone=True), nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, default=datetime.utcnow)

    # Relationships
    project = relationship("Project", back_populates="raw_events")
    clusters = relationship(
        "ErrorCluster",
        back_populates="representative_event",
        foreign_keys="ErrorCluster.representative_event_id",
    )
    cluster = relationship("ErrorCluster", foreign_keys=[cluster_id], back_populates="events")

    __table_args__ = (
        Index("idx_raw_events_project_id", "project_id"),
        Index("idx_raw_events_fingerprint", "fingerprint"),
        Index("idx_raw_events_cluster_id", "cluster_id"),
        Index("idx_raw_events_occurred_at", "occurred_at"),
        Index("idx_raw_events_created_at", "created_at"),
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": str(self.id),
            "project_id": str(self.project_id),
            "source_type": self.source_type,
            "service": self.service,
            "environment": self.environment,
            "message": self.message,
            "stack_trace": self.stack_trace,
            "fingerprint": self.fingerprint,
            "metadata": self.metadata,
            "occurred_at": self.occurred_at.isoformat() if self.occurred_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class ErrorCluster(Base):
    """Clustered errors - grouped by root cause."""
    __tablename__ = "error_clusters"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    title = Column(String(512), nullable=False)  # Cluster signature
    representative_event_id = Column(UUID(as_uuid=True), ForeignKey("raw_events.id"), nullable=True)
    event_count = Column(Integer, default=0)
    severity = Column(String(10), nullable=True)  # 'S1', 'S2', 'S3', 'S4'
    status = Column(String(50), default="NEW")  # 'NEW', 'REGRESSION', 'ONGOING'
    confidence = Column(Float, default=0.0)
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at = Column(TIMESTAMP(timezone=True), nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    project = relationship("Project", back_populates="error_clusters")
    representative_event = relationship(
        "RawEvent",
        back_populates="clusters",
        foreign_keys=[representative_event_id],
    )
    events = relationship("RawEvent", foreign_keys="RawEvent.cluster_id", back_populates="cluster")
    embedding = relationship("ClusterEmbedding", uselist=False, back_populates="cluster", cascade="all, delete-orphan")
    incidents = relationship("Incident", back_populates="cluster", cascade="all, delete-orphan")
    mutes = relationship("Mute", back_populates="cluster", cascade="all, delete-orphan")
    signal_fusion = relationship("SignalFusionMetadata", uselist=False, back_populates="cluster", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_error_clusters_project_id", "project_id"),
        Index("idx_error_clusters_status", "status"),
        Index("idx_error_clusters_severity", "severity"),
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": str(self.id),
            "project_id": str(self.project_id),
            "title": self.title,
            "representative_event_id": str(self.representative_event_id) if self.representative_event_id else None,
            "event_count": self.event_count,
            "severity": self.severity,
            "status": self.status,
            "confidence": self.confidence,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class ClusterEmbedding(Base):
    """Vector embeddings for semantic search on error clusters."""
    __tablename__ = "cluster_embeddings"

    cluster_id = Column(UUID(as_uuid=True), ForeignKey("error_clusters.id", ondelete="CASCADE"), primary_key=True)
    embedding = Column(Vector(384), nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, default=datetime.utcnow)

    # Relationships
    cluster = relationship("ErrorCluster", back_populates="embedding")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "cluster_id": str(self.cluster_id),
            "embedding_length": len(self.embedding) if self.embedding else 0,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class Incident(Base):
    """Incident - analyzed error with root cause and recommendations."""
    __tablename__ = "incidents"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    cluster_id = Column(UUID(as_uuid=True), ForeignKey("error_clusters.id", ondelete="CASCADE"), nullable=False)
    title = Column(String(512), nullable=True)
    summary = Column(Text, nullable=True)
    root_cause = Column(Text, nullable=True)
    recommendations = Column(JSONB, default={})
    ai_confidence = Column(Float, default=0.0)
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at = Column(TIMESTAMP(timezone=True), nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    cluster = relationship("ErrorCluster", back_populates="incidents")
    alerts = relationship("Alert", back_populates="incident", cascade="all, delete-orphan")
    tickets = relationship("Ticket", back_populates="incident", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_incidents_cluster_id", "cluster_id"),
        Index("idx_incidents_created_at", "created_at"),
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": str(self.id),
            "cluster_id": str(self.cluster_id),
            "title": self.title,
            "summary": self.summary,
            "root_cause": self.root_cause,
            "recommendations": self.recommendations,
            "ai_confidence": self.ai_confidence,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class Alert(Base):
    """Alerts sent to external channels (Slack, email, etc.)."""
    __tablename__ = "alerts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    incident_id = Column(UUID(as_uuid=True), ForeignKey("incidents.id", ondelete="CASCADE"), nullable=False)
    channel = Column(String(50), nullable=False)  # 'slack', 'email', 'linear'
    status = Column(String(50), default="pending")  # 'pending', 'sent', 'failed'
    payload = Column(JSONB, default={})
    sent_at = Column(TIMESTAMP(timezone=True), nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, default=datetime.utcnow)

    # Relationships
    incident = relationship("Incident", back_populates="alerts")

    __table_args__ = (
        Index("idx_alerts_incident_id", "incident_id"),
        Index("idx_alerts_channel", "channel"),
        Index("idx_alerts_status", "status"),
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": str(self.id),
            "incident_id": str(self.incident_id),
            "channel": self.channel,
            "status": self.status,
            "payload": self.payload,
            "sent_at": self.sent_at.isoformat() if self.sent_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class GitHubEvent(Base):
    """GitHub events for deployment correlation."""
    __tablename__ = "github_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    event_type = Column(String(50), nullable=False)  # 'push', 'pull_request', 'issue'
    payload = Column(JSONB, default={})
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, default=datetime.utcnow)

    # Relationships
    project = relationship("Project", back_populates="github_events")

    __table_args__ = (
        Index("idx_github_events_project_id", "project_id"),
        Index("idx_github_events_type", "event_type"),
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": str(self.id),
            "project_id": str(self.project_id),
            "event_type": self.event_type,
            "payload": self.payload,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class Deployment(Base):
    """Deployment events for correlation analysis."""
    __tablename__ = "deployments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    provider = Column(String(50), nullable=False)  # 'vercel', 'github-actions', 'terraform'
    deployment_id = Column(String(255), nullable=False)  # External ID
    status = Column(String(50), nullable=True)  # 'success', 'failed', 'in_progress'
    extra_metadata = Column(JSONB, default={})
    deployed_at = Column(TIMESTAMP(timezone=True), nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, default=datetime.utcnow)

    # Relationships
    project = relationship("Project", back_populates="deployments")

    __table_args__ = (
        Index("idx_deployments_project_id", "project_id"),
        Index("idx_deployments_deployed_at", "deployed_at"),
        Index("idx_deployments_status", "status"),
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": str(self.id),
            "project_id": str(self.project_id),
            "provider": self.provider,
            "deployment_id": self.deployment_id,
            "status": self.status,
            "metadata": self.metadata,
            "deployed_at": self.deployed_at.isoformat() if self.deployed_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class Ticket(Base):
    """Tickets in external systems (Linear, Jira, GitHub)."""
    __tablename__ = "tickets"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    incident_id = Column(UUID(as_uuid=True), ForeignKey("incidents.id", ondelete="CASCADE"), nullable=False)
    provider = Column(String(50), nullable=False)  # 'linear', 'jira', 'github'
    external_id = Column(String(255), nullable=False)
    url = Column(String(512), nullable=True)
    status = Column(String(50), nullable=True)  # 'open', 'in_progress', 'closed'
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at = Column(TIMESTAMP(timezone=True), nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    incident = relationship("Incident", back_populates="tickets")

    __table_args__ = (
        Index("idx_tickets_incident_id", "incident_id"),
        Index("idx_tickets_provider", "provider"),
        Index("idx_tickets_provider_external_id", "provider", "external_id"),
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": str(self.id),
            "incident_id": str(self.incident_id),
            "provider": self.provider,
            "external_id": self.external_id,
            "url": self.url,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class Mute(Base):
    """Mute rules for error suppression."""
    __tablename__ = "mutes"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    cluster_id = Column(UUID(as_uuid=True), ForeignKey("error_clusters.id", ondelete="CASCADE"), nullable=False)
    reason = Column(Text, nullable=True)
    muted_by = Column(String(255), nullable=True)
    muted_until = Column(TIMESTAMP(timezone=True), nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, default=datetime.utcnow)

    # Relationships
    cluster = relationship("ErrorCluster", back_populates="mutes")

    __table_args__ = (
        Index("idx_mutes_cluster_id", "cluster_id"),
        Index("idx_mutes_until", "muted_until"),
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": str(self.id),
            "cluster_id": str(self.cluster_id),
            "reason": self.reason,
            "muted_by": self.muted_by,
            "muted_until": self.muted_until.isoformat() if self.muted_until else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class SignalFusionMetadata(Base):
    """Metadata for signal fusion and operational context."""
    __tablename__ = "signal_fusion_metadata"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    cluster_id = Column(UUID(as_uuid=True), ForeignKey("error_clusters.id", ondelete="CASCADE"), nullable=False)
    deployment_correlation = Column(Float, default=0.0)
    temporal_proximity = Column(Float, default=0.0)
    service_overlap_score = Column(Float, default=0.0)
    propagation_path = Column(Text, nullable=True)
    extra_metadata = Column(JSONB, default={})
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, default=datetime.utcnow)

    # Relationships
    cluster = relationship("ErrorCluster", back_populates="signal_fusion")

    __table_args__ = (
        Index("idx_signal_fusion_cluster", "cluster_id"),
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": str(self.id),
            "cluster_id": str(self.cluster_id),
            "deployment_correlation": self.deployment_correlation,
            "temporal_proximity": self.temporal_proximity,
            "service_overlap_score": self.service_overlap_score,
            "propagation_path": self.propagation_path,
            "metadata": self.metadata,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class SignatureState(Base):
    """Compatibility storage for signature-based JSON state."""
    __tablename__ = "signature_states"

    signature = Column(String(1024), primary_key=True)
    data = Column(JSONB, default={})
    updated_at = Column(TIMESTAMP(timezone=True), nullable=False, default=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "signature": self.signature,
            "data": self.data,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
