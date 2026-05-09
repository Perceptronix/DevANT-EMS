from __future__ import annotations

from typing import Any, Dict

from .normalization import normalize_signature, normalize_text


def stable_identity(parts: Dict[str, Any]) -> str:
    values = [normalize_text(value) for value in parts.values() if value not in (None, "")]
    return "|".join(values)


def incident_identity(incident: Dict[str, Any]) -> str:
    explicit_id = incident.get("incident_id") or incident.get("id")
    if explicit_id:
        return normalize_text(explicit_id)

    return stable_identity(
        {
            "signature": incident.get("signature") or incident.get("error_signature") or incident.get("message"),
            "service": incident.get("service") or incident.get("container") or incident.get("module"),
            "timestamp": incident.get("timestamp") or incident.get("occurred_at"),
        }
    )


def deployment_identity(deployment: Dict[str, Any]) -> str:
    explicit_id = deployment.get("deployment_id") or deployment.get("id")
    if explicit_id:
        return normalize_text(explicit_id)

    return stable_identity(
        {
            "commit": deployment.get("commit_hash") or deployment.get("commit_sha"),
            "workflow": deployment.get("workflow_name") or deployment.get("workflow"),
            "service": deployment.get("service"),
            "environment": deployment.get("environment"),
        }
    )


def same_incident(left: Dict[str, Any], right: Dict[str, Any]) -> bool:
    left_signature = normalize_signature(left.get("signature") or left.get("error_signature") or left.get("message"))
    right_signature = normalize_signature(right.get("signature") or right.get("error_signature") or right.get("message"))
    if left_signature and right_signature and left_signature == right_signature:
        return True

    left_service = normalize_text(left.get("service") or left.get("container") or left.get("module"))
    right_service = normalize_text(right.get("service") or right.get("container") or right.get("module"))
    if left_service and right_service and left_service == right_service:
        return True

    left_identity = incident_identity(left)
    right_identity = incident_identity(right)
    return bool(left_identity and right_identity and left_identity == right_identity)