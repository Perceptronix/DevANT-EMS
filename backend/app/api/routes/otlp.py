from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import tempfile
from pathlib import Path
from typing import Any
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request, BackgroundTasks
from opentelemetry.proto.collector.logs.v1 import logs_service_pb2
from config import get_config

try:
    from database.client import get_database_client
    from database.repositories.entities import RawEventRepository
    from database.repositories.entities import ProjectRepository
    from database.repositories.entities import ErrorClusterRepository
    from database.repositories.entities import IncidentRepository
    from core.root_cause_clusterer import RootCauseClusterer
    from memory.incident_graph import get_incident_graph
except Exception as import_error:  # pragma: no cover - optional for parser-only test environments
    print(f"[OTLP] Import error: {import_error}", flush=True)  # stderr for immediate visibility
    import traceback
    traceback.print_exc()
    get_database_client = None
    RawEventRepository = None
    ProjectRepository = None
    ErrorClusterRepository = None
    IncidentRepository = None
    RootCauseClusterer = None
    get_incident_graph = None

router = APIRouter(prefix="/api/v1/ingest", tags=["otlp"])

logger = logging.getLogger(__name__)


def _log_otlp_event(event: str, **fields: Any) -> None:
    payload = {"event": event, **fields}
    logger.info(json.dumps(payload, default=str, sort_keys=True))


def _extract_any_value(value: Any) -> Any:
    if isinstance(value, dict):
        if "stringValue" in value:
            return value["stringValue"]
        if "boolValue" in value:
            return value["boolValue"]
        if "intValue" in value:
            return value["intValue"]
        if "doubleValue" in value:
            return value["doubleValue"]
        if "arrayValue" in value:
            array_values = value.get("arrayValue", {}).get("values", [])
            return [_extract_any_value(item) for item in array_values]
        if "kvlistValue" in value:
            entries = value.get("kvlistValue", {}).get("values", [])
            return {
                entry.get("key"): _extract_any_value(entry.get("value"))
                for entry in entries
                if isinstance(entry, dict) and entry.get("key") is not None
            }
        if "bytesValue" in value:
            return value["bytesValue"]
    return value


def _extract_attributes(attributes: Any) -> dict[str, Any]:
    extracted: dict[str, Any] = {}
    if not isinstance(attributes, list):
        return extracted

    for attribute in attributes:
        if not isinstance(attribute, dict):
            continue
        key = attribute.get("key")
        if key is None:
            continue
        extracted[key] = _extract_any_value(attribute.get("value"))
    return extracted


def _decode_protobuf_attribute_value(value: Any) -> Any:
    if value is None:
        return None

    # The generated protobuf classes expose snake_case fields.
    active_field = None
    try:
        active_field = value.WhichOneof("value")
    except Exception:
        active_field = None

    if active_field == "string_value":
        return value.string_value
    if active_field == "bool_value":
        return value.bool_value
    if active_field == "int_value":
        return value.int_value
    if active_field == "double_value":
        return value.double_value
    if active_field == "bytes_value":
        return value.bytes_value
    if active_field == "array_value":
        return [_decode_protobuf_attribute_value(item) for item in value.array_value.values]
    if active_field == "kvlist_value":
        return {
            item.key: _decode_protobuf_attribute_value(item.value)
            for item in value.kvlist_value.values
            if item.key
        }

    if getattr(value, "string_value", None) not in (None, ""):
        return value.string_value
    if getattr(value, "int_value", None) is not None:
        return value.int_value
    if getattr(value, "double_value", None) is not None:
        return value.double_value
    if getattr(value, "bool_value", None) is not None:
        return value.bool_value
    if getattr(value, "bytes_value", None) not in (None, b""):
        return value.bytes_value
    return None


def _extract_protobuf_attributes(attributes: Any) -> dict[str, Any]:
    extracted: dict[str, Any] = {}
    if not attributes:
        return extracted

    for attribute in attributes:
        key = getattr(attribute, "key", None)
        if not key:
            continue
        extracted[key] = _decode_protobuf_attribute_value(getattr(attribute, "value", None))
    return extracted


def parse_otlp_protobuf_logs(payload: bytes) -> list[dict[str, Any]]:
    """Extract normalized log records from an OTLP protobuf payload."""
    request = logs_service_pb2.ExportLogsServiceRequest()
    request.ParseFromString(payload)

    records: list[dict[str, Any]] = []

    for resource_log in request.resource_logs:
        resource_attributes = _extract_protobuf_attributes(getattr(resource_log.resource, "attributes", []))

        for scope_log in resource_log.scope_logs:
            for log_record in scope_log.log_records:
                records.append(
                    {
                        "timestamp": log_record.time_unix_nano or None,
                        "severity": log_record.severity_text or log_record.severity_number,
                        "body": _decode_protobuf_attribute_value(log_record.body),
                        "attributes": _extract_protobuf_attributes(log_record.attributes),
                        "resource_attributes": resource_attributes,
                    }
                )

    return records


def parse_otlp_json_logs(payload: bytes | str | dict[str, Any]) -> list[dict[str, Any]]:
    """Extract normalized log records from an OTLP JSON payload."""
    if isinstance(payload, bytes):
        payload = payload.decode("utf-8")

    if isinstance(payload, str):
        payload = json.loads(payload)

    records: list[dict[str, Any]] = []
    resource_logs = payload.get("resourceLogs", []) if isinstance(payload, dict) else []

    for resource_log in resource_logs:
        resource_attributes = _extract_attributes(
            resource_log.get("resource", {}).get("attributes", []) if isinstance(resource_log, dict) else []
        )
        scope_logs = resource_log.get("scopeLogs", []) if isinstance(resource_log, dict) else []

        for scope_log in scope_logs:
            log_records = scope_log.get("logRecords", []) if isinstance(scope_log, dict) else []

            for log_record in log_records:
                if not isinstance(log_record, dict):
                    continue

                records.append(
                    {
                        "timestamp": log_record.get("timeUnixNano"),
                        "severity": log_record.get("severityText") or log_record.get("severityNumber"),
                        "body": _extract_any_value(log_record.get("body")),
                        "attributes": _extract_attributes(log_record.get("attributes", [])),
                        "resource_attributes": resource_attributes,
                    }
                )

    return records


def normalize_otlp_log_record(record: dict[str, Any], project_id: str, fingerprint: str | None = None) -> dict[str, Any]:
    """Convert a parsed OTLP log record into the platform's raw event schema."""
    resource_attributes = record.get("resource_attributes") or {}
    attributes = record.get("attributes") or {}

    service = (
        resource_attributes.get("service.name")
        or attributes.get("service.name")
        or attributes.get("service")
        or "unknown"
    )
    environment = (
        resource_attributes.get("deployment.environment")
        or attributes.get("deployment.environment")
        or attributes.get("environment")
        or "production"
    )

    body = record.get("body")
    if isinstance(body, (dict, list)):
        message = json.dumps(body, default=str)
    elif body is None:
        message = ""
    else:
        message = str(body)

    stack_trace = (
        attributes.get("exception.stacktrace")
        or attributes.get("stack_trace")
        or attributes.get("stackTrace")
    )

    inferred_fingerprint = fingerprint or _build_otlp_fingerprint(service, message, stack_trace)

    occurred_at = _coerce_occurred_at(record.get("timestamp"))

    extra_metadata = {
        "attributes": {
            key: value
            for key, value in attributes.items()
            if key not in {"service", "service.name", "environment", "deployment.environment"}
        },
        "resource_attributes": {
            key: value
            for key, value in resource_attributes.items()
            if key not in {"service.name", "deployment.environment"}
        },
    }

    return {
        "project_id": project_id,
        "source_type": "opentelemetry",
        "service": service,
        "environment": environment,
        "message": message,
        "stack_trace": stack_trace,
        "fingerprint": inferred_fingerprint,
        "occurred_at": occurred_at,
        "extra_metadata": extra_metadata,
    }


def normalize_otlp_log_records(records: list[dict[str, Any]], project_id: str) -> list[dict[str, Any]]:
    """Normalize a batch of parsed OTLP records into raw event rows."""
    return [normalize_otlp_log_record(record, project_id=project_id) for record in records]


def _coerce_occurred_at(timestamp: Any) -> datetime:
    """Convert an OTLP timestamp into a timezone-aware UTC datetime.
    
    OTLP timestamps are typically in nanoseconds since Unix epoch.
    Fallback to current ingestion time if timestamp is missing/invalid/stale.
    """
    now_utc = datetime.now(timezone.utc)
    
    if timestamp in (None, ""):
        logger.debug("OTLP timestamp: missing, using current UTC: %s", now_utc.isoformat())
        return now_utc

    try:
        # Parse timestamp (handle string or numeric formats)
        if isinstance(timestamp, str):
            timestamp = int(timestamp)
        
        if isinstance(timestamp, (int, float)):
            # Convert from nanoseconds to seconds
            seconds = float(timestamp) / 1_000_000_000
            occurred_at = datetime.fromtimestamp(seconds, tz=timezone.utc)
            
            # Check for unreasonable drift (more than 24 hours in past or 1 hour in future)
            drift = (now_utc - occurred_at).total_seconds()
            MAX_PAST_DRIFT = 86400  # 24 hours
            MAX_FUTURE_DRIFT = 3600  # 1 hour
            
            if drift > MAX_PAST_DRIFT or drift < -MAX_FUTURE_DRIFT:
                logger.warning(
                    "OTLP timestamp drift: parsed=%s drift_seconds=%d max_past=%d max_future=%d. Using current UTC.",
                    occurred_at.isoformat(),
                    drift,
                    MAX_PAST_DRIFT,
                    -MAX_FUTURE_DRIFT,
                )
                return now_utc
            
            logger.debug(
                "OTLP timestamp: parsed=%s drift_seconds=%d status=OK",
                occurred_at.isoformat(),
                drift,
            )
            return occurred_at
            
    except Exception as exc:
        logger.warning(
            "OTLP timestamp parse error: timestamp=%s error=%s. Using current UTC.",
            timestamp,
            exc,
        )
        pass

    return now_utc


def _build_otlp_fingerprint(service: str, message: str, stack_trace: str | None) -> str:
    """Build a deterministic SHA-256 fingerprint for an OTLP log record."""
    first_stack_line = ""
    if stack_trace:
        first_stack_line = stack_trace.splitlines()[0].strip()

    material = f"{service}|{message}|{first_stack_line}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def persist_normalized_otlp_records(records: list[dict[str, Any]], project_id: str) -> int:
    """Persist normalized OTLP raw events using the repository layer."""
    if get_database_client is None or RawEventRepository is None:
        raise RuntimeError("Database persistence dependencies are unavailable")

    if not project_id or not records:
        return 0

    client = get_database_client()
    try:
        session = client.get_session()
    except Exception as exc:
        logger.error("Failed to open database session for OTLP ingest: %s", exc, exc_info=True)
        raise

    persisted = 0
    try:
        raw_event_repo = RawEventRepository(session)
        now_utc = datetime.now(timezone.utc)
        
        for index, record in enumerate(records):
            try:
                occurred_at = record["occurred_at"]
                drift = (now_utc - occurred_at).total_seconds()
                
                raw_event_repo.create(
                    project_id=record["project_id"],
                    source_type=record["source_type"],
                    service=record["service"],
                    environment=record["environment"],
                    message=record["message"],
                    stack_trace=record.get("stack_trace"),
                    fingerprint=record["fingerprint"],
                    extra_metadata=record["extra_metadata"],
                    occurred_at=occurred_at,
                )
                
                logger.info(
                    "OTLP persisted: index=%d service=%s fingerprint=%s occurred_at=%s drift_sec=%d",
                    index,
                    record.get("service"),
                    record.get("fingerprint")[:8],
                    occurred_at.isoformat(),
                    int(drift),
                )
                persisted += 1
            except Exception as exc:
                logger.error(
                    "Failed to persist OTLP raw event index=%d project_id=%s service=%s fingerprint=%s error=%s",
                    index,
                    record.get("project_id"),
                    record.get("service"),
                    record.get("fingerprint"),
                    exc,
                    exc_info=True,
                )
        
        # Validate: ensure persisted events fall within clustering lookback (5 minutes)
        if persisted > 0:
            from datetime import timedelta
            lookback_cutoff = datetime.now(timezone.utc) - timedelta(minutes=5)
            recent_count = session.query(RawEvent).filter(
                RawEvent.project_id == project_id,
                RawEvent.occurred_at >= lookback_cutoff,
            ).count()
            logger.info(
                "OTLP persist validation: persisted=%d recent_events(lookback=5m)=%d cutoff=%s",
                persisted,
                recent_count,
                lookback_cutoff.isoformat(),
            )
        
        return persisted
    finally:
        session.close()


def _sanitize_for_json(obj: Any) -> Any:
    """Remove datetime and other non-JSON-serializable objects from nested structures."""
    if obj is None:
        return None
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {k: _sanitize_for_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_sanitize_for_json(item) for item in obj]
    if isinstance(obj, (str, int, float, bool)):
        return obj
    # For other types, try converting to string
    return str(obj)


def run_otlp_clustering_pipeline(records: list[dict[str, Any]], project_id: str) -> dict[str, int]:
    """Run the existing clustering and incident analysis flow for OTLP events."""
    if get_database_client is None or RootCauseClusterer is None or ErrorClusterRepository is None or IncidentRepository is None:
        return {"cluster_count": 0, "incident_count": 0, "incident_graph_count": 0}

    if not project_id or not records:
        return {"cluster_count": 0, "incident_count": 0, "incident_graph_count": 0}

    cluster_inputs = []
    for record in records:
        cluster_inputs.append(
            {
                "message": record.get("message", ""),
                "service": record.get("service", "unknown"),
                "stack_trace": record.get("stack_trace") or "",
                "timestamp": record.get("occurred_at"),
                "signature": record.get("fingerprint") or record.get("message") or record.get("service") or "otlp-event",
                "severity": record.get("environment", "production"),
                "source": record.get("source_type", "opentelemetry"),
                "confidence": 0.5,
                "error_count": 1,
                "affected_orgs": [],
            }
        )

    clusterer = RootCauseClusterer()
    clusters = clusterer.cluster_errors(cluster_inputs)

    client = get_database_client()
    session = client.get_session()
    incident_graph = get_incident_graph() if get_incident_graph is not None else None
    repo_name = getattr(get_config().github, "repo", project_id)

    counts = {"cluster_count": 0, "incident_count": 0, "incident_graph_count": 0}
    try:
        cluster_repo = ErrorClusterRepository(session)
        incident_repo = IncidentRepository(session)

        for cluster in clusters:
            cluster_record = cluster_repo.create(
                project_id=project_id,
                title=(cluster.signature or cluster.root_cause or "OTLP cluster")[:512],
                representative_event_id=None,
                event_count=cluster.error_count,
                severity=cluster.severity,
                status="NEW",
                confidence=cluster.confidence,
            )
            counts["cluster_count"] += 1

            incident_repo.create(
                cluster_id=cluster_record.id,
                title=(cluster.root_cause or cluster.signature or "OTLP incident")[:512],
                summary=cluster.root_cause or cluster.signature,
                root_cause=cluster.root_cause or cluster.signature,
                recommendations=_sanitize_for_json({"evidence": cluster.representative_evidence[:5]}),
                ai_confidence=cluster.confidence,
            )
            counts["incident_count"] += 1

            if incident_graph is not None:
                topo_hash = hashlib.md5(
                    ",".join(sorted(cluster.affected_services or [cluster.signature or "unknown"])).encode("utf-8")
                ).hexdigest()[:8]
                incident_graph.add_incident(
                    incident_id=cluster.cluster_id,
                    timestamp=cluster.last_seen,
                    repo=repo_name,
                    dominant_service=(cluster.affected_services[0] if cluster.affected_services else "unknown"),
                    blast_radius=max(1, cluster.error_count),
                    operational_confidence=cluster.confidence,
                    regression_risk=cluster.regression_probability,
                    topology_hash=topo_hash,
                )
                counts["incident_graph_count"] += 1

        session.commit()
        return counts
    finally:
        session.close()


def _run_embedding_clustering_background(normalized_records: list[dict[str, Any]], project_id: str) -> None:
    """Background task: generate embeddings and trigger clustering for OTLP events.

    Runs Phase 3→4 orchestrator:
    1. Generate embeddings for each raw event
    2. Store embeddings in pgvector
    3. Trigger HDBSCAN clustering
    4. Analyze clusters
    5. Create incidents
    """
    try:
        from orchestration.otlp_clustering_orchestrator import get_otlp_clustering_orchestrator
        from database.models import RawEvent
        from database.client import get_database_client

        orchestrator = get_otlp_clustering_orchestrator()
        db_client = get_database_client()
        session = db_client.get_session()

        try:
            # Step 1: Process each event to generate embeddings
            for record in normalized_records:
                try:
                    # Find persisted raw event by fingerprint
                    raw_event = (
                        session.query(RawEvent)
                        .filter(RawEvent.fingerprint == record["fingerprint"])
                        .filter(RawEvent.project_id == project_id)
                        .order_by(RawEvent.occurred_at.desc())
                        .first()
                    )

                    if not raw_event:
                        logger.warning(
                            "Raw event not found for fingerprint %s",
                            record["fingerprint"],
                        )
                        continue

                    # Generate embedding and store
                    result = orchestrator.process_otlp_event(
                        raw_event_id=raw_event.id,
                        message=record.get("message", ""),
                        stack_trace=record.get("stack_trace"),
                        service=record.get("service", "unknown"),
                        environment=record.get("environment", "production"),
                        project_id=project_id,
                        fingerprint=record["fingerprint"],
                        session=session,
                    )

                    if result.get("error"):
                        logger.warning(
                            "Failed to process event %s: %s",
                            raw_event.id,
                            result["error"],
                        )
                except Exception as exc:
                    logger.error(
                        "Error processing OTLP event %s: %s",
                        record.get("fingerprint"),
                        exc,
                        exc_info=True,
                    )

            session.commit()

            # Step 2: Trigger clustering pipeline on batch
            _log_otlp_event(
                "otlp.embedding_clustering.started",
                project_id=project_id,
                event_count=len(normalized_records),
            )

            cluster_counts = orchestrator.process_recent_unclustered_batch(
                project_id=project_id,
                session=session,
            )

            _log_otlp_event(
                "otlp.embedding_clustering.completed",
                project_id=project_id,
                fetched_events=cluster_counts.get("fetched_events", 0),
                embedded_events=cluster_counts.get("embedded_events", 0),
                created_clusters=cluster_counts.get("created_clusters", 0),
                updated_clusters=cluster_counts.get("updated_clusters", 0),
                assigned_events=cluster_counts.get("assigned_events", 0),
                analyzed_clusters=cluster_counts.get("analyzed_clusters", 0),
                incidents_created=cluster_counts.get("incidents_created", 0),
            )

        finally:
            session.close()

    except Exception as exc:
        _log_otlp_event(
            "otlp.embedding_clustering.failed",
            project_id=project_id,
            error=str(exc),
        )
        logger.error(
            "Background embedding/clustering failed for project %s: %s",
            project_id,
            exc,
            exc_info=True,
        )


def _run_pipeline_background(records: list[dict[str, Any]], project_id: str) -> None:
    """Background wrapper for running the clustering pipeline with robust logging."""
    try:
        counts = run_otlp_clustering_pipeline(records, project_id)
        _log_otlp_event(
            "otlp.ingest.analysis_completed",
            project_id=project_id,
            cluster_count=counts.get("cluster_count", 0),
            incident_count=counts.get("incident_count", 0),
            incident_graph_count=counts.get("incident_graph_count", 0),
        )
    except Exception as exc:
        _log_otlp_event(
            "otlp.ingest.analysis_failed",
            project_id=project_id,
            error=str(exc),
        )


def resolve_otlp_project_id(project_id: str | None) -> str | None:
    """Resolve a project id from the request or configured GitHub repository."""
    if project_id:
        return project_id

    if get_database_client is None or ProjectRepository is None:
        _log_otlp_event(
            "otlp.resolve_project_id.dependencies_unavailable",
            get_database_client_available=get_database_client is not None,
            project_repo_available=ProjectRepository is not None,
        )
        return None

    config = get_config()
    github_repo = getattr(config.github, "repo", None)
    if not github_repo:
        _log_otlp_event("otlp.resolve_project_id.no_github_repo_configured")
        return None

    client = get_database_client()
    session = client.get_session()
    try:
        project_repo = ProjectRepository(session)
        project = project_repo.get_by_github_repo(github_repo)
        if project:
            return str(project.id)

        project_name = github_repo.split("/")[-1] if github_repo else github_repo
        project = project_repo.create(name=project_name, github_repo=github_repo)
        return str(project.id)
    finally:
        session.close()


def _detect_payload_format(payload: bytes, content_type: str | None) -> str:
    if content_type:
        lowered = content_type.lower()
        if "json" in lowered:
            return "json"
        if "protobuf" in lowered or "proto" in lowered:
            return "protobuf"

    stripped = payload.lstrip()
    if stripped.startswith(b"{") or stripped.startswith(b"["):
        try:
            json.loads(payload.decode("utf-8"))
            return "json"
        except Exception:
            pass

    return "protobuf"


@router.post("/otlp")
async def ingest_otlp(request: Request, background_tasks: BackgroundTasks):
    payload = await request.body()
    if not payload:
        raise HTTPException(status_code=400, detail="Empty OTLP payload")

    payload_format = _detect_payload_format(payload, request.headers.get("content-type"))
    _log_otlp_event(
        "otlp.ingest.received",
        payload_size=len(payload),
        content_type=request.headers.get("content-type"),
        payload_format=payload_format,
    )

    try:
        if payload_format == "json":
            parsed_records = parse_otlp_json_logs(payload)
        elif payload_format == "protobuf":
            parsed_records = parse_otlp_protobuf_logs(payload)
        else:
            raise HTTPException(status_code=400, detail="Unsupported OTLP payload format")
    except HTTPException:
        raise
    except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as exc:
        _log_otlp_event(
            "otlp.ingest.invalid_payload",
            payload_size=len(payload),
            content_type=request.headers.get("content-type"),
            payload_format=payload_format,
            error=str(exc),
        )
        raise HTTPException(status_code=400, detail="Invalid OTLP payload") from exc
    except Exception as exc:
        _log_otlp_event(
            "otlp.ingest.invalid_payload",
            payload_size=len(payload),
            content_type=request.headers.get("content-type"),
            payload_format=payload_format,
            error=str(exc),
        )
        raise HTTPException(status_code=400, detail="Invalid OTLP payload") from exc

    temp_dir = Path(tempfile.gettempdir()) / "devant-otlp"
    temp_dir.mkdir(parents=True, exist_ok=True)

    suffix = ".json" if payload_format == "json" else ".pb"
    with tempfile.NamedTemporaryFile(
        mode="wb",
        delete=False,
        suffix=suffix,
        prefix="otlp-",
        dir=temp_dir,
    ) as temp_file:
        temp_file.write(payload)
        temp_path = Path(temp_file.name)

    _log_otlp_event(
        "otlp.ingest.persisted_raw_payload",
        payload_size=len(payload),
        payload_format=payload_format,
        temp_path=str(temp_path),
    )

    if parsed_records:
        parsed_path = temp_path.with_suffix(".records.json")
        parsed_path.write_text(json.dumps(parsed_records, indent=2, default=str), encoding="utf-8")
        _log_otlp_event(
            "otlp.ingest.parsed",
            records_received=len(parsed_records),
            parsed_path=str(parsed_path),
            payload_format=payload_format,
        )

    if parsed_records and (get_database_client is None or RawEventRepository is None or ProjectRepository is None):
        _log_otlp_event(
            "otlp.ingest.dependencies_unavailable",
            get_database_client_available=get_database_client is not None,
            raw_event_repository_available=RawEventRepository is not None,
            project_repository_available=ProjectRepository is not None,
        )
        raise HTTPException(status_code=503, detail="OTLP persistence dependencies unavailable")

    resolved_project_id = resolve_otlp_project_id(None)
    normalized_records: list[dict[str, Any]] = []
    persisted_count = 0
    pipeline_triggered = False
    analysis_counts = {"cluster_count": 0, "incident_count": 0, "incident_graph_count": 0}
    
    if resolved_project_id is None:
        _log_otlp_event(
            "otlp.ingest.skipped_persistence",
            reason="no_project_id_resolved",
            records_received=len(parsed_records),
        )
        if parsed_records:
            raise HTTPException(status_code=503, detail="No OTLP project context available")
    elif not parsed_records:
        _log_otlp_event(
            "otlp.ingest.skipped_persistence",
            reason="no_parsed_records",
            project_id=resolved_project_id,
        )
    
    if resolved_project_id and parsed_records:
        try:
            normalized_records = normalize_otlp_log_records(parsed_records, project_id=resolved_project_id)
            normalized_path = temp_path.with_suffix(".raw-events.json")
            normalized_path.write_text(json.dumps(normalized_records, indent=2, default=str), encoding="utf-8")
            _log_otlp_event(
                "otlp.ingest.normalized",
                records_saved=len(normalized_records),
                normalized_path=str(normalized_path),
                project_id=resolved_project_id,
            )
            persisted_count = persist_normalized_otlp_records(normalized_records, project_id=resolved_project_id)
        except Exception as exc:
            _log_otlp_event(
                "otlp.ingest.processing_failed",
                stage="persist_or_normalize",
                project_id=resolved_project_id,
                error=str(exc),
            )
            raise HTTPException(status_code=500, detail="Failed to process OTLP payload") from exc

        if persisted_count > 0:
            # Schedule Phase 3→4 orchestrator in background: embeddings + clustering + analysis.
            # Keeps ingest fast and resilient to downstream failures.
            background_tasks.add_task(_run_embedding_clustering_background, normalized_records, resolved_project_id)
            pipeline_triggered = True

    pipeline_triggered = pipeline_triggered and persisted_count > 0

    _log_otlp_event(
        "otlp.ingest.completed",
        payload_format=payload_format,
        payload_size=len(payload),
        records_received=len(parsed_records),
        records_saved=persisted_count,
        pipeline_triggered=pipeline_triggered,
        cluster_count=analysis_counts["cluster_count"],
        incident_count=analysis_counts["incident_count"],
        incident_graph_count=analysis_counts["incident_graph_count"],
        temp_path=str(temp_path),
    )

    return {
        "success": True,
        "records_received": len(parsed_records),
        "records_saved": persisted_count,
        "pipeline_triggered": pipeline_triggered,
    }