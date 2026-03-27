"""Google Maps reviews scraper using SerpApi.

SerpApi provides a Google Maps API with 100 free searches/month.
  - Place search: engine=google_maps, q={keyword}, type=search
  - Reviews: engine=google_maps_reviews, place_id={place_id}

Requires SERPAPI_API_KEY in environment.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import httpx

logger = logging.getLogger(__name__)

SERPAPI_BASE = "https://serpapi.com/search.json"


def _normalize_rating(value: object) -> int:
    try:
        return max(0, int(round(float(value))))
    except (TypeError, ValueError):
        return 0


async def search_google_maps(
    entity_name: str,
    serpapi_key: str | None = None,
    max_results: int = 10,
) -> list[dict]:
    """Search Google Maps for a place and fetch its reviews.

    Args:
        entity_name: Name of the place/organization to search.
        serpapi_key: SerpApi API key.
        max_results: Maximum reviews to return.

    Returns list of dicts compatible with the search pipeline.
    """
    if not serpapi_key:
        logger.info("No SERPAPI_API_KEY configured, skipping Google Maps scraper")
        return []

    results: list[dict] = []
    now = datetime.now(timezone.utc).isoformat()

    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
        # Step 1: Search for the place
        place_id = await _find_place_id(client, entity_name, serpapi_key)
        if not place_id:
            logger.info("No Google Maps place found for '%s'", entity_name)
            return []

        # Step 2: Fetch reviews for the place
        try:
            resp = await client.get(
                SERPAPI_BASE,
                params={
                    "engine": "google_maps_reviews",
                    "place_id": place_id,
                    "api_key": serpapi_key,
                    "hl": "zh-TW",
                    "sort_by": "newestFirst",
                },
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            logger.warning("SerpApi reviews request failed: %s", exc)
            return []

        # Extract place info
        place_info = data.get("place_info", {})
        place_name = place_info.get("title", entity_name)
        place_address = place_info.get("address", "")
        place_rating = place_info.get("rating")
        place_reviews_count = place_info.get("reviews")

        # Add a summary card for the place itself
        if place_rating is not None:
            results.append({
                "title": f"[Google Maps] {place_name} — 評分 {place_rating}/5 ({place_reviews_count} 則評論)",
                "url": f"https://www.google.com/maps/place/?q=place_id:{place_id}",
                "content": f"{place_name}，地址：{place_address}。Google Maps 平均評分 {place_rating}/5，共 {place_reviews_count} 則評論。",
                "source": "Google Maps",
                "source_type": "other",
                "published_date": None,
                "fetched_at": now,
                "platform": "google_maps",
                "rating": place_rating,
                "reviews_count": place_reviews_count,
            })

        # Parse individual reviews
        reviews = data.get("reviews", [])
        for review in reviews[: max_results - 1]:
            user_name = review.get("user", {}).get("name", "匿名用戶")
            rating_value = _normalize_rating(review.get("rating", 0))
            snippet = review.get("snippet", review.get("extracted_snippet", {}).get("original", ""))
            date_str = review.get("date", "")
            link = review.get("link", f"https://www.google.com/maps/place/?q=place_id:{place_id}")

            results.append({
                "title": f"[Google Maps 評論] {user_name} — {'⭐' * rating_value}",
                "url": link,
                "content": snippet[:700] if snippet else f"{user_name} 給予 {rating_value} 星評價。",
                "source": "Google Maps",
                "source_type": "other",
                "published_date": _parse_relative_date(date_str),
                "fetched_at": now,
                "platform": "google_maps",
                "user_rating": rating_value,
            })

    return results


async def _find_place_id(
    client: httpx.AsyncClient, entity_name: str, api_key: str
) -> str | None:
    """Search Google Maps for a place and return its place_id."""
    try:
        resp = await client.get(
            SERPAPI_BASE,
            params={
                "engine": "google_maps",
                "q": entity_name,
                "api_key": api_key,
                "hl": "zh-TW",
                "type": "search",
            },
        )
        resp.raise_for_status()
        data = resp.json()
        local_results = data.get("local_results", [])
        if local_results:
            return local_results[0].get("place_id")
        return None
    except Exception as exc:
        logger.warning("SerpApi place search failed: %s", exc)
        return None


def _parse_relative_date(date_str: str) -> str | None:
    """Parse relative date strings like '2 個月前' into ISO date."""
    if not date_str:
        return None
    # For now, just return None — relative dates are hard to parse exactly
    # The recency_label logic in AnalysisService handles "unknown" gracefully
    return None
