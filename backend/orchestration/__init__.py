"""Orchestration layer: coordinates multi-phase pipelines (OTLP → embedding → clustering → analysis)."""
from .otlp_clustering_orchestrator import (
    OTLPClusteringOrchestrator,
    get_otlp_clustering_orchestrator,
)

# Scheduler module is optional in some deployments/worktrees.
try:
    from .cluster_scheduler import (
        get_cluster_scheduler,
        start_scheduler,
        stop_scheduler,
    )
except Exception:  # pragma: no cover - optional runtime dependency
    get_cluster_scheduler = None
    start_scheduler = None
    stop_scheduler = None

__all__ = [
    "OTLPClusteringOrchestrator",
    "get_otlp_clustering_orchestrator",
]

if get_cluster_scheduler is not None:
    __all__.extend([
        "get_cluster_scheduler",
        "start_scheduler",
        "stop_scheduler",
    ])
