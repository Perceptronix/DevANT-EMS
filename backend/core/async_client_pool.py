"""
Shared AsyncClient connection pool — prevents per-request client creation.

DevANT shares a single httpx.AsyncClient across all connectors.
This prevents:
- Connection pool fragmentation
- Resource exhaustion (100+ connections to same API)
- Connection timeout errors
- Memory leaks from unclosed clients

Thread-safe singleton with automatic cleanup.
"""
from __future__ import annotations

import asyncio
import logging
import threading
from typing import Optional

logger = logging.getLogger(__name__)

# Global state
_client_lock = threading.Lock()
_client_instance: Optional[object] = None
_client_refcount: int = 0

def get_async_client(timeout: float = 15.0) -> Optional[object]:
    """
    Get the shared httpx.AsyncClient instance.
    
    Creates once with connection pool limits, reuses forever.
    Thread-safe.
    
    Args:
        timeout: Request timeout in seconds (default 15)
        
    Returns:
        httpx.AsyncClient instance or None if creation fails
    """
    global _client_instance, _client_refcount
    
    # Fast path: already created
    if _client_instance is not None:
        with _client_lock:
            _client_refcount += 1
        return _client_instance
    
    # Slow path: create under lock
    with _client_lock:
        # Double-check after acquiring lock
        if _client_instance is not None:
            _client_refcount += 1
            return _client_instance
        
        # Create client with connection pool limits
        try:
            import httpx
            
            limits = httpx.Limits(
                max_connections=10,       # Max concurrent connections
                max_keepalive_connections=5,  # Keep-alive pool size
            )
            
            logger.info("Creating shared httpx.AsyncClient with connection limits (10 max, 5 keepalive)")
            _client_instance = httpx.AsyncClient(
                timeout=timeout,
                limits=limits,
            )
            _client_refcount = 1
            logger.info("✅ Shared AsyncClient created globally")
            return _client_instance
        except Exception as e:
            logger.error(f"Failed to create shared AsyncClient: {e}")
            _client_instance = None
            _client_refcount = 0
            return None

async def close_async_client():
    """
    Close the shared AsyncClient.
    
    Used for cleanup at shutdown.
    """
    global _client_instance, _client_refcount
    with _client_lock:
        if _client_instance is not None:
            logger.info("Closing shared AsyncClient")
            await _client_instance.aclose()
            _client_instance = None
            _client_refcount = 0

def release_async_client():
    """
    Release a reference to the shared client.
    
    Decrements reference count (for future pooling).
    """
    global _client_refcount
    with _client_lock:
        if _client_refcount > 0:
            _client_refcount -= 1
