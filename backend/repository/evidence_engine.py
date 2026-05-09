"""
Evidence engine: compute evidence depth and confidence scores for various operational dimensions.
"""
from typing import Dict, Any


class EvidenceEngine:
    def __init__(self):
        pass

    def evaluate(self, evidence: Dict[str, Any], topology: Dict[str, Any]) -> Dict[str, Any]:
        """Return structured evidence strengths and guidance.
        Keys: deployment_confidence, observability_confidence, topology_confidence, evidence_depth
        """
        result = {
            'deployment_confidence': 0.0,
            'observability_confidence': 0.0,
            'topology_confidence': 0.0,
            'evidence_depth': 0,
            'details': {}
        }

        depth = 0
        # Workflows depth
        workflows = evidence.get('workflows', [])
        wf_strength = 0.0
        for wf in workflows:
            # presence of 'deploy' or 'deploy:' or 'deployment' in name increases strength
            name = wf.get('name', '') if isinstance(wf, dict) else ''
            path = wf.get('path', '') if isinstance(wf, dict) else ''
            low = (name + ' ' + path).lower()
            if 'deploy' in low or 'rollback' in low or 'canary' in low:
                wf_strength += 0.6
            else:
                wf_strength += 0.2
            depth += 1
        # normalize
        if workflows:
            wf_strength = min(1.0, wf_strength / max(1, len(workflows)))
        result['deployment_confidence'] = wf_strength

        # Prometheus + OTEL depth
        obs_strength = 0.0
        if evidence.get('prometheus'):
            obs_strength += 0.5
            depth += 1
        if evidence.get('otel'):
            obs_strength += 0.4
            depth += 1
        # presence of recording/alerts hints would raise strength; for now small bump if both present
        if evidence.get('prometheus') and evidence.get('otel'):
            obs_strength = min(1.0, obs_strength + 0.05)
        result['observability_confidence'] = obs_strength

        # Topology confidence based on topology clarity
        services = topology.get('services', []) if topology else []
        edges = topology.get('edges', []) if topology else []
        if services:
            clarity = max(0.0, 1.0 - (len(edges) / max(1, len(services) * 3)))
            result['topology_confidence'] = min(1.0, clarity)
            depth += len(services)
        else:
            result['topology_confidence'] = 0.0

        result['evidence_depth'] = depth
        result['details'] = {
            'workflow_count': len(workflows),
            'prometheus': bool(evidence.get('prometheus')),
            'otel': bool(evidence.get('otel')),
            'service_count': len(services),
        }
        return result
