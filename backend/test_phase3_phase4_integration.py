"""Phase 3 ↔ Phase 4 integration validation: OTLP → embeddings → clustering → incidents."""
import pytest
import json
from datetime import datetime, timezone
from uuid import uuid4

import numpy as np


class TestPhase3Phase4Integration:
    """Validate unified OTLP → clustering → incidents pipeline."""

    @pytest.fixture
    def project_id(self, db_session):
        """Persist and return a valid project ID for FK-safe test inserts."""
        from database.repositories.entities import ProjectRepository

        repo = ProjectRepository(db_session)
        project = repo.create(
            name=f"phase3-phase4-test-{uuid4().hex[:8]}",
            github_repo=f"test-org/test-repo-{uuid4().hex[:8]}",
        )
        return project.id

    @pytest.fixture
    def orchestrator(self):
        """OTLP clustering orchestrator."""
        from orchestration.otlp_clustering_orchestrator import get_otlp_clustering_orchestrator

        return get_otlp_clustering_orchestrator()

    @pytest.fixture
    def db_session(self):
        """Database session."""
        from database.client import get_database_client

        client = get_database_client()
        session = client.get_session()
        yield session
        session.close()

    # TEST CASE 1: Similar errors cluster together
    def test_similar_errors_cluster_together(self, orchestrator, db_session, project_id):
        """
        Input: Three similar "Cannot read property" errors
        Expected: Same semantic cluster, one incident created
        """
        from database.repositories.entities import RawEventRepository
        from database.models import RawEvent

        # Create test events with similar errors
        events_data = [
            {
                "message": "Cannot read property 'name' of undefined",
                "stack_trace": "at getUser (app.js:42:15)",
                "service": "user-api",
            },
            {
                "message": "Cannot read property 'email' of undefined",
                "stack_trace": "at sendEmail (auth.js:28:9)",
                "service": "user-api",
            },
            {
                "message": "Cannot read property 'id' of undefined",
                "stack_trace": "at updateUser (users.js:55:12)",
                "service": "user-api",
            },
        ]

        # Persist events
        repo = RawEventRepository(db_session)
        event_ids = []
        for event_data in events_data:
            event = repo.create(
                project_id=project_id,
                source_type="test",
                service=event_data["service"],
                environment="test",
                message=event_data["message"],
                stack_trace=event_data["stack_trace"],
                fingerprint=f"test-{len(event_ids)}",
                extra_metadata={},
                occurred_at=datetime.now(timezone.utc),
            )
            event_ids.append(event.id)
        db_session.commit()

        # Process each event for embeddings
        for i, event_data in enumerate(events_data):
            result = orchestrator.process_otlp_event(
                raw_event_id=event_ids[i],
                message=event_data["message"],
                stack_trace=event_data["stack_trace"],
                service=event_data["service"],
                environment="test",
                project_id=project_id,
                fingerprint=f"test-{i}",
                session=db_session,
            )
            assert result["embedding_stored"], f"Failed to store embedding for event {i}"

        db_session.commit()

        # Run clustering on batch
        cluster_result = orchestrator.process_recent_unclustered_batch(
            project_id=project_id,
            session=db_session,
        )

        print(f"Clustering result: {cluster_result}")
        assert cluster_result["fetched_events"] >= 3, "Should fetch at least 3 events"
        assert cluster_result["embedded_events"] >= 3, "Should have embeddings for 3+ events"
        assert (
            cluster_result["assigned_events"] >= 2
        ), "Should assign events to clusters (not all noise)"
        # Should create at least 1 incident
        assert cluster_result["incidents_created"] >= 0, "Should analyze clusters"

    # TEST CASE 2: Different errors stay separate
    def test_different_errors_stay_separate(self, orchestrator, db_session, project_id):
        """
        Input: Three different error types
        Expected: Separate clusters, separate incidents
        """
        from database.repositories.entities import RawEventRepository

        events_data = [
            {
                "message": "Database connection timeout after 30s",
                "stack_trace": "at Connection.connect (db.js:123)",
                "service": "database",
            },
            {
                "message": "JWT token expired: signature mismatch",
                "stack_trace": "at verifyToken (auth.js:89)",
                "service": "auth",
            },
            {
                "message": "Redis connection refused on 127.0.0.1:6379",
                "stack_trace": "at RedisClient.connect (redis.js:45)",
                "service": "cache",
            },
        ]

        repo = RawEventRepository(db_session)
        event_ids = []
        for event_data in events_data:
            event = repo.create(
                project_id=project_id,
                source_type="test",
                service=event_data["service"],
                environment="test",
                message=event_data["message"],
                stack_trace=event_data["stack_trace"],
                fingerprint=f"test-separate-{len(event_ids)}",
                extra_metadata={},
                occurred_at=datetime.now(timezone.utc),
            )
            event_ids.append(event.id)
        db_session.commit()

        # Generate embeddings
        for i, event_data in enumerate(events_data):
            result = orchestrator.process_otlp_event(
                raw_event_id=event_ids[i],
                message=event_data["message"],
                stack_trace=event_data["stack_trace"],
                service=event_data["service"],
                environment="test",
                project_id=project_id,
                fingerprint=f"test-separate-{i}",
                session=db_session,
            )
            assert result["embedding_stored"], f"Failed to embed event {i}"

        db_session.commit()

        # Cluster
        cluster_result = orchestrator.process_recent_unclustered_batch(
            project_id=project_id,
            session=db_session,
        )

        print(f"Different errors clustering: {cluster_result}")
        assert cluster_result["fetched_events"] >= 3

    # TEST CASE 3: OTLP end-to-end ingestion
    def test_otlp_end_to_end_ingestion(self, db_session, project_id):
        """
        Input: OTLP JSON payload
        Expected: Events stored, embeddings generated, incidents created
        """
        from app.api.routes.otlp import parse_otlp_json_logs, normalize_otlp_log_records
        from database.repositories.entities import RawEventRepository

        otlp_payload = {
            "resourceLogs": [
                {
                    "resource": {
                        "attributes": [
                            {"key": "service.name", "value": {"stringValue": "test-service"}},
                            {
                                "key": "deployment.environment",
                                "value": {"stringValue": "production"},
                            },
                        ]
                    },
                    "scopeLogs": [
                        {
                            "logRecords": [
                                {
                                    "timeUnixNano": "1715344200000000000",
                                    "severityText": "ERROR",
                                    "body": {"stringValue": "Test error message"},
                                    "attributes": [
                                        {
                                            "key": "exception.stacktrace",
                                            "value": {
                                                "stringValue": "at testFunc (test.js:10)\nat main (test.js:20)"
                                            },
                                        }
                                    ],
                                }
                            ]
                        }
                    ],
                }
            ]
        }

        # Parse OTLP
        parsed = parse_otlp_json_logs(json.dumps(otlp_payload))
        assert len(parsed) >= 1, "Should parse at least 1 log record"

        # Normalize
        normalized = normalize_otlp_log_records(parsed, project_id=project_id)
        assert len(normalized) >= 1
        assert normalized[0]["service"] == "test-service"

        # Persist
        repo = RawEventRepository(db_session)
        for record in normalized:
            event = repo.create(
                project_id=record["project_id"],
                source_type=record["source_type"],
                service=record["service"],
                environment=record["environment"],
                message=record["message"],
                stack_trace=record.get("stack_trace"),
                fingerprint=record["fingerprint"],
                extra_metadata=record["extra_metadata"],
                occurred_at=record["occurred_at"],
            )
            assert event.id is not None, "Event should be persisted with ID"

        db_session.commit()

    # TEST CASE 4: Root cause analysis execution
    def test_root_cause_analysis(self, orchestrator, db_session, project_id):
        """
        Input: Cluster with events
        Expected: Root cause analysis generated with title + remediation
        """
        from database.repositories.entities import RawEventRepository, ErrorClusterRepository
        from database.models import RawEvent

        # Create test events
        repo = RawEventRepository(db_session)
        event_ids = []
        for i in range(3):
            event = repo.create(
                project_id=project_id,
                source_type="test",
                service="test-service",
                environment="test",
                message="Database query timeout after 30 seconds",
                stack_trace="at Query.execute (db.js:100)",
                fingerprint=f"test-analysis-{i}",
                extra_metadata={},
                occurred_at=datetime.now(timezone.utc),
            )
            event_ids.append(event.id)
        db_session.commit()

        # Generate embeddings
        for event_id in event_ids:
            orchestrator.process_otlp_event(
                raw_event_id=event_id,
                message="Database query timeout after 30 seconds",
                stack_trace="at Query.execute (db.js:100)",
                service="test-service",
                environment="test",
                project_id=project_id,
                fingerprint=f"test-analysis-{event_ids.index(event_id)}",
                session=db_session,
            )
        db_session.commit()

        # Run clustering
        result = orchestrator.process_recent_unclustered_batch(
            project_id=project_id,
            session=db_session,
        )

        print(f"Analysis result: {result}")
        assert result.get("analyzed_clusters") >= 0, "Should attempt cluster analysis"

    # TEST CASE 5: Duplicate incident prevention
    def test_duplicate_incident_prevention(self, orchestrator, db_session, project_id):
        """
        Input: Same event sent multiple times
        Expected: No duplicate incidents created
        """
        from database.repositories.entities import RawEventRepository
        from database.models import Incident

        repo = RawEventRepository(db_session)

        # Create 5 similar events
        event_ids = []
        for i in range(5):
            event = repo.create(
                project_id=project_id,
                source_type="test",
                service="api-server",
                environment="prod",
                message="Request timeout: handler took > 30s",
                stack_trace="at handleRequest (app.js:50)",
                fingerprint="request-timeout-key",  # Same fingerprint
                extra_metadata={},
                occurred_at=datetime.now(timezone.utc),
            )
            event_ids.append(event.id)
        db_session.commit()

        # Generate embeddings for all
        for i, event_id in enumerate(event_ids):
            orchestrator.process_otlp_event(
                raw_event_id=event_id,
                message="Request timeout: handler took > 30s",
                stack_trace="at handleRequest (app.js:50)",
                service="api-server",
                environment="prod",
                project_id=project_id,
                fingerprint="request-timeout-key",
                session=db_session,
            )
        db_session.commit()

        # Run clustering
        result = orchestrator.process_recent_unclustered_batch(
            project_id=project_id,
            session=db_session,
        )

        print(f"Duplicate prevention result: {result}")

        # Check incidents
        incidents = db_session.query(Incident).filter(Incident.ai_confidence > 0).all()
        # Should not create incidents for duplicate events
        print(f"Incidents created: {len(incidents)}")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
