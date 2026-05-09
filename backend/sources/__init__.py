"""
Data source factory - picks the right source based on configuration.

The factory auto-detects which sources are configured and selects
the appropriate one. Falls back to sample data if nothing else is available.
"""
import logging
from typing import Dict, Any, Optional

from .base import DataSource, RawError
from .sample_source import SampleDataSource
from .azure_source import AzureLogAnalyticsSource
from .sentry_source import SentrySource
from config import get_config

logger = logging.getLogger(__name__)

# Registry of available sources
SOURCES = {
    "sample": SampleDataSource,
    "azure": AzureLogAnalyticsSource,
    "sentry": SentrySource,
    # Future: "datadog": DatadogSource,
}


def get_data_source(source_type: Optional[str] = None) -> DataSource:
    """
    Get the configured data source.
    
    Priority:
    1. Explicit source_type parameter
    2. DATA_SOURCE environment variable
    3. Auto-detect based on available credentials
    4. Fall back to sample data
    
    Args:
        source_type: Override source type (optional)
        
    Returns:
        Configured DataSource instance
    """
    config = get_config()
    
    # 1. Check explicit parameter
    if source_type:
        requested = source_type.lower()
    else:
        # 2. Check config (from environment variable)
        requested = config.data_source.source_type.lower()
    
    # 3. If specific source requested, try to use it
    if requested and requested != "sample":
        if requested not in SOURCES:
            logger.warning(f"Unknown data source '{requested}', falling back to sample")
            return SampleDataSource()
        
        source_class = SOURCES[requested]
        source = source_class()
        
        if source.is_configured:
            logger.info(f"Using data source: {source.name}")
            return source
        else:
            logger.warning(
                f"Data source '{requested}' not configured (missing credentials), "
                f"falling back to sample data"
            )
            return SampleDataSource()
    
    # 4. Auto-detect: try each source, use first configured one
    if not requested or requested == "auto":
        for name, source_class in SOURCES.items():
            if name == "sample":
                continue
            source = source_class()
            if source.is_configured:
                logger.info(f"Auto-detected data source: {source.name}")
                return source
    
    # 5. Fall back to sample data
    logger.info("Using sample data source (default)")
    return SampleDataSource()


def get_available_sources() -> Dict[str, Dict[str, Any]]:
    """
    Get status of all available data sources.
    
    Returns dict for API/UI showing which sources are configured.
    """
    result = {}
    
    for name, source_class in SOURCES.items():
        source = source_class()
        result[name] = {
            "name": source.name,
            "type": source.source_type,
            "configured": source.is_configured,
            "active": False,  # Will be set by caller
        }
    
    return result


# Cached data source instance
_data_source: Optional[DataSource] = None


def get_cached_data_source() -> DataSource:
    """Get cached data source instance."""
    global _data_source
    if _data_source is None:
        _data_source = get_data_source()
    return _data_source


def reset_data_source():
    """Reset cached data source (for testing or config changes)."""
    global _data_source
    _data_source = None


# Export all
__all__ = [
    "DataSource",
    "RawError",
    "SampleDataSource",
    "AzureLogAnalyticsSource",
    "SentrySource",
    "get_data_source",
    "get_available_sources",
    "get_cached_data_source",
    "reset_data_source",
    "SOURCES",
]
