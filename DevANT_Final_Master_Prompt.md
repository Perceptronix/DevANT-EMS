# DevANT — Final Master Copilot Prompt
### GitHub Copilot Workspace / Edits Mode

Paste this entire file into GitHub Copilot Chat (Workspace mode). Read every section before generating code.

---

## SECTION 1 — CODEBASE REALITY (Read Before Any Code)

### Existing Classes and Their Exact Signatures

**`backend/connectors/github_connector.py` — `GitHubConnector`**
- `__init__(self, token=None)` — reads `GITHUB_TOKEN` from env
- `_headers` — includes `Authorization: Bearer {token}`, `Accept: application/vnd.github+json`, `X-GitHub-Api-Version: 2022-11-28`
- `_get(self, path, params=None)` — uses `urllib.request` (NOT httpx), returns parsed JSON or `{}`
- `_parse_repo(repo_url)` — static helper, returns `(owner, repo)` tuple or None
- `get_recent_commits(repo_url, since_hours, max_commits)` — returns `[{sha, message, author, date, url}]`
- `get_recent_prs(repo_url, since_hours, max_prs)` — returns `[{number, title, author, merged_at, url, changed_files}]`
- `get_repo_metadata(repo_url)` — returns `{name, description, default_branch, topics, language}`
- `search_related_issues(repo_url, query, max_issues)` — uses `/search/issues` endpoint
- `is_configured` — property, returns `bool(self.token)`

**`backend/connectors/slack_connector.py` — `SlackConnector`**
- `__init__(self, token=None, timeout=15.0)` — reads `SLACK_BOT_TOKEN` from env
- `async __aenter__ / __aexit__` — uses `get_async_client()` from `core.async_client_pool`
- `_request(self, method, path, params, json_body, retry_count)` — async, uses `self._client`
- `search_messages(query, channels, since_minutes, limit)` — async, returns list of messages
- `fetch_channel_history(channel_id, since_minutes, limit)` — async
- `is_configured` — property, returns `bool(self.token)`
- **IMPORTANT**: `self._client` is only available inside `async with connector:` block

**`backend/connectors/sentry_connector.py` — `SentryConnector`**
- `__init__(self, token=None, org_slug=None)` — reads `SENTRY_AUTH_TOKEN` and `SENTRY_ORG` from env
- `async __aenter__ / __aexit__` — uses `get_async_client()` from `core.async_client_pool`
- `fetch_recent_issues(project_slug, since_minutes, limit)` — async, returns list of issue dicts
- `is_configured` — property, returns `bool(self.token and self.org_slug)`

**`backend/core/root_cause_clusterer.py` — `RootCauseClusterer`**
- `__init__(self, embedding_model="all-MiniLM-L6-v2")` — loads embedder from `get_embedder()`
- `cluster_errors(errors, deployment_info=None)` — takes list of error dicts, returns `List[ErrorCluster]`
- `ErrorCluster` dataclass fields: `cluster_id`, `root_cause`, `affected_services`, `error_signatures`, `error_count`, `affected_orgs`, `severity` (S1/S2/S3/S4), `frequency_trend`, `regression_probability`, `deployment_related`, `deployment_ids`, `confidence`, `historical_matches`, `last_seen`, `topology_affected`, `evidence_score`

**`backend/pipeline/suppression_engine.py` — `SuppressionEngine`**
- `__init__(self, window_minutes=60)` — no async
- `should_suppress(cluster: Dict) -> bool` — takes a dict (not ErrorCluster dataclass), checks mute state and error count
- `filter(clusters: List[Dict]) -> List[Dict]` — returns only non-suppressed clusters

**`backend/memory/incident_graph.py` — `IncidentGraph`**
- `__init__(self)` — loads from `data/incident_graph.json` via `_load_from_disk()`
- `add_incident(incident_id, timestamp, repo, dominant_service, blast_radius, operational_confidence, regression_risk, topology_hash, ...)` — saves to disk
- `detect_recurring_patterns(incident: IncidentNode) -> Dict` — returns `{is_recurring, matched_incidents, pattern_type, recurrence_count, confidence}`
- `analyze_operational_drift(repo: str) -> Dict`

**`backend/core/async_client_pool.py`**
- `get_async_client(timeout=15.0)` — returns singleton `httpx.AsyncClient` or None
- `release_async_client()` — decrements refcount
- All connectors that use httpx MUST use this pool, not `httpx.AsyncClient()` directly

**`backend/config.py` — `Config`**
- `get_config()` — `@lru_cache`, returns singleton `Config`
- `Config.groq` — `GroqConfig(api_key, model)`, `is_configured` property
- `Config.github` — `GitHubConfig(enabled, token, owner, repo)`, `is_configured` property
- `Config.slack` — `LegacySlackConfig(enabled, api_key, channel_id, signing_secret)`, `is_configured` property
- `Config.data_source` — `DataSourceConfig(source_type, sentry_auth_token, sentry_org_slug, ...)`
- `Config.from_env()` — classmethod, reads all env vars

**`backend/state.py` — `StateManager`**
- `get_state_manager()` — returns singleton
- `is_muted(signature)` — returns bool
- `upsert_signature(signature, updates)` — persists error state

**`backend/main.py`**
- FastAPI app with `lifespan` handler
- Existing endpoints: `GET /`, `GET /api/config`, `GET /api/samples`, `GET /api/state`, `POST /api/mute`, `DELETE /api/mute/{signature}`, `POST /api/analyze-repository`, `GET /api/analyze-repository`, `GET /api/analyze-repository/{run_id}`, `GET /api/analyze-repository/{run_id}/stream`, `POST /api/analyze-repository/{run_id}/cancel`
- Uses `asyncio.create_task()` for background work
- Uses `StreamingResponse` with `text/event-stream` for SSE

---

## SECTION 2 — WHAT TO BUILD (6 Tasks in Logical Order)

### TASK 1 — Extend `GitHubConnector` with Deployment API Methods

**File: `backend/connectors/github_connector.py`**

Add the following methods to the existing `GitHubConnector` class. All methods use the existing `self._get()` helper (urllib, not httpx). All methods must fail silently and return empty lists/dicts on error.

**Method 1: `get_deployments`**
```python
def get_deployments(
    self,
    repo_url: str,
    environment: str = "production",
    per_page: int = 10,
) -> List[Dict[str, Any]]:
```
- Calls `GET /repos/{owner}/{repo}/deployments`
- Params: `environment=environment`, `per_page=per_page`
- GitHub API ref: https://docs.github.com/en/rest/deployments/deployments#list-deployments
- Returns list of dicts: `{id, sha, ref, environment, created_at, updated_at, creator_login, description, task}`
- Extracts from response: `id`, `sha`, `ref`, `environment`, `created_at`, `updated_at`, `creator.login` (safe get), `description`, `task`

**Method 2: `get_deployment_statuses`**
```python
def get_deployment_statuses(
    self,
    repo_url: str,
    deployment_id: int,
) -> List[Dict[str, Any]]:
```
- Calls `GET /repos/{owner}/{repo}/deployments/{deployment_id}/statuses`
- GitHub API ref: https://docs.github.com/en/rest/deployments/statuses#list-deployment-statuses
- Returns list of dicts: `{id, state, log_url, description, environment, created_at, creator_login}`
- `state` values: `"error"`, `"failure"`, `"inactive"`, `"in_progress"`, `"queued"`, `"pending"`, `"success"`
- Extracts: `id`, `state`, `log_url`, `description`, `environment`, `created_at`, `creator.login` (safe get)

**Method 3: `get_commit_diff`**
```python
def get_commit_diff(
    self,
    repo_url: str,
    sha: str,
) -> Dict[str, Any]:
```
- Calls `GET /repos/{owner}/{repo}/commits/{sha}`
- GitHub API ref: https://docs.github.com/en/rest/commits/commits#get-a-commit
- Returns: `{sha, message, author_name, author_date, files_changed, additions, deletions, files}`
- `files` is a list of: `{filename, status, additions, deletions, patch}` (patch truncated to 500 chars)
- `files_changed` is the count of files in the response `files` array
- Extract from response: `commit.message` (first line only), `commit.author.name`, `commit.author.date`, `stats.additions`, `stats.deletions`, `files` array

**Method 4: `get_workflow_runs`**
```python
def get_workflow_runs(
    self,
    repo_url: str,
    branch: str = "main",
    per_page: int = 5,
) -> List[Dict[str, Any]]:
```
- Calls `GET /repos/{owner}/{repo}/actions/runs`
- Params: `branch=branch`, `per_page=per_page`, `event=push`
- GitHub API ref: https://docs.github.com/en/rest/actions/workflow-runs#list-workflow-runs-for-a-repository
- Returns list from `workflow_runs` key in response
- Each item: `{id, name, status, conclusion, head_sha, head_branch, created_at, updated_at, html_url, logs_url}`
- `conclusion` values: `"success"`, `"failure"`, `"cancelled"`, `"skipped"`, `"timed_out"`, `"action_required"`, null
- Filter to only return runs where `conclusion == "failure"` or `status == "in_progress"`

**Method 5: `fetch_log_text`**
```python
def fetch_log_text(
    self,
    log_url: str,
    max_chars: int = 8000,
) -> str:
```
- Makes a GET request to `log_url` directly (not a GitHub API path, it's a full URL)
- Uses `urllib.request.Request(log_url, headers=self._headers)`
- Returns decoded text, truncated to `max_chars` from the END (the end of logs has the failure reason)
- If any exception (401, 403, timeout): log warning and return `""`
- This fetches Vercel/Render/GitHub Actions build logs

---

### TASK 2 — Create `backend/pipeline/deployment_failure_detector.py` (NEW FILE)

This is the core module. It receives a repo URL and runs the full deployment failure detection pipeline. It is synchronous (not async) because `GitHubConnector` uses `urllib` (blocking). The async wrapper is in Task 4.

```python
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
```

**Function: `detect_deployment_failures`**
```python
def detect_deployment_failures(
    repo_url: str,
    environment: str = "production",
    since_hours: int = 24,
    max_deployments: int = 10,
) -> Dict[str, Any]:
```

**Step 1 — Fetch deployments:**
- Instantiate `GitHubConnector()` (reads token from env)
- If not `connector.is_configured`: return `{"error": "GITHUB_TOKEN not configured", "deployments": [], "failures": [], "clusters": []}`
- Call `connector.get_deployments(repo_url, environment=environment, per_page=max_deployments)`
- Filter to only deployments created within `since_hours` hours using `created_at` field

**Step 2 — Find failed deployments:**
- For each deployment, call `connector.get_deployment_statuses(repo_url, deployment["id"])`
- Statuses are ordered newest-first. Take `statuses[0]` as the latest status.
- A deployment is "failed" if latest status `state` is `"failure"` or `"error"`
- A deployment is "succeeded" if latest status `state` is `"success"`
- Build a list of failed deployments: `[{deployment, latest_status}]`

**Step 3 — Enrich each failure with commit diff:**
- For each failed deployment, call `connector.get_commit_diff(repo_url, deployment["sha"])`
- This gives you exactly what code changed in the commit that triggered the failure
- Attach as `commit_diff` to the failure dict

**Step 4 — Fetch build logs:**
- For each failed deployment, get `log_url` from `latest_status["log_url"]`
- If `log_url` is not empty, call `connector.fetch_log_text(log_url, max_chars=8000)`
- Attach as `raw_log` to the failure dict

**Step 5 — Parse errors from logs:**
- Call `_parse_log_errors(raw_log, deployment)` (define this helper below)
- Attach parsed errors as `parsed_errors` list

**Step 6 — Cluster errors:**
- Collect all `parsed_errors` across all failures into one flat list
- If list is empty: generate synthetic errors from commit diffs (call `_errors_from_diff(failures)`)
- Call `RootCauseClusterer().cluster_errors(all_errors)` — import from `core.root_cause_clusterer`
- Convert `ErrorCluster` dataclass objects to dicts using `dataclasses.asdict()`

**Step 7 — Return result:**
```python
return {
    "repo": repo_url,
    "environment": environment,
    "checked_at": datetime.now(timezone.utc).isoformat(),
    "total_deployments_checked": len(deployments),
    "failed_deployments": [
        {
            "deployment_id": f["deployment"]["id"],
            "sha": f["deployment"]["sha"],
            "sha_short": f["deployment"]["sha"][:8],
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
    "clusters": clusters_as_dicts,
    "has_failures": len(failed_deployments) > 0,
    "summary": _build_summary(failed_deployments, clusters_as_dicts),
}
```

**Helper: `_parse_log_errors`**
```python
def _parse_log_errors(
    raw_log: str,
    deployment: Dict[str, Any],
) -> List[Dict[str, Any]]:
```
- If `raw_log` is empty, return `[]`
- Split log into lines
- Find lines matching these patterns (use `re` module):
  - Contains `ERROR` or `error:` (case-insensitive)
  - Contains `Exception:` or `Error:` followed by a message
  - Contains `CRITICAL` or `FATAL`
  - Contains `Build failed` or `Deployment failed`
  - Contains `Cannot find module` or `Module not found`
  - Contains `npm ERR!` or `yarn error`
  - Contains `SyntaxError` or `TypeError` or `ReferenceError`
- Deduplicate by exact line content
- Return list of dicts, one per matched line:
```python
{
    "id": f"log_{deployment['deployment']['id']}_{i}",
    "message": line.strip()[:300],
    "level": "ERROR" if any(k in line for k in ["CRITICAL", "FATAL", "Build failed"]) else "WARNING",
    "timestamp": deployment["latest_status"]["created_at"],
    "service": _infer_service_from_line(line),
    "signature": _make_signature(line),
    "stack_trace": None,
    "exception_type": _extract_exception_type(line),
    "affected_orgs": [],
    "metadata": {"source": "build_log", "deployment_id": deployment["deployment"]["id"]},
}
```

**Helper: `_errors_from_diff`**
```python
def _errors_from_diff(failures: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
```
- Called when no log errors found — synthesize errors from what changed
- For each failure, for each changed file in `commit_diff["files"]`:
  - If file has `deletions > 5` or `additions > 20`: create a synthetic error
  - `message`: `f"Deployment failure in {filename} (+{additions}/-{deletions} lines)"`
  - `signature`: `f"deployment_failure:{filename}"`
  - `level`: `"ERROR"`
  - `exception_type`: `"DeploymentFailure"`
- Return flat list

**Helper: `_infer_service_from_line`**
```python
def _infer_service_from_line(line: str) -> str:
```
- Extract service name from log line heuristically
- Look for patterns: `[service_name]`, `service/filename.py`, `at service.`
- Default: `"unknown"`

**Helper: `_extract_exception_type`**
```python
def _extract_exception_type(line: str) -> str:
```
- Match patterns: `SyntaxError`, `TypeError`, `ModuleNotFoundError`, `ReferenceError`, `BuildError`, `npm ERR`
- Return matched type or `"GenericError"`

**Helper: `_make_signature`**
```python
def _make_signature(line: str) -> str:
```
- Strip timestamps, line numbers, hex addresses from the line
- Use `re.sub` to remove: timestamps `\d{2}:\d{2}:\d{2}`, hex `0x[0-9a-f]+`, line refs `line \d+`
- Take first 80 chars of cleaned line as signature

**Helper: `_build_summary`**
```python
def _build_summary(failures: List[Dict], clusters: List[Dict]) -> str:
```
- Returns a plain string like:
  `"2 failed deployments detected. Commit ae4b8f9 introduced 6 file changes. 1 error cluster found (S2)."`
- Use actual data from the inputs

---

### TASK 3 — Add `post_alert` to `SlackConnector`

**File: `backend/connectors/slack_connector.py`**

Add this method to the `SlackConnector` class. It must work inside `async with connector:` context (uses `self._client`).

```python
async def post_alert(
    self,
    failure_result: Dict[str, Any],
    channel: Optional[str] = None,
) -> bool:
```

- `channel` defaults to `os.environ.get("SLACK_ALERT_CHANNEL", "#devant-alerts")`
- If `not self.is_configured`: log a warning `"Slack not configured, skipping alert"` and return `False`
- Build Block Kit payload:

```python
severity_emoji = {"S1": "🔴", "S2": "🟠", "S3": "🟡", "S4": "🔵"}

# Get top cluster severity
top_cluster = failure_result.get("clusters", [{}])[0] if failure_result.get("clusters") else {}
severity = top_cluster.get("severity", "S3")
emoji = severity_emoji.get(severity, "⚪")

failed = failure_result.get("failed_deployments", [])
repo = failure_result.get("repo", "unknown")
environment = failure_result.get("environment", "production")

blocks = [
    {
        "type": "header",
        "text": {
            "type": "plain_text",
            "text": f"{emoji} {severity} Deployment Failure — {repo.split('/')[-1]}",
            "emoji": True,
        }
    },
    {
        "type": "section",
        "fields": [
            {"type": "mrkdwn", "text": f"*Repository:*\n{repo}"},
            {"type": "mrkdwn", "text": f"*Environment:*\n{environment}"},
            {"type": "mrkdwn", "text": f"*Failed Deployments:*\n{len(failed)}"},
            {"type": "mrkdwn", "text": f"*Severity:*\n{severity}"},
        ]
    },
]

# Add each failed deployment as a section
for f in failed[:3]:  # max 3
    sha = f.get("sha_short", "unknown")
    msg = f.get("commit_message", "No message")[:80]
    files = f.get("files_changed", 0)
    changed = ", ".join(f.get("changed_files", [])[:3]) or "unknown files"
    log_url = f.get("log_url", "")
    link = f" <{log_url}|View Logs>" if log_url else ""
    
    blocks.append({
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": (
                f"*Commit `{sha}`:* {msg}\n"
                f"*Files changed:* {files} ({changed}){link}"
            )
        }
    })

# Add root cause from top cluster
if top_cluster.get("root_cause"):
    blocks.append({
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": f"*Root Cause Analysis:*\n{top_cluster['root_cause'][:200]}"
        }
    })

# Context footer
from datetime import datetime, timezone
blocks.append({
    "type": "context",
    "elements": [
        {
            "type": "mrkdwn",
            "text": f"DevANT | {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"
        }
    ]
})

payload = {
    "channel": channel,
    "blocks": blocks,
    "text": f"{emoji} Deployment failure in {repo} ({severity})",  # fallback
}
```

- POST to `https://slack.com/api/chat.postMessage` using `self._client.post()`
- Include header `Authorization: Bearer {self.token}`
- Check response JSON `ok` field. If `False`, log `f"Slack post failed: {data.get('error')}"` and return `False`
- Return `True` on success
- Wrap in try/except, return `False` on any exception

---

### TASK 4 — Create `backend/pipeline/error_pipeline.py` (NEW FILE)

This is the orchestration glue. It connects all the pieces in sequence.

```python
"""
Error Pipeline — connects deployment failure detection to alert output.

Called either by:
  1. The GitHub webhook handler (Task 5) when a deployment_status event arrives
  2. The manual trigger endpoint (Task 5) for on-demand scanning

This pipeline is async. The deployment failure detector (Task 2) is sync,
so it runs in an executor to avoid blocking the event loop.
"""
```

**Function: `run_error_pipeline`**
```python
async def run_error_pipeline(
    repo_url: str,
    environment: str = "production",
    log_url: Optional[str] = None,
    since_hours: int = 24,
) -> Dict[str, Any]:
```

**Step 1 — Run deployment failure detection (in executor):**
```python
import asyncio
from pipeline.deployment_failure_detector import detect_deployment_failures

loop = asyncio.get_event_loop()
result = await loop.run_in_executor(
    None,
    lambda: detect_deployment_failures(repo_url, environment, since_hours)
)
```
- If `result.get("error")`: log warning and return result immediately

**Step 2 — If no failures found, return early:**
```python
if not result.get("has_failures"):
    logger.info(f"No failures detected for {repo_url} in {environment}")
    result["alerted"] = False
    result["suppressed"] = False
    return result
```

**Step 3 — Run suppression check on clusters:**
```python
from pipeline.suppression_engine import SuppressionEngine
engine = SuppressionEngine()
clusters = result.get("clusters", [])
active_clusters = engine.filter(clusters)
suppressed_count = len(clusters) - len(active_clusters)
```

**Step 4 — Post Slack alert if any clusters survived suppression:**
```python
alerted = False
if active_clusters:
    result["clusters"] = active_clusters  # update with non-suppressed only
    
    from connectors.slack_connector import SlackConnector
    connector = SlackConnector()
    if connector.is_configured:
        async with connector:
            alerted = await connector.post_alert(result)
    else:
        logger.info("Slack not configured — skipping alert (log-only mode)")
        alerted = False
```

**Step 5 — Record to IncidentGraph:**
```python
from memory.incident_graph import IncidentGraph
import hashlib

try:
    graph = IncidentGraph()
    for cluster in active_clusters:
        incident_id = cluster.get("cluster_id", f"inc_{int(datetime.now().timestamp())}")
        graph.add_incident(
            incident_id=incident_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
            repo=repo_url,
            dominant_service=cluster.get("affected_services", ["unknown"])[0],
            blast_radius=cluster.get("error_count", 1),
            operational_confidence=cluster.get("confidence", 0.5),
            regression_risk=cluster.get("regression_probability", 0.3),
            topology_hash=hashlib.md5(
                ",".join(sorted(cluster.get("affected_services", []))).encode()
            ).hexdigest()[:8],
        )
except Exception as exc:
    logger.warning(f"IncidentGraph update failed (non-fatal): {exc}")
```

**Step 6 — Return enriched result:**
```python
result["alerted"] = alerted
result["suppressed_count"] = suppressed_count
result["active_cluster_count"] = len(active_clusters)
result["pipeline_completed_at"] = datetime.now(timezone.utc).isoformat()
return result
```

All steps wrapped in try/except at the function level. On any unhandled exception:
```python
logger.error(f"Error pipeline failed for {repo_url}: {exc}", exc_info=True)
return {
    "repo": repo_url,
    "environment": environment,
    "error": str(exc),
    "has_failures": False,
    "alerted": False,
}
```

---

### TASK 5 — Add Webhook + Live Errors Endpoints to `backend/main.py`

**DO NOT modify any existing endpoint. Only add new code.**

**Add module-level state store (after existing imports, before `app = FastAPI(...)`):**
```python
import hashlib
import hmac
from typing import Dict

# In-memory store for latest pipeline results per repo
# Key: repo_full_name (e.g. "Nandeesh71/watchtoower")
_pipeline_results: Dict[str, Dict] = {}
```

**Add background task function (before the `@app.get("/")` route):**
```python
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
```

**Add webhook endpoint:**
```python
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
```

**Note on import:** Add `from fastapi import Request` to the existing FastAPI imports at the top of `main.py`.

**Add manual trigger endpoint:**
```python
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
    import re
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
```

**Add live errors read endpoint:**
```python
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
```

**Add live errors SSE stream endpoint:**
```python
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
            yield "event: timeout\ndata: {\"error\": \"scan timeout\"}\n\n"
    
    return StreamingResponse(event_generator(), media_type="text/event-stream")
```

---

### TASK 6 — Update `backend/config.py`

**Add new dataclass (after existing `LegacySlackConfig`, before `Config`):**
```python
@dataclass
class WebhookConfig:
    """GitHub webhook configuration."""
    secret: Optional[str] = None
    
    @property
    def is_configured(self) -> bool:
        return bool(self.secret)
```

**Add `webhook: WebhookConfig` field to `Config` dataclass.**

**In `Config.from_env()`, add:**
```python
cfg.webhook = WebhookConfig(
    secret=os.getenv("GITHUB_WEBHOOK_SECRET"),
)
```

**Also add `SLACK_ALERT_CHANNEL` reading to the existing Slack config population:**
```python
cfg.slack = LegacySlackConfig(
    enabled=os.getenv("SLACK_ENABLED", "false").lower() == "true",
    api_key=os.getenv("SLACK_BOT_TOKEN"),
    channel_id=os.getenv("SLACK_CHANNEL_ID") or os.getenv("SLACK_ALERT_CHANNEL", "#devant-alerts"),
    signing_secret=os.getenv("SLACK_SIGNING_SECRET"),
)
```

---

## SECTION 3 — .env.example UPDATE

Append these lines to `.env.example`. Do not remove existing lines.

```bash
# =====================================================
# DevANT Deployment Failure Detection
# =====================================================

# GitHub Webhook Secret
# Set this in GitHub: repo → Settings → Webhooks → Secret
# Must match EXACTLY — copy-paste, no trailing spaces
GITHUB_WEBHOOK_SECRET=your_webhook_secret_here

# Slack Alert Output
# Bot Token: Slack App → OAuth & Permissions → Bot User OAuth Token
# Scopes needed: chat:write, channels:read
SLACK_BOT_TOKEN=xoxb-your-bot-token-here
SLACK_ALERT_CHANNEL=#devant-alerts

# GitHub Token (required for deployment API access)
# Scopes needed: repo (for private), public_repo (for public)
GITHUB_TOKEN=ghp_your_token_here
```

---

## SECTION 4 — LOGICAL FLOW DIAGRAM (For Copilot Reference)

```
TRIGGER A: GitHub sends POST /webhook/github
  └── X-GitHub-Event: deployment_status + state: failure
       └── extract repo_full_name, environment, log_url
            └── asyncio.create_task(_run_error_pipeline_bg(...))
                 └── returns {"status": "processing"} immediately

TRIGGER B: POST /api/scan-repo
  └── extract owner/repo from URL
       └── asyncio.create_task(_run_error_pipeline_bg(...))
            └── returns {"status": "scanning", "check_result_at": "..."} immediately

BACKGROUND: _run_error_pipeline_bg(repo_full_name, environment, log_url)
  └── builds repo_url = f"https://github.com/{repo_full_name}"
       └── await run_error_pipeline(repo_url, environment, log_url)
            └── [executor] detect_deployment_failures(repo_url, environment)
                 ├── GitHubConnector.get_deployments()
                 │    └── GET /repos/{owner}/{repo}/deployments?environment=production
                 ├── GitHubConnector.get_deployment_statuses(deployment_id)
                 │    └── GET /repos/{owner}/{repo}/deployments/{id}/statuses
                 │         └── state == "failure" or "error" → mark as failed
                 ├── GitHubConnector.get_commit_diff(sha)
                 │    └── GET /repos/{owner}/{repo}/commits/{sha}
                 │         └── files changed, additions, deletions, patch
                 ├── GitHubConnector.fetch_log_text(log_url)
                 │    └── GET log_url directly
                 │         └── parse ERROR/Exception lines
                 ├── RootCauseClusterer.cluster_errors(all_parsed_errors)
                 │    └── semantic embedding + fingerprint clustering
                 │         └── returns ErrorCluster list with severity S1-S4
                 └── returns structured result dict
            └── SuppressionEngine.filter(clusters)
                 └── removes muted / low-confidence / transient clusters
            └── SlackConnector.post_alert(result)
                 └── POST https://slack.com/api/chat.postMessage
                      └── Block Kit message with severity, commit, files, root cause
            └── IncidentGraph.add_incident(...)
                 └── persists to data/incident_graph.json
            └── stores result in _pipeline_results[repo_full_name]

FRONTEND POLLING: GET /api/live-errors/{repo}/stream (SSE)
  └── polls _pipeline_results every 1s
       └── emits event: update when result arrives
            └── event: done when pipeline_completed_at is set
```

---

## SECTION 5 — CONSTRAINTS (Non-Negotiable)

1. `GitHubConnector._get()` uses `urllib.request`, NOT httpx. All new methods in `GitHubConnector` must use `self._get()`.
2. `SlackConnector.post_alert()` uses `self._client` (httpx). It MUST be called inside `async with connector:` block. The pipeline does this correctly in Task 4.
3. Do NOT close the shared async client. Use `get_async_client()` and `release_async_client()` from `core.async_client_pool`. Never call `httpx.AsyncClient()` directly in a connector.
4. Do NOT modify `backend/pipeline/unified_orchestrator.py` or `backend/orchestrator/unified_orchestrator.py`.
5. Do NOT modify any existing endpoint in `main.py`.
6. All new code: wrap in try/except. Log errors. Never raise unhandled exceptions in background tasks.
7. The pipeline must work even when Sentry, Slack, and webhook secret are NOT configured. GitHub token alone is sufficient to detect failures.
8. `SuppressionEngine.should_suppress()` and `filter()` take `Dict`, not `ErrorCluster` dataclass. Use `dataclasses.asdict()` when converting.

---

## SECTION 6 — VALIDATION TESTS

Run these after implementation. All must pass.

```bash
cd backend

# Test 1: Import chain — no circular imports, no missing modules
python -c "
from connectors.github_connector import GitHubConnector
from pipeline.deployment_failure_detector import detect_deployment_failures
from pipeline.error_pipeline import run_error_pipeline
from connectors.slack_connector import SlackConnector
print('All imports OK')
"

# Test 2: GitHubConnector new methods exist
python -c "
from connectors.github_connector import GitHubConnector
c = GitHubConnector()
assert hasattr(c, 'get_deployments'), 'get_deployments missing'
assert hasattr(c, 'get_deployment_statuses'), 'get_deployment_statuses missing'
assert hasattr(c, 'get_commit_diff'), 'get_commit_diff missing'
assert hasattr(c, 'get_workflow_runs'), 'get_workflow_runs missing'
assert hasattr(c, 'fetch_log_text'), 'fetch_log_text missing'
print('GitHubConnector methods OK')
"

# Test 3: SlackConnector post_alert exists
python -c "
from connectors.slack_connector import SlackConnector
import inspect
assert 'post_alert' in dir(SlackConnector), 'post_alert missing'
sig = inspect.signature(SlackConnector.post_alert)
assert 'failure_result' in sig.parameters, 'failure_result param missing'
print('SlackConnector.post_alert OK')
"

# Test 4: Log parser works
python -c "
from pipeline.deployment_failure_detector import _parse_log_errors
fake_log = '''
2026-05-09 12:00:01 Starting build...
2026-05-09 12:00:05 ERROR: Cannot find module ./components/Header
2026-05-09 12:00:05 npm ERR! Build failed with exit code 1
2026-05-09 12:00:06 Deployment failed
'''
fake_dep = {'deployment': {'id': 1}, 'latest_status': {'created_at': '2026-05-09T12:00:00Z'}}
errors = _parse_log_errors(fake_log, fake_dep)
assert len(errors) >= 2, f'Expected >= 2 errors, got {len(errors)}'
assert all('message' in e for e in errors), 'Missing message field'
assert all('signature' in e for e in errors), 'Missing signature field'
print(f'Log parser OK — found {len(errors)} errors')
"

# Test 5: Config loads new webhook field
python -c "
import os
os.environ['GITHUB_WEBHOOK_SECRET'] = 'test_secret_123'
from config import reload_config
c = reload_config()
assert hasattr(c, 'webhook'), 'webhook config missing'
print('Config OK')
"

# Test 6: Webhook HMAC validation logic
python -c "
import hmac as _hmac, hashlib
secret = b'test_secret_123'
body = b'{\"action\": \"created\"}'
sig = 'sha256=' + _hmac.new(secret, body, hashlib.sha256).hexdigest()
assert sig.startswith('sha256='), 'Bad signature format'
valid = _hmac.compare_digest(sig, sig)
assert valid, 'HMAC compare failed'
print('HMAC logic OK — sig:', sig[:30], '...')
"

# Test 7: Server starts and new endpoints are registered
uvicorn main:app --host 0.0.0.0 --port 8001 &
SERVER_PID=$!
sleep 4

curl -s http://localhost:8001/api/live-errors/Nandeesh71/watchtoower | python3 -c "
import sys, json
d = json.load(sys.stdin)
assert 'status' in d or 'repo' in d, 'Bad response'
print('GET /api/live-errors OK:', d.get('status'))
"

curl -s -X POST http://localhost:8001/webhook/github \
  -H "Content-Type: application/json" \
  -H "X-GitHub-Event: ping" \
  -d '{"zen": "Non-blocking is better than blocking."}' | python3 -c "
import sys, json
d = json.load(sys.stdin)
assert d.get('status') == 'pong', f'Expected pong, got {d}'
print('POST /webhook/github ping OK')
"

curl -s -X POST http://localhost:8001/api/scan-repo \
  -H "Content-Type: application/json" \
  -d '{\"repo_url\": \"Nandeesh71/watchtoower\", \"environment\": \"production\"}' | python3 -c "
import sys, json
d = json.load(sys.stdin)
assert d.get('status') == 'scanning', f'Expected scanning, got {d}'
print('POST /api/scan-repo OK:', d.get('check_result_at'))
"

kill $SERVER_PID 2>/dev/null
echo ""
echo "All 7 tests passed. DevANT deployment failure detection is ready."
```

---

## SECTION 7 — FILES TO CREATE OR MODIFY

| File | Action |
|---|---|
| `backend/connectors/github_connector.py` | ADD 5 methods to `GitHubConnector` |
| `backend/pipeline/deployment_failure_detector.py` | CREATE new file |
| `backend/pipeline/error_pipeline.py` | CREATE new file |
| `backend/connectors/slack_connector.py` | ADD `post_alert` method to `SlackConnector` |
| `backend/main.py` | ADD `_pipeline_results`, `_run_error_pipeline_bg`, 4 new endpoints, `Request` import |
| `backend/config.py` | ADD `WebhookConfig` dataclass, add to `Config`, update `from_env()` |
| `.env.example` | APPEND new variables |

Do not create any other files. Do not modify `unified_orchestrator.py`, `repo_analyzer.py`, or any existing endpoint.
