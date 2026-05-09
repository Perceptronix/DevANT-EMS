"""Debug deployment regression test."""

from memory.regression_engine import get_regression_engine
from datetime import datetime, timedelta

engine = get_regression_engine()

# Historical incident
hist_time = datetime.utcnow() - timedelta(days=30)
hist_incident = {
    "incident_id": "config-error-001",
    "service": "api-server",
    "error_signature": "config_parsing_error",
    "sample_message": """Traceback (most recent call last):
  File "/app/handlers.py", line 89, in process_request
    timeout_value = int(config['timeout_ms'] / 1000)
  File "/app/config.py", line 156, in __getitem__
    if not hasattr(self.data, key):
AttributeError: 'NoneType' object has no attribute 'get'
    """,
    "deployment_id": "deploy-v1.0",
    "deployment_time": (hist_time - timedelta(minutes=5)).isoformat(),
    "timestamp": hist_time.isoformat(),
    "severity": "S1",
}

incident_id = engine.record_resolution(hist_incident, "Fixed it", "Root cause")
print(f"Recorded: {incident_id}")

# New incident
new_time = datetime.utcnow()
new_incident = {
    "incident_id": "config-error-recurrence",
    "service": "api-server",
    "error_signature": "config_parsing_error",
    "sample_message": """Traceback (most recent call last):
  File "/app/handlers.py", line 89, in process_request
    timeout_value = int(config['timeout_ms'] / 1000)
  File "/app/config.py", line 156, in __getitem__
    if not hasattr(self.data, key):
AttributeError: 'NoneType' object has no attribute 'get'
    """,
    "deployment_id": "deploy-v2.0",
    "deployment_time": (new_time - timedelta(minutes=2)).isoformat(),
    "timestamp": new_time.isoformat(),
    "severity": "S1",
}

analysis = engine.analyze_incident(new_incident)
print(f"is_regression: {analysis['is_regression']}")
print(f"confidence: {analysis['regression_confidence']}")
print(f"signals: {analysis['regression_signals']}")
if "signal_fusion" in analysis:
    print(f"signal_fusion: {analysis['signal_fusion']}")
