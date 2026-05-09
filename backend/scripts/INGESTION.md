# GitHub Ingestion Script

## Overview

The `ingest.py` script builds persistent engineering memory for DevANT by fetching and indexing GitHub repository data into ChromaDB. It creates semantic context for error enrichment without requiring Airweave.

## What Gets Ingested

### 1. **GitHub Issues**
- Issue titles and descriptions
- Labels and status
- Complete discussion threads
- Stored as `github_issues` collection

### 2. **Pull Requests**  
- PR titles and descriptions
- Changed files summary
- Author and merge status
- Discussion context
- Stored as `github_issues` collection (operational memory)

### 3. **Code Files**
Supported languages:
- Python (`.py`)
- TypeScript (`.ts`, `.tsx`)
- JavaScript (`.js`, `.jsx`)

**Chunking Strategy**: Logical units, not character count
- Python: Classes, functions, exceptions
- TypeScript/JavaScript: Classes, functions, React components
- Each chunk includes imports and module context
- Stored as `github_code` collection

## Setup

### Prerequisites
- GitHub repository public access
- GitHub Personal Access Token (PAT)

### Environment Variables

```bash
# Required
export GITHUB_TOKEN=ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxx
export GITHUB_REPO=owner/repo-name

# Optional (defaults to ./data/chroma)
export CHROMA_PERSIST_DIR=/path/to/chroma/data
```

### Get GitHub Token
1. Go to https://github.com/settings/tokens
2. Generate new personal access token (classic)
3. Select scopes: `repo` (public/private), `read:org`
4. Copy token and export as `GITHUB_TOKEN`

## Usage

### Basic Ingestion
```bash
cd backend

export GITHUB_TOKEN=ghp_...
export GITHUB_REPO=owner/repo

python scripts/ingest.py
```

### Example Output
```
============================================================
Starting complete GitHub repository ingestion
============================================================
2026-05-07 20:45:32,123 - __main__ - INFO - Starting GitHub issues ingestion from owner/repo
2026-05-07 20:45:34,456 - __main__ - INFO - Ingested 24 GitHub issues into ChromaDB
2026-05-07 20:45:36,789 - __main__ - INFO - Starting GitHub PR ingestion from owner/repo
2026-05-07 20:45:38,012 - __main__ - INFO - Ingested 12 GitHub PRs into ChromaDB
2026-05-07 20:45:40,345 - __main__ - INFO - Starting code ingestion from owner/repo
2026-05-07 20:46:15,678 - __main__ - INFO - Ingested 287 code chunks into ChromaDB

============================================================
Ingestion Summary:
  Issues: 24
  Pull Requests: 12
  Code Chunks: 287
  Total: 323
============================================================

Test search returned 3 results
  1. error_handler.py::handle_timeout (score: 0.87)
  2. retry_logic.py::exponential_backoff (score: 0.85)
  3. PR #42: Add retry mechanism (score: 0.82)
```

## Testing

### Run Parsing Tests
```bash
python scripts/test_ingest.py
```

This validates:
- Python code chunking by class/function
- TypeScript code chunking by component/function
- Metadata structure for ChromaDB
- No external API calls required

### Verify ChromaDB Ingestion
After running ingestion, test semantic search:

```python
from clients.chroma_client import ChromaClient

client = ChromaClient()
results = await client.search(
    query="redis timeout in authentication flow",
    source_filter="github",
    limit=5
)

for result in results:
    print(f"Title: {result['metadata']['title']}")
    print(f"Path: {result['metadata']['path']}")
    print(f"Score: {result['score']:.2f}")
```

## Data Structure

### Document Metadata
Each ingested document includes:

```python
{
    "path": "core/auth.py or issues/123 or pulls/456",
    "url": "GitHub URL to resource",
    "source": "github",
    "type": "python_class | python_function | github_issue | github_pr | etc",
    "title": "Human-readable title",
    # Additional fields based on type
    "state": "open|closed",      # For issues/PRs
    "author": "username",         # For PRs
    "labels": "label1,label2"     # For issues
}
```

### Collections
- **`github_code`**: Python, TypeScript, JavaScript chunks
- **`github_issues`**: Issues and PRs (operational memory)

## Performance

### Rate Limiting
- GitHub API: 60 req/minute (unauthenticated), 5000/hour (authenticated)
- Script respects rate limits with built-in delays
- Typical ingestion times:
  - 100 issues: 5-10 seconds
  - 50 PRs: 3-5 seconds  
  - 500 code files: 2-5 minutes

### Storage
- ChromaDB stores vectors and metadata
- Typical repository: 300-500 MB
- Ingestion is idempotent (re-run safely)

## Troubleshooting

### `GITHUB_TOKEN environment variable required`
```bash
# Verify token is exported
echo $GITHUB_TOKEN

# If empty, set it:
export GITHUB_TOKEN=ghp_...
```

### `Repository not found`
```bash
# Verify repo name format
export GITHUB_REPO=owner/repo-name

# Test with public repo:
export GITHUB_REPO=torvalds/linux
```

### `ChromaDB initialization failed`
```bash
# Ensure data directory is writable
ls -la ./data/chroma

# Or use custom directory
export CHROMA_PERSIST_DIR=/tmp/chroma
```

### API Rate Limit Exceeded
- Use authenticated token (5000 req/hour vs 60 req/hour)
- Wait for rate limit reset (shown in error)
- Reduce scope (specific files/issues)

## Integration with DevANT Pipeline

Once ingested, the data is available to:

1. **Context Search Stage**
   - Searches GitHub code for related errors
   - Finds relevant issues and discussions
   - Returns semantic matches for alert enrichment

2. **Mock Search Fallback**
   - If ChromaDB is empty, uses generated mock context
   - Allows frontend demo to work without ingestion

3. **Persistent Memory**
   - Re-run ingestion periodically (nightly, weekly)
   - New issues/PRs automatically indexed
   - Code changes picked up on re-index

## Example: DevANT Repository

```bash
export GITHUB_TOKEN=ghp_...
export GITHUB_REPO=Perceptronix/DevANT-error-monitoring-system

python scripts/ingest.py
```

This ingests:
- DevANT's own error tracking issues
- Implementation PRs and discussions
- Complete codebase (backend + frontend)
- Available for self-monitoring
