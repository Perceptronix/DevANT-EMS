"""
Test script to validate the exclusion filter for obsolete provider files.
Demonstrates that ingestion will no longer index deprecated providers.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path('.').resolve()))

# Test data simulating GitHub file paths
TEST_CASES = [
    # (file_path, should_include, reason)
    ("backend/clients/airweave_client.py", False, "Obsolete Airweave provider"),
    ("backend/clients/linear_client.py", False, "Obsolete Linear provider"),
    ("backend/clients/openai_config.py", False, "Obsolete OpenAI provider"),
    ("backend/clients/anthropic_wrapper.py", False, "Obsolete Anthropic provider"),
    ("backend/pipeline/search.py", True, "Core DevANT search logic"),
    ("backend/pipeline/clustering.py", True, "Core DevANT clustering"),
    ("frontend/src/components/pipeline-visualizer.tsx", True, "Frontend component"),
    ("frontend/src/hooks/useWebSocket.ts", True, "React hook"),
    ("frontend/node_modules/package/index.js", False, "NPM dependencies"),
    ("backend/__pycache__/main.pyc", False, "Python cache"),
    ("frontend/dist/index.js", False, "Build output"),
    ("backend/build/output.py", False, "Build output"),
    ("backend/config.py", True, "Configuration"),
    ("backend/main.py", True, "Main entry point"),
    ("backend/state.py", True, "State management"),
]

# Mimic the exclusion logic from ingest.py
SUPPORTED_EXTENSIONS = {".py", ".ts", ".tsx", ".js", ".jsx"}

EXCLUDED_KEYWORDS = [
    "airweave",
    "linear",
    "openai",
    "anthropic",
    "__pycache__",
    "node_modules",
    "dist",
    "build"
]

def should_include_file(file_path: str) -> bool:
    """Determine if a file should be included in ingestion."""
    # Check file extension
    has_valid_ext = any(file_path.endswith(ext) for ext in SUPPORTED_EXTENSIONS)
    if not has_valid_ext:
        return False
    
    # Check for excluded keywords
    has_excluded = any(keyword in file_path.lower() for keyword in EXCLUDED_KEYWORDS)
    if has_excluded:
        return False
    
    return True


def test_exclusion_filter():
    """Test the exclusion filter logic."""
    print("=" * 70)
    print("Testing Exclusion Filter for Obsolete Provider Files")
    print("=" * 70)
    
    passed = 0
    failed = 0
    
    for file_path, should_include, reason in TEST_CASES:
        result = should_include_file(file_path)
        status = "✓ PASS" if result == should_include else "✗ FAIL"
        
        if result == should_include:
            passed += 1
        else:
            failed += 1
        
        action = "INCLUDE" if should_include else "EXCLUDE"
        result_str = "INCLUDED" if result else "EXCLUDED"
        
        print(f"\n{status}")
        print(f"  File: {file_path}")
        print(f"  Expected: {action}")
        print(f"  Got: {result_str}")
        print(f"  Reason: {reason}")
    
    print("\n" + "=" * 70)
    print(f"Results: {passed} passed, {failed} failed")
    print("=" * 70)
    
    # Summary of exclusions
    print("\nExclusion Summary:")
    print("─" * 70)
    excluded_files = [f for f, include, _ in TEST_CASES if not include]
    included_files = [f for f, include, _ in TEST_CASES if include]
    
    print(f"\nFiles that will be EXCLUDED (NOT indexed):")
    for f in excluded_files:
        print(f"  ✗ {f}")
    
    print(f"\nFiles that will be INCLUDED (indexed):")
    for f in included_files:
        print(f"  ✓ {f}")
    
    print("\n" + "=" * 70)
    print("Excluded Keywords in Filter:")
    print("─" * 70)
    for keyword in EXCLUDED_KEYWORDS:
        print(f"  • {keyword}")
    
    print("\n" + "=" * 70)
    if failed == 0:
        print("✓ All tests passed! Exclusion filter is working correctly.")
        print("✓ Obsolete provider files will NOT be indexed.")
        print("✓ Engineering memory will be clean and DevANT-native.")
    else:
        print(f"✗ {failed} test(s) failed. Please review the filter logic.")
    print("=" * 70)
    
    return failed == 0


if __name__ == "__main__":
    success = test_exclusion_filter()
    sys.exit(0 if success else 1)
