"""
AI Synthesis Engine — grounded operational reasoning.

This keeps the existing async API used by the orchestrator, but routes the
actual reasoning through the operational reasoner so summaries are grounded
in clusters, deployments, commits, topology, and history.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Dict, List, Optional

from ai.operational_reasoner import OperationalReasoner
from core.groq_cache import get_groq_client

logger = logging.getLogger(__name__)

try:
    from groq import Groq
    HAS_GROQ = True
except ImportError:
    HAS_GROQ = False
    logger.warning("Groq not available. Synthesis will use grounded fallback.")


class AISynthesisEngine:
    """Generate operational synthesis from grounded cluster evidence."""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key
        self._client = get_groq_client(api_key)
        self._reasoner = OperationalReasoner(api_key=api_key)

    async def synthesize_operational_brief(
        self,
        clusters: List[Dict[str, Any]],
        repository_info: Dict[str, Any],
    ) -> Dict[str, Any]:
        if not clusters:
            return self._empty_synthesis()

        repo_type = self._detect_repository_type(repository_info)
        grounded = await self._ground_clusters(clusters)

        if HAS_GROQ and self._client:
            try:
                result = await asyncio.wait_for(
                    asyncio.to_thread(
                        self._llm_synthesis,
                        clusters,
                        repository_info,
                        repo_type,
                        grounded,
                    ),
                    timeout=15.0,
                )
                result.setdefault("grounding", grounded)
                return result
            except asyncio.TimeoutError:
                logger.warning("LLM synthesis timed out after 15s")
            except Exception as exc:
                logger.warning("LLM synthesis failed: %s", exc)

        return self._template_synthesis(clusters, repository_info, repo_type, grounded)

    async def generate_root_cause_explanation(
        self,
        cluster: Dict[str, Any],
        context: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        try:
            result = await self._reasoner.reason(cluster, {"context": context or []})
            return result.get("likely_cause") or result.get("operational_summary") or cluster.get("root_cause", "Error detected")
        except Exception as exc:
            logger.warning("Operational reasoner failed: %s", exc)
            return cluster.get("root_cause", "Error detected")

    async def generate_action_recommendation(
        self,
        cluster: Dict[str, Any],
        deployment_correlated: bool,
        historical_similar: Optional[Dict[str, Any]] = None,
    ) -> str:
        if not HAS_GROQ or not self._client:
            return self._default_action_recommendation(cluster, deployment_correlated, historical_similar)

        prompt = self._build_action_prompt(cluster, deployment_correlated, historical_similar)
        try:
            response = await asyncio.wait_for(
                asyncio.to_thread(self._call_groq, prompt, 300),
                timeout=8.0,
            )
            return response
        except Exception as exc:
            logger.warning("LLM action generation failed: %s", exc)
            return self._default_action_recommendation(cluster, deployment_correlated, historical_similar)

    async def _ground_clusters(self, clusters: List[Dict[str, Any]]) -> Dict[str, Any]:
        grounded = []
        for cluster in clusters[:8]:
            grounded.append(await self._reasoner.reason(cluster, {}))
        return {
            "cluster_count": len(clusters),
            "grounded_clusters": grounded,
        }

    def _llm_synthesis(
        self,
        clusters: List[Dict[str, Any]],
        repository_info: Dict[str, Any],
        repo_type: str,
        grounded: Dict[str, Any],
    ) -> Dict[str, Any]:
        prompt = self._build_synthesis_prompt(clusters, repository_info, repo_type, grounded)
        try:
            response = self._call_groq(prompt, max_tokens=1200)
            parsed = self._parse_structured_synthesis(response)
            parsed.setdefault("grounding", grounded)
            return parsed
        except Exception as exc:
            logger.warning("LLM synthesis failed: %s", exc)
            return self._template_synthesis(clusters, repository_info, repo_type, grounded)

    def _call_groq(self, prompt: str, max_tokens: int = 1000) -> str:
        if not self._client:
            return ""

        try:
            message = self._client.chat.completions.create(
                messages=[{"role": "user", "content": prompt}],
                model="mixtral-8x7b-32768",
                max_tokens=max_tokens,
                temperature=0.2,
                timeout=15.0,
            )
            return message.choices[0].message.content.strip()
        except Exception as exc:
            logger.warning("Groq API call failed: %s", exc)
            return ""

    def _build_synthesis_prompt(
        self,
        clusters: List[Dict[str, Any]],
        repository_info: Dict[str, Any],
        repo_type: str,
        grounded: Dict[str, Any],
    ) -> str:
        critical = [cluster for cluster in clusters if cluster.get("severity") in ("S1", "S2")]
        cluster_summary = "\n".join(
            f"- {cluster.get('root_cause')}: {cluster.get('error_count')} errors in {', '.join(cluster.get('affected_services', [])[:2])}"
            for cluster in clusters[:5]
        )
        return f"""You are an expert operational reliability engineer analyzing production incidents.

Repository Type: {repo_type}
Repository Info: {json.dumps(repository_info, indent=2)[:500]}

Grounded Reasoning:
{json.dumps(grounded, indent=2)[:2000]}

Current Incident Clusters ({len(clusters)} total, {len(critical)} critical):
{cluster_summary}

Provide a concise operational brief that:
1. Summarizes the key operational issues
2. Explains the likely root causes with {repo_type}-specific context
3. Identifies which services are most affected
4. Rates current operational status (normal/degraded/critical/outage-risk)
5. Recommends specific actions

Return JSON with keys: narrative, key_insights, recommended_actions, repository_specific_reasoning, confidence.
"""

    def _build_action_prompt(
        self,
        cluster: Dict[str, Any],
        deployment_correlated: bool,
        historical_similar: Optional[Dict[str, Any]] = None,
    ) -> str:
        history = ""
        if historical_similar:
            history = f"\nHistorical Context: Similar incident before, resolved via: {historical_similar.get('resolution_method')}"

        return f"""Recommend specific operational actions for this production incident.

Issue:
- Root Cause: {cluster.get('root_cause')}
- Severity: {cluster.get('severity')}
- Operational Severity: {cluster.get('operational_severity')}
- Affected Services: {', '.join(cluster.get('affected_services', [])[:3])}
- Deployment Related: {deployment_correlated}{history}

Provide 1-2 specific, actionable steps to investigate and resolve this incident immediately.
"""

    def _parse_structured_synthesis(self, response: str) -> Dict[str, Any]:
        try:
            parsed = json.loads(response)
            if isinstance(parsed, dict):
                return {
                    "narrative": parsed.get("narrative", response),
                    "key_insights": parsed.get("key_insights", []),
                    "recommended_actions": parsed.get("recommended_actions", []),
                    "repository_specific_reasoning": parsed.get("repository_specific_reasoning", ""),
                    "confidence": float(parsed.get("confidence", 0.85)),
                }
        except Exception:
            pass

        if "---" in response:
            sections = response.split("---")
            return {
                "narrative": sections[0].strip(),
                "key_insights": self._parse_list_section(sections[1] if len(sections) > 1 else ""),
                "recommended_actions": self._parse_list_section(sections[2] if len(sections) > 2 else ""),
                "repository_specific_reasoning": sections[3].strip() if len(sections) > 3 else "",
                "confidence": 0.85,
            }

        return {
            "narrative": response,
            "key_insights": [],
            "recommended_actions": [],
            "repository_specific_reasoning": "",
            "confidence": 0.8,
        }

    def _template_synthesis(
        self,
        clusters: List[Dict[str, Any]],
        repository_info: Dict[str, Any],
        repo_type: str,
        grounded: Dict[str, Any],
    ) -> Dict[str, Any]:
        critical = [cluster for cluster in clusters if cluster.get("severity") in ("S1", "S2")]
        deployment_correlated = sum(1 for cluster in clusters if cluster.get("deployment_related"))
        narrative = self._generate_template_narrative(len(clusters), len(critical), deployment_correlated, repo_type)

        return {
            "narrative": narrative,
            "key_insights": [
                f"{len(clusters)} incident cluster(s) detected",
                f"{len(critical)} critical cluster(s) requiring attention",
                f"{deployment_correlated} cluster(s) correlated with deployments" if deployment_correlated else "No deployment correlation",
            ],
            "recommended_actions": [
                "Investigate critical clusters immediately",
                "Review recent deployments for correlation",
                "Check service dependencies and topology",
                "Monitor recurrence and escalation status",
            ],
            "repository_specific_reasoning": self._get_repo_specific_reasoning(repo_type),
            "confidence": 0.72,
            "grounding": grounded,
        }

    def _generate_template_narrative(
        self,
        total_clusters: int,
        critical_count: int,
        deployment_correlation: int,
        repo_type: str,
    ) -> str:
        if critical_count >= 3:
            status = "**CRITICAL**: Multiple severe incidents detected"
        elif critical_count >= 1:
            status = "**DEGRADED**: One or more critical incident clusters"
        else:
            status = "**MONITORING**: Several incident clusters under observation"

        repo_context = self._get_repo_type_context(repo_type)
        return f"""{status} requiring investigation.

{total_clusters} incident cluster(s) identified.
{deployment_correlation} cluster(s) show deployment correlation.

{repo_context}

Recommended immediate action: Investigate critical clusters and verify deployment impact."""

    def _detect_repository_type(self, repo_info: Dict[str, Any]) -> str:
        language = repo_info.get("language", "").lower()
        topics = [topic.lower() for topic in repo_info.get("topics", [])]
        name = repo_info.get("name", "").lower()

        if language in ("typescript", "javascript", "jsx"):
            return "frontend"
        if language in ("python", "go", "rust", "java"):
            return "backend"

        if any(topic in topics for topic in ["frontend", "react", "vue", "angular"]):
            return "frontend"
        if any(topic in topics for topic in ["kubernetes", "infrastructure", "devops", "terraform"]):
            return "infrastructure"
        if any(topic in topics for topic in ["ml", "machine-learning", "data-science"]):
            return "ml"
        if any(topic in topics for topic in ["backend", "api", "database"]):
            return "backend"

        if any(token in name for token in ["frontend", "client", "ui", "web"]):
            return "frontend"
        if any(token in name for token in ["backend", "api", "server", "service"]):
            return "backend"
        if any(token in name for token in ["infra", "kubernetes", "devops"]):
            return "infrastructure"

        return "general"

    def _get_repo_type_context(self, repo_type: str) -> str:
        contexts = {
            "frontend": "Frontend errors may indicate UI rendering issues, API integration problems, or browser compatibility concerns.",
            "backend": "Backend errors suggest service logic failures, database issues, or external API integration problems.",
            "infrastructure": "Infrastructure errors may indicate deployment failures, resource constraints, or service topology issues.",
            "ml": "ML errors may indicate data pipeline failures, model serving issues, or inference performance problems.",
            "data": "Data errors suggest ETL pipeline failures, data quality issues, or storage/retrieval problems.",
            "general": "Investigation should focus on service dependencies and operational impact.",
        }
        return contexts.get(repo_type, contexts["general"])

    def _get_repo_specific_reasoning(self, repo_type: str) -> str:
        reasoning = {
            "frontend": "Frontend errors significantly impact user experience and conversion rates. Prioritize fixes for UI/navigation issues.",
            "backend": "Backend errors affect downstream services. Prioritize fixes that restore service availability.",
            "infrastructure": "Infrastructure errors cascade to all services. Focus on deployment stability and service topology.",
            "ml": "ML errors impact prediction quality and latency. Prioritize data pipeline and model serving fixes.",
            "data": "Data errors affect all data consumers. Prioritize data quality and pipeline reliability.",
            "general": "Prioritize errors affecting multiple services or critical user workflows.",
        }
        return reasoning.get(repo_type, reasoning["general"])

    def _parse_list_section(self, section: str) -> List[str]:
        lines = section.strip().split("\n")
        items = [
            line.strip("- •* ").strip()
            for line in lines
            if line.strip() and line.strip()[0] in "-•*"
        ]
        return items[:5]

    def _default_action_recommendation(
        self,
        cluster: Dict[str, Any],
        deployment_correlated: bool,
        historical_similar: Optional[Dict[str, Any]] = None,
    ) -> str:
        severity = str(cluster.get("severity", "S4")).upper()
        operational_severity = str(cluster.get("operational_severity", "informational"))

        if severity == "S1" or operational_severity == "outage-risk":
            action = "Page on-call immediately. Begin incident investigation and prepare rollback."
        elif severity == "S2" or operational_severity == "critical":
            action = "Create incident ticket and assign to on-call engineer."
        elif severity == "S3" or operational_severity == "degraded":
            action = "Investigate service degradation and verify dependency health."
            if deployment_correlated:
                action = "Investigate deployment correlation. Consider rollback if impact continues."
        else:
            action = "Log for monitoring. Investigate if error count increases."

        if historical_similar:
            action = f"{action} Compare with the prior remediation: {historical_similar.get('resolution_method', 'unknown')}."

        return action

    def _empty_synthesis(self) -> Dict[str, Any]:
        return {
            "narrative": "No incidents detected. Repository operating normally.",
            "key_insights": ["No critical incidents", "No errors detected"],
            "recommended_actions": ["Continue monitoring"],
            "repository_specific_reasoning": "No operational issues requiring attention.",
            "confidence": 1.0,
        }
