"""
Multi-stage error clustering.

Groups similar errors together using a three-stage approach:
1. Strict clustering (exact module+function+line match)
2. Regex-based clustering (error_type+module+function)
3. LLM semantic clustering (for remaining similar errors)

This multi-stage approach reduces LLM calls while still catching
semantically similar errors that strict matching would miss.
"""
import os
import re
import asyncio
import logging
from collections import defaultdict
from typing import List, Dict, Any, Optional, Tuple

from pydantic import BaseModel, Field

from config import get_config
from core.identity import incident_identity

logger = logging.getLogger(__name__)


class ClusterGroup(BaseModel):
    """LLM output for grouping similar errors."""
    groups: List[List[int]] = Field(description="List of groups, where each group contains indices of similar errors")
    reasoning: str = Field(description="Brief explanation of the clustering logic")


class ClusterSummary(BaseModel):
    """LLM-generated summary for a merged error cluster."""
    signature: str = Field(description="Natural language signature (50-150 chars) explaining what's happening")
    description: str = Field(description="Technical description with context about the error pattern")


class ErrorClusterer:
    """
    Multi-stage error clustering to reduce alert noise.
    
    Three-stage approach:
    1. Strict: Exact module+function+line match
    2. Regex: error_type+module+function match
    3. LLM: Semantic similarity for remaining clusters
    
    This groups errors like:
    - "HTTP 429 downloading file A" + "HTTP 429 downloading file B" 
      → "Rate limiting errors during file downloads"
    """
    
    def __init__(self):
        self.last_reasoning: Optional[str] = None
        self._init_llm()
    
    def _init_llm(self):
        """Initialize the LLM client."""
        cfg = get_config()

        if not cfg.groq.is_configured:
            raise RuntimeError("Groq provider not configured")

        try:
            from langchain_groq import ChatGroq

            self.llm = ChatGroq(
                api_key=cfg.groq.api_key,
                model_name=cfg.groq.model,
                temperature=0,
            )
            self.provider = "groq"
            logger.info("LLM provider initialized: groq")
        except Exception as e:
            raise RuntimeError(f"Groq initialization failed: {e}")
    
    async def cluster_errors(self, errors: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Cluster similar errors together using multi-stage approach.
        
        Stage 1: Strict clustering (exact module+function+line)
        Stage 2: Regex clustering (error_type+module+function)
        Stage 3: LLM semantic clustering (remaining similar errors)
        
        Args:
            errors: List of raw error dictionaries
            
        Returns:
            List of clustered error groups with signatures
        """
        if not errors:
            return []
        
        await asyncio.sleep(0.001)

        if len(errors) == 1:
            cluster = self._create_cluster([errors[0]])
            self.last_reasoning = "Single error - no clustering needed"
            return [cluster]
        
        reasoning_parts = []
        
        # Stage 1: Strict clustering
        strict_clusters, remaining = self._strict_cluster(errors)
        reasoning_parts.append(f"Stage 1 (strict): {len(errors)} → {len(strict_clusters)} clusters, {len(remaining)} remaining")
        
        # Stage 2: Regex clustering on remaining
        if remaining:
            regex_clusters, remaining = self._regex_cluster(remaining)
            reasoning_parts.append(f"Stage 2 (regex): {len(regex_clusters)} clusters, {len(remaining)} remaining")
        else:
            regex_clusters = []
        
        # Stage 3: LLM semantic clustering on remaining (if > 1)
        if len(remaining) > 1 and self.llm:
            try:
                llm_clusters = await self._llm_cluster(remaining)
                reasoning_parts.append(f"Stage 3 (LLM): {len(remaining)} → {len(llm_clusters)} clusters")
            except Exception as e:
                logger.error(f"LLM clustering failed: {e}")
                # Fallback: each remaining error is its own cluster
                llm_clusters = [self._create_cluster([e]) for e in remaining]
                reasoning_parts.append(f"Stage 3 (fallback): {len(remaining)} → {len(llm_clusters)} clusters")
        elif remaining:
            # No LLM, each remaining error is its own cluster
            llm_clusters = [self._create_cluster([e]) for e in remaining]
            reasoning_parts.append(f"Stage 3 (no LLM): {len(remaining)} individual clusters")
        else:
            llm_clusters = []
        
        # Combine all clusters
        all_clusters = strict_clusters + regex_clusters + llm_clusters
        
        # Stage 4: Merge similar clusters
        if len(all_clusters) > 3:
            if self.llm:
                try:
                    merged = await self._merge_similar_clusters(all_clusters)
                    reasoning_parts.append(f"Stage 4 (LLM merge): {len(all_clusters)} → {len(merged)} clusters")
                    all_clusters = merged
                except Exception as e:
                    logger.warning(f"LLM cluster merging failed: {e}")
            else:
                # Fallback: merge clusters with same error type
                merged = self._fallback_merge_clusters(all_clusters)
                if len(merged) < len(all_clusters):
                    reasoning_parts.append(f"Stage 4 (type merge): {len(all_clusters)} → {len(merged)} clusters")
                    all_clusters = merged
        
        self.last_reasoning = " | ".join(reasoning_parts)
        logger.info(f"Clustering complete: {self.last_reasoning}")
        
        return all_clusters
    
    def _strict_cluster(self, errors: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """
        Stage 1: Strict clustering by exact module+function+line.
        
        NOTE: For better demo results, we skip strict clustering and let 
        the regex (error-type) clustering handle everything. This produces
        more intuitive clusters like "all rate limit errors" vs "all DB errors".
        
        Returns:
            Tuple of (clusters, remaining_errors)
        """
        # Skip strict clustering - pass all errors to regex stage
        # This gives better semantic grouping for the demo
        return [], errors
    
    def _regex_cluster(self, errors: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """
        Stage 2: Regex-based clustering by error_type only.
        
        This groups all similar error types together regardless of module/function,
        which produces better clustering for demo purposes.
        
        Returns:
            Tuple of (clusters, remaining_errors)
        """
        groups = defaultdict(list)
        
        for error in errors:
            # Just use error_type for broader clustering
            error_type = self._extract_error_type(error.get("message", ""))
            groups[error_type].append(error)
        
        clusters = []
        remaining = []
        
        for key, group_errors in groups.items():
            if len(group_errors) >= 2:
                cluster = self._create_cluster(group_errors)
                clusters.append(cluster)
            else:
                remaining.extend(group_errors)
        
        return clusters, remaining
    
    def _extract_error_type(self, message: str) -> str:
        """Extract error type from message using regex patterns.
        
        More specific patterns are checked first to enable proper semantic grouping.
        All patterns are lowercase since we search against lowercase message.
        """
        msg_lower = message.lower()
        
        # Check semantic patterns first (more specific, before generic HTTP codes)
        # All patterns must be lowercase to match against msg_lower
        semantic_patterns = [
            # Rate limiting - various APIs
            (r'(429|rate.?limit|ratelimited|too many requests|quota exceeded)', "RateLimit"),
            # Authentication/OAuth failures
            (r'(401|unauthorized|invalid_grant|token.*expired|token.*revoked|auth.*fail)', "Auth"),
            # Database/connection pool issues
            (r'(pool.*exhaust|connection.*pool|operationalerror|psycopg2|connection.*timeout|connection.*refused)', "Database"),
            # Document processing failures (PDF, DOCX, etc.)
            (r'(pdfreaderror|pdfread|\.pdf|docx|packagenotfounderror|corrupted|eof marker|empty file)', "DocumentProcessing"),
            # Memory issues
            (r'(memoryerror|oom|outofmemory|cannot allocate|memory limit)', "Memory"),
            # Timeouts
            (r'(timeout|timed? ?out)', "Timeout"),
            # Service unavailable
            (r'(502|503|504|bad gateway|service unavailable|upstream)', "ServiceUnavailable"),
            # Generic server errors
            (r'(500|internal server error)', "ServerError"),
            # Not found
            (r'(404|not found)', "NotFound"),
            # Parse/format errors
            (r'(parse|json|decode|format)', "Parse"),
        ]
        
        for pattern, error_type in semantic_patterns:
            if re.search(pattern, msg_lower):
                return error_type
        
        # Fallback: extract exception class name if present
        class_match = re.search(r'(\w+Error|\w+Exception):', message)
        if class_match:
            return class_match.group(1)[:20]
        
        # Last fallback: first word
        first_word = message.split()[0] if message else "Unknown"
        return first_word[:20]
    
    async def _merge_similar_clusters(self, clusters: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Use LLM to merge semantically similar clusters.
        
        This catches cases where Stage 1+2 created separate clusters
        that are actually the same underlying issue.
        """
        if len(clusters) <= 1:
            return clusters
        
        from langchain_core.prompts import ChatPromptTemplate
        from langchain_core.output_parsers import JsonOutputParser
        
        # Build cluster descriptions
        cluster_descs = []
        for idx, cluster in enumerate(clusters):
            sig = cluster.get("signature", "Unknown")
            count = cluster.get("error_count", 1)
            sample = cluster.get("sample_messages", cluster.get("errors", [{}]))[0]
            if isinstance(sample, dict):
                sample = sample.get("message", "")[:100]
            else:
                sample = str(sample)[:100]
            
            cluster_descs.append(f"{idx}. [{count} errors] {sig}\n   Sample: {sample}")
        
        prompt = ChatPromptTemplate.from_messages([
            ("system", """You are merging error clusters that represent the SAME underlying issue.

Only merge clusters if they are CLEARLY the same root cause. When in doubt, don't merge.

Examples to MERGE:
- "HTTP 429 in sync_worker" + "Rate limit errors in sync" → Same issue
- "DB timeout in api" + "Database connection timeout" → Same issue

Examples NOT to merge:
- "HTTP 429 rate limit" + "HTTP 500 server error" → Different errors
- "Timeout in sync" + "Timeout in auth" → Different modules

Return JSON: {{"groups": [[0, 2], [1], [3, 4, 5]], "reasoning": "..."}}
Each group contains cluster indices that should be merged."""),
            ("user", "Merge these clusters:\n\n{clusters}")
        ])
        
        parser = JsonOutputParser()
        chain = prompt | self.llm | parser
        
        result = await chain.ainvoke({"clusters": "\n".join(cluster_descs)})
        
        # Build merged clusters
        merged = []
        for group in result.get("groups", []):
            if len(group) == 1:
                merged.append(clusters[group[0]])
            else:
                # Merge multiple clusters
                all_errors = []
                original_sigs = []
                for idx in group:
                    if idx < len(clusters):
                        c = clusters[idx]
                        all_errors.extend(c.get("errors", []))
                        original_sigs.append(c.get("signature", ""))
                
                if all_errors:
                    new_cluster = self._create_cluster(all_errors)
                    # Generate merged signature
                    new_cluster["signature"] = await self._generate_signature(all_errors)
                    new_cluster["merged_count"] = len(group)
                    new_cluster["original_signatures"] = original_sigs
                    merged.append(new_cluster)
        
        return merged
    
    def _fallback_merge_clusters(self, clusters: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Fallback merge for when LLM isn't available.
        
        Merges clusters that have the same error type based on their signatures.
        """
        # Group clusters by their inferred error type
        type_groups: Dict[str, List[int]] = defaultdict(list)
        
        for idx, cluster in enumerate(clusters):
            sig = cluster.get("signature", "")
            sample_msg = cluster.get("sample_message", sig)
            error_type = self._extract_error_type(sample_msg)
            type_groups[error_type].append(idx)
        
        # Build merged clusters
        merged = []
        for error_type, indices in type_groups.items():
            if len(indices) == 1:
                merged.append(clusters[indices[0]])
            else:
                # Merge multiple clusters of same error type
                all_errors = []
                for idx in indices:
                    all_errors.extend(clusters[idx].get("errors", []))
                
                if all_errors:
                    new_cluster = self._create_cluster(all_errors)
                    new_cluster["merged_count"] = len(indices)
                    merged.append(new_cluster)
        
        return merged
    
    async def _llm_cluster(self, errors: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Use LLM to semantically cluster errors."""
        from langchain_core.prompts import ChatPromptTemplate
        from langchain_core.output_parsers import JsonOutputParser
        
        # Build error descriptions for the LLM
        error_descriptions = []
        for idx, error in enumerate(errors):
            error_descriptions.append(
                f"{idx}. [{error.get('level', 'ERROR')}] {error.get('module', 'unknown')}.{error.get('function', 'unknown')}\n"
                f"   Message: {error.get('message', '')[:200]}\n"
                f"   Org: {error.get('org_name', 'Unknown')}"
            )
        
        error_list = "\n\n".join(error_descriptions)
        
        # Clustering prompt
        parser = JsonOutputParser(pydantic_object=ClusterGroup)
        
        prompt = ChatPromptTemplate.from_messages([
            ("system", """You are clustering error logs to group semantically similar errors together.

Errors should be GROUPED if they represent the same underlying issue, even if specific details differ.

Examples of errors that SHOULD be grouped:
- "HTTP 429 downloading file report.pdf" + "HTTP 429 downloading file invoice.xlsx" → Same issue (rate limiting)
- "Timeout in process_batch" + "Timeout in batch_processor" → Same issue (timeout in batch processing)
- "ConnectionError to database" + "DB connection failed" → Same issue (database connection)

Examples of errors that should NOT be grouped:
- "HTTP 429 rate limit" + "HTTP 500 internal error" → Different HTTP errors
- "Timeout in sync" + "ValueError in sync" → Different error types

{format_instructions}"""),
            ("user", """Group these errors:

{error_list}

Return groups as lists of indices. Each group contains errors that are semantically the same.
Example: {{"groups": [[0, 1, 3], [2], [4, 5]], "reasoning": "..."}}""")
        ])
        
        chain = prompt | self.llm | parser
        
        result = await chain.ainvoke({
            "format_instructions": parser.get_format_instructions(),
            "error_list": error_list,
        })
        
        cluster_result = ClusterGroup(**result)
        self.last_reasoning = cluster_result.reasoning
        
        logger.info(f"LLM clustering: {len(errors)} errors → {len(cluster_result.groups)} groups")
        logger.info(f"Reasoning: {cluster_result.reasoning}")
        
        # Build clusters from groups
        clusters = []
        for group in cluster_result.groups:
            if not group:
                continue
            
            group_errors = [errors[i] for i in group if i < len(errors)]
            if not group_errors:
                continue
            
            # Generate signature for the cluster
            if len(group_errors) > 1:
                signature = await self._generate_signature(group_errors)
            else:
                signature = self._extract_signature(group_errors[0])
            
            cluster = self._create_cluster(group_errors, signature)
            clusters.append(cluster)
        
        return clusters
    
    async def _generate_signature(self, errors: List[Dict[str, Any]]) -> str:
        """Generate a natural language signature for a cluster of errors."""
        from langchain_core.prompts import ChatPromptTemplate
        from langchain_core.output_parsers import JsonOutputParser
        
        parser = JsonOutputParser(pydantic_object=ClusterSummary)
        
        error_summaries = []
        for error in errors[:5]:  # Limit to 5 for context window
            error_summaries.append(f"- {error.get('message', '')[:150]}")
        
        prompt = ChatPromptTemplate.from_messages([
            ("system", """Create a natural language signature for this cluster of similar errors.

The signature should:
- Be 50-150 characters
- Clearly describe what's happening
- Be useful for matching against existing tickets
- Focus on the root cause, not specific variable data

Good examples:
- "Rate limiting errors (HTTP 429) during file downloads from external storage"
- "Database connection timeouts in sync worker batch processing"
- "OAuth token refresh failures for user integrations"

{format_instructions}"""),
            ("user", """Create a signature for these errors:

{errors}""")
        ])
        
        chain = prompt | self.llm | parser
        
        try:
            result = await chain.ainvoke({
                "format_instructions": parser.get_format_instructions(),
                "errors": "\n".join(error_summaries),
            })
            summary = ClusterSummary(**result)
            return summary.signature
        except Exception as e:
            logger.error(f"Failed to generate signature: {e}")
            return self._extract_signature(errors[0])
    
    def _extract_signature(self, error: Dict[str, Any]) -> str:
        """Extract a simple signature from a single error."""
        message = error.get("message", "Unknown error")
        module = error.get("module", "unknown")
        
        # Extract error type from message
        if "HTTP" in message:
            # Extract HTTP code
            import re
            match = re.search(r'HTTP (\d{3})', message)
            if match:
                return f"HTTP {match.group(1)} error in {module}"
        
        if "timeout" in message.lower():
            return f"Timeout error in {module}"
        
        if "connection" in message.lower():
            return f"Connection error in {module}"
        
        # Fallback: first 80 chars of message
        return message[:80]
    
    def _create_cluster(self, errors: List[Dict[str, Any]], signature: Optional[str] = None) -> Dict[str, Any]:
        """Create a cluster dictionary from a list of errors."""
        if signature is None:
            signature = self._extract_signature(errors[0])
        
        # Collect unique sample messages (up to 5)
        sample_messages = []
        seen_msgs = set()
        for e in errors:
            msg = e.get("message", "")[:300]
            if msg and msg not in seen_msgs:
                sample_messages.append(msg)
                seen_msgs.add(msg)
                if len(sample_messages) >= 5:
                    break
        
        # Get primary error info from first error
        primary = errors[0]
        
        return {
            "id": incident_identity(primary),
            "signature": signature,
            "error_count": len(errors),
            "errors": errors,
            "affected_orgs": list(set(e.get("org_name", "Unknown") for e in errors if e.get("org_name"))),
            "org_count": len(set(e.get("org_id") or e.get("org_name", "Unknown") for e in errors)),
            "modules": list(set(e.get("module", "unknown") for e in errors)),
            "module": primary.get("module"),
            "function": primary.get("function"),
            "container": primary.get("container"),
            "error_type": self._extract_error_type(primary.get("message", "")),
            "sample_messages": sample_messages,
            "merged_count": 0,
            "original_signatures": [],
        }
    
    def _fallback_clustering(self, errors: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Fallback clustering by module + error type."""
        from collections import defaultdict
        
        groups = defaultdict(list)
        
        for error in errors:
            # Group by module and first word of error (e.g., "HTTP", "Timeout", etc.)
            module = error.get("module", "unknown")
            message = error.get("message", "")
            error_type = message.split()[0] if message else "Unknown"
            
            key = f"{module}:{error_type}"
            groups[key].append(error)
        
        clusters = []
        for key, group_errors in groups.items():
            cluster = self._create_cluster(group_errors)
            clusters.append(cluster)
        
        self.last_reasoning = f"Fallback clustering by module + error type: {len(errors)} errors → {len(clusters)} clusters"
        return clusters
