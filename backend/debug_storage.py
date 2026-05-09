"""Debug what's stored in incident graph."""

from memory.regression_engine import get_regression_engine
from memory.stacktrace_normalizer import StacktraceNormalizer
from datetime import datetime, timedelta

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

# Check what was stored
stored_inc = engine.memory_graph.incidents[incident_id]
print(f"Stored normalized stacktrace:")
print(f"  {repr(stored_inc.normalized_stacktrace)[:200]}")

# Now test similarity directly
normalizer = StacktraceNormalizer()
sim, meta = normalizer.similarity(stacktrace_template, stored_inc.normalized_stacktrace)
print(f"\nDirect similarity test:")
print(f"  sim={sim}")
print(f"  meta={meta}")

# Check signatures
sig1 = normalizer.signature(stacktrace_template)
sig2 = normalizer.signature(stored_inc.normalized_stacktrace)
print(f"\nSignatures:")
print(f"  sig1={sig1}")
print(f"  sig2={sig2}")
