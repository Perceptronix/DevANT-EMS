# Configuration Guide

This guide covers all configuration options for the Error Monitoring Agent.

## Quick Start

The minimal configuration to run the demo:

```bash
# Required: Airweave connection
AIRWEAVE_API_KEY=your_key
AIRWEAVE_COLLECTION_ID=your_collection_id

# Required: LLM provider (choose one)
ANTHROPIC_API_KEY=your_anthropic_key
# or
OPENAI_API_KEY=your_openai_key
```

Everything else is optional - the demo works with sample data by default.

## Configuration Sections

### Airweave Configuration

Airweave provides the context search that makes this agent intelligent.

| Variable | Required | Description |
|----------|----------|-------------|
| `AIRWEAVE_API_KEY` | Yes | Your Airweave API key |
| `AIRWEAVE_API_URL` | No | API URL (default: `https://api.airweave.ai`) |
| `AIRWEAVE_COLLECTION_ID` | Yes | Collection ID to search |

**Getting Started with Airweave:**
1. Sign up at [airweave.ai](https://airweave.ai)
2. Create a collection
3. Connect your data sources (GitHub, Linear, Notion, etc.)
4. Copy your API key and collection ID

### LLM Configuration

The agent uses an LLM for:
- Semantic clustering of similar errors
- Severity analysis
- Root cause identification
- Summary generation

| Variable | Required | Description |
|----------|----------|-------------|
| `ANTHROPIC_API_KEY` | One required | Anthropic API key (recommended) |
| `ANTHROPIC_MODEL` | No | Model to use (default: `claude-sonnet-4-20250514`) |
| `OPENAI_API_KEY` | One required | OpenAI API key |
| `OPENAI_MODEL` | No | Model to use (default: `gpt-4o`) |

**Note:** If both keys are provided, Anthropic is used by default.

### Data Source Configuration

By default, the demo uses sample data. You can connect to real error sources.

| Variable | Required | Description |
|----------|----------|-------------|
| `DATA_SOURCE` | No | Source type: `sample`, `azure`, `sentry`, `datadog` |

#### Azure Log Analytics

| Variable | Required | Description |
|----------|----------|-------------|
| `AZURE_LOG_ANALYTICS_WORKSPACE_ID` | Yes (if using Azure) | Workspace ID |
| `AZURE_LOG_ANALYTICS_CLIENT_ID` | Yes | Service principal client ID |
| `AZURE_LOG_ANALYTICS_CLIENT_SECRET` | Yes | Service principal secret |
| `AZURE_LOG_ANALYTICS_TENANT_ID` | Yes | Azure AD tenant ID |

**Setup:**
1. Create a service principal in Azure AD
2. Grant it "Log Analytics Reader" role on your workspace
3. Copy the credentials

#### Sentry

| Variable | Required | Description |
|----------|----------|-------------|
| `SENTRY_AUTH_TOKEN` | Yes (if using Sentry) | Sentry auth token |
| `SENTRY_ORG_SLUG` | Yes | Organization slug |
| `SENTRY_PROJECT_SLUG` | No | Project slug (omit to fetch all projects) |
| `SENTRY_URL` | No | Sentry URL (default: `https://sentry.io`) |

**Setup:**
1. Go to Sentry Settings → Auth Tokens
2. Create a token with `project:read`, `event:read` scopes
3. Copy your org slug from the URL

### Linear Integration (Optional)

Enable to create real Linear tickets instead of previews.

| Variable | Required | Description |
|----------|----------|-------------|
| `LINEAR_ENABLED` | No | Set to `true` to enable (default: `false`) |
| `LINEAR_API_KEY` | Yes (if enabled) | Linear API key |
| `LINEAR_TEAM_ID` | Yes (if enabled) | Team ID for ticket creation |

**Setup:**
1. Go to Linear Settings → API → Personal API keys
2. Create a new key
3. Get your team ID from the URL or API

**Preview Mode:** When disabled, the agent generates preview tickets showing what would be created, but doesn't actually call Linear.

### Slack Integration (Optional)

Enable to post real Slack alerts instead of previews.

| Variable | Required | Description |
|----------|----------|-------------|
| `SLACK_ENABLED` | No | Set to `true` to enable (default: `false`) |
| `SLACK_BOT_TOKEN` | Yes (if enabled) | Bot token (starts with `xoxb-`) |
| `SLACK_CHANNEL_ID` | Yes (if enabled) | Channel ID to post alerts |
| `SLACK_SIGNING_SECRET` | No | For webhook verification |

**Setup:**
1. Create a Slack app at [api.slack.com/apps](https://api.slack.com/apps)
2. Add `chat:write` bot scope
3. Install to workspace
4. Copy bot token and channel ID

**Preview Mode:** When disabled, the agent generates preview messages showing what would be posted, but doesn't actually call Slack.

## Configuration Patterns

### Demo Mode (Default)

Just set the required variables:

```bash
AIRWEAVE_API_KEY=your_key
AIRWEAVE_COLLECTION_ID=your_collection
ANTHROPIC_API_KEY=your_key
```

Sample data is used, and integrations show previews.

### Development Mode

Connect to real data but keep integrations in preview:

```bash
AIRWEAVE_API_KEY=your_key
AIRWEAVE_COLLECTION_ID=your_collection
ANTHROPIC_API_KEY=your_key

# Real data source
DATA_SOURCE=sentry
SENTRY_AUTH_TOKEN=your_token
SENTRY_ORG_SLUG=your_org

# Integrations stay in preview mode (default)
```

### Production Mode

Everything enabled:

```bash
AIRWEAVE_API_KEY=your_key
AIRWEAVE_COLLECTION_ID=your_collection
ANTHROPIC_API_KEY=your_key

# Real data
DATA_SOURCE=azure
AZURE_LOG_ANALYTICS_WORKSPACE_ID=...
# ... other Azure vars

# Real integrations
LINEAR_ENABLED=true
LINEAR_API_KEY=...
LINEAR_TEAM_ID=...

SLACK_ENABLED=true
SLACK_BOT_TOKEN=xoxb-...
SLACK_CHANNEL_ID=C...
```

## Checking Configuration

The `/api/config` endpoint shows current configuration status:

```bash
curl http://localhost:8000/api/config | jq
```

Response:
```json
{
  "airweave": {
    "configured": true,
    "collection_id": "abc123..."
  },
  "llm": {
    "configured": true,
    "provider": "anthropic",
    "model": "claude-sonnet-4-20250514"
  },
  "data_source": {
    "type": "sample",
    "available": {
      "sample": true,
      "azure": false,
      "sentry": false,
      "datadog": false
    }
  },
  "integrations": {
    "linear": {
      "enabled": false,
      "configured": false,
      "mode": "preview"
    },
    "slack": {
      "enabled": false,
      "configured": false,
      "mode": "preview"
    }
  }
}
```

## Troubleshooting

### "No LLM configured"

Make sure you have either `ANTHROPIC_API_KEY` or `OPENAI_API_KEY` set.

### "Airweave not configured"

Check that both `AIRWEAVE_API_KEY` and `AIRWEAVE_COLLECTION_ID` are set.

### "Data source not configured"

If using Azure/Sentry, make sure all required credentials are provided.

### Integration shows "preview" when it should be "live"

Check that:
1. `LINEAR_ENABLED=true` or `SLACK_ENABLED=true` is set
2. All required credentials are provided
