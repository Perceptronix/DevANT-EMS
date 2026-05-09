"""Semantic clustering service for embedding vectors using HDBSCAN."""

import logging
from typing import Any, Dict, List, Optional, Sequence

import hdbscan
import numpy as np
from sklearn.preprocessing import normalize

logger = logging.getLogger(__name__)


class SemanticClusteringService:
    """Cluster embedding vectors with HDBSCAN using cosine distance."""

    def __init__(self, min_cluster_size: int = 5, min_samples: Optional[int] = None):
        self.min_cluster_size = max(2, int(min_cluster_size))
        self.min_samples = min_samples

    @staticmethod
    def _coerce_embeddings(embeddings: Sequence[Sequence[float]]) -> np.ndarray:
        arr = np.asarray(embeddings, dtype=np.float32)
        if arr.ndim != 2:
            raise ValueError("Expected 2D array-like embeddings: [n_samples, n_features]")
        if arr.shape[0] == 0:
            raise ValueError("Expected non-empty embeddings input")
        if arr.shape[1] == 0:
            raise ValueError("Expected embeddings with non-zero feature dimension")
        return arr

    @staticmethod
    def _build_cluster_metadata(labels: np.ndarray, probabilities: np.ndarray) -> Dict[str, Any]:
        unique_labels, counts = np.unique(labels, return_counts=True)
        cluster_sizes: Dict[int, int] = {
            int(label): int(count)
            for label, count in zip(unique_labels, counts)
            if int(label) != -1
        }

        noise_count = int(cluster_sizes.pop(-1, 0)) if -1 in cluster_sizes else int(np.sum(labels == -1))
        n_clusters = int(np.sum(unique_labels != -1))

        return {
            "n_samples": int(labels.shape[0]),
            "n_clusters": n_clusters,
            "noise_count": noise_count,
            "noise_ratio": float(noise_count / labels.shape[0]) if labels.shape[0] else 0.0,
            "has_noise": bool(noise_count > 0),
            "cluster_sizes": cluster_sizes,
            "labels": [int(x) for x in labels.tolist()],
            "probabilities": [float(x) for x in probabilities.tolist()],
        }

    def cluster_embeddings(
        self,
        embeddings: Sequence[Sequence[float]],
        min_cluster_size: Optional[int] = None,
        min_samples: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Cluster embeddings and return labels + metadata.

        Args:
            embeddings: Input vectors as list/array of shape [n_samples, n_features].
            min_cluster_size: Optional override for HDBSCAN min_cluster_size.
            min_samples: Optional override for HDBSCAN min_samples.

        Returns:
            Dict with:
                - labels: Cluster labels list (noise points have label -1)
                - metadata: Cluster metadata including noise stats and cluster sizes
        """
        try:
            emb = self._coerce_embeddings(embeddings)
        except Exception as exc:
            logger.error("Invalid embeddings for clustering: %s", exc)
            return {
                "labels": [],
                "metadata": {
                    "n_samples": 0,
                    "n_clusters": 0,
                    "noise_count": 0,
                    "noise_ratio": 0.0,
                    "has_noise": False,
                    "cluster_sizes": {},
                    "error": str(exc),
                },
            }

        mcs = max(2, int(min_cluster_size)) if min_cluster_size is not None else self.min_cluster_size
        ms = min_samples if min_samples is not None else self.min_samples

        logger.info(
            "Running HDBSCAN semantic clustering: samples=%d dim=%d min_cluster_size=%d min_samples=%s metric=cosine",
            emb.shape[0],
            emb.shape[1],
            mcs,
            str(ms),
        )

        if emb.shape[0] < mcs:
            logger.warning(
                "Insufficient samples for clustering: n_samples=%d < min_cluster_size=%d; marking all as noise",
                emb.shape[0],
                mcs,
            )
            labels = np.full((emb.shape[0],), -1, dtype=np.int32)
            probabilities = np.zeros((emb.shape[0],), dtype=np.float32)
            metadata = self._build_cluster_metadata(labels=labels, probabilities=probabilities)
            return {"labels": metadata["labels"], "metadata": metadata}

        try:
            # Normalize vectors to stabilize cosine distance behavior and numeric range.
            emb_norm = normalize(emb, norm="l2", axis=1, copy=False).astype(np.float64, copy=False)

            clusterer = hdbscan.HDBSCAN(
                min_cluster_size=mcs,
                min_samples=ms,
                metric="cosine",
                algorithm="generic",
                cluster_selection_method="eom",
            )

            labels = clusterer.fit_predict(emb_norm).astype(np.int32, copy=False)
            probabilities = np.asarray(getattr(clusterer, "probabilities_", np.zeros(emb.shape[0])), dtype=np.float32)

            metadata = self._build_cluster_metadata(labels=labels, probabilities=probabilities)

            logger.info(
                "Semantic clustering complete: clusters=%d noise=%d/%d",
                metadata["n_clusters"],
                metadata["noise_count"],
                metadata["n_samples"],
            )

            return {
                "labels": metadata["labels"],
                "metadata": metadata,
            }

        except Exception as exc:
            logger.exception("Semantic clustering failed: %s", exc)
            labels = np.full((emb.shape[0],), -1, dtype=np.int32)
            probabilities = np.zeros((emb.shape[0],), dtype=np.float32)
            metadata = self._build_cluster_metadata(labels=labels, probabilities=probabilities)
            metadata["error"] = str(exc)
            return {
                "labels": metadata["labels"],
                "metadata": metadata,
            }


def get_semantic_clustering_service(
    min_cluster_size: int = 5,
    min_samples: Optional[int] = None,
) -> SemanticClusteringService:
    return SemanticClusteringService(min_cluster_size=min_cluster_size, min_samples=min_samples)


__all__ = ["SemanticClusteringService", "get_semantic_clustering_service"]
