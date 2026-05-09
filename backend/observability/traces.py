from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence

from core.normalization import normalize_timestamp


def _to_datetime(value: Any) -> Optional[datetime]:
    timestamp = normalize_timestamp(value)
    if timestamp is not None:
        return timestamp
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value) / 1_000_000_000, tz=timezone.utc)
    return None


@dataclass
class TraceSpan:
    trace_id: str
    span_id: str
    parent_span_id: Optional[str]
    name: str
    service: str
    start_timestamp: datetime
    end_timestamp: datetime
    status: str = "ok"
    attributes: Dict[str, Any] = field(default_factory=dict)
    source_of_truth: str = "observability.traces"
    confidence_origin: str = "otel_ingestion"
    evidence_origin: List[str] = field(default_factory=list)
    persistence_rules: Dict[str, Any] = field(default_factory=lambda: {
        "retention": "indefinite",
        "mutability": "append-only",
        "rewrite_policy": "source-driven",
    })

    @property
    def duration_ms(self) -> float:
        return max(0.0, (self.end_timestamp - self.start_timestamp).total_seconds() * 1000.0)


class TraceIngestor:
    """Parse OTEL-style traces into a normalized operational model."""

    def ingest(self, payload: Dict[str, Any]) -> List[TraceSpan]:
        spans = payload.get("spans")
        if spans is None:
            spans = self._extract_otel_spans(payload)

        normalized: List[TraceSpan] = []
        for span in spans or []:
            normalized.append(self._normalize_span(span, payload))
        return normalized

    def build_propagation_chain(self, spans: Sequence[TraceSpan]) -> List[Dict[str, Any]]:
        ordered = sorted(spans, key=lambda span: span.start_timestamp)
        chain: List[Dict[str, Any]] = []
        for index, span in enumerate(ordered):
            chain.append({
                "phase": "request propagation" if index == 0 else "downstream span",
                "description": f"{span.name} on {span.service}",
                "timestamp": span.start_timestamp.isoformat(),
                "trace_id": span.trace_id,
                "span_id": span.span_id,
                "parent_span_id": span.parent_span_id,
                "duration_ms": span.duration_ms,
                "service": span.service,
                "source_of_truth": span.source_of_truth,
                "confidence_origin": span.confidence_origin,
                "evidence_origin": list(span.evidence_origin),
            })
        return chain

    def timeout_chains(self, spans: Sequence[TraceSpan], timeout_ms: float = 1000.0) -> List[Dict[str, Any]]:
        chains: List[Dict[str, Any]] = []
        ordered = sorted(spans, key=lambda span: span.start_timestamp)
        by_trace: Dict[str, List[TraceSpan]] = {}
        for span in ordered:
            by_trace.setdefault(span.trace_id, []).append(span)

        for trace_id, trace_spans in by_trace.items():
            for span in trace_spans:
                if span.duration_ms >= timeout_ms or str(span.status).lower() in {"error", "timeout", "deadline_exceeded"}:
                    chains.append({
                        "trace_id": trace_id,
                        "span_id": span.span_id,
                        "service": span.service,
                        "duration_ms": span.duration_ms,
                        "status": span.status,
                        "chain": self._ancestor_chain(span, trace_spans),
                    })
        return chains

    def detect_degradation(self, spans: Sequence[TraceSpan]) -> Optional[Dict[str, Any]]:
        if not spans:
            return None
        ordered = sorted(spans, key=lambda span: span.start_timestamp)
        durations = [span.duration_ms for span in ordered]
        if len(durations) < 2:
            return None
        latest = ordered[-1]
        baseline = sum(durations[:-1]) / max(1, len(durations) - 1)
        if latest.duration_ms > max(baseline * 1.5, sorted(durations)[int(len(durations) * 0.95) - 1 if len(durations) > 1 else 0]):
            return {
                "trace_id": latest.trace_id,
                "service": latest.service,
                "timestamp": latest.start_timestamp.isoformat(),
                "baseline_ms": baseline,
                "latest_ms": latest.duration_ms,
                "degradation": "latency",
            }
        return None

    def _normalize_span(self, span: Dict[str, Any], root_payload: Dict[str, Any]) -> TraceSpan:
        start = _to_datetime(span.get("start_time") or span.get("start_timestamp") or span.get("startTime") or span.get("timestamp")) or datetime.utcnow().replace(tzinfo=timezone.utc)
        end = _to_datetime(span.get("end_time") or span.get("end_timestamp") or span.get("endTime")) or (start + timedelta(milliseconds=float(span.get("duration_ms", span.get("duration", 0)) or 0)))
        service = span.get("service") or span.get("attributes", {}).get("service.name") or root_payload.get("service") or "unknown"
        return TraceSpan(
            trace_id=str(span.get("trace_id") or root_payload.get("trace_id") or root_payload.get("traceId") or "trace:unknown"),
            span_id=str(span.get("span_id") or span.get("spanId") or span.get("id") or f"span:{start.isoformat()}"),
            parent_span_id=span.get("parent_span_id") or span.get("parentSpanId") or span.get("parent_id"),
            name=str(span.get("name") or span.get("operation") or span.get("path") or "unknown"),
            service=str(service),
            start_timestamp=start,
            end_timestamp=end if end >= start else start,
            status=str(span.get("status") or span.get("status_code") or "ok"),
            attributes=dict(span.get("attributes") or span.get("tags") or {}),
            source_of_truth=str(span.get("source_of_truth", "observability.traces")),
            confidence_origin=str(span.get("confidence_origin", "otel_ingestion")),
            evidence_origin=[str(span.get("source", "otel"))],
        )

    def _extract_otel_spans(self, payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        spans: List[Dict[str, Any]] = []
        for resource_span in payload.get("resourceSpans", []):
            resource_attributes = resource_span.get("resource", {}).get("attributes", [])
            service_name = None
            for attribute in resource_attributes:
                if attribute.get("key") == "service.name":
                    service_name = attribute.get("value", {}).get("stringValue")
                    break
            for scope_span in resource_span.get("scopeSpans", []):
                for span in scope_span.get("spans", []):
                    attributes = {item.get("key"): next((value for value in item.get("value", {}).values() if value is not None), None) for item in span.get("attributes", [])}
                    spans.append({
                        "trace_id": span.get("traceId"),
                        "span_id": span.get("spanId"),
                        "parent_span_id": span.get("parentSpanId"),
                        "name": span.get("name"),
                        "service": service_name,
                        "start_time": span.get("startTimeUnixNano"),
                        "end_time": span.get("endTimeUnixNano"),
                        "status": span.get("status", {}).get("code", "ok"),
                        "attributes": attributes,
                    })
        return spans

    def _ancestor_chain(self, span: TraceSpan, trace_spans: Sequence[TraceSpan]) -> List[str]:
        index = {item.span_id: item for item in trace_spans}
        chain = [span.name]
        current = span
        visited = set()
        while current.parent_span_id and current.parent_span_id in index and current.parent_span_id not in visited:
            visited.add(current.parent_span_id)
            current = index[current.parent_span_id]
            chain.append(current.name)
        return list(reversed(chain))