"""
Error enrichment with context from Airweave.

Enriches error clusters with:
- Related code snippets from GitHub
- Related tickets from Linear
- Documentation from Notion/Confluence
- Comprehensive LLM-generated summary
"""
import logging
import os
from typing import Dict, Any, List, Optional

from schemas import ErrorCluster, EnrichedError, CodeSnippet, RelatedTicket
from clients import get_airweave_client

logger = logging.getLogger(__name__)


class ErrorEnricher:
    """
    Enriches error clusters with context from Airweave.
    
    This is what makes the agent "intelligent" - it pulls in relevant
    context from your codebase, tickets, and docs to help understand
    and resolve errors.
    """
    
    def __init__(self):
        self.airweave = get_airweave_client()
        self._init_llm()
    
    def _init_llm(self):
        """Initialize LLM for summary generation."""
        self.llm = None
        
        # Try Anthropic first
        if os.getenv("ANTHROPIC_API_KEY"):
            try:
                from langchain_anthropic import ChatAnthropic
                model = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")
                self.llm = ChatAnthropic(model=model, temperature=0)
                logger.info(f"Using Anthropic ({model}) for enrichment")
            except Exception as e:
                logger.warning(f"Failed to init Anthropic: {e}")
        
        # Fall back to OpenAI
        if not self.llm and os.getenv("OPENAI_API_KEY"):
            try:
                from langchain_openai import ChatOpenAI
                model = os.getenv("OPENAI_MODEL", "gpt-4o")
                self.llm = ChatOpenAI(model=model, temperature=0)
                logger.info(f"Using OpenAI ({model}) for enrichment")
            except Exception as e:
                logger.warning(f"Failed to init OpenAI: {e}")
        
        if not self.llm:
            logger.warning("No LLM configured - summaries will be basic")
    
    async def enrich(self, cluster: Dict[str, Any]) -> EnrichedError:
        """
        Enrich an error cluster with context.
        
        Args:
            cluster: Error cluster dict
            
        Returns:
            EnrichedError with all context populated
        """
        signature = cluster.get("signature", "")
        module = cluster.get("module")
        function = cluster.get("function")
        sample_messages = cluster.get("sample_messages", [])
        
        logger.info(f"[{signature[:30]}...] Enriching with context")
        
        # Build search query from error info
        search_query = self._build_search_query(signature, module, function, sample_messages)
        
        # Fetch context in parallel (conceptually - we'll do sequential for simplicity)
        code_snippets = await self._search_code(search_query, module)
        related_tickets = await self._search_tickets(search_query, signature)
        documentation = await self._search_docs(search_query)
        
        # Generate comprehensive summary
        comprehensive_summary = await self._generate_summary(
            cluster, code_snippets, related_tickets, documentation
        )
        
        # Build EnrichedError
        return EnrichedError(
            # Copy cluster fields
            signature=signature,
            error_count=cluster.get("error_count", 1),
            affected_orgs=cluster.get("affected_orgs", []),
            org_count=cluster.get("org_count", 0),
            sample_messages=sample_messages,
            modules=cluster.get("modules", []),
            module=module,
            function=function,
            container=cluster.get("container"),
            error_type=cluster.get("error_type"),
            merged_count=cluster.get("merged_count", 0),
            original_signatures=cluster.get("original_signatures", []),
            errors=cluster.get("errors", []),
            # Enrichment fields
            code_snippets=code_snippets,
            related_tickets=related_tickets,
            documentation=documentation,
            comprehensive_summary=comprehensive_summary,
        )
    
    def _build_search_query(
        self,
        signature: str,
        module: Optional[str],
        function: Optional[str],
        sample_messages: List[str],
    ) -> str:
        """Build an effective search query from error info."""
        """
        Error enrichment with context from ChromaDB.

        Enriches error clusters with:
        - Related code snippets from GitHub (via ChromaDB)
        - Related tickets from GitHub issues
        - Comprehensive LLM-generated summary
        """
        import asyncio
        import logging
        import os
        from typing import Dict, Any, List, Optional

        from schemas import ErrorCluster, EnrichedError, CodeSnippet, RelatedTicket
        from clients import ChromaClient
            # Extract error type if present
            if "Error:" in msg:
                error_part = msg.split("Error:")[0].strip().split()[-1]
                if error_part:
                    parts.append(error_part + "Error")
        
        # Dedupe and limit
        seen = set()
            Uses ChromaDB for semantic code/ticket search.
                try:
                    self.chroma = ChromaClient()
                except Exception as e:
                try:
                    self.chroma = ChromaClient()
                except Exception as e:
                    logger.warning(f"Failed to initialize ChromaDB: {e}")
                    self.chroma = None
                    self.chroma = None
                seen.add(p.lower())
                unique_parts.append(p)
        
        query = " ".join(unique_parts[:10])
        logger.debug(f"Built search query: {query}")
        return query
    
    async def _search_code(
        self,
        query: str,
        module: Optional[str] = None,
    ) -> List[CodeSnippet]:
        """Search for related code from GitHub."""
        if not self.airweave.is_configured:
            return self._mock_code_results(module)
        
        results = await self.airweave.search_code(query, module, limit=5)
        
        snippets = []
        for r in results:
            snippets.append(CodeSnippet(
                file_path=r.get("title", "unknown"),
                content=r.get("content", "")[:500],
                url=r.get("url"),
                relevance_score=r.get("score", 0),
            ))
        
        logger.info(f"Found {len(snippets)} code snippets")
        return snippets
    
    async def _search_tickets(
        self,
        query: str,
        signature: str,
    ) -> List[RelatedTicket]:
        """Search for related issues from GitHub Issues."""
        if not self.airweave.is_configured:
            return self._mock_ticket_results()
        
        results = await self.airweave.search_tickets(query, limit=5)
        
        tickets = []
        for r in results:
            tickets.append(RelatedTicket(
                id=r.get("id", ""),
                identifier=r.get("identifier", ""),
                title=r.get("title", "Unknown"),
                status=r.get("status"),
                url=r.get("url"),
                relevance_score=r.get("score", 0),
            ))
        
        logger.info(f"Found {len(tickets)} related tickets")
        return tickets
    
    async def _search_docs(self, query: str) -> List[Dict[str, Any]]:
        """Search for related documentation."""
        if not self.airweave.is_configured:
            return []
        
        results = await self.airweave.search_docs(query, limit=3)
        
        docs = []
        for r in results:
            docs.append({
                "title": r.get("title", "Unknown"),
                "content": r.get("content", "")[:200],
                "source": r.get("source", "unknown"),
                "url": r.get("url"),
            })
        
        logger.info(f"Found {len(docs)} documentation results")
        return docs
    
    async def _generate_summary(
        self,
        cluster: Dict[str, Any],
        code_snippets: List[CodeSnippet],
        related_tickets: List[RelatedTicket],
        documentation: List[Dict[str, Any]],
    ) -> str:
        """
        Generate a comprehensive summary using LLM.
        
        This summary will be used in Linear tickets and Slack alerts.
        """
        if not self.llm:
            return self._basic_summary(cluster)
        
        # Build context for LLM
        context_parts = []
        
        # Error info
        context_parts.append(f"**Error Signature:** {cluster.get('signature', 'Unknown')}")
        context_parts.append(f"**Module:** {cluster.get('module', 'Unknown')}")
        context_parts.append(f"**Function:** {cluster.get('function', 'Unknown')}")
        context_parts.append(f"**Error Count:** {cluster.get('error_count', 1)}")
        context_parts.append(f"**Affected Orgs:** {cluster.get('org_count', 0)}")
        
        # Sample messages
        if cluster.get("sample_messages"):
            context_parts.append("\n**Sample Error Messages:**")
            for i, msg in enumerate(cluster["sample_messages"][:2], 1):
                context_parts.append(f"{i}. {msg[:300]}")
        
        # Code context
        if code_snippets:
            context_parts.append("\n**Related Code:**")
            for snippet in code_snippets[:2]:
                context_parts.append(f"- {snippet.file_path}: {snippet.content[:150]}...")
        
        # Ticket context
        if related_tickets:
            context_parts.append("\n**Related Tickets:**")
            for ticket in related_tickets[:2]:
                context_parts.append(f"- [{ticket.identifier}] {ticket.title} ({ticket.status})")
        
        context = "\n".join(context_parts)
        
        prompt = f"""Analyze this error and provide a comprehensive summary for a support ticket.

{context}

Write a clear, actionable summary in markdown format that includes:
1. **What happened** - Brief description of the error
2. **Impact** - Who is affected and how
3. **Likely cause** - Based on the error and code context
4. **Suggested investigation** - Next steps to diagnose/fix

Keep it concise (under 300 words). Focus on actionable information."""

        try:
            response = await self.llm.ainvoke(prompt)
            summary = response.content if hasattr(response, 'content') else str(response)
            logger.info("Generated comprehensive summary")
            return summary
        except Exception as e:
            logger.error(f"Failed to generate summary: {e}")
            return self._basic_summary(cluster)
    
    def _basic_summary(self, cluster: Dict[str, Any]) -> str:
        """Generate a basic summary without LLM."""
        return f"""## Error Summary

**Signature:** {cluster.get('signature', 'Unknown')}

**Location:** `{cluster.get('module', 'unknown')}.{cluster.get('function', 'unknown')}`

**Impact:** {cluster.get('error_count', 1)} occurrences affecting {cluster.get('org_count', 0)} organizations.

**Sample Message:**
```
{cluster.get('sample_messages', ['No message available'])[0][:300]}
```

*This is a basic summary. Configure an LLM for more detailed analysis.*"""
    
    def _mock_code_results(self, module: Optional[str]) -> List[CodeSnippet]:
        """Generate mock code results for demo."""
        if not module:
            return []
        
        return [
            CodeSnippet(
                file_path=f"backend/{module.replace('.', '/')}.py",
                content=f"# Code from {module}\n# (Demo: Connect Airweave to see real code)",
                url=None,
                relevance_score=0.8,
            )
        ]
    
    def _mock_ticket_results(self) -> List[RelatedTicket]:
        """Generate mock ticket results for demo."""
        return [
            RelatedTicket(
                id="demo-ticket-1",
                identifier="DEMO-001",
                title="[Demo] Similar error pattern",
                status="Open",
                url=None,
                relevance_score=0.7,
            )
        ]


# Singleton
_enricher: Optional[ErrorEnricher] = None


def get_enricher() -> ErrorEnricher:
    """Get singleton enricher instance."""
    global _enricher
    if _enricher is None:
        _enricher = ErrorEnricher()
    return _enricher
