"""Test topology propagation engine integration."""
import json
import sys
from pathlib import Path
from repository.repo_analyzer import analyze_repository

print("=" * 60)
print("TEST: Topology Propagation Engine Integration")
print("=" * 60)

# For now, test the propagation engine directly with a realistic topology
from core.topology_propagation import TopologyPropagationEngine

print("\nScenario: Multi-service topology with dependencies")
print("-" * 60)

try:
    # Create realistic topology with service-to-service edges
    topology = {
        'services': [
            {'name': 'api', 'path': 'src/api', 'markers': ['python', 'fastapi']},
            {'name': 'db', 'path': 'src/db', 'markers': ['postgres']},
            {'name': 'cache', 'path': 'src/cache', 'markers': ['redis']},
            {'name': 'web', 'path': 'src/web', 'markers': ['nodejs', 'react']},
            {'name': 'auth', 'path': 'src/auth', 'markers': ['python', 'jwt']},
        ],
        'edges': [
            # Real service dependencies
            {'from': 'web', 'to': 'api'},    # web calls api
            {'from': 'api', 'to': 'db'},     # api calls db
            {'from': 'api', 'to': 'cache'},  # api calls cache
            {'from': 'api', 'to': 'auth'},   # api calls auth
            {'from': 'auth', 'to': 'db'},    # auth calls db
        ]
    }
    
    # Test propagation engine
    propagation_engine = TopologyPropagationEngine()
    propagation_result = propagation_engine.analyze(topology_graph=topology)
    
    print("\n" + "=" * 60)
    print("Result Analysis")
    print("=" * 60)
    
    print("\nTopology Information:")
    print(f"  Services: {propagation_result.service_count}")
    print(f"  Dependencies: {propagation_result.edge_count}")
    print(f"  Max depth: {propagation_result.propagation_depth}")
    
    print("\nPropagation Analysis:")
    print(f"  Blast radius: {propagation_result.blast_radius} services")
    print(f"  Dominant service: {propagation_result.dominant_service}")
    print(f"  Upstream risk: {propagation_result.upstream_risk:.2f}")
    print(f"  Downstream risk: {propagation_result.downstream_risk:.2f}")
    
    critical_paths = propagation_result.critical_paths
    print(f"\nCritical Dependency Paths ({len(critical_paths)}):")
    for i, path in enumerate(critical_paths[:5]):
        print(f"  Path {i+1}: {' → '.join(path)}")
    
    high_risk = propagation_result.high_risk_dependencies
    print(f"\nHigh-Risk Dependencies ({len(high_risk)}):")
    for dep in high_risk[:5]:
        print(f"  {dep['from']} → {dep['to']} (risk: {dep['risk']:.2f}, fanout: {dep['fanout']})")
    
    # Verify results
    checks = [
        ("Service count correct", propagation_result.service_count == 5),
        ("Dependency count correct", propagation_result.edge_count == 5),
        ("Dominant service detected", propagation_result.dominant_service in ['api', 'db']),
        ("Blast radius computed", propagation_result.blast_radius > 0),
        ("Critical paths found", len(critical_paths) > 0),
        ("Risk assessment valid", 0 <= propagation_result.upstream_risk <= 1.0),
        ("Downstream risk valid", 0 <= propagation_result.downstream_risk <= 1.0),
        ("High-risk deps identified", len(high_risk) > 0),
    ]
    
    print("\n" + "=" * 60)
    print("Validation Results")
    print("=" * 60)
    
    all_passed = True
    for check_name, passed in checks:
        status = "✓" if passed else "✗"
        print(f"{status} {check_name}")
        if not passed:
            all_passed = False
    
    if all_passed:
        print("\n" + "=" * 60)
        print("SUCCESS: Topology propagation analysis working!")
        print("=" * 60)
        print("\nCapabilities:")
        print("- Service topology extraction")
        print("- Dependency graph analysis")
        print("- Blast radius computation")
        print("- Critical path identification")
        print("- Risk propagation reasoning")
    else:
        print("\n✗ Some validations failed")
        sys.exit(1)
    
    # Now test integration with repo_analyzer
    print("\n" + "=" * 60)
    print("Testing Integration with repo_analyzer")
    print("=" * 60)
    
    # Create test repo
    test_path = Path("test_data/topology_propagation_integration")
    test_path.mkdir(parents=True, exist_ok=True)
    
    (test_path / "api").mkdir(exist_ok=True)
    (test_path / "api/Dockerfile").write_text("FROM python:3.11\n")
    
    (test_path / "web").mkdir(exist_ok=True)
    (test_path / "web/package.json").write_text('{"name": "web"}\n')
    
    progress_events = []
    
    def progress_handler(step: str, payload):
        progress_events.append({'step': step, 'payload': payload})
        if step == 'topology_propagation':
            print(f"→ Propagation event: blast_radius={payload.get('blast_radius')}, services={payload.get('service_count')}")
    
    result = analyze_repository(
        repo_url=str(test_path),
        local_path=str(test_path),
        progress_callback=progress_handler
    )
    
    # Check propagation event
    prop_events = [e for e in progress_events if e['step'] == 'topology_propagation']
    if prop_events:
        print("✓ Propagation event emitted via SSE")
    else:
        print("✗ Propagation event NOT emitted")
        sys.exit(1)
    
    # Check evidence
    evidence = result.get('evidence', {})
    if 'propagation' in evidence:
        print("✓ Propagation data in evidence")
    else:
        print("✗ Propagation data NOT in evidence")
        sys.exit(1)
    
    print("\n" + "=" * 60)
    print("SUCCESS: Full integration working!")
    print("=" * 60)
    
except Exception as e:
    print(f"\n✗ Error: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
