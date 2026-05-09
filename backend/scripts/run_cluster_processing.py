"""Run semantic cluster processing pipeline for recent unclustered events."""

import argparse
import logging
from pathlib import Path

from dotenv import load_dotenv

from pipeline.cluster_processing import get_cluster_processing_pipeline

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


_here = Path(__file__).resolve()
load_dotenv(_here.parents[1] / ".env")
load_dotenv(_here.parents[2] / ".env")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run cluster processing pipeline")
    parser.add_argument("--project-id", type=str, default=None, help="Optional project UUID filter")
    parser.add_argument("--limit", type=int, default=500, help="Max events to fetch")
    parser.add_argument("--lookback-minutes", type=int, default=180, help="Lookback window in minutes")
    parser.add_argument("--min-cluster-size", type=int, default=3, help="HDBSCAN min_cluster_size")
    parser.add_argument("--min-samples", type=int, default=2, help="HDBSCAN min_samples")
    parser.add_argument("--merge-threshold", type=float, default=0.90, help="Cosine similarity threshold for merge")
    args = parser.parse_args()

    pipeline = get_cluster_processing_pipeline(
        min_cluster_size=args.min_cluster_size,
        min_samples=args.min_samples,
        merge_similarity_threshold=args.merge_threshold,
        fetch_limit=args.limit,
        lookback_minutes=args.lookback_minutes,
    )

    result = pipeline.process_recent_unclustered_events(
        project_id=args.project_id,
        limit=args.limit,
        lookback_minutes=args.lookback_minutes,
        min_cluster_size=args.min_cluster_size,
        min_samples=args.min_samples,
    )

    logger.info("Cluster processing result: %s", result)
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
