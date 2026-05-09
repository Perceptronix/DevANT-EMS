"""
FastAPI backend for the Error Monitoring Agent demo.

This demo showcases how to build intelligent error monitoring with Airweave.
It features:
- Pluggable data sources (sample data by default, Sentry/Azure optional)
- LLM-powered semantic clustering
- Airweave context search for related code and tickets
- Smart suppression logic (NEW/REGRESSION/ONGOING)
- Optional GitHub Issues and Slack integrations with preview fallbacks
"""
import os
from dotenv import load_dotenv
load_dotenv()
import asyncio
import json
import logging
import os
import re
from contextlib import asynccontextmanager
from datetime import datetime
from typing import List, Dict, Any, Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

# Import our modules
from config import get_config
from state import get_state_manager
from sources import get_data_source, get_available_sources
from samples import get_sample_errors
from pipeline import ErrorClusterer, ContextSearcher, ErrorAnalyzer, get_action_executor
from core.scoring import severity_priority
from repository.repo_analyzer import analyze_repository
from app.api.routes.health_routes import router as health_router
from repository.analysis_state import (
    create_run,
    fail_run,
    get_run_snapshot,
    cancel_run,
    list_runs,
    transition_run,
    set_partial_update,
    finalize_run,
)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# --- Pipeline results storage ---
import hashlib
import hmac
from typing import Dict

# In-memory store for latest pipeline results per repo
# Key: repo_full_name (e.g. "Nandeesh71/watchtoower")
_pipeline_results: Dict[str, Dict] = {}


async def _run_error_pipeline_bg(
    repo_full_name: str,
    environment: str,
    log_url: Optional[str],
) -> None:
    """Background task: runs error pipeline and stores result."""
    try:
        from pipeline.error_pipeline import run_error_pipeline
        
        # Convert owner/repo to full GitHub URL
        repo_url = f"https://github.com/{repo_full_name}"
        
        result = await run_error_pipeline(
            repo_url=repo_url,
            environment=environment,
            log_url=log_url,
        )
        
        _pipeline_results[repo_full_name] = result
        logger.info(
            f"[{repo_full_name}] Pipeline done — "
            f"failures={result.get('has_failures')}, "
            f"alerted={result.get('alerted')}"
        )
    except Exception as exc:
        logger.error(f"[{repo_full_name}] Background pipeline error: {exc}", exc_info=True)
        _pipeline_results[repo_full_name] = {
            "repo": repo_full_name,
            "error": str(exc),
            "has_failures": False,
            "alerted": False,
        }


# --- Removed old Pipeline Execution and ConnectionManager ---


def _generate_actionable_title(analysis: Dict[str, Any]) -> str:
    """Generate a human-readable, actionable title from analysis data."""
    # Use LLM-generated title if available (from analysis step)
    if analysis.get("title"):
        return analysis["title"]
    
    # Fallback: pattern matching for common error types
    signature = analysis.get("signature", "").lower()
    
    if "429" in signature or "rate limit" in signature:
        if "google" in signature or "drive" in signature:
            return "Google Drive API rate limits exceeded"
        elif "dropbox" in signature:
            return "Dropbox API rate limits exceeded"
        elif "slack" in signature:
            return "Slack API rate limits exceeded"
        return "External API rate limiting errors"
    
    if "database" in signature or "connection pool" in signature or "postgres" in signature or "sqlalchemy" in signature:
        if "pool" in signature or "exhaust" in signature:
            return "Database connection pool exhausted"
        if "timeout" in signature:
            return "Database connection timeouts"
        return "Database connectivity issues"
    
    if "401" in signature or "oauth" in signature or "token" in signature or "unauthorized" in signature:
        if "refresh" in signature or "expired" in signature or "revoked" in signature:
            return "OAuth tokens expired - users need to reconnect"
        return "Authentication failures with external service"
    
    if "pdf" in signature or "corrupt" in signature or "parse" in signature:
        return "Document processing failures"
    
    if "memory" in signature or "oom" in signature:
        return "Worker memory limit exceeded"
    
    if "timeout" in signature or "504" in signature:
        return "Request timeouts on external API calls"
    
    if "502" in signature or "503" in signature or "bad gateway" in signature:
        return "Upstream service unavailable"
    
    # Fallback: extract module/function info
    modules = analysis.get("modules", [])
    if modules:
        module = modules[0].replace("_", " ").replace(".", " ")
        return f"Errors in {module}"
    
    return "Production error requiring investigation"


def _generate_slack_preview(analysis: Dict[str, Any]) -> Dict[str, Any]:
    """Generate a Slack message preview."""
    severity_icon = {
        "S1": "🔴",
        "S2": "🟠", 
        "S3": "🟡",
        "S4": "🔵"
    }
    
    title = _generate_actionable_title(analysis)
    
    return {
        "blocks": [
            {
                "type": "header",
                "text": f"{severity_icon.get(analysis['severity'], '⚪')} {analysis['severity']}: {title}"
            },
            {
                "type": "section",
                "text": analysis.get("root_cause", "Error detected in production")
            },
            {
                "type": "context",
                "text": f"Affected: {', '.join(analysis.get('affected_orgs', ['Unknown']))}"
            }
        ]
    }


def _generate_github_issue_preview(analysis: Dict[str, Any]) -> Dict[str, Any]:
    """Generate a GitHub issue preview."""
    title = _generate_actionable_title(analysis)
    
    return {
        "title": f"[{analysis['severity']}] {title}",
        "description": f"""## Summary
{analysis.get('root_cause', 'Error detected')}

## Impact
- Organizations affected: {len(analysis.get('affected_orgs', []))}
- Severity: {analysis['severity']}

## Suggested Action
{analysis.get('suggested_action', 'Investigate and resolve')}
""",
        "priority": severity_priority(analysis["severity"]),
        "labels": ["bug", "monitoring", analysis["severity"].lower()]
    }


# --- FastAPI App ---

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    logger.info("Starting Error Monitoring Agent Demo...")
    yield
    logger.info("Shutting down...")


app = FastAPI(
    title="Error Monitoring Agent Demo",
    description="Intelligent error monitoring with LLM clustering and Airweave search",
    version="1.0.0",
    lifespan=lifespan
)

app.include_router(health_router)

# CORS middleware for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify your frontend URL
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class MuteRequest(BaseModel):
    """Request to mute an error signature."""
    signature: str
    duration_hours: int = 24
    reason: Optional[str] = None


@app.post("/api/mute")
async def mute_error(request: MuteRequest):
    """
    Mute an error signature for a specified duration.
    
    Muted errors will be suppressed and not trigger alerts.
    """
    state = get_state_manager()
    state.add_mute(
        signature=request.signature,
        duration_hours=request.duration_hours,
        reason=request.reason,
    )
    
    return {
        "status": "muted",
        "signature": request.signature,
        "duration_hours": request.duration_hours,
    }


@app.delete("/api/mute/{signature:path}")
async def unmute_error(signature: str):
    """Remove a mute for an error signature."""
    state = get_state_manager()
    state.remove_mute(signature)
    
    return {
        "status": "unmuted",
        "signature": signature,
    }





class RepoAnalyzeRequest(BaseModel):
    repo_url: str
    local_path: str | None = None
    include_live_errors: bool = True


@app.post("/api/analyze-repository")
async def analyze_repository_endpoint(req: RepoAnalyzeRequest):
    """Start async repository analysis via UnifiedOrchestrator. Returns run_id."""
    run_id = create_run(req.repo_url)
    logger.info(f"[{run_id}] Analysis created for: {req.repo_url}")

    async def _bg():
        try:
            logger.info(f"[{run_id}] BG TASK STARTED")
            loop = asyncio.get_event_loop()

            def _sync():
                logger.info(f"[{run_id}] Running UnifiedOrchestrator...")

                # Map orchestrator steps → canonical stage IDs for SSE / partial state
                step_to_stage = {
                    'started':              'repository_ingestion',
                    'ingesting_errors':     'repository_ingestion',
                    'github_enriched':      'repository_ingestion',
                    'github_sample':        'repository_ingestion',
                    'scanning_repository':  'repository_ingestion',
                    'scanned_files':        'repository_ingestion',
                    'repository_classified':'workflow_discovery',
                    'enriching_context':    'workflow_discovery',
                    'workflows_extracted':  'workflow_discovery',
                    'deployments_correlated':'deployment_analysis',
                    'observability_checked': 'observability_analysis',
                    'topology':             'topology_inference',
                    'assessing_health':     'topology_propagation',
                    'scored':               'operational_scoring',
                    'temporal_analyzed':    'regression_risk_analysis',
                    'live_errors_ingested': 'confidence_calibration',
                    'generating_brief':     'final_operational_synthesis',
                    'synthesis_complete':   'final_operational_synthesis',
                    'completed':            'final_operational_synthesis',
                    'error':                'final_operational_synthesis',
                }

                def progress_callback(step: str, payload: dict):
                    logger.info(f"[{run_id}] PROGRESS: step={step}")
                    stage_id = step_to_stage.get(step, step)

                    # State machine transitions
                    try:
                        if step == 'started':
                            transition_run(run_id, 'INITIALIZING', 'Started')
                        elif step in ('github_sample', 'scanned_files', 'ingesting_errors',
                                      'github_enriched', 'scanning_repository'):
                            transition_run(run_id, 'INGESTING', f'Progress in {stage_id}')
                        elif step in ('topology', 'assessing_health', 'enriching_context',
                                      'repository_classified'):
                            transition_run(run_id, 'ANALYZING', f'Progress in {stage_id}')
                        elif step in ('scored', 'temporal_analyzed', 'live_errors_ingested'):
                            transition_run(run_id, 'SCORING', f'Progress in {stage_id}')
                        elif step in ('generating_brief', 'synthesis_complete', 'completed'):
                            transition_run(run_id, 'FINALIZING', f'Completed {stage_id}')
                        elif step == 'error':
                            transition_run(run_id, 'FAILED', f'Error in {stage_id}')
                    except Exception as exc:
                        logger.error(f"[{run_id}] State transition error at {step}: {exc}")

                    # Store partial update for progressive SSE rendering
                    try:
                        set_partial_update(run_id, stage_id, {
                            'stage': stage_id,
                            'step': step,
                            'evidence': payload,
                        })
                    except Exception as exc:
                        logger.error(f"[{run_id}] Partial update error at {stage_id}: {exc}")

                try:
                    from pipeline.unified_orchestrator import UnifiedOrchestrator
                    from pipeline.db_persistence import persist_orchestrator_result
                    orch = UnifiedOrchestrator()
                    result = orch.run(
                        repo_url=req.repo_url,
                        run_id=run_id,
                        progress_callback=progress_callback,
                        local_path=req.local_path,
                    )
                    logger.info(f"[{run_id}] Orchestrator completed successfully.")
                    
                    # Persist result to database
                    persist_counts = persist_orchestrator_result(run_id, result)
                    logger.info(f"[{run_id}] DB persistence: {persist_counts}")
                    
                    finalize_run(run_id, result)
                    logger.info(f"[{run_id}] Run finalized.")
                except Exception as exc:
                    logger.exception(f"[{run_id}] Orchestrator exception: {exc}")
                    raise

            await loop.run_in_executor(None, _sync)
            logger.info(f"[{run_id}] BG TASK COMPLETED SUCCESSFULLY")
        except Exception as exc:
            logger.error(f"[{run_id}] BG TASK FAILED: {exc}", exc_info=True)
            fail_run(run_id, str(exc))

    asyncio.create_task(_bg())
    return {"run_id": run_id, "status": "started"}


@app.get("/api/analyze-repository/{run_id}")
async def get_analysis(run_id: str):
    return get_run_snapshot(run_id)


@app.get("/api/analyze-repository")
async def get_recent_analyses(limit: int = 20):
    return {"runs": list_runs(limit=limit)}


@app.post("/api/analyze-repository/{run_id}/cancel")
async def cancel_analysis(run_id: str):
    snap = get_run_snapshot(run_id)
    if snap.get("status") == "not_found":
        raise HTTPException(status_code=404, detail="run_id not found")
    try:
        cancel_run(run_id, "user_request")
    except Exception:
        # terminal states return current snapshot
        pass
    return get_run_snapshot(run_id)


@app.get("/api/analyze-repository/{run_id}/stream")
async def stream_analysis(run_id: str):
    """SSE stream for analysis run snapshots. Emits only on state changes."""

    async def event_generator():
        last_sig = None
        while True:
            snap = get_run_snapshot(run_id)
            if snap.get("status") == "not_found":
                yield "event: error\ndata: {\"error\":\"not_found\"}\n\n"
                break

            # Create signature including partial values to detect any changes
            partial_sigs = {}
            for stage_id, partial_data in (snap.get("partial") or {}).items():
                if isinstance(partial_data, dict):
                    # Include evidence/progress values to detect updates
                    partial_sigs[stage_id] = json.dumps({
                        'state': partial_data.get('state'),
                        'progress_keys': sorted(list((partial_data.get('progress') or {}).keys())) if partial_data.get('progress') else [],
                        'evidence_keys': sorted(list((partial_data.get('evidence') or {}).keys())) if partial_data.get('evidence') else [],
                    }, sort_keys=True)
            
            sig = json.dumps({
                "state": snap.get("state"),
                "transitions": len(snap.get("transitions", [])),
                "partial_keys": sorted(list((snap.get("partial") or {}).keys())),
                "partial_sigs": partial_sigs,
                "result": bool(snap.get("result_snapshot")),
            }, sort_keys=True)

            if sig != last_sig:
                payload = json.dumps(snap)
                yield f"event: update\ndata: {payload}\n\n"
                last_sig = sig

            if snap.get("state") in ("COMPLETED", "FAILED", "CANCELLED"):
                break

            await asyncio.sleep(0.5)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


# ====================================================================
# DEPLOYMENT FAILURE DETECTION: GitHub Webhook + Live Errors Endpoints
# ====================================================================


@app.post("/webhook/github")
async def github_webhook(request: Request):
    """
    Receives GitHub deployment_status and push webhook events.
    
    GitHub sends this whenever:
    - A deployment changes state (success, failure, error)
    - A push is made to any branch
    
    Setup: In your GitHub repo → Settings → Webhooks → Add webhook
    Payload URL: https://your-devant-server/webhook/github
    Content type: application/json
    Events: Deployment statuses, Pushes
    Secret: Set GITHUB_WEBHOOK_SECRET in your .env
    """
    # Read raw body for HMAC validation
    body = await request.body()
    
    # Validate HMAC signature if secret is configured
    webhook_secret = os.environ.get("GITHUB_WEBHOOK_SECRET", "")
    if webhook_secret:
        sig_header = request.headers.get("X-Hub-Signature-256", "")
        if not sig_header.startswith("sha256="):
            logger.warning("Webhook received without X-Hub-Signature-256 header")
            raise HTTPException(status_code=401, detail="Missing signature")
        
        expected_sig = "sha256=" + hmac.new(
            webhook_secret.encode("utf-8"),
            body,
            hashlib.sha256,
        ).hexdigest()
        
        # Use hmac.compare_digest to prevent timing attacks
        if not hmac.compare_digest(expected_sig, sig_header):
            logger.warning("Webhook HMAC validation failed")
            raise HTTPException(status_code=401, detail="Invalid signature")
    
    # Parse event type
    event_type = request.headers.get("X-GitHub-Event", "")
    
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")
    
    repo_full_name = payload.get("repository", {}).get("full_name", "")
    if not repo_full_name:
        return {"status": "ignored", "reason": "no repository in payload"}
    
    # Handle deployment_status events
    if event_type == "deployment_status":
        state = payload.get("deployment_status", {}).get("state", "")
        environment = payload.get("deployment", {}).get("environment", "production")
        log_url = payload.get("deployment_status", {}).get("log_url", "")
        
        logger.info(
            f"Deployment status event: {repo_full_name} | "
            f"env={environment} | state={state}"
        )
        
        # Only process failure and error states
        if state in ("failure", "error"):
            asyncio.create_task(
                _run_error_pipeline_bg(repo_full_name, environment, log_url)
            )
            return {"status": "processing", "repo": repo_full_name, "state": state}
        
        return {"status": "ignored", "reason": f"state={state} not a failure"}
    
    # Handle push events — scan for failures after any push
    elif event_type == "push":
        ref = payload.get("ref", "")
        # Only process pushes to main/master
        if ref in ("refs/heads/main", "refs/heads/master"):
            logger.info(f"Push event to main: {repo_full_name}")
            asyncio.create_task(
                _run_error_pipeline_bg(repo_full_name, "production", None)
            )
            return {"status": "processing", "repo": repo_full_name, "event": "push"}
        return {"status": "ignored", "reason": f"push to {ref} (not main/master)"}
    
    # Ping event — GitHub sends this when webhook is first created
    elif event_type == "ping":
        return {"status": "pong", "message": "DevANT webhook connected successfully"}
    
    # All other events
    return {"status": "ignored", "event": event_type}


class ScanRequest(BaseModel):
    repo_url: str
    environment: str = "production"


@app.post("/api/scan-repo")
async def trigger_scan(req: ScanRequest):
    """
    Manually trigger deployment failure scan for a repo.
    
    Use this to test without waiting for a webhook, or to scan on demand.
    Returns run_id immediately; check /api/live-errors/{repo} for result.
    """
    # Extract owner/repo from URL
    parsed = None
    m = re.match(r"https?://github\.com/([^/]+)/([^/]+?)(?:\.git)?$", req.repo_url)
    if m:
        parsed = f"{m.group(1)}/{m.group(2)}"
    else:
        m2 = re.match(r"^([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)$", req.repo_url)
        if m2:
            parsed = req.repo_url
    
    if not parsed:
        raise HTTPException(status_code=400, detail="Invalid repo URL or owner/repo format")
    
    asyncio.create_task(
        _run_error_pipeline_bg(parsed, req.environment, None)
    )
    
    return {
        "status": "scanning",
        "repo": parsed,
        "environment": req.environment,
        "check_result_at": f"/api/live-errors/{parsed}",
    }


@app.get("/api/live-errors/{repo_full_name:path}")
async def get_live_errors(repo_full_name: str):
    """
    Get the latest error scan result for a repo.
    
    Returns the most recent pipeline result, or status=no_data if not scanned yet.
    """
    result = _pipeline_results.get(repo_full_name)
    if not result:
        return {
            "status": "no_data",
            "repo": repo_full_name,
            "message": "No scan has run yet. Trigger one via POST /api/scan-repo or wait for a webhook.",
        }
    return result


@app.get("/api/live-errors/{repo_full_name:path}/stream")
async def stream_live_errors(repo_full_name: str):
    """
    SSE stream for live error scan results.
    
    Emits an update event when the pipeline result changes.
    Closes automatically when result arrives (one-shot stream).
    Frontend connects to this after triggering /api/scan-repo.
    """
    async def event_generator():
        last_sig = None
        poll_count = 0
        max_polls = 120  # 2 minutes max (120 * 1s)
        
        while poll_count < max_polls:
            result = _pipeline_results.get(repo_full_name)
            
            if result:
                # Build a change signature
                sig = f"{result.get('has_failures')}:{result.get('pipeline_completed_at', '')}:{result.get('error', '')}"
                
                if sig != last_sig:
                    payload = json.dumps(result)
                    yield f"event: update\ndata: {payload}\n\n"
                    last_sig = sig
                    
                    # If pipeline is done (has result), close after sending
                    if result.get("pipeline_completed_at") or result.get("error"):
                        yield "event: done\ndata: {}\n\n"
                        break
            else:
                # Still scanning
                yield f"event: scanning\ndata: {{\"repo\": \"{repo_full_name}\", \"status\": \"scanning\"}}\n\n"
            
            poll_count += 1
            await asyncio.sleep(1)
        
        if poll_count >= max_polls:
            yield "event: timeout\ndata: {{\"error\": \"scan timeout\"}}\n\n"
    
    return StreamingResponse(event_generator(), media_type="text/event-stream")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
