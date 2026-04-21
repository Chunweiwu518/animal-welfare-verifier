"""One-off: use LLM+Tavily to find FB page URLs for all watchlist entities,
write to FACEBOOK_PAGE_IDS in .env, so the FB pipeline can run.
"""
from __future__ import annotations

import asyncio
import logging
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import Settings
from app.services.persistence_service import PersistenceService
from app.services.shelter_verification_service import ShelterVerificationService

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def _sanitize_fb_url(url: str) -> str:
    url = (url or "").strip()
    if not url.startswith(("http://", "https://")):
        return ""
    if "facebook.com" not in url and "fb.com" not in url:
        return ""
    return url.rstrip("/")


async def main() -> None:
    settings = Settings()
    persistence = PersistenceService(settings)
    persistence.initialize()
    verifier = ShelterVerificationService(settings)

    watchlist = persistence.list_due_watchlist_entities(limit=200)
    if not watchlist:
        # Fallback: get all entities in watchlist regardless of due status
        import sqlite3
        conn = sqlite3.connect(settings.database_path)
        names = [
            str(r[0])
            for r in conn.execute(
                "SELECT e.name FROM entities e JOIN entity_watchlists w ON w.entity_id = e.id"
            ).fetchall()
        ]
    else:
        names = [w.entity_name for w in watchlist]

    logger.info("Fetching FB URLs for %d entities...", len(names))

    mapping: list[tuple[str, str]] = []  # (entity_name, fb_url)
    for idx, name in enumerate(names, 1):
        logger.info("[%d/%d] %s", idx, len(names), name)
        verified, candidate, reason = await verifier.verify(name)
        if not verified or candidate is None:
            logger.warning("  ↳ verify failed: %s", reason)
            continue
        fb = _sanitize_fb_url(candidate.facebook_url)
        if fb:
            mapping.append((name, fb))
            logger.info("  ↳ %s", fb)
        else:
            logger.info("  ↳ no FB URL")

    # Build FACEBOOK_PAGE_IDS value: "entity1|url1;entity2|url2"
    fb_value = ";".join(f"{name}|{url}" for name, url in mapping)

    env_path = Path(settings.model_config["env_file"])
    if not env_path.is_absolute():
        env_path = Path(__file__).resolve().parent.parent / env_path
    env_content = env_path.read_text(encoding="utf-8")

    if "FACEBOOK_PAGE_IDS=" in env_content:
        env_content = re.sub(
            r"^FACEBOOK_PAGE_IDS=.*$",
            f"FACEBOOK_PAGE_IDS={fb_value}",
            env_content,
            flags=re.MULTILINE,
        )
    else:
        env_content = env_content.rstrip() + f"\nFACEBOOK_PAGE_IDS={fb_value}\n"

    env_path.write_text(env_content, encoding="utf-8")
    logger.info("Wrote %d mappings to %s", len(mapping), env_path)
    logger.info("Sample: %s", fb_value[:200])


if __name__ == "__main__":
    asyncio.run(main())
