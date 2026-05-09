"""Cluster processing pipeline for raw events using semantic embeddings + HDBSCAN.

Event groups map to `error_clusters` table.
"""

import logging
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
from sklearn.preprocessing import normalize

from database.client import get_database_client
from database.models import ErrorCluster, RawEvent, SignalFusionMetadata
from embeddings import get_semantic_clustering_service

logger = logging.getLogger(__name__)


class ClusterProcessingPipeline:
    """Process recent unclustered events into semantic event groups."""

    def __init__(
        self,
        min_cluster_size: int = 5,
        min_samples: Optional[int] = None,
        merge_similarity_threshold: float = 0.90,
        fetch_limit: int = 500,
        lookback_minutes: int = 120,
    ):
        self.min_cluster_size = max(2, int(min_cluster_size))
        self.min_samples = min_samples
        self.merge_similarity_threshold = float(merge_similarity_threshold)
        self.fetch_limit = int(fetch_limit)
        self.lookback_minutes = int(lookback_minutes)
        self.cluster_service = get_semantic_clustering_service(
            min_cluster_size=self.min_cluster_size,
            min_samples=self.min_samples,
        )

    def process_recent_unclustered_events(
        self,
        project_id: Optional[Any] = None,
        limit: Optional[int] = None,
        lookback_minutes: Optional[int] = None,
        min_cluster_size: Optional[int] = None,
        min_samples: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Run full cluster processing workflow.

        Workflow:
        1. Fetch recent unclustered events
        2. Load embeddings
        3. Run HDBSCAN
        4. Create/update event groups (`error_clusters`)
        5. Assign cluster_id to events
        """
        fetch_limit = int(limit or self.fetch_limit)
        lookback = int(lookback_minutes or self.lookback_minutes)

        summary: Dict[str, Any] = {
            "fetched_events": 0,
            "embedded_events": 0,
            "noise_ignored": 0,
            "created_event_groups": 0,
            "updated_event_groups": 0,
            "assigned_events": 0,
            "cluster_metadata": {},
            "processed_at": datetime.utcnow().isoformat(),
        }

        client = get_database_client()
        session = client.get_session()

        try:
            events = self._fetch_recent_unclustered_events(
                session=session,
                project_id=project_id,
                limit=fetch_limit,
                lookback_minutes=lookback,
            )
            summary["fetched_events"] = len(events)

            if not events:
                logger.info("Cluster pipeline: no unclustered events found")
                return summary

            embed_events, embed_matrix = self._load_embeddings(events)
            summary["embedded_events"] = len(embed_events)

            if len(embed_events) < 2:
                logger.info("Cluster pipeline: not enough embedded events to cluster")
                return summary

            cluster_result = self.cluster_service.cluster_embeddings(
                embeddings=embed_matrix,
                min_cluster_size=min_cluster_size,
                min_samples=min_samples,
            )

            labels = cluster_result.get("labels", [])
            metadata = cluster_result.get("metadata", {})
            summary["cluster_metadata"] = metadata

            groups = defaultdict(list)
            for idx, label in enumerate(labels):
                groups[int(label)].append(embed_events[idx])

            summary["noise_ignored"] = len(groups.get(-1, []))

            for label, group_events in groups.items():
                if label == -1:
                    continue
                if not group_events:
                    continue

                group_embedding = self._centroid_embedding(group_events)
                representative = self._pick_representative_event(group_events, group_embedding)

                cluster_id, merged = self._create_or_merge_event_group(
                    session=session,
                    representative_event=representative,
                    grouped_events=group_events,
                    centroid=group_embedding,
                    similarity_threshold=self.merge_similarity_threshold,
                    cluster_probability=metadata,
                )

                self._assign_cluster_id_to_events(
                    session=session,
                    event_ids=[event.id for event in group_events],
                    cluster_id=cluster_id,
                )

                self._store_cluster_statistics(
                    session=session,
                    cluster_id=cluster_id,
                    label=label,
                    events=group_events,
                    representative_event=representative,
                )

                if merged:
                    summary["updated_event_groups"] += 1
                else:
                    summary["created_event_groups"] += 1
                summary["assigned_events"] += len(group_events)

            session.commit()
            logger.info(
                "Cluster pipeline complete: fetched=%d embedded=%d created=%d updated=%d assigned=%d noise=%d",
                summary["fetched_events"],
                summary["embedded_events"],
                summary["created_event_groups"],
                summary["updated_event_groups"],
                summary["assigned_events"],
                summary["noise_ignored"],
            )
            return summary

        except Exception as exc:
            session.rollback()
            logger.exception("Cluster pipeline failed: %s", exc)
            summary["error"] = str(exc)
            return summary
        finally:
            session.close()

    def _fetch_recent_unclustered_events(
        self,
        session,
        project_id: Optional[Any],
        limit: int,
        lookback_minutes: int,
    ) -> List[RawEvent]:
        since = datetime.utcnow() - timedelta(minutes=lookback_minutes)

        query = (
            session.query(RawEvent)
            .filter(RawEvent.cluster_id.is_(None))
            .filter(RawEvent.embedding.isnot(None))
            .filter(RawEvent.occurred_at >= since)
            .order_by(RawEvent.occurred_at.desc())
        )
        if project_id is not None:
            query = query.filter(RawEvent.project_id == project_id)

        return query.limit(limit).all()

    @staticmethod
    def _load_embeddings(events: Sequence[RawEvent]) -> Tuple[List[RawEvent], np.ndarray]:
        valid_events: List[RawEvent] = []
        vectors: List[np.ndarray] = []

        for event in events:
            if event.embedding is None:
                continue
            arr = np.asarray(event.embedding, dtype=np.float32).reshape(-1)
            if arr.size == 0:
                continue
            valid_events.append(event)
            vectors.append(arr)

        if not vectors:
            return [], np.empty((0, 0), dtype=np.float32)

        matrix = np.vstack(vectors)
        return valid_events, matrix

    @staticmethod
    def _centroid_embedding(events: Sequence[RawEvent]) -> np.ndarray:
        matrix = np.vstack([np.asarray(e.embedding, dtype=np.float32).reshape(-1) for e in events])
        centroid = np.mean(matrix, axis=0)
        centroid = normalize(centroid.reshape(1, -1), norm="l2").reshape(-1)
        return centroid.astype(np.float32)

    @staticmethod
    def _pick_representative_event(events: Sequence[RawEvent], centroid: np.ndarray) -> RawEvent:
        best_event = events[0]
        best_score = -1.0

        for event in events:
            emb = np.asarray(event.embedding, dtype=np.float32).reshape(-1)
            num = float(np.dot(emb, centroid))
            denom = float(np.linalg.norm(emb) * np.linalg.norm(centroid))
            score = num / denom if denom > 0 else -1.0
            if score > best_score:
                best_score = score
                best_event = event

        return best_event

    def _find_semantically_similar_group(
        self,
        session,
        centroid: np.ndarray,
        project_id: Any,
        similarity_threshold: float,
    ) -> Optional[Any]:
        max_distance = max(0.0, 1.0 - float(similarity_threshold))
        centroid_vec = np.asarray(centroid, dtype=np.float32).reshape(-1)
        centroid_norm = float(np.linalg.norm(centroid_vec))

        if centroid_norm <= 0:
            return None

        # Use representative event embeddings for merge matching; avoids
        # hard dependency on cluster_embeddings DB column type.
        rows = (
            session.query(ErrorCluster.id, RawEvent.embedding)
            .join(RawEvent, RawEvent.id == ErrorCluster.representative_event_id)
            .filter(ErrorCluster.project_id == project_id)
            .filter(RawEvent.embedding.isnot(None))
            .all()
        )

        best_cluster_id: Optional[Any] = None
        best_distance = float("inf")

        for row in rows:
            vec = np.asarray(row.embedding, dtype=np.float32).reshape(-1)
            if vec.size == 0 or vec.shape != centroid_vec.shape:
                continue

            denom = float(np.linalg.norm(vec) * centroid_norm)
            if denom <= 0:
                continue

            similarity = float(np.dot(vec, centroid_vec) / denom)
            distance = 1.0 - similarity

            if distance <= max_distance and distance < best_distance:
                best_distance = distance
                best_cluster_id = row.id

        return best_cluster_id

    def _create_or_merge_event_group(
        self,
        session,
        representative_event: RawEvent,
        grouped_events: Sequence[RawEvent],
        centroid: np.ndarray,
        similarity_threshold: float,
        cluster_probability: Dict[str, Any],
    ) -> Tuple[Any, bool]:
        existing_id = self._find_semantically_similar_group(
            session=session,
            centroid=centroid,
            project_id=representative_event.project_id,
            similarity_threshold=similarity_threshold,
        )

        group_size = len(grouped_events)
        confidence = self._estimate_group_confidence(cluster_probability, grouped_events)

        if existing_id:
            cluster = session.query(ErrorCluster).filter(ErrorCluster.id == existing_id).first()
            if cluster is None:
                existing_id = None
            else:
                old_count = int(cluster.event_count or 0)
                cluster.event_count = old_count + group_size
                cluster.updated_at = datetime.utcnow()
                cluster.confidence = max(float(cluster.confidence or 0.0), confidence)
                if cluster.representative_event_id is None:
                    cluster.representative_event_id = representative_event.id

                return cluster.id, True

        title = self._build_group_title(representative_event)
        severity = self._infer_group_severity(grouped_events)
        cluster = ErrorCluster(
            project_id=representative_event.project_id,
            title=title,
            representative_event_id=representative_event.id,
            event_count=group_size,
            severity=severity,
            status="NEW",
            confidence=confidence,
        )
        session.add(cluster)
        session.flush()

        return cluster.id, False

    @staticmethod
    def _estimate_group_confidence(metadata: Dict[str, Any], grouped_events: Sequence[RawEvent]) -> float:
        probs = metadata.get("probabilities") or []
        if probs and len(probs) >= len(grouped_events):
            vals = [float(x) for x in probs[: len(grouped_events)]]
            return float(np.mean(vals))
        return 0.7

    @staticmethod
    def _build_group_title(event: RawEvent) -> str:
        message = (event.message or "").strip()
        if message:
            return message[:180]
        fallback = f"{event.source_type}:{event.service or 'unknown-service'}"
        return fallback[:180]

    @staticmethod
    def _infer_group_severity(events: Sequence[RawEvent]) -> str:
        text = " ".join((e.message or "") for e in events).lower()
        if any(token in text for token in ("critical", "fatal", "sev1", "panic")):
            return "S1"
        if any(token in text for token in ("error", "failed", "exception", "sev2")):
            return "S2"
        if any(token in text for token in ("warn", "warning", "sev3")):
            return "S3"
        return "S4"

    @staticmethod
    def _assign_cluster_id_to_events(session, event_ids: Sequence[Any], cluster_id: Any) -> None:
        if not event_ids:
            return
        (
            session.query(RawEvent)
            .filter(RawEvent.id.in_(list(event_ids)))
            .update({RawEvent.cluster_id: cluster_id}, synchronize_session=False)
        )

    @staticmethod
    def _store_cluster_statistics(
        session,
        cluster_id: Any,
        label: int,
        events: Sequence[RawEvent],
        representative_event: RawEvent,
    ) -> None:
        occurred = [e.occurred_at for e in events if e.occurred_at is not None]
        services = sorted({e.service for e in events if e.service})
        envs = sorted({e.environment for e in events if e.environment})

        stats = {
            "pipeline": "hdbscan-semantic",
            "cluster_label": int(label),
            "event_count": len(events),
            "representative_event_id": str(representative_event.id),
            "first_seen": min(occurred).isoformat() if occurred else None,
            "last_seen": max(occurred).isoformat() if occurred else None,
            "services": services,
            "environments": envs,
            "updated_at": datetime.utcnow().isoformat(),
        }

        record = (
            session.query(SignalFusionMetadata)
            .filter(SignalFusionMetadata.cluster_id == cluster_id)
            .first()
        )

        if record is None:
            session.add(
                SignalFusionMetadata(
                    cluster_id=cluster_id,
                    deployment_correlation=0.0,
                    temporal_proximity=0.0,
                    service_overlap_score=0.0,
                    extra_metadata=stats,
                )
            )
            return

        existing = record.extra_metadata or {}
        merged_batches = int(existing.get("merged_batches", 0)) + 1
        existing.update(stats)
        existing["merged_batches"] = merged_batches
        record.extra_metadata = existing


def get_cluster_processing_pipeline(
    min_cluster_size: int = 5,
    min_samples: Optional[int] = None,
    merge_similarity_threshold: float = 0.90,
    fetch_limit: int = 500,
    lookback_minutes: int = 120,
) -> ClusterProcessingPipeline:
    return ClusterProcessingPipeline(
        min_cluster_size=min_cluster_size,
        min_samples=min_samples,
        merge_similarity_threshold=merge_similarity_threshold,
        fetch_limit=fetch_limit,
        lookback_minutes=lookback_minutes,
    )


__all__ = ["ClusterProcessingPipeline", "get_cluster_processing_pipeline"]
