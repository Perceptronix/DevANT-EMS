"""
Operational scoring engine. Deterministic scores derived from repository evidence.
All scores in [0,1].
"""
from typing import Dict, Any
try:
    from .evidence_engine import EvidenceEngine
except Exception:
    EvidenceEngine = None


class OperationalScoringEngine:
    def __init__(self):
        pass

    def score(self, evidence: Dict[str, Any], topology: Dict[str, Any]) -> Dict[str, float]:
        """Public score method - delegates to score_from_evidence."""
        return self.score_from_evidence(evidence, topology)

    def _norm(self, v: float) -> float:
        if v < 0:
            v = 0.0
        if v > 1:
            v = 1.0
        return v

    def score_from_evidence(self, evidence: Dict[str, Any], topology: Dict[str, Any]) -> Dict[str, float]:
        # If evidence engine available, use it to compute confidences
        if EvidenceEngine is not None:
            ee = EvidenceEngine()
            ev = ee.evaluate(evidence, topology)
            # map evidence confidences into scores with conservative scaling
            scores = {
                'deployment_maturity': round(ev.get('deployment_confidence', 0.0) * 0.9, 3),
                'observability_readiness': round(ev.get('observability_confidence', 0.0) * 0.95, 3),
                'rollback_safety': 0.3 + 0.4 * ev.get('deployment_confidence', 0.0),
                'retry_resilience': 0.2 + 0.3 * min(1.0, ev.get('details', {}).get('workflow_count', 0) / 3),
                'topology_resilience': round(ev.get('topology_confidence', 0.0), 3),
                'operational_complexity': min(1.0, (len(topology.get('services', [])) * 0.15) + (len(topology.get('edges', [])) * 0.05)),
                'regression_risk': round(0.5 + max(0.0, 0.3 - ev.get('observability_confidence', 0.0) * 0.3), 3),
                'production_readiness': round(0.35 * ev.get('deployment_confidence', 0.0) + 0.45 * ev.get('observability_confidence', 0.0) + 0.2 * (1.0 - min(1.0, (len(topology.get('services', [])) * 0.15))), 3),
            }
            return scores

        scores = {
            'deployment_maturity': 0.0,
            'observability_readiness': 0.0,
            'rollback_safety': 0.0,
            'retry_resilience': 0.0,
            'topology_resilience': 0.0,
            'operational_complexity': 0.0,
            'regression_risk': 0.0,
            'production_readiness': 0.0,
        }

        # Deployment maturity heuristics
        workflows = evidence.get('workflows', [])
        dockerfiles = evidence.get('dockerfiles', [])
        terraform = evidence.get('terraform', [])
        has_k8s = len(evidence.get('kubernetes_manifests', [])) > 0

        deploy_score = 0.0
        if workflows:
            deploy_score += 0.4
        if dockerfiles:
            deploy_score += 0.25
        if terraform:
            deploy_score += 0.2
        if has_k8s:
            deploy_score += 0.15
        scores['deployment_maturity'] = self._norm(deploy_score)

        # Observability readiness
        obs = 0.0
        if evidence.get('prometheus'):
            obs += 0.5
        if evidence.get('otel'):
            obs += 0.4
        # presence of metrics + some workflows
        if workflows and evidence.get('prometheus'):
            obs += 0.05
        scores['observability_readiness'] = self._norm(obs)

        # Rollback safety: presence of deployments with versions, or Helm charts
        helm = len(evidence.get('helm_charts', []))
        if helm:
            scores['rollback_safety'] = self._norm(0.7 + min(helm * 0.05, 0.25))
        else:
            # if k8s manifests present but no helm, moderate
            if has_k8s:
                scores['rollback_safety'] = 0.4
            else:
                scores['rollback_safety'] = 0.2

        # Retry resilience: detect explicit retry patterns in workflows or manifests
        retry_hints = 0
        for w in workflows:
            content = w.get('content_preview', '') if isinstance(w, dict) else ''
            if 'retry' in content or 'max_retries' in content or 'retry-after' in content:
                retry_hints += 1
        scores['retry_resilience'] = self._norm(min(1.0, 0.2 * retry_hints))

        # Topology resilience: from topology extractor
        services = topology.get('services', []) if topology else []
        edges = topology.get('edges', []) if topology else []
        if services:
            deg = len(edges) / max(1, len(services))
            # too many edges per service → complexity → reduce resilience
            scores['topology_resilience'] = self._norm(max(0.0, 1.0 - min(deg / 5.0, 0.8)))
        else:
            scores['topology_resilience'] = 0.3

        # Operational complexity: more services and more edges increase complexity
        complexity = min(1.0, (len(services) * 0.15) + (len(edges) * 0.05))
        scores['operational_complexity'] = self._norm(complexity)

        # Regression risk: if limited observability but many services, risk higher
        risk = 0.5
        if scores['observability_readiness'] < 0.4:
            risk += 0.3
        if len(services) > 3:
            risk += 0.1
        scores['regression_risk'] = self._norm(risk)

        # Production readiness: composite
        prod = 0.0
        prod += 0.4 * scores['deployment_maturity']
        prod += 0.4 * scores['observability_readiness']
        prod += 0.2 * (1.0 - scores['operational_complexity'])
        scores['production_readiness'] = self._norm(prod)

        return scores
