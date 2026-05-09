from dataclasses import dataclass, field
from typing import List, Optional
from datetime import datetime

import json, logging, threading
from pathlib import Path
from dataclasses import asdict
from datetime import timedelta
from typing import Dict, Any

logger = logging.getLogger(__name__)
INCIDENT_GRAPH_FILE = Path("data/incident_graph.json")
_lock = threading.Lock()

@dataclass
class IncidentMemory:
    incident_id: str
    error_signature: str
    service: str
    stack_trace: str
    deployment_id: Optional[str] = None
    commit_hash: Optional[str] = None
    owner: Optional[str] = None
    severity: str = "unknown"
    root_cause: Optional[str] = None
    resolution: Optional[str] = None
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    status: str = "open"
    historical_matches: List[str] = field(default_factory=list)
    deployment_lineage: List[str] = field(default_factory=list)
    recurring_cluster_id: Optional[str] = None
    temporal_drift_score: float = 0.0
    affected_services: List[str] = field(default_factory=list)

@dataclass
class IncidentNode:
    incident_id: str
    timestamp: str
    repo: str
    dominant_service: str
    blast_radius: int
    operational_confidence: float
    regression_risk: float
    topology_hash: str
    critical_paths: List[List[str]] = field(default_factory=list)
    upstream_risk: float = 0.0
    downstream_risk: float = 0.0

@dataclass
class IncidentEdge:
    source_incident: str
    target_incident: str
    relationship: str
    confidence: float

class IncidentGraph:
    def __init__(self):
        self.nodes: Dict[str, IncidentNode] = {}
        self.edges: List[IncidentEdge] = []
        self.incidents: List[IncidentMemory] = []
        self._load_from_disk()
    
    def add_incident(self, incident_id: str, timestamp: str, repo: str, dominant_service: str,
                     blast_radius: int, operational_confidence: float, regression_risk: float,
                     topology_hash: str, critical_paths: Optional[List[List[str]]] = None,
                     upstream_risk: float = 0.0, downstream_risk: float = 0.0) -> IncidentNode:
        node = IncidentNode(incident_id, timestamp, repo, dominant_service, blast_radius,
                           operational_confidence, regression_risk, topology_hash,
                           critical_paths or [], upstream_risk, downstream_risk)
        self.nodes[incident_id] = node
        self._detect_relationships(node)
        self._save_to_disk()
        return node
    
    def detect_recurring_patterns(self, incident: IncidentNode) -> Dict[str, Any]:
        if not self.nodes:
            return {'is_recurring': False, 'matched_incidents': [], 'pattern_type': None,
                    'recurrence_count': 0, 'confidence': 0.0}
        matched, pattern_types = [], []
        same_service = [n for n, nd in self.nodes.items()
                       if nd.dominant_service == incident.dominant_service and nd.repo == incident.repo]
        if len(same_service) >= 2:
            matched.extend(same_service)
            pattern_types.append('dominant_service')
        similar_radius = [n for n, nd in self.nodes.items()
                         if abs(nd.blast_radius - incident.blast_radius) <= 1 and nd.repo == incident.repo]
        if len(similar_radius) >= 3:
            matched.extend(similar_radius)
            pattern_types.append('blast_radius')
        high_regression = [n for n, nd in self.nodes.items()
                          if nd.regression_risk > 0.6 and incident.regression_risk > 0.6 and nd.repo == incident.repo]
        if len(high_regression) >= 2:
            matched.extend(high_regression)
            pattern_types.append('regression')
        matched = list(set(matched))
        return {'is_recurring': len(matched) >= 2, 'matched_incidents': matched[:10],
                'pattern_type': pattern_types[0] if pattern_types else None,
                'recurrence_count': len(matched), 'confidence': min(1.0, len(matched) / 5.0) if matched else 0.0}

    def detect_recurring_deployment_failures(self, service: str, deployment_id: str) -> Dict[str, Any]:
        related = [incident for incident in self.incidents if incident.service == service and incident.deployment_id == deployment_id]
        return {
            'is_recurring': len(related) >= 2,
            'deployment_id': deployment_id,
            'service': service,
            'occurrence_count': len(related),
            'incident_ids': [incident.incident_id for incident in related[:10]],
            'confidence': min(1.0, len(related) / 4.0) if related else 0.0,
        }

    def track_deployment_failure_lineage(self, incident_id: str) -> List[str]:
        lineage = self.get_incident_lineage(incident_id, depth=8)
        if incident_id not in lineage:
            lineage.insert(0, incident_id)
        return lineage
    
    def analyze_operational_drift(self, repo: str) -> Dict[str, Any]:
        repo_inc = [n for n in self.nodes.values() if n.repo == repo]
        if len(repo_inc) < 2:
            return {'has_drift': False, 'blast_radius_trend': 0.0, 'confidence_trend': 0.0,
                    'regression_trend': 0.0, 'topology_instability': 0.0,
                    'recent_incidents': len(repo_inc), 'drift_score': 0.0}
        sorted_inc = sorted(repo_inc, key=lambda x: x.timestamp)
        mid = len(sorted_inc) // 2
        first, second = sorted_inc[:mid], sorted_inc[mid:]
        avg_r1 = sum(i.blast_radius for i in first) / len(first)
        avg_r2 = sum(i.blast_radius for i in second) / len(second)
        trend_r = 1.0 if avg_r2 > avg_r1 * 1.1 else (-1.0 if avg_r2 < avg_r1 * 0.9 else 0.0)
        avg_c1 = sum(i.operational_confidence for i in first) / len(first)
        avg_c2 = sum(i.operational_confidence for i in second) / len(second)
        trend_c = -1.0 if avg_c2 < avg_c1 * 0.9 else (1.0 if avg_c2 > avg_c1 * 1.1 else 0.0)
        avg_g1 = sum(i.regression_risk for i in first) / len(first)
        avg_g2 = sum(i.regression_risk for i in second) / len(second)
        trend_g = 1.0 if avg_g2 > avg_g1 * 1.1 else (-1.0 if avg_g2 < avg_g1 * 0.9 else 0.0)
        topo_h = set(i.topology_hash for i in repo_inc)
        topo_inst = min(1.0, len(topo_h) / len(repo_inc))
        now = datetime.fromisoformat(sorted_inc[-1].timestamp)
        wk_ago = now - timedelta(days=7)
        recent = sum(1 for i in repo_inc if datetime.fromisoformat(i.timestamp) >= wk_ago)
        drift = min(1.0, abs(trend_r) * 0.3 + abs(trend_c) * 0.3 + abs(trend_g) * 0.2 + topo_inst * 0.2)
        return {'has_drift': drift > 0.3, 'blast_radius_trend': trend_r, 'confidence_trend': trend_c,
                'regression_trend': trend_g, 'topology_instability': topo_inst,
                'recent_incidents': recent, 'drift_score': drift}

    def summarize_regression_tracking(self, repo: str) -> Dict[str, Any]:
        repo_incidents = [node for node in self.nodes.values() if node.repo == repo]
        recurring = [node.incident_id for node in repo_incidents if self.detect_recurring_patterns(node)['is_recurring']]
        return {
            'repo': repo,
            'tracked_incidents': len(repo_incidents),
            'recurring_incidents': recurring[:20],
            'recurring_count': len(recurring),
            'lineage_depth': max((len(self.get_incident_lineage(node.incident_id)) for node in repo_incidents), default=0),
            'drift_score': self.analyze_operational_drift(repo)['drift_score'] if repo_incidents else 0.0,
        }
    
    def find_historical_similarity(self, incident: IncidentNode, threshold: float = 0.7) -> List[Dict]:
        sims = []
        for n_id, nd in self.nodes.items():
            sm = 1.0 if nd.dominant_service == incident.dominant_service else 0.0
            rm = 1.0 - min(1.0, abs(nd.blast_radius - incident.blast_radius) / 10.0)
            gm = 1.0 - abs(nd.regression_risk - incident.regression_risk)
            cm = 1.0 - abs(nd.operational_confidence - incident.operational_confidence)
            sim = sm * 0.4 + rm * 0.3 + gm * 0.15 + cm * 0.15
            if sim >= threshold:
                sims.append({'incident_id': n_id, 'similarity': sim, 'timestamp': nd.timestamp,
                            'dominant_service': nd.dominant_service, 'blast_radius': nd.blast_radius})
        sims.sort(key=lambda x: x['similarity'], reverse=True)
        return sims[:10]
    
    def get_incident_lineage(self, incident_id: str, depth: int = 5) -> List[str]:
        lin = [incident_id]
        curr = incident_id
        for _ in range(depth):
            pred = [e.source_incident for e in self.edges
                   if e.target_incident == curr and e.source_incident not in lin]
            if not pred:
                break
            curr = pred[0]
            lin.append(curr)
        return lin
    
    def add_resolved(self, incident: IncidentMemory):
        incident.deployment_lineage = incident.deployment_lineage or ([incident.deployment_id] if incident.deployment_id else [])
        self.incidents.append(incident)
    
    def find_similar(self, signature: str, threshold: float = 0.6) -> List[IncidentMemory]:
        return [i for i in self.incidents if i.error_signature == signature or i.service in signature]
    
    def _detect_relationships(self, new_inc: IncidentNode) -> None:
        if not self.nodes or len(self.nodes) == 1:
            return
        recent = max((nd for n, nd in self.nodes.items() if n != new_inc.incident_id),
                    key=lambda x: x.timestamp, default=None)
        if not recent:
            return
        if recent.dominant_service == new_inc.dominant_service:
            self.edges.append(IncidentEdge(recent.incident_id, new_inc.incident_id, 'recurring', 0.8))
        if new_inc.blast_radius > recent.blast_radius:
            self.edges.append(IncidentEdge(recent.incident_id, new_inc.incident_id, 'escalation',
                                          min(1.0, new_inc.blast_radius / 10.0)))
        if recent.topology_hash == new_inc.topology_hash:
            self.edges.append(IncidentEdge(recent.incident_id, new_inc.incident_id, 'similar', 0.9))
    
    def _save_to_disk(self) -> None:
        with _lock:
            INCIDENT_GRAPH_FILE.parent.mkdir(parents=True, exist_ok=True)
            data = {'nodes': {nid: asdict(nd) for nid, nd in self.nodes.items()},
                   'edges': [{'source_incident': e.source_incident, 'target_incident': e.target_incident,
                             'relationship': e.relationship, 'confidence': e.confidence} for e in self.edges]}
            INCIDENT_GRAPH_FILE.write_text(json.dumps(data, indent=2, default=str))
    
    def _load_from_disk(self) -> None:
        with _lock:
            if not INCIDENT_GRAPH_FILE.exists():
                return
            try:
                data = json.loads(INCIDENT_GRAPH_FILE.read_text())
                for nid, nd_data in data.get('nodes', {}).items():
                    self.nodes[nid] = IncidentNode(**nd_data)
                for ed in data.get('edges', []):
                    self.edges.append(IncidentEdge(**ed))
                logger.info(f"Loaded {len(self.nodes)} incidents, {len(self.edges)} edges")
            except Exception as e:
                logger.error(f"Failed to load incident graph: {e}")

_graph: Optional[IncidentGraph] = None


def get_incident_graph() -> IncidentGraph:
    global _graph
    if _graph is None:
        _graph = IncidentGraph()
    return _graph
