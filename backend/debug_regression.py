"""Debug regression detection."""

from memory.regression_engine import get_regression_engine
from memory.regression_memory import RegressionIncident
from datetime import datetime, timedelta

engine = get_regression_engine()

# Record a resolved incident
hist_time = datetime.utcnow() - timedelta(days=5)
hist_incident = {
    "incident_id": "redis-001",
    "service": "cache-service",
    "error_signature": "redis_connection_refused",
    "sample_message": "ConnectionError: Error 61 connecting to redis:6379. Connection refused.",
    "deployment_id": "deploy-v1.0",
    "deployment_time": (hist_time - timedelta(hours=1)).isoformat(),
    "timestamp": hist_time.isoformat(),
    "severity": "S2",
}

incident_id = engine.record_resolution(hist_incident, "Restarted Redis", "Pool exhaustion")
print(f"Recorded: {incident_id}")

# Check memory
print(f"Memory size: {len(engine.memory_graph.incidents)}")
for inc_id, inc in engine.memory_graph.incidents.items():
    print(f"  - {inc_id}: {inc.service} @ {inc.timestamp} status={inc.status}")
    print(f"    normalized stacktrace: {inc.normalized_stacktrace[:80]}...")

# Check the detect_regression logic step by step
new_time = datetime.utcnow()
new_incident_data = {
    "service": "cache-service",
    "error_signature": "redis_connection_refused",
    "stacktrace": "ConnectionError: Error 61 connecting to redis:6379. Connection refused.",
    "deployment_id": "deploy-v1.1",
    "deployment_time": (new_time - timedelta(hours=0.5)).isoformat(),
    "timestamp": new_time.isoformat(),
    "metrics_anomalies": [],
    "propagation_path": [],
}

# Try detection
match = engine.memory_graph.detect_regression(new_incident_data, threshold=0.5)
print(f"\nDetection result:")
print(f"  is_regression: {match.is_regression}")
print(f"  confidence: {match.confidence}")
print(f"  reason: {match.reason}")
if match.is_regression:
    print(f"  signals:")
    print(f"    stacktrace_similarity: {match.stacktrace_similarity}")
    print(f"    deployment_overlap: {match.deployment_overlap}")
    print(f"    metric_overlap: {match.metric_overlap}")
    print(f"    temporal_proximity_minutes: {match.temporal_proximity_minutes}")

