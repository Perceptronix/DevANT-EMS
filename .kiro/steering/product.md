# Product: Intelligent Error Monitoring Agent

An AI-powered error monitoring agent that transforms raw production errors into actionable insights using semantic understanding. Based on an internal agent ("Donke") that handles ~40,000 Airweave queries/month.

## Problem It Solves

Standard error monitoring tools produce raw alerts. This agent adds:
- **Context** — what code is involved, has someone already worked on this, is it a regression?
- **Deduplication** — 20 raw errors → 4 actionable clusters
- **Suppression** — no duplicate tickets or Slack spam for ongoing known issues
- **Severity** — S1–S4 classification with reasoning, not just "error occurred"

## Core Pipeline

```
Raw Errors → [Clustering] → [Context Search] → [Analysis] → [Actions]
```

1. **Clustering** — groups similar errors by root cause using 3-stage approach (regex → LLM → merge)
2. **Context Search** — finds related code (GitHub), tickets (Linear/GitHub Issues), discussions (Slack) via ChromaDB or Airweave
3. **Analysis** — determines severity (S1–S4), status (NEW/REGRESSION/ONGOING), and suppression using LLM with grounded evidence
4. **Actions** — creates/updates Linear tickets and posts Slack alerts (or generates previews)

## Status Classification

| Status | Meaning | Action |
|--------|---------|--------|
| NEW | First time seeing this error | Create ticket + alert |
| REGRESSION | Error reoccurred after ticket was closed | Reopen ticket + alert |
| ONGOING | Continues with existing open ticket | Comment + thread reply (or suppress) |

## Severity Levels

| Level | Meaning | Examples |
|-------|---------|---------|
| S1 | Complete outage, data loss, security breach | All users down |
| S2 | Major feature broken, >10% users affected | Auth failures, OOM |
| S3 | Feature degraded, <10% users, workaround exists | Rate limits, timeouts |
| S4 | Minor issue, single user, no immediate action | Parse errors, 404s |

Severity escalates automatically if >3 orgs are affected.

## Suppression Logic

Alerts are suppressed unless:
- Status is NEW or REGRESSION (always alert)
- Severity is S1 or S2 (always alert, overrides everything)
- Error is muted → suppress
- ONGOING with open ticket → suppress
- Already alerted within 24h → suppress

## Data Sources

| Source | Env var | Notes |
|--------|---------|-------|
| `sample` | (default) | Realistic demo data, zero config |
| `sentry` | `SENTRY_AUTH_TOKEN` | Fetches issues from Sentry API |
| `azure` | `AZURE_LOG_ANALYTICS_*` | Azure Log Analytics workspace |
| `datadog` | `DATADOG_API_KEY` | Datadog integration |

## Integration Modes

- **Preview mode** (default) — shows what Linear tickets and Slack messages would be created, no external calls
- **Live mode** — `LINEAR_ENABLED=true` and/or `SLACK_ENABLED=true` to create real tickets/messages

## LLM Usage

LLM is used for:
1. **Semantic clustering** — grouping errors that are the same issue but worded differently
2. **Cluster signature generation** — natural language description of each cluster
3. **Cluster merging** — identifying clusters that are actually the same root cause
4. **Severity analysis** — evidence-grounded S1–S4 classification with root cause and suggested action

LLM analysis is strictly evidence-grounded: the system prompt mandates citing evidence by index/URL and responding with "Insufficient evidence" rather than guessing. All LLM paths have non-LLM fallbacks (regex/heuristic).

## Context Search (ChromaDB / Airweave)

Searches three types of context for each error cluster:
- **Code snippets** — relevant source files from GitHub (`github_code` collection)
- **Related tickets** — existing issues from Linear/GitHub Issues (`github_issues` collection)
- **Discussions** — Slack threads (`slack_threads` collection)

Results are scored by cosine similarity and used to ground LLM analysis.

## State Persistence

JSON files (no database) track per-signature history:
- `first_seen`, `last_seen`, `last_alerted`, `times_seen`
- `linear_issue_id`, `linear_issue_status`, `linear_issue_url`
- `slack_thread_ts`
- `muted_until`, `muted_by`, `mute_reason`

This enables regression detection (ticket was closed → error came back) and suppression (already alerted recently).

## Regression Detection (`memory/regression_engine.py`)

Multi-signal correlation using:
- Stacktrace similarity (normalized, variable data stripped)
- Deployment event correlation
- Metric anomaly overlap
- Propagation path consistency
- Temporal proximity

Confidence threshold: 0.4 (lower = more sensitive). Returns `is_regression`, `regression_confidence`, `recurrence_risk` (HIGH/MEDIUM/LOW).

## See Also

- `docs/ARCHITECTURE.md` — full pipeline design with diagrams
- `docs/CONFIGURATION.md` — all environment variables
- `.env.example` — annotated example config
