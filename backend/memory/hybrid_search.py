import asyncio
from typing import Dict, Any, List

from clients.chroma_client import get_chroma_client
from .retrieval import normalize_stacktrace, extract_function_tokens, stacktrace_score
from .deployment_correlation import DeploymentCorrelator
from observability.deployment_tracker import DeploymentTracker
from observability.service_map import owners_for_service
from observability.rollback_engine import RollbackEngine
from .reranker import RetrievalReranker
from .evidence_builder import EvidenceBuilder
from core.scoring import combine_evidence_score


class HybridRetriever:
    """Combines semantic search, keyword retrieval, stacktrace matching,
    deployment correlation, commit correlation and ownership filtering.

    The retriever returns a list of evidence items and a bundled evidence
    structure for the LLM to consume.
    """

    def __init__(self):
        self.client = get_chroma_client()
        self.deployment = DeploymentCorrelator()
        self.deployment_tracker = DeploymentTracker()
        self.reranker = RetrievalReranker()
        self.builder = EvidenceBuilder()

    async def retrieve(self, incident: Dict[str, Any], limit: int = 10) -> Dict[str, Any]:
        """Retrieve evidence for a given incident dict.

        Incident is expected to include keys like `signature`, `stack_trace`,
        `service`, `timestamp`, `commit_hash`, etc.
        """
        query = incident.get("signature") or incident.get("sample_message") or ""

        # 1) Semantic search (embeddings) - batched and async
        sem_task = asyncio.create_task(self.client.search(query, source_filter=None, limit=limit))

        # 2) Semantic search scoped to github code
        code_task = asyncio.create_task(self.client.search_code(query, module=incident.get("service"), limit=limit))

        # 3) Tickets / Issues
        tickets_task = asyncio.create_task(self.client.search_tickets(query, limit=limit))

        sem_results, code_results, ticket_results = await asyncio.gather(sem_task, code_task, tickets_task)

        evidences: List[Dict[str, Any]] = []

        # Convert semantic results into common evidence shape
        def to_evidence(item, kind: str):
            return {
                "source": kind,
                "title": item.get("title") or item.get("metadata", {}).get("title") or item.get("content", "")[:120],
                "content": item.get("content", ""),
                "url": item.get("url") or item.get("metadata", {}).get("url"),
                "base_score": item.get("score", 0.0),
                "metadata": item.get("metadata", {}),
                # optional stack_trace field if available in metadata
                "stack_trace": item.get("metadata", {}).get("stack_trace") or item.get("stack_trace"),
            }

        for r in code_results:
            evidences.append(to_evidence(r, "code"))
        for r in ticket_results:
            evidences.append(to_evidence(r, "ticket"))
        for r in sem_results:
            evidences.append(to_evidence(r, "semantic"))

        # Ownership filtering: if incident specifies owner/service, deprioritize others
        owner = incident.get("owner") or incident.get("service_owner")
        if owner:
            for e in evidences:
                meta_owner = e.get("metadata", {}).get("owner") or e.get("metadata", {}).get("author")
                if meta_owner and owner != meta_owner:
                    # small penalty
                    e["base_score"] *= 0.9

        # Stacktrace matching: compute stacktrace scores
        for e in evidences:
            if incident.get("stack_trace") and e.get("stack_trace"):
                e["stacktrace_score"] = stacktrace_score(incident.get("stack_trace"), e.get("stack_trace"))
            else:
                e["stacktrace_score"] = 0.0

        # Deployment correlation (temporal/nearby events)
        correlation = self.deployment.correlate(incident)

        # Fetch deployments for the repo (if provided) to include in evidence
        deployments = []
        repo = incident.get("repo") or incident.get("repository")
        try:
            if repo:
                deployments = await self.deployment_tracker.fetch_recent_deployments(repo)
        except Exception:
            deployments = []

        # ownership mapping
        service = incident.get("service")
        ownership = owners_for_service(service) if service else []

        # rollback suggestions based on deployment history
        rollback_engine = RollbackEngine(deployment_history=deployments)
        rollback_candidates = rollback_engine.suggest(incident)

        # Apply weighted ranking to produce base_score
        for e in evidences:
            semantic = e.get("base_score", 0.0)
            stack = e.get("stacktrace_score", 0.0)
            # keyword score: simple token overlap
            qtokens = set(extract_function_tokens(normalize_stacktrace(query)))
            dtokens = set(extract_function_tokens(normalize_stacktrace(e.get("content", ""))))
            keyword_score = len(qtokens.intersection(dtokens)) / max(1, len(qtokens)) if qtokens else 0.0

            # deployment score: use correlator score if present
            deployment_score = correlation.get("score", 0.0)
            owner_match = e.get("metadata", {}).get("owner") == owner

            final_base = combine_evidence_score(
                semantic_score=semantic,
                stacktrace_score=stack,
                deployment_score=deployment_score,
                keyword_score=keyword_score,
                owner_match=owner_match,
            )

            # boost if evidence directly references a deployment/commit matching incident
            commit_match_bonus = 0.0
            try:
                inc_commit = incident.get("commit_hash")
                for d in deployments:
                    if d.get("commit_sha") and inc_commit and d.get("commit_sha") == inc_commit:
                        commit_match_bonus = max(commit_match_bonus, 0.2)
                        break
            except Exception:
                commit_match_bonus = 0.0

            e["base_score"] = final_base
            e["deployment_correlation"] = bool(commit_match_bonus)

        # Rerank with additional heuristics
        ranked = self.reranker.rerank(evidences, incident)

        # Build evidence bundle
        bundle = self.builder.build(
            ranked,
            correlation,
            incident,
            deployments=deployments,
            ownership=ownership,
            rollback_candidates=rollback_candidates,
        )

        return bundle
