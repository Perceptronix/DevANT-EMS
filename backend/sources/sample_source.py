"""
Sample data source - always available, no configuration needed.

Generates realistic error data for demonstrating the pipeline.
Perfect for demos and testing without connecting to real systems.
"""
import logging
import random
import uuid
from datetime import datetime, timedelta
from typing import List, Optional

from .base import DataSource
from schemas import RawError

logger = logging.getLogger(__name__)


# Sample error templates for realistic demo data
SAMPLE_ERRORS = [
    {
        "level": "ERROR",
        "message": "HTTP 429 Too Many Requests: Rate limit exceeded when downloading file {file} from external storage",
        "module": "sync_worker",
        "function": "download_file",
        "container": "sync-worker",
        "error_type": "RateLimitError",
        "files": ["report_q4.pdf", "invoice_2024.xlsx", "data_export.csv", "backup.zip", "presentation.pptx"]
    },
    {
        "level": "ERROR",
        "message": "Database connection timeout after 30s: could not connect to PostgreSQL server at {host}",
        "module": "backend_api",
        "function": "get_connection",
        "container": "backend",
        "error_type": "TimeoutError",
        "hosts": ["db.internal:5432", "db-replica.internal:5432", "db-primary:5432"]
    },
    {
        "level": "ERROR",
        "message": "HTTP 502 Bad Gateway: Upstream service {service} returned invalid response",
        "module": "api_gateway",
        "function": "forward_request",
        "container": "api-gateway",
        "error_type": "BadGatewayError",
        "services": ["auth-service", "billing-service", "notification-service", "search-service"]
    },
    {
        "level": "WARNING",
        "message": "Retry attempt {attempt}/3 for operation {operation}: temporary failure",
        "module": "utils.retry",
        "function": "with_retry",
        "container": "sync-worker",
        "error_type": "RetryWarning",
        "operations": ["sync_entities", "process_batch", "upload_results", "fetch_metadata"]
    },
    {
        "level": "ERROR",
        "message": "HTTP 401 Unauthorized: OAuth token expired for user integration, refresh token invalid",
        "module": "integrations",
        "function": "refresh_oauth_token",
        "container": "sync-worker",
        "error_type": "AuthenticationError",
    },
    {
        "level": "ERROR",
        "message": "Entity not found: {entity_type} with ID {entity_id} does not exist",
        "module": "crud.entities",
        "function": "get_by_id",
        "container": "backend",
        "error_type": "NotFoundError",
        "entity_types": ["User", "Organization", "Connection", "Sync", "Document"]
    },
    {
        "level": "CRITICAL",
        "message": "Out of memory while processing batch of {count} items in {operation}",
        "module": "batch_processor",
        "function": "process_batch",
        "container": "worker",
        "error_type": "MemoryError",
        "operations": ["document_indexing", "embedding_generation", "file_processing"]
    },
    {
        "level": "ERROR",
        "message": "Connection refused: PostgreSQL connection pool exhausted, max connections ({max}) reached",
        "module": "backend_api",
        "function": "execute_query",
        "container": "backend",
        "error_type": "ConnectionPoolError",
    },
    {
        "level": "ERROR",
        "message": "ValueError: Unable to parse {file_type} file - corrupted or password protected: {filename}",
        "module": "file_processor",
        "function": "extract_text",
        "container": "sync-worker",
        "error_type": "ParseError",
        "file_types": ["PDF", "DOCX", "XLSX"],
        "filenames": ["annual_report.pdf", "contract_v2.docx", "financial_data.xlsx"]
    },
    {
        "level": "ERROR",
        "message": "HTTP 503 Service Unavailable: {provider} API is experiencing downtime",
        "module": "{provider}_connector",
        "function": "api_request",
        "container": "sync-worker",
        "error_type": "ServiceUnavailableError",
        "providers": ["Google Drive", "Slack", "Notion", "Confluence", "Jira"]
    },
]

SAMPLE_ORGS = [
    ("org-acme", "Acme Corporation"),
    ("org-globex", "Globex Systems"),
    ("org-techstart", "TechStart Inc"),
    ("org-umbrella", "Umbrella Corp"),
    ("org-wayne", "Wayne Enterprises"),
    ("org-stark", "Stark Industries"),
    ("org-oscorp", "Oscorp"),
]


class SampleDataSource(DataSource):
    """
    Generates realistic sample error data.
    
    Always available - no configuration needed.
    Perfect for demos and testing the pipeline.
    """
    
    def __init__(self, seed: Optional[int] = None):
        """
        Initialize sample source.
        
        Args:
            seed: Random seed for reproducible data (optional)
        """
        if seed is not None:
            random.seed(seed)
        logger.info("Sample data source initialized")
    
    @property
    def name(self) -> str:
        return "Sample Data"
    
    @property
    def source_type(self) -> str:
        return "sample"
    
    @property
    def is_configured(self) -> bool:
        return True  # Always available
    
    async def fetch_errors(
        self,
        window_minutes: int = 30,
        limit: int = 100
    ) -> List[RawError]:
        """Generate sample errors."""
        logger.info(f"Generating up to {limit} sample errors")
        
        errors = []
        now = datetime.utcnow()
        
        # Generate a reasonable number of errors for demo
        num_errors = min(limit, random.randint(5, 15))
        
        for i in range(num_errors):
            template = random.choice(SAMPLE_ERRORS)
            org_id, org_name = random.choice(SAMPLE_ORGS)
            
            # Generate message with random values
            message = self._generate_message(template)
            module = template["module"]
            
            # Handle provider-specific module names
            if "{provider}" in module:
                provider = random.choice(template.get("providers", ["Service"]))
                module = module.replace("{provider}", provider.lower().replace(" ", "_"))
            
            # Random timestamp within window
            timestamp = now - timedelta(minutes=random.uniform(0, window_minutes))
            
            # Random line number
            line = random.randint(50, 500)
            
            error = RawError(
                id=f"sample-{uuid.uuid4().hex[:12]}",
                timestamp=timestamp,
                level=template["level"],
                message=message,
                module=module,
                function=template["function"],
                line=line,
                container=template["container"],
                environment="production",
                org_id=org_id,
                org_name=org_name,
                stack_trace=self._generate_stack_trace(template, module, line),
                metadata={
                    "error_type": template.get("error_type", "Error"),
                    "sample": True,
                },
                source_type="sample",
            )
            errors.append(error)
        
        # Sort by timestamp descending (most recent first)
        errors.sort(key=lambda e: e.timestamp, reverse=True)
        
        logger.info(f"Generated {len(errors)} sample errors")
        return errors
    
    def _generate_message(self, template: dict) -> str:
        """Generate error message from template with random values."""
        message = template["message"]
        
        # Replace placeholders with random values
        if "{file}" in message:
            message = message.replace("{file}", random.choice(template.get("files", ["file.txt"])))
        
        if "{host}" in message:
            message = message.replace("{host}", random.choice(template.get("hosts", ["localhost:5432"])))
        
        if "{service}" in message:
            message = message.replace("{service}", random.choice(template.get("services", ["service"])))
        
        if "{attempt}" in message:
            message = message.replace("{attempt}", str(random.randint(1, 3)))
        
        if "{operation}" in message:
            message = message.replace("{operation}", random.choice(template.get("operations", ["operation"])))
        
        if "{entity_type}" in message:
            message = message.replace("{entity_type}", random.choice(template.get("entity_types", ["Entity"])))
        
        if "{entity_id}" in message:
            message = message.replace("{entity_id}", uuid.uuid4().hex[:8])
        
        if "{count}" in message:
            message = message.replace("{count}", str(random.randint(1000, 50000)))
        
        if "{max}" in message:
            message = message.replace("{max}", str(random.choice([100, 200, 500])))
        
        if "{file_type}" in message:
            message = message.replace("{file_type}", random.choice(template.get("file_types", ["File"])))
        
        if "{filename}" in message:
            message = message.replace("{filename}", random.choice(template.get("filenames", ["file.txt"])))
        
        if "{provider}" in message:
            message = message.replace("{provider}", random.choice(template.get("providers", ["Service"])))
        
        return message
    
    def _generate_stack_trace(self, template: dict, module: str, line: int) -> str:
        """Generate a fake but realistic stack trace."""
        module_path = module.replace(".", "/")
        function = template["function"]
        error_type = template.get("error_type", "Error")
        
        return f"""Traceback (most recent call last):
  File "/app/{module_path}.py", line {line}, in {function}
    result = await self._execute_operation()
  File "/app/{module_path}.py", line {line - 30}, in _execute_operation
    response = await client.request(url, timeout=30)
  File "/app/utils/http.py", line 45, in request
    raise {error_type}("{template['message'][:50]}...")
{error_type}: {template['message'][:80]}"""
    
    def get_error_url(self, error: RawError) -> Optional[str]:
        """Sample errors don't have real URLs."""
        return None
