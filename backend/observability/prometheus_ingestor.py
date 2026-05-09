"""
Prometheus metrics ingestion for live operational telemetry grounding.

Handles:
- Polling + range queries for historical metrics
- Sparse metric handling (missing/delayed/malformed)
- Incremental ingestion to avoid duplicates
- Latency percentiles (p50/p95/p99)
- Resource saturation (CPU, memory)
- Error/retry rates, queue depth, throughput
- Graceful degradation under partial telemetry
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime, timedelta, timezone
from enum import Enum
import logging
import hashlib
import json
import asyncio
from typing import Iterable
try:
    import aiohttp
except Exception:
    aiohttp = None
from collections import defaultdict

logger = logging.getLogger(__name__)


class MetricType(Enum):
    """Prometheus metric categories."""
    LATENCY_P50 = "latency_p50"
    LATENCY_P95 = "latency_p95"
    LATENCY_P99 = "latency_p99"
    CPU_SATURATION = "cpu_saturation"
    MEMORY_SATURATION = "memory_saturation"
    ERROR_RATE = "error_rate"
    RETRY_RATE = "retry_rate"
    QUEUE_DEPTH = "queue_depth"
    REQUEST_THROUGHPUT = "request_throughput"
    CUSTOM = "custom"


@dataclass
class MetricPoint:
    """Single metric observation."""
    timestamp: datetime
    service: str
    metric_type: MetricType
    value: float
    labels: Dict[str, str] = field(default_factory=dict)
    unit: str = "unknown"
    is_stale: bool = False
    ingestion_timestamp: Optional[datetime] = None
    
    def __post_init__(self):
        # Normalize timestamp to UTC-aware
        if self.timestamp.tzinfo is None:
            self.timestamp = self.timestamp.replace(tzinfo=timezone.utc)
        if self.ingestion_timestamp is None:
            self.ingestion_timestamp = datetime.now(timezone.utc)
    
    def age_seconds(self) -> float:
        """Seconds since metric recorded."""
        now = datetime.now(timezone.utc)
        return (now - self.timestamp).total_seconds()
    
    def staleness_factor(self, stale_threshold_sec: float = 300.0) -> float:
        """
        Staleness 0.0 (fresh) to 1.0 (very stale).
        Stale threshold: 5 minutes default.
        """
        age = self.age_seconds()
        if age < 0:
            return 0.0  # Future timestamp, treat as fresh
        if age > stale_threshold_sec:
            return 1.0
        return age / stale_threshold_sec


@dataclass
class MetricSeries:
    """Time series of metric observations."""
    service: str
    metric_type: MetricType
    points: List[MetricPoint] = field(default_factory=list)
    
    def latest(self) -> Optional[MetricPoint]:
        """Most recent point."""
        return self.points[-1] if self.points else None
    
    def trend(self, window_sec: float = 300.0) -> Optional[float]:
        """
        Rate of change (slope) over window.
        Positive = increasing, negative = decreasing.
        None if <2 points in window.
        """
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(seconds=window_sec)
        
        recent = [p for p in self.points if p.timestamp >= cutoff]
        if len(recent) < 2:
            return None
        
        # Linear regression slope
        x = [(p.timestamp - recent[0].timestamp).total_seconds() for p in recent]
        y = [p.value for p in recent]
        
        if len(x) < 2:
            return None
        
        n = len(x)
        sum_x = sum(x)
        sum_y = sum(y)
        sum_xy = sum(a * b for a, b in zip(x, y))
        sum_x2 = sum(a * a for a in x)
        
        denom = n * sum_x2 - sum_x * sum_x
        if denom == 0:
            return None
        
        return (n * sum_xy - sum_x * sum_y) / denom
    
    def percentile(self, p: int = 95, window_sec: float = 300.0) -> Optional[float]:
        """95th percentile over window."""
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(seconds=window_sec)
        
        recent = [pt.value for pt in self.points if pt.timestamp >= cutoff]
        if not recent:
            return None
        
        sorted_vals = sorted(recent)
        idx = int(len(sorted_vals) * p / 100)
        return sorted_vals[min(idx, len(sorted_vals) - 1)]


@dataclass
class MetricIngestionResult:
    """Result of ingestion attempt."""
    success: bool
    metric_type: MetricType
    service: str
    points_ingested: int
    points_failed: int
    failures: List[str] = field(default_factory=list)
    deduplicated: int = 0


class PrometheusIngestor:
    """
    Ingest Prometheus metrics for live telemetry grounding.
    
    Capabilities:
    - Polling + range queries
    - Historical ingestion (gaps handled)
    - Incremental updates (deduplication)
    - Sparse handling (missing metric OK, confidence adjusted)
    - Staleness tracking
    """
    
    def __init__(self, poll_interval_sec: float = 30.0, stale_threshold_sec: float = 300.0):
        self.poll_interval = poll_interval_sec
        self.stale_threshold = stale_threshold_sec
        
        # Time series storage: (service, metric_type) -> MetricSeries
        self.series: Dict[Tuple[str, MetricType], MetricSeries] = {}
        
        # Deduplication: hash of (service, metric_type, timestamp, value)
        self.seen_hashes: set = set()
        
        # Last poll timestamp per query
        self.last_polls: Dict[Tuple[str, MetricType], datetime] = {}
        
        # Ingestion statistics
        self.stats = {
            "total_ingested": 0,
            "total_deduplicated": 0,
            "total_failed": 0,
            "ingestions": 0,
        }
    
    def _dedup_hash(self, service: str, metric_type: MetricType, 
                   timestamp: datetime, value: float) -> str:
        """Create hash for deduplication."""
        data = f"{service}:{metric_type.value}:{timestamp.isoformat()}:{value}"
        return hashlib.md5(data.encode()).hexdigest()
    
    def ingest_point(self, service: str, metric_type: MetricType, value: float,
                    timestamp: Optional[datetime] = None,
                    labels: Optional[Dict[str, str]] = None,
                    unit: str = "unknown") -> bool:
        """
        Ingest single metric point.
        
        Returns: True if ingested, False if duplicate/invalid.
        """
        if timestamp is None:
            timestamp = datetime.now(timezone.utc)
        elif timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        
        # Deduplication
        hash_key = self._dedup_hash(service, metric_type, timestamp, value)
        if hash_key in self.seen_hashes:
            self.stats["total_deduplicated"] += 1
            return False
        
        self.seen_hashes.add(hash_key)
        
        # Create point
        point = MetricPoint(
            timestamp=timestamp,
            service=service,
            metric_type=metric_type,
            value=value,
            labels=labels or {},
            unit=unit,
        )
        
        # Get or create series
        key = (service, metric_type)
        if key not in self.series:
            self.series[key] = MetricSeries(service=service, metric_type=metric_type)
        
        # Append (keep sorted by timestamp)
        self.series[key].points.append(point)
        self.series[key].points.sort(key=lambda p: p.timestamp)
        
        # Trim old points (keep last 1000)
        if len(self.series[key].points) > 1000:
            self.series[key].points = self.series[key].points[-1000:]
        
        self.stats["total_ingested"] += 1
        return True
    
    def ingest_batch(self, points: List[Dict[str, Any]]) -> MetricIngestionResult:
        """
        Ingest batch of metrics.
        
        Each point dict:
        {
            "service": str,
            "metric_type": str,
            "value": float,
            "timestamp": ISO string or datetime,
            "labels": dict,
            "unit": str,
        }
        """
        result = MetricIngestionResult(
            success=True,
            metric_type=MetricType.CUSTOM,
            service="batch",
            points_ingested=0,
            points_failed=0,
        )
        
        for point_dict in points:
            try:
                service = point_dict.get("service", "unknown")
                metric_str = point_dict.get("metric_type", "custom")
                value = float(point_dict.get("value", 0.0))
                
                # Parse timestamp
                ts_val = point_dict.get("timestamp")
                if isinstance(ts_val, str):
                    timestamp = datetime.fromisoformat(ts_val)
                elif isinstance(ts_val, datetime):
                    timestamp = ts_val
                else:
                    timestamp = None
                
                # Convert metric_type
                try:
                    metric_type = MetricType[metric_str.upper().replace(" ", "_")]
                except (KeyError, AttributeError):
                    metric_type = MetricType.CUSTOM
                
                labels = point_dict.get("labels", {})
                unit = point_dict.get("unit", "unknown")
                
                if self.ingest_point(service, metric_type, value, timestamp, labels, unit):
                    result.points_ingested += 1
                else:
                    result.deduplicated += 1
                    
            except Exception as e:
                result.points_failed += 1
                result.failures.append(str(e))
                logger.error(f"Failed to ingest point: {e}")
        
        self.stats["ingestions"] += 1
        return result

    # Async HTTP query to real Prometheus /api/v1/query_range
    async def query_range_async(self, prom_url: str, query: str, start: datetime, end: datetime, step: str = "60s", timeout: float = 10.0, max_retries: int = 3) -> Optional[Dict[str, Any]]:
        """
        Query Prometheus HTTP API `/api/v1/query_range` asynchronously.
        Returns parsed JSON on success, None on failure.
        """
        if aiohttp is None:
            logging.warning("aiohttp not installed, cannot perform async Prometheus queries")
            return None

        url = f"{prom_url.rstrip('/')}/api/v1/query_range"
        params = {"query": query, "start": start.isoformat(), "end": end.isoformat(), "step": step}

        backoff = 1.0
        for attempt in range(1, max_retries + 1):
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(url, params=params, timeout=timeout) as resp:
                        if resp.status != 200:
                            text = await resp.text()
                            logging.warning("Prometheus query returned %s: %s", resp.status, text)
                            raise RuntimeError(f"prometheus error {resp.status}")
                        data = await resp.json()
                        return data
            except Exception as e:
                logging.warning("Prometheus query attempt %d failed: %s", attempt, e)
                await asyncio.sleep(backoff)
                backoff *= 2
        return None

    def query_range(self, prom_url: str, query: str, start: datetime, end: datetime, step: str = "60s") -> Optional[Dict[str, Any]]:
        """Synchronous wrapper for query_range_async. Returns JSON or None."""
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            import asyncio
            loop = asyncio.new_event_loop(); asyncio.set_event_loop(loop)
        return loop.run_until_complete(self.query_range_async(prom_url, query, start, end, step))
    
    def query_range(self, service: str, metric_type: MetricType,
                   start_time: datetime, end_time: datetime) -> MetricSeries:
        """
        Query range of historical metrics.
        
        Returns series with points in [start_time, end_time].
        Empty series if no data.
        """
        key = (service, metric_type)
        if key not in self.series:
            return MetricSeries(service=service, metric_type=metric_type)
        
        full_series = self.series[key]
        filtered_points = [
            p for p in full_series.points
            if start_time <= p.timestamp <= end_time
        ]
        
        result = MetricSeries(service=service, metric_type=metric_type)
        result.points = filtered_points
        return result
    
    def get_latest(self, service: str, metric_type: MetricType) -> Optional[MetricPoint]:
        """Get most recent metric point."""
        key = (service, metric_type)
        series = self.series.get(key)
        return series.latest() if series else None
    
    def get_services(self) -> List[str]:
        """List all services with metrics."""
        return list(set(service for service, _ in self.series.keys()))
    
    def get_metrics_for_service(self, service: str) -> List[MetricType]:
        """List metric types available for service."""
        return [mt for s, mt in self.series.keys() if s == service]
    
    def detect_anomaly(self, service: str, metric_type: MetricType,
                      threshold_std: float = 2.0,
                      window_sec: float = 300.0) -> bool:
        """
        Simple anomaly: value >threshold_std deviations above mean.
        
        Returns True if latest point anomalous.
        """
        key = (service, metric_type)
        if key not in self.series:
            return False
        
        series = self.series[key]
        latest = series.latest()
        if not latest:
            return False
        
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(seconds=window_sec)
        recent = [p.value for p in series.points if p.timestamp >= cutoff]
        
        if len(recent) < 2:
            return False
        
        mean = sum(recent) / len(recent)
        variance = sum((x - mean) ** 2 for x in recent) / len(recent)
        if variance == 0:
            return False
        
        std_dev = variance ** 0.5
        z_score = (latest.value - mean) / std_dev
        
        return z_score > threshold_std
    
    def health_check(self) -> Dict[str, Any]:
        """Ingestor health summary."""
        return {
            "services": len(self.get_services()),
            "series": len(self.series),
            "total_points": sum(len(s.points) for s in self.series.values()),
            "total_ingested": self.stats["total_ingested"],
            "total_deduplicated": self.stats["total_deduplicated"],
            "total_failed": self.stats["total_failed"],
            "ingestions": self.stats["ingestions"],
            "stale_threshold_sec": self.stale_threshold,
        }
    
    def export_state(self) -> Dict[str, Any]:
        """Export all metrics for persistence/debugging."""
        result = {}
        for (service, metric_type), series in self.series.items():
            key = f"{service}:{metric_type.value}"
            result[key] = {
                "metric_type": metric_type.value,
                "service": service,
                "points": [
                    {
                        "timestamp": p.timestamp.isoformat(),
                        "value": p.value,
                        "unit": p.unit,
                        "staleness": p.staleness_factor(self.stale_threshold),
                    }
                    for p in series.points[-100:]  # Last 100 points
                ]
            }
        return result


# Convenience: global ingestor instance
_default_ingestor: Optional[PrometheusIngestor] = None


def get_prometheus_ingestor() -> PrometheusIngestor:
    """Get or create default Prometheus ingestor."""
    global _default_ingestor
    if _default_ingestor is None:
        _default_ingestor = PrometheusIngestor()
    return _default_ingestor
