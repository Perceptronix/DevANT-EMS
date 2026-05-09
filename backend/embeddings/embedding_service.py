import logging
from typing import Optional

import numpy as np
import torch
from sentence_transformers import SentenceTransformer

logger = logging.getLogger(__name__)


class EmbeddingService:
    """Singleton service for generating normalized embeddings.

    Uses SentenceTransformer model (BAAI/bge-small-en-v1.5 by default).
    """

    _instance: Optional["EmbeddingService"] = None

    def __new__(cls, model_name: str = "BAAI/bge-small-en-v1.5", device: Optional[str] = None):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._init_model(model_name=model_name, device=device)
        return cls._instance

    def _init_model(self, model_name: str, device: Optional[str]):
        if device is None:
            device = "cuda" if torch.cuda.is_available() else "cpu"
        self.device = device
        logger.info("Loading embedding model %s on %s", model_name, device)
        # SentenceTransformer will load model onto requested device when provided
        self.model = SentenceTransformer(model_name, device=device)
        self.dim = int(self.model.get_embedding_dimension())
        logger.info("Loaded embedding model: dim=%d", self.dim)

    def generate_embedding(self, text: str) -> np.ndarray:
        """Generate a normalized embedding for given text.

        - Returns NumPy array for model-friendly downstream math
        - Handles empty text by returning zero vector of model dimension
        - Uses `torch.no_grad()` during inference
        """
        if text is None or not str(text).strip():
            logger.warning("Empty or whitespace text provided to generate_embedding; returning zero vector")
            return np.zeros(self.dim, dtype=np.float32)

        try:
            with torch.no_grad():
                emb = self.model.encode(text, convert_to_tensor=True, normalize_embeddings=True)

                if torch.is_tensor(emb):
                    emb = emb.to("cpu")
                    return emb.detach().numpy().astype(np.float32, copy=False)

                emb_arr = np.asarray(emb, dtype=np.float32)
                return emb_arr.astype(np.float32, copy=False)

        except Exception as exc:  # keep broad except for robustness
            logger.exception("Error generating embedding: %s", exc)
            return np.zeros(self.dim, dtype=np.float32)


def get_embedding_service(model_name: str = "BAAI/bge-small-en-v1.5", device: Optional[str] = None) -> EmbeddingService:
    """Helper to retrieve singleton instance."""
    return EmbeddingService(model_name=model_name, device=device)


__all__ = ["EmbeddingService", "get_embedding_service"]
