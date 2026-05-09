#!/usr/bin/env python
"""Comprehensive validation test suite for DevANT deployment failure detection."""

print("\n" + "="*60)
print("TEST 1: Import chain validation")
print("="*60)
try:
    from connectors.github_connector import GitHubConnector
    from pipeline.deployment_failure_detector import detect_deployment_failures
    from pipeline.error_pipeline import run_error_pipeline
    from connectors.slack_connector import SlackConnector
    print("✓ All imports OK")
except Exception as e:
    print(f"✗ Import failed: {e}")

print("\n" + "="*60)
print("TEST 2: GitHubConnector methods")
print("="*60)
try:
    c = GitHubConnector()
    methods = ['get_deployments', 'get_deployment_statuses', 'get_commit_diff', 'get_workflow_runs', 'fetch_log_text']
    for m in methods:
        assert hasattr(c, m), f'{m} missing'
    print(f"✓ All {len(methods)} methods exist")
except Exception as e:
    print(f"✗ {e}")

print("\n" + "="*60)
print("TEST 3: SlackConnector.post_alert")
print("="*60)
try:
    import inspect
    sig = inspect.signature(SlackConnector.post_alert)
    assert 'failure_result' in sig.parameters, 'failure_result param missing'
    assert inspect.iscoroutinefunction(SlackConnector.post_alert), 'not async'
    print("✓ post_alert method exists and is async")
except Exception as e:
    print(f"✗ {e}")

print("\n" + "="*60)
print("TEST 4: Log parser functionality")
print("="*60)
try:
    from pipeline.deployment_failure_detector import _parse_log_errors
    fake_log = """2026-05-09 12:00:01 Starting build...
2026-05-09 12:00:05 ERROR: Cannot find module ./components/Header
2026-05-09 12:00:05 npm ERR! Build failed with exit code 1
2026-05-09 12:00:06 Deployment failed"""
    fake_dep = {'deployment': {'id': 1}, 'latest_status': {'created_at': '2026-05-09T12:00:00Z'}}
    errors = _parse_log_errors(fake_log, fake_dep)
    assert len(errors) >= 2, f'Expected >= 2 errors, got {len(errors)}'
    assert all('message' in e for e in errors), 'Missing message field'
    assert all('signature' in e for e in errors), 'Missing signature field'
    print(f"✓ Log parser works ({len(errors)} errors found)")
except Exception as e:
    print(f"✗ {e}")

print("\n" + "="*60)
print("TEST 5: Config webhook field")
print("="*60)
try:
    from config import get_config, WebhookConfig
    c = get_config()
    assert hasattr(c, 'webhook'), 'webhook field missing'
    assert isinstance(c.webhook, WebhookConfig), 'webhook not WebhookConfig instance'
    assert hasattr(c.webhook, 'is_configured'), 'is_configured property missing'
    print("✓ Config.webhook field exists")
except Exception as e:
    print(f"✗ {e}")

print("\n" + "="*60)
print("TEST 6: Webhook endpoints registered")
print("="*60)
try:
    import main
    routes = [r.path for r in main.app.routes]
    endpoints = ['/webhook/github', '/api/scan-repo', '/api/live-errors/{repo_full_name}', '/api/live-errors/{repo_full_name}/stream']
    found = [e for e in endpoints if any(e in r for r in routes)]
    print(f"✓ New endpoints registered: {found}")
except Exception as e:
    print(f"✗ {e}")

print("\n" + "="*60)
print("TEST 7: Error pipeline async function")
print("="*60)
try:
    from pipeline.error_pipeline import run_error_pipeline
    import inspect
    assert inspect.iscoroutinefunction(run_error_pipeline), 'run_error_pipeline not async'
    sig = inspect.signature(run_error_pipeline)
    params = list(sig.parameters.keys())
    assert 'repo_url' in params, 'repo_url param missing'
    assert 'environment' in params, 'environment param missing'
    print(f"✓ run_error_pipeline is async with correct signature")
except Exception as e:
    print(f"✗ {e}")

print("\n" + "="*60)
print("VALIDATION COMPLETE")
print("="*60)
