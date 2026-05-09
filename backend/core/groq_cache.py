"""
Global Groq LLM client cache — prevents per-request client initialization.

DevANT creates the Groq client ONCE at startup and reuses it globally.
This prevents:
- HTTP connection pool recreation per request
- API rate limit exhaustion
- 100-200ms latency per initialization

Thread-safe singleton pattern with API key validation.
"""
from __future__ import annotations

import logging
import os
import threading
from typing import Optional

logger = logging.getLogger(__name__)

# Global state
_groq_lock = threading.Lock()
_groq_instance: Optional[object] = None
_groq_api_key: Optional[str] = None

def get_groq_client(api_key: Optional[str] = None) -> Optional[object]:
    """
    Get the global Groq client instance.
    
    Initializes once, reuses forever. Thread-safe.
    
    Args:
        api_key: Groq API key (uses env var if not provided)
        
    Returns:
        Groq client instance or None if initialization fails
    """
    global _groq_instance, _groq_api_key
    
    # Determine API key
    key = api_key or os.environ.get("GROQ_API_KEY", "")
    if not key:
        logger.warning("GROQ_API_KEY not set. LLM synthesis disabled.")
        return None
    
    # Fast path: already initialized with same key
    if _groq_instance is not None and _groq_api_key == key:
        return _groq_instance
    
    # Slow path: initialize under lock
    with _groq_lock:
        # Double-check after acquiring lock
        if _groq_instance is not None and _groq_api_key == key:
            return _groq_instance
        
        # Initialize client
        try:
            from groq import Groq
            logger.info("Initializing global Groq client")
            _groq_instance = Groq(api_key=key)
            _groq_api_key = key
            logger.info("✅ Groq client initialized globally")
            return _groq_instance
        except Exception as e:
            logger.error(f"Failed to initialize Groq client: {e}")
            _groq_instance = None
            _groq_api_key = None
            return None

def clear_groq_client():
    """
    Clear the global Groq client from memory.
    
    Used for testing or cleanup.
    """
    global _groq_instance, _groq_api_key
    with _groq_lock:
        if _groq_instance is not None:
            logger.info("Clearing Groq client from memory")
            _groq_instance = None
            _groq_api_key = None

def is_groq_available() -> bool:
    """Check if Groq client is available and configured."""
    try:
        return get_groq_client() is not None
    except Exception:
        return False
