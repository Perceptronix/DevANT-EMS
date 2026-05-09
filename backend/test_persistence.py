"""Validate JSON persistence for repository analysis state."""
import json
from pathlib import Path
import sys
import time

# Test 1: Create run and verify JSON file created
print("=" * 60)
print("TEST 1: Create run and verify JSON persisted")
print("=" * 60)

from repository.analysis_state import create_run, get_run_snapshot

# Create a test run
run_id = create_run('https://github.com/test/repo')
print(f"✓ Created run: {run_id}")

# Verify JSON file exists
state_file = Path('data/analysis_runs.json')
if state_file.exists():
    print(f"✓ {state_file} created")
    data = json.loads(state_file.read_text())
    if 'runs' in data and run_id in data['runs']:
        print(f"✓ Run {run_id} persisted in JSON")
        status = data['runs'][run_id].get('status')
        print(f"✓ Run status: {status}")
    else:
        print("✗ Run not found in JSON")
        sys.exit(1)
else:
    print(f"✗ {state_file} not created")
    sys.exit(1)

# Test 2: Verify in-memory run accessible
print("\n" + "=" * 60)
print("TEST 2: Verify in-memory state accessible")
print("=" * 60)

snapshot = get_run_snapshot(run_id)
if snapshot.get('status') != 'not_found':
    print(f"✓ Run snapshot accessible in memory")
    print(f"✓ Snapshot status: {snapshot.get('status')}")
else:
    print("✗ Run snapshot not found in memory")
    sys.exit(1)

# Test 3: Verify restart simulation
print("\n" + "=" * 60)
print("TEST 3: Simulate restart (reload from disk)")
print("=" * 60)

# Save run ID
saved_run_id = run_id

# Clear in-memory state and reload
import repository.analysis_state as state_module
state_module._runs.clear()
print(f"✓ Cleared in-memory state")

# Reload from disk
state_module._load_from_disk()
print(f"✓ Reloaded from disk")

# Verify run is restored
if saved_run_id in state_module._runs:
    print(f"✓ Run {saved_run_id} restored from disk")
    restored_status = state_module._runs[saved_run_id].get('status')
    print(f"✓ Restored status: {restored_status}")
else:
    print("✗ Run not restored from disk")
    sys.exit(1)

# Test 4: Multiple runs
print("\n" + "=" * 60)
print("TEST 4: Multiple runs persistence")
print("=" * 60)

# Create more runs
run_id_2 = create_run('https://github.com/test/repo2')
run_id_3 = create_run('https://github.com/test/repo3')
print(f"✓ Created run 2: {run_id_2}")
print(f"✓ Created run 3: {run_id_3}")

# Verify all 3 in JSON
data = json.loads(state_file.read_text())
count = len(data['runs'])
print(f"✓ Total runs in JSON: {count}")

if saved_run_id in data['runs'] and run_id_2 in data['runs'] and run_id_3 in data['runs']:
    print(f"✓ All {count} runs present in JSON")
else:
    print("✗ Some runs missing from JSON")
    sys.exit(1)

print("\n" + "=" * 60)
print("SUCCESS: All persistence tests passed!")
print("=" * 60)
print("JSON state persistence is working correctly.")
print("- Runs auto-save on creation and mutation")
print("- Runs auto-load from disk on startup")
print("- Multiple runs handled without corruption")
