"""
SQLAlchemy ORM models for Phase 2 Supabase integration.

Provides type-safe database abstraction for all DevANT entities.
"""
from datetime import datetime
from typing import Optional, Dict, Any, List
import sqlalchemy as sa
from sqlalchemy import (
    Column, String, Integer, Float, DateTime, Boolean,
    ForeignKey, JSON, Index, Text, TIMESTAMP
)
from .pgvector_compat import Vector, JSONB, UUID
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
    extra_metadata = Column(JSONB(), default={})
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
    recommendations = Column(JSONB(), default={})
    ai_confidence = Column(Float, default=0.0)
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at = Column(TIMESTAMP(timezone=True), nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    cluster = relationship("ErrorCluster", back_populates="incidents")
    alerts = relationship("Alert", back_populates="incident", cascade="all, delete-orphan")
    tickets = relationship("Ticket", back_populates="incident", cascade="all, delete-orphan")
    commit_correlations = relationship("IncidentCommitCorrelation", back_populates="incident", cascade="all, delete-orphan")
    deployment_correlations = relationship("IncidentDeploymentCorrelation", back_populates="incident", cascade="all, delete-orphan")

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
    payload = Column(JSONB(), default={})
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
    payload = Column(JSONB(), default={})
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
    extra_metadata = Column(JSONB(), default={})
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


class GitHubRepository(Base):
    """GitHub repository metadata."""
    __tablename__ = "github_repositories"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    owner = Column(String(255), nullable=False)
    name = Column(String(255), nullable=False)
    full_name = Column(String(512), nullable=False, unique=True)
    url = Column(String(512), nullable=True)
    default_branch = Column(String(255), nullable=True)
    description = Column(Text, nullable=True)
    extra_metadata = Column(JSONB(), default={})
    synced_at = Column(TIMESTAMP(timezone=True), nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at = Column(TIMESTAMP(timezone=True), nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    project = relationship("Project", backref="github_repositories")
    commits = relationship("GitHubCommit", back_populates="repository", cascade="all, delete-orphan")
    pull_requests = relationship("GitHubPullRequest", back_populates="repository", cascade="all, delete-orphan")
    deployments = relationship("GitHubDeployment", back_populates="repository", cascade="all, delete-orphan")
    workflows = relationship("GitHubWorkflow", back_populates="repository", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_github_repositories_project_id", "project_id"),
        Index("idx_github_repositories_full_name", "full_name"),
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": str(self.id),
            "project_id": str(self.project_id),
            "owner": self.owner,
            "name": self.name,
            "full_name": self.full_name,
            "url": self.url,
            "default_branch": self.default_branch,
            "description": self.description,
            "extra_metadata": self.extra_metadata,
            "synced_at": self.synced_at.isoformat() if self.synced_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class GitHubCommit(Base):
    """GitHub commits."""
    __tablename__ = "github_commits"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    repository_id = Column(UUID(as_uuid=True), ForeignKey("github_repositories.id", ondelete="CASCADE"), nullable=False)
    sha = Column(String(40), nullable=False)  # Git commit SHA
    author = Column(String(255), nullable=True)
    message = Column(Text, nullable=True)
    files_changed = Column(Integer, nullable=True)
    additions = Column(Integer, nullable=True)
    deletions = Column(Integer, nullable=True)
    url = Column(String(512), nullable=True)
    committed_at = Column(TIMESTAMP(timezone=True), nullable=True)
    changed_files = Column(JSONB(), default=list)
    extra_metadata = Column(JSONB(), default={})
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, default=datetime.utcnow)

    # Relationships
    repository = relationship("GitHubRepository", back_populates="commits")

    __table_args__ = (
        Index("idx_github_commits_repository_id", "repository_id"),
        Index("idx_github_commits_sha", "sha"),
        Index("idx_github_commits_committed_at", "committed_at"),
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": str(self.id),
            "repository_id": str(self.repository_id),
            "sha": self.sha,
            "author": self.author,
            "message": self.message,
            "files_changed": self.files_changed,
            "additions": self.additions,
            "deletions": self.deletions,
            "url": self.url,
            "committed_at": self.committed_at.isoformat() if self.committed_at else None,
            "changed_files": self.changed_files,
            "extra_metadata": self.extra_metadata,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class GitHubPullRequest(Base):
    """GitHub pull requests."""
    __tablename__ = "github_pull_requests"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    repository_id = Column(UUID(as_uuid=True), ForeignKey("github_repositories.id", ondelete="CASCADE"), nullable=False)
    number = Column(Integer, nullable=False)
    title = Column(String(512), nullable=True)
    author = Column(String(255), nullable=True)
    state = Column(String(50), nullable=True)  # 'open', 'closed'
    merged = Column(Boolean, default=False)
    merged_at = Column(TIMESTAMP(timezone=True), nullable=True)
    created_at_gh = Column(TIMESTAMP(timezone=True), nullable=True)
    updated_at_gh = Column(TIMESTAMP(timezone=True), nullable=True)
    closed_at = Column(TIMESTAMP(timezone=True), nullable=True)
    url = Column(String(512), nullable=True)
    files_changed = Column(Integer, nullable=True)
    additions = Column(Integer, nullable=True)
    deletions = Column(Integer, nullable=True)
    extra_metadata = Column(JSONB(), default={})
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, default=datetime.utcnow)

    # Relationships
    repository = relationship("GitHubRepository", back_populates="pull_requests")

    __table_args__ = (
        Index("idx_github_pull_requests_repository_id", "repository_id"),
        Index("idx_github_pull_requests_number", "number"),
        Index("idx_github_pull_requests_merged_at", "merged_at"),
        Index("idx_github_pull_requests_state", "state"),
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": str(self.id),
            "repository_id": str(self.repository_id),
            "number": self.number,
            "title": self.title,
            "author": self.author,
            "state": self.state,
            "merged": self.merged,
            "merged_at": self.merged_at.isoformat() if self.merged_at else None,
            "created_at_gh": self.created_at_gh.isoformat() if self.created_at_gh else None,
            "updated_at_gh": self.updated_at_gh.isoformat() if self.updated_at_gh else None,
            "closed_at": self.closed_at.isoformat() if self.closed_at else None,
            "url": self.url,
            "files_changed": self.files_changed,
            "additions": self.additions,
            "deletions": self.deletions,
            "extra_metadata": self.extra_metadata,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class GitHubDeployment(Base):
    """GitHub deployments."""
    __tablename__ = "github_deployments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    repository_id = Column(UUID(as_uuid=True), ForeignKey("github_repositories.id", ondelete="CASCADE"), nullable=False)
    deployment_id = Column(String(255), nullable=False)  # GitHub deployment ID
    ref = Column(String(255), nullable=True)
    sha = Column(String(40), nullable=True)
    environment = Column(String(255), nullable=True)  # e.g., 'production', 'staging'
    status = Column(String(50), nullable=True)  # 'pending', 'success', 'failure'
    url = Column(String(512), nullable=True)
    creator = Column(String(255), nullable=True)
    deployed_at = Column(TIMESTAMP(timezone=True), nullable=True)
    extra_metadata = Column(JSONB(), default={})
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, default=datetime.utcnow)

    # Relationships
    repository = relationship("GitHubRepository", back_populates="deployments")

    __table_args__ = (
        Index("idx_github_deployments_repository_id", "repository_id"),
        Index("idx_github_deployments_deployment_id", "deployment_id"),
        Index("idx_github_deployments_environment", "environment"),
        Index("idx_github_deployments_deployed_at", "deployed_at"),
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": str(self.id),
            "repository_id": str(self.repository_id),
            "deployment_id": self.deployment_id,
            "ref": self.ref,
            "sha": self.sha,
            "environment": self.environment,
            "status": self.status,
            "url": self.url,
            "creator": self.creator,
            "deployed_at": self.deployed_at.isoformat() if self.deployed_at else None,
            "extra_metadata": self.extra_metadata,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class GitHubWorkflow(Base):
    """GitHub workflow runs."""
    __tablename__ = "github_workflows"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    repository_id = Column(UUID(as_uuid=True), ForeignKey("github_repositories.id", ondelete="CASCADE"), nullable=False)
    workflow_id = Column(String(255), nullable=False)  # GitHub workflow run ID
    name = Column(String(512), nullable=True)
    status = Column(String(50), nullable=True)  # 'queued', 'in_progress', 'completed'
    conclusion = Column(String(50), nullable=True)  # 'success', 'failure', 'neutral', etc.
    ref = Column(String(255), nullable=True)
    sha = Column(String(40), nullable=True)
    actor = Column(String(255), nullable=True)
    started_at = Column(TIMESTAMP(timezone=True), nullable=True)
    completed_at = Column(TIMESTAMP(timezone=True), nullable=True)
    url = Column(String(512), nullable=True)
    extra_metadata = Column(JSONB(), default={})
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, default=datetime.utcnow)

    # Relationships
    repository = relationship("GitHubRepository", back_populates="workflows")

    __table_args__ = (
        Index("idx_github_workflows_repository_id", "repository_id"),
        Index("idx_github_workflows_workflow_id", "workflow_id"),
        Index("idx_github_workflows_status", "status"),
        Index("idx_github_workflows_completed_at", "completed_at"),
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": str(self.id),
            "repository_id": str(self.repository_id),
            "workflow_id": self.workflow_id,
            "name": self.name,
            "status": self.status,
            "conclusion": self.conclusion,
            "ref": self.ref,
            "sha": self.sha,
            "actor": self.actor,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "url": self.url,
            "extra_metadata": self.extra_metadata,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class IncidentCommitCorrelation(Base):
    """Correlation result between incident and suspect GitHub commits."""
    __tablename__ = "incident_commit_correlations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    incident_id = Column(UUID(as_uuid=True), ForeignKey("incidents.id", ondelete="CASCADE"), nullable=False)
    cluster_id = Column(UUID(as_uuid=True), ForeignKey("error_clusters.id", ondelete="CASCADE"), nullable=True)
    representative_event_id = Column(UUID(as_uuid=True), ForeignKey("raw_events.id", ondelete="SET NULL"), nullable=True)
    repository_id = Column(UUID(as_uuid=True), ForeignKey("github_repositories.id", ondelete="SET NULL"), nullable=True)
    suspect_commits = Column(JSONB(), default=list)
    likely_changed_files = Column(JSONB(), default=list)
    confidence_score = Column(Float, default=0.0)
    service_match_score = Column(Float, default=0.0)
    deployment_timing_score = Column(Float, default=0.0)
    file_match_score = Column(Float, default=0.0)
    notes = Column(Text, nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, default=datetime.utcnow)

    incident = relationship("Incident", back_populates="commit_correlations")

    __table_args__ = (
        Index("idx_incident_commit_correlations_incident_id", "incident_id"),
        Index("idx_incident_commit_correlations_cluster_id", "cluster_id"),
        Index("idx_incident_commit_correlations_repository_id", "repository_id"),
        Index("idx_incident_commit_correlations_confidence", "confidence_score"),
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": str(self.id),
            "incident_id": str(self.incident_id),
            "cluster_id": str(self.cluster_id) if self.cluster_id else None,
            "representative_event_id": str(self.representative_event_id) if self.representative_event_id else None,
            "repository_id": str(self.repository_id) if self.repository_id else None,
            "suspect_commits": self.suspect_commits,
            "likely_changed_files": self.likely_changed_files,
            "confidence_score": self.confidence_score,
            "service_match_score": self.service_match_score,
            "deployment_timing_score": self.deployment_timing_score,
            "file_match_score": self.file_match_score,
            "notes": self.notes,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class IncidentDeploymentCorrelation(Base):
    """Correlation result between incident and suspect deployments."""
    __tablename__ = "incident_deployment_correlations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    incident_id = Column(UUID(as_uuid=True), ForeignKey("incidents.id", ondelete="CASCADE"), nullable=False)
    cluster_id = Column(UUID(as_uuid=True), ForeignKey("error_clusters.id", ondelete="CASCADE"), nullable=True)
    representative_event_id = Column(UUID(as_uuid=True), ForeignKey("raw_events.id", ondelete="SET NULL"), nullable=True)
    suspect_deployments = Column(JSONB(), default=list)
    confidence_score = Column(Float, default=0.0)
    temporal_proximity_score = Column(Float, default=0.0)
    service_match_score = Column(Float, default=0.0)
    provider_match_score = Column(Float, default=0.0)
    notes = Column(Text, nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, default=datetime.utcnow)

    # Relationships
    incident = relationship("Incident", back_populates="deployment_correlations")

    __table_args__ = (
        Index("idx_incident_deployment_correlations_incident_id", "incident_id"),
        Index("idx_incident_deployment_correlations_cluster_id", "cluster_id"),
        Index("idx_incident_deployment_correlations_confidence", "confidence_score"),
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": str(self.id),
            "incident_id": str(self.incident_id),
            "cluster_id": str(self.cluster_id) if self.cluster_id else None,
            "representative_event_id": str(self.representative_event_id) if self.representative_event_id else None,
            "suspect_deployments": self.suspect_deployments,
            "confidence_score": self.confidence_score,
            "temporal_proximity_score": self.temporal_proximity_score,
            "service_match_score": self.service_match_score,
            "provider_match_score": self.provider_match_score,
            "notes": self.notes,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class SignalFusionMetadata(Base):
    """Signal fusion metadata for cluster analysis."""
    __tablename__ = "signal_fusion_metadata"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    cluster_id = Column(UUID(as_uuid=True), ForeignKey("error_clusters.id", ondelete="CASCADE"), nullable=False)
    deployment_correlation = Column(Float, default=0.0)
    temporal_proximity = Column(Float, default=0.0)
    service_overlap_score = Column(Float, default=0.0)
    propagation_path = Column(Text, nullable=True)
    extra_metadata = Column(JSONB(), default={})
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
            "extra_metadata": self.extra_metadata,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


