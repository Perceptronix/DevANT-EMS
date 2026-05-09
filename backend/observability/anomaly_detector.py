from typing import List, Dict, Any

from ontology import MetricAnomaly


class AnomalyDetector:
    """Detect metric anomalies and correlate with deployments.

    Simple heuristics-based detector: spike detection and baseline deviation.
    """

    def __init__(self):
        pass

    def detect_spikes(self, series: List[Dict[str, Any]], factor: float = 3.0) -> List[Dict[str, Any]]:
        """Return list of detected spike events given a metric time series.

        series: list of {"time": ..., "value": ...}
        """
        if not series:
            return []
        values = [s.get("value", 0) for s in series]
        avg = sum(values) / len(values)
        spikes = []
        for s in series:
            if s.get("value", 0) > avg * factor:
                anomaly = MetricAnomaly(
                    source_of_truth="metric_series",
                    timestamp=s.get("time") if isinstance(s.get("time"), str) else s.get("time"),
                    confidence_origin="spike_detector",
                    evidence_origin=["metric_series"],
                    anomaly_id=f"{s.get('time')}-{s.get('value')}",
                    metric_name=s.get("metric", "unknown"),
                    value=float(s.get("value", 0)),
                    baseline=float(avg),
                    deviation=float(s.get("value", 0) - avg),
                    direction="up",
                    window_minutes=5,
                    service=s.get("service"),
                )
                spikes.append(anomaly.model_dump())
        return spikes
