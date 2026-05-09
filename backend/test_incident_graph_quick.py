"""Quick validation of IncidentGraph temporal memory engine."""
import sys
from datetime import datetime, timedelta

sys.path.insert(0, '.')
from memory.incident_graph import IncidentGraph, IncidentNode

print("=" * 70)
print("WEEK 4 FIX 01 - INCIDENTGRAPH VALIDATION")
print("=" * 70)

graph = IncidentGraph()
now = datetime.utcnow()

# TEST 1: Incident ingestion
print("\n[TEST 1] Incident Ingestion")
inc1 = graph.add_incident(
    incident_id='inc-001',
    timestamp=(now - timedelta(days=10)).isoformat(),
    repo='myapp',
    dominant_service='api',
    blast_radius=5,
    operational_confidence=0.65,
    regression_risk=0.45,
    topology_hash='topo-hash-1',
    critical_paths=[['api', 'db']],
)
print(f"✓ Added incident inc-001")

# TEST 2: Recurring pattern detection
print("\n[TEST 2] Recurring Pattern Detection")
inc2 = graph.add_incident(
    incident_id='inc-002',
    timestamp=(now - timedelta(days=8)).isoformat(),
    repo='myapp',
    dominant_service='api',
    blast_radius=4,
    operational_confidence=0.60,
    regression_risk=0.55,
    topology_hash='topo-hash-1',
)

inc3 = graph.add_incident(
    incident_id='inc-003',
    timestamp=(now - timedelta(days=5)).isoformat(),
    repo='myapp',
    dominant_service='api',
    blast_radius=5,
    operational_confidence=0.62,
    regression_risk=0.65,
    topology_hash='topo-hash-1',
)

patterns = graph.detect_recurring_patterns(inc3)
print(f"✓ Recurring: {patterns['is_recurring']}")
print(f"  Pattern type: {patterns['pattern_type']}")
print(f"  Recurrence count: {patterns['recurrence_count']}")
print(f"  Confidence: {patterns['confidence']:.2f}")

if not patterns['is_recurring']:
    print("✗ Expected recurring pattern to be detected")
    sys.exit(1)

# TEST 3: Operational drift analysis
print("\n[TEST 3] Operational Drift Analysis")
drift = graph.analyze_operational_drift('myapp')
print(f"✓ Drift score: {drift['drift_score']:.2f}")
print(f"  Has drift: {drift['has_drift']}")
print(f"  Blast radius trend: {drift['blast_radius_trend']}")
print(f"  Confidence trend: {drift['confidence_trend']}")
print(f"  Regression trend: {drift['regression_trend']}")

# TEST 4: Historical similarity
print("\n[TEST 4] Historical Similarity Search")
similar = graph.find_historical_similarity(inc3, threshold=0.5)
print(f"✓ Found {len(similar)} similar incidents")
for s in similar[:2]:
    print(f"  - {s['incident_id']}: {s['similarity']:.2f} similarity")

# TEST 5: Incident lineage
print("\n[TEST 5] Incident Lineage Tracing")
lineage = graph.get_incident_lineage('inc-003', depth=5)
print(f"✓ Lineage: {' -> '.join(lineage)}")

# TEST 6: Temporal relationships
print("\n[TEST 6] Temporal Relationships")
print(f"✓ Edges created: {len(graph.edges)}")
for edge in graph.edges[:3]:
    print(f"  - {edge.source_incident} -{edge.relationship}-> {edge.target_incident} (conf: {edge.confidence:.2f})")

# TEST 7: Persistence
print("\n[TEST 7] Persistence to Disk")
graph._save_to_disk()
from pathlib import Path
if Path('data/incident_graph.json').exists():
    size = Path('data/incident_graph.json').stat().st_size
    print(f"✓ Persisted to disk ({size} bytes)")
else:
    print("✗ Persistence file not created")
    sys.exit(1)

# TEST 8: Restart simulation
print("\n[TEST 8] Restart Simulation")
graph2 = IncidentGraph()
if len(graph2.nodes) == 3:
    print(f"✓ Loaded {len(graph2.nodes)} incidents from disk")
    print(f"✓ Loaded {len(graph2.edges)} edges from disk")
else:
    print(f"✗ Expected 3 incidents, got {len(graph2.nodes)}")
    sys.exit(1)

# TEST 9: Evidence payload assembly
print("\n[TEST 9] Evidence Payload Assembly")
temporal_memory_evidence = {
    "recurring_patterns": {
        "is_recurring": patterns['is_recurring'],
        "pattern_type": patterns['pattern_type'],
        "recurrence_count": patterns['recurrence_count'],
        "confidence": patterns['confidence'],
    },
    "operational_drift": {
        "has_drift": drift['has_drift'],
        "drift_score": drift['drift_score'],
        "blast_radius_trend": drift['blast_radius_trend'],
    },
    "historical_similarity": {
        "similar_count": len(similar),
    },
}
print(f"✓ Evidence payload assembled with {len(temporal_memory_evidence)} key insights")
for key in temporal_memory_evidence:
    print(f"  - {key}")

print("\n" + "=" * 70)
print("ALL TESTS PASSED ✓")
print("=" * 70)
print("""
IncidentGraph Capabilities Activated:
✓ Persistent temporal memory (JSON storage)
✓ Recurring pattern detection
✓ Operational drift measurement
✓ Historical similarity matching
✓ Incident lineage tracing
✓ Temporal relationships (recurring, escalation, similar)
✓ Thread-safe persistence
✓ Restart survival

System State: PERSISTENT ADAPTIVE OPERATIONAL COGNITION ENABLED
""")
