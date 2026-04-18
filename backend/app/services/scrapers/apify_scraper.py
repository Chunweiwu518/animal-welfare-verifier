"""Apify-based scrapers for Instagram and Facebook.

Requires APIFY_API_TOKEN. Uses Apify's official actors:
- apify/instagram-scraper: hashtag/profile posts
- apify/instagram-comment-scraper: post comments
- apify/facebook-posts-scraper: page posts
- apify/facebook-comments-scraper: post comments
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_call_actor(client, actor_id: str, run_input: dict, timeout_secs: int = 180):
    """Call an Apify actor and return dataset items, or empty list on error."""
    try:
        run = client.actor(actor_id).call(run_input=run_input, timeout_secs=timeout_secs)
        if run.get("status") != "SUCCEEDED":
            logger.warning("Apify actor %s status=%s", actor_id, run.get("status"))
            return []
        return list(client.dataset(run["defaultDatasetId"]).iterate_items())
    except Exception as exc:
        logger.warning("Apify actor %s error: %s", actor_id, exc)
        return []


async def crawl_instagram_posts(
    entity_name: str,
    apify_token: str,
    max_results: int = 10,
) -> list[dict]:
    """Crawl Instagram hashtag posts via Apify."""
    if not apify_token:
        return []
    try:
        from apify_client import ApifyClient
    except ImportError:
        logger.warning("apify-client not installed")
        return []

    client = ApifyClient(apify_token)
    now = _now()
    reviews: list[dict] = []

    # Try hashtag first
    hashtag_url = f"https://www.instagram.com/explore/tags/{entity_name}/"
    items = _safe_call_actor(
        client,
        "apify/instagram-scraper",
        {
            "directUrls": [hashtag_url],
            "resultsType": "posts",
            "resultsLimit": max_results,
            "searchType": "hashtag",
            "searchLimit": 1,
        },
    )

    for item in items[:max_results]:
        caption = item.get("caption") or ""
        if not caption.strip():
            continue
        reviews.append({
            "content": caption[:1000],
            "author": item.get("ownerUsername"),
            "source_url": item.get("url") or "",
            "parent_title": "[Instagram 貼文]",
            "likes": int(item.get("likesCount") or 0),
            "published_at": item.get("timestamp"),
            "fetched_at": now,
        })

    logger.info("Apify IG posts entity=%s got=%d", entity_name, len(reviews))
    return reviews


async def crawl_instagram_comments(
    entity_name: str,
    apify_token: str,
    post_urls: list[str] | None = None,
    max_results: int = 50,
) -> list[dict]:
    """Crawl Instagram post comments via Apify.

    post_urls: list of IG post URLs; if not given, first searches hashtag for URLs.
    """
    if not apify_token:
        return []
    try:
        from apify_client import ApifyClient
    except ImportError:
        return []

    client = ApifyClient(apify_token)
    now = _now()
    reviews: list[dict] = []

    # If no URLs given, get them from hashtag
    if not post_urls:
        hashtag_url = f"https://www.instagram.com/explore/tags/{entity_name}/"
        post_items = _safe_call_actor(
            client,
            "apify/instagram-scraper",
            {
                "directUrls": [hashtag_url],
                "resultsType": "posts",
                "resultsLimit": 5,
                "searchType": "hashtag",
                "searchLimit": 1,
            },
        )
        post_urls = [p.get("url") for p in post_items if p.get("url")][:5]

    if not post_urls:
        return []

    # Fetch comments for each post
    comment_items = _safe_call_actor(
        client,
        "apify/instagram-comment-scraper",
        {
            "directUrls": post_urls,
            "resultsLimit": max_results,
        },
    )

    for item in comment_items[:max_results]:
        text = item.get("text") or ""
        if not text.strip():
            continue
        reviews.append({
            "content": text[:500],
            "author": item.get("ownerUsername"),
            "source_url": item.get("postUrl") or "",
            "parent_title": "[Instagram 留言]",
            "likes": int(item.get("likesCount") or 0),
            "published_at": item.get("timestamp"),
            "fetched_at": now,
        })

    logger.info("Apify IG comments entity=%s got=%d", entity_name, len(reviews))
    return reviews


async def crawl_facebook_posts(
    entity_name: str,
    apify_token: str,
    page_urls: list[str] | None = None,
    max_results: int = 10,
) -> list[dict]:
    """Crawl Facebook page posts via Apify."""
    if not apify_token:
        return []
    try:
        from apify_client import ApifyClient
    except ImportError:
        return []
    if not page_urls:
        # Without explicit page URL we can't crawl FB effectively
        logger.info("No FB page URLs configured for %s, skipping", entity_name)
        return []

    client = ApifyClient(apify_token)
    now = _now()
    reviews: list[dict] = []

    items = _safe_call_actor(
        client,
        "apify/facebook-posts-scraper",
        {
            "startUrls": [{"url": u} for u in page_urls],
            "resultsLimit": max_results,
        },
    )

    for item in items[:max_results]:
        text = item.get("text") or item.get("message") or ""
        if not text.strip():
            continue
        reviews.append({
            "content": text[:1000],
            "author": item.get("user", {}).get("name") if isinstance(item.get("user"), dict) else item.get("pageName"),
            "source_url": item.get("url") or item.get("postUrl") or "",
            "parent_title": "[Facebook 貼文]",
            "likes": int(item.get("likes") or 0),
            "published_at": item.get("time") or item.get("timestamp"),
            "fetched_at": now,
        })

    logger.info("Apify FB posts entity=%s got=%d", entity_name, len(reviews))
    return reviews


async def crawl_facebook_comments(
    entity_name: str,
    apify_token: str,
    post_urls: list[str] | None = None,
    max_results: int = 50,
) -> list[dict]:
    """Crawl Facebook post comments via Apify."""
    if not apify_token or not post_urls:
        return []
    try:
        from apify_client import ApifyClient
    except ImportError:
        return []

    client = ApifyClient(apify_token)
    now = _now()
    reviews: list[dict] = []

    items = _safe_call_actor(
        client,
        "apify/facebook-comments-scraper",
        {
            "startUrls": [{"url": u} for u in post_urls],
            "resultsLimit": max_results,
        },
    )

    for item in items[:max_results]:
        text = item.get("text") or ""
        if not text.strip():
            continue
        reviews.append({
            "content": text[:500],
            "author": item.get("profileName") or item.get("user"),
            "source_url": item.get("commentUrl") or item.get("postUrl") or "",
            "parent_title": "[Facebook 留言]",
            "likes": int(item.get("likesCount") or item.get("reactionsCount") or 0),
            "published_at": item.get("date") or item.get("timestamp"),
            "fetched_at": now,
        })

    logger.info("Apify FB comments entity=%s got=%d", entity_name, len(reviews))
    return reviews
