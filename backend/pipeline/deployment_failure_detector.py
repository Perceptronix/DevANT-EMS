"""
Deployment Failure Detector — GitHub-native error detection pipeline.

Detects production failures by reading GitHub Deployments API and commit diffs.
No access to Vercel/Netlify/Render dashboards required — GitHub is the single
source of truth because all hosting platforms report back to GitHub.

Flow:
  1. Fetch recent deployments for the repo + environment
  2. Check statuses of each deployment — find failures
  3. For each failure: get the commit diff (what changed)
  4. Fetch build log if log_url is accessible
  5. Parse log text into structured error events
  6. Cluster errors by root cause
  7. Return structured result for the alert pipeline
"""
from __future__ import annotations

import logging
import re
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

from connectors.github_connector import GitHubConnector
from core.root_cause_clusterer import RootCauseClusterer

logger = logging.getLogger(__name__)


def detect_deployment_failures(
    repo_url: str,
    environment: str = "production",
    since_hours: int = 24,
    max_deployments: int = 10,
) -> Dict[str, Any]:
    """
    Main entry point: detect deployment failures for a repo/environment.
    
    Returns structured result with deployments, failures, and error clusters.
    """
    # Step 1: Fetch deployments
    connector = GitHubConnector()
    if not connector.is_configured:
        logger.warning("GitHubConnector not configured (no GITHUB_TOKEN)")
        return {
            "error": "GITHUB_TOKEN not configured",
            "deployments": [],
            "failures": [],
            "clusters": [],
        }
    
    deployments = connector.get_deployments(
        repo_url, environment=environment, per_page=max_deployments
    )
    
    if not deployments:
        logger.info(f"No deployments found for {repo_url} in {environment}")
        return {
            "repo": repo_url,
            "environment": environment,
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "total_deployments_checked": 0,
            "failed_deployments": [],
            "clusters": [],
            "has_failures": False,
            "summary": "No deployments found.",
        }
    
    # Filter to deployments created within since_hours
    cutoff = datetime.now(timezone.utc) - timedelta(hours=since_hours)
    recent_deployments = []
    for d in deployments:
        try:
            created_dt = datetime.fromisoformat(
                d.get("created_at", "").replace("Z", "+00:00")
            )
            if created_dt >= cutoff:
                recent_deployments.append(d)
        except Exception:
            pass
    
    logger.info(
        f"Found {len(recent_deployments)} deployments in last {since_hours}h for {repo_url}"
    )
    
    # Step 2: Find failed deployments
    failed_deployments = []
    for deployment in recent_deployments:
        statuses = connector.get_deployment_statuses(repo_url, deployment["id"])
        if not statuses:
            continue
        
        # Latest status is first in the list
        latest_status = statuses[0]
        state = latest_status.get("state", "")
        
        if state in ("failure", "error"):
            failed_deployments.append({
                "deployment": deployment,
                "latest_status": latest_status,
            })
    
    if not failed_deployments:
        logger.info(f"No failed deployments for {repo_url} in {environment}")
        return {
            "repo": repo_url,
            "environment": environment,
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "total_deployments_checked": len(recent_deployments),
            "failed_deployments": [],
            "clusters": [],
            "has_failures": False,
            "summary": f"Checked {len(recent_deployments)} deployments — all successful.",
        }
    
    logger.info(f"Found {len(failed_deployments)} failed deployments")
    
    # Step 3: Enrich failures with commit diff
    for failure in failed_deployments:
        sha = failure["deployment"]["sha"]
        commit_diff = connector.get_commit_diff(repo_url, sha)
        failure["commit_diff"] = commit_diff
    
    # Step 4: Fetch build logs
    for failure in failed_deployments:
        log_url = failure["latest_status"].get("log_url", "")
        if log_url:
            raw_log = connector.fetch_log_text(log_url, max_chars=8000)
            failure["raw_log"] = raw_log
        else:
            failure["raw_log"] = ""
    
    # Step 5: Parse errors from logs
    all_errors: List[Dict[str, Any]] = []
    for failure in failed_deployments:
        parsed_errors = _parse_log_errors(failure.get("raw_log", ""), failure)
        failure["parsed_errors"] = parsed_errors
        all_errors.extend(parsed_errors)
    
    # If no log errors, generate synthetic errors from commit diffs
    if not all_errors:
        all_errors = _errors_from_diff(failed_deployments)
    
    # Step 6: Cluster errors
    clusters = []
    if all_errors:
        try:
            clusterer = RootCauseClusterer()
            error_clusters = clusterer.cluster_errors(all_errors)
            clusters = [asdict(c) for c in error_clusters]
        except Exception as exc:
            logger.error(f"Error clustering failed: {exc}", exc_info=True)
            clusters = []
    
    # Step 7: Return result
    result = {
        "repo": repo_url,
        "environment": environment,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "total_deployments_checked": len(recent_deployments),
        "failed_deployments": [
            {
                "deployment_id": f["deployment"]["id"],
                "sha": f["deployment"]["sha"],
                "sha_short": f["deployment"]["sha"][:8] if f["deployment"]["sha"] else "",
                "ref": f["deployment"]["ref"],
                "environment": f["deployment"]["environment"],
                "failed_at": f["latest_status"]["created_at"],
                "log_url": f["latest_status"].get("log_url", ""),
                "commit_message": f["commit_diff"].get("message", ""),
                "files_changed": f["commit_diff"].get("files_changed", 0),
                "additions": f["commit_diff"].get("additions", 0),
                "deletions": f["commit_diff"].get("deletions", 0),
                "changed_files": [
                    fi["filename"] for fi in f["commit_diff"].get("files", [])[:10]
                ],
                "parsed_errors": f.get("parsed_errors", []),
                "log_available": bool(f.get("raw_log")),
            }
            for f in failed_deployments
        ],
        "clusters": clusters,
        "has_failures": len(failed_deployments) > 0,
        "summary": _build_summary(failed_deployments, clusters),
    }
    
    return result


def _parse_log_errors(
    raw_log: str,
    failure: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """
    Parse error patterns from build log text.
    
    Returns list of error dicts with message, level, timestamp, etc.
    """
    if not raw_log:
        return []
    
    lines = raw_log.split("\n")
    deployment = failure.get("deployment", {})
    latest_status = failure.get("latest_status", {})
    
    # Regex patterns for error detection
    error_patterns = [
        r"(?i)ERROR\s*:",
        r"(?i)error\s+",
        r"(?i)Exception\s*:",
        r"(?i)Error\s*:",
        r"(?i)CRITICAL",
        r"(?i)FATAL",
        r"(?i)Build\s+failed",
        r"(?i)Deployment\s+failed",
        r"(?i)Cannot\s+find\s+module",
        r"(?i)Module\s+not\s+found",
        r"npm\s+ERR!",
        r"yarn\s+error",
        r"SyntaxError",
        r"TypeError",
        r"ReferenceError",
    ]
    
    matched_lines = set()
    for line in lines:
        for pattern in error_patterns:
            if re.search(pattern, line):
                matched_lines.add(line.strip())
                break
    
    errors = []
    for i, line in enumerate(matched_lines):
        if not line:
            continue
        
        errors.append({
            "id": f"log_{deployment.get('id', 'unknown')}_{i}",
            "message": line[:300],
            "level": "ERROR" if any(
                k in line for k in ["CRITICAL", "FATAL", "Build failed"]
            ) else "WARNING",
            "timestamp": latest_status.get("created_at", ""),
            "service": _infer_service_from_line(line),
            "signature": _make_signature(line),
            "stack_trace": None,
            "exception_type": _extract_exception_type(line),
            "affected_orgs": [],
            "metadata": {
                "source": "build_log",
                "deployment_id": deployment.get("id"),
            },
        })
    
    return errors


def _errors_from_diff(failures: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Generate synthetic errors from commit diffs when no log errors found.
    """
    errors = []
    for failure in failures:
        commit_diff = failure.get("commit_diff", {})
        files = commit_diff.get("files", [])
        deployment = failure.get("deployment", {})
        
        for file_info in files:
            filename = file_info.get("filename", "")
            additions = file_info.get("additions", 0)
            deletions = file_info.get("deletions", 0)
            
            # Generate error if significant changes
            if deletions > 5 or additions > 20:
                errors.append({
                    "id": f"synthetic_{deployment.get('id')}_{filename}",
                    "message": f"Deployment failure in {filename} (+{additions}/-{deletions} lines)",
                    "level": "ERROR",
                    "timestamp": deployment.get("created_at", ""),
                    "service": _infer_service_from_line(filename),
                    "signature": f"deployment_failure:{filename}",
                    "stack_trace": None,
                    "exception_type": "DeploymentFailure",
                    "affected_orgs": [],
                    "metadata": {
                        "source": "commit_diff",
                        "deployment_id": deployment.get("id"),
                        "filename": filename,
                    },
                })
    
    return errors


def _infer_service_from_line(line: str) -> str:
    """
    Extract service name from log line heuristically.
    """
    # Look for patterns: [service_name], service/filename.py, at service.
    m = re.search(r"\[([a-zA-Z0-9_-]+)\]", line)
    if m:
        return m.group(1)
    
    m = re.search(r"(?:at\s+)?([a-zA-Z0-9_-]+)[/\\.]", line)
    if m:
        return m.group(1)
    
    return "unknown"


def _extract_exception_type(line: str) -> str:
    """
    Extract exception type from log line.
    """
    patterns = [
        r"(SyntaxError)",
        r"(TypeError)",
        r"(ModuleNotFoundError)",
        r"(ReferenceError)",
        r"(BuildError)",
        r"(npm ERR!)",
    ]
    
    for pattern in patterns:
        m = re.search(pattern, line, re.IGNORECASE)
        if m:
            return m.group(1)
    
    return "GenericError"


def _make_signature(line: str) -> str:
    """
    Create error signature by stripping timestamps and addresses.
    """
    # Remove timestamps: HH:MM:SS
    cleaned = re.sub(r"\d{2}:\d{2}:\d{2}", "", line)
    
    # Remove hex addresses: 0x[0-9a-f]+
    cleaned = re.sub(r"0x[0-9a-f]+", "", cleaned, flags=re.IGNORECASE)
    
    # Remove line references: line NNN
    cleaned = re.sub(r"line\s+\d+", "", cleaned, flags=re.IGNORECASE)
    
    # Take first 80 chars of cleaned line
    return cleaned.strip()[:80]


def _build_summary(failures: List[Dict[str, Any]], clusters: List[Dict[str, Any]]) -> str:
    """
    Build a plain-text summary of the failure detection.
    """
    num_failures = len(failures)
    
    if not failures:
        return "No deployment failures detected."
    
    # Get top cluster info
    top_cluster = clusters[0] if clusters else None
    severity = top_cluster.get("severity", "unknown") if top_cluster else "unknown"
    
    # Get commit info
    first_sha = failures[0].get("deployment", {}).get("sha", "")
    sha_short = first_sha[:8] if first_sha else ""
    
    total_files = sum(
        f.get("commit_diff", {}).get("files_changed", 0) for f in failures
    )
    
    cluster_count = len(clusters)
    
    return (
        f"{num_failures} failed deployment(s) detected. "
        f"Commit {sha_short} introduced {total_files} file changes. "
        f"{cluster_count} error cluster(s) found ({severity})."
    )
