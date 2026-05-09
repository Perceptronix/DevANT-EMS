from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from statistics import mean, StatisticsError, quantiles
from typing import Any, Dict, Iterable, List, Optional, Sequence

from core.normalization import normalize_timestamp
from ontology import MetricAnomaly


@dataclass
class MetricReading:
    metric_name: str
    value: float
    timestamp: datetime
    service: Optional[str] = None
    source_of_truth: str = "observability.metrics"
    confidence_origin: str = "telemetry_ingestion"
    evidence_origin: List[str] = field(default_factory=list)
    persistence_rules: Dict[str, Any] = field(default_factory=lambda: {
        "retention": "indefinite",
        "mutability": "append-only",
        "rewrite_policy": "source-driven",
    })
    tags: Dict[str, Any] = field(default_factory=dict)


@dataclass
class MetricSummary:
    metric_name: str
    service: Optional[str]
    count: int
    baseline: float
    p95: float
    p99: float
    latest: float
    latest_timestamp: datetime


class MetricsAdapter:
    """Adapter interface for metrics backends (Prometheus, Grafana, OTEL)."""

    def __init__(self):
        pass

    async def query_series(self, query: str, start: str, end: str) -> List[Dict[str, Any]]:
        return []

    async def get_metric_value(self, metric: str, at_time: str) -> Optional[float]:
        return None


class TelemetryBaselineEngine:
    """Detect metric drift using rolling windows and percentile comparison."""

    def __init__(self, window_size: int = 20):
        self.window_size = max(5, window_size)

    def ingest(self, series: Sequence[Dict[str, Any]]) -> List[MetricReading]:
        readings: List[MetricReading] = []
        for item in series:
            timestamp = normalize_timestamp(item.get("timestamp") or item.get("time")) or datetime.utcnow()
            metric_name = str(item.get("metric_name") or item.get("name") or item.get("metric") or "unknown")
            value = float(item.get("value", 0.0))
            readings.append(
                MetricReading(
                    metric_name=metric_name,
                    value=value,
                    timestamp=timestamp,
                    service=item.get("service"),
                    source_of_truth=str(item.get("source_of_truth", "observability.metrics")),
                    confidence_origin=str(item.get("confidence_origin", "telemetry_ingestion")),
                    evidence_origin=[str(item.get("source", "metric_series"))],
                    tags=dict(item.get("tags", {})),
                )
            )
        return readings

    def summarize(self, series: Sequence[Dict[str, Any]]) -> List[MetricSummary]:
        readings = self.ingest(series)
        grouped: Dict[tuple[str, Optional[str]], List[MetricReading]] = {}
        for reading in readings:
            grouped.setdefault((reading.metric_name, reading.service), []).append(reading)

        summaries: List[MetricSummary] = []
        for (metric_name, service), values in grouped.items():
            ordered = sorted(values, key=lambda item: item.timestamp)
            numeric_values = [item.value for item in ordered]
            baseline = mean(numeric_values[:-1] or numeric_values)
            p95, p99 = self._percentiles(numeric_values)
            latest = numeric_values[-1]
            summaries.append(
                MetricSummary(
                    metric_name=metric_name,
                    service=service,
                    count=len(numeric_values),
                    baseline=baseline,
                    p95=p95,
                    p99=p99,
                    latest=latest,
                    latest_timestamp=ordered[-1].timestamp,
                )
            )
        return summaries

    def detect_anomalies(self, series: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
        readings = self.ingest(series)
        grouped: Dict[tuple[str, Optional[str]], List[MetricReading]] = {}
        for reading in readings:
            grouped.setdefault((reading.metric_name, reading.service), []).append(reading)

        anomalies: List[Dict[str, Any]] = []
        for (metric_name, service), values in grouped.items():
            ordered = sorted(values, key=lambda item: item.timestamp)
            if len(ordered) < 2:
                continue

            for index in range(1, len(ordered)):
                history = ordered[max(0, index - self.window_size) : index]
                current = ordered[index]
                history_values = [item.value for item in history] or [current.value]
                baseline = mean(history_values)
                p95, p99 = self._percentiles(history_values)

                severity = self._metric_severity(metric_name, current.value, baseline, p95, p99)
                if severity is None:
                    continue

                anomaly = MetricAnomaly(
                    source_of_truth=current.source_of_truth,
                    timestamp=current.timestamp,
                    confidence_origin=current.confidence_origin,
                    evidence_origin=list(current.evidence_origin),
                    persistence_rules=dict(current.persistence_rules),
                    anomaly_id=f"{metric_name}:{current.timestamp.isoformat()}",
                    metric_name=metric_name,
                    value=current.value,
                    baseline=baseline,
                    deviation=(current.value - baseline) / baseline if baseline else current.value,
                    direction="up" if current.value >= baseline else "down",
                    window_minutes=self.window_size,
                    service=service,
                )
                payload = anomaly.model_dump()
                payload["p95"] = p95
                payload["p99"] = p99
                payload["severity"] = severity
                anomalies.append(payload)
                break

        return anomalies

    def align_samples(
        self,
        deployment_timestamp: Any,
        metric_spike_timestamp: Any,
        trace_degradation_timestamp: Any,
        outage_start_timestamp: Any,
    ) -> Dict[str, Any]:
        timestamps = [
            normalize_timestamp(deployment_timestamp),
            normalize_timestamp(metric_spike_timestamp),
            normalize_timestamp(trace_degradation_timestamp),
            normalize_timestamp(outage_start_timestamp),
        ]
        ordered = [timestamp for timestamp in timestamps if timestamp is not None]
        if len(ordered) < 2:
            return {"aligned": False, "alignment_score": 0.0, "ordered_timestamps": []}

        is_monotonic = ordered == sorted(ordered)
        score = sum(1 for left, right in zip(ordered, ordered[1:]) if left <= right) / max(1, len(ordered) - 1)
        return {
            "aligned": is_monotonic,
            "alignment_score": score,
            "ordered_timestamps": [timestamp.isoformat() for timestamp in sorted(ordered)],
        }

    def _metric_severity(self, metric_name: str, current: float, baseline: float, p95: float, p99: float) -> Optional[str]:
        metric = metric_name.lower()
        if any(token in metric for token in ["latency", "p95", "p99", "duration"]):
            if current > max(p95, baseline * 1.5):
                return "high"
        elif "retry" in metric:
            if current > max(p99, baseline * 2.0):
                return "high"
        elif any(token in metric for token in ["saturation", "cpu", "memory", "queue"]):
            if current > max(p95, baseline * 1.25):
                return "high"
        elif current > max(p99, baseline * 1.5):
            return "medium"
        return None

    def _percentiles(self, values: Iterable[float]) -> tuple[float, float]:
        numeric_values = sorted(float(value) for value in values)
        if len(numeric_values) == 1:
            return numeric_values[0], numeric_values[0]
        try:
            q95, q99 = quantiles(numeric_values, n=100, method="inclusive")[94], quantiles(numeric_values, n=100, method="inclusive")[98]
            return float(q95), float(q99)
        except StatisticsError:
            return numeric_values[-1], numeric_values[-1]
