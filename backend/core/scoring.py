from __future__ import annotations

from typing import Dict, Iterable, Optional

from .normalization import normalize_signature

SEVERITY_PRIORITY = {"S1": 1, "S2": 2, "S3": 3, "S4": 4}
OPERATIONAL_SEVERITY_PRIORITY = {"outage-risk": 1, "critical": 2, "degraded": 3, "informational": 4}
SEVERITY_EMOJI = {
    "S1": ":red_circle:",
    "S2": ":large_orange_circle:",
    "S3": ":large_yellow_circle:",
    "S4": ":large_blue_circle:",
}


def severity_priority(severity: str, default: int = 3) -> int:
    return SEVERITY_PRIORITY.get(str(severity).upper(), default)


def severity_emoji(severity: str) -> str:
    return SEVERITY_EMOJI.get(str(severity).upper(), ":white_circle:")


def assess_operational_severity(
    production_impact: float = 0.0,
    service_criticality: float = 0.0,
    deployment_scope: float = 0.0,
    recurrence_frequency: float = 0.0,
    blast_radius: float = 0.0,
    workflow_criticality: float = 0.0,
    historical_patterns: float = 0.0,
) -> Dict[str, object]:
    score = (
        production_impact * 0.22
        + service_criticality * 0.18
        + deployment_scope * 0.14
        + recurrence_frequency * 0.14
        + blast_radius * 0.14
        + workflow_criticality * 0.10
        + historical_patterns * 0.08
    )

    if production_impact >= 0.85 or blast_radius >= 0.85 or score >= 0.82:
        severity = "outage-risk"
        reasoning = "Multiple high-impact operational signals indicate outage risk"
    elif production_impact >= 0.55 or blast_radius >= 0.55 or score >= 0.58:
        severity = "critical"
        reasoning = "Operational impact is severe enough to require immediate attention"
    elif production_impact >= 0.25 or recurrence_frequency >= 0.35 or score >= 0.32:
        severity = "degraded"
        reasoning = "System is degraded or trending toward instability"
    else:
        severity = "informational"
        reasoning = "No material operational impact detected"

    legacy_map = {
        "outage-risk": "S1",
        "critical": "S2",
        "degraded": "S3",
        "informational": "S4",
    }

    return {
        "severity": severity,
        "legacy_severity": legacy_map[severity],
        "score": max(0.0, min(1.0, float(score))),
        "reasoning": reasoning,
    }


def combine_evidence_score(
    semantic_score: float = 0.0,
    stacktrace_score: float = 0.0,
    deployment_score: float = 0.0,
    keyword_score: float = 0.0,
    owner_match: bool = False,
    commit_match: bool = False,
) -> float:
    score = (
        semantic_score * 0.35
        + stacktrace_score * 0.30
        + deployment_score * 0.15
        + keyword_score * 0.10
        + (0.1 if owner_match else 0.0)
        + (0.2 if commit_match else 0.0)
    )
    return max(0.0, min(1.0, float(score)))


def infer_severity(
    signature: str,
    error_count: int = 1,
    affected_orgs: Optional[Iterable[str]] = None,
    modules: Optional[Iterable[str]] = None,
) -> Dict[str, str]:
    normalized = normalize_signature(signature)
    affected_orgs = list(affected_orgs or [])
    modules = list(modules or [])

    operational = assess_operational_severity(
        production_impact=min(1.0, error_count / 25.0),
        service_criticality=0.4 if affected_orgs else 0.1,
        deployment_scope=0.3 if modules else 0.1,
        recurrence_frequency=min(1.0, error_count / 15.0),
        blast_radius=min(1.0, len(affected_orgs) / 5.0),
        workflow_criticality=0.2 if any(word in normalized for word in ["deploy", "build", "release", "workflow"]) else 0.0,
        historical_patterns=0.2 if any(word in normalized for word in ["regression", "recurring", "reopened"]) else 0.0,
    )

    if any(word in normalized for word in ["500", "502", "503", "outage", "down"]):
        severity = "S2"
        title = "Service errors indicating degradation"
        root_cause = "Server error indicating service degradation"
    elif any(word in normalized for word in ["401", "403", "auth", "unauthorized"]):
        severity = "S3"
        if any(word in normalized for word in ["oauth", "token", "refresh"]):
            title = "OAuth tokens expired - users need to reconnect"
        else:
            title = "Authentication failures with external service"
        root_cause = "Authentication or authorization failure"
    elif any(word in normalized for word in ["429", "rate limit", "throttl"]):
        severity = "S3"
        if "google" in normalized or "drive" in normalized:
            title = "Google Drive API rate limits exceeded"
        elif "dropbox" in normalized:
            title = "Dropbox API rate limits exceeded"
        elif "slack" in normalized:
            title = "Slack API rate limits exceeded"
        else:
            title = "External API rate limiting errors"
        root_cause = "Rate limiting from external service"
    elif any(word in normalized for word in ["timeout", "connection"]):
        severity = "S3" if error_count > 5 else "S4"
        if any(word in normalized for word in ["database", "postgres", "pool"]):
            title = "Database connection issues"
        else:
            title = "Network connectivity issues"
        root_cause = "Network or connection issues"
    elif any(word in normalized for word in ["pool", "exhaust"]):
        severity = "S3"
        title = "Database connection pool exhausted"
        root_cause = "Connection pool exhausted under load"
    elif any(word in normalized for word in ["memory", "oom"]):
        severity = "S2"
        title = "Worker memory limit exceeded"
        root_cause = "Out of memory during processing"
    elif any(word in normalized for word in ["pdf", "corrupt", "parse"]):
        severity = "S4"
        title = "Document processing failures"
        root_cause = "Unable to process corrupted or malformed files"
    else:
        severity = "S4"
        title = f"Errors in {modules[0] if modules else 'application'}"
        root_cause = "Unknown error - requires investigation"

    if len(affected_orgs) > 3 and severity in ["S3", "S4"]:
        severity = "S2" if severity == "S3" else "S3"

    return {
        "severity": severity,
        "operational_severity": operational["severity"],
        "operational_score": operational["score"],
        "operational_reasoning": operational["reasoning"],
        "legacy_severity": severity,
        "title": title,
        "root_cause": root_cause,
    }