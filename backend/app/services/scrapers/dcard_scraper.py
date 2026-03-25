"""Dcard scraper using public API.

Dcard provides a public JSON API:
  - Search: https://www.dcard.tw/service/api/v2/search/posts?query={keyword}
  - Post detail: https://www.dcard.tw/service/api/v2/posts/{id}
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import httpx

logger = logging.getLogger(__name__)

DCARD_API = "https://www.dcard.tw/service/api/v2"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://www.dcard.tw/",
}


async def search_dcard(entity_name: str, max_results: int = 10) -> list[dict]:
    """Search Dcard for posts mentioning the entity.

    Returns list of dicts compatible with the search pipeline.
    """
    results: list[dict] = []
    now = datetime.now(timezone.utc).isoformat()

    async with httpx.AsyncClient(
        timeout=15.0,
        headers=HEADERS,
        follow_redirects=True,
    ) as client:
        try:
            search_url = f"{DCARD_API}/search/posts"
            resp = await client.get(search_url, params={"query": entity_name, "limit": max_results})
            if resp.status_code != 200:
                logger.warning("Dcard search returned status %d", resp.status_code)
                return []

            posts = resp.json()
            if not isinstance(posts, list):
                return []

            for post in posts[:max_results]:
                post_id = post.get("id")
                title = post.get("title", "")
                excerpt = post.get("excerpt", "")
                forum_name = post.get("forumName", "")
                created_at = post.get("createdAt", "")
                like_count = post.get("likeCount", 0)
                comment_count = post.get("commentCount", 0)

                # Build the URL
                post_url = f"https://www.dcard.tw/f/{forum_name}/p/{post_id}" if post_id else ""

                # Try to get full content
                content = excerpt
                if post_id:
                    content = await _fetch_post_content(client, post_id) or excerpt

                # Parse date
                published_date = None
                if created_at:
                    try:
                        dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                        published_date = dt.strftime("%Y-%m-%d")
                    except ValueError:
                        pass

                results.append({
                    "title": f"[Dcard/{forum_name}] {title}",
                    "url": post_url,
                    "content": content[:700] if content else "",
                    "source": f"Dcard {forum_name}",
                    "source_type": "forum",
                    "published_date": published_date,
                    "fetched_at": now,
                    "like_count": like_count,
                    "comment_count": comment_count,
                    "platform": "dcard",
                })

        except Exception as exc:
            logger.warning("Dcard scrape error: %s", exc)

    return results


async def _fetch_post_content(client: httpx.AsyncClient, post_id: int) -> str | None:
    """Fetch full content of a Dcard post."""
    try:
        resp = await client.get(f"{DCARD_API}/posts/{post_id}")
        if resp.status_code != 200:
            return None
        data = resp.json()
        return data.get("content", "") or data.get("excerpt", "")
    except Exception:
        return None

