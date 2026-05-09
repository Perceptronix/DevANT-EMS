"""
Test script for GitHub ingestion functionality.
Demonstrates parsing logic without requiring a real GitHub token.
"""
import sys
from pathlib import Path

# Add backend directory to path
backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

from scripts.ingest import GitHubIngester

def test_python_parsing():
    """Test Python code parsing and chunking."""
    print("\n" + "=" * 60)
    print("Testing Python Code Parsing")
    print("=" * 60)
    
    # Create minimal ingester with test values
    ingester = GitHubIngester.__new__(GitHubIngester)
    ingester.github_repo = "test/repo"
    
    # Sample Python code
    sample_code = '''"""Module for handling errors."""
import logging
from typing import Optional

logger = logging.getLogger(__name__)

class ErrorHandler:
    """Handles application errors."""
    
    def __init__(self):
        self.errors = []
    
    def log_error(self, error: Exception) -> None:
        """Log an error to the list."""
        self.errors.append(error)
        logger.error(f"Error occurred: {error}")

def format_error_message(error: str, context: Optional[str] = None) -> str:
    """Format error message with context."""
    if context:
        return f"{context}: {error}"
    return error

class RetryableError(Exception):
    """Raised when operation should be retried."""
    pass
'''
    
    chunks = ingester._parse_python_file(sample_code, "core/errors.py")
    
    print(f"\nFound {len(chunks)} chunks:")
    for i, chunk in enumerate(chunks, 1):
        metadata = chunk["metadata"]
        print(f"\n  Chunk {i}:")
        print(f"    Type: {metadata['type']}")
        print(f"    Title: {metadata['title']}")
        print(f"    Path: {metadata['path']}")
        print(f"    Lines: {len(chunk['content'].split(chr(10)))}")


def test_typescript_parsing():
    """Test TypeScript code parsing and chunking."""
    print("\n" + "=" * 60)
    print("Testing TypeScript Code Parsing")
    print("=" * 60)
    
    # Create minimal ingester with test values
    ingester = GitHubIngester.__new__(GitHubIngester)
    ingester.github_repo = "test/repo"
    
    # Sample TypeScript code
    sample_code = '''import { useEffect, useState } from 'react'
import { fetchData } from '@/api'

interface User {
  id: string
  name: string
  email: string
}

export function UserProfile() {
  const [user, setUser] = useState<User | null>(null)
  const [loading, setLoading] = useState(false)
  
  useEffect(() => {
    setLoading(true)
    fetchData().then(setUser).finally(() => setLoading(false))
  }, [])
  
  if (loading) return <div>Loading...</div>
  return <div>{user?.name}</div>
}

export async function fetchUser(id: string): Promise<User> {
  const response = await fetch(`/api/users/${id}`)
  return response.json()
}

class UserService {
  async getUser(id: string): Promise<User> {
    return fetchUser(id)
  }
}
'''
    
    chunks = ingester._parse_typescript_file(sample_code, "src/components/user.tsx")
    
    print(f"\nFound {len(chunks)} chunks:")
    for i, chunk in enumerate(chunks, 1):
        metadata = chunk["metadata"]
        print(f"\n  Chunk {i}:")
        print(f"    Type: {metadata['type']}")
        print(f"    Title: {metadata['title']}")
        print(f"    Path: {metadata['path']}")
        print(f"    Lines: {len(chunk['content'].split(chr(10)))}")


def test_metadata_structure():
    """Test metadata structure for ChromaDB."""
    print("\n" + "=" * 60)
    print("Testing Metadata Structure")
    print("=" * 60)
    
    metadata_examples = [
        {
            "type": "github_issue",
            "title": "Rate limiting causes 429 errors",
            "path": "issues/1234",
            "url": "https://github.com/owner/repo/issues/1234",
            "source": "github",
            "state": "open",
            "labels": "bug,priority"
        },
        {
            "type": "github_pr",
            "title": "Add exponential backoff retry logic",
            "path": "pulls/5678",
            "url": "https://github.com/owner/repo/pull/5678",
            "source": "github",
            "author": "developer",
            "state": "merged",
            "changed_files": "3"
        },
        {
            "type": "python_function",
            "title": "errors.py::format_error_message",
            "path": "core/errors.py",
            "url": "https://raw.githubusercontent.com/owner/repo/main/core/errors.py#L45",
            "source": "github",
            "title": "Function for formatting errors"
        }
    ]
    
    print("\nMetadata examples for ChromaDB ingestion:")
    for i, meta in enumerate(metadata_examples, 1):
        print(f"\n  Example {i} ({meta.get('type')}):")
        for key, value in meta.items():
            print(f"    {key}: {value}")


if __name__ == "__main__":
    try:
        test_python_parsing()
        test_typescript_parsing()
        test_metadata_structure()
        
        print("\n" + "=" * 60)
        print("All tests passed! ✓")
        print("=" * 60)
        print("\nTo run full ingestion:")
        print("  export GITHUB_TOKEN=ghp_...")
        print("  export GITHUB_REPO=owner/repo")
        print("  python scripts/ingest.py")
        
    except Exception as e:
        print(f"\nTest failed: {e}")
        import traceback
        traceback.print_exc()
