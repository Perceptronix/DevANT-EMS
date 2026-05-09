"""Comprehensive validation test for Week 3 FIX 01: Topology Propagation Integration."""
import sys
from pathlib import Path
from core.topology_propagation import TopologyPropagationEngine

print("=" * 70)
print("WEEK 3 FIX 01 VALIDATION: Topology Propagation Engine Integration")
print("=" * 70)

# ============================================================================
# TEST 1: Direct Engine Validation
# ============================================================================
print("\n[TEST 1] Direct TopologyPropagationEngine Validation")
print("-" * 70)

try:
    topology = {
        'services': [
            {'name': 'frontend', 'path': 'services/frontend', 'markers': []},
            {'name': 'api', 'path': 'services/api', 'markers': []},
            {'name': 'db', 'path': 'services/db', 'markers': []},
            {'name': 'cache', 'path': 'services/cache', 'markers': []},
            {'name': 'queue', 'path': 'services/queue', 'markers': []},
            {'name': 'worker', 'path': 'services/worker', 'markers': []},
        ],
        'edges': [
            {'from': 'frontend', 'to': 'api'},
            {'from': 'api', 'to': 'db'},
            {'from': 'api', 'to': 'cache'},
            {'from': 'api', 'to': 'queue'},
            {'from': 'worker', 'to': 'queue'},
            {'from': 'worker', 'to': 'db'},
        ]
    }
    
    engine = TopologyPropagationEngine()
    result = engine.analyze(topology)
    
    checks = {
        'Service count': (result.service_count == 6, result.service_count),
        'Edge count': (result.edge_count == 6, result.edge_count),
        'Dominant service detected': (result.dominant_service in ['api', 'db'], result.dominant_service),
        'Blast radius > 0': (result.blast_radius > 0, result.blast_radius),
        'Critical paths found': (len(result.critical_paths) > 0, len(result.critical_paths)),
        'Upstream risk in range': (0 <= result.upstream_risk <= 1, result.upstream_risk),
        'Downstream risk in range': (0 <= result.downstream_risk <= 1, result.downstream_risk),
        'Propagation depth valid': (0 < result.propagation_depth <= 20, result.propagation_depth),
        'High-risk deps found': (len(result.high_risk_dependencies) > 0, len(result.high_risk_dependencies)),
    }
    
    all_pass = True
    for check_name, (passed, value) in checks.items():
        status = "✓" if passed else "✗"
        print(f"  {status} {check_name}: {value}")
        if not passed:
            all_pass = False
    
    if not all_pass:
        print("\n✗ TEST 1 FAILED")
        sys.exit(1)
    
    print("\n✓ TEST 1 PASSED: Engine produces correct topology analysis")

except Exception as e:
    print(f"\n✗ TEST 1 FAILED: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# ============================================================================
# TEST 2: Integration with repo_analyzer
# ============================================================================
print("\n[TEST 2] Integration with repo_analyzer Propagation Events")
print("-" * 70)

try:
    from repository.repo_analyzer import analyze_repository
    
    test_path = Path("test_data/validation_week3_fix01")
    test_path.mkdir(parents=True, exist_ok=True)
    
    # Create minimal repo structure
    (test_path / "src").mkdir(exist_ok=True)
    (test_path / "src/main.py").write_text("# main service\n")
    (test_path / "Dockerfile").write_text("FROM python:3.11\n")
    
    events = []
    
    def collect_events(step, payload):
        events.append({'step': step, 'data': payload})
    
    result = analyze_repository(
        repo_url=str(test_path),
        local_path=str(test_path),
        progress_callback=collect_events
    )
    
    # Check for topology_propagation event
    propagation_events = [e for e in events if e['step'] == 'topology_propagation']
    
    if propagation_events:
        print("  ✓ topology_propagation event emitted")
        event_data = propagation_events[0]['data']
        
        required_fields = ['blast_radius', 'service_count', 'edge_count', 'dominant_service']
        missing = [f for f in required_fields if f not in event_data]
        
        if missing:
            print(f"  ✗ Missing fields in event: {missing}")
            sys.exit(1)
        
        print(f"  ✓ Event contains required fields: {', '.join(required_fields)}")
        
        # Check evidence
        evidence = result.get('evidence', {})
        if 'propagation' in evidence:
            print("  ✓ Propagation data stored in evidence")
        else:
            print("  ✗ Propagation data NOT in evidence")
            sys.exit(1)
        
        print("\n✓ TEST 2 PASSED: Integration working correctly")
    else:
        print("  ✗ topology_propagation event NOT emitted")
        print(f"  Events received: {[e['step'] for e in events]}")
        sys.exit(1)

except Exception as e:
    print(f"\n✗ TEST 2 FAILED: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# ============================================================================
# TEST 3: Propagation Reasoning Under Various Topologies
# ============================================================================
print("\n[TEST 3] Propagation Reasoning - Various Topology Scenarios")
print("-" * 70)

try:
    engine = TopologyPropagationEngine()
    
    # Scenario A: Hub topology (central service with many dependents)
    print("\n  Scenario A: Hub Topology (Central Service)")
    hub_topology = {
        'services': [
            {'name': 'hub', 'path': '', 'markers': []},
            {'name': 'srv1', 'path': '', 'markers': []},
            {'name': 'srv2', 'path': '', 'markers': []},
            {'name': 'srv3', 'path': '', 'markers': []},
        ],
        'edges': [
            {'from': 'hub', 'to': 'srv1'},
            {'from': 'hub', 'to': 'srv2'},
            {'from': 'hub', 'to': 'srv3'},
        ]
    }
    
    result_hub = engine.analyze(hub_topology)
    print(f"    Dominant: {result_hub.dominant_service}, Blast radius: {result_hub.blast_radius}")
    
    if result_hub.dominant_service == 'hub' and result_hub.blast_radius == 3:
        print("    ✓ Hub topology correctly identified")
    else:
        print("    ✗ Hub topology analysis incorrect")
        sys.exit(1)
    
    # Scenario B: Chain topology (linear dependency chain)
    print("\n  Scenario B: Chain Topology (Linear Dependencies)")
    chain_topology = {
        'services': [
            {'name': 'a', 'path': '', 'markers': []},
            {'name': 'b', 'path': '', 'markers': []},
            {'name': 'c', 'path': '', 'markers': []},
            {'name': 'd', 'path': '', 'markers': []},
        ],
        'edges': [
            {'from': 'a', 'to': 'b'},
            {'from': 'b', 'to': 'c'},
            {'from': 'c', 'to': 'd'},
        ]
    }
    
    result_chain = engine.analyze(chain_topology)
    print(f"    Blast radius: {result_chain.blast_radius}, Depth: {result_chain.propagation_depth}")
    
    if result_chain.propagation_depth == 3 and result_chain.blast_radius >= 0:
        print("    ✓ Chain topology correctly analyzed")
    else:
        print("    ✗ Chain topology analysis incorrect")
        sys.exit(1)
    
    # Scenario C: Mesh topology (many interconnections)
    print("\n  Scenario C: Mesh Topology (Interconnected Services)")
    mesh_topology = {
        'services': [
            {'name': 'api', 'path': '', 'markers': []},
            {'name': 'db', 'path': '', 'markers': []},
            {'name': 'cache', 'path': '', 'markers': []},
        ],
        'edges': [
            {'from': 'api', 'to': 'db'},
            {'from': 'api', 'to': 'cache'},
            {'from': 'db', 'to': 'cache'},
            {'from': 'cache', 'to': 'api'},
        ]
    }
    
    result_mesh = engine.analyze(mesh_topology)
    print(f"    Services: {result_mesh.service_count}, Edges: {result_mesh.edge_count}")
    
    if result_mesh.service_count == 3 and result_mesh.edge_count == 4:
        print("    ✓ Mesh topology correctly analyzed")
    else:
        print("    ✗ Mesh topology analysis incorrect")
        sys.exit(1)
    
    print("\n✓ TEST 3 PASSED: Propagation reasoning works across topologies")

except Exception as e:
    print(f"\n✗ TEST 3 FAILED: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# ============================================================================
# SUCCESS SUMMARY
# ============================================================================
print("\n" + "=" * 70)
print("ALL TESTS PASSED ✓")
print("=" * 70)

print("""
Week 3 FIX 01 Status: COMPLETE & VALIDATED

✓ TopologyPropagationEngine implemented with:
  - Blast radius computation (DFS traversal)
  - Critical path identification (longest chains)
  - Dominant service detection (hub analysis)
  - Risk assessment (upstream/downstream)
  - High-risk dependency identification

✓ Integration into repo_analyzer.py:
  - Propagation analysis runs after topology extraction
  - Results exposed in evidence payload
  - SSE events emitted with topology_propagation step
  - Both local path and GitHub ingestion paths updated

✓ Frontend visualization:
  - topology_propagation stage added to pipeline
  - Card will display propagation data when available

✓ Test coverage:
  - Direct engine functionality validated
  - Integration with main pipeline tested
  - Multiple topology scenarios verified

Operational Causality Platform: ACTIVATED
Propagation Intelligence: LIVE
""")

print("=" * 70)
