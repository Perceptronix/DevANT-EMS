# DevANT Architecture

## Canonical Ownership

- `backend/app/api/` owns HTTP routes.
- `backend/app/streaming/` owns SSE and live event plumbing.
- `backend/app/orchestration/` owns pipeline coordination.
- `backend/app/intelligence/` owns clustering, scoring, causality, and enrichment logic.
- `backend/app/operational/` owns deployment/topology/temporal reasoning.
- `backend/app/memory/` owns incident history and retrieval.
- `backend/app/reasoning/` owns LLM synthesis and grounded explanation.
- `backend/app/integrations/` owns external service connectors.
- `backend/app/models/` owns canonical domain models and contracts.
- `backend/app/storage/` owns persistent state and runtime storage.
- `backend/app/config/` owns configuration loading.

## Runtime Path

1. `main.py` creates FastAPI app and mounts routers.
2. API routes invoke orchestration services.
3. Orchestration runs ingestion, intelligence, operational correlation, reasoning, and memory updates.
4. Streaming layer broadcasts live pipeline updates.
5. Integrations fetch GitHub, Slack, Sentry, Datadog, and other operational signals.

## Import Rules

- New imports should prefer `app.*` namespaces.
- Legacy modules remain supported until migration is complete.
- Do not break runtime by moving large subsystems before the facade layer is stable.

## Migration Rule

- Move one low-risk subsystem at a time.
- Validate backend importability after each slice.
- Keep `main.py` thin by extracting routes before extracting runtime engines.
