"""
AI Synthesis Engine (Groq-powered).

Converts ALL collected operational evidence into a single, repository-specific
operational brief.  Every output is grounded in the actual evidence passed in.

FAIL LOUD: if Groq is unavailable or misconfigured this raises RuntimeError.
There are NO fallback heuristics. NO mock summaries. NO static defaults.

Output schema:
{
    "operational_summary":   str,   # 2-3 sentence narrative
    "root_cause":            str,   # inferred root cause or "unknown"
    "repository_type":       str,   # e.g. "backend_api"
    "affected_services":     list,  # service names impacted
    "detected_strengths":    list,  # things that ARE in place
    "detected_gaps":         list,  # things that are MISSING
    "deployment_risks":      list,  # deployment-specific risks
    "monitoring_risks":      list,  # observability gaps
    "rollback_confidence":   str,   # "high" | "medium" | "low"
    "recommended_actions":   list,  # 3-5 concrete actions
    "operational_confidence":float, # 0.0 – 1.0
    "severity":              str,   # "Critical" | "High" | "Medium" | "Low"
    "health_state":          str,   # "Healthy" | "Degraded" | "Critical"
    "human_summary":         str,   # 1-sentence TL;DR
    "final_assessment":      str    # 1-2 sentence executive summary
}
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from groq import Groq
from config import get_config

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are an AI operational reliability analyst for DevANT.

Your task: analyze the operational evidence for THIS SPECIFIC REPOSITORY and produce a
precise, evidence-grounded operational brief.

STRICT RULES:
1. NEVER produce generic advice. Every risk and recommendation MUST reference
   specific evidence from the payload.
2. If evidence is absent, say so explicitly ("No Kubernetes manifests detected,
   so rollback confidence cannot be assessed").
3. Do NOT invent infrastructure that was not detected.
4. Recommendations must differ between repositories — they must reflect THIS repo's
   actual evidence.
5. The repository_type field tells you what kind of system this is — adjust your
   analysis accordingly:
   - frontend_app     → focus on CDN, build pipeline, bundle monitoring
   - backend_api      → focus on API error rates, latency, DB, rollback
   - microservices    → focus on inter-service propagation, topology resilience
   - infrastructure   → focus on IaC drift, state consistency, apply risk
   - ml_ai            → focus on model serving, GPU, data pipeline health
   - data_pipeline    → focus on DAG health, SLA, data quality
6. detected_strengths: list things that ARE correctly in place.
7. detected_gaps: list things that are MISSING based on repo type expectations.
8. rollback_confidence must be justified: "high" only if rollback workflow evidence
   exists; "low" if no Helm/K8s/workflow rollback steps were detected.
9. operational_confidence must reflect evidence density:
   - >= 0.8 only if workflows + topology + observability all present
   - <= 0.4 if most evidence buckets are empty
10. health_state:
    - "Healthy"  → scores > 0.7, live errors ≤ 1, strong monitoring
    - "Degraded" → moderate scores or 2-4 active error clusters
    - "Critical" → scores < 0.4 or >= 5 active error clusters or S1/S2 errors

Respond ONLY with a valid JSON object matching this exact schema — no markdown, no
explanation outside the JSON:
{
  "operational_summary":    "<2-3 sentences, evidence-specific>",
  "root_cause":             "<inferred root cause or 'Insufficient evidence to determine'>",
  "repository_type":        "<value from input>",
  "affected_services":      ["<service1>", ...],
  "detected_strengths":     ["<thing1>", ...],
  "detected_gaps":          ["<thing1>", ...],
  "deployment_risks":       ["<risk1>", ...],
  "monitoring_risks":       ["<risk1>", ...],
  "rollback_confidence":    "high|medium|low",
  "recommended_actions":    ["<action1>", "<action2>", "<action3>"],
  "operational_confidence": <0.0-1.0>,
  "severity":               "Critical|High|Medium|Low",
  "health_state":           "Healthy|Degraded|Critical",
  "human_summary":          "<1 sentence TL;DR>",
  "final_assessment":       "<1-2 sentence executive summary>"
}
"""


class SynthesisEngine:
    """
    Evidence-grounded AI synthesis.  Requires GROQ_API_KEY.

    Raises RuntimeError at construction time if Groq is not configured.
    """

    def __init__(self):
        cfg = get_config()
        if not cfg.groq.api_key:
            raise RuntimeError(
                "GROQ_API_KEY is not set. "
                "DevANT AI synthesis requires a valid Groq API key."
            )
        self._model = cfg.groq.model
        self._client = Groq(api_key=cfg.groq.api_key)
        logger.info(f"SynthesisEngine ready — model={self._model}")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def synthesize(
        self,
        evidence: Dict[str, Any],
        topology: Dict[str, Any],
        scores: Dict[str, Any],
        propagation: Dict[str, Any] | None = None,
        # Extended evidence from unified orchestrator
        repo_type: str = "unknown",
        github_context: Dict[str, Any] | None = None,
        live_error_clusters: List[Dict[str, Any]] | None = None,
        temporal_memory: Dict[str, Any] | None = None,
        signal_fusion: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        """
        Synthesize ALL evidence into an operational brief.

        Raises RuntimeError if Groq call fails — no silent fallbacks.
        """
        payload = self._build_payload(
            evidence=evidence,
            topology=topology,
            scores=scores,
            propagation=propagation or {},
            repo_type=repo_type,
            github_context=github_context or {},
            live_error_clusters=live_error_clusters or [],
            temporal_memory=temporal_memory or {},
            signal_fusion=signal_fusion or {},
        )

        user_content = json.dumps(payload, default=str)

        logger.info(
            f"SynthesisEngine: sending {len(user_content)} chars to Groq "
            f"(model={self._model})"
        )

        try:
            response = self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": user_content},
                ],
                response_format={"type": "json_object"},
                temperature=0.15,
                max_tokens=1500,
            )
        except Exception as exc:
            raise RuntimeError(f"Groq synthesis failed: {exc}") from exc

        content = response.choices[0].message.content
        try:
            result = json.loads(content)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"Groq returned invalid JSON: {exc}\nRaw: {content[:200]}"
            ) from exc

        # Attach repo_type in case LLM dropped it
        result.setdefault("repository_type", repo_type)
        logger.info(
            f"SynthesisEngine: health_state={result.get('health_state')} "
            f"confidence={result.get('operational_confidence')}"
        )
        return result

    # ------------------------------------------------------------------
    # Payload builder — keeps context window lean but information-rich
    # ------------------------------------------------------------------

    @staticmethod
    def _build_payload(
        evidence: Dict[str, Any],
        topology: Dict[str, Any],
        scores: Dict[str, Any],
        propagation: Dict[str, Any],
        repo_type: str,
        github_context: Dict[str, Any],
        live_error_clusters: List[Dict[str, Any]],
        temporal_memory: Dict[str, Any],
        signal_fusion: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Build a context-rich but token-efficient payload for Groq."""

        # --- live error summary (top 5 clusters) ----------------------
        error_summary = []
        for c in live_error_clusters[:5]:
            error_summary.append({
                "signature": c.get("signature", c.get("title", ""))[:80],
                "error_count": c.get("error_count", 1),
                "affected_orgs": c.get("affected_orgs", [])[:3],
                "modules": c.get("modules", [])[:3],
                "severity_level": c.get("error_type", "ERROR"),
            })

        # --- topology summary -----------------------------------------
        topo_summary = {
            "service_count": len(topology.get("services", [])),
            "edge_count": len(topology.get("edges", [])),
            "service_names": [
                s.get("name", "") for s in topology.get("services", [])[:8]
            ],
        }
        if propagation:
            topo_summary["blast_radius"] = propagation.get("blast_radius", 0)
            topo_summary["dominant_service"] = propagation.get("dominant_service", "")
            topo_summary["upstream_risk"] = propagation.get("upstream_risk", 0)

        # --- github context summary -----------------------------------
        gh_summary: Dict[str, Any] = {}
        if github_context:
            gh_summary["recent_commits"] = len(github_context.get("commits", []))
            gh_summary["recent_prs"] = len(github_context.get("prs", []))
            gh_summary["primary_language"] = github_context.get("primary_language", "")
            if github_context.get("commits"):
                gh_summary["latest_commit"] = github_context["commits"][0].get("message", "")[:80]
            if github_context.get("prs"):
                gh_summary["latest_pr"] = github_context["prs"][0].get("title", "")[:80]

        # --- evidence counts (avoids dumping huge file lists) ---------
        ev_summary = {
            "workflows": len(evidence.get("workflows", [])),
            "dockerfiles": len(evidence.get("dockerfiles", [])),
            "kubernetes_manifests": len(evidence.get("kubernetes_manifests", [])),
            "helm_charts": len(evidence.get("helm_charts", [])),
            "terraform": len(evidence.get("terraform", [])),
            "prometheus": bool(evidence.get("prometheus")),
            "otel": bool(evidence.get("otel")),
            "services_detected": len(evidence.get("services", [])),
            "package_managers": evidence.get("package_managers", []),
            "live_error_clusters": len(live_error_clusters),
        }

        return {
            "repository_type": repo_type,
            "evidence": ev_summary,
            "topology": topo_summary,
            "health_scores": scores,
            "live_incidents": error_summary,
            "github_context": gh_summary,
            "temporal_memory": {
                "is_recurring": temporal_memory.get("is_recurring", False),
                "recurrence_count": temporal_memory.get("recurrence_count", 0),
                "drift_score": temporal_memory.get("drift_score", 0),
                "pattern_type": temporal_memory.get("pattern_type"),
            },
            "signal_fusion": {
                "confidence": signal_fusion.get("confidence", 0),
                "sparse_evidence": signal_fusion.get("sparse_evidence", True),
                "conflict_count": signal_fusion.get("conflict_count", 0),
            },
        }
