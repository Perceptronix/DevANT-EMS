"""Debug detect_regression in detail."""

from memory.regression_memory import RegressionMemoryGraph, RegressionIncident
from memory.stacktrace_normalizer import StacktraceNormalizer
from datetime import datetime, timedelta
from core.normalization import normalize_timestamp

graph = RegressionMemoryGraph()
normalizer = StacktraceNormalizer()

stacktrace_template = """Traceback (most recent call last):
  File "/app/handlers.py", line 89, in process_request
    timeout_value = int(config['timeout_ms'] / 1000)
  File "/app/config.py", line 156, in __getitem__
    if not hasattr(self.data, key):
AttributeError: 'NoneType' object has no attribute 'get'
    """

# Create a resolved incident
hist_time = datetime.utcnow() - timedelta(days=30)
hist_incident = RegressionIncident(
    incident_id="config-error-001",
    error_signature="config_parsing_error",
    service="api-server",
    normalized_stacktrace=normalizer.normalize(stacktrace_template),
    timestamp=normalize_timestamp(hist_time.isoformat()),
    deployment_id="deploy-v1.0",
    status="resolved",
)

graph.insert_resolved(hist_incident)

# Check what was stored
print(f"Stored incident:")
for inc_id, inc in graph.incidents.items():
    print(f"  {inc_id}: service={inc.service} status={inc.status}")

# Now manually walk through detect_regression logic
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

print(f"\nWalking through detect_regression:")
service = new_incident_data.get("service", "unknown")
print(f"  service: {service}")

for inc in graph.incidents.values():
    print(f"\n  Checking incident {inc.incident_id}:")
    print(f"    inc.service == service? {inc.service} == {service} -> {inc.service == service}")
    print(f"    inc.status == 'resolved'? {inc.status} -> {inc.status == 'resolved'}")
    
    if inc.service != service or inc.status != "resolved":
        print(f"    SKIPPED: service or status mismatch")
        continue
    
    # Calculate similarity
    sim, _ = normalizer.similarity(new_incident_data["stacktrace"], inc.normalized_stacktrace)
    print(f"    stacktrace_similarity: {sim}")
    
    # Calculate temporal proximity
    new_ts = normalize_timestamp(new_incident_data["timestamp"])
    print(f"    new_ts: {new_ts} (type: {type(new_ts)})")
    print(f"    inc.timestamp: {inc.timestamp} (type: {type(inc.timestamp)})")
    
    if new_ts and inc.timestamp:
        delta_days = (new_ts - inc.timestamp).days
        print(f"    delta_days: {delta_days}")
        
        if delta_days <= 1:
            temporal = 1.0
        elif delta_days <= 7:
            temporal = 0.9
        elif delta_days <= 30:
            temporal = 0.7
        elif delta_days <= 90:
            temporal = 0.4
        else:
            temporal = 0.0
        
        print(f"    temporal_proximity: {temporal}")
        
        # Weighted confidence
        confidence = (
            (sim * 0.35)
            + (0.0 * 0.25)
            + (0.0 * 0.15)
            + (temporal * 0.15)
            + (0.0 * 0.10)
        )
        print(f"    confidence: {confidence}")
