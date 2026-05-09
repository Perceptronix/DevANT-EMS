#!/usr/bin/env python3
"""Quick validation script for Phase 3 ↔ Phase 4 integration."""
import sys
import logging
from pathlib import Path

# Add backend to path
backend_path = Path(__file__).parent / "backend"
sys.path.insert(0, str(backend_path))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def validate_imports():
    """Validate all critical imports."""
    logger.info("Validating imports...")
    
    try:
        from orchestration.otlp_clustering_orchestrator import get_otlp_clustering_orchestrator
        logger.info("✅ OTLPClusteringOrchestrator imported")
    except Exception as exc:
        logger.error(f"❌ Failed to import OTLPClusteringOrchestrator: {exc}")
        return False

    try:
        from embeddings.semantic_embedding_service import get_semantic_embedding_service
        logger.info("✅ SemanticEmbeddingService imported")
    except Exception as exc:
        logger.error(f"❌ Failed to import SemanticEmbeddingService: {exc}")
        return False

    try:
        from pipeline.cluster_processing import get_cluster_processing_pipeline
        logger.info("✅ ClusterProcessingPipeline imported")
    except Exception as exc:
        logger.error(f"❌ Failed to import ClusterProcessingPipeline: {exc}")
        return False

    try:
        from orchestration.cluster_scheduler import start_scheduler, stop_scheduler
        logger.info("✅ Scheduler functions imported")
    except Exception as exc:
        logger.error(f"❌ Failed to import scheduler: {exc}")
        return False

    try:
        from database.client import get_database_client
        logger.info("✅ Database client imported")
    except Exception as exc:
        logger.error(f"❌ Failed to import database client: {exc}")
        return False

    return True


def validate_embeddings():
    """Validate embedding service."""
    logger.info("\nValidating embedding service...")
    try:
        from embeddings.semantic_embedding_service import get_semantic_embedding_service
        import numpy as np

        svc = get_semantic_embedding_service()
        embedding = svc.embed_text("Test error message")
        
        if embedding is None:
            logger.error("❌ Embedding returned None")
            return False
        
        if not isinstance(embedding, np.ndarray):
            logger.error(f"❌ Embedding is not ndarray, got {type(embedding)}")
            return False
        
        if len(embedding) != 384:
            logger.error(f"❌ Embedding dimension is {len(embedding)}, expected 384")
            return False
        
        logger.info(f"✅ Embedding service working (dim={len(embedding)})")
        return True
    except Exception as exc:
        logger.error(f"❌ Embedding validation failed: {exc}", exc_info=True)
        return False


def validate_database():
    """Validate database connectivity."""
    logger.info("\nValidating database connectivity...")
    try:
        from database.client import get_database_client

        client = get_database_client()
        session = client.get_session()
        
        # Simple query
        from database.models import RawEvent
        count = session.query(RawEvent).count()
        session.close()
        
        logger.info(f"✅ Database connected (RawEvent count={count})")
        return True
    except Exception as exc:
        logger.error(f"❌ Database validation failed: {exc}")
        return False


def validate_scheduler():
    """Validate scheduler can be started/stopped."""
    logger.info("\nValidating scheduler...")
    try:
        from orchestration.cluster_scheduler import start_scheduler, stop_scheduler

        start_scheduler()
        logger.info("✅ Scheduler started")
        
        stop_scheduler()
        logger.info("✅ Scheduler stopped")
        return True
    except Exception as exc:
        logger.error(f"❌ Scheduler validation failed: {exc}", exc_info=True)
        return False


def main():
    """Run all validations."""
    logger.info("=" * 60)
    logger.info("Phase 3 ↔ Phase 4 Integration Validation")
    logger.info("=" * 60)

    checks = [
        ("Imports", validate_imports),
        ("Embeddings", validate_embeddings),
        ("Database", validate_database),
        ("Scheduler", validate_scheduler),
    ]

    results = []
    for name, check in checks:
        try:
            result = check()
            results.append((name, result))
        except Exception as exc:
            logger.error(f"Validation {name} failed with exception: {exc}", exc_info=True)
            results.append((name, False))

    logger.info("\n" + "=" * 60)
    logger.info("Validation Summary")
    logger.info("=" * 60)
    for name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        logger.info(f"{status}: {name}")

    all_pass = all(result for _, result in results)
    logger.info("=" * 60)
    if all_pass:
        logger.info("🎉 All validations passed!")
        return 0
    else:
        logger.error("❌ Some validations failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
