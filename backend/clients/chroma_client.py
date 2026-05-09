"""
ChromaDB client for semantic context retrieval.

Replaces Airweave with local vector search using ChromaDB and sentence-transformers.
Provides semantic search across:
- GitHub code snippets (github_code collection)
- GitHub issues (github_issues collection)
- Slack threads (slack_threads collection)
- All context combined (all_context collection)
"""
import logging
from typing import List, Dict, Optional, Any
import chromadb
from chromadb.utils import embedding_functions

from config import get_config

logger = logging.getLogger(__name__)

# Embedding model - lightweight but effective for code/docs
EMBEDDING_MODEL = "all-MiniLM-L6-v2"

# Collection names by source
COLLECTIONS = {
    "github": "github_code",
    "github_issues": "github_issues",
    "slack": "slack_threads",
    "all": "all_context",
}


class ChromaClient:
    """
    Local vector search client using ChromaDB and sentence-transformers.
    
    Provides methods to search for:
    - Related code from GitHub
    - Related issues from GitHub Issues
    - Discussions from Slack
    - Combined search across all sources
    """
    
    def __init__(self, persist_dir: Optional[str] = None):
        """
        Initialize ChromaDB client with persistent storage.
        
        Args:
            persist_dir: Optional path to persistent storage directory.
                        If not provided, uses config.chroma.persist_dir
        """
        # Use provided persist_dir or fall back to config
        if persist_dir is None:
            config = get_config()
            persist_dir = config.chroma.persist_dir
        
        self.persist_dir = persist_dir
        
        # Initialize ChromaDB with persistent storage
        self.client = chromadb.PersistentClient(path=persist_dir)
        
        # Initialize embedding function (sentence-transformers)
        self.embedding_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name=EMBEDDING_MODEL
        )
        
        # Initialize or get collections
        self.collections = {}
        for source_name, collection_name in COLLECTIONS.items():
            try:
                col = self.client.get_or_create_collection(
                    name=collection_name,
                    embedding_function=self.embedding_fn,
                    metadata={"source": source_name, "hnsw:space": "cosine"}
                )
                self.collections[collection_name] = col
                logger.info(f"Initialized collection: {collection_name}")
            except Exception as e:
                logger.error(f"Failed to initialize collection {collection_name}: {e}")
        
        logger.info(f"ChromaDB client initialized (persist_dir: {persist_dir})")
    
    async def search(
        self,
        query: str,
        source_filter: Optional[str] = None,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """
        Search for context across ChromaDB collections.
        
        Args:
            query: Search query string
            source_filter: Optional source filter:
                - "github" → github_code
                - "github_issues" → github_issues
                - "slack" → slack_threads
                - None → all_context
            limit: Maximum number of results
            
        Returns:
            List of search results with content, metadata, and similarity scores
        """
        # Map source filter to collection name
        if source_filter == "github":
            collection_name = COLLECTIONS["github"]
        elif source_filter == "github_issues":
            collection_name = COLLECTIONS["github_issues"]
        elif source_filter == "slack":
            collection_name = COLLECTIONS["slack"]
        else:
            # Search across all context if no filter
            collection_name = COLLECTIONS["all"]
        
        # Get collection
        if collection_name not in self.collections:
            logger.warning(f"Collection {collection_name} not found")
            return []
        
        collection = self.collections[collection_name]
        
        # Safety check: return empty if collection is empty
        if collection.count() == 0:
            logger.debug(f"Collection {collection_name} is empty, returning no results")
            return []
        
        try:
            # Query the collection
            results = collection.query(
                query_texts=[query],
                n_results=limit,
                include=["documents", "metadatas", "distances"]
            )
            
            # Transform results to expected format
            formatted_results = []
            
            if results and results["documents"] and len(results["documents"]) > 0:
                documents = results["documents"][0]  # First (only) query
                metadatas = results["metadatas"][0] if results["metadatas"] else [{}] * len(documents)
                distances = results["distances"][0] if results["distances"] else [0] * len(documents)
                
                for doc, meta, distance in zip(documents, metadatas, distances):
                    # Convert cosine distance to similarity score (1.0 - distance)
                    # Chroma returns distances; 0 = identical, 1 = most different
                    similarity_score = 1.0 - distance if distance is not None else 0.5
                    
                    formatted_results.append({
                        "content": doc,
                        "metadata": meta if meta else {},
                        "score": similarity_score,
                    })
            
            logger.debug(
                f"Search in {collection_name} returned {len(formatted_results)} results "
                f"for query: {query[:50]}..."
            )
            return formatted_results
            
        except Exception as e:
            logger.error(f"Search failed in {collection_name}: {e}", exc_info=True)
            return []
    
    def ingest(
        self,
        documents: List[str],
        metadatas: List[Dict[str, Any]],
        source: str,
    ) -> None:
        """
        Ingest documents into the appropriate ChromaDB collection.
        
        Args:
            documents: List of document strings to ingest
            metadatas: List of metadata dicts (must match documents length)
            source: Source type:
                - "github" → github_code
                - "github_issues" → github_issues
                - "linear" → github_issues
                - "slack" → slack_threads
                - "all" → all_context
        """
        if not documents or len(documents) == 0:
            logger.warning("No documents to ingest")
            return
        
        if len(documents) != len(metadatas):
            logger.error("Documents and metadatas must have same length")
            return
        
        # Map source to collection name
        if source == "github":
            collection_name = COLLECTIONS["github"]
        elif source in ["github_issues", "linear"]:
            collection_name = COLLECTIONS["github_issues"]
        elif source == "slack":
            collection_name = COLLECTIONS["slack"]
        elif source == "all":
            collection_name = COLLECTIONS["all"]
        else:
            logger.error(f"Unknown source: {source}")
            return
        
        # Get collection
        if collection_name not in self.collections:
            logger.error(f"Collection {collection_name} not found")
            return
        
        collection = self.collections[collection_name]
        
        try:
            # Generate IDs for documents (use hash of content + metadata)
            ids = []
            for i, (doc, meta) in enumerate(zip(documents, metadatas)):
                # Create deterministic ID from content hash
                doc_id = f"{source}_{i}_{hash(doc) % 10000000:07d}"
                ids.append(doc_id)
            
            # Add documents to collection
            collection.add(
                documents=documents,
                metadatas=metadatas,
                ids=ids,
            )
            
            logger.info(
                f"Ingested {len(documents)} documents into {collection_name} "
                f"(source: {source})"
            )
            
            # Also add to all_context collection for combined search
            if collection_name != COLLECTIONS["all"]:
                all_collection = self.collections[COLLECTIONS["all"]]
                all_ids = [f"all_{id_}" for id_ in ids]
                all_collection.add(
                    documents=documents,
                    metadatas=metadatas,
                    ids=all_ids,
                )
                logger.debug(f"Also added {len(documents)} documents to all_context")
            
        except Exception as e:
            logger.error(f"Failed to ingest documents into {collection_name}: {e}", exc_info=True)
    
    async def search_code(
        self,
        query: str,
        module: Optional[str] = None,
        limit: int = 5,
    ) -> List[Dict[str, Any]]:
        """
        Search for related code from GitHub.
        
        Args:
            query: Search query (error message, function name, etc.)
            module: Optional module name to focus search
            limit: Maximum results
            
        Returns:
            List of code snippets with metadata
        """
        search_query = f"{query} {module}" if module else query
        results = await self.search(search_query, source_filter="github", limit=limit)
        
        # Format results for code context
        formatted = []
        for result in results:
            formatted.append({
                "title": result.get("metadata", {}).get("path", "Unknown"),
                "content": result.get("content", "")[:500],
                "source": "github",
                "url": result.get("metadata", {}).get("url"),
                "score": result.get("score", 0),
            })
        
        return formatted
    
    async def search_tickets(
        self,
        query: str,
        limit: int = 5,
    ) -> List[Dict[str, Any]]:
        """
        Search for related issues from GitHub/Linear.
        
        Args:
            query: Search query (error description, etc.)
            limit: Maximum results
            
        Returns:
            List of issues/tickets with metadata
        """
        results = await self.search(query, source_filter="linear", limit=limit)
        
        # Format results for ticket context
        formatted = []
        for result in results:
            formatted.append({
                "title": result.get("metadata", {}).get("title", "Unknown"),
                "content": result.get("content", "")[:300],
                "source": "github_issues",
                "url": result.get("metadata", {}).get("url"),
                "status": result.get("metadata", {}).get("status"),
                "identifier": result.get("metadata", {}).get("identifier"),
                "id": result.get("metadata", {}).get("id"),
                "score": result.get("score", 0),
            })
        
        return formatted
    
    async def search_docs(
        self,
        query: str,
        limit: int = 3,
    ) -> List[Dict[str, Any]]:
        """
        Search for related documentation and slack threads.
        
        Args:
            query: Search query
            limit: Maximum results
            
        Returns:
            List of documentation/discussion results
        """
        # Search slack threads for discussions
        results = await self.search(query, source_filter="slack", limit=limit)
        
        # Format results
        formatted = []
        for result in results:
            formatted.append({
                "title": result.get("metadata", {}).get("title", "Unknown"),
                "content": result.get("content", "")[:300],
                "source": "slack",
                "url": result.get("metadata", {}).get("url"),
                "score": result.get("score", 0),
            })
        
        return formatted[:limit]


# Singleton instance
_chroma_client: Optional[ChromaClient] = None


def get_chroma_client() -> ChromaClient:
    """Get singleton ChromaDB client instance."""
    global _chroma_client
    if _chroma_client is None:
        _chroma_client = ChromaClient()
    return _chroma_client
