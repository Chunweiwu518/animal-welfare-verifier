"""Batch-analyze reviews: add relevance_score + stance + short_summary.

Usage:
    .venv/bin/python -m scripts.analyze_reviews           # incremental (only unanalyzed)
    .venv/bin/python -m scripts.analyze_reviews --all     # re-analyze everything
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import Settings
from app.services.persistence_service import PersistenceService
from app.services.review_relevance_service import ReviewRelevanceService

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

BATCH_SIZE = 40  # reviews per API batch (balanced concurrency)


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--all", action="store_true", help="Re-analyze all reviews (ignore analyzed_at)")
    parser.add_argument("--entity", help="Only analyze reviews for this entity")
    args = parser.parse_args()

    settings = Settings()
    persistence = PersistenceService(settings)
    persistence.initialize()
    service = ReviewRelevanceService(settings)

    if not service.is_available():
        logger.error("Missing OPENAI_API_KEY or openai SDK")
        sys.exit(1)

    conn = sqlite3.connect(settings.database_path)
    conn.row_factory = sqlite3.Row

    where = "WHERE 1=1"
    params: list = []
    if not args.all:
        where += " AND r.analyzed_at IS NULL"
    if args.entity:
        where += " AND e.name = ?"
        params.append(args.entity)

    rows = conn.execute(
        f"""
        SELECT r.id, r.entity_id, r.platform, r.content, r.parent_title, e.name AS entity_name
        FROM reviews r
        JOIN entities e ON e.id = r.entity_id
        {where}
        ORDER BY r.entity_id, r.id
        """,
        params,
    ).fetchall()

    logger.info("Reviews to analyze: %d", len(rows))
    if not rows:
        logger.info("Nothing to do")
        return

    # Group by entity for batch-context
    per_entity: dict[int, list] = defaultdict(list)
    for r in rows:
        per_entity[r["entity_id"]].append(r)

    total_done = 0
    stats = {"relevant": 0, "borderline": 0, "noise": 0}
    stance_count: dict[str, int] = defaultdict(int)
    content_type_count: dict[str, int] = defaultdict(int)

    for entity_id, items in per_entity.items():
        entity_name = items[0]["entity_name"]
        logger.info(
            "[entity=%s] analyzing %d reviews...", entity_name, len(items)
        )

        for i in range(0, len(items), BATCH_SIZE):
            batch = items[i : i + BATCH_SIZE]
            payloads = [
                {
                    "platform": row["platform"],
                    "content": row["content"],
                    "parent_title": row["parent_title"],
                }
                for row in batch
            ]
            results = await service.analyze_batch(entity_name, payloads)

            for row, analysis in zip(batch, results):
                conn.execute(
                    """
                    UPDATE reviews
                    SET relevance_score=?, stance=?, short_summary=?, content_type=?, analyzed_at=CURRENT_TIMESTAMP
                    WHERE id=?
                    """,
                    (
                        analysis.relevance_score,
                        analysis.stance,
                        analysis.short_summary,
                        analysis.content_type,
                        row["id"],
                    ),
                )
                if analysis.relevance_score >= 0.6:
                    stats["relevant"] += 1
                elif analysis.relevance_score >= 0.3:
                    stats["borderline"] += 1
                else:
                    stats["noise"] += 1
                stance_count[analysis.stance] += 1
                content_type_count[analysis.content_type] += 1

            conn.commit()
            total_done += len(batch)
            logger.info(
                "  batch done: %d/%d for %s  (running total: %d)",
                min(i + BATCH_SIZE, len(items)),
                len(items),
                entity_name,
                total_done,
            )

    logger.info(
        "DONE. Analyzed %d reviews. Relevance: %s. Stance: %s. ContentType: %s",
        total_done,
        stats,
        dict(stance_count),
        dict(content_type_count),
    )


if __name__ == "__main__":
    asyncio.run(main())
