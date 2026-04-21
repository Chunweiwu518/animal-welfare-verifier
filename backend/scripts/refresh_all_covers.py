"""Refresh cover_image_url for all watchlist entities by fetching og:image from
their website or Facebook page. Much more reliable than LLM-generated URLs.

Strategy for each entity:
1. Extract website + facebook_url from entity_page_profiles.introduction (stored as
   free text "Facebook：URL" / "官網：URL") or from re-running LLM verify.
2. Try og:image from website first.
3. Fall back to og:image from facebook_url.
4. Validate with HEAD (status<400, content-type=image/*).
5. Update entity_page_profiles.cover_image_url.
"""
from __future__ import annotations

import asyncio
import html as html_lib
import logging
import re
import sqlite3
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import Settings
from app.services.persistence_service import PersistenceService
from app.services.shelter_verification_service import ShelterVerificationService

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

OG_IMAGE_PATTERNS = [
    # Match og:image OR og:image:url OR og:image:secure_url (in either attr order)
    re.compile(
        r'<meta[^>]+property=[\"\']og:image(?::(?:url|secure_url))?[\"\'][^>]+content=[\"\']([^\"\']+)[\"\']',
        re.IGNORECASE,
    ),
    re.compile(
        r'<meta[^>]+content=[\"\']([^\"\']+)[\"\'][^>]+property=[\"\']og:image(?::(?:url|secure_url))?[\"\']',
        re.IGNORECASE,
    ),
    # Twitter card image as second preference
    re.compile(
        r'<meta[^>]+name=[\"\']twitter:image[\"\'][^>]+content=[\"\']([^\"\']+)[\"\']',
        re.IGNORECASE,
    ),
    re.compile(
        r'<meta[^>]+content=[\"\']([^\"\']+)[\"\'][^>]+name=[\"\']twitter:image[\"\']',
        re.IGNORECASE,
    ),
]

URL_RE = re.compile(r"https?://[^\s，、。\)]+")
HEADERS = {"user-agent": "Mozilla/5.0 (compatible; AnimalWelfareVerifier/1.0)"}


async def _fetch_og_image(client: httpx.AsyncClient, page_url: str) -> str | None:
    try:
        r = await client.get(page_url, headers=HEADERS, timeout=15.0, follow_redirects=True)
    except Exception as exc:
        logger.debug("fetch_og: %s → %s", page_url, exc)
        return None
    if r.status_code >= 400:
        return None
    for pat in OG_IMAGE_PATTERNS:
        m = pat.search(r.text)
        if m:
            img = html_lib.unescape(m.group(1).strip())
            if not img.startswith("http"):
                from urllib.parse import urljoin

                img = urljoin(page_url, img)
            return img
    return None


async def _validate_image(client: httpx.AsyncClient, image_url: str) -> bool:
    # FB CDN blocks HEAD from non-browser UAs but works fine in browsers.
    # Trust fbcdn.net / FB graph URLs and let the frontend onError hide if really broken.
    lower = image_url.lower()
    if "fbcdn.net" in lower or "facebook.com" in lower or "graph.facebook.com" in lower:
        return image_url.startswith("http")
    try:
        # Try HEAD first
        h = await client.head(image_url, headers=HEADERS, timeout=10.0, follow_redirects=True)
        if h.status_code < 400 and "image" in h.headers.get("content-type", ""):
            return True
        if h.status_code < 400:
            # Some servers return 200 with wrong content-type on HEAD; try a GET
            pass
        elif h.status_code == 405 or h.status_code == 403:
            # HEAD not supported — try GET
            pass
        else:
            return False
    except Exception:
        pass
    try:
        r = await client.get(
            image_url, headers=HEADERS, timeout=10.0, follow_redirects=True
        )
        return r.status_code < 400 and "image" in r.headers.get("content-type", "")
    except Exception:
        return False


def _extract_urls_from_intro(intro: str) -> tuple[str | None, str | None]:
    """Return (website, facebook_url)."""
    website = facebook = None
    for match in URL_RE.finditer(intro or ""):
        url = match.group(0).rstrip(".,;")
        lower = url.lower()
        if "facebook.com" in lower or "fb.com" in lower:
            if facebook is None:
                facebook = url
        else:
            if website is None:
                website = url
    return website, facebook


async def main() -> None:
    settings = Settings()
    persistence = PersistenceService(settings)
    persistence.initialize()
    verifier = ShelterVerificationService(settings)

    conn = sqlite3.connect(settings.database_path)
    rows = conn.execute(
        """
        SELECT e.id, e.name, p.introduction, p.cover_image_url
        FROM entities e
        JOIN entity_watchlists w ON w.entity_id = e.id
        LEFT JOIN entity_page_profiles p ON p.entity_id = e.id
        ORDER BY e.id
        """
    ).fetchall()

    logger.info("Refreshing covers for %d entities...", len(rows))

    async with httpx.AsyncClient() as client:
        for entity_id, name, intro, current_cover in rows:
            logger.info("[%s]", name)

            website, fb = _extract_urls_from_intro(intro or "")
            # Fall back to LLM verify if we can't extract both
            if not website and not fb:
                verified, cand, _ = await verifier.verify(name)
                if verified and cand:
                    website = cand.website or None
                    fb = cand.facebook_url or None

            # Try website → fb, keep first working og:image
            new_cover = None
            for source in (website, fb):
                if not source:
                    continue
                img = await _fetch_og_image(client, source)
                if img and await _validate_image(client, img):
                    new_cover = img
                    logger.info("  ↳ og:image from %s → %s", source, img)
                    break
                if img:
                    logger.info("  ↳ og:image invalid (%s), trying next", img)

            if not new_cover:
                # If current cover is also broken, clear it; otherwise keep existing
                if current_cover and current_cover.startswith("http"):
                    valid = await _validate_image(client, current_cover)
                    if valid:
                        logger.info("  ↳ keeping existing valid cover")
                        continue
                    logger.warning("  ↳ existing cover broken: %s", current_cover)
                logger.warning("  ↳ no valid cover found, leaving unchanged")
                continue

            alt = f"{name} 介紹圖片"
            conn.execute(
                """
                INSERT INTO entity_page_profiles (
                    entity_id, headline, introduction, location,
                    cover_image_url, cover_image_alt, gallery_json, updated_at
                ) VALUES (?, '', ?, '', ?, ?, '[]', CURRENT_TIMESTAMP)
                ON CONFLICT(entity_id) DO UPDATE SET
                    cover_image_url = excluded.cover_image_url,
                    cover_image_alt = excluded.cover_image_alt,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (entity_id, intro or "", new_cover, alt),
            )
            conn.commit()
            logger.info("  ↳ UPDATED")

    logger.info("Done.")


if __name__ == "__main__":
    asyncio.run(main())
