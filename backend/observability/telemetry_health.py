"""
Telemetry health monitoring. Tracks ingestion lag, queue pressure, completeness.
"""
from datetime import datetime, timezone
from typing import Dict, Any


def make_health_snapshot(prometheus, otel, deployments, topology, pipeline_stats=None) -> Dict[str, Any]:
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "prometheus": prometheus.health_check() if hasattr(prometheus, 'health_check') else {},
        "otel": otel.health_check() if hasattr(otel, 'health_check') else {},
        "deployments": deployments.health_check() if hasattr(deployments, 'health_check') else {},
        "topology_services": len(topology.get_graph().services) if hasattr(topology, 'get_graph') else 0,
        "pipeline": pipeline_stats or {},
    }
