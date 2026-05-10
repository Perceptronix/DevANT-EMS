from __future__ import annotations

import hashlib
import hmac
import json
import logging
from datetime import datetime
from typing import Any, Dict, Optional

from fastapi import APIRouter, Request, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse

from config import get_config

try:
    from database.client import get_database_client
    from database.repositories.entities import (
        GitHubEventRepository,
        ProjectRepository,
        DeploymentRepository,
        IncidentRepository,
    )
    from app.services.github_commit_ingestion import ingest_push_commits
    from core.incident_commit_correlation import IncidentCommitCorrelationEngine
    from core.deployment_correlation_service import DeploymentCorrelationService
except Exception:
    get_database_client = None
    GitHubEventRepository = None
    ProjectRepository = None
    DeploymentRepository = None
    IncidentRepository = None
    ingest_push_commits = None
    IncidentCommitCorrelationEngine = None
    DeploymentCorrelationService = None

router = APIRouter(prefix="/api/v1/webhooks", tags=["github-webhooks"])

logger = logging.getLogger(__name__)


def _verify_signature(secret: str, payload: bytes, signature_header: Optional[str]) -> bool:
    if not secret:
        return False
    if not signature_header:
        return False
    sig_parts = signature_header.split("=", 1)
    if len(sig_parts) != 2:
        return False
    algo, signature = sig_parts
    if algo != "sha256":
        return False

    mac = hmac.new(secret.encode("utf-8"), msg=payload, digestmod=hashlib.sha256)
    expected = mac.hexdigest()
    return hmac.compare_digest(expected, signature)


def _resolve_project_id(repo_full_name: str) -> Optional[str]:
    if get_database_client is None or ProjectRepository is None:
        return None
    client = get_database_client()
    session = client.get_session()
    try:
        proj_repo = ProjectRepository(session)
        project = proj_repo.get_by_github_repo(repo_full_name)
        if project:
            return str(project.id)
        # create project record
        name = repo_full_name.split("/")[-1]
        project = proj_repo.create(name=name, github_repo=repo_full_name)
        return str(project.id)
    finally:
        session.close()


def _normalize_event(event_type: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    repo = payload.get("repository") or payload.get("repo") or {}
    repo_full = repo.get("full_name") if isinstance(repo, dict) else None

    normalized = {
        "event_type": event_type,
        "repo_full_name": repo_full,
        "actor": (payload.get("sender") or {}).get("login") if isinstance(payload.get("sender"), dict) else None,
        "action": payload.get("action"),
        "summary": None,
        "payload": payload,
    }

    # build short summary per event
    if event_type == "push":
        pusher = payload.get("pusher", {}).get("name") if isinstance(payload.get("pusher"), dict) else None
        commits = payload.get("commits") or []
        normalized["summary"] = f"push by {pusher}, commits={len(commits)}"
    elif event_type == "pull_request":
        pr = payload.get("pull_request") or {}
        normalized["summary"] = f"pr #{pr.get('number')} {pr.get('title')} action={payload.get('action')}"
    elif event_type == "deployment":
        dep = payload.get("deployment") or {}
        normalized["summary"] = f"deployment id={dep.get('id')} ref={dep.get('ref')}"
    elif event_type == "deployment_status":
        ds = payload.get("deployment_status") or {}
        normalized["summary"] = f"deployment_status id={ds.get('id')} state={ds.get('state')}"
    elif event_type == "workflow_run":
        wr = payload.get("workflow_run") or {}
        normalized["summary"] = f"workflow_run id={wr.get('id')} status={wr.get('status')} conclusion={wr.get('conclusion')}"

    return normalized


async def _persist_event(normalized: Dict[str, Any]) -> None:
    if get_database_client is None or GitHubEventRepository is None:
        logger.warning("DB persistence dependencies unavailable for GitHub webhook")
        return

    repo_full = normalized.get("repo_full_name")
    if not repo_full:
        logger.info("No repo found in webhook payload; skipping persistence")
        return

    project_id = _resolve_project_id(repo_full)
    if not project_id:
        logger.warning("Could not resolve project for repo %s; skipping persistence", repo_full)
        return

    client = get_database_client()
    session = client.get_session()
    try:
        gh_repo = GitHubEventRepository(session)
        gh_repo.create(project_id=project_id, event_type=normalized.get("event_type"), payload=normalized.get("payload"))

        # For deployments, persist to Deployments table too (basic mapping)
        if normalized.get("event_type") in ("deployment", "deployment_status") and DeploymentRepository is not None:
            dep_repo = DeploymentRepository(session)
            # try to extract deployment id and status
            dep = normalized.get("payload", {}).get("deployment") or normalized.get("payload", {}).get("deployment_status") or {}
            deployment_id = str(dep.get("id") or dep.get("deployment_id") or dep.get("sha") or "")
            status = dep.get("state") or dep.get("status") or None
            dep_repo.create(
                project_id=project_id,
                provider="github-actions",
                deployment_id=deployment_id,
                status=status,
                extra_metadata={"raw": dep},
            )
    except Exception as exc:
        logger.error("Failed to persist GitHub webhook event: %s", exc, exc_info=True)
    finally:
        session.close()


async def _trigger_pipeline(repo_full_name: str, environment: Optional[str] = None, log_url: Optional[str] = None) -> None:
    """Trigger error pipeline for repo (background)."""
    try:
        from pipeline.error_pipeline import run_error_pipeline
    except Exception as exc:
        logger.warning("Error pipeline not available: %s", exc)
        return

    try:
        repo_url = f"https://github.com/{repo_full_name}"
        result = await run_error_pipeline(repo_url=repo_url, environment=environment or "production", log_url=log_url)
        logger.info("Triggered error pipeline for %s: %s", repo_full_name, {"has_failures": result.get("has_failures")})
    except Exception as exc:
        logger.error("Error running pipeline for %s: %s", repo_full_name, exc, exc_info=True)


async def _ingest_push_commits(payload: Dict[str, Any]) -> None:
    if ingest_push_commits is None:
        logger.warning("Commit ingestion service unavailable for GitHub push webhook")
        return

    try:
        commits = ingest_push_commits(payload)
        logger.info("Stored %d GitHub commits from push webhook", len(commits))
    except Exception as exc:
        logger.error("Failed to ingest GitHub push commits: %s", exc, exc_info=True)


async def _score_recent_incidents_for_push(payload: Dict[str, Any]) -> None:
    if get_database_client is None or ProjectRepository is None or IncidentRepository is None or IncidentCommitCorrelationEngine is None:
        logger.warning("Incident correlation dependencies unavailable for GitHub push webhook")
        return

    repo = payload.get("repository") or {}
    repo_full = repo.get("full_name") if isinstance(repo, dict) else None
    if not repo_full:
        return

    client = get_database_client()
    session = client.get_session()
    try:
        proj_repo = ProjectRepository(session)
        project = proj_repo.get_by_github_repo(repo_full)
        if not project:
            return

        incident_repo = IncidentRepository(session)
        recent_incidents = incident_repo.get_recent_for_project(project.id, days=14)[:10]
        if not recent_incidents:
            return

        engine = IncidentCommitCorrelationEngine(session=session)
        for incident in recent_incidents:
            incident_payload = incident.to_dict() if hasattr(incident, "to_dict") else {"id": str(getattr(incident, "id", ""))}
            cluster = incident.cluster.to_dict() if hasattr(incident, "cluster") and incident.cluster and hasattr(incident.cluster, "to_dict") else {}
            stack_trace = (incident.summary or incident.root_cause or incident.title or "")
            engine.correlate_and_store(
                incident=incident_payload,
                representative_event=None,
                stack_trace=stack_trace,
                cluster_metadata={
                    "cluster_id": str(getattr(incident, "cluster_id", "")),
                    "repo_full_name": repo_full,
                    "service": cluster.get("affected_services", [repo.get("name") or "unknown"])[0] if isinstance(cluster, dict) else (repo.get("name") or "unknown"),
                    "affected_services": cluster.get("affected_services", [repo.get("name") or "unknown"]) if isinstance(cluster, dict) else [repo.get("name") or "unknown"],
                    "deployment_time": getattr(incident, "created_at", None).isoformat() if getattr(incident, "created_at", None) else None,
                },
            )
    except Exception as exc:
        logger.error("Failed to score recent incidents for push: %s", exc, exc_info=True)
    finally:
        session.close()


async def _score_recent_incidents_for_deployment(payload: Dict[str, Any]) -> None:
    if get_database_client is None or ProjectRepository is None or IncidentRepository is None or DeploymentCorrelationService is None:
        logger.warning("Deployment correlation dependencies unavailable for GitHub webhook")
        return

    repo = payload.get("repository") or {}
    repo_full = repo.get("full_name") if isinstance(repo, dict) else None
    if not repo_full:
        return

    deployment = payload.get("deployment") or payload.get("deployment_status") or {}
    if not isinstance(deployment, dict):
        deployment = {}

    normalized_deployment = {
        "provider": "github",
        "deployment_id": str(deployment.get("id") or deployment.get("deployment_id") or deployment.get("sha") or ""),
        "timestamp": deployment.get("created_at") or deployment.get("updated_at") or deployment.get("deployed_at") or payload.get("created_at") or datetime.utcnow().isoformat(),
        "sha": deployment.get("sha") or payload.get("sha"),
        "environment": deployment.get("environment") or deployment.get("target"),
        "service": repo.get("name") or repo_full,
        "url": deployment.get("url") or payload.get("repository", {}).get("html_url") if isinstance(payload.get("repository"), dict) else None,
        "metadata": {"raw": deployment},
    }

    client = get_database_client()
    session = client.get_session()
    try:
        proj_repo = ProjectRepository(session)
        project = proj_repo.get_by_github_repo(repo_full)
        if not project:
            return

        incident_repo = IncidentRepository(session)
        recent_incidents = incident_repo.get_recent_for_project(project.id, days=14)[:10]
        if not recent_incidents:
            return

        service = DeploymentCorrelationService(session=session)
        for incident in recent_incidents:
            result = service.correlate_and_store(
                incident=incident,
                deployments=[normalized_deployment],
            )
            logger.info(
                "Deployment correlation for incident %s: score=%s trigger=%s",
                getattr(incident, "id", None),
                result.deployment_confidence_score,
                getattr(result.likely_deployment_trigger, "deployment_id", None) if result.likely_deployment_trigger else None,
            )
    except Exception as exc:
        logger.error("Failed to score recent incidents for deployment: %s", exc, exc_info=True)
    finally:
        session.close()


@router.post("/github")
async def github_webhook(request: Request, background_tasks: BackgroundTasks):
    payload = await request.body()
    if not payload:
        raise HTTPException(status_code=400, detail="Empty payload")

    config = get_config()
    secret = config.webhook.secret

    signature = request.headers.get("X-Hub-Signature-256") or request.headers.get("x-hub-signature-256")
    if not _verify_signature(secret or "", payload, signature):
        logger.warning("Invalid GitHub webhook signature")
        raise HTTPException(status_code=401, detail="Invalid signature")

    event_type = request.headers.get("X-GitHub-Event") or request.headers.get("x-github-event")
    if not event_type:
        raise HTTPException(status_code=400, detail="Missing X-GitHub-Event header")

    try:
        parsed = json.loads(payload.decode("utf-8"))
    except Exception as exc:
        logger.warning("Failed to parse GitHub webhook JSON: %s", exc)
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    supported = {"push", "pull_request", "deployment", "deployment_status", "workflow_run"}
    if event_type not in supported:
        logger.info("Received unsupported GitHub event %s; ignoring", event_type)
        return JSONResponse({"status": "ignored", "event": event_type})

    normalized = _normalize_event(event_type, parsed)

    # Persist in background to keep webhook fast
    background_tasks.add_task(_persist_event, normalized)

    if event_type == "push":
        background_tasks.add_task(_ingest_push_commits, parsed)
        background_tasks.add_task(_score_recent_incidents_for_push, parsed)

    # If deployment-related event, trigger error pipeline in background
    if event_type in ("deployment", "deployment_status"):
        repo_full = normalized.get("repo_full_name")
        # try to extract environment or target
        env = None
        payload_dep = parsed.get("deployment") or parsed.get("deployment_status") or {}
        if isinstance(payload_dep, dict):
            env = payload_dep.get("environment") or payload_dep.get("target")
        background_tasks.add_task(_trigger_pipeline, repo_full, env, None)
        background_tasks.add_task(_score_recent_incidents_for_deployment, parsed)

    logger.info("GitHub webhook received: %s repo=%s actor=%s", event_type, normalized.get("repo_full_name"), normalized.get("actor"))
    return {"status": "ok", "event": event_type}
