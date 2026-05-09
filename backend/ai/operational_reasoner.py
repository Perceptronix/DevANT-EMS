from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Dict, Optional

from core.groq_cache import get_groq_client
from intelligence.root_cause_engine import RootCauseEngine

logger = logging.getLogger(__name__)

try:
    from groq import Groq
    HAS_GROQ = True
except ImportError:
    HAS_GROQ = False


class OperationalReasoner:
    """Grounded operational synthesis using clustered incidents and evidence."""

    def __init__(self, api_key: Optional[str] = None):
        self._client = get_groq_client(api_key)
        self._root_cause_engine = RootCauseEngine()

    async def reason(self, cluster: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        context = context or {}
        hypothesis = self._root_cause_engine.analyze_cluster({**cluster, **context})
        if not HAS_GROQ or not self._client:
            return self._fallback_reasoning(cluster, hypothesis, context)

        prompt = self._build_prompt(cluster, context, hypothesis)
        try:
            response = await asyncio.wait_for(
                asyncio.to_thread(self._call_groq, prompt),
                timeout=12.0,
            )
            parsed = self._parse_response(response)
            parsed.update({
                "confidence": max(float(parsed.get("confidence", 0.0)), hypothesis.confidence),
                "severity": hypothesis.severity,
                "operational_summary": parsed.get("operational_summary") or hypothesis.summary,
                "likely_cause": parsed.get("likely_cause") or hypothesis.likely_cause,
                "recommended_actions": parsed.get("recommended_actions") or hypothesis.recommended_actions,
                "risk_assessment": parsed.get("risk_assessment") or hypothesis.risk_assessment,
                "grounding": self._grounding(cluster, context, hypothesis),
            })
            return parsed
        except Exception as exc:
            logger.warning("Operational reasoning failed: %s", exc)
            return self._fallback_reasoning(cluster, hypothesis, context)

    def _build_prompt(self, cluster: Dict[str, Any], context: Dict[str, Any], hypothesis) -> str:
        ground = self._grounding(cluster, context, hypothesis)
        return f"""You are analyzing a real operational incident. Use only the evidence below.

Operational grounding:
{json.dumps(ground, indent=2)[:6000]}

Return JSON with keys:
operational_summary, likely_cause, confidence, recommended_actions, risk_assessment.

Rules:
- Reference the exact deployment failure, workflow step, changed files, affected services, and historical incident match if present.
- Do not produce a generic template.
- If evidence is weak, say so explicitly and lower confidence.
"""

    def _grounding(self, cluster: Dict[str, Any], context: Dict[str, Any], hypothesis) -> Dict[str, Any]:
        return {
            "cluster": {
                "signature": cluster.get("signature"),
                "error_count": cluster.get("error_count"),
                "affected_services": cluster.get("affected_services", []),
                "deployment_ids": cluster.get("deployment_ids", []),
                "commit_shas": cluster.get("commit_shas", []),
                "changed_files": cluster.get("changed_files", []),
                "workflow_steps": cluster.get("workflow_steps", []),
            },
            "context": {
                "deployment_correlation": context.get("deployment_correlation", {}),
                "metrics_anomalies": context.get("metrics_anomalies", []),
                "regression_history": context.get("regression_history", []),
                "propagation_chain": context.get("propagation_chain", []),
            },
            "hypothesis": {
                "summary": hypothesis.summary,
                "likely_cause": hypothesis.likely_cause,
                "confidence": hypothesis.confidence,
                "severity": hypothesis.severity,
                "recommended_actions": hypothesis.recommended_actions,
                "risk_assessment": hypothesis.risk_assessment,
            },
        }

    def _call_groq(self, prompt: str) -> str:
        response = self._client.chat.completions.create(
            model="mixtral-8x7b-32768",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=900,
            timeout=12.0,
        )
        return response.choices[0].message.content.strip()

    def _parse_response(self, response: str) -> Dict[str, Any]:
        try:
            parsed = json.loads(response)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass
        return {
            "operational_summary": response,
            "likely_cause": response,
            "confidence": 0.55,
            "recommended_actions": [],
            "risk_assessment": "unknown",
        }

    def _fallback_reasoning(self, cluster: Dict[str, Any], hypothesis, context: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "operational_summary": hypothesis.summary,
            "likely_cause": hypothesis.likely_cause,
            "confidence": hypothesis.confidence,
            "recommended_actions": hypothesis.recommended_actions,
            "risk_assessment": hypothesis.risk_assessment,
            "severity": hypothesis.severity,
            "grounding": self._grounding(cluster, context, hypothesis),
        }