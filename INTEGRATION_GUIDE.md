"""
Integration Guide — Final Intelligence Wiring Phase

This document explains how to integrate the new operational intelligence
components into the existing DevANT backend.

ARCHITECTURE OVERVIEW:

Old Flow:
  repo → unified_ingestor → pipeline.orchestrator → state manager → SSE

New Flow (ENHANCED):
  repo → unified_ingestor → core.orchestrator → enrichment → alerts → state → SSE
                           ↓
                        (clusters, deployments, temporal analysis)
                           ↓
                        LLM synthesis


INTEGRATION POINTS:

1. Backend Main.py Integration
   - Import: from orchestrator import UnifiedOperationalOrchestrator
   - Replace pipeline orchestrator call with new one
   - Adapt result format for existing state manager

2. Existing State Manager Compatibility
   - Existing: analyze_repository → run_id → get_run_snapshot
   - Enhanced: Still works, but results include new fields
   - Fields added: alerts, enriched_clusters, deployment_correlations, brief

3. Streaming Response Adaptation
   - Progress events now include: operational_alerts, context_attachments
   - Frontend can render alerts as they're generated
   - Enrichment happens in parallel with clustering

4. Frontend Integration
   - New alerts panel showing OperationalAlert objects
   - Context sidebar showing ContextAttachment objects
   - Deployment timeline view
   - Service topology visualization


STEP-BY-STEP INTEGRATION:

Step 1: Update imports in backend/main.py
───────────────────────────────────────
from orchestrator import UnifiedOperationalOrchestrator
from core.deployment_correlation import Deployment, DeploymentCorrelationEngine
from core.temporal_memory import TemporalMemoryEngine


Step 2: Replace orchestrator instantiation in analyze_repository_endpoint
────────────────────────────────────────────────────────────────────────
# OLD (remove):
# from pipeline.unified_orchestrator import UnifiedOrchestrator
# orch = UnifiedOrchestrator()

# NEW (add):
orch = UnifiedOperationalOrchestrator(config={
    'sentry_org': os.environ.get('SENTRY_ORG'),
    'datadog_site': os.environ.get('DATADOG_SITE', 'datadoghq.com'),
})


Step 3: Update orchestrator call to use new async API
─────────────────────────────────────────────────────
# OLD (sync in executor):
# result = orch.run(repo_url, run_id, progress_callback, local_path)

# NEW (async):
result = await orch.analyze_repository(
    repo_url=req.repo_url,
    services=extract_services(req.local_path),  # NEW
    since_minutes=60,
)


Step 4: Map new result format to existing state format
──────────────────────────────────────────────────────
# Existing state format expects:
# {
#     'analysis': {...},
#     'title': str,
#     'status': str,
#     ...
# }

# New format provides:
# {
#     'clusters': [...],
#     'enriched_clusters': [...],
#     'deployment_correlations': [...],
#     'operational_brief': {...},
#     'alerts': [...],
#     'metadata': {...}
# }

# ADAPTER function (see below) converts new→old format


Step 5: Update progress callbacks for new stages
────────────────────────────────────────────────
# Add new progress callbacks:
if result['alerts']:
    progress_callback('alerts_generated', {'count': len(result['alerts'])})

if result['enriched_clusters']:
    progress_callback('clusters_enriched', {
        'count': len(result['enriched_clusters']),
        'with_context': sum(1 for c in result['enriched_clusters'] 
                           if c['context_attachments'])
    })


Step 6: Update frontend to render new fields
─────────────────────────────────────────────
// In React components:
// - AlertPanel shows result.alerts
// - ContextSidebar shows context_attachments
// - DeploymentTimeline shows deployment_correlations
// - OperationalBrief shows narrative and status


ENVIRONMENT VARIABLES (ADD TO .env):
────────────────────────────────────

# Sentry Integration
SENTRY_AUTH_TOKEN=your_sentry_token
SENTRY_ORG=your_org_slug

# Datadog Integration
DATADOG_API_KEY=your_api_key
DATADOG_APP_KEY=your_app_key
DATADOG_SITE=datadoghq.com  # or datadoghq.eu

# Slack Integration
SLACK_BOT_TOKEN=xoxb-your-bot-token

# GitHub (already exists)
GITHUB_TOKEN=your_github_token


RESULT FORMAT ADAPTER:

def convert_orchestrator_result_to_state_format(
    orchestrator_result: Dict[str, Any],
) -> Dict[str, Any]:
    \"\"\"Convert new orchestrator format to existing state format.\"\"\"
    return {
        'analysis': {
            'title': orchestrator_result['operational_brief'].get('narrative', 'Analysis'),
            'root_cause': 'See alerts and clusters below',
            'affected_services': list(set(
                svc for cluster in orchestrator_result['enriched_clusters']
                for svc in cluster['affected_services']
            )),
            'severity': max((c['severity'] for c in orchestrator_result['enriched_clusters']),
                           default='S4'),
            'clusters': [asdict(c) for c in orchestrator_result['clusters']],
            'alerts': orchestrator_result['alerts'],
            'deployment_correlations': orchestrator_result['deployment_correlations'],
        },
        'title': orchestrator_result['operational_brief']['narrative'][:200],
        'status': orchestrator_result['operational_brief']['current_operational_status'],
        'timestamp': orchestrator_result['timestamp'],
        'metadata': orchestrator_result['metadata'],
    }


TESTING NEW COMPONENTS:

# Test Sentry connector:
python -c "
from connectors.sentry_connector import test_sentry_connection
import asyncio
asyncio.run(test_sentry_connection())
"

# Test Datadog connector:
python -c "
from connectors.datadog_connector import test_datadog_connection
import asyncio
asyncio.run(test_datadog_connection())
"

# Test Slack connector:
python -c "
from connectors.slack_connector import test_slack_connection
import asyncio
asyncio.run(test_slack_connection())
"

# Test full orchestrator:
python -c "
from orchestrator import UnifiedOperationalOrchestrator
import asyncio

async def test():
    orch = UnifiedOperationalOrchestrator()
    result = await orch.analyze_repository('owner/repo')
    print(f'Clusters: {len(result[\"clusters\"])}')
    print(f'Alerts: {len(result[\"alerts\"])}')

asyncio.run(test())
"


NEXT: Dynamic Synthesis with LLM

The operational brief is currently using string templates. To enhance with
real LLM reasoning:

1. Install: pip install groq (already available)
2. Create: backend/core/ai_synthesizer.py
3. Integration:
   - Call LLM with cluster data + context
   - Generate repository-specific analysis
   - Different reasoning for React vs Kubernetes vs ML repos


KEY FEATURES ENABLED:

✓ Multi-source error ingestion
✓ Intelligent root cause clustering
✓ Automatic context enrichment
✓ Deployment correlation
✓ Recurring pattern detection
✓ Temporal MTTR analysis
✓ Live operational alerts
✓ Repository-specific reasoning
✓ Suppression & deduplication
✓ Non-blocking error handling
"""
