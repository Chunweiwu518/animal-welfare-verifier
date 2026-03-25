"""Facebook scraper using the facebook-scraper library.

pip install facebook-scraper

Scrapes public Facebook pages/groups without API key.
Note: May require cookies for better results.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


async def search_facebook(
    entity_name: str,
    page_ids: list[str] | None = None,
    max_results: int = 10,
    cookies_path: str | None = None,
) -> list[dict]:
    """Search Facebook public pages for posts about the entity.

    Args:
        entity_name: Name to search for in post text.
        page_ids: Optional list of Facebook page IDs/names to scrape.
        max_results: Maximum posts to return.
        cookies_path: Optional path to cookies.txt for authenticated scraping.

    Returns list of dicts compatible with the search pipeline.
    """
    try:
        from facebook_scraper import get_posts
    except ImportError:
        logger.warning(
            "facebook-scraper not installed. Run: pip install facebook-scraper"
        )
        return []

    results: list[dict] = []
    now = datetime.now(timezone.utc).isoformat()
    entity_lower = entity_name.lower()

    # Default animal welfare related pages in Taiwan
    if not page_ids:
        page_ids = []  # User should configure relevant page IDs
        logger.info("No Facebook page_ids configured, skipping Facebook scraping")
        return []

    for page_id in page_ids:
        if len(results) >= max_results:
            break
        try:
            kwargs: dict = {
                "pages": 2,
                "timeout": 15,
                "options": {"allow_extra_requests": False},
            }
            if cookies_path:
                kwargs["cookies"] = cookies_path

            for post in get_posts(page_id, **kwargs):
                if len(results) >= max_results:
                    break

                text = post.get("text") or post.get("post_text") or ""
                if not text:
                    continue

                # Filter: only include posts that mention the entity
                if entity_lower not in text.lower():
                    continue

                post_time = post.get("time")
                published_date = None
                if isinstance(post_time, datetime):
                    published_date = post_time.strftime("%Y-%m-%d")

                post_url = post.get("post_url") or post.get("w3_fb_url") or ""
                likes = post.get("likes") or 0
                comments_count = post.get("comments") or 0
                shares = post.get("shares") or 0

                results.append({
                    "title": f"[Facebook/{post.get('username', page_id)}] {text[:60]}...",
                    "url": post_url,
                    "content": text[:700],
                    "source": f"Facebook {post.get('username', page_id)}",
                    "source_type": "social",
                    "published_date": published_date,
                    "fetched_at": now,
                    "likes": likes,
                    "comments_count": comments_count,
                    "shares": shares,
                    "platform": "facebook",
                })

        except Exception as exc:
            logger.warning("Facebook scrape error for page %s: %s", page_id, exc)
            continue

    return results

