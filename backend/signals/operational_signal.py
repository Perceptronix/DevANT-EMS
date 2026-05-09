from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional


class SignalType(str, Enum):
    deployment_failed = "deployment_failed"
    build_failed = "build_failed"
    runtime_error = "runtime_error"
    dependency_break = "dependency_break"
    workflow_timeout = "workflow_timeout"
    rollback_detected = "rollback_detected"
    hotfix_detected = "hotfix_detected"
    recurring_incident = "recurring_incident"


@dataclass
class OperationalSignal:
    type: SignalType
    source: str
    timestamp: datetime
    repo: str = "unknown"
    service: str = "unknown"
    severity: str = "informational"
    deployment_id: Optional[str] = None
    commit_sha: Optional[str] = None
    evidence: List[Dict[str, Any]] = field(default_factory=list)
    confidence: float = 0.5

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["type"] = self.type.value
        payload["timestamp"] = self.timestamp.isoformat()
        return payload

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "OperationalSignal":
        signal_type = data.get("type")
        if not isinstance(signal_type, SignalType):
            signal_type = SignalType(str(signal_type or SignalType.runtime_error.value))

        timestamp = data.get("timestamp")
        if isinstance(timestamp, datetime):
            parsed_timestamp = timestamp.astimezone(timezone.utc)
        elif isinstance(timestamp, str):
            parsed_timestamp = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            parsed_timestamp = parsed_timestamp.astimezone(timezone.utc) if parsed_timestamp.tzinfo else parsed_timestamp.replace(tzinfo=timezone.utc)
        else:
            parsed_timestamp = datetime.now(timezone.utc)

        return cls(
            type=signal_type,
            source=str(data.get("source", "unknown")),
            timestamp=parsed_timestamp,
            repo=str(data.get("repo", "unknown")),
            service=str(data.get("service", "unknown")),
            severity=str(data.get("severity", "informational")),
            deployment_id=data.get("deployment_id"),
            commit_sha=data.get("commit_sha"),
            evidence=list(data.get("evidence", []) or []),
            confidence=float(data.get("confidence", 0.5)),
        )