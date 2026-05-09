"""
Lightweight repository analyzer focused on operational metadata extraction.
- Designed for local-path scans (fast filesystem checks)
- For remote GitHub URLs, returns pending requiring local path or allowlist for clone
- Emits progress via progress_callback(step_name, partial_result)
- Uses concurrent extraction for improved throughput
"""
from typing import Callable, Dict, Any, List, Optional
import os
import json
from pathlib import Path
import logging
from datetime import datetime
import asyncio
import concurrent.futures
from .topology_extractor import TopologyExtractor
from .operational_scoring import OperationalScoringEngine
from .github_ingestor import GitHubIngestor
from .evidence_engine import EvidenceEngine
from .analysis_state import transition_run, finalize_run, fail_run, get_run_snapshot, set_partial_update
from samples import get_sample_errors
from pipeline import ErrorClusterer

# Import SignalFusionEngine + TopologyPropagationEngine - sys.path must include backend dir
import sys
_backend_dir = str(Path(__file__).parent.parent)
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

from core.signal_fusion import SignalFusionEngine, SignalType
from core.topology_propagation import TopologyPropagationEngine
from memory.incident_graph import IncidentGraph, IncidentNode
import hashlib

logger = logging.getLogger(__name__)
_incident_graph = IncidentGraph()  # Persistent temporal memory


def _read_file_safe(path: Path, max_bytes: int = 16_384) -> str:
    try:
        with path.open('rb') as f:
            data = f.read(max_bytes)
            return data.decode(errors='replace')
    except Exception:
        return ''


# Concurrent extraction tasks for parallel repository scanning
async def _extract_workflows_async(path: Path, max_entries: int = 10000) -> Dict[str, Any]:
    """Extract GitHub workflows concurrently."""
    result = {'workflows': [], 'extracted_count': 0}
    entries_seen = 0
    loop = asyncio.get_event_loop()
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=2)
    
    try:
        for root, dirs, files in os.walk(path):
            entries_seen += len(files) + len(dirs)
            if entries_seen > max_entries:
                break
            
            for f in files:
                if f.lower().endswith(('.yml', '.yaml')):
                    relroot = os.path.relpath(root, path)
                    if '.github/workflows' in os.path.join(relroot, f).replace('\\', '/'):
                        fp = Path(root) / f
                        # Read file in thread pool
                        content = await loop.run_in_executor(executor, lambda p=fp: _read_file_safe(p))
                        result['workflows'].append({
                            'path': os.path.join(relroot, f),
                            'content_preview': content[:1024]
                        })
                        result['extracted_count'] += 1
    finally:
        executor.shutdown(wait=False)
    
    return result


async def _extract_deployments_async(path: Path, max_entries: int = 10000) -> Dict[str, Any]:
    """Extract deployment artifacts (Dockerfile, K8s, Helm, Terraform) concurrently."""
    result = {
        'dockerfiles': [],
        'kubernetes_manifests': [],
        'helm_charts': [],
        'terraform': [],
        'extracted_count': 0
    }
    entries_seen = 0
    loop = asyncio.get_event_loop()
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=3)
    
    try:
        for root, dirs, files in os.walk(path):
            entries_seen += len(files) + len(dirs)
            if entries_seen > max_entries:
                break
            
            relroot = os.path.relpath(root, path)
            for f in files:
                nf = f.lower()
                relf = os.path.join(relroot, f)
                fp = Path(root) / f
                
                # Dockerfile detection
                if nf == 'dockerfile' or nf.startswith('dockerfile.') or f.endswith('.dockerfile'):
                    result['dockerfiles'].append(relf)
                    result['extracted_count'] += 1
                
                # Helm charts
                if nf == 'chart.yaml' or nf == 'chart.yml':
                    result['helm_charts'].append(relf)
                    result['extracted_count'] += 1
                
                # Terraform
                if nf.endswith('.tf'):
                    result['terraform'].append(relf)
                    result['extracted_count'] += 1
                
                # Kubernetes manifests (needs file read)
                if nf.endswith(('.yaml', '.yml')):
                    content = await loop.run_in_executor(executor, lambda p=fp: _read_file_safe(p))
                    lc = content.lower()
                    if 'kind: deployment' in lc or 'kind: service' in lc or 'apiVersion:' in content:
                        result['kubernetes_manifests'].append({
                            'path': relf,
                            'preview': content[:1024]
                        })
                        result['extracted_count'] += 1
    finally:
        executor.shutdown(wait=False)
    
    return result


async def _extract_observability_async(path: Path, max_entries: int = 10000) -> Dict[str, Any]:
    """Extract observability configuration (Prometheus, OTEL) concurrently."""
    result = {
        'prometheus': False,
        'otel': False,
        'extracted_count': 0
    }
    entries_seen = 0
    
    for root, dirs, files in os.walk(path):
        entries_seen += len(files) + len(dirs)
        if entries_seen > max_entries:
            break
        
        for f in files:
            nf = f.lower()
            if 'prometheus' in nf or nf == 'prometheus.yml':
                result['prometheus'] = True
                result['extracted_count'] += 1
            if 'otel' in nf or 'opentelemetry' in nf or 'collector' in nf:
                result['otel'] = True
                result['extracted_count'] += 1
    
    return result


async def _extract_package_managers_async(path: Path, max_entries: int = 10000) -> Dict[str, Any]:
    """Extract package manager files and detect services concurrently."""
    result = {
        'package_managers': [],
        'services': [],
        'extracted_count': 0
    }
    entries_seen = 0
    
    pm_markers = ('package.json', 'pyproject.toml', 'requirements.txt', 'setup.py', 'go.mod', 'Gemfile')
    
    for root, dirs, files in os.walk(path):
        entries_seen += len(files) + len(dirs)
        if entries_seen > max_entries:
            break
        
        relroot = os.path.relpath(root, path)
        for f in files:
            nf = f.lower()
            relf = os.path.join(relroot, f)
            
            if nf in pm_markers:
                result['package_managers'].append(relf)
                result['extracted_count'] += 1
                
                # Mark service directory
                if nf in ('package.json', 'requirements.txt', 'pyproject.toml', 'go.mod', 'Gemfile'):
                    service_dir = relroot if relroot != '.' else '/'
                    result['services'].append({'path': service_dir, 'marker': nf})
    
    return result


async def _extract_topology_async(path: Path) -> Dict[str, Any]:
    """Extract topology concurrently."""
    loop = asyncio.get_event_loop()
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    
    try:
        extractor = TopologyExtractor()
        topology = await loop.run_in_executor(executor, lambda: extractor.extract_from_local_path(path))
        return {'topology': topology, 'extracted_count': 1}
    finally:
        executor.shutdown(wait=False)


async def _concurrent_extraction(path: Path) -> Dict[str, Any]:
    """Run all extraction tasks concurrently and merge results."""
    # Launch all extraction tasks in parallel
    tasks = [
        _extract_workflows_async(path),
        _extract_deployments_async(path),
        _extract_observability_async(path),
        _extract_package_managers_async(path),
        _extract_topology_async(path),
    ]
    
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    # Merge results into unified evidence
    merged = {
        'files_present': [],
        'workflows': [],
        'dockerfiles': [],
        'kubernetes_manifests': [],
        'helm_charts': [],
        'terraform': [],
        'prometheus': False,
        'otel': False,
        'package_managers': [],
        'services': [],
        'topology': {'services': [], 'edges': []},
        'extraction_tasks': {
            'workflows': results[0] if not isinstance(results[0], Exception) else None,
            'deployments': results[1] if not isinstance(results[1], Exception) else None,
            'observability': results[2] if not isinstance(results[2], Exception) else None,
            'package_managers': results[3] if not isinstance(results[3], Exception) else None,
            'topology': results[4] if not isinstance(results[4], Exception) else None,
        }
    }
    
    # Consolidate results from each extraction task
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            logger.warning(f"Extraction task {i} failed: {result}")
            continue
        
        if i == 0 and result:  # workflows
            merged['workflows'].extend(result.get('workflows', []))
        elif i == 1 and result:  # deployments
            merged['dockerfiles'].extend(result.get('dockerfiles', []))
            merged['kubernetes_manifests'].extend(result.get('kubernetes_manifests', []))
            merged['helm_charts'].extend(result.get('helm_charts', []))
            merged['terraform'].extend(result.get('terraform', []))
        elif i == 2 and result:  # observability
            merged['prometheus'] = merged['prometheus'] or result.get('prometheus', False)
            merged['otel'] = merged['otel'] or result.get('otel', False)
        elif i == 3 and result:  # package managers
            merged['package_managers'].extend(result.get('package_managers', []))
            merged['services'].extend(result.get('services', []))
        elif i == 4 and result:  # topology
            merged['topology'] = result.get('topology', {'services': [], 'edges': []})
    
    return merged


def analyze_repository(repo_url: str, local_path: Optional[str] = None, progress_callback: Optional[Callable[[str, Dict[str, Any]], None]] = None, run_id: Optional[str] = None, include_live_errors: bool = True) -> Dict[str, Any]:
    """Analyze repository for operational metadata.

    Args:
        repo_url: user-provided repo URL (https or local path)
        local_path: optional explicit local path to analyze (preferred)
        progress_callback: optional callback(step_name, partial_result) used to stream progress
        run_id: Analysis run identifier
        include_live_errors: Whether to ingest live operational errors

    Returns:
        result dict with evidence and flags
    """
    result: Dict[str, Any] = {
        'repo_url': repo_url,
        'scanned': False,
        'error': None,
        'evidence': {},
        'topology': {},
        'scores': {},
    }

    # monotonic sequence counter for emitted stage events
    seq_counter = 0

    def _workflow_path(item: Any) -> str:
        if isinstance(item, dict):
            return item.get('path', '')
        if isinstance(item, str):
            try:
                parsed = json.loads(item)
                if isinstance(parsed, dict):
                    return parsed.get('path', '')
            except Exception:
                return item
        return str(item)

    def progress(step: str, payload: Dict[str, Any]):
        nonlocal seq_counter
        seq_counter += 1
        ts = datetime.utcnow().isoformat()
        # canonical stage mapping
        step_to_stage = {
            'started': 'repository_ingestion',
            'github_ingest_started': 'repository_ingestion',
            'github_sample': 'repository_ingestion',
            'scanned_files': 'repository_ingestion',
            'workflows_extracted': 'workflow_discovery',
            'deployments_correlated': 'deployment_analysis',
            'observability_checked': 'observability_analysis',
            'topology': 'topology_inference',
            'regression_checked': 'regression_risk_analysis',
            'scored': 'operational_scoring',
            'confidence_calibrated': 'confidence_calibration',
            'completed': 'final_operational_synthesis',
            'error': 'final_operational_synthesis',
        }
        stage_id = step_to_stage.get(step, step)

        # derive event kind and status
        if step in ('started', 'github_ingest_started'):
            event_kind = 'stage_started'
            status = 'running'
        elif step in ('github_sample', 'scanned_files', 'topology', 'scored'):
            event_kind = 'stage_progress'
            status = 'partial'
        elif step == 'completed':
            event_kind = 'stage_completed'
            status = 'completed'
        elif step == 'error':
            event_kind = 'stage_failed'
            status = 'failed'
        else:
            event_kind = 'stage_progress'
            status = 'partial'

        event_payload = {
            'seq': seq_counter,
            'event': event_kind,
            'stage': stage_id,
            'status': status,
            'evidence': payload,
            'confidence': payload.get('confidence') if isinstance(payload, dict) else None,
            'timestamp': ts,
            'partial_result': payload,
        }

        # cancellation safety: no processing after cancel
        if run_id:
            snap = get_run_snapshot(run_id)
            if snap.get('state') == 'CANCELLED':
                raise RuntimeError('cancelled')

        if progress_callback:
            try:
                # emit generic progress callback for legacy handlers
                progress_callback(step, payload)
                # also emit canonical stage event when available
                try:
                    progress_callback('stage_event', event_payload)
                except Exception:
                    pass
            except Exception:
                logger.exception('progress callback failed')
        if run_id:
            try:
                # store canonical partial by stage id for frontend consumption
                set_partial_update(run_id, stage_id, {
                    'state': status.upper() if isinstance(status, str) else status,
                    'progress': payload.get('progress') if isinstance(payload, dict) and 'progress' in payload else None,
                    'evidence': payload.get('evidence') if isinstance(payload, dict) and 'evidence' in payload else payload,
                    'confidence': payload.get('confidence') if isinstance(payload, dict) else None,
                    'last_event': event_payload,
                })
            except Exception:
                pass
        # also update run state transitions for deterministic lifecycle
        if run_id:
            try:
                if step == 'started':
                    transition_run(run_id, 'INITIALIZING')
                elif step == 'github_sample' or step == 'scanned_files':
                    transition_run(run_id, 'INGESTING')
                elif step == 'topology':
                    transition_run(run_id, 'ANALYZING')
                elif step == 'scored':
                    transition_run(run_id, 'SCORING')
                elif step == 'completed':
                    transition_run(run_id, 'FINALIZING')
            except Exception:
                # avoid raising from progress reporting
                pass

    # Determine local path to scan
    path = None
    if local_path:
        path = Path(local_path)
    else:
        # If repo_url looks like local path
        if repo_url.startswith('file://'):
            path = Path(repo_url[len('file://'):])
        elif os.path.exists(repo_url):
            path = Path(repo_url)

    # If remote GitHub URL, perform metadata-first ingestion via API
    if path is None and repo_url.startswith('https://github.com'):
        # Use GitHubIngestor to sample operational files
        gh = GitHubIngestor()
        try:
            progress('started', {'status': 'github_ingest_started'})
            sample = gh.sample_operational_files(repo_url, max_paths=200)
            evidence = {
                'files_present': [],
                'workflows': [],
                'dockerfiles': [],
                'kubernetes_manifests': [],
                'helm_charts': [],
                'terraform': [],
                'prometheus': False,
                'otel': False,
                'package_managers': [],
                'services': [],
            }
            evidence.update(sample)
            progress('github_sample', {'sample_counts': {k: (len(v) if isinstance(v, list) else int(bool(v))) for k, v in sample.items()}})
            progress('workflows_extracted', {
                'workflow_count': len(evidence.get('workflows', [])),
                'workflows': [_workflow_path(w) for w in evidence.get('workflows', [])[:5]],
            })
            progress('deployments_correlated', {
                'dockerfiles': len(evidence.get('dockerfiles', [])),
                'kubernetes_manifests': len(evidence.get('kubernetes_manifests', [])),
                'helm_charts': len(evidence.get('helm_charts', [])),
                'terraform': len(evidence.get('terraform', [])),
            })
            progress('observability_checked', {
                'prometheus': evidence.get('prometheus', False),
                'otel': evidence.get('otel', False),
            })
            
            if include_live_errors:
                try:
                    gh_loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(gh_loop)
                    errors = get_sample_errors(include_extended=True)
                    clusterer = ErrorClusterer()
                    clusters = gh_loop.run_until_complete(clusterer.cluster_errors(errors))
                    gh_loop.close()
                    evidence['live_errors'] = clusters
                    progress('live_errors_ingested', {
                        'raw_errors': len(errors),
                        'clusters': clusters
                    })
                except Exception as e:
                    logger.error(f"Live error ingestion failed in GH flow: {e}")
                    evidence['live_errors'] = []

            # Build topology from sampled manifests minimal
            topology = TopologyExtractor().extract_from_local_path(path) if path else {'services': [], 'edges': []}
            
            # Emit topology progress event (triggers ANALYZING state transition)
            progress('topology', {'topology': topology, 'concurrent': True})
            
            # Topology propagation analysis
            propagation_engine = TopologyPropagationEngine()
            propagation_result = propagation_engine.analyze(topology_graph=topology)
            evidence['propagation'] = {
                'blast_radius': propagation_result.blast_radius,
                'critical_paths': propagation_result.critical_paths,
                'dominant_service': propagation_result.dominant_service,
                'upstream_risk': propagation_result.upstream_risk,
                'downstream_risk': propagation_result.downstream_risk,
                'service_count': propagation_result.service_count,
                'edge_count': propagation_result.edge_count,
                'propagation_depth': propagation_result.propagation_depth,
                'high_risk_dependencies': propagation_result.high_risk_dependencies,
            }
            progress('topology_propagation', {
                'blast_radius': propagation_result.blast_radius,
                'dominant_service': propagation_result.dominant_service,
                'critical_paths_count': len(propagation_result.critical_paths),
                'upstream_risk': propagation_result.upstream_risk,
                'downstream_risk': propagation_result.downstream_risk,
                'service_count': propagation_result.service_count,
                'edge_count': propagation_result.edge_count,
            })
            
            # Evidence engine deeper evaluation
            ee = EvidenceEngine()
            evidence_scores = ee.evaluate(evidence, topology)
            scoring_engine = OperationalScoringEngine()
            scores = scoring_engine.score_from_evidence(evidence, topology)
            
            # Signal fusion: integrate multi-signal reasoning into confidence
            fusion_engine = SignalFusionEngine()
            
            # Map evidence scores to operational signals
            deployment_conf = evidence_scores.get('deployment_confidence', 0.0)
            observability_conf = evidence_scores.get('observability_confidence', 0.0)
            topology_conf = evidence_scores.get('topology_confidence', 0.0)
            
            # Add signals to fusion engine
            if deployment_conf > 0:
                fusion_engine.add_signal(
                    SignalType.TEMPORAL_CORRELATION,
                    deployment_conf,
                    "deployment_evidence",
                    uncertainty=0.1 if deployment_conf < 0.7 else 0.05
                )
            
            if observability_conf > 0:
                fusion_engine.add_signal(
                    SignalType.TELEMETRY_CONVERGENCE,
                    observability_conf,
                    "observability_evidence",
                    uncertainty=0.1 if observability_conf < 0.7 else 0.05
                )
            
            if topology_conf > 0:
                fusion_engine.add_signal(
                    SignalType.TOPOLOGY_CONSISTENCY,
                    topology_conf,
                    "topology_evidence",
                    uncertainty=0.15 if topology_conf < 0.6 else 0.08
                )
            
            # Derive regression similarity from risk assessment
            regression_risk = scores.get('regression_risk', 0.5)
            regression_similarity = 1.0 - min(1.0, regression_risk)
            if regression_similarity > 0:
                fusion_engine.add_signal(
                    SignalType.REGRESSION_SIMILARITY,
                    regression_similarity,
                    "regression_analysis",
                    uncertainty=0.15
                )
            
            # Add workflow signal (deployment resilience)
            workflow_count = len(evidence.get('workflows', []))
            workflow_strength = min(1.0, workflow_count / 3.0)
            if workflow_strength > 0:
                fusion_engine.add_signal(
                    SignalType.PROPAGATION_ALIGNMENT,
                    workflow_strength,
                    "workflow_evidence",
                    uncertainty=0.1 if workflow_strength < 0.5 else 0.05
                )
            
            # Add repository health signal
            repo_health = min(
                1.0,
                (len(evidence.get('dockerfiles', [])) * 0.2 +
                 len(evidence.get('kubernetes_manifests', [])) * 0.2 +
                 len(evidence.get('helm_charts', [])) * 0.1 +
                 len(evidence.get('terraform', [])) * 0.1) / 4.0 + (
                 1.0 if evidence.get('prometheus') else 0.0) * 0.2 +
                (1.0 if evidence.get('otel') else 0.0) * 0.2
            )
            if repo_health > 0:
                fusion_engine.add_signal(
                    SignalType.ANOMALY_ALIGNMENT,
                    repo_health,
                    "repository_health",
                    uncertainty=0.12
                )
            
            # Fuse signals into calibrated confidence
            fusion_result = fusion_engine.fuse()
            
            # Update scores with fused confidence
            scores['operational_confidence'] = fusion_result['confidence']
            scores['signal_consensus'] = fusion_result['convergence_score']
            scores['uncertainty'] = fusion_result['uncertainty']
            scores['fusion_signal_count'] = fusion_result['signal_count']
            scores['fusion_sparse_evidence'] = fusion_result['sparse_evidence']
            
            regression_signals = {
                'observability_gap': not observability_conf,
                'topology_confidence': topology_conf,
                'deployment_confidence': deployment_conf,
                'signal_consensus': fusion_result['convergence_score'],
                'dominant_signals': [s.value for s in fusion_result.get('dominant_signals', [])],
            }
            progress('regression_checked', {
                'risk_score': scores.get('regression_risk', 0),
                'regression_signals': regression_signals,
            })
            progress('scored', {'scores': scores})
            progress('confidence_calibrated', {
                'production_readiness': scores.get('production_readiness', 0),
                'regression_risk': scores.get('regression_risk', 0),
                'operational_confidence': scores.get('operational_confidence', 0),
                'signal_consensus': scores.get('signal_consensus', 0),
                'uncertainty': scores.get('uncertainty', 0),
                'signal_count': scores.get('fusion_signal_count', 0),
                'sparse_evidence': scores.get('fusion_sparse_evidence', False),
                'confidence_basis': 'multi_signal_fusion',
                'dominant_signal': fusion_result.get('dominant_signals', [])[0].value if fusion_result.get('dominant_signals') else None,
                'conflict_count': fusion_result.get('conflict_count', 0),
            })
            result.update({'scanned': True, 'evidence': evidence, 'topology': topology, 'scores': scores})
            
            # AI Synthesis Layer
            from pipeline.synthesis_engine import SynthesisEngine
            synth_engine = SynthesisEngine()
            synthesis = synth_engine.synthesize(
                evidence=evidence,
                topology=topology,
                scores=scores,
                propagation=evidence.get('propagation', {})
            )
            result['synthesis'] = synthesis
            
            progress('completed', {'result_summary': {'services': len(evidence.get('services', [])), 'scores': scores, 'synthesis': result.get('synthesis')}})
            # finalize run deterministically
            try:
                if run_id:
                    finalize_run(run_id, result)
            except Exception:
                pass
            # return immutable snapshot
            return json.loads(json.dumps(result))
        except Exception as e:
            if str(e) == 'cancelled':
                result['error'] = 'cancelled'
                return json.loads(json.dumps(result))
            result['error'] = f'github_ingest_failed: {e}'
            progress('error', {'error': result['error']})
            return result

    if path is None:
        # Remote repository: do not clone by default
        result['error'] = 'remote_repo_requires_clone_or_local_path'
        progress('started', {'status': 'remote_pending', 'message': 'remote repo requires local path or clone permission'})
        try:
            if run_id:
                fail_run(run_id, result['error'])
        except Exception:
            pass
        return json.loads(json.dumps(result))

    if not path.exists():
        result['error'] = 'path_not_found'
        progress('error', {'status': 'path_not_found', 'path': str(path)})
        try:
            if run_id:
                fail_run(run_id, result['error'])
        except Exception:
            pass
        return json.loads(json.dumps(result))

    # Start scanning with concurrent extraction
    progress('started', {'status': 'scanning_local_path_concurrent', 'path': str(path)})
    
    # Run concurrent extraction tasks
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        async def run_all():
            evidence_task = _concurrent_extraction(path)
            if include_live_errors:
                errors = get_sample_errors(include_extended=True)
                clusterer = ErrorClusterer()
                clusters_task = clusterer.cluster_errors(errors)
                evidence, clusters = await asyncio.gather(evidence_task, clusters_task, return_exceptions=True)
                if isinstance(evidence, Exception):
                    raise evidence
                if isinstance(clusters, Exception):
                    logger.error(f"Live error ingestion failed: {clusters}")
                    evidence['live_errors'] = []
                else:
                    evidence['live_errors'] = clusters
                    progress('live_errors_ingested', {
                        'raw_errors': len(errors),
                        'clusters': clusters
                    })
                return evidence
            else:
                return await evidence_task
                
        concurrent_evidence = loop.run_until_complete(run_all())
        loop.close()
    except Exception as e:
        logger.exception(f"Concurrent extraction failed: {e}")
        concurrent_evidence = {
            'files_present': [],
            'workflows': [],
            'dockerfiles': [],
            'kubernetes_manifests': [],
            'helm_charts': [],
            'terraform': [],
            'prometheus': False,
            'otel': False,
            'package_managers': [],
            'services': [],
            'topology': {'services': [], 'edges': []},
        }
    
    # Merge concurrent extraction results
    evidence = concurrent_evidence.copy()
    
    # Emit progress for each completed extraction task
    extraction_tasks = evidence.pop('extraction_tasks', {})
    if extraction_tasks.get('workflows'):
        progress('workflows_extracted', {
            'workflow_count': extraction_tasks['workflows'].get('extracted_count', 0),
            'concurrent': True,
        })
    
    if extraction_tasks.get('deployments'):
        progress('deployments_correlated', {
            'dockerfiles': len(evidence.get('dockerfiles', [])),
            'kubernetes_manifests': len(evidence.get('kubernetes_manifests', [])),
            'helm_charts': len(evidence.get('helm_charts', [])),
            'terraform': len(evidence.get('terraform', [])),
            'concurrent': True,
        })
    
    if extraction_tasks.get('observability'):
        progress('observability_checked', {
            'prometheus': evidence.get('prometheus', False),
            'otel': evidence.get('otel', False),
            'concurrent': True,
        })
    
    # Normalize dedupe lists
    for k in ('dockerfiles', 'workflows', 'helm_charts', 'terraform', 'kubernetes_manifests'):
        evidence[k] = list({json.dumps(e) if isinstance(e, dict) else e for e in evidence.get(k, [])})

    # Safe counts
    counts = {}
    for k, v in evidence.items():
        if isinstance(v, (list, dict)):
            counts[k] = len(v)
        elif isinstance(v, bool):
            counts[k] = int(v)
        elif v is None:
            counts[k] = 0
        else:
            counts[k] = 1
    
    progress('scanned_files', {'counts': counts, 'concurrent': True, 'extraction_method': 'async_parallel'})
    progress('workflows_extracted', {
        'workflow_count': len(evidence.get('workflows', [])),
        'workflows': [_workflow_path(w) for w in evidence.get('workflows', [])[:5]],
        'concurrent': True,
    })
    progress('deployments_correlated', {
        'dockerfiles': len(evidence.get('dockerfiles', [])),
        'kubernetes_manifests': len(evidence.get('kubernetes_manifests', [])),
        'helm_charts': len(evidence.get('helm_charts', [])),
        'terraform': len(evidence.get('terraform', [])),
        'concurrent': True,
    })
    progress('observability_checked', {
        'prometheus': evidence.get('prometheus', False),
        'otel': evidence.get('otel', False),
        'concurrent': True,
    })

    # Topology already extracted concurrently
    topology = evidence.get('topology', {'services': [], 'edges': []})
    progress('topology', {'topology': topology, 'concurrent': True})
    
    # Topology propagation analysis: compute blast radius, critical paths, risk
    propagation_engine = TopologyPropagationEngine()
    propagation_result = propagation_engine.analyze(topology_graph=topology)
    
    # Expose propagation analysis in evidence
    evidence['propagation'] = {
        'blast_radius': propagation_result.blast_radius,
        'critical_paths': propagation_result.critical_paths,
        'dominant_service': propagation_result.dominant_service,
        'upstream_risk': propagation_result.upstream_risk,
        'downstream_risk': propagation_result.downstream_risk,
        'service_count': propagation_result.service_count,
        'edge_count': propagation_result.edge_count,
        'propagation_depth': propagation_result.propagation_depth,
        'high_risk_dependencies': propagation_result.high_risk_dependencies,
    }
    
    # Emit propagation progress event
    progress('topology_propagation', {
        'blast_radius': propagation_result.blast_radius,
        'dominant_service': propagation_result.dominant_service,
        'critical_paths_count': len(propagation_result.critical_paths),
        'upstream_risk': propagation_result.upstream_risk,
        'downstream_risk': propagation_result.downstream_risk,
        'service_count': propagation_result.service_count,
        'edge_count': propagation_result.edge_count,
    })

    # Scoring
    scoring_engine = OperationalScoringEngine()
    scores = scoring_engine.score_from_evidence(evidence, topology)
    evidence_scores = EvidenceEngine().evaluate(evidence, topology)
    
    # Signal fusion: integrate multi-signal reasoning into confidence
    fusion_engine = SignalFusionEngine()
    
    # Map evidence scores to operational signals
    deployment_conf = evidence_scores.get('deployment_confidence', 0.0)
    observability_conf = evidence_scores.get('observability_confidence', 0.0)
    topology_conf = evidence_scores.get('topology_confidence', 0.0)
    
    # Add signals to fusion engine
    if deployment_conf > 0:
        fusion_engine.add_signal(
            SignalType.TEMPORAL_CORRELATION,
            deployment_conf,
            "deployment_evidence",
            uncertainty=0.1 if deployment_conf < 0.7 else 0.05
        )
    
    if observability_conf > 0:
        fusion_engine.add_signal(
            SignalType.TELEMETRY_CONVERGENCE,
            observability_conf,
            "observability_evidence",
            uncertainty=0.1 if observability_conf < 0.7 else 0.05
        )
    
    if topology_conf > 0:
        fusion_engine.add_signal(
            SignalType.TOPOLOGY_CONSISTENCY,
            topology_conf,
            "topology_evidence",
            uncertainty=0.15 if topology_conf < 0.6 else 0.08
        )
    
    # Derive regression similarity from risk assessment
    regression_risk = scores.get('regression_risk', 0.5)
    regression_similarity = 1.0 - min(1.0, regression_risk)
    if regression_similarity > 0:
        fusion_engine.add_signal(
            SignalType.REGRESSION_SIMILARITY,
            regression_similarity,
            "regression_analysis",
            uncertainty=0.15
        )
    
    # Add workflow signal (deployment resilience)
    workflow_count = len(evidence.get('workflows', []))
    workflow_strength = min(1.0, workflow_count / 3.0)
    if workflow_strength > 0:
        fusion_engine.add_signal(
            SignalType.PROPAGATION_ALIGNMENT,
            workflow_strength,
            "workflow_evidence",
            uncertainty=0.1 if workflow_strength < 0.5 else 0.05
        )
    
    # Add repository health signal
    repo_health = min(
        1.0,
        (len(evidence.get('dockerfiles', [])) * 0.2 +
         len(evidence.get('kubernetes_manifests', [])) * 0.2 +
         len(evidence.get('helm_charts', [])) * 0.1 +
         len(evidence.get('terraform', [])) * 0.1) / 4.0 + (
         1.0 if evidence.get('prometheus') else 0.0) * 0.2 +
        (1.0 if evidence.get('otel') else 0.0) * 0.2
    )
    if repo_health > 0:
        fusion_engine.add_signal(
            SignalType.ANOMALY_ALIGNMENT,
            repo_health,
            "repository_health",
            uncertainty=0.12
        )
    
    # Fuse signals into calibrated confidence
    fusion_result = fusion_engine.fuse()
    
    # Update scores with fused confidence
    scores['operational_confidence'] = fusion_result['confidence']
    scores['signal_consensus'] = fusion_result['convergence_score']
    scores['uncertainty'] = fusion_result['uncertainty']
    scores['fusion_signal_count'] = fusion_result['signal_count']
    scores['fusion_sparse_evidence'] = fusion_result['sparse_evidence']
    
    regression_signals = {
        'observability_gap': not observability_conf,
        'topology_confidence': topology_conf,
        'deployment_confidence': deployment_conf,
        'signal_consensus': fusion_result['convergence_score'],
        'dominant_signals': [s.value for s in fusion_result.get('dominant_signals', [])],
    }
    progress('regression_checked', {
        'risk_score': scores.get('regression_risk', 0),
        'regression_signals': regression_signals,
    })
    progress('scored', {'scores': scores})
    progress('confidence_calibrated', {
        'production_readiness': scores.get('production_readiness', 0),
        'regression_risk': scores.get('regression_risk', 0),
        'operational_confidence': scores.get('operational_confidence', 0),
        'signal_consensus': scores.get('signal_consensus', 0),
        'uncertainty': scores.get('uncertainty', 0),
        'signal_count': scores.get('fusion_signal_count', 0),
        'sparse_evidence': scores.get('fusion_sparse_evidence', False),
        'confidence_basis': 'multi_signal_fusion',
        'dominant_signal': fusion_result.get('dominant_signals', [])[0].value if fusion_result.get('dominant_signals') else None,
        'conflict_count': fusion_result.get('conflict_count', 0),
    })

    result['scanned'] = True
    result['evidence'] = evidence
    result['topology'] = topology
    result['scores'] = scores

    # AI Synthesis Layer
    from pipeline.synthesis_engine import SynthesisEngine
    synth_engine = SynthesisEngine()
    synthesis = synth_engine.synthesize(
        evidence=evidence,
        topology=topology,
        scores=scores,
        propagation=evidence.get('propagation', {})
    )
    result['synthesis'] = synthesis

    progress('completed', {'result_summary': {'services': len(evidence['services']), 'scores': scores, 'synthesis': result.get('synthesis')}})
    try:
        if run_id:
            finalize_run(run_id, result)
    except Exception:
        pass
    return json.loads(json.dumps(result))
