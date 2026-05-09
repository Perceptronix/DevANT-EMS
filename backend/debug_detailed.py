"""Debug detection in detail."""

from memory.regression_engine import get_regression_engine
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

# Manually test the detection
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

# Manually iterate through incidents to debug
print("Checking incidents in memory graph...")
for inc_id, incident in engine.memory_graph.incidents.items():
    print(f"\nIncident: {inc_id}")
    print(f"  Service match: {incident.service} == 'cache-service'? {incident.service == 'cache-service'}")
    print(f"  Status: {incident.status} == 'resolved'? {incident.status == 'resolved'}")
    print(f"  Will process: {incident.service == 'cache-service' and incident.status == 'resolved'}")
    
    if incident.service == 'cache-service' and incident.status == 'resolved':
        # Calculate signals
        stacktrace_sim, _ = engine.memory_graph.normalizer.similarity(
            new_incident_data["stacktrace"],
            incident.normalized_stacktrace,
        )
        print(f"  Stacktrace similarity: {stacktrace_sim}")
        
        deployment_overlap = engine.memory_graph._deployment_overlap_score(
            new_incident_data["deployment_id"],
            new_incident_data["deployment_time"],
            incident.deployment_id,
            incident.timestamp,
        )
        print(f"  Deployment overlap: {deployment_overlap}")
        
        metric_overlap = engine.memory_graph._metric_overlap_score(
            new_incident_data["metrics_anomalies"],
            incident.associated_metrics,
        )
        print(f"  Metric overlap: {metric_overlap}")
        
        temporal_proximity = engine.memory_graph._temporal_proximity_score(
            new_incident_data["timestamp"],
            incident.timestamp,
        )
        print(f"  Temporal proximity: {temporal_proximity}")
        
        propagation_sim = engine.memory_graph._propagation_alignment_score(
            new_incident_data["propagation_path"],
            incident.propagation_path,
        )
        print(f"  Propagation alignment: {propagation_sim}")
        
        # Weighted confidence
        confidence = (
            (stacktrace_sim * 0.35)
            + (deployment_overlap * 0.25)
            + (metric_overlap * 0.15)
            + (temporal_proximity * 0.15)
            + (propagation_sim * 0.10)
        )
        print(f"  Combined confidence: {confidence}")
