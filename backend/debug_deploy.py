"""Debug deployment overlap calculation."""

from memory.regression_engine import get_regression_engine
from datetime import datetime, timedelta

engine = get_regression_engine()

# Record a resolved incident
hist_time = datetime.utcnow() - timedelta(days=5)
print(f"Historical incident time: {hist_time}")
print(f"Historical deployment time: {(hist_time - timedelta(hours=1)).isoformat()}")

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

# Get the stored incident
stored_incident = engine.memory_graph.incidents[incident_id]
print(f"\nStored incident:")
print(f"  deployment_id: {stored_incident.deployment_id}")
print(f"  timestamp: {stored_incident.timestamp} (type: {type(stored_incident.timestamp)})")

# Now test deployment overlap with new incident
new_time = datetime.utcnow()
new_deployment_time = (new_time - timedelta(hours=0.5)).isoformat()
print(f"\nNew incident:")
print(f"  deployment_id: deploy-v1.1")
print(f"  deployment_time: {new_deployment_time}")

# Test the _deployment_overlap_score function
score = engine.memory_graph._deployment_overlap_score(
    "deploy-v1.1",
    new_deployment_time,
    stored_incident.deployment_id,
    stored_incident.timestamp,
)
print(f"\nDeployment overlap score: {score}")

# Let me manually trace through the function logic
print("\n--- Tracing _deployment_overlap_score logic ---")
print(f"new_deployment_id = 'deploy-v1.1', new_deployment_time = {new_deployment_time}")
print(f"prev_deployment_id = {stored_incident.deployment_id}, prev_incident_time = {stored_incident.timestamp}")
print(f"IDs equal? {'deploy-v1.1' == stored_incident.deployment_id}")
print(f"new_deployment_id provided? True")
print(f"prev_deployment_id provided? {stored_incident.deployment_id is not None}")

# The function should check temporal proximity since IDs are different
if "deploy-v1.1" != stored_incident.deployment_id:
    from core.normalization import normalize_timestamp
    new_time_parsed = normalize_timestamp(new_deployment_time)
    print(f"Parsed new_deployment_time: {new_time_parsed} (type: {type(new_time_parsed)})")
    print(f"prev_incident_time: {stored_incident.timestamp} (type: {type(stored_incident.timestamp)})")
    
    if new_time_parsed:
        delta_minutes = abs((stored_incident.timestamp - new_time_parsed).total_seconds() / 60)
        print(f"Time delta: {delta_minutes} minutes")
        if delta_minutes < 30:
            print(f"  -> Would return 0.7")
        elif delta_minutes < 120:
            print(f"  -> Would return 0.4")
        else:
            print(f"  -> Would return 0.0")
