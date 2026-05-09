"""
ChromaDB-powered context search for error enrichment.
Searches for related code, tickets, and documentation using semantic similarity.
"""
import os
import logging
from typing import List, Dict, Any, Optional

from clients.chroma_client import ChromaClient

logger = logging.getLogger(__name__)


class ContextSearcher:
    """
    Searches for context related to errors using ChromaDB.
    
    Finds:
    - Related code from GitHub
    - Similar issues from GitHub Issues
    - Relevant documentation
    """
    
    def __init__(self):
        self._init_airweave()
    
    def _init_airweave(self):
        """Initialize the ChromaDB client."""
        try:
            self.client = ChromaClient(
                persist_dir=os.getenv(
                    "CHROMA_PERSIST_DIR",
                    "./data/chroma"
                )
            )
            self.configured = True
            self.collection_id = None
            logger.info("ChromaDB client initialized")
        except Exception as e:
            logger.warning(f"Failed to initialize ChromaDB: {e}")
            self.client = None
            self.configured = False
    
    async def search_context(self, clusters: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Search for context related to each error cluster.
        
        Args:
            clusters: List of error clusters from clustering step
            
        Returns:
            List of context results per cluster
        """
        results = []
        
        for cluster in clusters:
            signature = cluster.get("signature", "")
            sample_message = cluster.get("sample_message", "")
            
            # Build search query
            query = f"{signature} {sample_message}"[:500]
            
            if self.configured and self.client:
                context = await self._airweave_search(query, cluster)
            else:
                context = self._mock_search(cluster)
            
            results.append({
                "cluster_signature": signature,
                "context": context
            })
        
        return results
    
    async def _airweave_search(self, query: str, cluster: Dict[str, Any]) -> Dict[str, Any]:
        """Search Airweave for relevant context."""
        try:
            # Search for code context
            code_results = await self._search_source(query, source_filter="github")
            
            # Search for related tickets
            ticket_results = await self._search_source(query, source_filter="github_issues")
            
            # Search documentation
            doc_results = await self._search_source(query, source_filter=None, limit=3)
            
            return {
                "code_snippets": code_results,
                "related_tickets": ticket_results,
                "documentation": doc_results,
                "search_query": query[:100],
            }
            
        except Exception as e:
            logger.error(f"Airweave search failed: {e}", exc_info=True)
            return self._mock_search(cluster)
    
    async def _search_source(
        self,
        query: str,
        source_filter: Optional[str] = None,
        limit: int = 5
    ) -> List[Dict]:
        """Search ChromaDB for relevant context."""
        try:
            results = await self.client.search(
                query=query,
                source_filter=source_filter,
                limit=limit
            )

            formatted = []

            for r in results:
                formatted.append({
                    "title": r.get("metadata", {}).get(
                        "title",
                        r.get("metadata", {}).get(
                            "path",
                            "Untitled"
                        )
                    ),
                    "content": r.get("content", "")[:500],
                    "source": source_filter or "unknown",
                    "url": r.get("metadata", {}).get("url"),
                    "score": r.get("score", 0)
                })

            return formatted

        except Exception:
            return []
    
    def _mock_search(self, cluster: Dict[str, Any]) -> Dict[str, Any]:
        """Return mock search results for demo without Airweave configured."""
        signature = cluster.get("signature", "Unknown error")
        modules = cluster.get("modules", ["unknown"])

        async def search(self, query: str, limit: int = 5, source_filter: Optional[str] = None) -> List[Dict[str, Any]]:
            """Compatibility wrapper returning a flat list of results for simple `search` calls.

            This method is a thin, backward-compatible adapter used by tests and
            older callers that expect an async `search(query, limit)` API.
            """
            if self.configured and self.client:
                try:
                    results = await self.client.search(query=query, source_filter=source_filter, limit=limit)
                    formatted = []
                    for r in results:
                        formatted.append({
                            "content": r.get("content", ""),
                            "metadata": r.get("metadata", {}),
                            "score": r.get("score", 0),
                        })
                    return formatted
                except Exception:
                    return []

            # Fallback to mock search
            cluster = {"signature": query, "modules": []}
            context = self._mock_search(cluster)
            out = []
            for src in ("code_snippets", "related_tickets", "documentation"):
                for item in context.get(src, []):
                    out.append({"content": item.get("content"), "metadata": {"title": item.get("title"), "url": item.get("url")}, "score": item.get("score", 0)})
            return out
        
        # Generate realistic mock results based on the error
        mock_code = []
        mock_tickets = []
        mock_slack = []
        
        if "429" in signature or "rate limit" in signature.lower():
            mock_code = [
                {
                    "title": "connectors/google_drive/client.py",
                    "content": """from tenacity import retry, stop_after_attempt, wait_exponential

class GoogleDriveClient:
    @retry(
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=1, min=2, max=60),
        retry=retry_if_exception_type(RateLimitError)
    )
    async def download_file(self, file_id: str) -> bytes:
        try:
            response = await self._service.files().get_media(fileId=file_id).execute()
            return response
        except HttpError as e:
            if e.resp.status == 429:
                logger.warning(f"Rate limited on file {file_id}, will retry")
                raise RateLimitError(e.resp.get('Retry-After', 60))
            raise""",
                    "source": "github",
                    "url": "https://github.com/acme/sync-platform/blob/main/connectors/google_drive/client.py#L47-L62",
                    "score": 0.94,
                }
            ]
            mock_tickets = [
                {
                    "title": "Google Drive rate limits hitting during large workspace syncs",
                    "content": "**Problem:** Customers with 10k+ files in Drive are hitting 429s consistently.\n\n**Root cause:** We're making parallel requests without respecting quotas.\n\n**Fix:** Implemented token bucket rate limiter with 100 req/100s limit. Also added request batching for metadata calls.\n\n**Status:** Fixed in v2.4.1",
                    "source": "github_issues",
                    "url": "https://github.com/acme/sync-platform/issues/1847",
                    "score": 0.91,
                }
            ]
            mock_slack = [
                {
                    "title": "#eng-incidents",
                    "content": "**@sarah.chen** (2 days ago): Seeing 429 spike from Google Drive - 340 errors in last hour\n**@mike.torres**: Checking quotas dashboard now. We're at 95% of daily limit.\n**@sarah.chen**: Ah that explains it. Large customer \"Acme Corp\" just started initial sync.\n**@mike.torres**: I'll enable the new rate limiter for their org. Should smooth out the requests.",
                    "source": "slack",
                    "url": "https://acme.slack.com/archives/C02KXHN8P/p1705312847",
                    "score": 0.89,
                },
                {
                    "title": "#eng-backend",
                    "content": "**@alex.kumar** (1 week ago): PSA - Google reduced Drive API quotas from 1000 to 600 req/100s for free tier. Enterprise accounts still have 1000. Make sure we're checking the tier before setting rate limits.\n**@sarah.chen**: Good catch, I'll update the config. We have it hardcoded to 1000 everywhere.",
                    "source": "slack",
                    "url": "https://acme.slack.com/archives/C03PLMQ9Z/p1704721234",
                    "score": 0.78,
                }
            ]
        elif "database" in signature.lower() or "connection" in signature.lower() or "pool" in signature.lower():
            mock_code = [
                {
                    "title": "core/db/session.py",
                    "content": """from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.pool import NullPool, AsyncAdaptedQueuePool

# Production configuration - tune based on your workload
engine = create_async_engine(
    settings.DATABASE_URL,
    poolclass=AsyncAdaptedQueuePool,
    pool_size=20,           # Base connections
    max_overflow=30,        # Extra connections under load
    pool_timeout=30,        # Wait time for connection
    pool_recycle=3600,      # Recycle connections after 1hr
    pool_pre_ping=True,     # Verify connection health
    echo=settings.DEBUG,
)

async def get_db() -> AsyncSession:
    async with AsyncSession(engine, expire_on_commit=False) as session:
        yield session""",
                    "source": "github",
                    "url": "https://github.com/acme/sync-platform/blob/main/core/db/session.py#L12-L28",
                    "score": 0.92,
                }
            ]
            mock_tickets = [
                {
                    "title": "Connection pool exhaustion causing 500s during peak hours",
                    "content": "**Impact:** ~2% of API requests failing between 2-4pm UTC\n\n**Investigation:**\n- `pg_stat_activity` shows 50 connections from api-server pods\n- Pool size was 10 per pod × 5 pods = 50 (at limit)\n- Long-running sync queries holding connections\n\n**Resolution:**\n1. Increased pool_size to 20 per pod\n2. Added statement_timeout=30s for sync queries\n3. Moving heavy queries to read replica\n\n**Monitoring:** Added pool_exhausted metric to dashboard",
                    "source": "github_issues",
                    "url": "https://github.com/acme/sync-platform/issues/2103",
                    "score": 0.88,
                }
            ]
            mock_slack = [
                {
                    "title": "#eng-incidents",
                    "content": "**@on-call** (3 hours ago): 🚨 P1 - DB connection errors spiking. 50 errors/min.\n**@mike.torres**: Checking pg_stat_activity... we have 48/50 connections in \"active\" state\n**@sarah.chen**: That sync job for Enterprise Ltd is running a massive query without LIMIT\n**@mike.torres**: Found it - killing PID 23847. Also, we need to add query timeouts.\n**@on-call**: Errors clearing up. Let's add this to the postmortem.",
                    "source": "slack",
                    "url": "https://acme.slack.com/archives/C02KXHN8P/p1705398234",
                    "score": 0.93,
                },
                {
                    "title": "#eng-backend",
                    "content": "**@alex.kumar**: Reminder - if you're adding new DB queries in sync workers, please use `async with db.begin():` context manager. We've had connection leaks from forgotten commits.\n**@sarah.chen**: Also set reasonable timeouts. I just added `statement_timeout` to all sync queries - default 30s.",
                    "source": "slack",
                    "url": "https://acme.slack.com/archives/C03PLMQ9Z/p1705312234",
                    "score": 0.75,
                }
            ]
        elif "401" in signature or "auth" in signature.lower() or "oauth" in signature.lower() or "token" in signature.lower():
            mock_code = [
                {
                    "title": "integrations/oauth/refresh.py",
                    "content": """async def refresh_oauth_token(integration: Integration) -> OAuthToken:
    \"\"\"Refresh an OAuth token, handling various failure modes.\"\"\"
    if not integration.refresh_token:
        raise TokenRefreshError("No refresh token - user must reauthorize")
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                integration.provider.token_url,
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": integration.refresh_token,
                    "client_id": settings.OAUTH_CLIENT_ID,
                    "client_secret": settings.OAUTH_CLIENT_SECRET,
                },
                timeout=10.0,
            )
            response.raise_for_status()
            return OAuthToken(**response.json())
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 400:
            # Token revoked or expired - user needs to reconnect
            await mark_integration_disconnected(integration.id)
            raise TokenRevokedError("Refresh token invalid")
        raise""",
                    "source": "github",
                    "url": "https://github.com/acme/sync-platform/blob/main/integrations/oauth/refresh.py#L23-L48",
                    "score": 0.95,
                }
            ]
            mock_tickets = [
                {
                    "title": "Google OAuth tokens expiring unexpectedly after 7 days",
                    "content": "**Issue:** Users report integrations disconnecting without warning\n\n**Root cause:** Google's \"Testing\" OAuth status expires refresh tokens after 7 days of user inactivity. Need to apply for \"Production\" verification.\n\n**Workaround:** Email users 5 days after last activity to prompt re-auth\n\n**Long-term fix:**\n1. Submit app for Google verification (in progress)\n2. Add proactive token refresh before expiry\n3. Better error messaging in UI",
                    "source": "github_issues",
                    "url": "https://github.com/acme/sync-platform/issues/1592",
                    "score": 0.92,
                }
            ]
            mock_slack = [
                {
                    "title": "#eng-incidents",
                    "content": "**@sarah.chen** (yesterday): OAuth 401 errors up 300% since Tuesday\n**@alex.kumar**: Let me check... mostly Google integrations that haven't synced in 7+ days\n**@mike.torres**: Classic Google \"testing mode\" behavior. Their refresh tokens expire after 7 days of inactivity until we get verified.\n**@sarah.chen**: How long until verification?\n**@alex.kumar**: Google says 4-6 weeks. For now, we should email affected users.",
                    "source": "slack",
                    "url": "https://acme.slack.com/archives/C02KXHN8P/p1705225847",
                    "score": 0.94,
                },
                {
                    "title": "#customer-support",
                    "content": "**@support-lead**: Getting a lot of tickets about \"disconnected\" Google Drive integrations. Is there something going on?\n**@alex.kumar**: Yes, known issue - Google tokens expiring. We've drafted an email to affected customers with reconnection instructions. Should go out in 30 mins.",
                    "source": "slack",
                    "url": "https://acme.slack.com/archives/C04SUPPORT/p1705311234",
                    "score": 0.82,
                }
            ]
        elif "pdf" in signature.lower() or "corrupt" in signature.lower() or "parse" in signature.lower():
            mock_code = [
                {
                    "title": "processors/document/pdf_extractor.py",
                    "content": """import pypdf
from pypdf.errors import PdfReadError

async def extract_text_from_pdf(file_path: Path) -> str:
    \"\"\"Extract text from PDF, handling various failure modes.\"\"\"
    try:
        reader = pypdf.PdfReader(file_path)
        
        # Check for encryption
        if reader.is_encrypted:
            raise DocumentProcessingError("PDF is password protected")
        
        text_parts = []
        for page in reader.pages:
            text_parts.append(page.extract_text() or "")
        
        return "\\n".join(text_parts)
        
    except PdfReadError as e:
        logger.warning(f"PDF parsing failed: {e}")
        # Fall back to OCR for corrupted/scanned PDFs
        return await ocr_fallback(file_path)""",
                    "source": "github",
                    "url": "https://github.com/acme/sync-platform/blob/main/processors/document/pdf_extractor.py#L15-L35",
                    "score": 0.89,
                }
            ]
            mock_tickets = [
                {
                    "title": "PDF processing failing on scanned documents",
                    "content": "**Problem:** Some customer PDFs fail with \"EOF marker not found\"\n\n**Analysis:** These are scanned PDFs where the scanner software created non-standard PDF structure.\n\n**Solution:**\n1. Added OCR fallback using Tesseract\n2. Skip corrupted files and mark for manual review\n3. Notify customer of unprocessable files",
                    "source": "github_issues",
                    "url": "https://github.com/acme/sync-platform/issues/987",
                    "score": 0.85,
                }
            ]
            mock_slack = [
                {
                    "title": "#eng-data-processing",
                    "content": "**@alex.kumar**: PDF extraction failing a lot today - 12% failure rate\n**@sarah.chen**: Most are old scanned docs. The scanner created malformed PDFs.\n**@alex.kumar**: We should add OCR fallback for these cases. I'll create a ticket.\n**@mike.torres**: Also let's skip and notify rather than blocking the whole sync.",
                    "source": "slack",
                    "url": "https://acme.slack.com/archives/C05DATA/p1705398234",
                    "score": 0.83,
                }
            ]
        elif "memory" in signature.lower() or "oom" in signature.lower():
            mock_code = [
                {
                    "title": "processors/embedding/batch_processor.py",
                    "content": """import gc
from itertools import islice

BATCH_SIZE = 1000  # Process in smaller batches to avoid OOM
MAX_MEMORY_MB = 2048

async def generate_embeddings_batch(documents: List[Document]) -> List[Embedding]:
    \"\"\"Generate embeddings in memory-safe batches.\"\"\"
    all_embeddings = []
    
    for batch_start in range(0, len(documents), BATCH_SIZE):
        batch = documents[batch_start:batch_start + BATCH_SIZE]
        
        # Check memory before processing
        if get_memory_usage_mb() > MAX_MEMORY_MB:
            gc.collect()
            await asyncio.sleep(0.1)  # Allow cleanup
        
        embeddings = await embedding_model.encode(batch)
        all_embeddings.extend(embeddings)
        
        # Explicit cleanup
        del batch
        gc.collect()
    
    return all_embeddings""",
                    "source": "github",
                    "url": "https://github.com/acme/sync-platform/blob/main/processors/embedding/batch_processor.py#L24-L48",
                    "score": 0.91,
                }
            ]
            mock_slack = [
                {
                    "title": "#eng-incidents",
                    "content": "**@on-call**: Worker pod processor-7d8f9 got OOMKilled. Memory spiked to 4.2GB before termination.\n**@mike.torres**: That's the embedding worker. Large customer sync with 500k documents.\n**@sarah.chen**: We need to stream instead of loading everything. I'll refactor to use batching.\n**@alex.kumar**: Also bump memory limit to 6GB as a stopgap while we fix the code.",
                    "source": "slack",
                    "url": "https://acme.slack.com/archives/C02KXHN8P/p1705412847",
                    "score": 0.90,
                }
            ]
        else:
            # Generic mock results
            module_name = modules[0] if modules else "core"
            mock_code = [
                {
                    "title": f"{module_name}/error_handler.py",
                    "content": """from sentry_sdk import capture_exception

async def handle_connector_error(error: Exception, context: SyncContext):
    \"\"\"Centralized error handling for connector failures.\"\"\"
    logger.error(
        f"Connector error: {error}",
        extra={
            "org_id": context.org_id,
            "connector": context.connector_type,
            "trace_id": context.trace_id,
        }
    )
    
    if is_retryable(error):
        raise Retry(countdown=exponential_backoff(context.attempt))
    
    # Non-retryable: notify and mark sync as failed
    await notify_sync_failure(context)
    capture_exception(error)""",
                    "source": "github",
                    "url": f"https://github.com/acme/sync-platform/blob/main/{module_name}/error_handler.py#L18-L35",
                    "score": 0.78,
                }
            ]
            mock_slack = [
                {
                    "title": "#eng-incidents",
                    "content": "**@on-call**: New error pattern in logs - seeing this for the first time\n**@sarah.chen**: Can you share the trace ID? I'll dig into the full stack trace.\n**@mike.torres**: Might be related to the deploy we did at 2pm. Let me check the diff.",
                    "source": "slack",
                    "url": "https://acme.slack.com/archives/C02KXHN8P/p1705398234",
                    "score": 0.72,
                },
                {
                    "title": "#eng-backend",
                    "content": "**@alex.kumar**: Reminder for the team - always include org_id and trace_id in error logs. Makes debugging production issues much easier.\n**@sarah.chen**: +1. Also added structured logging to the connector base class so we get this automatically now.",
                    "source": "slack",
                    "url": "https://acme.slack.com/archives/C03PLMQ9Z/p1705312234",
                    "score": 0.68,
                }
            ]
        
        return {
            "code_snippets": mock_code,
            "related_tickets": mock_tickets,
            "documentation": mock_slack,
            "search_query": signature[:100],
            "is_mock": True,
        }
