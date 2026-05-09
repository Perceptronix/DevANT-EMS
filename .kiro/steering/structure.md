# Project Structure

## Top-Level Layout

```
backend/        Python FastAPI backend
frontend/       React/TypeScript frontend
docs/           Architecture and configuration docs
.env.example    All available environment variables
README.md       Setup and usage guide
```

## Backend (`backend/`)

| Path | Purpose |
|------|---------|
| `main.py` | FastAPI app entry point — routes, WebSocket, pipeline orchestration |
| `config.py` | Centralized config via env vars; use `get_config()` singleton |
| `schemas.py` | All Pydantic v2 data models shared across the app |
| `state.py` | JSON-based state persistence; use `get_state_manager()` singleton |
| `pipeline/` | Core processing stages: clustering → search → analysis → actions |
| `core/` | Pure logic utilities: scoring, normalization, identity, confidence, signal fusion |
| `memory/` | Regression detection, incident graphs, hybrid search, evidence building |
| `observability/` | Metrics, traces, deployment tracking, anomaly detection, service topology |
| `sources/` | Data source adapters (`base.py` defines the interface) |
| `clients/` | External API clients: Airweave, Linear, Slack, ChromaDB |
| `repository/` | GitHub repo analysis and analysis state tracking |
| `ontology/` | Domain models (`Incident`, `RCAHypothesis`) and ontology definitions |
| `contracts/` | Typed contracts for analysis, evidence, memory, regression, retrieval |
| `samples/` | Sample error data for demo mode |
| `datasets/` | Incident corpus and replay engine for testing |
| `data/` | Runtime data — JSON state files and ChromaDB persistence (gitignored except `.gitkeep`) |
| `tests/` | pytest test suite (80+ tests across 4 modules) |
| `scripts/` | One-off utility scripts (ingestion, debugging) |

## Data Model Hierarchy (`schemas.py`)

The pipeline transforms data through a strict inheritance chain:

```
RawError                    ← normalized input from any source
  └── ErrorCluster          ← after clustering (groups similar RawErrors)
        └── EnrichedError   ← after context search (adds code/tickets/docs)
              └── AnalyzedError  ← after analysis (adds severity, status, suppression)
                    └── ErrorResult  ← final output (adds Linear/Slack action results)
```

Key models:
- `RawError` — normalized error from any source (id, timestamp, message, module, org_id, stack_trace)
- `ErrorCluster` — grouped errors with signature, error_count, affected_orgs, sample_messages
- `PreviousErrorState` — history from JSON state (linear_issue_id, slack_thread_ts, muted_until, last_alerted)
- `AnalyzedError` — adds status (NEW/REGRESSION/ONGOING), severity (S1-S4), should_alert, suppression_reason
- `ErrorResult` — final result with LinearTicketResult and SlackMessageResult
- `PipelineResult` — summary of a full pipeline run

## Pipeline Stages (`pipeline/`)

### 1. `clustering.py` — ErrorClusterer
Multi-stage approach to group similar errors:
- Stage 1: Strict (skipped by default — passes all to Stage 2 for better semantic grouping)
- Stage 2: Regex by error type only (`RateLimit`, `Auth`, `Database`, `Timeout`, etc.)
- Stage 3: LLM semantic clustering for remaining ungrouped errors
- Stage 4: LLM cluster merging when >3 clusters exist

LLM uses `ClusterGroup` and `ClusterSummary` Pydantic models for structured output via `JsonOutputParser`.

### 2. `search.py` — ContextSearcher
Queries ChromaDB (or Airweave if configured) for related code, tickets, and docs. Falls back to mock results in demo mode.

### 3. `enrichment.py` — ErrorEnricher
Combines search results into enriched cluster context. Currently partially commented out in `__init__.py`.

### 4. `analysis.py` — ErrorAnalyzer
- Builds `operational_context` via `PropagationEngine` and `CausalGraph`
- Uses `HybridRetriever` for grounded evidence bundle
- LLM analysis is evidence-grounded — must cite sources, no invented facts
- Fallback uses `infer_severity()` from `core/scoring.py` with keyword matching
- `determine_status()` checks JSON state for prior occurrences and ticket status
- `should_alert()` implements suppression logic (mute → S1/S2 override → NEW → REGRESSION → ONGOING rules)

Suppression logic (in order):
1. Muted → suppress
2. S1/S2 severity → always alert (overrides everything)
3. NEW status → alert
4. REGRESSION status → alert
5. ONGOING with open ticket → suppress
6. Alerted within 24h → suppress

### 5. `semantic_matcher.py` — SemanticMatcher
Deduplication against existing tickets and active mutes. Currently commented out in `__init__.py`.

### 6. `actions.py` — ActionExecutor
Executes Linear and Slack actions based on status:
- NEW or ONGOING (no ticket) → create Linear ticket + post Slack alert
- REGRESSION → reopen/comment on ticket + post Slack alert
- ONGOING (with ticket) → add comment + thread reply
- Suppressed → skip alerting, still update state

## Singleton Pattern

These are all singletons — always use the getter, never instantiate directly:

```python
get_config()              # config.py
get_state_manager()       # state.py
get_chroma_client()       # clients/chroma_client.py
get_action_executor()     # pipeline/actions.py
get_regression_engine()   # memory/regression_engine.py
```

## Data Sources (`sources/`)

All sources extend `DataSource` (ABC in `base.py`) and implement:
- `name: str` (property)
- `source_type: str` (property)
- `is_configured: bool` (property)
- `fetch_errors(window_minutes, limit) -> List[RawError]` (async)

Available: `SampleDataSource`, `SentrySource`, `AzureLogAnalyticsSource`. Selected via `DATA_SOURCE` env var.

## ChromaDB Collections (`clients/chroma_client.py`)

| Collection | Source | Used for |
|------------|--------|---------|
| `github_code` | GitHub | Code snippet search |
| `github_issues` | GitHub Issues / Linear | Ticket search |
| `slack_threads` | Slack | Discussion search |
| `all_context` | All of the above | Combined search (default) |

Embedding model: `all-MiniLM-L6-v2`. Similarity metric: cosine (distance → score via `1.0 - distance`).

## State Files (`data/`)

| File | Contents |
|------|---------|
| `error_signatures.json` | Error history keyed by signature (first_seen, last_alerted, linear_issue_id, etc.) |
| `mutes.json` | Active mutes keyed by signature (muted_until, muted_by, reason) |
| `kv_store.json` | General key-value store |

All reads/writes use `FileLock` for thread safety. Corrupted files are backed up and reset automatically.

## Frontend (`frontend/`)

| Path | Purpose |
|------|---------|
| `src/App.tsx` | Root component — WebSocket connection, pipeline state management |
| `src/components/` | Pipeline visualization UI components |
| `src/hooks/` | Custom React hooks (WebSocket, etc.) |
| `src/lib/` | Shared utilities |
| `vite.config.ts` | Dev server on port 3000; proxies `/api` → `localhost:8000` |

## Key Conventions

- **New data sources** → `sources/`, extend `DataSource` ABC, register in `sources/__init__.py`
- **New pipeline stages** → `pipeline/`, export from `pipeline/__init__.py`
- **Shared data models** → `schemas.py` (Pydantic v2), follow the inheritance chain
- **Config** → always via `get_config()`, never `os.environ` directly in feature code
- **State** → always via `get_state_manager()`
- **LLM calls** → use LangChain `ChatPromptTemplate` + `JsonOutputParser(pydantic_object=...)` + `chain.ainvoke()`
- **LLM fallback** → every LLM path must have a non-LLM fallback (regex/heuristic)
- **Async** → all I/O operations must be `async def` with `await`
- **Logging** → `logger = logging.getLogger(__name__)` at module level; use INFO for key decisions, DEBUG for details
- **Tests** → `backend/tests/`; use `conftest.py` fixtures; `asyncio_mode = auto` means no decorator needed
- **Debug/one-off scripts** → `scripts/` or top-level `debug_*.py` files, never in core modules
- **Severity** → always S1/S2/S3/S4 strings; use `severity_priority()` from `core/scoring.py` for ordering
