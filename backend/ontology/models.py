from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class OperationalEntity(BaseModel):
    """Base metadata required for every operational object."""

    source_of_truth: str = Field(description="Canonical source that owns this object")
    timestamp: datetime = Field(description="Timestamp associated with the object")
    confidence_origin: str = Field(description="Where the confidence value came from")
    evidence_origin: List[str] = Field(default_factory=list, description="Evidence references used to derive this object")
    persistence_rules: Dict[str, Any] = Field(
        default_factory=lambda: {
            "retention": "indefinite",
            "mutability": "append-only",
            "rewrite_policy": "source-driven",
        },
        description="Rules that govern persistence and mutation",
    )

    model_config = ConfigDict(extra="allow")


class Incident(OperationalEntity):
    incident_id: str = Field(description="Stable incident identifier")
    signature: str = Field(description="Operational signature for the incident")
    service: str = Field(description="Owning service")
    severity: Optional[str] = Field(default=None, description="Current severity")
    status: Optional[Literal["NEW", "REGRESSION", "ONGOING", "RESOLVED"]] = Field(default=None, description="Operational status")
    summary: Optional[str] = Field(default=None, description="Short incident summary")
    root_cause: Optional[str] = Field(default=None, description="Likely root cause")
    deployment_id: Optional[str] = Field(default=None, description="Related deployment identifier")
    commit_hash: Optional[str] = Field(default=None, description="Related commit hash")
    owner: Optional[str] = Field(default=None, description="Owning team or person")
    affected_orgs: List[str] = Field(default_factory=list, description="Affected organizations")


class Deployment(OperationalEntity):
    deployment_id: str = Field(description="Deployment identifier")
    service: str = Field(description="Deployed service")
    environment: str = Field(description="Deployment environment")
    status: str = Field(description="Deployment state")
    commit_hash: Optional[str] = Field(default=None, description="Commit deployed")
    workflow_name: Optional[str] = Field(default=None, description="Deployment workflow name")
    rollback_of: Optional[str] = Field(default=None, description="Deployment rolled back from")
    actor: Optional[str] = Field(default=None, description="Deployer or triggering actor")
    url: Optional[str] = Field(default=None, description="Deployment URL")


class Regression(OperationalEntity):
    regression_id: str = Field(description="Regression identifier")
    incident_id: str = Field(description="Incident being treated as a regression")
    prior_incident_id: Optional[str] = Field(default=None, description="Previously resolved incident")
    reopened_ticket_id: Optional[str] = Field(default=None, description="Reopened ticket identifier")
    recurrence_count: int = Field(default=1, description="Number of times the regression has reoccurred")
    time_since_resolution_minutes: Optional[float] = Field(default=None, description="Minutes since the prior resolution")


class Evidence(OperationalEntity):
    evidence_id: str = Field(description="Evidence identifier")
    kind: Literal["code", "ticket", "log", "metric", "deployment", "document", "other"] = Field(description="Evidence kind")
    title: str = Field(description="Short evidence title")
    content: str = Field(description="Grounded evidence content")
    score: float = Field(description="Relevance or confidence score")
    url: Optional[str] = Field(default=None, description="Source URL")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Evidence metadata")


class MetricAnomaly(OperationalEntity):
    anomaly_id: str = Field(description="Metric anomaly identifier")
    metric_name: str = Field(description="Observed metric name")
    value: float = Field(description="Observed value")
    baseline: float = Field(description="Baseline value")
    deviation: float = Field(description="Absolute or normalized deviation")
    direction: Literal["up", "down", "flat"] = Field(description="Direction of change")
    window_minutes: int = Field(description="Time window used for detection")
    service: Optional[str] = Field(default=None, description="Service associated with the anomaly")


class ServiceDependency(OperationalEntity):
    dependency_id: str = Field(description="Dependency identifier")
    service: str = Field(description="Dependent service")
    depends_on: str = Field(description="Upstream dependency")
    relationship: str = Field(description="Relationship description")
    strength: float = Field(description="Dependency strength or confidence")
    criticality: Optional[str] = Field(default=None, description="Criticality of the dependency")


class PropagationEvent(OperationalEntity):
    event_id: str = Field(description="Propagation event identifier")
    source_service: str = Field(description="Source of the propagation")
    target_service: str = Field(description="Downstream impacted service")
    mechanism: str = Field(description="Propagation mechanism")
    severity: str = Field(description="Severity of the propagation")
    latency_ms: Optional[int] = Field(default=None, description="Propagation latency in milliseconds")
    impact_summary: Optional[str] = Field(default=None, description="Brief impact summary")


class RCAHypothesis(OperationalEntity):
    hypothesis_id: str = Field(description="Hypothesis identifier")
    incident_id: str = Field(description="Incident this hypothesis explains")
    hypothesis: str = Field(description="Root cause hypothesis")
    likelihood: float = Field(description="Likelihood of the hypothesis")
    supporting_evidence_ids: List[str] = Field(default_factory=list, description="Evidence supporting the hypothesis")
    counter_evidence_ids: List[str] = Field(default_factory=list, description="Evidence that contradicts the hypothesis")
    conclusion: Optional[str] = Field(default=None, description="Final conclusion if established")