"""Semantic similarity search for raw_events using pgvector cosine distance."""

import logging
from typing import Any, Dict, List, Optional, Sequence

import numpy as np

from database.client import get_database_client
from database.models import RawEvent

logger = logging.getLogger(__name__)


class SemanticSimilaritySearchService:
    """Search similar raw_events by cosine similarity using pgvector."""

    def __init__(self, session=None):
        self._session = session

    @staticmethod
    def _coerce_embedding(embedding: Sequence[float]) -> List[float]:
        embedding_array = np.asarray(embedding, dtype=np.float32).reshape(-1)
        return embedding_array.tolist()

    def search_similar_events(
        self,
        embedding: Sequence[float],
        similarity_threshold: float = 0.75,
        limit: int = 10,
        project_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Return top similar raw_events sorted by similarity descending.

        Args:
            embedding: Query embedding vector.
            similarity_threshold: Minimum cosine similarity in [0, 1].
            limit: Max rows to return.
            project_id: Optional project filter.
        """
        if not 0.0 <= similarity_threshold <= 1.0:
            logger.error("Invalid similarity_threshold=%s", similarity_threshold)
            return []

        if limit <= 0:
            logger.error("Invalid limit=%s", limit)
            return []

        try:
            query_embedding = self._coerce_embedding(embedding)
        except Exception as exc:
            logger.error("Invalid query embedding: %s", exc)
            return []

        close_session = False
        session = self._session
        if session is None:
            client = get_database_client()
            session = client.get_session()
            close_session = True

        try:
            max_distance = 1.0 - similarity_threshold
            distance_expr = RawEvent.embedding.cosine_distance(query_embedding)

            query = (
                session.query(RawEvent, distance_expr.label("distance"))
                .filter(RawEvent.embedding.isnot(None))
                .filter(distance_expr <= max_distance)
            )

            if project_id is not None:
                query = query.filter(RawEvent.project_id == project_id)

            rows = query.order_by(distance_expr.asc()).limit(limit).all()

            results: List[Dict[str, Any]] = []
            for raw_event, distance in rows:
                similarity = max(0.0, 1.0 - float(distance))
                results.append(
                    {
                        "id": str(raw_event.id),
                        "project_id": str(raw_event.project_id) if raw_event.project_id else None,
                        "fingerprint": raw_event.fingerprint,
                        "source_type": raw_event.source_type,
                        "service": raw_event.service,
                        "environment": raw_event.environment,
                        "message": raw_event.message,
                        "stack_trace": raw_event.stack_trace,
                        "similarity": similarity,
                        "distance": float(distance),
                        "occurred_at": raw_event.occurred_at.isoformat() if raw_event.occurred_at else None,
                        "created_at": raw_event.created_at.isoformat() if raw_event.created_at else None,
                    }
                )

            return results

        except Exception as exc:
            logger.exception("Semantic similarity search failed: %s", exc)
            return []
        finally:
            if close_session:
                session.close()


def get_similarity_search_service(session=None) -> SemanticSimilaritySearchService:
    return SemanticSimilaritySearchService(session=session)


__all__ = ["SemanticSimilaritySearchService", "get_similarity_search_service"]
