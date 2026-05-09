"""
OpenTelemetry trace ingestion for live operational telemetry grounding.

Handles:
- Distributed spans + parent-child relationships
- Timeout chains and retry propagation
- Cross-service latency correlation
- Incomplete/broken traces (partial telemetry OK)
- Malformed/missing span fields
- Trace reconstruction from fragments
- Graceful degradation under sparse evidence
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Any, Set
from datetime import datetime, timezone, timedelta
from enum import Enum
import logging
import uuid
import asyncio
try:
    import aiohttp
    from aiohttp import web
except Exception:
    aiohttp = None
    web = None

logger = logging.getLogger(__name__)


class SpanKind(Enum):
    """OpenTelemetry span types."""
    INTERNAL = "INTERNAL"
    SERVER = "SERVER"
    CLIENT = "CLIENT"
    PRODUCER = "PRODUCER"
    CONSUMER = "CONSUMER"


class SpanStatus(Enum):
    """Span execution status."""
    UNSET = "UNSET"
    OK = "OK"
    ERROR = "ERROR"


@dataclass
class SpanEvent:
    """Event within span."""
    name: str
    timestamp: datetime
    attributes: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Span:
    """
    Single distributed trace span.
    
    Handles missing/malformed fields gracefully.
    """
    trace_id: str
    span_id: str
    parent_span_id: Optional[str] = None
    
    service_name: str = "unknown"
    operation_name: str = "operation"
    
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    
    kind: SpanKind = SpanKind.INTERNAL
    status: SpanStatus = SpanStatus.UNSET
    
    # Telemetry data
    attributes: Dict[str, Any] = field(default_factory=dict)
    events: List[SpanEvent] = field(default_factory=list)
    links: List[Tuple[str, str]] = field(default_factory=list)  # (trace_id, span_id)
    
    # Retry/error context
    retry_count: int = 0
    error_message: Optional[str] = None
    
    # Ingestion metadata
    ingestion_timestamp: Optional[datetime] = None
    is_partial: bool = False  # Missing critical fields
    
    def __post_init__(self):
        # Normalize timestamps to UTC
        for ts_attr in ["start_time", "end_time", "ingestion_timestamp"]:
            val = getattr(self, ts_attr)
            if val is not None and val.tzinfo is None:
                setattr(self, ts_attr, val.replace(tzinfo=timezone.utc))
        
        if self.ingestion_timestamp is None:
            self.ingestion_timestamp = datetime.now(timezone.utc)
    
    def duration_ms(self) -> Optional[float]:
        """Span duration in milliseconds."""
        if not self.start_time or not self.end_time:
            return None
        return (self.end_time - self.start_time).total_seconds() * 1000.0
    
    def is_timeout(self, timeout_threshold_ms: float = 30000.0) -> bool:
        """Check if span timed out."""
        dur = self.duration_ms()
        return dur is not None and dur > timeout_threshold_ms
    
    def is_error_span(self) -> bool:
        """Span indicates error."""
        return (
            self.status == SpanStatus.ERROR
            or self.error_message is not None
            or any(
                "error" in str(e.name).lower() or "exception" in str(e.name).lower()
                for e in self.events
            )
        )
    
    def get_downstream_service(self) -> Optional[str]:
        """Extract target service for CLIENT spans."""
        if self.kind != SpanKind.CLIENT:
            return None
        return self.attributes.get("peer.service") or self.attributes.get("rpc.service")
    
    def get_retry_chain_depth(self) -> int:
        """Estimate retry depth from span attributes."""
        # Check explicit retry_count
        if self.retry_count > 0:
            return self.retry_count
        # Check attributes
        return int(self.attributes.get("retry.count", 0))


@dataclass
class Trace:
    """
    Complete or partial distributed trace.
    
    Can be incomplete (missing spans, partial chains).
    """
    trace_id: str
    spans: Dict[str, Span] = field(default_factory=dict)  # span_id -> Span
    root_service: Optional[str] = None
    
    # Reconstruction state
    is_complete: bool = False
    is_broken: bool = False  # Missing spans in chain
    completeness_pct: float = 0.0
    
    # Timing
    earliest_span_time: Optional[datetime] = None
    latest_span_time: Optional[datetime] = None
    
    def add_span(self, span: Span) -> None:
        """Add span to trace."""
        self.spans[span.span_id] = span
        
        # Update root service
        if span.parent_span_id is None and not self.root_service:
            self.root_service = span.service_name
        
        # Update time bounds
        if span.start_time:
            if self.earliest_span_time is None or span.start_time < self.earliest_span_time:
                self.earliest_span_time = span.start_time
        if span.end_time:
            if self.latest_span_time is None or span.end_time > self.latest_span_time:
                self.latest_span_time = span.end_time
    
    def duration_ms(self) -> Optional[float]:
        """Total trace duration."""
        if not self.earliest_span_time or not self.latest_span_time:
            return None
        return (self.latest_span_time - self.earliest_span_time).total_seconds() * 1000.0
    
    def critical_path_ms(self) -> float:
        """
        Longest end-to-end path through trace.
        
        Approximation: sum of max latency chain from root.
        """
        if not self.spans:
            return 0.0
        
        # Find root span(s)
        roots = [s for s in self.spans.values() if s.parent_span_id is None]
        if not roots:
            return 0.0
        
        # BFS to find longest path
        max_path = 0.0
        for root in roots:
            max_path = max(max_path, self._longest_path_from(root))
        
        return max_path
    
    def _longest_path_from(self, span: Span) -> float:
        """Longest latency chain from span."""
        dur = span.duration_ms() or 0.0
        
        # Find children
        children = [s for s in self.spans.values() if s.parent_span_id == span.span_id]
        if not children:
            return dur
        
        # Recursively longest child path
        child_max = max((self._longest_path_from(c) for c in children), default=0.0)
        return dur + child_max
    
    def get_services(self) -> Set[str]:
        """All services in trace."""
        return {s.service_name for s in self.spans.values() if s.service_name}
    
    def error_spans(self) -> List[Span]:
        """Spans with errors."""
        return [s for s in self.spans.values() if s.is_error_span()]
    
    def timeout_spans(self, threshold_ms: float = 30000.0) -> List[Span]:
        """Spans exceeding timeout threshold."""
        return [s for s in self.spans.values() if s.is_timeout(threshold_ms)]
    
    def retry_chains(self) -> List[List[Span]]:
        """
        Identify retry chains (repeated operations).
        
        Returns list of chains where each chain is list of retried spans.
        """
        chains = []
        operation_groups: Dict[str, List[Span]] = {}
        
        # Group by operation
        for span in self.spans.values():
            op_key = f"{span.service_name}:{span.operation_name}"
            if op_key not in operation_groups:
                operation_groups[op_key] = []
            operation_groups[op_key].append(span)
        
        # Identify retries (same operation, sequential execution)
        for op_key, spans_list in operation_groups.items():
            if len(spans_list) <= 1:
                continue
            
            # Sort by time
            sorted_spans = sorted(spans_list, key=lambda s: s.start_time or datetime.min)
            
            # Check for retry pattern (errors followed by success)
            chain = []
            for span in sorted_spans:
                if span.is_error_span():
                    chain.append(span)
            
            if len(chain) >= 2:
                chains.append(chain)
        
        return chains
    
    def propagation_path(self) -> List[Tuple[str, str]]:
        """
        Service propagation path: [(service_from, service_to), ...].
        
        Trace dependencies from CLIENT spans.
        """
        path = []
        for span in self.spans.values():
            if span.kind == SpanKind.CLIENT:
                downstream = span.get_downstream_service()
                if downstream:
                    path.append((span.service_name, downstream))
        
        return path
    
    def check_completeness(self) -> float:
        """
        Estimate trace completeness (0.0 to 1.0).
        
        Based on:
        - Root span presence (0.3)
        - Span chain continuity (0.4)
        - No error/timeout gaps (0.3)
        """
        score = 0.0
        
        # Root span (0.3)
        roots = [s for s in self.spans.values() if s.parent_span_id is None]
        if roots:
            score += 0.3
        
        # Continuity (0.4): check for orphan spans (no parent)
        orphans = 0
        for span in self.spans.values():
            if span.parent_span_id and span.parent_span_id not in self.spans:
                orphans += 1
        
        if orphans == 0:
            score += 0.4
        else:
            # Partial credit
            continuity = max(0.0, 1.0 - (orphans / len(self.spans)))
            score += 0.4 * continuity
        
        # No critical gaps (0.3): check for timeout/error orphans
        error_orphans = sum(
            1 for s in self.spans.values()
            if s.parent_span_id and s.parent_span_id not in self.spans and s.is_error_span()
        )
        
        if error_orphans == 0:
            score += 0.3
        
        self.completeness_pct = score * 100.0
        self.is_complete = score >= 0.95
        self.is_broken = orphans > 0
        
        return score


class OtelIngestor:
    """
    Ingest OpenTelemetry traces for live telemetry grounding.
    
    Capabilities:
    - Partial trace reconstruction
    - Broken chain handling
    - Deduplication
    - Lazy span arrival
    """
    
    def __init__(self, max_traces: int = 10000, max_spans_per_trace: int = 500):
        self.max_traces = max_traces
        self.max_spans_per_trace = max_spans_per_trace
        
        # Trace storage: trace_id -> Trace
        self.traces: Dict[str, Trace] = {}
        
        # Orphan spans awaiting parent: (trace_id, parent_span_id) -> [Spans]
        self.orphans: Dict[Tuple[str, str], List[Span]] = {}
        
        # Deduplication
        self.seen_spans: Set[Tuple[str, str]] = set()  # (trace_id, span_id)
        
        # Statistics
        self.stats = {
            "total_spans_ingested": 0,
            "total_spans_deduplicated": 0,
            "total_spans_failed": 0,
            "total_traces_closed": 0,
            "total_orphans_resolved": 0,
        }
        # Async buffer
        self.async_queue: Optional[asyncio.Queue] = None
        self._http_server: Optional[asyncio.Task] = None
    
    def ingest_span(self, trace_id: str, span: Span) -> bool:
        """
        Ingest single span.
        
        Handles out-of-order arrival, orphans, late parents.
        Returns True if ingested, False if duplicate.
        """
        # Deduplication
        dedup_key = (trace_id, span.span_id)
        if dedup_key in self.seen_spans:
            self.stats["total_spans_deduplicated"] += 1
            return False
        
        self.seen_spans.add(dedup_key)
        
        try:
            # Get or create trace
            if trace_id not in self.traces:
                if len(self.traces) >= self.max_traces:
                    # Evict oldest trace
                    oldest_id = min(
                        self.traces.keys(),
                        key=lambda tid: self.traces[tid].earliest_span_time or datetime.min
                    )
                    del self.traces[oldest_id]
                
                self.traces[trace_id] = Trace(trace_id=trace_id)
            
            trace = self.traces[trace_id]
            
            # Check capacity
            if len(trace.spans) >= self.max_spans_per_trace:
                logger.warning(f"Trace {trace_id} exceeded max spans")
                self.stats["total_spans_failed"] += 1
                return False
            
            # Add to trace
            trace.add_span(span)
            self.stats["total_spans_ingested"] += 1
            
            # Try to resolve orphans
            orphan_key = (trace_id, span.span_id)
            if orphan_key in self.orphans:
                for orphan in self.orphans[orphan_key]:
                    trace.add_span(orphan)
                    self.stats["total_orphans_resolved"] += 1
                del self.orphans[orphan_key]
            
            # Check if orphan itself
            if span.parent_span_id and span.parent_span_id not in trace.spans:
                orphan_key = (trace_id, span.parent_span_id)
                if orphan_key not in self.orphans:
                    self.orphans[orphan_key] = []
                self.orphans[orphan_key].append(span)
            
            return True
            
        except Exception as e:
            self.stats["total_spans_failed"] += 1
            logger.error(f"Failed to ingest span: {e}")
            return False
    
    def ingest_batch(self, batch: List[Dict[str, Any]]) -> Dict[str, int]:
        """Ingest batch of spans."""
        result = {
            "ingested": 0,
            "deduplicated": 0,
            "failed": 0,
        }
        
        for span_dict in batch:
            try:
                trace_id = span_dict.get("trace_id", str(uuid.uuid4()))
                span_id = span_dict.get("span_id", str(uuid.uuid4()))
                parent_span_id = span_dict.get("parent_span_id")
                
                service_name = span_dict.get("service_name", "unknown")
                operation_name = span_dict.get("operation_name", "operation")
                
                # Parse times
                start_time = self._parse_timestamp(span_dict.get("start_time"))
                end_time = self._parse_timestamp(span_dict.get("end_time"))
                
                # Kind and status
                kind_str = span_dict.get("kind", "INTERNAL").upper()
                kind = SpanKind[kind_str] if kind_str in SpanKind.__members__ else SpanKind.INTERNAL
                
                status_str = span_dict.get("status", "UNSET").upper()
                status = SpanStatus[status_str] if status_str in SpanStatus.__members__ else SpanStatus.UNSET
                
                # Create span
                span = Span(
                    trace_id=trace_id,
                    span_id=span_id,
                    parent_span_id=parent_span_id,
                    service_name=service_name,
                    operation_name=operation_name,
                    start_time=start_time,
                    end_time=end_time,
                    kind=kind,
                    status=status,
                    attributes=span_dict.get("attributes", {}),
                    retry_count=span_dict.get("retry_count", 0),
                    error_message=span_dict.get("error_message"),
                )
                
                # Ingest
                if self.ingest_span(trace_id, span):
                    result["ingested"] += 1
                else:
                    result["deduplicated"] += 1
                    
            except Exception as e:
                result["failed"] += 1
                logger.error(f"Failed to parse span: {e}")
        
        return result

    async def ingest_span_async(self, trace_id: str, span: Span) -> bool:
        """Async wrapper for ingest_span."""
        # Setup queue if not exists
        if self.async_queue is None:
            self.async_queue = asyncio.Queue()
            asyncio.create_task(self._async_consumer())
        try:
            await self.async_queue.put((trace_id, span))
            return True
        except Exception as e:
            logger.error("Failed to enqueue span: %s", e)
            return False

    async def _async_consumer(self):
        while True:
            try:
                trace_id, span = await self.async_queue.get()
                self.ingest_span(trace_id, span)
            except Exception:
                logger.exception("Async consumer error")

    async def start_http_receiver(self, host: str = '0.0.0.0', port: int = 4318):
        """
        Start a minimal OTLP HTTP receiver for JSON spans at /v1/traces.
        Not full OTLP; accepts list of span dicts and ingests.
        """
        if web is None:
            logger.warning("aiohttp not available; HTTP OTLP receiver disabled")
            return None

        app = web.Application()

        async def handle_traces(request):
            try:
                payload = await request.json()
                spans = payload.get('spans') or []
                result = {'ingested': 0, 'failed': 0}
                for s in spans:
                    try:
                        trace_id = s.get('trace_id') or str(uuid.uuid4())
                        span_id = s.get('span_id') or str(uuid.uuid4())
                        span = Span(
                            trace_id=trace_id,
                            span_id=span_id,
                            parent_span_id=s.get('parent_span_id'),
                            service_name=s.get('service_name', 'unknown'),
                            operation_name=s.get('operation_name', 'op'),
                            start_time=self._parse_timestamp(s.get('start_time')),
                            end_time=self._parse_timestamp(s.get('end_time')),
                            kind=SpanKind[s.get('kind', 'INTERNAL')] if s.get('kind') in SpanKind.__members__ else SpanKind.INTERNAL,
                            status=SpanStatus[s.get('status', 'UNSET')] if s.get('status') in SpanStatus.__members__ else SpanStatus.UNSET,
                            attributes=s.get('attributes', {}),
                            retry_count=s.get('retry_count', 0),
                            error_message=s.get('error_message'),
                        )
                        await self.ingest_span_async(trace_id, span)
                        result['ingested'] += 1
                    except Exception:
                        result['failed'] += 1
                return web.json_response(result)
            except Exception as e:
                logger.exception("Failed handle_traces: %s", e)
                return web.json_response({'error': str(e)}, status=500)

        app.router.add_post('/v1/traces', handle_traces)

        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, host, port)
        await site.start()
        logger.info("OTLP HTTP receiver listening on %s:%d", host, port)
        # Keep running until cancelled
        self._http_server = asyncio.create_task(self._http_keepalive())
        return self._http_server

    async def _http_keepalive(self):
        try:
            while True:
                await asyncio.sleep(3600)
        except asyncio.CancelledError:
            return
    
    def _parse_timestamp(self, value: Any) -> Optional[datetime]:
        """Parse timestamp from various formats."""
        if value is None:
            return None
        if isinstance(value, datetime):
            return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value)
            except:
                return None
        return None
    
    def get_trace(self, trace_id: str) -> Optional[Trace]:
        """Get trace by ID."""
        return self.traces.get(trace_id)
    
    def get_traces_by_service(self, service_name: str) -> List[Trace]:
        """Get all traces containing service."""
        return [
            t for t in self.traces.values()
            if service_name in t.get_services()
        ]
    
    def get_error_traces(self, limit: int = 100) -> List[Trace]:
        """Get traces with errors, recent first."""
        error_traces = [t for t in self.traces.values() if t.error_spans()]
        # Sort by latest span time
        error_traces.sort(
            key=lambda t: t.latest_span_time or datetime.min,
            reverse=True
        )
        return error_traces[:limit]
    
    def get_incomplete_traces(self) -> List[Trace]:
        """Get traces with missing spans (orphans)."""
        incomplete = []
        for trace in self.traces.values():
            trace.check_completeness()
            if trace.is_broken or not trace.is_complete:
                incomplete.append(trace)
        return incomplete
    
    def close_trace(self, trace_id: str) -> Optional[Trace]:
        """Close trace (finalize, calculate metrics)."""
        trace = self.traces.pop(trace_id, None)
        if trace:
            trace.check_completeness()
            self.stats["total_traces_closed"] += 1
        return trace
    
    def health_check(self) -> Dict[str, Any]:
        """Ingestor health."""
        incomplete = self.get_incomplete_traces()
        return {
            "active_traces": len(self.traces),
            "orphan_groups": len(self.orphans),
            "incomplete_traces": len(incomplete),
            "total_spans": sum(len(t.spans) for t in self.traces.values()),
            "total_ingested": self.stats["total_spans_ingested"],
            "total_deduplicated": self.stats["total_spans_deduplicated"],
            "total_failed": self.stats["total_spans_failed"],
            "total_traces_closed": self.stats["total_traces_closed"],
        }


# Convenience: global ingestor instance
_default_otel_ingestor: Optional[OtelIngestor] = None


def get_otel_ingestor() -> OtelIngestor:
    """Get or create default OTEL ingestor."""
    global _default_otel_ingestor
    if _default_otel_ingestor is None:
        _default_otel_ingestor = OtelIngestor()
    return _default_otel_ingestor
