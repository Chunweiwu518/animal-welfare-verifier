"""Pipeline runner script.

Usage:
    python -m scripts.run_pipeline --pipeline ptt
    python -m scripts.run_pipeline --pipeline all
    python -m scripts.run_pipeline --pipeline ptt --entity "趙媽媽狗園"
    python -m scripts.run_pipeline --pipeline all --entity "台北市動物之家"
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import Settings
from app.pipelines.orchestrator import CrawlOrchestrator
from app.pipelines.registry import list_all, list_available
from app.services.persistence_service import PersistenceService

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def main() -> None:
    parser = argparse.ArgumentParser(description="Run review crawl pipelines")
    parser.add_argument(
        "--pipeline", required=True,
        help="Pipeline name (ptt, news, threads, google_maps) or 'all'",
    )
    parser.add_argument("--entity", help="Entity name to crawl (optional, defaults to watchlist)")
    parser.add_argument("--max-results", type=int, default=50, help="Max reviews per pipeline per entity")
    parser.add_argument("--list", action="store_true", help="List available pipelines and exit")
    args = parser.parse_args()

    settings = Settings()
    persistence = PersistenceService(settings)
    persistence.initialize()
    orchestrator = CrawlOrchestrator(settings, persistence)

    if args.list:
        available = list_available(settings)
        all_names = list_all()
        for name in all_names:
            status = "available" if name in available else "unavailable (missing API key)"
            print(f"  {name}: {status}")
        return

    if args.entity:
        if args.pipeline == "all":
            results = await orchestrator.run_all_for_entity(
                args.entity, max_results=args.max_results,
            )
        else:
            saved = await orchestrator.run_pipeline_for_entity(
                args.pipeline, args.entity, max_results=args.max_results,
            )
            results = {args.pipeline: saved}
    else:
        if args.pipeline == "all":
            all_results: dict[str, int] = {}
            for platform in list_available(settings):
                platform_results = await orchestrator.run_pipeline_for_watchlist(
                    platform, max_results=args.max_results,
                )
                for name, count in platform_results.items():
                    all_results[f"{platform}/{name}"] = count
            results = all_results
        else:
            results = await orchestrator.run_pipeline_for_watchlist(
                args.pipeline, max_results=args.max_results,
            )

    total = sum(results.values())
    logger.info("Pipeline run complete. Total reviews saved: %d", total)
    for key, count in results.items():
        logger.info("  %s: %d reviews", key, count)


if __name__ == "__main__":
    asyncio.run(main())
