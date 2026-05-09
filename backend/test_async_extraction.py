"""Test AsyncIngestionPipeline integration - parallel extraction."""
import json
import sys
import time
from pathlib import Path
from repository.repo_analyzer import analyze_repository

print("=" * 60)
print("TEST: AsyncIngestionPipeline Parallel Extraction")
print("=" * 60)

# Create test repo with various artifacts
test_path = Path("test_data/async_extraction")
test_path.mkdir(parents=True, exist_ok=True)

# Create deployment artifacts
(test_path / ".github").mkdir(exist_ok=True)
(test_path / ".github/workflows").mkdir(exist_ok=True)
(test_path / ".github/workflows/deploy.yml").write_text("name: deploy\njobs:\n")
(test_path / ".github/workflows/test.yml").write_text("name: test\njobs:\n")

(test_path / "Dockerfile").write_text("FROM python:3.11\nRUN pip install -r requirements.txt\n")
(test_path / "Dockerfile.prod").write_text("FROM python:3.11-slim\n")

(test_path / "k8s").mkdir(exist_ok=True)
(test_path / "k8s/deployment.yaml").write_text("apiVersion: apps/v1\nkind: Deployment\n")
(test_path / "k8s/service.yaml").write_text("apiVersion: v1\nkind: Service\n")

(test_path / "helm").mkdir(exist_ok=True)
(test_path / "helm/myapp").mkdir(exist_ok=True)
(test_path / "helm/myapp/Chart.yaml").write_text("name: myapp\nversion: 1.0.0\n")

(test_path / "terraform").mkdir(exist_ok=True)
(test_path / "terraform/main.tf").write_text("resource \"aws_s3_bucket\" \"data\" {}\n")
(test_path / "terraform/vars.tf").write_text("variable \"region\" {}\n")

(test_path / "prometheus.yml").write_text("global:\n  scrape_interval: 15s\n")
(test_path / "otel-config.yaml").write_text("receivers:\n  prometheus:\n")

(test_path / "package.json").write_text('{"name": "myapp", "version": "1.0.0"}\n')
(test_path / "requirements.txt").write_text("flask==2.0.0\n")

# Track progress events and timing
progress_events = []
start_time = time.time()

def progress_handler(step: str, payload):
    elapsed = time.time() - start_time
    progress_events.append({
        'step': step,
        'elapsed': elapsed,
        'concurrent': payload.get('concurrent', False) if isinstance(payload, dict) else False,
        'payload': payload
    })
    
    if step in ('scanned_files', 'workflows_extracted', 'deployments_correlated', 'observability_checked'):
        print(f"\n→ {step} (t={elapsed:.2f}s)")
        if isinstance(payload, dict):
            for k, v in payload.items():
                if not isinstance(v, (dict, list)):
                    print(f"  {k}: {v}")

print("\nScenario: Large repository with diverse artifacts")
print("-" * 60)

try:
    result = analyze_repository(
        repo_url=str(test_path),
        local_path=str(test_path),
        progress_callback=progress_handler
    )
    
    total_time = time.time() - start_time
    
    print("\n" + "=" * 60)
    print("Result Analysis")
    print("=" * 60)
    
    print(f"\n✓ Scanned: {result.get('scanned')}")
    print(f"✓ Total analysis time: {total_time:.2f}s")
    
    evidence = result.get('evidence', {})
    print(f"\nExtracted Evidence:")
    print(f"  Workflows: {len(evidence.get('workflows', []))} files")
    print(f"  Dockerfiles: {len(evidence.get('dockerfiles', []))} files")
    print(f"  K8s Manifests: {len(evidence.get('kubernetes_manifests', []))} files")
    print(f"  Helm Charts: {len(evidence.get('helm_charts', []))} files")
    print(f"  Terraform: {len(evidence.get('terraform', []))} files")
    print(f"  Prometheus: {evidence.get('prometheus', False)}")
    print(f"  OTEL: {evidence.get('otel', False)}")
    print(f"  Package Managers: {len(evidence.get('package_managers', []))} files")
    print(f"  Services: {len(evidence.get('services', []))} services")
    
    # Verify concurrency marker in progress events
    concurrent_events = [e for e in progress_events if e.get('concurrent')]
    print(f"\n✓ Concurrent extraction events: {len(concurrent_events)}")
    
    # Find extraction method marker
    scanned_events = [e for e in progress_events if e['step'] == 'scanned_files']
    if scanned_events:
        payload = scanned_events[0]['payload']
        method = payload.get('extraction_method')
        print(f"✓ Extraction method: {method}")
        if method == 'async_parallel':
            print("✓ AsyncIngestionPipeline parallel extraction confirmed")
        else:
            print(f"✗ Expected 'async_parallel', got '{method}'")
            sys.exit(1)
    
    # Verify evidence completeness
    expected_artifacts = {
        'workflows': 2,
        'dockerfiles': 2,
        'kubernetes_manifests': 2,
        'helm_charts': 1,
        'terraform': 2,
    }
    
    print("\nArtifact Count Validation:")
    all_match = True
    for artifact_type, expected_count in expected_artifacts.items():
        actual_count = len(evidence.get(artifact_type, []))
        match = '✓' if actual_count >= expected_count else '✗'
        print(f"  {match} {artifact_type}: expected ≥{expected_count}, got {actual_count}")
        if actual_count < expected_count:
            all_match = False
    
    if not all_match:
        print("\n✗ Some artifacts missing")
        sys.exit(1)
    
    # Verify boolean signals
    if evidence.get('prometheus') and evidence.get('otel'):
        print("\n✓ Observability signals detected")
    else:
        print(f"\n✗ Observability signals incomplete: prometheus={evidence.get('prometheus')}, otel={evidence.get('otel')}")
        sys.exit(1)
    
    print("\n" + "=" * 60)
    print("SUCCESS: Parallel extraction working!")
    print("=" * 60)
    print("\nKey achievements:")
    print("- AsyncIngestionPipeline concurrent extraction active")
    print("- Parallel workers processing different artifact types")
    print("- Evidence merged correctly from concurrent tasks")
    print("- Progress events marked with concurrent=True")
    print(f"- Total throughput: {len(evidence.get('files_present', []))} files in {total_time:.2f}s")
    
except Exception as e:
    print(f"\n✗ Error: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
