"""
Azure Log Analytics data source.

Fetches errors from Azure Log Analytics workspace.
Requires Azure credentials to be configured.
"""
import logging
from datetime import datetime, timedelta
from typing import List, Optional

from .base import DataSource
from schemas import RawError
from config import get_config

logger = logging.getLogger(__name__)


class AzureLogAnalyticsSource(DataSource):
    """
    Fetch errors from Azure Log Analytics.
    
    Requires the following environment variables:
    - AZURE_LOG_ANALYTICS_WORKSPACE_ID
    - AZURE_LOG_ANALYTICS_CLIENT_ID
    - AZURE_LOG_ANALYTICS_CLIENT_SECRET
    - AZURE_LOG_ANALYTICS_TENANT_ID
    """
    
    def __init__(self):
        config = get_config()
        self.workspace_id = config.data_source.azure_workspace_id
        self.client_id = config.data_source.azure_client_id
        self.client_secret = config.data_source.azure_client_secret
        self.tenant_id = config.data_source.azure_tenant_id
        
        self._client = None
        
        if self.is_configured:
            logger.info("Azure Log Analytics source configured")
        else:
            logger.info("Azure Log Analytics source not configured (missing credentials)")
    
    @property
    def name(self) -> str:
        return "Azure Log Analytics"
    
    @property
    def source_type(self) -> str:
        return "azure"
    
    @property
    def is_configured(self) -> bool:
        return all([
            self.workspace_id,
            self.client_id,
            self.client_secret,
            self.tenant_id,
        ])
    
    async def _get_client(self):
        """Lazy-initialize the Azure client."""
        if not self._client and self.is_configured:
            try:
                from azure.identity.aio import ClientSecretCredential
                from azure.monitor.query.aio import LogsQueryClient
                
                credential = ClientSecretCredential(
                    tenant_id=self.tenant_id,
                    client_id=self.client_id,
                    client_secret=self.client_secret,
                )
                self._client = LogsQueryClient(credential)
            except ImportError:
                logger.error(
                    "Azure SDK not installed. Install with: "
                    "pip install azure-identity azure-monitor-query"
                )
                raise
        return self._client
    
    async def fetch_errors(
        self,
        window_minutes: int = 30,
        limit: int = 100
    ) -> List[RawError]:
        """Fetch errors from Azure Log Analytics."""
        if not self.is_configured:
            logger.warning("Azure source not configured, returning empty list")
            return []
        
        client = await self._get_client()
        if not client:
            return []
        
        # KQL query for errors
        # Customize this query based on your log structure
        query = f"""
        ContainerAppConsoleLogs_CL
        | where TimeGenerated > ago({window_minutes}m)
        | where Log_s contains "ERROR" or Log_s contains "CRITICAL" or Log_s contains "WARNING"
        | extend parsed = parse_json(Log_s)
        | project
            TimeGenerated,
            ContainerName_s,
            Log_s,
            Level = tostring(parsed.level),
            Module = tostring(parsed.module),
            Function = tostring(parsed.funcName),
            Line = toint(parsed.lineno),
            Message = tostring(parsed.message),
            OrgId = tostring(parsed.organization_id),
            OrgName = tostring(parsed.organization_name)
        | order by TimeGenerated desc
        | take {limit}
        """
        
        try:
            from azure.monitor.query import LogsQueryStatus
            
            response = await client.query_workspace(
                workspace_id=self.workspace_id,
                query=query,
                timespan=timedelta(minutes=window_minutes),
            )
            
            if response.status != LogsQueryStatus.SUCCESS:
                logger.error(f"Azure query failed: {response.partial_error}")
                return []
            
            errors = []
            for table in response.tables:
                for row in table.rows:
                    error = self._row_to_error(row, table.columns)
                    if error:
                        errors.append(error)
            
            logger.info(f"Fetched {len(errors)} errors from Azure Log Analytics")
            return errors
            
        except Exception as e:
            logger.error(f"Failed to fetch from Azure: {e}", exc_info=True)
            return []
    
    def _row_to_error(self, row: list, columns: list) -> Optional[RawError]:
        """Convert Azure row to RawError."""
        try:
            # Build dict from row
            data = {col.name: row[i] for i, col in enumerate(columns)}
            
            # Extract timestamp
            timestamp = data.get("TimeGenerated")
            if isinstance(timestamp, str):
                timestamp = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            
            return RawError(
                id=f"azure-{timestamp.isoformat()}-{hash(data.get('Log_s', '')) % 10000}",
                timestamp=timestamp,
                level=data.get("Level", "ERROR"),
                message=data.get("Message", data.get("Log_s", ""))[:500],
                module=data.get("Module"),
                function=data.get("Function"),
                line=data.get("Line"),
                container=data.get("ContainerName_s"),
                environment="production",
                org_id=data.get("OrgId"),
                org_name=data.get("OrgName"),
                metadata={"raw_log": data.get("Log_s")},
                source_type="azure",
                source_url=self._generate_url(data),
            )
        except Exception as e:
            logger.error(f"Failed to parse Azure row: {e}")
            return None
    
    def _generate_url(self, data: dict) -> Optional[str]:
        """Generate Azure Portal deep link."""
        if not self.workspace_id:
            return None
        
        # Azure Log Analytics deep link format
        # Note: This is a simplified version - actual deep links are more complex
        return (
            f"https://portal.azure.com/#blade/Microsoft_Azure_Monitoring_Logs/LogsBlade"
            f"/resourceId/workspaces/{self.workspace_id}"
        )
    
    def get_error_url(self, error: RawError) -> Optional[str]:
        """Get Azure Portal deep link for error."""
        return error.source_url or self._generate_url({})
