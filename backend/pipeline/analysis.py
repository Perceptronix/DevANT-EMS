"""
LLM-powered severity analysis for error clusters.

Determines:
- Severity (S1-S4)
- Status (NEW, REGRESSION, ONGOING)
- Root cause and impact
- Whether to alert (suppression logic)
"""
import os
import logging
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Optional, Literal

from pydantic import BaseModel, Field

from config import get_config
from core.causality import correlate_deployment_events
from core.scoring import infer_severity
from ontology.models import Incident, RCAHypothesis
from observability.propagation_engine import PropagationEngine
from memory.causal_graph import CausalGraph
from schemas import PreviousErrorState
from state import get_state_manager
from memory.hybrid_search import HybridRetriever

logger = logging.getLogger(__name__)


# Closed ticket states (case-insensitive)
CLOSED_STATES = [
    "completed", "done", "closed",
    "canceled", "cancelled",
    "finished", "resolved", "fixed", "complete",
    "wontfix", "won't fix", "wont do", "won't do",
    "rejected", "declined", "duplicate",
    "archived",
]


class ErrorAnalysis(BaseModel):
    """LLM output for error analysis."""
    severity: str = Field(description="Severity level: S1 (Critical), S2 (High), S3 (Medium), S4 (Low)")
    title: str = Field(description="Short actionable title (5-10 words) for tickets/alerts, e.g. 'Google Drive rate limits exceeded' or 'Database connection pool exhausted'")
    root_cause: str = Field(description="Brief explanation of the likely root cause")
    impact: str = Field(description="Description of the impact on users/system")
    suggested_action: str = Field(description="Recommended next steps to resolve")
    reasoning: str = Field(description="Explanation of how severity was determined")
    confidence: float = Field(ge=0.0, le=1.0, description="Confidence score (0.0-1.0) for the analysis")
    evidence_count: int = Field(description="Number of evidence items used for reasoning")
    deployment_correlation: bool = Field(description="Whether a deployment correlation was found")
    historical_match: bool = Field(description="Whether historical incidents matched this one")


class ErrorAnalyzer:
    """
    Analyzes error clusters to determine severity, status, and alerting.
    
    Severity Levels:
    - S1 (Critical): Complete service outage, data loss, security breach
    - S2 (High): Major feature broken, significant user impact
    - S3 (Medium): Feature degraded, limited user impact
    - S4 (Low): Minor issue, no immediate action required
    
    Status:
    - NEW: First time seeing this error, no relevant ticket
    - REGRESSION: Error reoccurred after ticket was closed
    - ONGOING: Continues with open ticket or seen before
    
    Suppression Logic:
    - NEW → Always alert
    - REGRESSION → Always alert
    - ONGOING with open ticket → Suppress (don't spam)
    - ONGOING, alerted <24h ago → Suppress
    - S1/S2 severity → Always alert (override suppression)
    - Muted → Suppress
    """
    
    def __init__(self):
        self.last_reasoning: Optional[str] = None
        self.state = get_state_manager()
        self.propagation_engine = PropagationEngine()
        self.causal_graph = CausalGraph()
        self._init_llm()
        # Hybrid retriever for grounded operational evidence
        try:
            self.hybrid = HybridRetriever()
        except Exception:
            self.hybrid = None
    
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
    
    async def analyze_errors(
        self, 
        clusters: List[Dict[str, Any]], 
        context_results: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Analyze each error cluster with context to determine severity.
        
        Args:
            clusters: List of error clusters from clustering step
            context_results: Context search results from Airweave
            
        Returns:
            List of analysis results per cluster
        """
        analyses = []
        all_reasoning = []
        
        # Note: context_results (legacy) may still be provided but we will
        # prefer hybrid retrieval that produces a grounded evidence bundle.
        
        for cluster in clusters:
            signature = cluster.get("signature", "")
            # Hybrid retrieval: get grounded evidence bundle
            evidence_bundle = None
            try:
                if self.hybrid:
                    evidence_bundle = await self.hybrid.retrieve(cluster)
            except Exception as e:
                logger.warning(f"Hybrid retrieval failed for {signature[:40]}: {e}")

            operational_context = self.build_operational_context(cluster, evidence_bundle or {})

            if self.llm:
                try:
                    analysis = await self._llm_analyze(cluster, evidence_bundle or {}, operational_context)
                except Exception as e:
                    logger.error(f"LLM analysis failed: {e}", exc_info=True)
                    analysis = self._fallback_analysis(cluster, evidence_bundle or {}, operational_context)
            else:
                analysis = self._fallback_analysis(cluster, evidence_bundle or {}, operational_context)
            
            analyses.append(analysis)
            if analysis.get("reasoning"):
                all_reasoning.append(f"[{signature[:50]}]: {analysis['reasoning']}")
        
        self.last_reasoning = "\n\n".join(all_reasoning)
        return analyses

    async def analyze(
        self,
        errors: List[Dict[str, Any]],
        cluster_signature: str,
    ) -> ErrorAnalysis:
        """Compatibility wrapper returning the historical ErrorAnalysis model."""
        cluster = {
            "signature": cluster_signature,
            "error_count": len(errors),
            "affected_orgs": sorted({error.get("org_name") for error in errors if error.get("org_name")}),
            "modules": sorted({error.get("module") for error in errors if error.get("module")}),
        }
        analysis = self._fallback_analysis(cluster, {})
        operational_context = self.build_operational_context(cluster, {
            "deployment_correlation": correlate_deployment_events(cluster),
            "metrics_anomalies": self._extract_metrics_anomalies(cluster),
        })
        analysis = self._fallback_analysis(cluster, {}, operational_context)
        confidence = min(0.95, 0.35 + (0.05 * min(len(errors), 10)))
        return ErrorAnalysis(
            severity=analysis["severity"],
            title=analysis["title"],
            root_cause=analysis["root_cause"],
            impact=analysis["impact"],
            suggested_action=analysis["suggested_action"],
            reasoning=analysis["reasoning"],
            confidence=confidence,
            evidence_count=len(errors),
            deployment_correlation=False,
            historical_match=False,
        )

    def build_operational_context(
        self,
        cluster: Dict[str, Any],
        evidence_bundle: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Build a timeline-grounded causal context for RCA."""
        incident = self._build_incident_model(cluster, evidence_bundle)
        deployment_correlation = evidence_bundle.get("deployment_correlation") or correlate_deployment_events(cluster)
        metrics_anomalies = evidence_bundle.get("metrics_anomalies") or self._extract_metrics_anomalies(cluster)
        regression_history = evidence_bundle.get("history") or evidence_bundle.get("regression_history") or []

        propagation = self.propagation_engine.infer(
            incident=incident.model_dump(),
            deployment_correlation=deployment_correlation,
            metrics_anomalies=metrics_anomalies,
            regression_history=regression_history,
        )

        causal_graph = self.causal_graph.build_from_incident(
            incident=incident.model_dump(),
            propagation_chain=propagation.get("propagation_chain", []),
            deployment_correlation=deployment_correlation,
            metrics_anomalies=metrics_anomalies,
            regression_history=regression_history,
        )

        return {
            "incident": incident.model_dump(),
            "deployment_correlation": deployment_correlation,
            "metrics_anomalies": metrics_anomalies,
            "regression_history": regression_history,
            "propagation": propagation,
            "causal_graph": causal_graph.summary(),
            "timeline": causal_graph.timeline(),
            "causal_hypothesis": propagation.get("hypothesis"),
            "evidence_count": len(evidence_bundle.get("evidences", [])) if isinstance(evidence_bundle, dict) else 0,
        }

    def _build_incident_model(self, cluster: Dict[str, Any], evidence_bundle: Dict[str, Any]) -> Incident:
        timestamps = []
        for error in cluster.get("errors", []):
            ts = error.get("timestamp") or error.get("occurred_at")
            if ts:
                timestamps.append(ts)

        timestamp = timestamps[0] if timestamps else cluster.get("timestamp") or datetime.utcnow().isoformat()
        signature = cluster.get("signature", "Unknown")

        evidence_origin = []
        for evidence in (evidence_bundle.get("evidences", []) if isinstance(evidence_bundle, dict) else []):
            evidence_origin.append(
                evidence.get("url")
                or evidence.get("metadata", {}).get("url")
                or evidence.get("title")
                or evidence.get("metadata", {}).get("title")
                or "evidence"
            )

        return Incident(
            source_of_truth=evidence_bundle.get("source_of_truth", "pipeline.analysis"),
            timestamp=datetime.fromisoformat(str(timestamp).replace("Z", "+00:00")) if isinstance(timestamp, str) else timestamp,
            confidence_origin=evidence_bundle.get("confidence_origin", "causal_grounding"),
            evidence_origin=evidence_origin,
            persistence_rules={
                "retention": "indefinite",
                "mutability": "append-only",
                "rewrite_policy": "source-driven",
            },
            incident_id=cluster.get("incident_id") or f"incident:{signature[:80]}",
            signature=signature,
            service=cluster.get("service") or (cluster.get("modules") or ["unknown"])[0],
            severity=cluster.get("severity"),
            summary=cluster.get("summary") or cluster.get("sample_message") or signature,
            root_cause=cluster.get("root_cause"),
            deployment_id=cluster.get("deployment_id"),
            commit_hash=cluster.get("commit_hash"),
            owner=cluster.get("owner"),
            affected_orgs=cluster.get("affected_orgs", []),
        )

    def _extract_metrics_anomalies(self, cluster: Dict[str, Any]) -> List[Dict[str, Any]]:
        anomalies: List[Dict[str, Any]] = []
        message = str(cluster.get("sample_message") or cluster.get("signature") or "").lower()
        tokens = [message]
        for error in cluster.get("errors", []):
            tokens.append(str(error.get("message", "")).lower())

        if any(word in " ".join(tokens) for word in ["latency", "slow", "response time", "p95", "p99"]):
            anomalies.append({
                "metric_name": "latency_ms",
                "direction": "up",
                "value": cluster.get("latency_ms", 0),
                "baseline": cluster.get("baseline_latency_ms", 0),
                "deviation": cluster.get("latency_deviation", 0.0),
                "window_minutes": 15,
                "service": cluster.get("service") or (cluster.get("modules") or [None])[0],
            })

        if any(word in " ".join(tokens) for word in ["retry", "backoff", "storm", "throttle"]):
            anomalies.append({
                "metric_name": "retry_count",
                "direction": "up",
                "value": cluster.get("retry_count", 0),
                "baseline": cluster.get("baseline_retry_count", 0),
                "deviation": cluster.get("retry_deviation", 0.0),
                "window_minutes": 15,
                "service": cluster.get("service") or (cluster.get("modules") or [None])[0],
            })

        if any(word in " ".join(tokens) for word in ["saturation", "exhaust", "pool", "oom", "memory", "timeout"]):
            anomalies.append({
                "metric_name": "resource_saturation",
                "direction": "up",
                "value": cluster.get("saturation", 0),
                "baseline": cluster.get("baseline_saturation", 0),
                "deviation": cluster.get("saturation_deviation", 0.0),
                "window_minutes": 15,
                "service": cluster.get("service") or (cluster.get("modules") or [None])[0],
            })

        return anomalies
    
    async def _llm_analyze(
        self,
        cluster: Dict[str, Any],
        context: Dict[str, Any],
        operational_context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Use LLM to analyze the error cluster."""
        from langchain_core.prompts import ChatPromptTemplate
        from langchain_core.output_parsers import JsonOutputParser
        
        parser = JsonOutputParser(pydantic_object=ErrorAnalysis)
        
        # Build context string from grounded evidence bundle or legacy context
        context_parts = []

        # If evidence bundle produced by HybridRetriever
        if isinstance(context, dict) and context.get("evidences") is not None:
            evidences = context.get("evidences", [])
            if evidences:
                context_parts.append("**Top Evidence:**")
                for ev in evidences[:4]:
                    title = ev.get("title") or ev.get("metadata", {}).get("title", "")
                    src = ev.get("source")
                    url = ev.get("url") or ev.get("metadata", {}).get("url", "")
                    context_parts.append(f"- [{src}] {title} ({url}) Score:{ev.get('final_score', ev.get('base_score', 0)):.2f}")

            dep = context.get("deployment_correlation")
            if dep:
                context_parts.append(f"**Deployment Correlation:** matched={dep.get('matched', False)} score={dep.get('score', 0):.2f}")

            # include simple metadata
            meta = context.get("metadata") or {}
            if meta:
                context_parts.append(f"**Evidence Count:** {meta.get('evidence_count', 0)}  **Confidence:** {meta.get('confidence', 0):.2f}")

        else:
            # Legacy context format
            if context and isinstance(context, dict) and context.get("code_snippets"):
                context_parts.append("**Related Code:**")
                for snippet in context["code_snippets"][:2]:
                    context_parts.append(f"- {snippet.get('title', 'Code')}: {snippet.get('content', '')[:300]}")

            if context and isinstance(context, dict) and context.get("related_tickets"):
                context_parts.append("\n**Related Tickets:**")
                for ticket in context["related_tickets"][:2]:
                    context_parts.append(f"- {ticket.get('title', 'Ticket')}: {ticket.get('content', '')[:200]}")

        if operational_context:
            context_parts.append("\n**Timeline-Grounded Causality:**")
            incident = operational_context.get("incident", {})
            context_parts.append(f"- Incident: {incident.get('summary', 'Unknown')} @ {incident.get('timestamp', 'unknown')}")

            deployment = operational_context.get("deployment_correlation", {})
            context_parts.append(
                f"- Deployment correlation: matched={deployment.get('matched', False)} score={deployment.get('score', 0):.2f}"
            )

            anomalies = operational_context.get("metrics_anomalies", [])
            for idx, anomaly in enumerate(anomalies[:4]):
                context_parts.append(
                    f"- anomaly[{idx}]: {anomaly.get('metric_name')} {anomaly.get('direction')} value={anomaly.get('value')} baseline={anomaly.get('baseline')}"
                )

            propagation = operational_context.get("propagation", {})
            chain = propagation.get("propagation_chain", [])
            for idx, event in enumerate(chain[:6]):
                context_parts.append(
                    f"- chain[{idx}]: {event.get('phase')} -> {event.get('description')} @ {event.get('timestamp')}"
                )

            hypothesis = operational_context.get("causal_hypothesis", {})
            if hypothesis:
                context_parts.append(
                    f"- hypothesis: {hypothesis.get('hypothesis', 'Unknown')} likelihood={hypothesis.get('likelihood', 0):.2f}"
                )

            regression_history = operational_context.get("regression_history", [])
            if regression_history:
                context_parts.append(f"- regression_history: {len(regression_history)} prior incident(s)")

        context_str = "\n".join(context_parts) if context_parts else "No additional context available."
        
        prompt = ChatPromptTemplate.from_messages([
            ("system", """You are analyzing production errors to determine severity and impact.

    MANDATES:
    - Do NOT invent deployments, commits, owners, metrics, or historical incidents.
    - Only use the provided, retrieved evidence and structured incident data.
    - Root cause must be grounded in timeline evidence, propagation order, deployment correlation, metrics anomalies, or regression history.
    - Every factual claim MUST reference evidence by index, URL, or field from the evidence bundle or causal timeline.
    - If evidence is insufficient, respond with "Insufficient evidence" rather than guessing.

    Severity Guidelines (be conservative - most errors should be S3 or S4):
    - **S1 (Critical)**: Complete service outage, data loss/corruption, security breach, ALL users affected
    - **S2 (High)**: Major feature broken, significant user impact (>10% users), potential data issues
    - **S3 (Medium)**: Feature degraded, limited user impact (<10% users), workaround available
    - **S4 (Low)**: Minor issue, cosmetic, no immediate action required, single user affected

    Title Guidelines:
    - Create a short, actionable title (5-10 words) suitable for tickets and alerts
    - Focus on WHAT is happening, not the technical error class

    Output Requirements:
    - Provide a JSON object matching the required schema including `confidence`, `evidence_count`, `deployment_correlation`, and `historical_match`.
    - Include a brief `reasoning` field that cites evidence items and causal timeline entries (e.g., "evidence[0].url", "timeline[2]", "propagation[1]").

    {format_instructions}"""),
            ("user", """Analyze this error cluster:

    **Signature:** {signature}

    **Error Count:** {error_count}
    **Organizations Affected:** {orgs}

    **Sample Error:**
    {sample_message}

    **Evidence Bundle (do NOT invent additional facts):**
    {context}

    Determine severity, create an actionable title, identify root cause, assess impact, and suggest action. If you cannot reach a conclusion from evidence, state "Insufficient evidence" and set `confidence` accordingly.""")
        ])
        
        chain = prompt | self.llm | parser
        
        result = await chain.ainvoke({
            "format_instructions": parser.get_format_instructions(),
            "signature": cluster.get("signature", "Unknown"),
            "error_count": cluster.get("error_count", 1),
            "orgs": ", ".join(cluster.get("affected_orgs", ["Unknown"])),
            "sample_message": cluster.get("sample_message", "")[:500],
            "context": context_str,
        })
        
        analysis = ErrorAnalysis(**result)
        
        logger.info(f"Analysis for '{cluster.get('signature', '')[:50]}': {analysis.severity} - {analysis.title}")
        
        return {
            "signature": cluster.get("signature", ""),
            "severity": analysis.severity,
            "title": analysis.title,
            "root_cause": analysis.root_cause,
            "impact": analysis.impact,
            "suggested_action": analysis.suggested_action,
            "reasoning": analysis.reasoning,
            "error_count": cluster.get("error_count", 1),
            "affected_orgs": cluster.get("affected_orgs", []),
            "modules": cluster.get("modules", []),
            "deployment_correlation": operational_context.get("deployment_correlation", {}),
            "metrics_anomalies": operational_context.get("metrics_anomalies", []),
            "regression_history": operational_context.get("regression_history", []),
            "propagation_chain": operational_context.get("propagation", {}).get("propagation_chain", []),
            "causal_graph": operational_context.get("causal_graph", {}),
        }
    
    def _fallback_analysis(
        self, 
        cluster: Dict[str, Any], 
        context: Dict[str, Any],
        operational_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Fallback analysis without LLM."""
        signature = cluster.get("signature", "")
        error_count = cluster.get("error_count", 1)
        affected_orgs = cluster.get("affected_orgs", [])
        modules = cluster.get("modules", [])
        operational_context = operational_context or self.build_operational_context(cluster, context)
        propagation = operational_context.get("propagation", {})
        deployment_correlation = operational_context.get("deployment_correlation", {})
        metrics_anomalies = operational_context.get("metrics_anomalies", [])
        regression_history = operational_context.get("regression_history", [])

        severity_data = infer_severity(
            signature=signature,
            error_count=error_count,
            affected_orgs=affected_orgs,
            modules=modules,
        )

        final_state = propagation.get("final_state")
        if final_state == "outage":
            severity_data["severity"] = "S1"
            severity_data["title"] = propagation.get("summary", "Propagation caused service outage")
        elif final_state in {"timeout", "saturation"} and severity_data["severity"] in {"S3", "S4"}:
            severity_data["severity"] = "S2"
            severity_data["title"] = propagation.get("summary", "Propagation caused downstream degradation")
        elif deployment_correlation.get("matched") and severity_data["severity"] == "S4":
            severity_data["severity"] = "S3"
        
        root_cause = severity_data["root_cause"]
        if deployment_correlation.get("matched"):
            root_cause = "Recent deployment correlated with the first causal event"
        elif propagation.get("hypothesis", {}).get("hypothesis"):
            root_cause = propagation["hypothesis"]["hypothesis"]

        timeline_bits = []
        for idx, event in enumerate(propagation.get("propagation_chain", [])[:5]):
            timeline_bits.append(f"{idx + 1}. {event.get('phase')} ({event.get('description')})")

        if metrics_anomalies:
            metric_summary = ", ".join(a.get("metric_name", "metric") for a in metrics_anomalies[:3])
        else:
            metric_summary = "no explicit metric anomaly recorded"

        return {
            "signature": signature,
            "severity": severity_data["severity"],
            "title": severity_data["title"],
            "root_cause": root_cause,
            "impact": (
                f"Affecting {len(affected_orgs)} organization(s): {', '.join(affected_orgs[:3])}. "
                f"Metrics anomalies: {metric_summary}."
            ),
            "suggested_action": propagation.get("recommended_action") or "Investigate the earliest causal event and validate deployment impact",
            "reasoning": (
                "Timeline-grounded analysis. "
                f"Deployment matched={deployment_correlation.get('matched', False)} score={deployment_correlation.get('score', 0):.2f}. "
                f"Propagation final_state={final_state or 'unknown'}. "
                + (" -> ".join(timeline_bits) if timeline_bits else "No propagation chain inferred.")
            ),
            "error_count": error_count,
            "affected_orgs": affected_orgs,
            "modules": modules,
            "deployment_correlation": deployment_correlation,
            "metrics_anomalies": metrics_anomalies,
            "regression_history": regression_history,
            "propagation_chain": propagation.get("propagation_chain", []),
            "causal_graph": operational_context.get("causal_graph", {}),
        }
    
    # =========================================================================
    # Status Determination
    # =========================================================================
    
    def determine_status(
        self,
        signature: str,
        has_relevant_ticket: bool = False,
    ) -> tuple[Literal["NEW", "REGRESSION", "ONGOING"], PreviousErrorState]:
        """
        Determine error status based on history and ticket state.
        
        Args:
            signature: Error signature
            has_relevant_ticket: Whether a relevant ticket was found
            
        Returns:
            Tuple of (status, previous_state)
        """
        # Get previous state from storage
        prev_state = self.state.get_signature(signature)
        
        if prev_state is None:
            # Never seen before
            prev_state = PreviousErrorState(signature=signature)
            logger.info(f"[{signature[:30]}...] Status: NEW (first occurrence)")
            return "NEW", prev_state
        
        # Check for regression (ticket was closed, error came back)
        if prev_state.linear_issue_id and prev_state.linear_issue_status:
            status_lower = prev_state.linear_issue_status.lower()
            if status_lower in CLOSED_STATES:
                logger.info(
                    f"[{signature[:30]}...] Status: REGRESSION "
                    f"(ticket {prev_state.linear_issue_id} was {prev_state.linear_issue_status})"
                )
                return "REGRESSION", prev_state
        
        # Check if we have a relevant open ticket
        if has_relevant_ticket:
            logger.info(f"[{signature[:30]}...] Status: ONGOING (has relevant ticket)")
            return "ONGOING", prev_state
        
        # Seen before but no ticket
        if not prev_state.last_alerted:
            logger.info(f"[{signature[:30]}...] Status: NEW (seen but never alerted)")
            return "NEW", prev_state
        
        logger.info(f"[{signature[:30]}...] Status: ONGOING (seen before)")
        return "ONGOING", prev_state
    
    # =========================================================================
    # Suppression Logic
    # =========================================================================
    
    def should_alert(
        self,
        signature: str,
        status: Literal["NEW", "REGRESSION", "ONGOING"],
        severity: str,
        has_relevant_ticket: bool,
        prev_state: PreviousErrorState,
    ) -> tuple[bool, Optional[str]]:
        """
        Determine if we should send an alert for this error.
        
        Args:
            signature: Error signature
            status: Error status (NEW, REGRESSION, ONGOING)
            severity: Severity level (S1-S4)
            has_relevant_ticket: Whether a relevant ticket exists
            prev_state: Previous error state
            
        Returns:
            Tuple of (should_alert, suppression_reason)
        """
        # 1. Check if muted
        if self.state.is_muted(signature):
            mute_info = self.state.get_mute_info(signature)
            reason = f"Muted until {mute_info.get('muted_until', 'unknown')}"
            logger.info(f"[{signature[:30]}...] Suppressed: {reason}")
            return False, reason
        
        # 2. S1/S2 always alerts (override other suppression)
        if severity in ["S1", "S2"]:
            logger.info(f"[{signature[:30]}...] {severity} severity → always alert")
            return True, None
        
        # 3. NEW errors always alert
        if status == "NEW":
            logger.info(f"[{signature[:30]}...] NEW status → alert")
            return True, None
        
        # 4. REGRESSION always alerts
        if status == "REGRESSION":
            logger.info(f"[{signature[:30]}...] REGRESSION status → alert")
            return True, None
        
        # 5. ONGOING with open ticket → suppress
        if status == "ONGOING" and has_relevant_ticket:
            reason = "Has open ticket - suppressing to avoid spam"
            logger.info(f"[{signature[:30]}...] Suppressed: {reason}")
            return False, reason
        
        # 6. Check 24h sliding window
        if prev_state.last_alerted:
            now = datetime.now(timezone.utc)
            last_alerted = prev_state.last_alerted
            
            # Handle timezone-naive datetimes
            if last_alerted.tzinfo is None:
                last_alerted = last_alerted.replace(tzinfo=timezone.utc)
            
            time_since_alert = now - last_alerted
            if time_since_alert < timedelta(hours=24):
                hours_ago = time_since_alert.total_seconds() / 3600
                reason = f"Alerted {hours_ago:.1f}h ago (within 24h window)"
                logger.info(f"[{signature[:30]}...] Suppressed: {reason}")
                return False, reason
        
        # Default: alert
        logger.info(f"[{signature[:30]}...] No suppression rules matched → alert")
        return True, None
    
    def analyze_with_status(
        self,
        cluster: Dict[str, Any],
        context: Dict[str, Any],
        has_relevant_ticket: bool = False,
    ) -> Dict[str, Any]:
        """
        Full analysis including status determination and suppression.
        
        This is the main entry point for analysis in the enhanced pipeline.
        
        Args:
            cluster: Error cluster data
            context: Context from Airweave search
            has_relevant_ticket: Whether a matching ticket was found
            
        Returns:
            Analysis dict with status, severity, and alert decision
        """
        signature = cluster.get("signature", "")
        
        # Determine status
        status, prev_state = self.determine_status(signature, has_relevant_ticket)
        
        # Run LLM/fallback analysis for severity
        if self.llm:
            try:
                import asyncio
                analysis = asyncio.get_event_loop().run_until_complete(
                    self._llm_analyze(cluster, context)
                )
            except Exception as e:
                logger.error(f"LLM analysis failed: {e}")
                analysis = self._fallback_analysis(cluster, context)
        else:
            analysis = self._fallback_analysis(cluster, context)
        
        # Determine if we should alert
        should_alert, suppression_reason = self.should_alert(
            signature=signature,
            status=status,
            severity=analysis["severity"],
            has_relevant_ticket=has_relevant_ticket,
            prev_state=prev_state,
        )
        
        # Add status and suppression info to analysis
        analysis["status"] = status
        analysis["should_alert"] = should_alert
        analysis["suppression_reason"] = suppression_reason
        analysis["previous_state"] = prev_state.model_dump() if prev_state else None
        
        return analysis
