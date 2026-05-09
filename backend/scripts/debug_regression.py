from datetime import datetime, timedelta
from memory.regression_engine import get_regression_engine

engine = get_regression_engine()
hist_time = datetime.utcnow() - timedelta(days=5)
hist_incident = {
    "incident_id": "redis-001-historical",
    "service": "cache-service",
    "error_signature": "redis_connection_refused",
    "sample_message": "Traceback... ConnectionError: Error 61 connecting to redis:6379. Connection refused.",
    "deployment_id": "deploy-v1.0",
    "deployment_time": (hist_time - timedelta(hours=1)).isoformat(),
    "timestamp": hist_time.isoformat(),
    "severity": "S2",
}
engine.record_resolution(incident=hist_incident, remediation="x", root_cause="y")

new_time = datetime.utcnow()
new_incident = {
    "incident_id": "redis-001-recurrence",
    "service": "cache-service",
    "error_signature": "redis_connection_refused",
    "sample_message": "Traceback... ConnectionError: Error 61 connecting to redis:6379. Connection refused.",
    "deployment_id": "deploy-v1.1",
    "deployment_time": (new_time - timedelta(hours=0.5)).isoformat(),
    "timestamp": new_time.isoformat(),
    "severity": "S2",
}
analysis = engine.analyze_incident(new_incident)
print('Analysis:', analysis)
# Direct call to detect_regression for inspection
from memory.regression_memory import RegressionMatch
match = engine.memory_graph.detect_regression(new_incident, threshold=0.5)
print('Direct detect_regression (th=0.5):', match.__dict__)
match2 = engine.memory_graph.detect_regression(new_incident, threshold=0.6)
print('Direct detect_regression (th=0.6):', match2.__dict__)
