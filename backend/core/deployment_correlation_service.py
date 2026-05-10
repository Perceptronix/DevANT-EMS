from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from database.models import IncidentDeploymentCorrelation
from database.repositories.entities import IncidentDeploymentCorrelationRepository

logger = logging.getLogger(__name__)


@dataclass
class DeploymentRecord:
    provider: str
    deployment_id: str
    timestamp: str
    sha: Optional[str] = None
    environment: Optional[str] = None
    service: Optional[str] = None
    url: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SuspectDeployment:
    provider: str
    deployment_id: str
    timestamp: str
    score: float = 0.0
    reason: str = ""
    sha: Optional[str] = None
    environment: Optional[str] = None
    service: Optional[str] = None
    url: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class DeploymentCorrelationResult:
    likely_deployment_trigger: Optional[DeploymentRecord] = None
    suspect_deployments: List[SuspectDeployment] = field(default_factory=list)
    likely_affected_services: List[str] = field(default_factory=list)
    deployment_confidence_score: float = 0.0
    temporal_proximity_score: float = 0.0
    service_match_score: float = 0.0
    provider_match_score: float = 0.0
    matched_provider: Optional[str] = None
    time_delta_minutes: Optional[int] = None
    reasoning: str = ""


class DeploymentCorrelationService:
    """Correlate incidents with multi-provider deployments."""

    def __init__(self, session=None, lookback_hours: int = 24):
        self.session = session
        self.lookback_hours = lookback_hours

    def correlate_incident_with_deployments(
        self,
        incident: Any,
        deployments: Sequence[Any],
        persist: bool = True,
    ) -> DeploymentCorrelationResult:
        incident_data = self._as_dict(incident)
        incident_ts = self._parse_timestamp(
            incident_data.get("first_seen")
            or incident_data.get("created_at")
            or incident_data.get("occurred_at")
            or incident_data.get("timestamp")
        )
        if incident_ts is None:
            return DeploymentCorrelationResult(reasoning="incident timestamp missing")

        incident_service = self._first_string(
            incident_data,
            ["service", "dominant_service", "owner", "component"],
        )
        incident_repo = self._first_string(
            incident_data,
            ["repo_full_name", "github_repo", "repository_full_name", "repo"],
        )

        suspect_deployments: List[SuspectDeployment] = []
        affected_services: List[str] = []
        best_confidence = 0.0
        best_deployment = None
        best_temporal = 0.0
        best_service = 0.0
        best_provider = 0.0

        for raw_deployment in deployments:
            deployment = self._to_record(raw_deployment)
            if deployment is None:
                continue
            dep_ts = self._parse_timestamp(deployment.timestamp)
            if dep_ts is None:
                continue

            delta_minutes = int(abs((incident_ts - dep_ts).total_seconds()) / 60)
            if delta_minutes > self.lookback_hours * 60:
                continue

            temporal_score = self._temporal_score(delta_minutes)
            service_score = self._service_score(incident_service, incident_repo, deployment)
            provider_score = self._provider_score(deployment.provider)
            confidence = round(min(1.0, temporal_score * 0.55 + service_score * 0.30 + provider_score * 0.15), 4)

            suspect = SuspectDeployment(
                provider=deployment.provider,
                deployment_id=deployment.deployment_id,
                timestamp=deployment.timestamp,
                score=confidence,
                reason=f"delta={delta_minutes}min temporal={temporal_score:.2f} service={service_score:.2f} provider={provider_score:.2f}",
                sha=deployment.sha,
                environment=deployment.environment,
                service=deployment.service,
                url=deployment.url,
                metadata=deployment.metadata,
            )
            suspect_deployments.append(suspect)

            if deployment.service and deployment.service not in affected_services:
                affected_services.append(deployment.service)

            if confidence > best_confidence:
                best_confidence = confidence
                best_deployment = deployment
                best_temporal = temporal_score
                best_service = service_score
                best_provider = provider_score

        suspect_deployments.sort(key=lambda x: x.score, reverse=True)
        suspect_deployments = suspect_deployments[:10]  # Keep top 10

        result = DeploymentCorrelationResult(
            likely_deployment_trigger=best_deployment,
            suspect_deployments=suspect_deployments,
            likely_affected_services=affected_services,
            deployment_confidence_score=best_confidence,
            temporal_proximity_score=best_temporal,
            service_match_score=best_service,
            provider_match_score=best_provider,
            matched_provider=best_deployment.provider if best_deployment else None,
            time_delta_minutes=int(abs((incident_ts - self._parse_timestamp(best_deployment.timestamp)).total_seconds()) / 60) if best_deployment else None,
            reasoning=self._reasoning(best_deployment, best_temporal, best_service) if best_deployment else "no deployment matched",
        )

        if persist and self.session is not None and hasattr(incident, 'id'):
            self._persist(result, incident)

        return result

    def correlate_incident_with_recorded_deployments(
        self,
        incident: Any,
        deployments: Sequence[Any],
    ) -> DeploymentCorrelationResult:
        return self.correlate_incident_with_deployments(incident, deployments, persist=False)

    def correlate_and_store(
        self,
        incident: Any,
        deployments: Sequence[Any],
    ) -> DeploymentCorrelationResult:
        return self.correlate_incident_with_deployments(incident, deployments, persist=True)

    def _temporal_score(self, delta_minutes: int) -> float:
        if delta_minutes <= 15:
            return 1.0
        if delta_minutes <= 60:
            return max(0.0, 1.0 - ((delta_minutes - 15) / 45.0))
        return max(0.0, 1.0 - ((delta_minutes - 60) / float(max(self.lookback_hours * 60 - 60, 1))))

    def _service_score(self, incident_service: Optional[str], incident_repo: Optional[str], deployment: DeploymentRecord) -> float:
        if not incident_service and not incident_repo:
            return 0.0
        haystack = " ".join(filter(None, [deployment.service, deployment.environment, deployment.sha, deployment.url, deployment.metadata.get("service"), deployment.metadata.get("repo"), deployment.metadata.get("repository")])).lower()
        hits = 0
        if incident_service and incident_service.lower() in haystack:
            hits += 1
        if incident_repo and incident_repo.lower() in haystack:
            hits += 1
        return min(1.0, hits / 2.0)

    def _provider_score(self, provider: str) -> float:
        provider = (provider or "").lower().replace(" ", "_")
        if provider in {"github", "github_actions", "github-actions", "github_deployment", "githubdeployment", "github_deployments"}:
            return 1.0
        if provider in {"vercel", "render"}:
            return 0.9
        return 0.5

    def _reasoning(self, deployment: DeploymentRecord, temporal_score: float, service_score: float) -> str:
        return f"provider={deployment.provider} temporal={temporal_score:.2f} service={service_score:.2f}"

    def _persist(
        self,
        result: DeploymentCorrelationResult,
        incident: Any,
    ) -> None:
        try:
            repository = IncidentDeploymentCorrelationRepository(self.session)
            incident_data = self._as_dict(incident)
            cluster_id = incident_data.get("cluster_id")

            row = repository.create(
                incident_id=self._as_uuid(incident_data.get("id")),
                cluster_id=self._as_uuid(cluster_id),
                representative_event_id=None,  # Could be added later if needed
                suspect_deployments=[self._suspect_to_dict(item) for item in result.suspect_deployments],
                likely_affected_services=result.likely_affected_services,
                confidence_score=result.deployment_confidence_score,
                temporal_proximity_score=result.temporal_proximity_score,
                service_match_score=result.service_match_score,
                provider_match_score=result.provider_match_score,
                notes=result.reasoning,
            )
            logger.info("Stored incident-deployment correlation %s", row.id)
        except Exception as exc:
            logger.error("Failed to store incident deployment correlation: %s", exc, exc_info=True)

    def _suspect_to_dict(self, suspect: SuspectDeployment) -> Dict[str, Any]:
        return {
            "provider": suspect.provider,
            "deployment_id": suspect.deployment_id,
            "timestamp": suspect.timestamp,
            "score": suspect.score,
            "reason": suspect.reason,
            "sha": suspect.sha,
            "environment": suspect.environment,
            "service": suspect.service,
            "url": suspect.url,
            "metadata": suspect.metadata,
        }

    def _as_uuid(self, value: Any) -> Optional[str]:
        if value is None:
            return None
        if isinstance(value, str):
            return value
        if hasattr(value, '__str__'):
            return str(value)
        return None

    def _to_record(self, raw: Any) -> Optional[DeploymentRecord]:
        if raw is None:
            return None
        data = self._as_dict(raw)
        provider = self._first_string(data, ["provider", "source", "platform"]) or "unknown"
        deployment_id = self._first_string(data, ["deployment_id", "id", "run_id", "deploymentId"]) or ""
        timestamp = self._first_string(data, ["deployed_at", "timestamp", "created_at", "started_at", "finished_at", "updated_at"]) or ""
        if not deployment_id or not timestamp:
            return None
        return DeploymentRecord(
            provider=provider,
            deployment_id=deployment_id,
            timestamp=timestamp,
            sha=self._first_string(data, ["sha", "commit_sha", "commit_hash"]),
            environment=self._first_string(data, ["environment", "target", "env"]),
            service=self._first_string(data, ["service", "project", "app", "repo", "repository"]),
            url=self._first_string(data, ["url", "deployment_url", "html_url"]),
            metadata=data.get("metadata") if isinstance(data.get("metadata"), dict) else {},
        )

    def _parse_timestamp(self, value: Any) -> Optional[datetime]:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        if not isinstance(value, str):
            return None
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except Exception:
            return None

    def _as_dict(self, value: Any) -> Dict[str, Any]:
        if isinstance(value, dict):
            return value
        if hasattr(value, "to_dict"):
            try:
                data = value.to_dict()
                if isinstance(data, dict):
                    return data
            except Exception:
                pass
        data: Dict[str, Any] = {}
        for key in ("provider", "deployment_id", "id", "run_id", "timestamp", "deployed_at", "created_at", "started_at", "finished_at", "updated_at", "sha", "commit_sha", "commit_hash", "environment", "target", "env", "service", "project", "app", "repo", "repository", "url", "deployment_url", "html_url", "metadata"):
            if hasattr(value, key):
                data[key] = getattr(value, key)
        return data

    def _first_string(self, data: Dict[str, Any], keys: Sequence[str]) -> Optional[str]:
        for key in keys:
            value = data.get(key)
            if isinstance(value, str) and value:
                return value
        return None
