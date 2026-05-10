from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from database.models import GitHubCommit, GitHubRepository, Incident, IncidentCommitCorrelation
from database.repositories.entities import IncidentCommitCorrelationRepository
from core.suspect_file_detection import SuspectFileDetectionService

logger = logging.getLogger(__name__)

_STACK_FILE_RE = re.compile(r"(?:[A-Za-z]:)?(?:[\\/][^\s:()]+)+\.(?:py|pyi|ts|tsx|js|jsx|go|rb|java|kt|cs|cpp|c|h|rs)")
_FILE_TOKEN_RE = re.compile(r"[A-Za-z0-9_./\\-]+\.(?:py|pyi|ts|tsx|js|jsx|go|rb|java|kt|cs|cpp|c|h|rs)")


@dataclass
class SuspectCommit:
    sha: str
    author: Optional[str] = None
    message: Optional[str] = None
    committed_at: Optional[str] = None
    score: float = 0.0
    reason: str = ""
    changed_files: List[Dict[str, Any]] = field(default_factory=list)
    additions: Optional[int] = None
    deletions: Optional[int] = None


@dataclass
class IncidentCommitCorrelationResult:
    incident_id: Optional[str]
    repository_id: Optional[str]
    repository_full_name: Optional[str]
    suspect_commits: List[SuspectCommit] = field(default_factory=list)
    likely_changed_files: List[str] = field(default_factory=list)
    confidence_score: float = 0.0
    service_match_score: float = 0.0
    deployment_timing_score: float = 0.0
    file_match_score: float = 0.0
    notes: str = ""


class IncidentCommitCorrelationEngine:
    """Correlate incidents to GitHub commits."""

    def __init__(self, session=None, lookback_hours: int = 72):
        self.session = session
        self.lookback_hours = lookback_hours
        self.file_detector = SuspectFileDetectionService()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def correlate_incident(
        self,
        incident: Any,
        representative_event: Optional[Any] = None,
        stack_trace: str = "",
        cluster_metadata: Optional[Dict[str, Any]] = None,
        persist: bool = True,
    ) -> IncidentCommitCorrelationResult:
        incident_data = self._as_dict(incident)
        event_data = self._as_dict(representative_event)
        cluster_metadata = cluster_metadata or {}

        incident_id = self._pick(incident_data, "id")
        incident_ts = self._parse_timestamp(
            self._pick(incident_data, "created_at", "occurred_at", "timestamp")
            or self._pick(event_data, "occurred_at", "timestamp", "created_at")
        )
        repo_full_name = self._pick(
            cluster_metadata,
            "repo_full_name",
            "github_repo",
            "repository_full_name",
            "repo",
        ) or self._extract_repo_full_name(incident_data, event_data)

        repo = self._get_repository(repo_full_name)
        candidate_commits = self._load_candidate_commits(repo_full_name, incident_ts)

        service_tokens = self._service_tokens(incident_data, event_data, cluster_metadata)
        stack_files = self._stack_files(stack_trace or self._pick(incident_data, "stack_trace", "message", default=""))
        deployment_ts = self._parse_timestamp(
            self._pick(cluster_metadata, "deployment_time", "deployed_at", "last_deploy_time")
            or self._pick(event_data, "deployment_time", "deployed_at")
        )

        suspects: List[SuspectCommit] = []
        changed_files: List[str] = []
        best_service = 0.0
        best_deployment = 0.0
        best_file = 0.0

        for commit in candidate_commits:
            score, reason, service_score, deployment_score, file_score = self._score_commit(
                commit=commit,
                incident_ts=incident_ts,
                deployment_ts=deployment_ts,
                service_tokens=service_tokens,
                stack_files=stack_files,
            )
            if score <= 0:
                continue

            suspect = SuspectCommit(
                sha=commit.sha,
                author=commit.author,
                message=commit.message,
                committed_at=commit.committed_at.isoformat() if commit.committed_at else None,
                score=round(score, 4),
                reason=reason,
                changed_files=self._normalize_changed_files(commit.changed_files),
                additions=commit.additions,
                deletions=commit.deletions,
            )
            suspects.append(suspect)
            best_service = max(best_service, service_score)
            best_deployment = max(best_deployment, deployment_score)
            best_file = max(best_file, file_score)

            for file_path in self._flatten_changed_files(commit.changed_files):
                if file_path not in changed_files:
                    changed_files.append(file_path)

        suspects.sort(key=lambda item: item.score, reverse=True)
        suspects = suspects[:10]
        changed_files = changed_files[:20]

        confidence = self._combine_confidence(suspects, best_service, best_deployment, best_file)
        notes = self._build_notes(repo_full_name, service_tokens, stack_files, deployment_ts, len(suspects))

        result = IncidentCommitCorrelationResult(
            incident_id=str(incident_id) if incident_id is not None else None,
            repository_id=str(repo.id) if repo else None,
            repository_full_name=repo_full_name,
            suspect_commits=suspects,
            likely_changed_files=changed_files,
            confidence_score=confidence,
            service_match_score=best_service,
            deployment_timing_score=best_deployment,
            file_match_score=best_file,
            notes=notes,
        )

        if persist and self.session is not None and incident_id is not None:
            self._persist(result, incident, cluster_metadata, representative_event)

        return result

    def correlate_and_store(
        self,
        incident: Any,
        representative_event: Optional[Any] = None,
        stack_trace: str = "",
        cluster_metadata: Optional[Dict[str, Any]] = None,
    ) -> IncidentCommitCorrelationResult:
        return self.correlate_incident(
            incident=incident,
            representative_event=representative_event,
            stack_trace=stack_trace,
            cluster_metadata=cluster_metadata,
            persist=True,
        )

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _persist(
        self,
        result: IncidentCommitCorrelationResult,
        incident: Any,
        cluster_metadata: Dict[str, Any],
        representative_event: Optional[Any],
    ) -> None:
        try:
            repository = IncidentCommitCorrelationRepository(self.session)
            row = repository.create(
                incident_id=self._as_uuid(self._pick(self._as_dict(incident), "id")),
                cluster_id=self._as_uuid(self._pick(cluster_metadata, "cluster_id")),
                representative_event_id=self._as_uuid(self._pick(self._as_dict(representative_event), "id")),
                repository_id=self._as_uuid(result.repository_id),
                suspect_commits=[self._suspect_to_dict(item) for item in result.suspect_commits],
                likely_changed_files=result.likely_changed_files,
                confidence_score=result.confidence_score,
                service_match_score=result.service_match_score,
                deployment_timing_score=result.deployment_timing_score,
                file_match_score=result.file_match_score,
                notes=result.notes,
            )
            logger.info("Stored incident-commit correlation %s", row.id)
        except Exception as exc:
            logger.error("Failed to store incident commit correlation: %s", exc, exc_info=True)

    # ------------------------------------------------------------------
    # Scoring
    # ------------------------------------------------------------------

    def _score_commit(
        self,
        commit: GitHubCommit,
        incident_ts: Optional[datetime],
        deployment_ts: Optional[datetime],
        service_tokens: Sequence[str],
        stack_files: Sequence[str],
    ) -> Tuple[float, str, float, float, float]:
        temporal_score = self._temporal_score(commit.committed_at, incident_ts)
        service_score = self._service_score(commit, service_tokens)
        file_score = self._file_score(commit, stack_files, service_tokens)
        deployment_score = self._deployment_score(commit.committed_at, deployment_ts)

        score = (
            temporal_score * 0.35
            + file_score * 0.35
            + service_score * 0.2
            + deployment_score * 0.1
        )

        if score < 0.15:
            return 0.0, "", service_score, deployment_score, file_score

        reasons: List[str] = []
        if temporal_score >= 0.6:
            reasons.append("time")
        if file_score >= 0.3:
            reasons.append("file")
        if service_score >= 0.3:
            reasons.append("service")
        if deployment_score >= 0.3:
            reasons.append("deploy")

        return score, "+".join(reasons) or "temporal", service_score, deployment_score, file_score

    def _temporal_score(self, committed_at: Optional[datetime], incident_ts: Optional[datetime]) -> float:
        if committed_at is None or incident_ts is None:
            return 0.0
        committed_at = self._ensure_utc(committed_at)
        incident_ts = self._ensure_utc(incident_ts)
        delta_hours = abs((incident_ts - committed_at).total_seconds()) / 3600.0
        if delta_hours > self.lookback_hours:
            return 0.0
        return max(0.0, 1.0 - (delta_hours / float(self.lookback_hours)))

    def _deployment_score(self, committed_at: Optional[datetime], deployment_ts: Optional[datetime]) -> float:
        if committed_at is None or deployment_ts is None:
            return 0.0
        committed_at = self._ensure_utc(committed_at)
        deployment_ts = self._ensure_utc(deployment_ts)
        delta_hours = abs((deployment_ts - committed_at).total_seconds()) / 3600.0
        if delta_hours > 24:
            return 0.0
        return max(0.0, 1.0 - (delta_hours / 24.0))

    def _service_score(self, commit: GitHubCommit, service_tokens: Sequence[str]) -> float:
        if not service_tokens:
            return 0.0
        haystack = " ".join([
            commit.sha or "",
            commit.author or "",
            commit.message or "",
            " ".join(self._flatten_changed_files(commit.changed_files)),
        ]).lower()
        hits = sum(1 for token in service_tokens if token and token.lower() in haystack)
        return min(1.0, hits / max(len(service_tokens), 1))

    def _file_score(self, commit: GitHubCommit, stack_files: Sequence[str], service_tokens: Sequence[str]) -> float:
        if not stack_files:
            return 0.0
        commit_files = [self._basename(path).lower() for path in self._flatten_changed_files(commit.changed_files)]
        stack_bases = [self._basename(path).lower() for path in stack_files]
        suspects, confidence = self.file_detector.rank_likely_culprit_files(
            stack_trace=" ".join(stack_files),
            changed_files=commit.changed_files or [],
            service_name=service_tokens[0] if service_tokens else None,
        )
        if suspects:
            return confidence
        hits = len(set(commit_files) & set(stack_bases))
        if hits:
            return min(1.0, hits / max(len(stack_bases), 1))
        commit_haystack = " ".join(commit_files)
        lexical_hits = sum(1 for token in stack_bases if token and token in commit_haystack)
        return min(1.0, lexical_hits / max(len(stack_bases), 1))

    def _combine_confidence(
        self,
        suspects: Sequence[SuspectCommit],
        service_score: float,
        deployment_score: float,
        file_score: float,
    ) -> float:
        if not suspects:
            return 0.0
        top = suspects[0].score if suspects else 0.0
        confidence = max(top, (service_score * 0.25) + (deployment_score * 0.2) + (file_score * 0.55))
        return round(min(1.0, confidence), 4)

    # ------------------------------------------------------------------
    # Data loading
    # ------------------------------------------------------------------

    def _load_candidate_commits(self, repo_full_name: Optional[str], incident_ts: Optional[datetime]) -> List[GitHubCommit]:
        if self.session is None or not repo_full_name:
            return []

        query = (
            self.session.query(GitHubCommit)
            .join(GitHubRepository, GitHubCommit.repository_id == GitHubRepository.id)
            .filter(GitHubRepository.full_name == repo_full_name)
        )

        if incident_ts is not None:
            start = incident_ts - timedelta(hours=self.lookback_hours)
            end = incident_ts + timedelta(hours=12)
            query = query.filter(
                (GitHubCommit.committed_at.is_(None))
                | ((GitHubCommit.committed_at >= start) & (GitHubCommit.committed_at <= end))
            )

        return query.order_by(GitHubCommit.committed_at.desc().nullslast()).limit(100).all()

    def _get_repository(self, repo_full_name: Optional[str]) -> Optional[GitHubRepository]:
        if self.session is None or not repo_full_name:
            return None
        return (
            self.session.query(GitHubRepository)
            .filter(GitHubRepository.full_name == repo_full_name)
            .first()
        )

    # ------------------------------------------------------------------
    # Parsing helpers
    # ------------------------------------------------------------------

    def _as_dict(self, value: Any) -> Dict[str, Any]:
        if value is None:
            return {}
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
        for key in ("id", "cluster_id", "title", "summary", "root_cause", "recommendations", "created_at", "updated_at", "occurred_at", "timestamp", "service", "repo_full_name", "github_repo", "stack_trace"):
            if hasattr(value, key):
                data[key] = getattr(value, key)
        return data

    def _pick(self, data: Dict[str, Any], *keys: str, default: Any = None) -> Any:
        for key in keys:
            if key in data and data[key] not in (None, ""):
                return data[key]
        return default

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

    def _extract_repo_full_name(self, incident_data: Dict[str, Any], event_data: Dict[str, Any]) -> Optional[str]:
        for source in (incident_data, event_data):
            repo = source.get("repository") if isinstance(source.get("repository"), dict) else None
            if repo and repo.get("full_name"):
                return repo.get("full_name")
            for key in ("repo_full_name", "github_repo", "repository_full_name", "repo"):
                value = source.get(key)
                if isinstance(value, str) and value:
                    return value
        return None

    def _service_tokens(self, incident_data: Dict[str, Any], event_data: Dict[str, Any], cluster_metadata: Dict[str, Any]) -> List[str]:
        tokens: List[str] = []
        for source in (incident_data, event_data, cluster_metadata):
            for key in ("service", "dominant_service", "owner", "component"):
                value = source.get(key)
                if isinstance(value, str) and value:
                    tokens.append(value)
            values = source.get("affected_services")
            if isinstance(values, list):
                tokens.extend([item for item in values if isinstance(item, str)])
        return list(dict.fromkeys(token.strip() for token in tokens if token and token.strip()))

    def _stack_files(self, stack_trace: str) -> List[str]:
        if not stack_trace:
            return []
        return list(dict.fromkeys(match.group(0) for match in _STACK_FILE_RE.finditer(stack_trace) or _FILE_TOKEN_RE.finditer(stack_trace)))

    def _flatten_changed_files(self, changed_files: Any) -> List[str]:
        flattened: List[str] = []
        if not changed_files:
            return flattened
        if isinstance(changed_files, list):
            for item in changed_files:
                if isinstance(item, str):
                    flattened.append(item)
                elif isinstance(item, dict):
                    path = item.get("path") or item.get("filename") or item.get("name")
                    if isinstance(path, str):
                        flattened.append(path)
        return flattened

    def _normalize_changed_files(self, changed_files: Any) -> List[Dict[str, Any]]:
        normalized: List[Dict[str, Any]] = []
        for item in changed_files or []:
            if isinstance(item, dict):
                normalized.append(item)
            elif isinstance(item, str):
                normalized.append({"path": item})
        return normalized

    def _basename(self, path: str) -> str:
        return path.replace("\\", "/").rsplit("/", 1)[-1]

    def _as_uuid(self, value: Any) -> Any:
        if value in (None, ""):
            return None
        return value

    def _ensure_utc(self, value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def _suspect_to_dict(self, item: SuspectCommit) -> Dict[str, Any]:
        return {
            "sha": item.sha,
            "author": item.author,
            "message": item.message,
            "committed_at": item.committed_at,
            "score": item.score,
            "reason": item.reason,
            "changed_files": item.changed_files,
            "additions": item.additions,
            "deletions": item.deletions,
        }

    def _build_notes(
        self,
        repo_full_name: Optional[str],
        service_tokens: Sequence[str],
        stack_files: Sequence[str],
        deployment_ts: Optional[datetime],
        suspect_count: int,
    ) -> str:
        notes = [f"suspects={suspect_count}"]
        if repo_full_name:
            notes.append(f"repo={repo_full_name}")
        if service_tokens:
            notes.append(f"services={','.join(service_tokens[:5])}")
        if stack_files:
            notes.append(f"stack_files={','.join(stack_files[:5])}")
        if deployment_ts:
            notes.append(f"deployment={deployment_ts.isoformat()}")
        return " | ".join(notes)
