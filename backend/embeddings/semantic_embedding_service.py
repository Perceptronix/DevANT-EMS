"""Semantic embedding service wrapper providing unified text→embedding interface."""
import logging
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)


class SemanticEmbeddingService:
    """Wrapper around base EmbeddingService providing semantic text embedding."""

    def __init__(self):
        from embeddings.embedding_service import get_embedding_service

        self.base_service = get_embedding_service()

    def embed_text(self, text: str) -> Optional[np.ndarray]:
        """Generate embedding for semantic text.

        Returns NumPy float32 array of dimension 384 (BAAI/bge-small-en-v1.5).
        Returns None if text is empty or embedding generation fails.
        """
        if not text or not str(text).strip():
            logger.debug("Empty text provided to embed_text")
            return None

        try:
            embedding = self.base_service.generate_embedding(text)
            if embedding is not None and len(embedding) > 0:
                return embedding.astype(np.float32)
            return None
        except Exception as exc:
            logger.error("Failed to embed text: %s", exc, exc_info=True)
            return None

    def embed_batch(self, texts: list[str]) -> list[Optional[np.ndarray]]:
        """Generate embeddings for multiple texts."""
        return [self.embed_text(text) for text in texts]


def get_semantic_embedding_service() -> SemanticEmbeddingService:
    """Factory for semantic embedding service."""
    return SemanticEmbeddingService()


__all__ = ["SemanticEmbeddingService", "get_semantic_embedding_service"]
