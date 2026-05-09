"""
Topology discovery for live operational systems.

Dynamically discovers:
- Service dependencies
- Downstream relationships
- Ownership relationships
- Propagation paths
- Blast radius estimation

Sources:
- Traces (parent-child span relationships)
- Metrics (service-to-service latency)
- Deployment events (service ownership)
- Configuration (explicit dependencies)
"""

from dataclasses import dataclass, field
from typing import Dict, List, Set, Tuple, Optional, Any
from datetime import datetime, timezone, timedelta
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class DependencyType(Enum):
    """Type of service dependency."""
    SYNCHRONOUS_RPC = "sync_rpc"
    ASYNCHRONOUS_QUEUE = "async_queue"
    DATABASE = "database"
    CACHE = "cache"
    MESSAGE_BROKER = "message_broker"
    EXTERNAL_API = "external_api"
    UNKNOWN = "unknown"


@dataclass
class ServiceDependency:
    """
    Relationship between two services.
    
    Source service depends on target service.
    """
    source_service: str
    target_service: str
    dependency_type: DependencyType = DependencyType.UNKNOWN
    
    # Observability
    call_count: int = 0
    error_count: int = 0
    p95_latency_ms: float = 0.0
    
    # Discovery metadata
    first_observed: Optional[datetime] = None
    last_observed: Optional[datetime] = None
    confidence: float = 1.0  # 0.0 (inferred) to 1.0 (observed)
    
    def __post_init__(self):
        if self.first_observed is None:
            self.first_observed = datetime.now(timezone.utc)
        if self.last_observed is None:
            self.last_observed = datetime.now(timezone.utc)
    
    def error_rate(self) -> float:
        """Ratio of errors to total calls."""
        if self.call_count == 0:
            return 0.0
        return self.error_count / self.call_count
    
    def is_healthy(self, error_threshold: float = 0.05, latency_threshold_ms: float = 10000.0) -> bool:
        """Dependency considered healthy."""
        return (
            self.error_rate() <= error_threshold
            and self.p95_latency_ms < latency_threshold_ms
        )
    
    def freshness_days(self) -> float:
        """Days since last observation."""
        if not self.last_observed:
            return float('inf')
        now = datetime.now(timezone.utc)
        return (now - self.last_observed).days


@dataclass
class ServiceNode:
    """Service in topology graph."""
    name: str
    owner: Optional[str] = None
    environment: str = "production"
    tags: Dict[str, str] = field(default_factory=dict)
    
    # Dependencies
    dependencies: Dict[str, ServiceDependency] = field(default_factory=dict)  # target -> dependency
    dependents: Set[str] = field(default_factory=set)  # services that depend on this
    
    # Health
    is_healthy: bool = True
    last_health_check: Optional[datetime] = None
    
    # Metrics
    total_requests: int = 0
    total_errors: int = 0
    p95_latency_ms: float = 0.0
    
    def add_dependency(self, dep: ServiceDependency) -> None:
        """Register outbound dependency."""
        self.dependencies[dep.target_service] = dep
    
    def add_dependent(self, service_name: str) -> None:
        """Register inbound dependent."""
        self.dependents.add(service_name)
    
    def error_rate(self) -> float:
        """Service error rate."""
        if self.total_requests == 0:
            return 0.0
        return self.total_errors / self.total_requests


class TopologyGraph:
    """
    Service topology with relationships.
    
    Enables:
    - Blast radius calculation
    - Propagation path discovery
    - Critical path analysis
    """
    
    def __init__(self):
        self.services: Dict[str, ServiceNode] = {}
        self.last_update: Optional[datetime] = None
    
    def add_service(self, service_name: str, owner: Optional[str] = None,
                   environment: str = "production") -> ServiceNode:
        """Add or update service in topology."""
        if service_name not in self.services:
            self.services[service_name] = ServiceNode(
                name=service_name,
                owner=owner,
                environment=environment,
            )
        
        node = self.services[service_name]
        if owner:
            node.owner = owner
        if environment:
            node.environment = environment
        
        self.last_update = datetime.now(timezone.utc)
        return node
    
    def add_dependency(self, source: str, target: str,
                      dep_type: DependencyType = DependencyType.UNKNOWN,
                      confidence: float = 1.0) -> ServiceDependency:
        """Register dependency edge."""
        # Ensure both services exist
        source_node = self.add_service(source)
        target_node = self.add_service(target)
        
        # Create dependency
        dep = ServiceDependency(
            source_service=source,
            target_service=target,
            dependency_type=dep_type,
            confidence=confidence,
        )
        
        source_node.add_dependency(dep)
        target_node.add_dependent(source)
        
        self.last_update = datetime.now(timezone.utc)
        return dep
    
    def get_downstream(self, service_name: str, max_depth: int = 10) -> Set[str]:
        """
        All services downstream from service.
        
        BFS from service following dependency edges.
        """
        visited = set()
        queue = [(service_name, 0)]
        
        while queue:
            current, depth = queue.pop(0)
            if current in visited or depth > max_depth:
                continue
            visited.add(current)
            
            if current not in self.services:
                continue
            
            # Add all dependencies
            for dep_name in self.services[current].dependencies.keys():
                if dep_name not in visited:
                    queue.append((dep_name, depth + 1))
        
        visited.discard(service_name)
        return visited
    
    def get_upstream(self, service_name: str, max_depth: int = 10) -> Set[str]:
        """
        All services upstream from service.
        
        BFS backwards following dependent edges.
        """
        visited = set()
        queue = [(service_name, 0)]
        
        while queue:
            current, depth = queue.pop(0)
            if current in visited or depth > max_depth:
                continue
            visited.add(current)
            
            if current not in self.services:
                continue
            
            # Add all dependents
            for dep_name in self.services[current].dependents:
                if dep_name not in visited:
                    queue.append((dep_name, depth + 1))
        
        visited.discard(service_name)
        return visited
    
    def blast_radius(self, service_name: str, immediate_only: bool = False) -> Dict[str, Any]:
        """
        Estimate blast radius if service fails.
        
        Returns:
        - immediate_impact: directly dependent services
        - transitive_impact: all reachable services
        - critical_path: services on critical path to failure propagation
        """
        if service_name not in self.services:
            return {
                "service": service_name,
                "immediate_impact": [],
                "transitive_impact": [],
                "critical_services": [],
                "estimated_affected_users": 0,
                "confidence": 0.0,
            }
        
        # Direct dependents
        direct = self.services[service_name].dependents
        
        # Transitive impact (all upstream services affected)
        transitive = self.get_upstream(service_name)
        
        # Critical path: services with <2 alternative paths
        critical = self._find_critical_path(service_name, direct)
        
        return {
            "service": service_name,
            "immediate_impact": list(direct),
            "transitive_impact": list(transitive),
            "critical_services": critical,
            "estimated_affected": len(transitive) + len(direct),
            "discovery_age_seconds": (
                (datetime.now(timezone.utc) - self.last_update).total_seconds()
                if self.last_update else None
            ),
        }
    
    def _find_critical_path(self, service: str, direct_dependents: Set[str]) -> List[str]:
        """
        Find services that are critical paths to failure propagation.
        
        Heuristic: service with no redundant path.
        """
        critical = []
        for dep in direct_dependents:
            if dep not in self.services:
                continue
            
            # Count alternative paths
            deps_list = list(self.services[dep].dependencies.keys())
            if len(deps_list) == 1:  # Only this service provides capability
                critical.append(dep)
        
        return critical
    
    def propagation_path(self, source: str, target: str) -> Optional[List[str]]:
        """
        Shortest propagation path from source to target.
        
        BFS to find path.
        """
        if source not in self.services or target not in self.services:
            return None
        
        queue = [(source, [source])]
        visited = {source}
        
        while queue:
            current, path = queue.pop(0)
            if current == target:
                return path
            
            for next_service in self.services[current].dependencies.keys():
                if next_service not in visited:
                    visited.add(next_service)
                    queue.append((next_service, path + [next_service]))
        
        return None
    
    def health_summary(self) -> Dict[str, Any]:
        """Overall topology health."""
        if not self.services:
            return {
                "services": 0,
                "healthy": 0,
                "unhealthy": 0,
                "dependencies": 0,
            }
        
        healthy = sum(1 for s in self.services.values() if s.is_healthy)
        dependencies = sum(
            len(s.dependencies) for s in self.services.values()
        )
        
        return {
            "services": len(self.services),
            "healthy": healthy,
            "unhealthy": len(self.services) - healthy,
            "dependencies": dependencies,
            "last_update_ago_sec": (
                (datetime.now(timezone.utc) - self.last_update).total_seconds()
                if self.last_update else None
            ),
        }
    
    def export_mermaid(self) -> str:
        """Export topology as Mermaid diagram."""
        lines = ["graph TD"]
        
        for service_name, node in self.services.items():
            # Service node
            style = "red" if not node.is_healthy else "green"
            lines.append(f'    {service_name}["<b>{service_name}</b><br/>{node.error_rate():.1%}"]')
        
        # Dependencies
        for service_name, node in self.services.items():
            for target, dep in node.dependencies.items():
                err_rate = dep.error_rate()
                style = "red" if err_rate > 0.05 else "black"
                lines.append(f'    {service_name} -->|{err_rate:.1%}| {target}')
        
        return "\n".join(lines)


class TopologyDiscovery:
    """
    Discover topology from multiple telemetry sources.
    
    Sources:
    - Distributed traces
    - Metrics
    - Configuration
    - Deployment events
    """
    
    def __init__(self):
        self.graph = TopologyGraph()
        self.discovery_sources = {
            "traces": 0,
            "metrics": 0,
            "config": 0,
            "deployments": 0,
        }
    
    def ingest_trace_topology(self, trace: Any) -> int:
        """
        Discover topology from distributed trace.
        
        Extract service dependencies from span relationships.
        """
        discovered = 0
        
        if not hasattr(trace, 'get_services'):
            return 0
        
        services = trace.get_services()
        for service in services:
            self.graph.add_service(service)
        
        # Extract dependencies from propagation path
        if hasattr(trace, 'propagation_path'):
            path = trace.propagation_path()
            for source, target in path:
                self.graph.add_dependency(
                    source, target,
                    DependencyType.SYNCHRONOUS_RPC,
                    confidence=0.9
                )
                discovered += 1
        
        self.discovery_sources["traces"] += discovered
        return discovered
    
    def ingest_metric_topology(self, service: str, downstream_services: List[str]) -> int:
        """
        Ingest topology hints from metrics.
        
        Low confidence (inferred from observed latency correlations).
        """
        discovered = 0
        self.graph.add_service(service)
        
        for downstream in downstream_services:
            self.graph.add_dependency(
                service, downstream,
                DependencyType.UNKNOWN,
                confidence=0.5  # Low confidence
            )
            discovered += 1
        
        self.discovery_sources["metrics"] += discovered
        return discovered
    
    def ingest_config_topology(self, service: str, config: Dict[str, Any]) -> int:
        """
        Ingest topology from explicit configuration.
        
        High confidence (manually configured).
        """
        discovered = 0
        self.graph.add_service(
            service,
            owner=config.get("owner"),
            environment=config.get("environment", "production")
        )
        
        for dep_config in config.get("dependencies", []):
            dep_service = dep_config.get("service")
            dep_type_str = dep_config.get("type", "unknown").lower()
            
            try:
                dep_type = DependencyType[dep_type_str.upper()]
            except KeyError:
                dep_type = DependencyType.UNKNOWN
            
            self.graph.add_dependency(
                service, dep_service,
                dep_type,
                confidence=1.0  # High confidence
            )
            discovered += 1
        
        self.discovery_sources["config"] += discovered
        return discovered
    
    def get_graph(self) -> TopologyGraph:
        """Get current topology graph."""
        return self.graph
    
    def stats(self) -> Dict[str, int]:
        """Discovery statistics."""
        return self.discovery_sources.copy()


# Convenience: global discovery instance
_default_discovery: Optional[TopologyDiscovery] = None


def get_topology_discovery() -> TopologyDiscovery:
    """Get or create default topology discovery."""
    global _default_discovery
    if _default_discovery is None:
        _default_discovery = TopologyDiscovery()
    return _default_discovery
