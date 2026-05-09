"""
Repository Classifier.

Detects the type of repository from scanned evidence so that the
SynthesisEngine can generate repository-specific operational reasoning
rather than generic advice.

Classifier outputs one of:
  frontend_app       — React, Vue, Next.js, Angular, etc.
  backend_api        — REST/GraphQL API server
  microservices      — multiple independent services
  monolith           — single large service
  infrastructure     — Terraform, Helm, Kubernetes configs
  ml_ai              — ML training, inference, data pipelines
  mobile_app         — iOS, Android, React Native
  cli_tooling        — command-line tools
  data_pipeline      — ETL, Spark, Airflow, dbt
  library_package    — npm/pip package
  unknown            — insufficient evidence
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Signal weights per repository type
# Evidence keys → (repo_type, weight)
# ---------------------------------------------------------------------------
_SIGNALS: List[tuple[str, float, str]] = [
    # (evidence_field_check, weight_contribution, repo_type)
    # Infrastructure
    ("terraform",          4.0, "infrastructure"),
    ("kubernetes_manifests", 3.5, "infrastructure"),
    ("helm_charts",        3.0, "infrastructure"),

    # ML / AI
    ("ml_notebooks",       4.0, "ml_ai"),
    ("requirements_ml",    3.0, "ml_ai"),   # torch, tensorflow, etc.

    # Data pipeline
    ("airflow_dags",       4.0, "data_pipeline"),
    ("dbt_models",         4.0, "data_pipeline"),

    # Microservices (many services + k8s)
    ("services_count_high", 3.5, "microservices"),

    # Frontend
    ("frontend_framework", 4.0, "frontend_app"),

    # Backend API
    ("backend_framework",  3.5, "backend_api"),
    ("api_spec",           2.0, "backend_api"),

    # Monolith (big single service, few k8s manifests)
    ("monolith_signal",    2.0, "monolith"),

    # Mobile
    ("mobile_config",      4.0, "mobile_app"),

    # CLI / Tooling
    ("cli_entrypoint",     3.0, "cli_tooling"),

    # Package / Library
    ("package_config",     3.0, "library_package"),
]


class RepositoryClassifier:
    """
    Classifies a repository using evidence collected by the repo scanner and
    GitHub connector.

    Usage::

        clf = RepositoryClassifier()
        result = clf.classify(evidence, github_languages, github_topics)
        # result = {
        #     "repo_type": "backend_api",
        #     "confidence": 0.85,
        #     "signals": ["backend_framework", "api_spec"],
        #     "description": "Backend API service ...",
        # }
    """

    def classify(
        self,
        evidence: Dict[str, Any],
        github_languages: Dict[str, int] | None = None,
        github_topics: List[str] | None = None,
        github_description: str = "",
    ) -> Dict[str, Any]:
        """
        Classify the repository type.

        Args:
            evidence:         Collected repo evidence dict (from repo_analyzer)
            github_languages: Language byte-counts from GitHub API
            github_topics:    Repository topics from GitHub API
            github_description: Repository description from GitHub API

        Returns:
            dict with repo_type, confidence, signals, description
        """
        langs = github_languages or {}
        topics = [t.lower() for t in (github_topics or [])]
        desc = (github_description or "").lower()

        derived = self._derive_signals(evidence, langs, topics, desc)
        scores: Dict[str, float] = {}

        for sig, weight, rtype in _SIGNALS:
            if sig in derived:
                scores[rtype] = scores.get(rtype, 0.0) + weight * derived[sig]

        if not scores:
            return self._build_result("unknown", 0.0, [], evidence)

        best_type = max(scores, key=lambda k: scores[k])
        total = sum(scores.values())
        confidence = min(1.0, scores[best_type] / max(total, 1.0) * 1.5)

        fired_signals = [
            sig for sig, weight, rtype in _SIGNALS
            if rtype == best_type and sig in derived
        ]

        return self._build_result(best_type, confidence, fired_signals, evidence)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _derive_signals(
        self,
        evidence: Dict[str, Any],
        langs: Dict[str, int],
        topics: List[str],
        desc: str,
    ) -> Dict[str, float]:
        """Convert raw evidence into named signal strengths (0..1)."""
        sig: Dict[str, float] = {}

        # ---- Infrastructure -------------------------------------------
        if evidence.get("terraform"):
            sig["terraform"] = 1.0
        if evidence.get("kubernetes_manifests"):
            k = len(evidence["kubernetes_manifests"])
            sig["kubernetes_manifests"] = min(1.0, k / 5)
        if evidence.get("helm_charts"):
            sig["helm_charts"] = 1.0

        # ---- ML / AI --------------------------------------------------
        ml_langs = {"jupyter notebook", "python"}
        ml_topics = {"machine-learning", "deep-learning", "ai", "ml", "pytorch",
                     "tensorflow", "transformers", "llm", "nlp"}
        ml_desc_kw = {"model", "training", "inference", "pytorch", "tensorflow",
                      "torch", "sklearn", "embedding", "transformer"}

        lang_names_lower = {k.lower() for k in langs}
        if "jupyter notebook" in lang_names_lower:
            sig["ml_notebooks"] = 1.0
        if ml_topics & set(topics):
            sig["requirements_ml"] = 0.9
        if any(kw in desc for kw in ml_desc_kw):
            sig["requirements_ml"] = max(sig.get("requirements_ml", 0), 0.7)

        # ---- Data pipeline --------------------------------------------
        dag_topics = {"airflow", "dbt", "spark", "etl", "data-pipeline", "dagster"}
        if dag_topics & set(topics):
            sig["airflow_dags"] = 1.0

        # ---- Microservices --------------------------------------------
        services = evidence.get("services", [])
        svc_count = len(services) if isinstance(services, list) else 0
        if svc_count >= 4:
            sig["services_count_high"] = min(1.0, svc_count / 10)

        # ---- Frontend -------------------------------------------------
        fe_langs = {"typescript", "javascript"}
        fe_topics = {"react", "vue", "angular", "next.js", "vite", "svelte",
                     "nextjs", "frontend", "spa"}
        fe_desc = {"frontend", "react", "vue", "angular", "next.js", "web app",
                   "ui library"}
        if "typescript" in lang_names_lower or "javascript" in lang_names_lower:
            if fe_topics & set(topics) or any(kw in desc for kw in fe_desc):
                sig["frontend_framework"] = 0.9
            elif langs.get("TypeScript", 0) + langs.get("JavaScript", 0) > sum(langs.values()) * 0.7:
                sig["frontend_framework"] = 0.7

        # ---- Backend API ----------------------------------------------
        be_langs = {"python", "go", "java", "ruby", "rust", "c#"}
        be_topics = {"api", "rest", "graphql", "fastapi", "django", "flask",
                     "express", "spring", "backend", "microservice"}
        be_desc = {"api", "backend", "server", "service", "endpoint"}
        if be_langs & lang_names_lower:
            if be_topics & set(topics) or any(kw in desc for kw in be_desc):
                sig["backend_framework"] = 0.85
        if evidence.get("workflows"):
            wf_content = " ".join(
                str(w) for w in evidence["workflows"][:3]
            ).lower()
            if "openapi" in wf_content or "swagger" in wf_content:
                sig["api_spec"] = 0.8

        # ---- Mobile ---------------------------------------------------
        mobile_topics = {"ios", "android", "react-native", "flutter", "mobile"}
        if mobile_topics & set(topics):
            sig["mobile_config"] = 1.0

        # ---- CLI / Tooling --------------------------------------------
        cli_topics = {"cli", "command-line", "tool", "utility"}
        if cli_topics & set(topics):
            sig["cli_entrypoint"] = 1.0

        # ---- Library / Package ----------------------------------------
        pkg_topics = {"library", "package", "sdk", "npm", "pypi"}
        if pkg_topics & set(topics):
            sig["package_config"] = 1.0

        # ---- Monolith (fallback when single service, no k8s) ----------
        if svc_count == 1 and not evidence.get("kubernetes_manifests"):
            if evidence.get("dockerfiles"):
                sig["monolith_signal"] = 0.6

        return sig

    @staticmethod
    def _build_result(
        repo_type: str,
        confidence: float,
        signals: List[str],
        evidence: Dict[str, Any],
    ) -> Dict[str, Any]:
        descriptions = {
            "frontend_app":    "Frontend web application",
            "backend_api":     "Backend API or service",
            "microservices":   "Microservices architecture",
            "monolith":        "Monolithic application",
            "infrastructure":  "Infrastructure-as-code repository",
            "ml_ai":           "Machine learning or AI system",
            "mobile_app":      "Mobile application",
            "cli_tooling":     "CLI tool or utility",
            "data_pipeline":   "Data pipeline or ETL system",
            "library_package": "Library or reusable package",
            "unknown":         "Repository type could not be determined",
        }
        return {
            "repo_type": repo_type,
            "confidence": round(confidence, 2),
            "signals": signals,
            "description": descriptions.get(repo_type, "Unknown"),
        }
