"""Google Maps reviews adapter for the reviews pipeline.

Wraps the existing search_google_maps() to return review-format dicts.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from app.services.scrapers.google_maps_scraper import search_google_maps

logger = logging.getLogger(__name__)


async def crawl_google_maps_reviews(
    entity_name: str,
    serpapi_key: str | None = None,
    max_results: int = 50,
) -> list[dict]:
    """Crawl Google Maps reviews for the entity.

    Returns list of dicts ready for PersistenceService.save_reviews().
    """
    raw_results = await search_google_maps(
        entity_name,
        serpapi_key=serpapi_key,
        max_results=max_results + 1,  # +1 for the summary card we skip
    )

    reviews: list[dict] = []
    for item in raw_results:
        # Skip the summary card (has reviews_count key)
        if "reviews_count" in item:
            continue

        content = str(item.get("content") or "").strip()
        if not content:
            continue

        user_name = None
        title = str(item.get("title") or "")
        if "評論]" in title:
            # Extract username from "[Google Maps 評論] 王小明 — ⭐⭐⭐"
            parts = title.split("]", 1)
            if len(parts) > 1:
                name_part = parts[1].split("—")[0].strip()
                if name_part:
                    user_name = name_part

        reviews.append({
            "content": content,
            "author": user_name,
            "rating": item.get("user_rating"),
            "source_url": str(item.get("url") or ""),
            "parent_title": "[Google Maps]",
            "published_at": item.get("published_date"),
            "fetched_at": item.get("fetched_at") or datetime.now(timezone.utc).isoformat(),
        })

    logger.info(
        "Google Maps review crawl entity=%s reviews=%d",
        entity_name, len(reviews),
    )
    return reviews
