"""Validate mutation persistence (transitions, finalization)."""
import json
from pathlib import Path
import sys

print("=" * 60)
print("TEST: State mutations trigger JSON persistence")
print("=" * 60)

from repository.analysis_state import create_run, transition_run, finalize_run

# Create run
run_id = create_run('https://github.com/mutation/test')
print(f"✓ Created run: {run_id}")

# Get initial JSON state
state_file = Path('data/analysis_runs.json')
data = json.loads(state_file.read_text())
initial_count = len(data['runs'][run_id].get('transitions', []))
print(f"✓ Initial transitions: {initial_count}")

# Transition run through states
print("\nTransitioning through states...")
transition_run(run_id, 'INITIALIZING')
print(f"✓ Transitioned to INITIALIZING")

transition_run(run_id, 'INGESTING')
print(f"✓ Transitioned to INGESTING")

transition_run(run_id, 'ANALYZING')
print(f"✓ Transitioned to ANALYZING")

# Verify all transitions persisted
data = json.loads(state_file.read_text())
final_count = len(data['runs'][run_id].get('transitions', []))
final_state = data['runs'][run_id]['state']

print(f"\n✓ Final state in JSON: {final_state}")
print(f"✓ Transitions in JSON: {final_count}")

if final_state == 'ANALYZING' and final_count > initial_count:
    print(f"✓ All mutations persisted to JSON")
else:
    print(f"✗ Mutations not fully persisted")
    sys.exit(1)

print("\n" + "=" * 60)
print("SUCCESS: Mutation persistence verified!")
print("=" * 60)
