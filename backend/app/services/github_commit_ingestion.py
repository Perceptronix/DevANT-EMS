from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

from database.client import get_database_client
from database.models import GitHubCommit, GitHubRepository, Project
from database.repositories.base import BaseRepository

logger = logging.getLogger(__name__)


class GitHubRepositoryRepository(BaseRepository[GitHubRepository]):
    def __init__(self, db):
        super().__init__(db, GitHubRepository)

    def get_by_full_name(self, full_name: str) -> Optional[GitHubRepository]:
        return self.db.query(GitHubRepository).filter(GitHubRepository.full_name == full_name).first()


class GitHubCommitRepository(BaseRepository[GitHubCommit]):
    def __init__(self, db):
        super().__init__(db, GitHubCommit)

    def get_by_repo_and_sha(self, repository_id, sha: str) -> Optional[GitHubCommit]:
        return (
            self.db.query(GitHubCommit)
            .filter(GitHubCommit.repository_id == repository_id, GitHubCommit.sha == sha)
            .first()
        )


class GitHubCommitIngestionService:
    """Persist GitHub push commits into normalized tables."""

    def __init__(self, db=None):
        self._db = db

    def _session(self):
        if self._db is not None:
            return self._db
        client = get_database_client()
        return client.get_session()

    @staticmethod
    def _parse_timestamp(value: Optional[str]) -> Optional[datetime]:
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=timezone.utc)
            return parsed
        except Exception:
            return None

    @staticmethod
    def _author_name(commit_payload: Dict[str, Any]) -> Optional[str]:
        author = commit_payload.get("author") or {}
        if isinstance(author, dict):
            return author.get("name") or author.get("email")
        return None

    @staticmethod
    def _changed_files(commit_payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        changed: List[Dict[str, Any]] = []
        for status_key in ("added", "removed", "modified"):
            for path in commit_payload.get(status_key, []) or []:
                changed.append({"path": path, "status": status_key})
        return changed

    def ingest_push_payload(self, payload: Dict[str, Any]) -> List[GitHubCommit]:
        repo = payload.get("repository") or {}
        full_name = repo.get("full_name")
        if not full_name:
            raise ValueError("push payload missing repository.full_name")

        session = self._session()
        created_here = self._db is None
        try:
            repo_repo = GitHubRepositoryRepository(session)
            project = session.query(Project).filter(Project.github_repo == full_name).first()
            if project is None:
                project = Project(name=full_name.split("/")[-1], github_repo=full_name)
                session.add(project)
                session.commit()
                session.refresh(project)

            github_repo = repo_repo.get_by_full_name(full_name)
            if github_repo is None:
                github_repo = GitHubRepository(
                    project_id=project.id,
                    owner=repo.get("owner", {}).get("login") if isinstance(repo.get("owner"), dict) else None,
                    name=repo.get("name") or full_name.split("/")[-1],
                    full_name=full_name,
                    url=repo.get("html_url") or repo.get("url"),
                    default_branch=repo.get("default_branch"),
                    description=repo.get("description"),
                    extra_metadata={"raw": repo},
                )
                session.add(github_repo)
                session.commit()
                session.refresh(github_repo)

            commit_repo = GitHubCommitRepository(session)
            saved: List[GitHubCommit] = []
            for commit_payload in payload.get("commits", []) or []:
                sha = commit_payload.get("id") or commit_payload.get("sha")
                if not sha:
                    continue
                existing = commit_repo.get_by_repo_and_sha(github_repo.id, sha)
                commit_data = {
                    "repository_id": github_repo.id,
                    "sha": sha,
                    "author": self._author_name(commit_payload),
                    "message": commit_payload.get("message"),
                    "committed_at": self._parse_timestamp(
                        (commit_payload.get("timestamp") or commit_payload.get("committed_at"))
                    ),
                    "files_changed": len(self._changed_files(commit_payload)),
                    "additions": commit_payload.get("additions"),
                    "deletions": commit_payload.get("deletions"),
                    "url": commit_payload.get("url"),
                    "changed_files": self._changed_files(commit_payload),
                    "extra_metadata": {
                        "distinct": commit_payload.get("distinct"),
                        "tree_id": commit_payload.get("tree_id"),
                        "raw": commit_payload,
                    },
                }
                if existing:
                    for key, value in commit_data.items():
                        setattr(existing, key, value)
                    session.commit()
                    session.refresh(existing)
                    saved.append(existing)
                else:
                    record = GitHubCommit(**commit_data)
                    session.add(record)
                    session.commit()
                    session.refresh(record)
                    saved.append(record)

            return saved
        finally:
            if created_here:
                session.close()


def ingest_push_commits(payload: Dict[str, Any], db=None) -> List[GitHubCommit]:
    return GitHubCommitIngestionService(db=db).ingest_push_payload(payload)
