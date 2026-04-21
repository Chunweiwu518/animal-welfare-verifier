"""Fill cover_image_url for watchlist entities that still have empty covers.

Runs LLM verify and updates entity_page_profiles.cover_image_url.
"""
from __future__ import annotations

import asyncio
import logging
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import Settings
from app.services.persistence_service import PersistenceService
from app.services.shelter_verification_service import ShelterVerificationService

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


async def main() -> None:
    settings = Settings()
    persistence = PersistenceService(settings)
    persistence.initialize()
    verifier = ShelterVerificationService(settings)

    conn = sqlite3.connect(settings.database_path)
    rows = conn.execute(
        """
        SELECT e.id, e.name
        FROM entities e
        JOIN entity_watchlists w ON w.entity_id = e.id
        LEFT JOIN entity_page_profiles p ON p.entity_id = e.id
        WHERE COALESCE(p.cover_image_url, '') = ''
        """
    ).fetchall()

    logger.info("Entities without cover: %d", len(rows))

    updated = 0
    for entity_id, name in rows:
        logger.info("Verifying %s...", name)
        verified, candidate, reason = await verifier.verify(name)
        if not verified or candidate is None or not candidate.cover_image_url:
            logger.warning("  ↳ no cover: verified=%s reason=%s url=%s",
                           verified, reason, candidate.cover_image_url if candidate else None)
            continue

        alt = f"{name} 介紹圖片"
        conn.execute(
            """
            INSERT INTO entity_page_profiles (
                entity_id, headline, introduction, location,
                cover_image_url, cover_image_alt, gallery_json, updated_at
            ) VALUES (?, '', '', '', ?, ?, '[]', CURRENT_TIMESTAMP)
            ON CONFLICT(entity_id) DO UPDATE SET
                cover_image_url = excluded.cover_image_url,
                cover_image_alt = excluded.cover_image_alt,
                updated_at = CURRENT_TIMESTAMP
            """,
            (entity_id, candidate.cover_image_url, alt),
        )
        conn.commit()
        updated += 1
        logger.info("  ↳ set cover: %s", candidate.cover_image_url)

    logger.info("Done. updated=%d/%d", updated, len(rows))


if __name__ == "__main__":
    asyncio.run(main())
