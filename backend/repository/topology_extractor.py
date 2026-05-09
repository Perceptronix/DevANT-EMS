"""
Topology extractor. Lightweight inference from local repo files.
Returns simple graph: services list and edges (caller -> callee placeholders).
"""
from pathlib import Path
from typing import Dict, Any, List
import yaml
import os


class TopologyExtractor:
    def __init__(self):
        pass

    def extract_from_local_path(self, path: Path) -> Dict[str, Any]:
        services: List[Dict[str, Any]] = []
        edges: List[Dict[str, str]] = []

        # Heuristics: directories containing Dockerfile or package.json or requirements.txt are services
        for root, dirs, files in os.walk(path):
            fname_set = set(f.lower() for f in files)
            markers = fname_set.intersection({'dockerfile', 'package.json', 'requirements.txt', 'pyproject.toml'})
            if markers:
                rel = os.path.relpath(root, path)
                services.append({'name': rel, 'path': rel, 'markers': list(markers)})

        # Simple edge inference: if a Kubernetes manifest references a service name, create edge
        for root, dirs, files in os.walk(path):
            for f in files:
                if f.lower().endswith(('.yml', '.yaml')):
                    fp = Path(root) / f
                    try:
                        txt = fp.read_text(errors='ignore')
                        if 'kind: Deployment' in txt or 'kind: Service' in txt:
                            # quick parse for service name mentions
                            for s in services:
                                if s['name'] in txt:
                                    # connect repository root -> service
                                    edges.append({'from': '.', 'to': s['name']})
                    except Exception:
                        continue

        # dedupe
        unique_services = {s['name']: s for s in services}
        services = list(unique_services.values())
        unique_edges = []
        seen = set()
        for e in edges:
            k = (e['from'], e['to'])
            if k not in seen:
                unique_edges.append(e)
                seen.add(k)

        return {'services': services, 'edges': unique_edges}
