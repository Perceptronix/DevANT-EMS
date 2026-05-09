"""Debug detect_regression directly."""

from memory.regression_engine import get_regression_engine
from memory.regression_memory import RegressionIncident
from datetime import datetime, timedelta
from core.normalization import normalize_timestamp

engine = get_regression_engine()

stacktrace_template = """Traceback (most recent call last):
  File "/app/handlers.py", line 89, in process_request
    timeout_value = int(config['timeout_ms'] / 1000)
  File "/app/config.py", line 156, in __getitem__
    if not hasattr(self.data, key):
AttributeError: 'NoneType' object has no attribute 'get'
    """

# Record
hist_time = datetime.utcnow() - timedelta(days=30)
hist_incident = {
    "incident_id": "config-error-001",
    "service": "api-server",
    "error_signature": "config_parsing_error",
    "sample_message": stacktrace_template,
    "deployment_id": "deploy-v1.0",
    "deployment_time": (hist_time - timedelta(minutes=5)).isoformat(),
    "timestamp": hist_time.isoformat(),
}

incident_id = engine.record_resolution(hist_incident, "Fixed", "Root cause")

# Check stored
stored = engine.memory_graph.incidents[incident_id]
print(f"Stored incident:")
print(f"  service: {stored.service}")
print(f"  status: {stored.status}")
print(f"  timestamp: {stored.timestamp} (type: {type(stored.timestamp)})")
print(f"  deployment_id: {stored.deployment_id}")

# Now call detect_regression directly
new_time = datetime.utcnow()
new_incident_data = {
    "service": "api-server",
    "error_signature": "config_parsing_error",
    "stacktrace": stacktrace_template,
    "deployment_id": "deploy-v2.0",
    "deployment_time": (new_time - timedelta(minutes=2)).isoformat(),
    "timestamp": new_time.isoformat(),
    "metrics_anomalies": [],
    "propagation_path": [],
}

print(f"\nNew incident data:")
print(f"  stacktrace length: {len(new_incident_data['stacktrace'])}")
print(f"  timestamp: {new_incident_data['timestamp']}")

match = engine.memory_graph.detect_regression(new_incident_data, threshold=0.4)
print(f"\nDetection result:")
print(f"  is_regression: {match.is_regression}")
print(f"  confidence: {match.confidence}")
print(f"  stacktrace_similarity: {match.stacktrace_similarity}")
print(f"  temporal_proximity_minutes: {match.temporal_proximity_minutes}")
