# OTLP HTTP Exporters

This guide shows how to configure OpenTelemetry OTLP HTTP exporters in JavaScript, Node.js, and Python applications so they can send logs to DevANT.

DevANT exposes an OTLP ingest endpoint at:

```text
/api/v1/ingest/otlp
```

The endpoint accepts OTLP log payloads over HTTP and can process either JSON or protobuf content. For best compatibility, use the default OTLP HTTP protobuf exporter format.

## Target Endpoint

Use the full URL for your DevANT deployment:

```text
https://your-devant-host/api/v1/ingest/otlp
```

For local development:

```text
http://127.0.0.1:8000/api/v1/ingest/otlp
```

## General Settings

These environment variables are a good default starting point for all exporters:

```bash
OTEL_SERVICE_NAME=my-service
OTEL_EXPORTER_OTLP_ENDPOINT=https://your-devant-host/api/v1/ingest/otlp
OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf
OTEL_RESOURCE_ATTRIBUTES=deployment.environment=production,service.version=1.0.0
```

If your SDK supports signal-specific endpoints, you can also set:

```bash
OTEL_EXPORTER_OTLP_LOGS_ENDPOINT=https://your-devant-host/api/v1/ingest/otlp
```

## JavaScript

Use this approach for browser-based JavaScript applications that emit logs directly to DevANT or through a trusted proxy.

### Install

```bash
npm install @opentelemetry/api @opentelemetry/sdk-logs @opentelemetry/exporter-logs-otlp-http
```

### Configure

```javascript
import { LoggerProvider, BatchLogRecordProcessor } from '@opentelemetry/sdk-logs';
import { OTLPLogExporter } from '@opentelemetry/exporter-logs-otlp-http';

const exporter = new OTLPLogExporter({
  url: 'https://your-devant-host/api/v1/ingest/otlp',
});

const loggerProvider = new LoggerProvider();
loggerProvider.addLogRecordProcessor(new BatchLogRecordProcessor(exporter));

const logger = loggerProvider.getLogger('web-app');

logger.emit({
  severityNumber: 17,
  severityText: 'ERROR',
  body: 'TypeError: Cannot read properties of undefined (reading \'map\')',
  attributes: {
    'service.name': 'web-frontend',
    'deployment.environment': 'production',
    'exception.type': 'TypeError',
  },
});
```

### Browser Notes

- If the browser cannot reach DevANT directly, send OTLP logs to your backend and forward them from there.
- Ensure CORS is allowed if you send directly from a browser application.

## Node.js

Use this for server-side JavaScript services and API backends.

### Install

```bash
npm install @opentelemetry/api @opentelemetry/sdk-node @opentelemetry/sdk-logs @opentelemetry/exporter-logs-otlp-http @opentelemetry/auto-instrumentations-node
```

### Configure

```javascript
import { NodeSDK } from '@opentelemetry/sdk-node';
import { logs } from '@opentelemetry/api-logs';
import { OTLPLogExporter } from '@opentelemetry/exporter-logs-otlp-http';
import { BatchLogRecordProcessor, LoggerProvider } from '@opentelemetry/sdk-logs';
import { getNodeAutoInstrumentations } from '@opentelemetry/auto-instrumentations-node';

const logExporter = new OTLPLogExporter({
  url: 'https://your-devant-host/api/v1/ingest/otlp',
});

const loggerProvider = new LoggerProvider();
loggerProvider.addLogRecordProcessor(new BatchLogRecordProcessor(logExporter));
logs.setGlobalLoggerProvider(loggerProvider);

const sdk = new NodeSDK({
  instrumentations: [getNodeAutoInstrumentations()],
});

sdk.start();

const logger = logs.getLogger('orders-api');
logger.emit({
  severityNumber: 17,
  severityText: 'ERROR',
  body: 'Unhandled TypeError in request handler',
  attributes: {
    'service.name': 'orders-api',
    'deployment.environment': 'production',
    'http.route': '/api/orders',
    'exception.type': 'TypeError',
  },
});
```

### Environment Variables

You can also configure the exporter entirely with environment variables:

```bash
OTEL_EXPORTER_OTLP_ENDPOINT=https://your-devant-host/api/v1/ingest/otlp
OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf
OTEL_SERVICE_NAME=orders-api
OTEL_RESOURCE_ATTRIBUTES=deployment.environment=production
```

## Python

Use this for Python applications, workers, and services.

### Install

```bash
pip install opentelemetry-api opentelemetry-sdk opentelemetry-exporter-otlp-proto-http opentelemetry-semantic-conventions
```

### Configure

```python
from opentelemetry import _logs
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter

exporter = OTLPLogExporter(
    endpoint="https://your-devant-host/api/v1/ingest/otlp",
)

logger_provider = LoggerProvider()
logger_provider.add_log_record_processor(BatchLogRecordProcessor(exporter))
_logs.set_logger_provider(logger_provider)

logger = _logs.get_logger("billing-worker")
logger.emit(
    severity_number=17,
    severity_text="ERROR",
    body="TypeError: Cannot read properties of undefined (reading 'map')",
    attributes={
        "service.name": "billing-worker",
        "deployment.environment": "production",
        "exception.type": "TypeError",
    },
)
```

### Environment Variables

```bash
OTEL_EXPORTER_OTLP_ENDPOINT=https://your-devant-host/api/v1/ingest/otlp
OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf
OTEL_SERVICE_NAME=billing-worker
OTEL_RESOURCE_ATTRIBUTES=deployment.environment=production
```

## What DevANT Expects

DevANT maps OTLP log fields into its raw event schema:

- `service.name` → `service`
- `deployment.environment` → `environment`
- log body → `message`
- exception or stack trace fields → `stack_trace`
- all remaining attributes → `extra_metadata`

## Validation

To verify the integration, send a sample log and confirm the ingest endpoint returns success:

```bash
curl -X POST https://your-devant-host/api/v1/ingest/otlp \
  -H "content-type: application/json" \
  --data @sample_otlp_logs.json
```

The response should include:

```json
{
  "success": true,
  "records_received": 1,
  "records_saved": 1,
  "pipeline_triggered": true
}
```

## Troubleshooting

### HTTP 400

This usually means the payload is not valid OTLP JSON/protobuf or the `content-type` does not match the body.

### HTTP 500

This means DevANT could parse the payload, but a downstream processing step failed during normalization, persistence, or analysis.

### No records saved

- Confirm `OTEL_EXPORTER_OTLP_ENDPOINT` points to `/api/v1/ingest/otlp`
- Confirm the app is sending log records, not only traces or metrics
- Confirm the payload includes `resourceLogs` and `scopeLogs` when using JSON
