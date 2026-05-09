"""
GitHub API ingest helper. Metadata-first operational extraction.
- Uses REST Contents API and Trees API for lightweight sampling
- Handles pagination, rate-limit backoff, retries
- Designed to avoid deep clone; caps on files fetched
"""
import os
import time
import logging
from typing import Optional, Dict, Any, List
import requests

logger = logging.getLogger(__name__)


class GitHubIngestor:
    def __init__(self, token: Optional[str] = None, base_url: str = "https://api.github.com", per_page: int = 100, max_files: int = 2000, timeout: int = 10):
        self.token = token or os.environ.get('GITHUB_TOKEN')
        self.base_url = base_url.rstrip('/')
        self.per_page = per_page
        self.max_files = max_files
        self.timeout = timeout
        self.session = requests.Session()
        if self.token:
            self.session.headers.update({'Authorization': f'token {self.token}'})
        self.session.headers.update({'Accept': 'application/vnd.github.v3+json'})

    def _get(self, url: str, params: Dict[str, Any] = None, max_retries: int = 3) -> Optional[requests.Response]:
        delay = 1.0
        for attempt in range(1, max_retries + 1):
            try:
                resp = self.session.get(url, params=params, timeout=self.timeout)
                if resp.status_code == 403 and 'rate limit' in (resp.text or '').lower():
                    reset = resp.headers.get('X-RateLimit-Reset')
                    if reset:
                        wait = max(1, int(reset) - int(time.time()))
                        logger.warning('GitHub rate limited, sleeping until reset: %s seconds', wait)
                        time.sleep(wait + 1)
                        continue
                if resp.status_code >= 500:
                    logger.warning('GitHub API server error %s on %s', resp.status_code, url)
                    time.sleep(delay)
                    delay *= 2
                    continue
                return resp
            except requests.RequestException as e:
                logger.warning('GitHub API request failed attempt %d: %s', attempt, e)
                time.sleep(delay)
                delay *= 2
        return None

    def parse_repo(self, repo_url: str) -> Optional[Dict[str, str]]:
        """Parse https://github.com/owner/repo or owner/repo into dict."""
        if repo_url.startswith('https://github.com/'):
            parts = repo_url[len('https://github.com/'):].strip('/').split('/')
            if len(parts) >= 2:
                return {'owner': parts[0], 'repo': parts[1]}
        if '/' in repo_url and len(repo_url.split('/')) == 2:
            owner, repo = repo_url.split('/')
            return {'owner': owner, 'repo': repo}
        return None

    def get_repo_tree(self, owner: str, repo: str, ref: str = 'HEAD') -> Optional[Dict[str, Any]]:
        """Get repository tree metadata (non-recursive by default)."""
        url = f"{self.base_url}/repos/{owner}/{repo}/git/trees/{ref}"
        resp = self._get(url, params={'recursive': 0})
        if not resp or resp.status_code != 200:
            logger.warning('Failed to get tree for %s/%s: %s', owner, repo, getattr(resp, 'status_code', None))
            return None
        try:
            return resp.json()
        except Exception:
            return None

    def list_workflows(self, owner: str, repo: str) -> List[Dict[str, Any]]:
        url = f"{self.base_url}/repos/{owner}/{repo}/actions/workflows"
        resp = self._get(url)
        if not resp or resp.status_code != 200:
            return []
        data = resp.json()
        return data.get('workflows', [])

    def get_contents(self, owner: str, repo: str, path: str = '', ref: str = None) -> List[Dict[str, Any]]:
        """List contents of path using Contents API. Avoids fetching large blobs unless match interest patterns."""
        url = f"{self.base_url}/repos/{owner}/{repo}/contents/{path.lstrip('/') or ''}"
        params = {}
        if ref:
            params['ref'] = ref
        resp = self._get(url, params=params)
        if not resp or resp.status_code != 200:
            return []
        try:
            return resp.json() if isinstance(resp.json(), list) else [resp.json()]
        except Exception:
            return []

    def fetch_blob(self, owner: str, repo: str, sha: str) -> Optional[str]:
        url = f"{self.base_url}/repos/{owner}/{repo}/git/blobs/{sha}"
        resp = self._get(url)
        if not resp or resp.status_code != 200:
            return None
        data = resp.json()
        import base64
        try:
            return base64.b64decode(data.get('content', '')).decode(errors='replace')
        except Exception:
            return None

    def sample_operational_files(self, repo_url: str, max_paths: int = 200) -> Dict[str, Any]:
        """Metadata-first sampling: list top-level, workflows, .github, Dockerfiles, manifests up to a cap."""
        parsed = self.parse_repo(repo_url)
        if not parsed:
            return {'error': 'invalid_repo_url'}
        owner = parsed['owner']; repo = parsed['repo']

        result = {'workflows': [], 'dockerfiles': [], 'k8s_manifests': [], 'prometheus': False, 'otel': False}

        # Workflows API
        wfs = self.list_workflows(owner, repo)
        for w in wfs[:max_paths]:
            result['workflows'].append({'id': w.get('id'), 'name': w.get('name'), 'path': w.get('path')})

        # Top-level tree
        tree = self.get_repo_tree(owner, repo, ref='HEAD')
        if not tree:
            return result
        count = 0
        for node in tree.get('tree', [])[:max_paths]:
            if count >= max_paths:
                break
            path = node.get('path', '')
            if path.lower().endswith('dockerfile') or path.lower().startswith('dockerfile'):
                result['dockerfiles'].append(path)
            if path.lower().endswith(('.yml', '.yaml')):
                # light check: could be k8s or prometheus
                # fetch small blob if size small
                if node.get('size', 0) < 32_000 and count < max_paths:
                    blob = self.fetch_blob(owner, repo, node.get('sha'))
                    if blob:
                        lc = blob.lower()
                        if 'kind: deployment' in lc or 'apiVersion:' in lc:
                            result['k8s_manifests'].append(path)
                        if 'prometheus' in lc or 'scrape_configs' in lc:
                            result['prometheus'] = True
                        if 'opentelemetry' in lc or 'otel' in lc or 'collector' in lc:
                            result['otel'] = True
                else:
                    # mark as potential manifest
                    result['k8s_manifests'].append(path)
            count += 1
            if count >= self.max_files:
                break

        return result
