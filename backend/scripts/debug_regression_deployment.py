from datetime import datetime, timedelta
from memory.regression_engine import get_regression_engine

engine = get_regression_engine()
# Historical incident 30 days ago
hist_time = datetime.utcnow() - timedelta(days=30)
hist_incident = {
    "incident_id": "config-error-001",
    "service": "api-server",
    "error_signature": "config_parsing_error",
    "sample_message": "Traceback... AttributeError: 'NoneType' object has no attribute 'get'",
    "deployment_id": "deploy-v1.0",
    "deployment_time": (hist_time - timedelta(minutes=5)).isoformat(),
    "timestamp": hist_time.isoformat(),
    "severity": "S1",
}
engine.record_resolution(incident=hist_incident, remediation="x", root_cause="config")

# New incident after deployment
new_time = datetime.utcnow()
new_incident = {
    "incident_id": "config-error-recurrence",
    "service": "api-server",
    "error_signature": "config_parsing_error",
    "sample_message": "Traceback... AttributeError: 'NoneType' object has no attribute 'get'",
    "deployment_id": "deploy-v2.0",
    "deployment_time": (new_time - timedelta(minutes=2)).isoformat(),
    "timestamp": new_time.isoformat(),
    "severity": "S1",
}
analysis = engine.analyze_incident(new_incident)
print('Analysis:', analysis)
match = engine.memory_graph.detect_regression({
    "service": new_incident['service'],
    "stacktrace": new_incident['sample_message'],
    "deployment_id": new_incident['deployment_id'],
    "deployment_time": new_incident['deployment_time'],
    "timestamp": new_incident['timestamp'],
}, threshold=0.5)
print('Stored normalized:', engine.memory_graph.incidents.get('config-error-001').normalized_stacktrace)
print('Direct match:', match.__dict__)
