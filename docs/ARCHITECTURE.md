# Architecture Overview

This document explains the architecture of the Error Monitoring Agent and how it uses Airweave to provide intelligent error analysis.

## High-Level Flow

```
┌─────────────────┐    ┌──────────────────┐    ┌──────────────────┐
│   Data Source   │───▶│   Pipeline       │───▶│   Integrations   │
│  (Sample/Azure/ │    │  (Cluster/Enrich/│    │  (Linear/Slack)  │
│   Sentry)       │    │   Analyze)       │    │                  │
└─────────────────┘    └────────┬─────────┘    └──────────────────┘
                                │
                                ▼
                       ┌────────────────┐
                       │    Airweave    │
                       │ (Context Search│
                       │  Code/Tickets) │
                       └────────────────┘
```

## Pipeline Stages

### 1. Data Ingestion

**Module:** `sources/`

Fetches errors from configured data source:
- `SampleDataSource` - Generates realistic demo data
- `AzureLogAnalyticsSource` - Queries Azure Log Analytics
- `SentrySource` - Fetches issues from Sentry API

All sources output standardized `RawError` objects.

### 2. Multi-Stage Clustering

**Module:** `pipeline/clustering.py`

Groups similar errors to reduce alert noise. Uses a 3-stage approach:

```
Stage 1: Error Type Clustering
  ├── Group by semantic error type (rate limit, auth, database, etc.)
  └── Fast regex-based pattern matching, no LLM needed

Stage 2: LLM Semantic Clustering
  ├── Use LLM to find semantically similar errors
  └── Catches "same issue, different wording"

Stage 3: Cluster Merging (Optional)
  └── LLM merges clusters that are actually the same issue
```

*Note: The clustering prioritizes semantic grouping (e.g., "all rate limit errors together") over strict location-based grouping for more intuitive results.*

**Example:**
```
Input:
- "HTTP 429 downloading report.pdf"
- "HTTP 429 downloading invoice.xlsx"
- "Rate limit exceeded for file sync"

Output (single cluster):
- Signature: "Rate limiting errors (HTTP 429) during file downloads"
- Error count: 3
```

### 3. Context Enrichment

**Module:** `pipeline/enrichment.py`

Queries Airweave to add context from your codebase:

```python
# Searches performed:
code_snippets = await airweave.search_code(query, module)      # GitHub
related_tickets = await airweave.search_tickets(query)          # Linear
documentation = await airweave.search_docs(query)               # Notion/Confluence
```

Then generates a comprehensive summary using LLM.

### 4. Semantic Matching

**Module:** `pipeline/semantic_matcher.py`

Determines if the error matches:
- An existing ticket (to avoid duplicates)
- An active mute rule (to suppress alerts)

Uses LLM for semantic comparison when exact matching fails.

### 5. Status Determination & Analysis

**Module:** `pipeline/analysis.py`

Determines error status and severity:

**Status:**
- `NEW` - First time seeing this error
- `REGRESSION` - Error reoccurred after ticket was closed
- `ONGOING` - Continues with existing open ticket

**Severity:**
- `S1` - Critical: Complete outage, data loss, security breach
- `S2` - High: Major feature broken, significant impact
- `S3` - Medium: Feature degraded, limited impact
- `S4` - Low: Minor issue, no immediate action needed

**Suppression Logic:**
```python
# Always alert
if status == "NEW" or status == "REGRESSION":
    return True

# S1/S2 always alert (override suppression)
if severity in ["S1", "S2"]:
    return True

# Suppress if muted
if is_muted(signature):
    return False

# Suppress if already alerted within 24h
if last_alerted < 24_hours_ago:
    return False
```

### 6. Action Execution

**Module:** `pipeline/actions.py`

Executes actions based on analysis:

| Status | Action |
|--------|--------|
| NEW | Create Linear ticket + Post Slack alert |
| REGRESSION | Reopen/comment on ticket + Post alert |
| ONGOING (with ticket) | Add comment + Thread reply |
| ONGOING (no ticket) | Create ticket + Post alert |

**Preview Mode:** When Linear/Slack aren't configured, generates preview objects showing what would be created.

## State Management

**Module:** `state.py`

Uses JSON files for persistence (no database required):

```
backend/data/
├── error_signatures.json    # Error history and ticket references
└── mutes.json               # Active mute rules
```

Each signature entry tracks:
```python
{
    "signature": "Rate limiting errors...",
    "first_seen": "2024-01-15T10:30:00Z",
    "last_seen": "2024-01-15T14:45:00Z",
    "last_alerted": "2024-01-15T10:35:00Z",
    "linear_issue_id": "abc123",
    "linear_issue_status": "In Progress",
    "slack_thread_ts": "1705312500.123456"
}
```

## Data Flow Example

```
1. Fetch Errors
   └── SentrySource.fetch_errors() → [RawError, RawError, ...]

2. Cluster
   └── ErrorClusterer.cluster_errors(raw_errors) → [ErrorCluster, ...]

3. For each cluster:
   
   3a. Enrich
       └── ErrorEnricher.enrich(cluster)
           ├── search_code(signature) → code_snippets
           ├── search_tickets(signature) → related_tickets
           └── generate_summary() → comprehensive_summary
           
   3b. Match
       └── SemanticMatcher.find_matching_ticket(cluster, related_tickets)
           └── matched_ticket, has_relevant_ticket
           
   3c. Analyze
       └── ErrorAnalyzer.analyze_with_status(cluster, context)
           ├── determine_status() → NEW/REGRESSION/ONGOING
           ├── analyze_severity() → S1/S2/S3/S4
           └── should_alert() → True/False
           
   3d. Execute
       └── ActionExecutor.execute(analyzed_error)
           ├── create_linear_ticket() → LinearTicketResult
           ├── post_slack_alert() → SlackMessageResult
           └── update_state()

4. Return Results
   └── PipelineResult with all ErrorResults
```

## WebSocket Protocol

The frontend connects via WebSocket for real-time updates:

```javascript
// Connect
const ws = new WebSocket('ws://localhost:8000/ws');

// Send command
ws.send(JSON.stringify({ action: 'run_pipeline' }));

// Receive updates
ws.onmessage = (event) => {
    const data = JSON.parse(event.data);
    // data.type: 'step' | 'cluster' | 'result' | 'error'
    // data.payload: step-specific data
};
```

## Key Design Decisions

### Why Multi-Stage Clustering?

LLM calls are expensive and slow. The multi-stage approach:
1. Uses fast regex-based error type matching first
2. Only uses LLM for remaining ambiguous cases and cluster merging
3. Reduces LLM calls by 60-80% in typical workloads

### Why JSON for State?

For a demo/showcase:
- Zero setup (no database to configure)
- Easy to inspect and debug
- Portable (just copy the files)
- Sufficient for reasonable workloads

For production, consider migrating to PostgreSQL or Redis.

### Why Preview Mode?

Allows users to:
1. See exactly what would happen without affecting real systems
2. Evaluate the agent without Linear/Slack accounts
3. Test changes safely before enabling real integrations

### Why Airweave?

Airweave provides:
1. **Unified search** across GitHub, Linear, Notion, etc.
2. **Semantic search** to find related context even with different wording
3. **No indexing hassle** - just connect your sources and search
4. **Hybrid search** combining keyword and semantic matching

This is what makes the agent "intelligent" - it understands your codebase.
