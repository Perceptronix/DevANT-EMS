"""
Global embedding model cache — prevents per-request model loading.

DevANT loads the SentenceTransformer model ONCE at startup and reuses it globally.
This prevents:
- 300MB+ memory allocation per request
- 2-3s model load per request
- Memory leaks from repeated loading

Thread-safe singleton pattern.
"""
from __future__ import annotations

import logging
import threading
from typing import Optional

logger = logging.getLogger(__name__)

# Global state
_embedder_lock = threading.Lock()
_embedder_instance: Optional[object] = None
_embedder_model_name: str = "all-MiniLM-L6-v2"

def get_embedder(model_name: str = "all-MiniLM-L6-v2"):
    """
    Get the global embedding model instance.
    
    Loads once, reuses forever. Thread-safe.
    
    Args:
        model_name: HuggingFace model identifier
        
    Returns:
        SentenceTransformer instance or None if load fails
    """
    global _embedder_instance, _embedder_model_name
    
    # Fast path: already loaded
    if _embedder_instance is not None:
        return _embedder_instance
    
    # Slow path: load under lock
    with _embedder_lock:
        # Double-check after acquiring lock
        if _embedder_instance is not None:
            return _embedder_instance
        
        # Load model
        try:
            from sentence_transformers import SentenceTransformer
            logger.info(f"Loading embedding model: {model_name}")
            _embedder_instance = SentenceTransformer(model_name)
            _embedder_model_name = model_name
            logger.info("✅ Embedding model loaded globally")
            return _embedder_instance
        except Exception as e:
            logger.error(f"Failed to load embedding model {model_name}: {e}")
            _embedder_instance = None
            return None

def clear_embedder():
    """
    Clear the global embedding model from memory.
    
    Used for testing or memory cleanup.
    """
    global _embedder_instance
    with _embedder_lock:
        if _embedder_instance is not None:
            logger.info("Clearing embedding model from memory")
            _embedder_instance = None
