"""
Unified Orchestration Engine.

Replaces the bifurcated repo-analyzer + demo-pipeline split.

Single 11-step pipeline:
  1.  ingest_signals          → NormalizedSignal[]
  2.  cluster_root_causes      → incident clusters
  3.  enrich_github_context    → commits, PRs, languages
  4.  classify_repository      → repo_type
  5.  analyze_topology         → service map
  6.  run_signal_fusion        → convergence score
  7.  compute_regression_risk  → regression signal
  8.  analyze_temporal_memory  → recurring patterns
  9.  suppress_noise           → filtered clusters
  10. generate_ai_synthesis    → operational brief (Groq)
  11. emit_result              → finalize run state

All progress is emitted via progress_callback(step_name, payload) for
real-time SSE streaming to the frontend.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import concurrent.futures
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


ProgressFn = Callable[[str, Dict[str, Any]], None]


class UnifiedOrchestrator:
    """
    Single entry-point for all DevANT operational intelligence.

    Usage (from background task in main.py)::

        orch = UnifiedOrchestrator()
        result = orch.run(
            repo_url="https://github.com/owner/repo",
            run_id=run_id,
            progress_callback=callback,
        )
    """

    def __init__(self):
        self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=4)

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------

    def run(
        self,
        repo_url: str,
        run_id: str,
        progress_callback: ProgressFn,
        local_path: Optional[str] = None,
        window_minutes: int = 30,
    ) -> Dict[str, Any]:
        """
        Execute the full unified pipeline synchronously.

        Returns a result dict compatible with finalize_run().
        Raises on unrecoverable errors (Groq not configured, etc.).
        """

        def emit(step: str, payload: Dict[str, Any]):
            try:
                progress_callback(step, payload)
            except Exception as e:
                logger.warning(f"[{run_id}] Progress callback error at {step}: {e}")

        # ----------------------------------------------------------------
        # Step 1 — Ingest signals
        # ----------------------------------------------------------------
        emit("started", {"status": "ingesting_signals"})
        signals = self._step_ingest(emit, window_minutes)

        # ----------------------------------------------------------------
        # Step 2 — Cluster root causes
        # ----------------------------------------------------------------
        emit("ingesting_errors", {"signal_count": len(signals)})
        clusters = self._step_cluster(signals, emit)

        # ----------------------------------------------------------------
        # Step 3 — GitHub context enrichment
        # ----------------------------------------------------------------
        emit("enriching_context", {"cluster_count": len(clusters)})
        github_ctx = self._step_github_context(repo_url, emit)

        # ----------------------------------------------------------------
        # Step 4 — Classify repository
        # ----------------------------------------------------------------
        repo_classification = self._step_classify_repo(
            {}, github_ctx, emit   # evidence built later during topology step
        )
        emit("repository_classified", {
            "repo_type": repo_classification["repo_type"],
            "confidence": repo_classification["confidence"],
        })

        # ----------------------------------------------------------------
        # Step 5 — Analyze topology (repo scan)
        # ----------------------------------------------------------------
        emit("scanning_repository", {"repo_url": repo_url})
        evidence, topology = self._step_topology(repo_url, local_path, emit)

        # Re-classify with real evidence
        repo_classification = self._step_classify_repo(
            evidence,
            github_ctx,
            emit,
        )

        # ----------------------------------------------------------------
        # Step 6 — Signal fusion
        # ----------------------------------------------------------------
        emit("assessing_health", {})
        fusion_result = self._step_signal_fusion(evidence, topology, clusters)

        # ----------------------------------------------------------------
        # Step 7 — Regression risk
        # ----------------------------------------------------------------
        scores = self._step_operational_scoring(evidence, topology)
        emit("scored", {"scores": scores})

        # ----------------------------------------------------------------
        # Step 8 — Temporal memory
        # ----------------------------------------------------------------
        temporal = self._step_temporal_memory(
            run_id, repo_url, topology, scores, emit
        )

        # ----------------------------------------------------------------
        # Step 9 — Suppression
        # ----------------------------------------------------------------
        from pipeline.suppression_engine import SuppressionEngine
        active_clusters = SuppressionEngine().filter(clusters)
        emit("live_errors_ingested", {
            "raw_errors": len(signals),
            "clusters": active_clusters,
        })

        # ----------------------------------------------------------------
        # Step 10 — AI Synthesis
        # ----------------------------------------------------------------
        emit("generating_brief", {"active_clusters": len(active_clusters)})
        propagation = self._step_propagation(topology)
        synthesis = self._step_synthesis(
            evidence=evidence,
            topology=topology,
            scores=scores,
            propagation=propagation,
            repo_type=repo_classification["repo_type"],
            github_context=github_ctx,
            live_error_clusters=active_clusters,
            temporal_memory=temporal,
            signal_fusion=fusion_result,
            emit=emit,
        )

        # ----------------------------------------------------------------
        # Step 11 — Build & return result
        # ----------------------------------------------------------------
        result = {
            "scanned": True,
            "error": None,
            "evidence": {
                **evidence,
                "live_errors": active_clusters,
                "repo_classification": repo_classification,
            },
            "topology": topology,
            "scores": scores,
            "synthesis": synthesis,
            "propagation": propagation,
            "temporal_memory": temporal,
            "github_context": github_ctx,
            "signal_fusion": fusion_result,
            "run_id": run_id,
            "repo_url": repo_url,
            "completed_at": datetime.utcnow().isoformat(),
        }

        emit("completed", {"run_id": run_id})
        return result

    # ------------------------------------------------------------------
    # Step implementations
    # ------------------------------------------------------------------

    def _step_ingest(
        self, emit: ProgressFn, window_minutes: int
    ) -> List[Any]:
        from ingestion.unified_ingestor import UnifiedIngestor
        try:
            ingestor = UnifiedIngestor()
            signals = ingestor.ingest(window_minutes=window_minutes, limit=200)
            logger.info(f"Ingested {len(signals)} signals")
            return signals
        except Exception as exc:
            logger.error(f"Signal ingestion failed: {exc}")
            emit("ingestion_warning", {"warning": str(exc)})
            return []

    def _step_cluster(
        self, signals: List[Any], emit: ProgressFn
    ) -> List[Dict[str, Any]]:
        """Cluster normalized signals into root-cause incidents."""
        if not signals:
            return []

        # Convert NormalizedSignal → raw dict for ErrorClusterer
        raw_errors = []
        for sig in signals:
            payload = sig.payload if hasattr(sig, "payload") else {}
            raw_errors.append({
                "message": sig.title if hasattr(sig, "title") else str(sig),
                "level": (sig.severity if hasattr(sig, "severity") else "error").upper(),
                "module": sig.service if hasattr(sig, "service") else "unknown",
                "function": payload.get("function", ""),
                "org_name": sig.org_name if hasattr(sig, "org_name") else "",
                "org_id": sig.org_id if hasattr(sig, "org_id") else "",
                "container": payload.get("container", ""),
                "source": sig.source if hasattr(sig, "source") else "unknown",
                **{k: v for k, v in payload.items() if k not in ("message",)},
            })

        try:
            from pipeline.clustering import ErrorClusterer
            clusterer = ErrorClusterer()

            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            clusters = loop.run_until_complete(clusterer.cluster_errors(raw_errors))
            loop.close()

            logger.info(f"Clustering: {len(raw_errors)} signals → {len(clusters)} clusters")
            return clusters
        except Exception as exc:
            logger.error(f"Clustering failed: {exc}")
            emit("clustering_warning", {"warning": str(exc)})
            return []

    def _step_github_context(
        self, repo_url: str, emit: ProgressFn
    ) -> Dict[str, Any]:
        """Fetch GitHub enrichment (commits, PRs, languages, metadata)."""
        from connectors.github_connector import GitHubConnector

        connector = GitHubConnector()
        if not connector.is_configured:
            logger.info("GitHub token not set — skipping GitHub enrichment")
            return {"available": False}

        try:
            commits = connector.get_recent_commits(repo_url, since_hours=48, max_commits=15)
            prs = connector.get_recent_prs(repo_url, since_hours=72, max_prs=8)
            languages = connector.get_repo_languages(repo_url)
            metadata = connector.get_repo_metadata(repo_url)

            primary_language = max(languages, key=lambda k: languages[k]) if languages else ""

            ctx = {
                "available": True,
                "commits": commits,
                "prs": prs,
                "languages": languages,
                "primary_language": primary_language,
                "metadata": metadata,
                "topics": metadata.get("topics", []),
                "description": metadata.get("description", ""),
            }
            emit("github_enriched", {
                "commits": len(commits),
                "prs": len(prs),
                "primary_language": primary_language,
            })
            return ctx
        except Exception as exc:
            logger.warning(f"GitHub enrichment failed: {exc}")
            return {"available": False, "error": str(exc)}

    def _step_classify_repo(
        self,
        evidence: Dict[str, Any],
        github_ctx: Dict[str, Any],
        emit: ProgressFn,
    ) -> Dict[str, Any]:
        from pipeline.repository_classifier import RepositoryClassifier
        try:
            clf = RepositoryClassifier()
            return clf.classify(
                evidence=evidence,
                github_languages=github_ctx.get("languages"),
                github_topics=github_ctx.get("topics"),
                github_description=github_ctx.get("description", ""),
            )
        except Exception as exc:
            logger.warning(f"Repo classification failed: {exc}")
            return {"repo_type": "unknown", "confidence": 0.0, "signals": []}

    def _step_topology(
        self,
        repo_url: str,
        local_path: Optional[str],
        emit: ProgressFn,
    ) -> tuple[Dict[str, Any], Dict[str, Any]]:
        """Run the repository file-system scan and topology extraction."""
        # Delegate to existing repo_analyzer logic but extract just the
        # evidence + topology rather than running synthesis (we do that here).
        from pathlib import Path
        import os

        path = None
        if local_path:
            path = Path(local_path)
        elif os.path.exists(repo_url.replace("file://", "")):
            path = Path(repo_url.replace("file://", ""))

        evidence: Dict[str, Any] = {
            "workflows": [],
            "dockerfiles": [],
            "kubernetes_manifests": [],
            "helm_charts": [],
            "terraform": [],
            "prometheus": False,
            "otel": False,
            "services": [],
            "package_managers": [],
            "files_present": [],
        }

        if path and path.exists():
            # Local scan
            try:
                from repository.evidence_engine import EvidenceEngine
                eng = EvidenceEngine()
                local_evidence = eng.scan(path)
                evidence.update(local_evidence)
                emit("scanned_files", {
                    "workflows": len(evidence.get("workflows", [])),
                    "dockerfiles": len(evidence.get("dockerfiles", [])),
                })
            except Exception as exc:
                logger.warning(f"Local evidence scan failed: {exc}")

            try:
                from repository.topology_extractor import TopologyExtractor
                topology = TopologyExtractor().extract_from_local_path(path)
                emit("topology", {"topology": topology, "concurrent": True})
            except Exception as exc:
                logger.warning(f"Topology extraction failed: {exc}")
                topology = {"services": [], "edges": []}

        elif repo_url.startswith("https://github.com"):
            # Remote GitHub scan via API
            try:
                from repository.github_ingestor import GitHubIngestor
                gh = GitHubIngestor()
                sample = gh.sample_operational_files(repo_url, max_paths=200)
                evidence.update(sample)
                emit("github_sample", {
                    "sample_counts": {
                        k: (len(v) if isinstance(v, list) else int(bool(v)))
                        for k, v in sample.items()
                    }
                })
            except Exception as exc:
                logger.warning(f"GitHub API scan failed: {exc}")

            topology = {"services": [], "edges": []}
            emit("topology", {"topology": topology})
        else:
            topology = {"services": [], "edges": []}
            emit("topology", {"topology": topology})

        emit("workflows_extracted", {
            "workflow_count": len(evidence.get("workflows", [])),
        })
        emit("deployments_correlated", {
            "dockerfiles": len(evidence.get("dockerfiles", [])),
            "kubernetes_manifests": len(evidence.get("kubernetes_manifests", [])),
            "helm_charts": len(evidence.get("helm_charts", [])),
            "terraform": len(evidence.get("terraform", [])),
        })
        emit("observability_checked", {
            "prometheus": evidence.get("prometheus", False),
            "otel": evidence.get("otel", False),
        })

        return evidence, topology

    def _step_signal_fusion(
        self,
        evidence: Dict[str, Any],
        topology: Dict[str, Any],
        clusters: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        try:
            from core.signal_fusion import SignalFusionEngine, SignalType
            fusion = SignalFusionEngine()

            # Workflow presence → regression similarity signal
            wf_count = len(evidence.get("workflows", []))
            fusion.add_signal(
                SignalType.REGRESSION_SIMILARITY,
                strength=min(1.0, wf_count / 3),
                evidence_source="workflows",
            )
            # Topology edges → propagation alignment
            edge_count = len(topology.get("edges", []))
            fusion.add_signal(
                SignalType.PROPAGATION_ALIGNMENT,
                strength=min(1.0, edge_count / 5),
                evidence_source="topology",
            )
            # Observability signals
            obs_strength = (
                (0.5 if evidence.get("prometheus") else 0.0)
                + (0.5 if evidence.get("otel") else 0.0)
            )
            fusion.add_signal(
                SignalType.TELEMETRY_CONVERGENCE,
                strength=obs_strength,
                evidence_source="observability",
            )
            # Live errors → historical recurrence signal
            fusion.add_signal(
                SignalType.HISTORICAL_RECURRENCE,
                strength=min(1.0, len(clusters) / 5) if clusters else 0.0,
                evidence_source="live_errors",
            )

            return fusion.fuse()
        except Exception as exc:
            logger.warning(f"Signal fusion failed: {exc}")
            return {"confidence": 0.3, "sparse_evidence": True, "conflict_count": 0}

    def _step_operational_scoring(
        self,
        evidence: Dict[str, Any],
        topology: Dict[str, Any],
    ) -> Dict[str, Any]:
        try:
            from repository.operational_scoring import OperationalScoringEngine
            scorer = OperationalScoringEngine()
            return scorer.score(evidence, topology)
        except Exception as exc:
            logger.warning(f"Operational scoring failed: {exc}")
            # Return zero scores so synthesis reflects sparse evidence
            return {
                "production_readiness": 0.0,
                "deployment_maturity": 0.0,
                "observability_readiness": 0.0,
                "rollback_safety": 0.0,
                "topology_resilience": 0.0,
                "regression_risk": 0.0,
            }

    def _step_propagation(self, topology: Dict[str, Any]) -> Dict[str, Any]:
        try:
            from core.topology_propagation import TopologyPropagationEngine
            engine = TopologyPropagationEngine()
            result = engine.analyze(topology_graph=topology)
            return {
                "blast_radius": result.blast_radius,
                "critical_paths": result.critical_paths,
                "dominant_service": result.dominant_service,
                "upstream_risk": result.upstream_risk,
            }
        except Exception as exc:
            logger.warning(f"Propagation analysis failed: {exc}")
            return {}

    def _step_temporal_memory(
        self,
        run_id: str,
        repo_url: str,
        topology: Dict[str, Any],
        scores: Dict[str, Any],
        emit: ProgressFn,
    ) -> Dict[str, Any]:
        try:
            from memory.incident_graph import get_incident_graph, IncidentNode

            graph = get_incident_graph()

            topo_hash = hashlib.md5(
                str(sorted(e.get("from", "") + e.get("to", "")
                           for e in topology.get("edges", []))).encode()
            ).hexdigest()[:8]

            dominant = (
                topology.get("services", [{}])[0].get("name", "unknown")
                if topology.get("services")
                else "unknown"
            )

            node = graph.add_incident(
                incident_id=run_id,
                timestamp=datetime.utcnow().isoformat(),
                repo=repo_url,
                dominant_service=dominant,
                blast_radius=len(topology.get("services", [])),
                operational_confidence=scores.get("production_readiness", 0.0),
                regression_risk=scores.get("regression_risk", 0.0),
                topology_hash=topo_hash,
            )

            patterns = graph.detect_recurring_patterns(node)
            drift = graph.analyze_operational_drift(repo_url)

            emit("temporal_analyzed", {
                "is_recurring": patterns.get("is_recurring", False),
                "recurrence_count": patterns.get("recurrence_count", 0),
            })

            return {**patterns, **drift}
        except Exception as exc:
            logger.warning(f"Temporal memory failed: {exc}")
            return {}

    def _step_synthesis(
        self,
        evidence: Dict[str, Any],
        topology: Dict[str, Any],
        scores: Dict[str, Any],
        propagation: Dict[str, Any],
        repo_type: str,
        github_context: Dict[str, Any],
        live_error_clusters: List[Dict[str, Any]],
        temporal_memory: Dict[str, Any],
        signal_fusion: Dict[str, Any],
        emit: ProgressFn,
    ) -> Dict[str, Any]:
        from pipeline.synthesis_engine import SynthesisEngine
        try:
            engine = SynthesisEngine()
            result = engine.synthesize(
                evidence=evidence,
                topology=topology,
                scores=scores,
                propagation=propagation,
                repo_type=repo_type,
                github_context=github_context,
                live_error_clusters=live_error_clusters,
                temporal_memory=temporal_memory,
                signal_fusion=signal_fusion,
            )
            emit("synthesis_complete", {
                "health_state": result.get("health_state"),
                "severity": result.get("severity"),
            })
            return result
        except Exception as exc:
            # Fail loud — do not produce fake summaries
            logger.error(f"AI synthesis failed: {exc}")
            emit("error", {"error": str(exc), "step": "synthesis"})
            raise RuntimeError(f"AI Synthesis failed: {exc}") from exc
