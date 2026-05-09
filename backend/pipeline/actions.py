"""
Execute actions: create/update GitHub issues, post Slack alerts, update state.

This module orchestrates all external actions after analysis is complete.
Actions are based on error status (NEW, REGRESSION, ONGOING) and whether
a relevant issue already exists.
"""
import logging
from datetime import datetime
from typing import Dict, Any, List, Optional

from schemas import AnalyzedError, ErrorResult, LinearTicketResult, SlackMessageResult
from state import get_state_manager
from clients import get_github_issues_client, get_slack_client

logger = logging.getLogger(__name__)


class ActionExecutor:
    """
    Executes alerting actions based on analysis results.
    
    Handles:
    - GitHub issue creation/update/commenting
    - Slack alert posting
    - State updates
    """
    
    def __init__(self):
        self.state = get_state_manager()
        self.issues = get_github_issues_client()
        self.slack = get_slack_client()
    
    async def execute(self, error: AnalyzedError) -> ErrorResult:
        """
        Execute all actions for an analyzed error.
        
        Actions depend on status and suppression:
        - If should_alert is False: Skip alerting, just update state
        - NEW: Create GitHub issue + Post Slack alert
        - REGRESSION: Reopen/comment on GitHub issue + Post Slack alert
        - ONGOING (with issue): Add comment to GitHub issue + Thread reply in Slack
        - ONGOING (no issue): Create GitHub issue + Post Slack alert
        
        Args:
            error: Analyzed error with all context
            
        Returns:
            ErrorResult with action results
        """
        signature = error.signature
        actions_taken = []
        
        logger.info(f"[{signature[:30]}...] Executing actions (status={error.status}, should_alert={error.should_alert})")
        
        # Initialize results
        linear_result = None
        slack_result = None
        
        # If suppressed, just record the occurrence
        if not error.should_alert:
            logger.info(f"[{signature[:30]}...] Suppressed: {error.suppression_reason}")
            actions_taken.append(f"suppressed: {error.suppression_reason}")
            
            # Still update state to track occurrence
            self.state.upsert_signature(signature, {
                "last_severity": error.severity,
            })
        else:
            # Execute GitHub issue actions
            linear_result = await self._execute_issue_actions(error)
            if linear_result:
                actions_taken.append(f"issue_{linear_result.action}")
            
            # Execute Slack actions
            slack_result = await self._execute_slack_actions(error, linear_result)
            if slack_result:
                actions_taken.append(f"slack_{slack_result.action}")
            
            # Update state with results
            self._update_state(error, linear_result, slack_result)
        
        logger.info(f"[{signature[:30]}...] Actions completed: {actions_taken}")
        
        # Build ErrorResult
        return ErrorResult(
            # Copy all fields from AnalyzedError
            signature=error.signature,
            error_count=error.error_count,
            affected_orgs=error.affected_orgs,
            org_count=error.org_count,
            sample_messages=error.sample_messages,
            modules=error.modules,
            module=error.module,
            function=error.function,
            container=error.container,
            error_type=error.error_type,
            merged_count=error.merged_count,
            original_signatures=error.original_signatures,
            errors=error.errors,
            previous_state=error.previous_state,
            code_snippets=error.code_snippets,
            related_tickets=error.related_tickets,
            documentation=error.documentation,
            comprehensive_summary=error.comprehensive_summary,
            status=error.status,
            severity=error.severity,
            severity_reasoning=error.severity_reasoning,
            is_critical=error.is_critical,
            root_cause=error.root_cause,
            impact=error.impact,
            suggested_action=error.suggested_action,
            matched_ticket=error.matched_ticket,
            has_relevant_ticket=error.has_relevant_ticket,
            is_muted=error.is_muted,
            should_alert=error.should_alert,
            suppression_reason=error.suppression_reason,
            # Action results
            linear_ticket=linear_result,
            slack_message=slack_result,
            actions_taken=actions_taken,
        )
    
    async def _execute_issue_actions(self, error: AnalyzedError) -> Optional[LinearTicketResult]:
        """Execute GitHub issue actions."""
        signature = error.signature
        status = error.status
        prev_state = error.previous_state
        
        # NEW or ONGOING without a relevant issue: Create new issue
        if status == "NEW" or (status == "ONGOING" and not error.has_relevant_ticket):
            logger.info(f"[{signature[:30]}...] Creating new GitHub issue")
            
            ticket = await self.issues.create_issue(
                title=f"[{error.severity}] {signature[:80]}",
                body=self._build_ticket_description(error),
                labels=["bug", "monitoring", error.severity.lower()],
            )
            
            return LinearTicketResult(
                id=ticket.id,
                identifier=ticket.identifier,
                title=ticket.title,
                url=ticket.url,
                status=ticket.status,
                action="created",
                is_preview=ticket.is_preview,
            )
        
        # REGRESSION: Reopen/comment on existing issue
        elif status == "REGRESSION" and prev_state.linear_issue_id:
            logger.info(f"[{signature[:30]}...] Reopening issue for regression: {prev_state.linear_issue_id}")
            
            # Add comment about regression
            comment = f"""## Regression Detected

This error has reoccurred after being marked as resolved.

**Current Impact:**
- Organizations: {error.org_count}
- Errors: {error.error_count}
- Severity: {error.severity}

**Root Cause:** {error.root_cause or 'Under investigation'}
"""
            await self.issues.comment_on_issue(prev_state.linear_issue_id, comment)
            await self.issues.update_issue(
                prev_state.linear_issue_id,
                labels=["bug", "monitoring", error.severity.lower(), "regression"],
            )
            
            return LinearTicketResult(
                id=prev_state.linear_issue_id,
                identifier=prev_state.linear_issue_id[:8],
                title=f"[{error.severity}] {signature[:80]}",
                url=prev_state.linear_issue_url or f"https://github.com/{self.issues.owner}/{self.issues.repo}/issues/{prev_state.linear_issue_id}",
                status="Open",
                action="reopened",
                is_preview=False,
            )
        
        # ONGOING with issue: Add comment
        elif status == "ONGOING" and error.has_relevant_ticket:
            ticket_id = prev_state.linear_issue_id
            if ticket_id:
                logger.info(f"[{signature[:30]}...] Adding comment to existing issue: {ticket_id}")
                
                comment = f"Error continues. {error.error_count} occurrences affecting {error.org_count} organizations."
                await self.issues.comment_on_issue(ticket_id, comment)
                await self.issues.update_issue(
                    ticket_id,
                    labels=["bug", "monitoring", error.severity.lower(), "ongoing"],
                )
                
                return LinearTicketResult(
                    id=ticket_id,
                    identifier=ticket_id[:8],
                    title=f"[{error.severity}] {signature[:80]}",
                    url=prev_state.linear_issue_url or f"https://github.com/{self.issues.owner}/{self.issues.repo}/issues/{ticket_id}",
                    status=prev_state.linear_issue_status or "Unknown",
                    action="commented",
                    is_preview=False,
                )
        
        return None
    
    async def _execute_slack_actions(
        self, 
        error: AnalyzedError,
        linear_result: Optional[LinearTicketResult],
    ) -> Optional[SlackMessageResult]:
        """Execute Slack alert actions."""
        signature = error.signature
        prev_state = error.previous_state
        
        # NEW or REGRESSION: Post new alert
        if error.status in ["NEW", "REGRESSION"] or not prev_state.slack_thread_ts:
            logger.info(f"[{signature[:30]}...] Posting Slack alert")
            
            message = await self.slack.post_alert(
                signature=signature,
                severity=error.severity,
                root_cause=error.root_cause or "Error detected - investigating",
                affected_orgs=error.affected_orgs,
                linear_ticket=linear_result,
                error_count=error.error_count,
            )
            
            return SlackMessageResult(
                channel=message.channel,
                thread_ts=message.thread_ts,
                message_ts=message.message_ts,
                action="posted",
                is_preview=message.is_preview,
            )
        
        # ONGOING: Thread reply
        elif prev_state.slack_thread_ts:
            logger.info(f"[{signature[:30]}...] Posting thread reply")
            
            reply_text = f"Error continues ({error.error_count} hits, {error.org_count} orgs affected)"
            success = await self.slack.post_thread_reply(prev_state.slack_thread_ts, reply_text)
            
            if success:
                return SlackMessageResult(
                    channel=self.slack.channel_id or "preview",
                    thread_ts=prev_state.slack_thread_ts,
                    action="replied",
                    is_preview=not self.slack.is_configured,
                )
        
        return None
    
    def _update_state(
        self,
        error: AnalyzedError,
        linear_result: Optional[LinearTicketResult],
        slack_result: Optional[SlackMessageResult],
    ):
        """Update state after actions."""
        signature = error.signature
        updates = {
            "last_alerted": datetime.utcnow().isoformat(),
            "last_severity": error.severity,
            "last_summary": {
                "severity": error.severity,
                "root_cause": error.root_cause,
                "impact": error.impact,
                "status": error.status,
                "org_count": error.org_count,
                "error_count": error.error_count,
            },
        }
        
        # Update issue tracking
        if linear_result and not linear_result.is_preview:
            updates["linear_issue_id"] = linear_result.id
            updates["linear_issue_status"] = linear_result.status
            updates["linear_issue_url"] = linear_result.url
        
        # Update Slack tracking
        if slack_result and not slack_result.is_preview and slack_result.thread_ts:
            updates["slack_thread_ts"] = slack_result.thread_ts
        
        self.state.upsert_signature(signature, updates)
    
    def _build_ticket_description(self, error: AnalyzedError) -> str:
        """Build GitHub issue description."""
        parts = []
        
        # Summary
        if error.comprehensive_summary:
            parts.append(error.comprehensive_summary)
            parts.append("\n---\n")
        
        # Error details
        parts.append("## Error Details\n")
        parts.append(f"- **Signature:** {error.signature}\n")
        parts.append(f"- **Module:** `{error.module}`\n")
        parts.append(f"- **Function:** `{error.function}`\n")
        parts.append(f"- **Container:** `{error.container}`\n")
        parts.append(f"- **Status:** {error.status}\n")
        parts.append(f"- **Severity:** {error.severity}\n")
        
        # Impact
        parts.append("\n## Impact\n")
        parts.append(f"- **Organizations affected:** {error.org_count}\n")
        parts.append(f"- **Error count:** {error.error_count}\n")
        if error.affected_orgs:
            parts.append(f"- **Orgs:** {', '.join(error.affected_orgs[:5])}\n")
        
        # Root cause
        if error.root_cause:
            parts.append(f"\n## Root Cause\n{error.root_cause}\n")
        
        # Suggested action
        if error.suggested_action:
            parts.append(f"\n## Suggested Action\n{error.suggested_action}\n")
        
        # Sample messages
        if error.sample_messages:
            parts.append("\n## Sample Errors\n")
            for i, msg in enumerate(error.sample_messages[:3], 1):
                parts.append(f"```\n{msg[:300]}\n```\n")
        
        parts.append("\n---\n*Generated by Error Monitoring Agent*")
        
        return "".join(parts)


# Singleton instance
_action_executor: Optional[ActionExecutor] = None


def get_action_executor() -> ActionExecutor:
    """Get singleton action executor instance."""
    global _action_executor
    if _action_executor is None:
        _action_executor = ActionExecutor()
    return _action_executor
