"""Batch-classify reviews into dimensions (staff attitude, transparency, etc).

Usage:
    .venv/bin/python -m scripts.classify_review_dimensions                # incremental
    .venv/bin/python -m scripts.classify_review_dimensions --all          # re-classify everything
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import Settings
from app.services.dimension_classifier import ReviewDimensionClassifier, DIMENSIONS
from app.services.persistence_service import PersistenceService

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

BATCH_SIZE = 30
MIN_RELEVANCE = 0.6  # only classify reviews that passed the relevance filter


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--all", action="store_true", help="Re-classify even already-classified")
    parser.add_argument("--entity", help="Limit to one entity")
    parser.add_argument("--limit", type=int, default=10000)
    args = parser.parse_args()

    settings = Settings()
    persistence = PersistenceService(settings)
    persistence.initialize()
    classifier = ReviewDimensionClassifier(settings)
    if not classifier.is_available():
        logger.error("OpenAI not configured")
        sys.exit(1)

    conn = sqlite3.connect(settings.database_path)
    conn.row_factory = sqlite3.Row

    where = "WHERE r.relevance_score >= ?"
    params: list = [MIN_RELEVANCE]
    if not args.all:
        where += " AND r.dimensions_classified_at IS NULL"
    if args.entity:
        where += " AND e.name = ?"
        params.append(args.entity)
    params.append(args.limit)

    rows = conn.execute(
        f"""
        SELECT r.id, r.entity_id, r.platform, r.content, r.parent_title, e.name AS entity_name
        FROM reviews r JOIN entities e ON e.id = r.entity_id
        {where}
        ORDER BY r.id
        LIMIT ?
        """,
        params,
    ).fetchall()

    logger.info("Reviews to classify: %d", len(rows))
    if not rows:
        return

    stats = Counter()
    stance_stats = defaultdict(Counter)
    total = 0

    for i in range(0, len(rows), BATCH_SIZE):
        batch = rows[i : i + BATCH_SIZE]
        payloads = [
            {
                "platform": r["platform"],
                "content": r["content"],
                "parent_title": r["parent_title"],
                "entity_name": r["entity_name"],
            }
            for r in batch
        ]
        results = await classifier.classify_batch(payloads)

        for row, tags in zip(batch, results):
            tag_json = json.dumps(
                [t.to_dict() for t in tags], ensure_ascii=False
            )
            conn.execute(
                """
                UPDATE reviews
                SET dimension_tags_json=?, dimensions_classified_at=CURRENT_TIMESTAMP
                WHERE id=?
                """,
                (tag_json, row["id"]),
            )
            for t in tags:
                stats[t.dim] += 1
                stance_stats[t.dim][t.stance] += 1
        conn.commit()
        total += len(batch)
        logger.info("Progress: %d/%d", total, len(rows))

    logger.info("Done. Tag counts:")
    for dim in DIMENSIONS:
        s = stance_stats[dim]
        logger.info(
            "  %s: total=%d  supporting=%d  opposing=%d  neutral=%d",
            dim,
            stats[dim],
            s["supporting"],
            s["opposing"],
            s["neutral"],
        )


if __name__ == "__main__":
    asyncio.run(main())
