"""
GitHub repository ingestion for engineering memory.

Fetches code, issues, and PRs from GitHub and stores them in ChromaDB.
This creates persistent engineering memory for semantic search.

Usage:
    export GITHUB_TOKEN=ghp_...
    export GITHUB_REPO=owner/repo
    python scripts/ingest.py
"""
import os
import sys
import asyncio
import httpx
import logging
import re
from typing import List, Dict, Any, Optional
from pathlib import Path

from dotenv import load_dotenv

# Load environment variables from .env (project root) before any initialization
env_path = Path(__file__).parent.parent.parent / ".env"
load_dotenv(dotenv_path=env_path)

# Add backend directory to path for imports
backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

from clients.chroma_client import ChromaClient

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# GitHub API configuration
GITHUB_API_BASE = "https://api.github.com"
GITHUB_RAW_BASE = "https://raw.githubusercontent.com"

# Supported code file extensions
SUPPORTED_EXTENSIONS = {".py", ".ts", ".tsx", ".js", ".jsx"}

# Excluded file paths to avoid indexing obsolete provider code
EXCLUDED_KEYWORDS = [
    "airweave",      # Obsolete Airweave provider
    "linear",        # Obsolete Linear provider
    "openai",        # Obsolete OpenAI provider
    "anthropic",     # Obsolete Anthropic provider
    "__pycache__",   # Python cache
    "node_modules",  # NPM dependencies
    "dist",          # Build output
    "build"          # Build output
]

# Rate limit consideration
GITHUB_API_RATE_LIMIT = 60  # Requests per minute for unauthenticated


class GitHubIngester:
    """Ingests GitHub repository data into ChromaDB."""
    
    def __init__(self):
        self.github_token = os.getenv("GITHUB_TOKEN")
        self.github_repo = os.getenv("GITHUB_REPO")
        
        if not self.github_token:
            raise ValueError("GITHUB_TOKEN environment variable required")
        if not self.github_repo:
            raise ValueError("GITHUB_REPO environment variable required")
        
        # Initialize HTTP client with GitHub authentication
        self.http_client = httpx.AsyncClient(
            headers={"Authorization": f"token {self.github_token}"},
            base_url=GITHUB_API_BASE,
            timeout=30.0
        )
        
        # Initialize ChromaDB client
        try:
            self.chroma = ChromaClient(
                persist_dir=os.getenv("CHROMA_PERSIST_DIR", "./data/chroma")
            )
            logger.info("ChromaDB client initialized")
        except Exception as e:
            logger.error(f"Failed to initialize ChromaDB: {e}")
            raise
    
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.http_client.aclose()
    
    async def ingest_github_issues(self) -> int:
        """
        Fetch GitHub issues and store in ChromaDB.
        
        Returns:
            Number of issues ingested
        """
        logger.info(f"Starting GitHub issues ingestion from {self.github_repo}")
        
        documents = []
        metadatas = []
        issues_count = 0
        page = 1
        
        try:
            while True:
                # Fetch paginated issues
                response = await self.http_client.get(
                    f"/repos/{self.github_repo}/issues",
                    params={"state": "all", "per_page": 100, "page": page}
                )
                response.raise_for_status()
                issues = response.json()
                
                if not issues:
                    break
                
                for issue in issues:
                    # Skip pull requests (they also appear in issues API)
                    if "pull_request" in issue:
                        continue
                    
                    # Build issue content
                    title = issue.get("title", "Untitled")
                    body = issue.get("body", "") or ""
                    labels = ", ".join([label["name"] for label in issue.get("labels", [])])
                    state = issue.get("state", "open")
                    url = issue.get("html_url", "")
                    issue_number = issue.get("number", "")
                    
                    # Combine content for semantic search
                    content = f"""# Issue #{issue_number}: {title}

Status: {state}
Labels: {labels}

{body}"""
                    
                    documents.append(content)
                    metadatas.append({
                        "type": "github_issue",
                        "title": title,
                        "path": f"issues/{issue_number}",
                        "url": url,
                        "source": "github",
                        "state": state,
                        "labels": labels
                    })
                    
                    issues_count += 1
                
                page += 1
                logger.info(f"Fetched page {page - 1}, total issues: {issues_count}")
                
                # Respect rate limiting
                await asyncio.sleep(0.5)
        
        except Exception as e:
            logger.error(f"Error fetching issues: {e}")
            raise
        
        # Insert into ChromaDB
        if documents:
            try:
                self.chroma.ingest(
                    documents=documents,
                    metadatas=metadatas,
                    source="github_issues"
                )
                logger.info(f"Ingested {issues_count} GitHub issues into ChromaDB")
            except Exception as e:
                logger.error(f"Error inserting issues into ChromaDB: {e}")
                raise
        
        return issues_count
    
    async def ingest_github_pull_requests(self) -> int:
        """
        Fetch GitHub pull requests and store in ChromaDB.
        PR discussions are operational memory, stored with issues.
        
        Returns:
            Number of PRs ingested
        """
        logger.info(f"Starting GitHub PR ingestion from {self.github_repo}")
        
        documents = []
        metadatas = []
        prs_count = 0
        page = 1
        
        try:
            while True:
                # Fetch paginated PRs
                response = await self.http_client.get(
                    f"/repos/{self.github_repo}/pulls",
                    params={"state": "all", "per_page": 100, "page": page}
                )
                response.raise_for_status()
                prs = response.json()
                
                if not prs:
                    break
                
                for pr in prs:
                    title = pr.get("title", "Untitled")
                    body = pr.get("body", "") or ""
                    pr_number = pr.get("number", "")
                    url = pr.get("html_url", "")
                    author = pr.get("user", {}).get("login", "unknown")
                    state = pr.get("state", "open")
                    merged = pr.get("merged", False)
                    
                    # Get changed files summary
                    changed_files = pr.get("changed_files", 0)
                    additions = pr.get("additions", 0)
                    deletions = pr.get("deletions", 0)
                    
                    # Build PR content for semantic search
                    content = f"""# PR #{pr_number}: {title}

Author: {author}
Status: {state}
Merged: {merged}
Changed Files: {changed_files} (+{additions} -{deletions})

{body}"""
                    
                    documents.append(content)
                    metadatas.append({
                        "type": "github_pr",
                        "title": title,
                        "path": f"pulls/{pr_number}",
                        "url": url,
                        "source": "github",
                        "author": author,
                        "state": state,
                        "merged": str(merged),
                        "changed_files": str(changed_files)
                    })
                    
                    prs_count += 1
                
                page += 1
                logger.info(f"Fetched page {page - 1}, total PRs: {prs_count}")
                
                # Respect rate limiting
                await asyncio.sleep(0.5)
        
        except Exception as e:
            logger.error(f"Error fetching PRs: {e}")
            raise
        
        # Insert into ChromaDB (same collection as issues - operational memory)
        if documents:
            try:
                self.chroma.ingest(
                    documents=documents,
                    metadatas=metadatas,
                    source="github_issues"  # Store PRs with issues
                )
                logger.info(f"Ingested {prs_count} GitHub PRs into ChromaDB")
            except Exception as e:
                logger.error(f"Error inserting PRs into ChromaDB: {e}")
                raise
        
        return prs_count
    
    async def ingest_github_code(self) -> int:
        """
        Recursively fetch code files from repository and chunk by logical units.
        
        Returns:
            Number of code chunks ingested
        """
        logger.info(f"Starting code ingestion from {self.github_repo}")
        
        documents = []
        metadatas = []
        chunks_count = 0
        
        try:
            # Get repository tree
            tree_response = await self.http_client.get(
                f"/repos/{self.github_repo}/git/trees/main",
                params={"recursive": 1}
            )
            tree_response.raise_for_status()
            tree = tree_response.json()
            
            # Filter for code files, excluding obsolete provider code
            code_files = [
                item for item in tree.get("tree", [])
                if item.get("type") == "blob"
                and any(item.get("path", "").endswith(ext) for ext in SUPPORTED_EXTENSIONS)
                and not any(keyword in item.get("path", "").lower() for keyword in EXCLUDED_KEYWORDS)
            ]
            
            logger.info(f"Found {len(code_files)} code files to process")
            
            # Process each code file
            for idx, file_item in enumerate(code_files):
                file_path = file_item.get("path", "")
                
                # Skip files with excluded keywords (defensive check)
                if any(keyword in file_path.lower() for keyword in EXCLUDED_KEYWORDS):
                    logger.debug(f"Skipping excluded file: {file_path}")
                    continue
                
                logger.debug(f"Processing file {idx + 1}/{len(code_files)}: {file_path}")
                
                try:
                    # Fetch file content
                    file_url = f"{GITHUB_RAW_BASE}/{self.github_repo}/main/{file_path}"
                    file_response = await self.http_client.get(file_url)
                    file_response.raise_for_status()
                    file_content = file_response.text
                    
                    # Parse and chunk file based on extension
                    if file_path.endswith(".py"):
                        chunks = self._parse_python_file(file_content, file_path)
                    elif file_path.endswith((".ts", ".tsx")):
                        chunks = self._parse_typescript_file(file_content, file_path)
                    elif file_path.endswith((".js", ".jsx")):
                        chunks = self._parse_javascript_file(file_content, file_path)
                    else:
                        chunks = []
                    
                    # Add chunks to batch
                    for chunk in chunks:
                        documents.append(chunk["content"])
                        metadatas.append(chunk["metadata"])
                        chunks_count += 1
                    
                    # Respect rate limiting
                    await asyncio.sleep(0.2)
                
                except Exception as e:
                    logger.warning(f"Error processing file {file_path}: {e}")
                    continue
            
            # Insert all chunks into ChromaDB
            if documents:
                try:
                    self.chroma.ingest(
                        documents=documents,
                        metadatas=metadatas,
                        source="github"
                    )
                    logger.info(f"Ingested {chunks_count} code chunks into ChromaDB")
                except Exception as e:
                    logger.error(f"Error inserting code into ChromaDB: {e}")
                    raise
        
        except Exception as e:
            logger.error(f"Error during code ingestion: {e}")
            raise
        
        return chunks_count
    
    def _parse_python_file(self, content: str, file_path: str) -> List[Dict[str, Any]]:
        """
        Parse Python file and chunk by class/function.
        
        Returns:
            List of chunks with content and metadata
        """
        chunks = []
        lines = content.split("\n")
        
        # Extract imports (always included with first chunk)
        import_lines = []
        code_start = 0
        for idx, line in enumerate(lines):
            if line.startswith(("import ", "from ")):
                import_lines.append(line)
            elif line.strip() and not line.startswith("#"):
                code_start = idx
                break
        
        imports_text = "\n".join(import_lines)
        
        # Find all classes and functions
        class_pattern = re.compile(r"^class\s+(\w+)")
        func_pattern = re.compile(r"^def\s+(\w+)")
        
        current_block = {"name": None, "start": None, "end": None, "type": None}
        
        for idx, line in enumerate(lines):
            # Check for class definition
            class_match = class_pattern.match(line)
            if class_match:
                # Save previous block if exists
                if current_block["start"] is not None:
                    chunks.append(
                        self._create_chunk(
                            lines, current_block, imports_text, file_path
                        )
                    )
                
                current_block = {
                    "name": class_match.group(1),
                    "start": idx,
                    "end": None,
                    "type": "class"
                }
            
            # Check for function definition (at module level or after class)
            elif func_pattern.match(line) and line[0] != " ":
                # Module-level function
                if current_block["start"] is not None and current_block["type"] == "class":
                    chunks.append(
                        self._create_chunk(
                            lines, current_block, imports_text, file_path
                        )
                    )
                
                current_block = {
                    "name": func_pattern.match(line).group(1),
                    "start": idx,
                    "end": None,
                    "type": "function"
                }
        
        # Save final block
        if current_block["start"] is not None:
            current_block["end"] = len(lines)
            chunks.append(
                self._create_chunk(
                    lines, current_block, imports_text, file_path
                )
            )
        
        # If no chunks found, add entire file
        if not chunks:
            chunks.append({
                "content": content,
                "metadata": {
                    "path": file_path,
                    "url": f"{GITHUB_RAW_BASE}/{self.github_repo}/main/{file_path}",
                    "source": "github",
                    "type": "python_module",
                    "title": Path(file_path).name
                }
            })
        
        return chunks
    
    def _parse_typescript_file(self, content: str, file_path: str) -> List[Dict[str, Any]]:
        """
        Parse TypeScript/TSX file and chunk by class/function/component.
        """
        chunks = []
        lines = content.split("\n")
        
        # Extract imports
        import_lines = []
        code_start = 0
        for idx, line in enumerate(lines):
            if line.startswith(("import ", "export import")):
                import_lines.append(line)
            elif line.strip() and not line.startswith("//"):
                code_start = idx
                break
        
        imports_text = "\n".join(import_lines)
        
        # Find classes, functions, and React components
        class_pattern = re.compile(r"^(?:export\s+)?class\s+(\w+)")
        func_pattern = re.compile(r"^(?:export\s+)?(?:async\s+)?function\s+(\w+)")
        const_pattern = re.compile(r"^(?:export\s+)?const\s+(\w+)\s*=\s*(?:\(.*?\)\s*)?=>|function")
        
        current_block = {"name": None, "start": None, "end": None, "type": None}
        
        for idx, line in enumerate(lines):
            # Check for class
            class_match = class_pattern.match(line)
            if class_match:
                if current_block["start"] is not None:
                    chunks.append(
                        self._create_chunk(
                            lines, current_block, imports_text, file_path, "typescript"
                        )
                    )
                
                current_block = {
                    "name": class_match.group(1),
                    "start": idx,
                    "end": None,
                    "type": "class"
                }
            
            # Check for function
            elif func_pattern.match(line):
                if current_block["start"] is not None:
                    chunks.append(
                        self._create_chunk(
                            lines, current_block, imports_text, file_path, "typescript"
                        )
                    )
                
                current_block = {
                    "name": func_pattern.match(line).group(1),
                    "start": idx,
                    "end": None,
                    "type": "function"
                }
            
            # Check for const with arrow function (React components)
            elif const_match := const_pattern.match(line):
                if current_block["start"] is not None:
                    chunks.append(
                        self._create_chunk(
                            lines, current_block, imports_text, file_path, "typescript"
                        )
                    )
                
                current_block = {
                    "name": const_match.group(1),
                    "start": idx,
                    "end": None,
                    "type": "component" if "use" in const_match.group(1).lower() or any(c.isupper() for c in const_match.group(1)) else "function"
                }
        
        # Save final block
        if current_block["start"] is not None:
            current_block["end"] = len(lines)
            chunks.append(
                self._create_chunk(
                    lines, current_block, imports_text, file_path, "typescript"
                )
            )
        
        # If no chunks found, add entire file
        if not chunks:
            chunks.append({
                "content": content,
                "metadata": {
                    "path": file_path,
                    "url": f"{GITHUB_RAW_BASE}/{self.github_repo}/main/{file_path}",
                    "source": "github",
                    "type": "typescript_module",
                    "title": Path(file_path).name
                }
            })
        
        return chunks
    
    def _parse_javascript_file(self, content: str, file_path: str) -> List[Dict[str, Any]]:
        """Parse JavaScript file - similar to TypeScript for now."""
        return self._parse_typescript_file(content, file_path)
    
    def _create_chunk(
        self,
        lines: List[str],
        block: Dict[str, Any],
        imports: str,
        file_path: str,
        language: str = "python"
    ) -> Dict[str, Any]:
        """Create a code chunk with metadata."""
        start = block["start"]
        end = block.get("end", len(lines))
        
        # Get the code block
        code_lines = lines[start:end]
        code_text = "\n".join(code_lines)
        
        # Combine with imports
        chunk_content = f"{imports}\n\n{code_text}" if imports else code_text
        
        block_type = block.get("type", "code")
        block_name = block.get("name", "unknown")
        
        return {
            "content": chunk_content,
            "metadata": {
                "path": file_path,
                "url": f"{GITHUB_RAW_BASE}/{self.github_repo}/main/{file_path}#L{start + 1}",
                "source": "github",
                "type": f"{language}_{block_type}",
                "title": f"{Path(file_path).name}::{block_name}"
            }
        }
    
    async def ingest_all(self) -> Dict[str, int]:
        """
        Run complete ingestion pipeline.
        
        Returns:
            Dictionary with ingestion counts
        """
        logger.info("Starting complete GitHub repository ingestion")
        
        results = {
            "issues": 0,
            "pull_requests": 0,
            "code_chunks": 0
        }
        
        try:
            # Ingest in order: issues, PRs, code
            results["issues"] = await self.ingest_github_issues()
            results["pull_requests"] = await self.ingest_github_pull_requests()
            results["code_chunks"] = await self.ingest_github_code()
            
            logger.info("=" * 60)
            logger.info("Ingestion Summary:")
            logger.info(f"  Issues: {results['issues']}")
            logger.info(f"  Pull Requests: {results['pull_requests']}")
            logger.info(f"  Code Chunks: {results['code_chunks']}")
            logger.info(f"  Total: {sum(results.values())}")
            logger.info("=" * 60)
            
        except Exception as e:
            logger.error(f"Ingestion failed: {e}")
            raise
        
        return results


async def main():
    """Main entry point."""
    try:
        async with GitHubIngester() as ingester:
            results = await ingester.ingest_all()
            
            # Verify data in ChromaDB
            logger.info("\nVerifying ChromaDB collections...")
            
            # Test search
            try:
                test_results = await ingester.chroma.search(
                    query="error handling",
                    source_filter="github",
                    limit=3
                )
                logger.info(f"Test search returned {len(test_results)} results")
                for i, result in enumerate(test_results, 1):
                    logger.info(
                        f"  {i}. {result.get('metadata', {}).get('title', 'N/A')} "
                        f"(score: {result.get('score', 0):.2f})"
                    )
            except Exception as e:
                logger.warning(f"Test search failed: {e}")
            
            return results
    
    except Exception as e:
        logger.error(f"Ingestion script failed: {e}", exc_info=True)
        raise


if __name__ == "__main__":
    asyncio.run(main())
