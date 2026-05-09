"""
Pydantic schemas for the error monitoring pipeline.

Provides strongly-typed data contracts for all stages of error processing.
These schemas ensure type safety and clear data flow through the pipeline.
"""
from datetime import datetime
from typing import Optional, List, Dict, Any, Literal
from pydantic import BaseModel, Field, ConfigDict, model_validator


# ============================================================================
# Raw Data from External Sources
# ============================================================================

class RawError(BaseModel):
    """
    Normalized error format from any data source.
    
    All data sources (sample, Sentry, Azure, etc.) convert their native
    format to this common structure for pipeline processing.
    """
    # Identity
    id: str = Field(description="Unique error ID from source")
    timestamp: datetime = Field(description="When the error occurred")
    
    # Error details
    level: str = Field(description="Log level: ERROR, WARNING, CRITICAL, etc.")
    message: str = Field(description="Error message")
    
    # Location
    module: Optional[str] = Field(default=None, description="Module/file name")
    function: Optional[str] = Field(default=None, description="Function/method name")
    line: Optional[int] = Field(default=None, description="Line number")
    
    # Context
    container: Optional[str] = Field(default=None, description="Container/service name")
    environment: Optional[str] = Field(default="production", description="Environment")
    
    # Organization context (multi-tenant)
    org_id: Optional[str] = Field(default=None, description="Organization ID")
    org_name: Optional[str] = Field(default=None, description="Organization name")
    user_id: Optional[str] = Field(default=None, description="User ID if applicable")
    
    # Stack trace
    stack_trace: Optional[str] = Field(default=None, description="Full stack trace")
    
    # Source tracking
    source_type: str = Field(default="unknown", description="Source: sample, azure, sentry, etc.")
    source_url: Optional[str] = Field(default=None, description="Deep link to error in source")
    
    # Additional metadata
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Source-specific metadata")
    
    model_config = ConfigDict(extra='allow')


# ============================================================================
# Clustering Stage
# ============================================================================

class ErrorCluster(BaseModel):
    """
    Clustered error with aggregated data from multiple occurrences.
    
    Created after semantic clustering groups similar errors together.
    """
    # Identity
    signature: str = Field(description="Natural language signature describing the error pattern")
    
    # Aggregated metrics
    error_count: int = Field(description="Number of errors in this cluster")
    affected_orgs: List[str] = Field(default_factory=list, description="List of org names affected")
    org_count: int = Field(description="Number of unique organizations affected")
    
    # Representative data
    sample_messages: List[str] = Field(default_factory=list, description="Sample error messages (up to 5)")
    modules: List[str] = Field(default_factory=list, description="Modules involved")
    
    # Primary error location
    module: Optional[str] = Field(default=None, description="Primary module")
    function: Optional[str] = Field(default=None, description="Primary function")
    container: Optional[str] = Field(default=None, description="Primary container")
    error_type: Optional[str] = Field(default=None, description="Extracted error type")
    
    # Clustering metadata
    merged_count: Optional[int] = Field(default=None, description="Number of sub-clusters merged")
    original_signatures: Optional[List[str]] = Field(default=None, description="Original signatures if merged")
    
    # Raw errors (kept for reference)
    errors: List[Dict[str, Any]] = Field(default_factory=list, description="Original error data")


# ============================================================================
# State from JSON Storage
# ============================================================================

class PreviousErrorState(BaseModel):
    """
    Previous state of an error signature from JSON storage.
    
    Used for determining status (NEW, REGRESSION, ONGOING) and suppression.
    """
    # Accept either `signature` or historical `error_id` values for compatibility
    signature: Optional[str] = Field(default=None, description="The error signature")
    error_id: Optional[str] = Field(default=None, description="Backward-compatible error_id")
    model_config = ConfigDict(extra='allow')

    @model_validator(mode="after")
    def _coerce_signature(cls, values):
        # Prefer explicit signature, fall back to error_id if provided
        if not values.signature and values.error_id:
            values.signature = values.error_id
        return values
    
    # History
    first_seen: Optional[datetime] = Field(default=None, description="When first seen")
    last_seen: Optional[datetime] = Field(default=None, description="When last seen")
    last_alerted: Optional[datetime] = Field(default=None, description="When we last sent an alert")
    times_seen: int = Field(default=0, description="Total occurrences")
    
    # Linear ticket tracking
    linear_issue_id: Optional[str] = Field(default=None, description="Linked Linear ticket ID")
    linear_issue_status: Optional[str] = Field(default=None, description="Last known ticket status")
    linear_issue_url: Optional[str] = Field(default=None, description="Linear ticket URL")
    
    # Slack tracking
    slack_thread_ts: Optional[str] = Field(default=None, description="Slack thread timestamp")
    
    # Muting
    muted_until: Optional[datetime] = Field(default=None, description="Muted until this time")
    muted_by: Optional[str] = Field(default=None, description="Who muted this error")
    mute_reason: Optional[str] = Field(default=None, description="Why it was muted")
    
    # Last analysis summary
    last_severity: Optional[str] = Field(default=None, description="Last assessed severity")
    last_summary: Optional[Dict[str, Any]] = Field(default=None, description="Last analysis summary")


# ============================================================================
# Enrichment Stage
# ============================================================================

class CodeSnippet(BaseModel):
    """Code snippet from Airweave search."""
    title: str = Field(description="File path or title")
    content: str = Field(description="Code content")
    source: str = Field(default="github", description="Source: github, etc.")
    url: Optional[str] = Field(default=None, description="Link to file")
    score: float = Field(default=0.0, description="Relevance score")


class RelatedTicket(BaseModel):
    """Related ticket from Airweave search."""
    title: str = Field(description="Ticket title")
    content: str = Field(description="Ticket description/content")
    source: str = Field(default="linear", description="Source: linear, jira, etc.")
    url: Optional[str] = Field(default=None, description="Link to ticket")
    status: Optional[str] = Field(default=None, description="Ticket status if known")
    score: float = Field(default=0.0, description="Relevance score")


class EnrichedError(ErrorCluster):
    """
    Error cluster enriched with context from Airweave and state.
    
    Contains everything needed for analysis and action.
    """
    # Previous state
    previous_state: PreviousErrorState = Field(description="History from state storage")
    
    # Context from Airweave
    code_snippets: List[Dict[str, Any]] = Field(default_factory=list, description="Related code")
    related_tickets: List[Dict[str, Any]] = Field(default_factory=list, description="Related tickets")
    documentation: List[Dict[str, Any]] = Field(default_factory=list, description="Related docs")
    
    # Comprehensive summary (single source of truth)
    comprehensive_summary: Optional[str] = Field(default=None, description="LLM-generated summary")


# ============================================================================
# Analysis Stage
# ============================================================================

class AnalyzedError(EnrichedError):
    """
    Error after analysis with severity, status, and action determination.
    """
    # Status determination
    status: Literal["NEW", "REGRESSION", "ONGOING"] = Field(description="Error status")
    
    # Severity assessment
    severity: str = Field(description="Severity: S1, S2, S3, S4")
    severity_reasoning: Optional[str] = Field(default=None, description="Why this severity")
    is_critical: bool = Field(default=False, description="Requires immediate attention")
    
    # Root cause analysis
    root_cause: Optional[str] = Field(default=None, description="Likely root cause")
    impact: Optional[str] = Field(default=None, description="Impact description")
    suggested_action: Optional[str] = Field(default=None, description="Recommended action")
    
    # Ticket matching
    matched_ticket: Optional[Dict[str, Any]] = Field(default=None, description="Matched existing ticket")
    has_relevant_ticket: bool = Field(default=False, description="Found a relevant ticket")
    
    # Suppression
    is_muted: bool = Field(default=False, description="Error is muted")
    should_alert: bool = Field(default=True, description="Should we send an alert")
    suppression_reason: Optional[str] = Field(default=None, description="Why suppressed")


# ============================================================================
# Action Results
# ============================================================================

class LinearTicketResult(BaseModel):
    """Result of Linear ticket action."""
    id: str = Field(description="Ticket ID")
    identifier: str = Field(description="Ticket identifier (e.g., ENG-1234)")
    title: str = Field(description="Ticket title")
    url: str = Field(description="Ticket URL")
    status: str = Field(description="Ticket status")
    action: Literal["created", "updated", "commented", "reopened", "found", "none"] = Field(
        description="Action taken"
    )
    is_preview: bool = Field(default=False, description="Preview mode (not actually created)")


class SlackMessageResult(BaseModel):
    """Result of Slack message action."""
    channel: str = Field(description="Channel ID or name")
    thread_ts: Optional[str] = Field(default=None, description="Thread timestamp")
    message_ts: Optional[str] = Field(default=None, description="Message timestamp")
    action: Literal["posted", "replied", "none"] = Field(description="Action taken")
    is_preview: bool = Field(default=False, description="Preview mode (not actually posted)")


class ErrorResult(AnalyzedError):
    """
    Final result after all actions have been executed.
    """
    # Linear results
    linear_ticket: Optional[LinearTicketResult] = Field(default=None, description="Linear action result")
    
    # Slack results
    slack_message: Optional[SlackMessageResult] = Field(default=None, description="Slack action result")
    
    # Actions taken
    actions_taken: List[str] = Field(default_factory=list, description="List of actions performed")


# ============================================================================
# Pipeline Results
# ============================================================================

class PipelineResult(BaseModel):
    """Summary of pipeline execution."""
    run_id: str = Field(description="Unique run identifier")
    started_at: datetime = Field(description="When pipeline started")
    completed_at: Optional[datetime] = Field(default=None, description="When pipeline completed")
    
    # Counts
    total_errors: int = Field(default=0, description="Total errors processed")
    clusters_created: int = Field(default=0, description="Clusters after grouping")
    alerts_sent: int = Field(default=0, description="Alerts actually sent")
    suppressed: int = Field(default=0, description="Errors suppressed")
    
    # Results
    results: List[ErrorResult] = Field(default_factory=list, description="Per-cluster results")
    
    # Status
    status: Literal["running", "completed", "error"] = Field(default="running")
    error_message: Optional[str] = Field(default=None, description="Error if failed")


# ---------------------------------------------------------------------------
# Compatibility shim for tests: ErrorAnalysis
# ---------------------------------------------------------------------------
class ErrorAnalysis(BaseModel):
    """Lightweight compatibility model used by tests.

    This is intentionally minimal and only exists to satisfy test imports.
    """
    severity: str = "medium"
    summary: str = ""
    root_cause: Optional[str] = None
    confidence: float = 0.0
    evidence: List[str] = []
