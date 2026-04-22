"""Mobile01 forum scraper.

Mobile01 is protected by Akamai — both plain HTTP and headless Playwright
return "Access Denied". So in practice we rely on SerpApi `site:mobile01.com`
to get thread URLs + Google snippets, and store those as review content.

Playwright-based deep extraction is kept as optional code path behind a
setting (MOBILE01_ENABLE_PLAYWRIGHT) and is a no-op by default. To actually
fetch thread bodies we'd need a residential-proxy scraper API (Bright Data,
ScrapingBee, Apify Mobile01 actor if available).
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timezone

from app.config import Settings
from app.services.serpapi_service import SerpApiService

logger = logging.getLogger(__name__)

MOBILE01_DOMAIN = "mobile01.com"
MAX_POSTS_PER_THREAD = 20
FETCH_TIMEOUT_MS = 15_000


async def crawl_mobile01_reviews(
    entity_name: str,
    settings: Settings,
    max_results: int = 30,
) -> list[dict]:
    """Find Mobile01 threads about entity via SerpApi, then Playwright-extract posts."""
    if not settings.serpapi_api_key:
        logger.info("No SERPAPI_API_KEY, skipping Mobile01 crawl")
        return []

    service = SerpApiService(settings)
    queries = [
        f"{entity_name} site:{MOBILE01_DOMAIN}",
        f"{entity_name} 評價 site:{MOBILE01_DOMAIN}",
        f"{entity_name} 狗 site:{MOBILE01_DOMAIN}",
    ]

    raw = await service.search_reviews(queries)

    # Deduplicate + keep the Google snippet as a fallback per URL
    candidates: list[dict] = []
    seen_urls: set[str] = set()
    for item in raw:
        url = str(item.get("url") or "").strip()
        if not url or MOBILE01_DOMAIN not in url or url in seen_urls:
            continue
        seen_urls.add(url)
        candidates.append(
            {
                "url": url,
                "title": str(item.get("title") or "").strip(),
                "snippet": str(item.get("snippet") or item.get("content") or "").strip(),
                "published_date": item.get("published_date"),
            }
        )

    if not candidates:
        return []

    now = datetime.now(timezone.utc).isoformat()
    reviews: list[dict] = []

    enable_playwright = bool(getattr(settings, "mobile01_enable_playwright", False))
    if not enable_playwright:
        # Fast path: SerpApi snippet only. Akamai blocks headless Chromium on mobile01.
        for c in candidates[:max_results]:
            fb = _snippet_fallback(c, now)
            if fb:
                reviews.append(fb)
        logger.info(
            "Mobile01 review crawl entity=%s threads=%d reviews=%d (snippet-only)",
            entity_name, len(candidates), len(reviews),
        )
        return reviews

    try:
        from playwright.async_api import async_playwright
    except ImportError:
        logger.warning("playwright not installed, falling back to snippet-only Mobile01")
        for c in candidates[:max_results]:
            fallback = _snippet_fallback(c, now)
            if fallback:
                reviews.append(fallback)
        return reviews

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
        context = await browser.new_context(
            locale="zh-TW",
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
        )
        page = await context.new_page()

        for c in candidates:
            if len(reviews) >= max_results:
                break
            try:
                posts = await _fetch_thread_posts(page, c["url"])
                if posts:
                    for post in posts[:MAX_POSTS_PER_THREAD]:
                        reviews.append({
                            "content": post["content"],
                            "author": post.get("author", ""),
                            "source_url": c["url"],
                            "parent_title": f"[Mobile01] {c['title']}"[:120],
                            "published_at": c.get("published_date"),
                            "fetched_at": now,
                        })
                else:
                    fb = _snippet_fallback(c, now)
                    if fb:
                        reviews.append(fb)
            except Exception as exc:
                logger.warning("Mobile01 fetch error url=%s: %s", c["url"], exc)
                fb = _snippet_fallback(c, now)
                if fb:
                    reviews.append(fb)

        await context.close()
        await browser.close()

    logger.info(
        "Mobile01 review crawl entity=%s threads=%d reviews=%d",
        entity_name, len(candidates), len(reviews),
    )
    return reviews[:max_results]


def _snippet_fallback(candidate: dict, now: str) -> dict | None:
    title = candidate.get("title") or ""
    snippet = candidate.get("snippet") or ""
    if len(snippet) < 20 and len(title) < 10:
        return None
    return {
        "content": f"{title}\n{snippet}".strip() if snippet else title,
        "author": "",
        "source_url": candidate["url"],
        "parent_title": "[Mobile01]",
        "published_at": candidate.get("published_date"),
        "fetched_at": now,
    }


async def _fetch_thread_posts(page, url: str) -> list[dict]:
    """Fetch a Mobile01 thread and extract each post's text + author."""
    await page.goto(url, timeout=FETCH_TIMEOUT_MS, wait_until="domcontentloaded")
    # Give lazy content a moment to hydrate
    try:
        await page.wait_for_selector("article, .l-post, .single-post", timeout=5000)
    except Exception:
        pass
    await asyncio.sleep(0.8)

    # Mobile01 thread post shape varies by template; try several selectors.
    posts: list[dict] = await page.evaluate(
        """
        () => {
          const bodies = Array.from(document.querySelectorAll(
            'article .l-publish__text, .single-post .single-post__body, .l-post__content'
          ));
          const authors = Array.from(document.querySelectorAll(
            '.l-post__meta .c-listTableTd__title, .single-post__author, .l-post__author'
          ));
          const out = [];
          const n = Math.max(bodies.length, 0);
          for (let i = 0; i < n; i++) {
            const body = bodies[i];
            if (!body) continue;
            const text = (body.innerText || '').trim();
            if (!text) continue;
            const authorEl = authors[i];
            out.push({
              content: text.slice(0, 1200),
              author: authorEl ? (authorEl.innerText || '').trim().slice(0, 40) : '',
            });
          }
          return out;
        }
        """
    )

    cleaned: list[dict] = []
    for post in posts:
        text = _clean_post_text(str(post.get("content") or ""))
        if len(text) < 15:
            continue
        cleaned.append({"content": text, "author": str(post.get("author") or "")})
    return cleaned


FOOTER_NOISE_RE = re.compile(
    r"(引用回覆|個人積分|精華文章|發文時間|文章積分|廣告)"
)


def _clean_post_text(text: str) -> str:
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    kept: list[str] = []
    for line in lines:
        if FOOTER_NOISE_RE.search(line):
            continue
        if re.match(r"^\d+\s*引言\s*$", line):
            continue
        kept.append(line)
    return "\n".join(kept).strip()
