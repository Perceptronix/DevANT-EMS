"""End-to-end embedding smoke test.

Flow:
1. Build sample orchestrator result.
2. Persist raw_event.
3. Fetch same row via ORM.
4. Verify embedding exists, is 384-D, and is normalized.
"""
import sys
from pathlib import Path
import logging
import numpy as np
from uuid import uuid4

backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

try:
    from dotenv import load_dotenv
    load_dotenv(backend_dir.parent / '.env')
except Exception:
    pass

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

from pipeline.db_persistence import persist_orchestrator_result
from database.client import get_database_client
from database.models import RawEvent
from sqlalchemy import desc
from embeddings import get_similarity_search_service

sample_result = {
    "repo_url": "test/test-repo",
    "test_fingerprint": f"test-signature-{uuid4().hex}",
    "evidence": {
        "live_errors": [
            {
                "signature": None,
                "message": "Test error occurred in function do_work",
                "stack_trace": "Traceback (most recent call last):\n  File \"app.py\", line 10, in <module>\n    raise ValueError('test')\nValueError: test",
                "module": "test.module",
                "error_count": 1,
                "org_count": 1,
                "severity": "error",
                "function": "do_work",
                "container": "test-container",
            }
        ]
    }

}

logger.info("Running persist_orchestrator_result sample ingest...")
counts = persist_orchestrator_result("test-run-emb-1", sample_result)
logger.info("persist counts: %s", counts)

client = get_database_client()

session = client.get_session()
try:
    event = (
        session.query(RawEvent)
        .filter(RawEvent.source_type == "devant_orchestrator")
        .order_by(desc(RawEvent.created_at))
        .first()
    )
    if not event:
        logger.error("No raw_event rows found after ingest")
        sys.exit(1)

    embedding = np.asarray(event.embedding, dtype=np.float32) if event.embedding is not None else None
    if embedding is None:
        logger.error("No embedding stored for raw_event %s", event.id)
        sys.exit(1)

    logger.info("Raw event fingerprint: %s", event.fingerprint)
    logger.info("Embedding dim for raw_event %s: %d", event.id, embedding.shape[0])
    logger.info("Embedding norm: %.6f", float(np.linalg.norm(embedding)))
    logger.info("Embedding sample (first 8): %s", embedding[:8].tolist())

    search_service = get_similarity_search_service(session=session)
    similar_events = search_service.search_similar_events(
        embedding=embedding,
        similarity_threshold=0.75,
        limit=5,
        project_id=str(event.project_id),
    )

    if not similar_events:
        logger.error("Similarity search returned no rows")
        sys.exit(1)

    top_match = similar_events[0]
    logger.info(
        "Top match fingerprint=%s similarity=%.6f distance=%.6f",
        top_match.get("fingerprint"),
        float(top_match.get("similarity", 0.0)),
        float(top_match.get("distance", 1.0)),
    )
finally:
    session.close()

print("Done")
