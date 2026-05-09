"""
Sample error data for demonstrating the error monitoring pipeline.
These are designed to look like real production errors from a SaaS data sync platform.

The errors are grouped into clusters that will be recognized by the semantic clustering:
- Rate limiting errors (multiple APIs) → 1 cluster
- Database connection errors → 1 cluster  
- OAuth/authentication errors → 1 cluster
- Document processing errors → 1 cluster

This demonstrates the value: 18+ raw errors → 4 actionable clusters
"""
from typing import List, Dict, Any
from datetime import datetime, timedelta
import random

# Sample error scenarios that demonstrate different clustering/analysis behaviors
SAMPLE_ERRORS: List[Dict[str, Any]] = [
    # =========================================================================
    # RATE LIMITING CLUSTER (7 errors → should cluster together)
    # =========================================================================
    {
        "id": "err-7f3a2b1c",
        "timestamp": "2024-01-15T10:23:45.123Z",
        "level": "ERROR",
        "message": "googleapiclient.errors.HttpError: <HttpError 429 when requesting https://www.googleapis.com/drive/v3/files/1xK7mN...?alt=media returned \"Rate Limit Exceeded\". Details: \"User Rate Limit Exceeded.\">",
        "module": "connectors.google_drive",
        "function": "download_file",
        "line": 142,
        "container": "sync-worker-7d9f8b6c4-xk2pq",
        "trace_id": "4f7a8b2c-1d3e-4f5a-6b7c-8d9e0f1a2b3c",
        "org_id": "org_2kL9mNpQrS",
        "org_name": "Acme Corporation",
    },
    {
        "id": "err-8a4b3c2d",
        "timestamp": "2024-01-15T10:24:12.456Z",
        "level": "ERROR",
        "message": "googleapiclient.errors.HttpError: <HttpError 429 when requesting https://www.googleapis.com/drive/v3/files?q=...&pageToken=... returned \"Rate Limit Exceeded\">",
        "module": "connectors.google_drive",
        "function": "list_files",
        "line": 87,
        "container": "sync-worker-7d9f8b6c4-xk2pq",
        "trace_id": "5a8b9c3d-2e4f-5a6b-7c8d-9e0f1a2b3c4d",
        "org_id": "org_8xY7zWvUtR",
        "org_name": "TechStart Inc",
    },
    {
        "id": "err-9b5c4d3e",
        "timestamp": "2024-01-15T10:24:33.789Z",
        "level": "ERROR",
        "message": "httpx.HTTPStatusError: Client error '429 Too Many Requests' for url 'https://api.dropboxapi.com/2/files/list_folder'",
        "module": "connectors.dropbox",
        "function": "fetch_folder_contents",
        "line": 203,
        "container": "sync-worker-7d9f8b6c4-m3n4o",
        "trace_id": "6b9c0d4e-3f5a-6b7c-8d9e-0f1a2b3c4d5e",
        "org_id": "org_2kL9mNpQrS",
        "org_name": "Acme Corporation",
    },
    {
        "id": "err-rate-4",
        "timestamp": "2024-01-15T10:24:45.234Z",
        "level": "ERROR",
        "message": "googleapiclient.errors.HttpError: <HttpError 429 when requesting https://www.googleapis.com/drive/v3/files/2yL8oP...?alt=media returned \"Rate Limit Exceeded\">",
        "module": "connectors.google_drive",
        "function": "download_file",
        "line": 142,
        "container": "sync-worker-7d9f8b6c4-p5q6r",
        "trace_id": "a1b2c3d4-e5f6-7a8b-9c0d-1e2f3a4b5c6d",
        "org_id": "org_4pQ3rStUvW",
        "org_name": "Globex Systems",
    },
    {
        "id": "err-rate-5",
        "timestamp": "2024-01-15T10:25:02.567Z",
        "level": "ERROR",
        "message": "slack_sdk.errors.SlackApiError: The request to the Slack API failed. The server responded with: {'ok': False, 'error': 'ratelimited', 'retry_after': 30}",
        "module": "connectors.slack",
        "function": "fetch_channel_messages",
        "line": 178,
        "container": "sync-worker-7d9f8b6c4-m3n4o",
        "trace_id": "b2c3d4e5-f6a7-8b9c-0d1e-2f3a4b5c6d7e",
        "org_id": "org_8xY7zWvUtR",
        "org_name": "TechStart Inc",
    },
    {
        "id": "err-rate-6",
        "timestamp": "2024-01-15T10:25:18.890Z",
        "level": "ERROR",
        "message": "httpx.HTTPStatusError: Client error '429 Too Many Requests' for url 'https://api.dropboxapi.com/2/files/download'",
        "module": "connectors.dropbox",
        "function": "download_file",
        "line": 156,
        "container": "sync-worker-7d9f8b6c4-xk2pq",
        "trace_id": "c3d4e5f6-a7b8-9c0d-1e2f-3a4b5c6d7e8f",
        "org_id": "org_6nM5oLkJiH",
        "org_name": "Enterprise Solutions Ltd",
    },
    {
        "id": "err-rate-7",
        "timestamp": "2024-01-15T10:25:33.123Z",
        "level": "ERROR",
        "message": "googleapiclient.errors.HttpError: <HttpError 429 when requesting https://www.googleapis.com/drive/v3/files/3zM9qR... returned \"User Rate Limit Exceeded\">",
        "module": "connectors.google_drive",
        "function": "get_file_metadata",
        "line": 98,
        "container": "sync-worker-7d9f8b6c4-p5q6r",
        "trace_id": "d4e5f6a7-b8c9-0d1e-2f3a-4b5c6d7e8f9a",
        "org_id": "org_2kL9mNpQrS",
        "org_name": "Acme Corporation",
    },
    
    # =========================================================================
    # DATABASE CONNECTION CLUSTER (5 errors → should cluster together)
    # =========================================================================
    {
        "id": "err-0c6d5e4f",
        "timestamp": "2024-01-15T10:26:01.234Z",
        "level": "ERROR",
        "message": "sqlalchemy.exc.OperationalError: (psycopg2.OperationalError) connection to server at \"prod-db.internal\" (10.0.1.42), port 5432 failed: timeout expired",
        "module": "api.routes.sync",
        "function": "get_sync_status",
        "line": 78,
        "container": "api-server-5c8d7e6f-2b3c4",
        "trace_id": "7c0d1e5f-4a6b-7c8d-9e0f-1a2b3c4d5e6f",
        "org_id": "org_4pQ3rStUvW",
        "org_name": "Globex Systems",
    },
    {
        "id": "err-1d7e6f5a",
        "timestamp": "2024-01-15T10:26:15.567Z",
        "level": "ERROR",
        "message": "sqlalchemy.exc.OperationalError: (psycopg2.pool.PoolError) connection pool exhausted, max pool size: 20, current checked out: 20",
        "module": "api.routes.documents",
        "function": "batch_update_metadata",
        "line": 234,
        "container": "api-server-5c8d7e6f-8k9l0",
        "trace_id": "8d1e2f6a-5b7c-8d9e-0f1a-2b3c4d5e6f7a",
        "org_id": "org_8xY7zWvUtR",
        "org_name": "TechStart Inc",
    },
    {
        "id": "err-db-3",
        "timestamp": "2024-01-15T10:26:28.890Z",
        "level": "ERROR",
        "message": "sqlalchemy.exc.OperationalError: (psycopg2.OperationalError) could not connect to server: Connection refused. Is the server running on host \"prod-db.internal\" and accepting TCP/IP connections on port 5432?",
        "module": "api.routes.integrations",
        "function": "list_integrations",
        "line": 45,
        "container": "api-server-5c8d7e6f-2b3c4",
        "trace_id": "e5f6a7b8-c9d0-1e2f-3a4b-5c6d7e8f9a0b",
        "org_id": "org_2kL9mNpQrS",
        "org_name": "Acme Corporation",
    },
    {
        "id": "err-db-4",
        "timestamp": "2024-01-15T10:26:42.123Z",
        "level": "ERROR",
        "message": "sqlalchemy.exc.OperationalError: (psycopg2.pool.PoolError) QueuePool limit of size 20 overflow 10 reached, connection timed out, timeout 30.00",
        "module": "workers.sync_processor",
        "function": "process_sync_job",
        "line": 189,
        "container": "sync-worker-7d9f8b6c4-xk2pq",
        "trace_id": "f6a7b8c9-d0e1-2f3a-4b5c-6d7e8f9a0b1c",
        "org_id": "org_4pQ3rStUvW",
        "org_name": "Globex Systems",
    },
    {
        "id": "err-db-5",
        "timestamp": "2024-01-15T10:26:55.456Z",
        "level": "ERROR",
        "message": "sqlalchemy.exc.OperationalError: (psycopg2.OperationalError) server closed the connection unexpectedly. This probably means the server terminated abnormally before or while processing the request.",
        "module": "api.routes.search",
        "function": "semantic_search",
        "line": 112,
        "container": "api-server-5c8d7e6f-8k9l0",
        "trace_id": "a7b8c9d0-e1f2-3a4b-5c6d-7e8f9a0b1c2d",
        "org_id": "org_6nM5oLkJiH",
        "org_name": "Enterprise Solutions Ltd",
    },
    
    # =========================================================================
    # OAUTH/AUTHENTICATION CLUSTER (4 errors → should cluster together)
    # =========================================================================
    {
        "id": "err-2e8f7a6b",
        "timestamp": "2024-01-15T10:27:00.890Z",
        "level": "ERROR",
        "message": "requests.exceptions.HTTPError: 401 Client Error: Unauthorized for url: https://oauth2.googleapis.com/token - {\"error\": \"invalid_grant\", \"error_description\": \"Token has been expired or revoked.\"}",
        "module": "integrations.oauth",
        "function": "refresh_access_token",
        "line": 156,
        "container": "sync-worker-7d9f8b6c4-xk2pq",
        "trace_id": "9e2f3a7b-6c8d-9e0f-1a2b-3c4d5e6f7a8b",
        "org_id": "org_2kL9mNpQrS",
        "org_name": "Acme Corporation",
    },
    {
        "id": "err-auth-2",
        "timestamp": "2024-01-15T10:27:15.234Z",
        "level": "ERROR",
        "message": "httpx.HTTPStatusError: Client error '401 Unauthorized' for url 'https://api.dropboxapi.com/2/users/get_current_account' - {\"error_summary\": \"expired_access_token/\"}",
        "module": "connectors.dropbox",
        "function": "verify_connection",
        "line": 67,
        "container": "sync-worker-7d9f8b6c4-m3n4o",
        "trace_id": "b8c9d0e1-f2a3-4b5c-6d7e-8f9a0b1c2d3e",
        "org_id": "org_8xY7zWvUtR",
        "org_name": "TechStart Inc",
    },
    {
        "id": "err-auth-3",
        "timestamp": "2024-01-15T10:27:28.567Z",
        "level": "ERROR",
        "message": "requests.exceptions.HTTPError: 401 Client Error: Unauthorized for url: https://oauth2.googleapis.com/token - {\"error\": \"invalid_grant\", \"error_description\": \"Token has been expired or revoked.\"}",
        "module": "integrations.oauth",
        "function": "refresh_access_token",
        "line": 156,
        "container": "sync-worker-7d9f8b6c4-p5q6r",
        "trace_id": "c9d0e1f2-a3b4-5c6d-7e8f-9a0b1c2d3e4f",
        "org_id": "org_4pQ3rStUvW",
        "org_name": "Globex Systems",
    },
    {
        "id": "err-auth-4",
        "timestamp": "2024-01-15T10:27:42.890Z",
        "level": "ERROR",
        "message": "slack_sdk.errors.SlackApiError: The request to the Slack API failed. The server responded with: {'ok': False, 'error': 'token_revoked'}",
        "module": "connectors.slack",
        "function": "post_message",
        "line": 234,
        "container": "sync-worker-7d9f8b6c4-xk2pq",
        "trace_id": "d0e1f2a3-b4c5-6d7e-8f9a-0b1c2d3e4f5a",
        "org_id": "org_2kL9mNpQrS",
        "org_name": "Acme Corporation",
    },
    
    # =========================================================================
    # DOCUMENT PROCESSING CLUSTER (4 errors → should cluster together)
    # =========================================================================
    {
        "id": "err-3f9a8b7c",
        "timestamp": "2024-01-15T10:28:00.123Z",
        "level": "ERROR",
        "message": "pypdf.errors.PdfReadError: EOF marker not found. File may be corrupted or encrypted: /tmp/processing/doc_8x7y6z.pdf",
        "module": "processors.document",
        "function": "extract_text_from_pdf",
        "line": 89,
        "container": "processor-worker-3a4b5c-7d8e9",
        "trace_id": "0f3a4b8c-7d9e-0f1a-2b3c-4d5e6f7a8b9c",
        "org_id": "org_4pQ3rStUvW",
        "org_name": "Globex Systems",
    },
    {
        "id": "err-doc-2",
        "timestamp": "2024-01-15T10:28:15.456Z",
        "level": "ERROR",
        "message": "pypdf.errors.PdfReadError: Cannot read an empty file: /tmp/processing/report_q4_2024.pdf",
        "module": "processors.document",
        "function": "extract_text_from_pdf",
        "line": 89,
        "container": "processor-worker-3a4b5c-2f3g4",
        "trace_id": "e1f2a3b4-c5d6-7e8f-9a0b-1c2d3e4f5a6b",
        "org_id": "org_8xY7zWvUtR",
        "org_name": "TechStart Inc",
    },
    {
        "id": "err-doc-3",
        "timestamp": "2024-01-15T10:28:28.789Z",
        "level": "ERROR",
        "message": "docx.opc.exceptions.PackageNotFoundError: Package not found at '/tmp/processing/contract_draft.docx' - file appears to be corrupted",
        "module": "processors.document",
        "function": "extract_text_from_docx",
        "line": 134,
        "container": "processor-worker-3a4b5c-7d8e9",
        "trace_id": "f2a3b4c5-d6e7-8f9a-0b1c-2d3e4f5a6b7c",
        "org_id": "org_2kL9mNpQrS",
        "org_name": "Acme Corporation",
    },
    {
        "id": "err-doc-4",
        "timestamp": "2024-01-15T10:28:42.012Z",
        "level": "ERROR",
        "message": "pypdf.errors.PdfReadError: Stream has ended unexpectedly. File is likely truncated: /tmp/processing/invoice_batch.pdf",
        "module": "processors.document",
        "function": "extract_text_from_pdf",
        "line": 89,
        "container": "processor-worker-3a4b5c-2f3g4",
        "trace_id": "a3b4c5d6-e7f8-9a0b-1c2d-3e4f5a6b7c8d",
        "org_id": "org_6nM5oLkJiH",
        "org_name": "Enterprise Solutions Ltd",
    },
]


def get_sample_errors(count: int = 20, include_extended: bool = False) -> List[Dict[str, Any]]:
    """
    Get sample errors for the demo.
    
    Default returns 20 errors that cluster into 4 groups, demonstrating
    the value of semantic clustering (20 raw errors → 4 actionable clusters).
    
    Args:
        count: Number of errors to return (default 20 for impressive demo)
        include_extended: Unused, kept for backward compatibility
        
    Returns:
        List of error dictionaries
    """
    all_errors = [e.copy() for e in SAMPLE_ERRORS]
    
    # Update timestamps to be recent (within last 5-10 minutes)
    now = datetime.utcnow()
    base_time = now - timedelta(minutes=10)
    
    for i, error in enumerate(all_errors):
        # Stagger timestamps realistically (every 15-30 seconds)
        offset_seconds = (i * 20) + random.randint(0, 15)
        error["timestamp"] = (base_time + timedelta(seconds=offset_seconds)).strftime("%Y-%m-%dT%H:%M:%S.") + f"{random.randint(100, 999)}Z"
    
    return all_errors[:count]
