"""Google News RSS scraper for reviews pipeline.

Wraps GoogleNewsRssService to return review-format dicts.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from app.config import Settings
from app.services.google_news_rss_service import GoogleNewsRssService

logger = logging.getLogger(__name__)


async def crawl_news_reviews(
    entity_name: str,
    settings: Settings,
    max_results: int = 50,
) -> list[dict]:
    """Crawl Google News RSS for articles about the entity.

    Returns list of dicts ready for PersistenceService.save_reviews().
    """
    service = GoogleNewsRssService(settings)
    queries = [
        f"{entity_name}",
        f"{entity_name} 評價",
        f"{entity_name} 動物",
        # site-restricted queries to pick up Mobile01 / 巴哈姆特 forum threads
        # that do not surface in regular news.google.com results
        f"{entity_name} site:mobile01.com",
        f"{entity_name} site:forum.gamer.com.tw",
    ]

    raw_results = await service.search_reviews(queries)
    now = datetime.now(timezone.utc).isoformat()
    reviews: list[dict] = []
    seen_urls: set[str] = set()

    for item in raw_results:
        url = str(item.get("url") or "").strip()
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)

        title = str(item.get("title") or "").strip()
        content = str(item.get("content") or item.get("snippet") or "").strip()
        if not title and not content:
            continue

        source = str(item.get("source") or "")
        published = item.get("published_date")

        reviews.append({
            "content": f"{title}\n{content}".strip() if content else title,
            "author": source,
            "source_url": url,
            "parent_title": f"[新聞/{source}]" if source else "[新聞]",
            "published_at": published,
            "fetched_at": now,
        })

        if len(reviews) >= max_results:
            break

    logger.info(
        "News review crawl entity=%s reviews=%d",
        entity_name, len(reviews),
    )
    return reviews
