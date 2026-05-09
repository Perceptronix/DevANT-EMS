"""Topology-based propagation analysis for operational blast radius reasoning."""

from typing import Dict, Any, List, Set, Tuple
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)


@dataclass
class PropagationAnalysis:
    """Result of topology propagation analysis."""
    blast_radius: int  # Number of affected services
    critical_paths: List[List[str]]  # Chains of dependencies
    dominant_service: str  # Most connected service
    upstream_risk: float  # Risk from upstream dependencies
    downstream_risk: float  # Risk to downstream dependents
    service_count: int  # Total services
    edge_count: int  # Total dependencies
    high_risk_dependencies: List[Dict[str, Any]]  # Critical paths
    propagation_depth: int  # Maximum traversal depth


class TopologyPropagationEngine:
    """Analyze service topology for operational propagation patterns."""
    
    def __init__(self):
        self.topology_graph = None
        self.adjacency = {}  # service -> [dependents]
        self.reverse_adjacency = {}  # service -> [dependencies]
    
    def analyze(
        self,
        topology_graph: Dict[str, Any],
        operational_scores: Dict[str, float] = None
    ) -> PropagationAnalysis:
        """Analyze topology for propagation patterns and blast radius.
        
        Args:
            topology_graph: {services: [...], edges: [{from, to}, ...]}
            operational_scores: Optional scores for risk weighting
        
        Returns:
            PropagationAnalysis with blast radius, critical paths, etc.
        """
        self.topology_graph = topology_graph
        operational_scores = operational_scores or {}
        
        services = topology_graph.get('services', [])
        edges = topology_graph.get('edges', [])
        
        service_names = {s['name']: s for s in services}
        
        # Build adjacency structures
        self.adjacency = {s['name']: [] for s in services}
        self.reverse_adjacency = {s['name']: [] for s in services}
        
        for edge in edges:
            source = edge.get('from')
            target = edge.get('to')
            
            if source and target and source in self.adjacency and target in self.adjacency:
                self.adjacency[source].append(target)  # source -> target dependency
                self.reverse_adjacency[target].append(source)  # target depends on source
        
        # Compute metrics
        dominant_service = self._find_dominant_service()
        
        # Blast radius: depth-first traversal from most critical service
        blast_radius = self._compute_blast_radius(dominant_service)
        
        # Critical paths: longest chains of dependencies
        critical_paths = self._find_critical_paths()
        
        # Risk assessment
        upstream_risk = self._compute_upstream_risk(dominant_service, service_names)
        downstream_risk = self._compute_downstream_risk(dominant_service, service_names)
        
        # High-risk dependencies
        high_risk_deps = self._identify_high_risk_dependencies(service_names, operational_scores)
        
        # Propagation depth
        propagation_depth = self._compute_max_depth()
        
        return PropagationAnalysis(
            blast_radius=blast_radius,
            critical_paths=critical_paths,
            dominant_service=dominant_service or 'unknown',
            upstream_risk=min(1.0, upstream_risk),
            downstream_risk=min(1.0, downstream_risk),
            service_count=len(services),
            edge_count=len(edges),
            high_risk_dependencies=high_risk_deps,
            propagation_depth=propagation_depth,
        )
    
    def _find_dominant_service(self) -> str:
        """Find most connected service (hub)."""
        if not self.adjacency:
            return None
        
        # Service with most outgoing + incoming edges
        connectivity = {}
        for svc, deps in self.adjacency.items():
            connectivity[svc] = len(deps) + len(self.reverse_adjacency.get(svc, []))
        
        return max(connectivity, key=connectivity.get) if connectivity else None
    
    def _compute_blast_radius(self, root_service: str) -> int:
        """Compute number of services affected if root service fails."""
        if not root_service:
            return 0
        
        affected = set()
        queue = [root_service]
        
        while queue:
            svc = queue.pop(0)
            if svc in affected:
                continue
            affected.add(svc)
            
            # Add downstream dependents
            if svc in self.adjacency:
                for dep in self.adjacency[svc]:
                    if dep not in affected:
                        queue.append(dep)
        
        return len(affected) - 1  # Exclude root itself
    
    def _find_critical_paths(self, max_paths: int = 5) -> List[List[str]]:
        """Find longest dependency chains."""
        paths = []
        visited_global = set()
        
        def dfs(node: str, path: List[str]) -> None:
            """Depth-first traversal to find chains."""
            if len(path) > 8:  # Limit depth
                return
            
            if not self.adjacency.get(node):
                if len(path) > 1:
                    paths.append(path.copy())
                return
            
            for neighbor in self.adjacency[node]:
                if neighbor not in path:  # Avoid cycles
                    path.append(neighbor)
                    dfs(neighbor, path)
                    path.pop()
        
        # Start from each service
        for service in self.adjacency.keys():
            if len(paths) >= max_paths:
                break
            dfs(service, [service])
        
        # Sort by length (longest first)
        paths.sort(key=len, reverse=True)
        return paths[:max_paths]
    
    def _compute_upstream_risk(self, root_service: str, service_info: Dict) -> float:
        """Risk to root service from upstream dependencies."""
        if not root_service or root_service not in self.reverse_adjacency:
            return 0.0
        
        dependencies = self.reverse_adjacency.get(root_service, [])
        if not dependencies:
            return 0.0
        
        # Risk increases with number of upstream deps
        base_risk = min(1.0, len(dependencies) / 5.0)
        return base_risk
    
    def _compute_downstream_risk(self, root_service: str, service_info: Dict) -> float:
        """Risk to downstream services if root service fails."""
        if not root_service or root_service not in self.adjacency:
            return 0.0
        
        dependents = self.adjacency.get(root_service, [])
        if not dependents:
            return 0.0
        
        # Risk increases with blast radius
        blast = self._compute_blast_radius(root_service)
        base_risk = min(1.0, blast / max(len(self.adjacency), 1))
        return base_risk
    
    def _identify_high_risk_dependencies(
        self,
        service_info: Dict,
        scores: Dict[str, float]
    ) -> List[Dict[str, Any]]:
        """Identify critical dependencies."""
        high_risk = []
        
        for source, targets in self.adjacency.items():
            if not targets:
                continue
            
            # Score based on fanout (how many services depend on this)
            fanout = len(targets)
            importance = min(1.0, fanout / 3.0)
            
            for target in targets:
                risk_score = importance + scores.get('regression_risk', 0.0) * 0.3
                high_risk.append({
                    'from': source,
                    'to': target,
                    'risk': min(1.0, risk_score),
                    'fanout': fanout,
                })
        
        # Sort by risk (highest first)
        high_risk.sort(key=lambda x: x['risk'], reverse=True)
        return high_risk[:10]  # Top 10 highest risk
    
    def _compute_max_depth(self) -> int:
        """Compute maximum traversal depth in graph."""
        if not self.adjacency:
            return 0
        
        max_d = 0
        
        def dfs_depth(node: str, depth: int, visited: Set[str]) -> int:
            if node in visited or depth > 20:
                return depth
            visited.add(node)
            
            max_depth = depth
            for neighbor in self.adjacency.get(node, []):
                d = dfs_depth(neighbor, depth + 1, visited.copy())
                max_depth = max(max_depth, d)
            
            return max_depth
        
        for service in self.adjacency.keys():
            d = dfs_depth(service, 0, set())
            max_d = max(max_d, d)
        
        return min(max_d, 20)
