# Tech Stack

## Backend

- **Language:** Python 3.9+
- **Framework:** FastAPI (async) — all routes and WebSocket handlers are async
- **Server:** Uvicorn (ASGI)
- **LLM:** Anthropic (`claude-sonnet-4-20250514`) preferred; falls back to OpenAI (`gpt-4o`); Groq (`llama3-70b-8192`) also supported via `langchain-groq`. LLM is initialized in each component's `_init_llm()` method and stored as `self.llm` / `self.provider`.
- **LangChain:** Used for all LLM calls — `ChatPromptTemplate`, `JsonOutputParser`, `chain.ainvoke()`. Pydantic models are passed to `JsonOutputParser(pydantic_object=...)` for structured output.
- **Vector store:** ChromaDB with local persistence at `backend/data/chroma/`. Collections: `github_code`, `github_issues`, `slack_threads`, `all_context`. Embedding model: `all-MiniLM-L6-v2` via `sentence-transformers`.
- **Validation:** Pydantic v2 — all data models use `BaseModel`, `Field`, `ConfigDict`, `model_validator`
- **HTTP client:** `httpx` (async)
- **State persistence:** JSON files with `filelock` for thread-safe concurrent access. No database required.
- **Real-time:** WebSockets via FastAPI — `ConnectionManager` broadcasts pipeline events to all connected clients
- **Config:** `python-dotenv` + dataclasses in `config.py`; always access via `get_config()` singleton

## Frontend

- **Language:** TypeScript (strict)
- **Framework:** React 18 — functional components with hooks only
- **Build tool:** Vite (port 3000 in dev; proxies `/api` → `localhost:8000`)
- **Styling:** Tailwind CSS + `tailwind-merge` + `clsx`
- **UI primitives:** Radix UI (`@radix-ui/react-collapsible`, `@radix-ui/react-slot`)
- **Icons:** Lucide React
- **Test runner:** Vitest (`npm test` runs single-pass, no watch)
- **Path alias:** `@/` maps to `frontend/src/`

## Key Dependencies (backend)

| Package | Purpose |
|---------|---------|
| `fastapi` | Web framework |
| `uvicorn[standard]` | ASGI server |
| `groq`, `langchain-groq`, `langchain-core`, `langchain` | LLM integration |
| `langchain-anthropic` | Anthropic LLM (preferred) |
| `langchain-openai` | OpenAI LLM (fallback) |
| `chromadb` | Vector store |
| `sentence-transformers` | Embeddings |
| `pydantic` | Data validation |
| `httpx` | Async HTTP |
| `filelock` | Thread-safe file access |
| `python-dotenv` | Env var loading |

## Testing (Backend)

- **Runner:** pytest with `asyncio_mode = auto` — all async tests run automatically without `@pytest.mark.asyncio`
- **Plugins:** `pytest-asyncio`, `pytest-mock`, `pytest-cov`, `pytest-xdist`, `pytest-timeout`
- **Timeout:** 30s per test
- **Test markers:** `integration`, `e2e`, `performance`, `slow`
- **Config file:** `backend/pytest.ini`
- **Fixtures:** shared in `backend/tests/conftest.py`

## Common Commands

### Backend

```bash
# Setup
cd backend
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt

# Run dev server (port 8000)
uvicorn main:app --reload --port 8000

# Install test deps
pip install -r requirements-test.txt

# Run all tests
pytest backend/tests/ -v

# Run a specific module
pytest backend/tests/test_pipeline_e2e.py -v

# Run with coverage
pytest backend/tests/ --cov=backend

# Run in parallel
pytest backend/tests/ -n auto

# Run excluding slow tests
pytest backend/tests/ -m "not slow" -v
```

### Frontend

```bash
# Setup
cd frontend
npm install

# Dev server (port 3000, proxies /api → localhost:8000)
npm run dev

# Type-check + production build
npm run build

# Run tests (single pass, no watch)
npm test
```

## Environment

Copy `.env.example` to `.env`. Minimum required for demo:

```
GROQ_API_KEY=...
AIRWEAVE_API_KEY=...
AIRWEAVE_COLLECTION_ID=...
```

LLM provider priority: `ANTHROPIC_API_KEY` → `OPENAI_API_KEY` → `GROQ_API_KEY`. If none are set, the system falls back to regex/heuristic logic (no LLM clustering or analysis).

See `docs/CONFIGURATION.md` for all options.

## API Endpoints (backend)

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/` | Health check |
| GET | `/api/config` | Configuration status |
| GET | `/api/samples` | Get sample errors |
| GET | `/api/state` | State statistics |
| POST | `/api/run` | Trigger pipeline run |
| POST | `/api/mute` | Mute an error signature |
| DELETE | `/api/mute/{signature}` | Unmute |
| WS | `/ws/pipeline` | Real-time pipeline events |

WebSocket events: `pipeline_started`, `step_started`, `step_data_ready`, `step_completed`, `pipeline_completed`
