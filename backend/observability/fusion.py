from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from core.normalization import normalize_timestamp
from .traces import TraceIngestor, TraceSpan
from .prometheus_ingestor import get_prometheus_ingestor, MetricType
from .otel_ingestor import get_otel_ingestor
from .deployment_feed import get_deployment_feed
from .topology_discovery import get_topology_discovery


class TemporalAlignmentEngine:
    """Align deployment, metric, trace, and outage timestamps into one causal order."""

    def __init__(self):
        self.trace_ingestor = TraceIngestor()

    def align(
        self,
        incident: Dict[str, Any],
        deployment_correlation: Optional[Dict[str, Any]] = None,
        metric_anomalies: Optional[Sequence[Dict[str, Any]]] = None,
        trace_spans: Optional[Sequence[TraceSpan | Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        deployment_correlation = deployment_correlation or {}
        metric_anomalies = list(metric_anomalies or [])
        trace_spans = list(trace_spans or [])

        trace_objects: List[TraceSpan] = []
        for span in trace_spans:
            if isinstance(span, TraceSpan):
                trace_objects.append(span)
            elif isinstance(span, dict):
                trace_objects.extend(self.trace_ingestor.ingest({"spans": [span]}))

        deployment_timestamp = self._deployment_timestamp(incident, deployment_correlation)
        metric_timestamp = self._first_timestamp(metric_anomalies, ["timestamp", "time"])
        trace_degradation = self.trace_ingestor.detect_degradation(trace_objects)
        trace_timestamp = normalize_timestamp(trace_degradation.get("timestamp")) if trace_degradation else self._first_trace_timestamp(trace_objects)
        outage_timestamp = normalize_timestamp(incident.get("outage_start") or incident.get("timestamp") or incident.get("occurred_at"))

        ordered_events = self._ordered_events(deployment_timestamp, metric_timestamp, trace_timestamp, outage_timestamp)
        propagation_chain = self._propagation_chain(incident, deployment_timestamp, metric_timestamp, trace_timestamp, outage_timestamp)
        alignment_score = self._alignment_score(ordered_events)

        return {
            "deployment_timestamp": deployment_timestamp.isoformat() if deployment_timestamp else None,
            "metric_spike_timestamp": metric_timestamp.isoformat() if metric_timestamp else None,
            "trace_degradation_timestamp": trace_timestamp.isoformat() if trace_timestamp else None,
            "outage_start_timestamp": outage_timestamp.isoformat() if outage_timestamp else None,
            "ordered_events": ordered_events,
            "propagation_chain": propagation_chain,
            "deployment_attribution": bool(deployment_correlation.get("matched")) or deployment_timestamp is not None,
            "alignment_score": alignment_score,
            "trace_degradation": trace_degradation,
            "metric_names": sorted({str(item.get("metric_name", "metric")) for item in metric_anomalies}),
        }

    def _deployment_timestamp(self, incident: Dict[str, Any], deployment_correlation: Dict[str, Any]) -> Optional[datetime]:
        if deployment_correlation.get("events"):
            first_event = deployment_correlation["events"][0]
            timestamp = first_event.get("time") or first_event.get("timestamp")
            parsed = normalize_timestamp(timestamp)
            if parsed is not None:
                return parsed
        return normalize_timestamp(incident.get("deployment_time") or incident.get("last_deploy_time"))

    def _first_timestamp(self, items: Sequence[Dict[str, Any]], keys: Sequence[str]) -> Optional[datetime]:
        for item in items:
            for key in keys:
                parsed = normalize_timestamp(item.get(key))
                if parsed is not None:
                    return parsed
        return None

    def _first_trace_timestamp(self, spans: Sequence[TraceSpan]) -> Optional[datetime]:
        if not spans:
            return None
        ordered = sorted(spans, key=lambda span: span.start_timestamp)
        return ordered[-1].start_timestamp if ordered else None

    def _ordered_events(
        self,
        deployment_timestamp: Optional[datetime],
        metric_timestamp: Optional[datetime],
        trace_timestamp: Optional[datetime],
        outage_timestamp: Optional[datetime],
    ) -> List[Dict[str, Any]]:
        events: List[Dict[str, Any]] = []
        for phase, timestamp in [
            ("deployment", deployment_timestamp),
            ("metric_spike", metric_timestamp),
            ("trace_degradation", trace_timestamp),
            ("outage_start", outage_timestamp),
        ]:
            if timestamp is not None:
                events.append({"phase": phase, "timestamp": timestamp.isoformat()})
        return sorted(events, key=lambda item: item["timestamp"])

    def _propagation_chain(
        self,
        incident: Dict[str, Any],
        deployment_timestamp: Optional[datetime],
        metric_timestamp: Optional[datetime],
        trace_timestamp: Optional[datetime],
        outage_timestamp: Optional[datetime],
    ) -> List[Dict[str, Any]]:
        chain: List[Dict[str, Any]] = []
        if deployment_timestamp is not None:
            chain.append({
                "phase": "deployment",
                "description": f"Deployment {incident.get('deployment_id') or incident.get('commit_hash') or 'unknown'}",
                "timestamp": deployment_timestamp.isoformat(),
            })
        if metric_timestamp is not None:
            chain.append({
                "phase": "metric_spike",
                "description": "Observed latency/retry/saturation spike",
                "timestamp": metric_timestamp.isoformat(),
            })
        if trace_timestamp is not None:
            chain.append({
                "phase": "trace_degradation",
                "description": "Trace latency and timeout propagation",
                "timestamp": trace_timestamp.isoformat(),
            })
        if outage_timestamp is not None:
            chain.append({
                "phase": "outage_start",
                "description": "User-visible outage began",
                "timestamp": outage_timestamp.isoformat(),
            })
        return chain

    def _alignment_score(self, events: Sequence[Dict[str, Any]]) -> float:
        if not events:
            return 0.0
        return round(len(events) / 4.0, 2)


class LiveTelemetryFusionEngine:
    """
    Fuse live operational telemetry sources into coherent incident analysis.
    
    Integrates:
    - Prometheus metrics
    - OTEL traces
    - Deployment events
    - Service topology
    - Regression intelligence
    
    Handles:
    - Partial/delayed telemetry
    - Missing data with confidence adjustment
    - Telemetry gaps with graceful degradation
    - Conflict detection between signals
    """
    
    def __init__(self):
        self.prometheus = get_prometheus_ingestor()
        self.otel = get_otel_ingestor()
        self.deployments = get_deployment_feed()
        self.topology = get_topology_discovery()
        self.trace_ingestor = TraceIngestor()
        
        # Fusion statistics
        self.stats = {
            "total_fusions": 0,
            "partial_evidence_fusions": 0,
            "full_evidence_fusions": 0,
            "telemetry_gaps": 0,
        }
    
    def fuse_incident_context(self, incident: Dict[str, Any],
                             time_window_sec: float = 600.0) -> Dict[str, Any]:
        """
        Fuse all telemetry around incident.
        
        Correlates:
        - Incident service + error type
        - Recent deployments
        - Metric anomalies
        - Distributed traces
        - Service propagation
        - Regression matches
        
        Returns comprehensive context with confidence levels.
        """
        incident_time = normalize_timestamp(
            incident.get("timestamp") or incident.get("occurred_at")
        ) or datetime.now(timezone.utc)
        
        window_start = incident_time - timedelta(seconds=time_window_sec)
        window_end = incident_time + timedelta(seconds=time_window_sec)
        
        service = incident.get("service_name", "unknown")
        
        result = {
            "incident_time": incident_time.isoformat(),
            "service": service,
            "fusion_timestamp": datetime.now(timezone.utc).isoformat(),
            "evidence": {},
            "confidence_factors": {},
            "telemetry_gaps": [],
            "gaps_affecting_confidence": False,
        }
        
        # 1. Deployment correlation
        deployment_evidence = self._correlate_deployments(
            service, window_start, window_end
        )
        result["evidence"]["deployments"] = deployment_evidence
        
        # 2. Metric anomalies
        metric_evidence = self._correlate_metrics(
            service, window_start, window_end
        )
        result["evidence"]["metrics"] = metric_evidence
        
        # 3. Distributed traces
        trace_evidence = self._correlate_traces(
            service, window_start, window_end
        )
        result["evidence"]["traces"] = trace_evidence
        
        # 4. Topology propagation
        topology_evidence = self._propagation_analysis(
            service, incident
        )
        result["evidence"]["topology"] = topology_evidence
        
        # 5. Gap analysis
        gaps = self._detect_telemetry_gaps(
            service, window_start, window_end,
            deployment_evidence, metric_evidence, trace_evidence
        )
        result["telemetry_gaps"] = gaps
        
        # 6. Confidence computation with gap penalties
        confidence = self._compute_fused_confidence(
            deployment_evidence,
            metric_evidence,
            trace_evidence,
            topology_evidence,
            gaps
        )
        result["fused_confidence"] = confidence
        result["gaps_affecting_confidence"] = len(gaps) > 0
        
        self.stats["total_fusions"] += 1
        if len(gaps) > 0:
            self.stats["partial_evidence_fusions"] += 1
        else:
            self.stats["full_evidence_fusions"] += 1
        
        return result
    
    def _correlate_deployments(self, service: str, start: datetime,
                              end: datetime) -> Dict[str, Any]:
        """Find deployments within time window."""
        deploys = self.deployments.deployments_during_window(service, start, end)
        
        if not deploys:
            return {
                "found": False,
                "count": 0,
                "deployments": [],
                "confidence": 0.0,
            }
        
        # Recent deployment = higher correlation
        latest = max(deploys, key=lambda d: d.start_time)
        time_delta = (datetime.now(timezone.utc) - latest.start_time).total_seconds()
        
        # Confidence: 1.0 if <5min old, degrades to 0.3 at 1 hour
        confidence = max(0.3, 1.0 - (time_delta / 600.0))
        
        return {
            "found": True,
            "count": len(deploys),
            "latest_deployment": {
                "version": latest.version,
                "start_time": latest.start_time.isoformat(),
                "status": latest.status.value,
                "success": latest.success,
            },
            "deployments": [
                {
                    "version": d.version,
                    "start_time": d.start_time.isoformat(),
                    "status": d.status.value,
                }
                for d in deploys
            ],
            "confidence": confidence,
        }
    
    def _correlate_metrics(self, service: str, start: datetime,
                          end: datetime) -> Dict[str, Any]:
        """Find metric anomalies within window."""
        result = {
            "found": False,
            "anomalies": [],
            "degradation_detected": False,
            "confidence": 0.0,
        }
        
        # Query key metrics
        metric_types = [
            MetricType.ERROR_RATE,
            MetricType.LATENCY_P99,
            MetricType.CPU_SATURATION,
            MetricType.QUEUE_DEPTH,
        ]
        
        anomaly_count = 0
        for mtype in metric_types:
            # Get latest metric
            latest = self.prometheus.get_latest(service, mtype)
            if not latest:
                continue
            
            # Check if anomalous
            is_anomaly = self.prometheus.detect_anomaly(service, mtype)
            if is_anomaly:
                result["anomalies"].append({
                    "metric": mtype.value,
                    "value": latest.value,
                    "unit": latest.unit,
                    "timestamp": latest.timestamp.isoformat(),
                    "staleness": latest.staleness_factor(self.prometheus.stale_threshold),
                })
                anomaly_count += 1
        
        result["found"] = anomaly_count > 0
        result["anomalies_detected"] = anomaly_count
        result["confidence"] = min(1.0, anomaly_count * 0.25)  # 0.25 per anomaly
        
        return result
    
    def _correlate_traces(self, service: str, start: datetime,
                         end: datetime) -> Dict[str, Any]:
        """Find traces with service involvement."""
        traces = self.otel.get_traces_by_service(service)
        
        result = {
            "found": len(traces) > 0,
            "trace_count": len(traces),
            "error_traces": 0,
            "timeout_traces": 0,
            "incomplete_traces": 0,
            "confidence": 0.0,
        }
        
        if not traces:
            return result
        
        # Analyze traces
        error_traces = [t for t in traces if t.error_spans()]
        timeout_traces = [t for t in traces if t.timeout_spans()]
        incomplete = [t for t in traces if not t.is_complete]
        
        result["error_traces"] = len(error_traces)
        result["timeout_traces"] = len(timeout_traces)
        result["incomplete_traces"] = len(incomplete)
        
        # Confidence: traces provide strong evidence
        if error_traces or timeout_traces:
            result["confidence"] = min(0.9, 0.7 + len(error_traces) * 0.1)
        else:
            result["confidence"] = 0.3
        
        # Penalty for incomplete traces
        if incomplete:
            result["confidence"] *= (1.0 - 0.2 * min(1.0, len(incomplete) / len(traces)))
        
        return result
    
    def _propagation_analysis(self, service: str,
                             incident: Dict[str, Any]) -> Dict[str, Any]:
        """Analyze propagation path and blast radius."""
        topo = self.topology.get_graph()
        
        blast = topo.blast_radius(service)
        downstream = topo.get_downstream(service, max_depth=5)
        upstream = topo.get_upstream(service, max_depth=5)
        
        return {
            "service": service,
            "immediate_impact": blast.get("immediate_impact", []),
            "transitive_impact": list(downstream),
            "upstream_dependents": list(upstream),
            "critical_services": blast.get("critical_services", []),
            "topology_age_seconds": blast.get("discovery_age_seconds"),
            "confidence": 0.8 if topo.services else 0.2,  # Low if no topology
        }
    
    def _detect_telemetry_gaps(self, service: str, start: datetime,
                              end: datetime,
                              deployment_evidence: Dict,
                              metric_evidence: Dict,
                              trace_evidence: Dict) -> List[str]:
        """Identify missing telemetry sources."""
        gaps = []
        
        # Deployment gap
        if not deployment_evidence.get("found"):
            gaps.append("no_recent_deployments")
        
        # Metric gap
        if not metric_evidence.get("found"):
            gaps.append("no_metrics")
        
        # Trace gap
        if not trace_evidence.get("found"):
            gaps.append("no_traces")
        
        # Topology gap
        topo = self.topology.get_graph()
        if service not in topo.services:
            gaps.append("service_not_in_topology")
        
        self.stats["telemetry_gaps"] += len(gaps)
        return gaps
    
    def _compute_fused_confidence(self, deployment: Dict, metrics: Dict,
                                 traces: Dict, topology: Dict,
                                 gaps: List[str]) -> float:
        """
        Compute overall confidence from converging evidence.
        
        Rules:
        - Requires multiple evidence sources
        - Gaps reduce confidence proportionally
        - No single source dominates
        - Conflict (e.g., good metrics + bad traces) penalizes
        """
        # Base: average confidence from sources
        sources = [
            deployment.get("confidence", 0.0),
            metrics.get("confidence", 0.0),
            traces.get("confidence", 0.0),
            topology.get("confidence", 0.0),
        ]
        
        base_confidence = sum(sources) / len(sources)
        
        # Gap penalty: 0.2 per gap
        gap_penalty = len(gaps) * 0.15
        
        # Convergence: if multiple sources agree, boost confidence
        strong_sources = sum(1 for c in sources if c > 0.7)
        if strong_sources >= 2:
            convergence_bonus = 0.15
        else:
            convergence_bonus = 0.0
        
        # Final confidence
        confidence = base_confidence + convergence_bonus - gap_penalty
        
        return max(0.0, min(1.0, confidence))
    
    def health_summary(self) -> Dict[str, Any]:
        """Telemetry fusion engine health."""
        return {
            "prometheus": self.prometheus.health_check(),
            "otel": self.otel.health_check(),
            "deployments": self.deployments.health_check(),
            "topology_services": len(self.topology.get_graph().services),
            "fusion_stats": self.stats,
        }


# Convenience function
def get_live_telemetry_fusion() -> LiveTelemetryFusionEngine:
    """Get or create default live telemetry fusion engine."""
    global _fusion_engine
    if not hasattr(get_live_telemetry_fusion, '_instance'):
        get_live_telemetry_fusion._instance = LiveTelemetryFusionEngine()
    return get_live_telemetry_fusion._instance