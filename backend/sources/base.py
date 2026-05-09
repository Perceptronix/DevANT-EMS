"""
Abstract base class for error data sources.

All data sources (sample, Sentry, Azure, etc.) implement this interface
to provide a consistent way to fetch errors for the pipeline.
"""
from abc import ABC, abstractmethod
from typing import List, Optional, Dict, Any

from schemas import RawError


class DataSource(ABC):
    """
    Abstract base class for error data sources.
    
    Each implementation converts source-specific data to RawError format,
    allowing the pipeline to work with any error monitoring system.
    """
    
    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable name of the data source."""
        pass
    
    @property
    @abstractmethod
    def source_type(self) -> str:
        """Machine identifier for this source type."""
        pass
    
    @property
    @abstractmethod
    def is_configured(self) -> bool:
        """Check if the source has valid credentials/configuration."""
        pass
    
    @abstractmethod
    async def fetch_errors(
        self,
        window_minutes: int = 30,
        limit: int = 100
    ) -> List[RawError]:
        """
        Fetch recent errors from the source.
        
        Args:
            window_minutes: How far back to look for errors
            limit: Maximum number of errors to return
            
        Returns:
            List of normalized RawError objects
        """
        pass
    
    def get_error_url(self, error: RawError) -> Optional[str]:
        """
        Get a deep link URL to view this error in the source's UI.
        
        Args:
            error: The error to get URL for
            
        Returns:
            URL string or None if source doesn't support deep links
        """
        return error.source_url
    
    def get_status(self) -> Dict[str, Any]:
        """
        Get source status for API/UI.
        
        Returns:
            Dict with name, type, configured status
        """
        return {
            "name": self.name,
            "type": self.source_type,
            "configured": self.is_configured,
        }
