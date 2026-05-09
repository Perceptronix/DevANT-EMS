"""Unified Phase 3 ↔ Phase 4 orchestrator: OTLP ingestion → embeddings → HDBSCAN clustering → incidents.

Connects:
- OTLP log ingestion
- Embedding generation (BAAI/bge-small-en-v1.5)
- pgvector storage
- HDBSCAN semantic clustering
- Event group creation
- Root cause analysis
- Incident generation with duplicate prevention
"""
import logging
import hashlib
from typing import Optional, Any, Dict, List
from datetime import datetime
from uuid import UUID

import numpy as np
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


class OTLPClusteringOrchestrator:
    """Orchestrates full OTLP → clustering → analysis → incident flow."""

    def __init__(self):
        """Initialize dependencies lazily."""
        self._embedding_service = None
        self._clustering_pipeline = None
        self._groq_client = None
        self._db_client = None

    @property
    def embedding_service(self):
        """Get or create embedding service."""
        if self._embedding_service is None:
            from embeddings.semantic_embedding_service import get_semantic_embedding_service

            self._embedding_service = get_semantic_embedding_service()
        return self._embedding_service

    @property
    def clustering_pipeline(self):
        """Get or create clustering pipeline."""
        if self._clustering_pipeline is None:
            from pipeline.cluster_processing import get_cluster_processing_pipeline

            self._clustering_pipeline = get_cluster_processing_pipeline(
                min_cluster_size=2,
                min_samples=1,
                merge_similarity_threshold=0.90,
                fetch_limit=500,
                lookback_minutes=5,
            )
        return self._clustering_pipeline

    @property
    def db_client(self):
        """Get database client."""
        if self._db_client is None:
            from database.client import get_database_client

            self._db_client = get_database_client()
        return self._db_client

    def process_otlp_event(
        self,
        raw_event_id: UUID,
        message: str,
        stack_trace: Optional[str],
        service: str,
        environment: str,
        project_id: UUID,
        fingerprint: str,
        session: Session,
    ) -> Dict[str, Any]:
        """Process single OTLP event: generate embedding, store, cluster, analyze.

        Returns dict with:
        - embedding_stored: bool
        - cluster_id: optional UUID
        - incident_created: bool
        - error: optional str
        """
        result = {
            "embedding_stored": False,
            "cluster_id": None,
            "incident_created": False,
            "error": None,
        }

        try:
            # Step 1: Generate embedding
            semantic_text = self._build_semantic_text(message, stack_trace, service)
            embedding = self.embedding_service.embed_text(semantic_text)

            if embedding is None or len(embedding) == 0:
                result["error"] = "Embedding generation returned empty vector"
                logger.warning(
                    "Failed to generate embedding for event %s: empty vector",
                    raw_event_id,
                )
                return result

            # Step 2: Store embedding in pgvector
            try:
                from database.models import RawEvent

                event = session.query(RawEvent).filter(RawEvent.id == raw_event_id).first()
                if event:
                    event.embedding = embedding.astype(np.float32).tolist()
                    session.flush()
                    result["embedding_stored"] = True
                    logger.info("Stored embedding for event %s", raw_event_id)
            except Exception as exc:
                result["error"] = f"Failed to store embedding: {exc}"
                logger.error("Failed to store embedding for event %s: %s", raw_event_id, exc)
                return result

            # Step 3: Trigger clustering if enough events accumulated
            # (Scheduled job handles batch clustering; here we just mark as ready)
            logger.info("Event %s ready for clustering pipeline", raw_event_id)

        except Exception as exc:
            result["error"] = str(exc)
            logger.error("Error processing OTLP event %s: %s", raw_event_id, exc, exc_info=True)

        return result

    def process_recent_unclustered_batch(
        self,
        project_id: UUID,
        session: Session,
    ) -> Dict[str, Any]:
        """Run HDBSCAN clustering on recent unclustered events + analyze + create incidents.

        Returns dict with clustering, analysis, and incident counts.
        """
        result = {
            "fetched_events": 0,
            "embedded_events": 0,
            "noise_ignored": 0,
            "created_clusters": 0,
            "updated_clusters": 0,
            "assigned_events": 0,
            "analyzed_clusters": 0,
            "incidents_created": 0,
            "error": None,
        }

        try:
            # Step 1: Run clustering pipeline (HDBSCAN)
            cluster_result = self.clustering_pipeline.process_recent_unclustered_events(
                project_id=project_id
            )

            result["fetched_events"] = cluster_result.get("fetched_events", 0)
            result["embedded_events"] = cluster_result.get("embedded_events", 0)
            result["noise_ignored"] = cluster_result.get("noise_ignored", 0)
            result["created_clusters"] = cluster_result.get("created_event_groups", 0)
            result["updated_clusters"] = cluster_result.get("updated_event_groups", 0)
            result["assigned_events"] = cluster_result.get("assigned_events", 0)

            if cluster_result.get("error"):
                result["error"] = cluster_result["error"]
                logger.error(
                    "Clustering pipeline error for project %s: %s",
                    project_id,
                    cluster_result["error"],
                )
                return result

            # Step 2: Analyze clusters and create incidents
            try:
                from database.repositories.entities import ErrorClusterRepository, IncidentRepository
                from database.models import ErrorCluster

                cluster_repo = ErrorClusterRepository(session)
                incident_repo = IncidentRepository(session)

                # Fetch newly created/updated clusters
                clusters = cluster_repo.get_by_project(project_id=project_id, limit=100)

                for cluster in clusters:
                    # Check for duplicate incidents (same cluster, not already analyzed)
                    from database.models import Incident

                    existing_incident = (
                        session.query(Incident)
                        .filter(Incident.cluster_id == cluster.id)
                        .filter(Incident.ai_confidence > 0)
                        .first()
                    )

                    if existing_incident:
                        logger.debug("Cluster %s already has incident; skipping", cluster.id)
                        continue

                    # Run root cause analysis
                    analysis = self._analyze_cluster(cluster, session)
                    if analysis is None:
                        logger.warning("Root cause analysis failed for cluster %s", cluster.id)
                        continue

                    # Create or update incident
                    if existing_incident:
                        existing_incident.title = analysis.get("title")
                        existing_incident.summary = analysis.get("summary")
                        existing_incident.root_cause = analysis.get("root_cause")
                        existing_incident.recommendations = analysis.get("recommendations", {})
                        existing_incident.ai_confidence = analysis.get("confidence", 0.7)
                    else:
                        incident = incident_repo.create(
                            cluster_id=cluster.id,
                            title=analysis.get("title", f"Cluster {cluster.id}")[:512],
                            summary=analysis.get("summary", "")[:2048],
                            root_cause=analysis.get("root_cause", "")[:2048],
                            recommendations=analysis.get("recommendations", {}),
                            ai_confidence=analysis.get("confidence", 0.7),
                        )
                        result["incidents_created"] += 1
                        logger.info(
                            "Created incident %s for cluster %s",
                            incident.id,
                            cluster.id,
                        )

                    result["analyzed_clusters"] += 1

                session.commit()

            except Exception as exc:
                session.rollback()
                result["error"] = f"Incident creation failed: {exc}"
                logger.error(
                    "Failed to create incidents for project %s: %s",
                    project_id,
                    exc,
                    exc_info=True,
                )

        except Exception as exc:
            result["error"] = str(exc)
            logger.error(
                "Error in batch clustering/analysis for project %s: %s",
                project_id,
                exc,
                exc_info=True,
            )

        return result

    def _build_semantic_text(
        self,
        message: str,
        stack_trace: Optional[str],
        service: str,
    ) -> str:
        """Build semantic text for embedding.

        Combines message, first stack frame, and service for semantic richness.
        """
        parts = []

        if message:
            parts.append(message)

        if stack_trace:
            first_line = stack_trace.split("\n")[0].strip()
            if first_line and first_line not in message:
                parts.append(first_line)

        if service:
            parts.append(f"Service: {service}")

        return " ".join(parts)

    def _analyze_cluster(
        self,
        cluster,
        session: Session,
    ) -> Optional[Dict[str, Any]]:
        """Run root cause analysis on a cluster using Groq.

        Returns dict with:
        - title
        - summary
        - root_cause
        - recommendations
        - confidence
        """
        try:
            from database.models import RawEvent

            # Gather cluster evidence
            events = (
                session.query(RawEvent)
                .filter(RawEvent.cluster_id == cluster.id)
                .order_by(RawEvent.occurred_at.desc())
                .limit(10)
                .all()
            )

            if not events:
                logger.warning("No events found for cluster %s", cluster.id)
                return None

            representative = events[0]
            messages = [e.message for e in events if e.message]
            services = sorted({e.service for e in events if e.service})
            environments = sorted({e.environment for e in events if e.environment})

            # Build analysis prompt
            prompt = self._build_analysis_prompt(
                representative=representative,
                messages=messages,
                services=services,
                environments=environments,
                cluster_size=len(events),
            )

            # Query Groq
            analysis = self._query_groq_analysis(prompt)
            if analysis is None:
                return None

            return analysis

        except Exception as exc:
            logger.error("Error analyzing cluster %s: %s", cluster.id, exc, exc_info=True)
            return None

    def _build_analysis_prompt(
        self,
        representative,
        messages: List[str],
        services: List[str],
        environments: List[str],
        cluster_size: int,
    ) -> str:
        """Build structured prompt for root cause analysis."""
        messages_str = "\n".join(f"- {m[:100]}" for m in messages[:5])
        services_str = ", ".join(services)
        environments_str = ", ".join(environments)

        prompt = f"""Analyze this error cluster and provide root cause analysis:

Representative Error: {representative.message}
Stack Trace: {representative.stack_trace or 'N/A'}
Service: {services_str}
Environments: {environments_str}
Cluster Size: {cluster_size} similar errors

Other errors in cluster:
{messages_str}

Provide a JSON response with:
{{"
  "title": "Brief error summary (max 100 chars)",
  "root_cause": "Root cause analysis (max 200 chars)",
  "remediation": "Suggested fix or investigation (max 200 chars)",
  "confidence": 0.85
}}"""
        return prompt

    def _query_groq_analysis(self, prompt: str) -> Optional[Dict[str, Any]]:
        """Query Groq for root cause analysis."""
        try:
            from groq import Groq

            client = Groq()
            message = client.messages.create(
                model="llama-3.3-70b-versatile",
                max_tokens=500,
                messages=[{"role": "user", "content": prompt}],
            )

            response_text = message.content[0].text if message.content else ""

            # Parse JSON from response
            import json
            import re

            json_match = re.search(r"\{.*\}", response_text, re.DOTALL)
            if not json_match:
                logger.warning("No JSON in Groq response: %s", response_text[:200])
                return self._fallback_analysis(prompt)

            analysis = json.loads(json_match.group())
            return {
                "title": analysis.get("title", "Error Cluster")[:100],
                "summary": analysis.get("root_cause", "")[:200],
                "root_cause": analysis.get("root_cause", "")[:200],
                "recommendations": {"remediation": analysis.get("remediation", "")},
                "confidence": analysis.get("confidence", 0.7),
            }

        except Exception as exc:
            logger.error("Groq analysis failed: %s", exc)
            return None

    def _fallback_analysis(self, prompt: str) -> Dict[str, Any]:
        """Fallback analysis when Groq fails."""
        return {
            "title": "Error Cluster",
            "summary": "Cluster analysis pending",
            "root_cause": "Cluster analysis pending",
            "recommendations": {"remediation": "Manual review required"},
            "confidence": 0.5,
        }


def get_otlp_clustering_orchestrator() -> OTLPClusteringOrchestrator:
    """Factory for orchestrator instance."""
    return OTLPClusteringOrchestrator()


__all__ = ["OTLPClusteringOrchestrator", "get_otlp_clustering_orchestrator"]
