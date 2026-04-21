"""One-off: verify + create a curated list of well-known Taiwan shelters.

Usage:
    cd backend && .venv/bin/python -m scripts.bootstrap_top_shelters
"""
from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import Settings
from app.services.persistence_service import PersistenceService
from app.services.shelter_verification_service import ShelterVerificationService

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

# Curated: well-known, real Taiwan animal welfare / shelter organizations,
# preferring ones NOT already in seed_data.py (which has the 5 public zoos).
TOP_SHELTERS = [
    "狗腳印幸福聯盟",
    "流浪動物花園協會",
    "台灣動物緊急救援小組",
    "中華民國保護動物協會",
    "台北市動物之家",
    "新北市板橋區公立動物之家",
    "桃園市動物保護教育園區",
    "台中市動物之家南屯園區",
    "關懷生命協會",
    "台灣之心愛護動物協會",
]


async def main() -> None:
    settings = Settings()
    persistence = PersistenceService(settings)
    persistence.initialize()
    verifier = ShelterVerificationService(settings)

    if not verifier.is_available():
        logger.error("Verification service unavailable: missing OPENAI_API_KEY or TAVILY_API_KEY")
        sys.exit(1)

    created_count = 0
    skipped_count = 0
    failed_count = 0

    for idx, name in enumerate(TOP_SHELTERS, 1):
        logger.info("[%d/%d] Processing: %s", idx, len(TOP_SHELTERS), name)

        existing = persistence.find_entity(name)
        if existing is not None:
            logger.info("  ↳ already in DB as '%s', skipping", existing["name"])
            skipped_count += 1
            continue

        verified, candidate, reason = await verifier.verify(name)
        if not verified or candidate is None:
            logger.warning("  ↳ verify failed: %s", reason)
            failed_count += 1
            continue

        entity_id, created = persistence.create_shelter_full(
            canonical_name=candidate.canonical_name,
            entity_type=candidate.entity_type,
            aliases=candidate.aliases,
            introduction=candidate.introduction,
            location=candidate.address,
            website=candidate.website,
            facebook_url=candidate.facebook_url,
            cover_image_url=candidate.cover_image_url,
        )
        if created:
            created_count += 1
            logger.info(
                "  ↳ created id=%d canonical=%s cover=%s evidence=%d",
                entity_id,
                candidate.canonical_name,
                "YES" if candidate.cover_image_url else "NO",
                len(candidate.evidence_urls),
            )
        else:
            skipped_count += 1
            logger.info("  ↳ already exists (alias collision), id=%d", entity_id)

    logger.info(
        "Done. created=%d skipped=%d failed=%d total=%d",
        created_count,
        skipped_count,
        failed_count,
        len(TOP_SHELTERS),
    )


if __name__ == "__main__":
    asyncio.run(main())
