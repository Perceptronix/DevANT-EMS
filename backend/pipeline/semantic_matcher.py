"""
Semantic matching for errors against existing tickets and mutes.

Uses LLM to determine if an error matches:
- An existing Linear ticket (to avoid duplicates)
- An existing mute rule (to suppress alerts)

This is more robust than exact string matching because error messages
can vary slightly while referring to the same underlying issue.
"""
import logging
import os
from typing import List, Dict, Any, Optional, Tuple

from schemas import RelatedTicket, PreviousErrorState
from state import get_state_manager

logger = logging.getLogger(__name__)


class SemanticMatcher:
    """
    LLM-powered semantic matching for errors.
    
    Determines if an error:
    1. Matches an existing open ticket (to avoid duplicates)
    2. Matches a mute rule (to suppress alerts)
    """
    
    def __init__(self):
        self.state = get_state_manager()
        self._init_llm()
    
    def _init_llm(self):
        """Initialize LLM for semantic matching."""
        self.llm = None
        
        # Try Anthropic first
        if os.getenv("ANTHROPIC_API_KEY"):
            try:
                from langchain_anthropic import ChatAnthropic
                model = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")
                self.llm = ChatAnthropic(model=model, temperature=0)
                logger.info(f"Using Anthropic ({model}) for semantic matching")
            except Exception as e:
                logger.warning(f"Failed to init Anthropic: {e}")
        
        # Fall back to OpenAI
        if not self.llm and os.getenv("OPENAI_API_KEY"):
            try:
                from langchain_openai import ChatOpenAI
                model = os.getenv("OPENAI_MODEL", "gpt-4o")
                self.llm = ChatOpenAI(model=model, temperature=0)
                logger.info(f"Using OpenAI ({model}) for semantic matching")
            except Exception as e:
                logger.warning(f"Failed to init OpenAI: {e}")
        
        if not self.llm:
            logger.warning("No LLM configured - using exact matching only")
    
    async def find_matching_ticket(
        self,
        signature: str,
        sample_messages: List[str],
        related_tickets: List[RelatedTicket],
    ) -> Tuple[Optional[RelatedTicket], bool]:
        """
        Find a matching ticket for this error.
        
        Returns the best matching ticket and whether it's relevant.
        A ticket is "relevant" if it's about the same issue AND still open.
        
        Args:
            signature: Error signature
            sample_messages: Sample error messages
            related_tickets: Tickets from Airweave search
            
        Returns:
            Tuple of (matched_ticket, has_relevant_ticket)
        """
        if not related_tickets:
            return None, False
        
        # First, try exact signature match in state
        prev_state = self.state.get_signature(signature)
        if prev_state and prev_state.linear_issue_id:
            # Find that ticket in related_tickets
            for ticket in related_tickets:
                if ticket.id == prev_state.linear_issue_id:
                    is_open = self._is_ticket_open(ticket.status)
                    logger.info(
                        f"Found exact ticket match: {ticket.identifier} "
                        f"(status: {ticket.status}, open: {is_open})"
                    )
                    return ticket, is_open
        
        # Use LLM to find semantic match
        if self.llm and related_tickets:
            match = await self._llm_find_match(signature, sample_messages, related_tickets)
            if match:
                is_open = self._is_ticket_open(match.status)
                return match, is_open
        
        # Fallback: Use highest scoring ticket if score > threshold
        best_ticket = max(related_tickets, key=lambda t: t.relevance_score or 0)
        if (best_ticket.relevance_score or 0) > 0.8:
            is_open = self._is_ticket_open(best_ticket.status)
            logger.info(
                f"High-confidence match: {best_ticket.identifier} "
                f"(score: {best_ticket.relevance_score})"
            )
            return best_ticket, is_open
        
        return None, False
    
    async def _llm_find_match(
        self,
        signature: str,
        sample_messages: List[str],
        related_tickets: List[RelatedTicket],
    ) -> Optional[RelatedTicket]:
        """Use LLM to find the best matching ticket."""
        # Build prompt
        tickets_text = "\n".join([
            f"{i+1}. [{t.identifier}] {t.title} (status: {t.status})"
            for i, t in enumerate(related_tickets[:5])
        ])
        
        sample_msg = sample_messages[0][:300] if sample_messages else "No sample message"
        
        prompt = f"""Determine if any of these tickets are about the SAME error/issue.

ERROR:
Signature: {signature}
Sample message: {sample_msg}

CANDIDATE TICKETS:
{tickets_text}

If one of these tickets is clearly about the same underlying issue/error, respond with ONLY the ticket number (1-5).
If none match, respond with "NONE".

Consider:
- Same module/function involved
- Same error type
- Same root cause (even if messages differ slightly)

Response (just the number or NONE):"""

        try:
            response = await self.llm.ainvoke(prompt)
            answer = response.content.strip() if hasattr(response, 'content') else str(response).strip()
            
            if answer.upper() == "NONE":
                return None
            
            # Parse ticket number
            try:
                idx = int(answer.replace(".", "").strip()) - 1
                if 0 <= idx < len(related_tickets):
                    matched = related_tickets[idx]
                    logger.info(f"LLM matched ticket: {matched.identifier}")
                    return matched
            except ValueError:
                pass
            
            return None
            
        except Exception as e:
            logger.error(f"LLM ticket matching failed: {e}")
            return None
    
    def _is_ticket_open(self, status: Optional[str]) -> bool:
        """Check if a ticket status indicates it's still open."""
        if not status:
            return False
        
        status_lower = status.lower()
        
        # Closed states
        closed_states = [
            "completed", "done", "closed",
            "canceled", "cancelled",
            "finished", "resolved", "fixed",
            "wontfix", "won't fix",
            "rejected", "duplicate",
        ]
        
        return status_lower not in closed_states
    
    async def check_mute_match(
        self,
        signature: str,
        sample_messages: List[str],
    ) -> Tuple[bool, Optional[str]]:
        """
        Check if this error matches any active mute rules.
        
        Supports both exact matching and semantic matching.
        
        Args:
            signature: Error signature
            sample_messages: Sample error messages
            
        Returns:
            Tuple of (is_muted, mute_reason)
        """
        # First, check exact match
        if self.state.is_muted(signature):
            mute_info = self.state.get_mute_info(signature)
            reason = mute_info.get("reason", "Exact signature muted")
            return True, reason
        
        # Get all active mutes
        mutes = self.state.get_active_mutes()
        if not mutes:
            return False, None
        
        # Check for semantic match using LLM
        if self.llm and mutes:
            is_match, matched_sig = await self._llm_check_mutes(
                signature, sample_messages, list(mutes.keys())
            )
            if is_match and matched_sig:
                mute_info = mutes.get(matched_sig, {})
                reason = mute_info.get("reason", f"Semantically matches muted: {matched_sig[:50]}")
                return True, reason
        
        return False, None
    
    async def _llm_check_mutes(
        self,
        signature: str,
        sample_messages: List[str],
        muted_signatures: List[str],
    ) -> Tuple[bool, Optional[str]]:
        """Use LLM to check if error matches any mute."""
        # Build prompt
        mutes_text = "\n".join([
            f"{i+1}. {sig[:100]}"
            for i, sig in enumerate(muted_signatures[:10])
        ])
        
        sample_msg = sample_messages[0][:200] if sample_messages else ""
        
        prompt = f"""Determine if this error should be suppressed by any of these mute rules.

CURRENT ERROR:
{signature}
{sample_msg}

MUTED ERROR SIGNATURES:
{mutes_text}

If the current error is essentially the SAME as one of the muted signatures (same root cause, same error type), respond with the mute number (1-10).
If the error doesn't match any mute, respond with "NONE".

Response (just the number or NONE):"""

        try:
            response = await self.llm.ainvoke(prompt)
            answer = response.content.strip() if hasattr(response, 'content') else str(response).strip()
            
            if answer.upper() == "NONE":
                return False, None
            
            # Parse mute number
            try:
                idx = int(answer.replace(".", "").strip()) - 1
                if 0 <= idx < len(muted_signatures):
                    return True, muted_signatures[idx]
            except ValueError:
                pass
            
            return False, None
            
        except Exception as e:
            logger.error(f"LLM mute matching failed: {e}")
            return False, None


# Singleton
_matcher: Optional[SemanticMatcher] = None


def get_semantic_matcher() -> SemanticMatcher:
    """Get singleton semantic matcher instance."""
    global _matcher
    if _matcher is None:
        _matcher = SemanticMatcher()
    return _matcher
