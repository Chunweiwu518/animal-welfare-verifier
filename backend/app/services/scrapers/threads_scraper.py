"""Threads scraper using Exa search + Playwright.

Strategy:
1. Use Exa to find Threads profile URLs and post URLs related to entity
2. Use Playwright to visit public profile pages and extract posts + replies
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

import httpx

logger = logging.getLogger(__name__)


async def crawl_threads_reviews(
    entity_name: str,
    exa_api_key: str | None = None,
    max_results: int = 20,
) -> list[dict]:
    """Crawl Threads for posts and replies about the entity.

    Returns list of dicts ready for PersistenceService.save_reviews().
    """
    if not exa_api_key:
        logger.info("No EXA_API_KEY, skipping Threads crawl")
        return []

    now = datetime.now(timezone.utc).isoformat()
    reviews: list[dict] = []

    # Step 1: Use Exa to find Threads URLs
    post_urls = await _exa_search_threads(entity_name, exa_api_key, max_results=max_results)
    if not post_urls:
        logger.info("No Threads results found for %s", entity_name)
        return []

    # Step 2: Use Playwright to crawl each post
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        logger.warning("playwright not installed, skipping Threads crawl")
        return []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
        page = await browser.new_page(locale="zh-TW")

        for url in post_urls:
            try:
                parsed = _parse_threads_posts(
                    await _fetch_threads_page(page, url),
                    url,
                    now,
                )
                reviews.extend(parsed)
            except Exception as exc:
                logger.warning("Threads crawl error url=%s: %s", url, exc)

            if len(reviews) >= max_results:
                break

        await browser.close()

    logger.info(
        "Threads review crawl entity=%s urls=%d reviews=%d",
        entity_name, len(post_urls), len(reviews),
    )
    return reviews[:max_results]


async def _exa_search_threads(
    entity_name: str,
    exa_api_key: str,
    max_results: int = 10,
) -> list[str]:
    """Search Exa for Threads URLs related to entity."""
    urls: list[str] = []
    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            resp = await client.post(
                "https://api.exa.ai/search",
                json={
                    "query": f"{entity_name} 評價 心得",
                    "numResults": min(max_results, 10),
                    "includeDomains": ["threads.net"],
                    "useAutoprompt": True,
                },
                headers={"x-api-key": exa_api_key},
            )
            if resp.status_code == 200:
                data = resp.json()
                for result in data.get("results", []):
                    url = result.get("url", "")
                    if "threads.net" in url:
                        urls.append(url)
        except Exception as exc:
            logger.warning("Exa Threads search error: %s", exc)

    return urls


async def _fetch_threads_page(page, url: str) -> str:
    """Fetch a Threads page and return its text content."""
    await page.goto(url, timeout=30000, wait_until="domcontentloaded")
    # Wait for content to load
    await page.wait_for_timeout(3000)
    return await page.inner_text("body")


def _parse_threads_posts(body_text: str, source_url: str, fetched_at: str) -> list[dict]:
    """Parse Threads page text into review dicts.

    Threads pages show username, then post content, then engagement counts.
    """
    reviews: list[dict] = []
    lines = [line.strip() for line in body_text.split("\n") if line.strip()]

    # Skip login/boilerplate lines
    skip_patterns = [
        "登入", "註冊", "Threads", "使用條款", "隱私政策", "Cookie",
        "暢所欲言", "加入", "© 2", "翻譯",
    ]

    # Lines matching these are preview cards / embed titles for linked media,
    # not actual user-written content. E.g.
    #   "XXX 協會（@xxx）• Instagram 相片與影片"
    #   "facebook.com/share…"
    #   "instagram.com/tssda…"
    #   "youtube.com/@fruit…"
    #   "YT 短影 - > youtube.com/@..."
    EMBED_PATTERNS = [
        "• Instagram ", "Instagram 相片與影片", "• Threads",
        "• Facebook", "Facebook 貼文",
    ]
    URL_PREVIEW_RE = re.compile(
        r"^(https?://|www\.)?"
        r"(instagram\.com|facebook\.com|youtube\.com|youtu\.be|fb\.com|threads\.net|t\.co)[/\w@.]*[…\.]+$"
    )
    NUM_WITH_COMMA_RE = re.compile(r"^[\d,]+$")

    i = 0
    current_author = None
    while i < len(lines):
        line = lines[i]

        # Skip boilerplate
        if any(pat in line for pat in skip_patterns) or len(line) < 3:
            i += 1
            continue

        # Skip embed card / profile preview titles
        if any(pat in line for pat in EMBED_PATTERNS):
            i += 1
            continue

        # Skip truncated URL previews (pure link cards with no user commentary)
        if URL_PREVIEW_RE.match(line):
            i += 1
            continue

        # Detect username pattern (short line, no spaces, possibly with dots/underscores)
        if len(line) < 40 and re.match(r"^[a-zA-Z0-9._]+$", line):
            current_author = line
            i += 1
            continue

        # Detect engagement line (likes/replies counts, possibly with commas)
        if NUM_WITH_COMMA_RE.match(line):
            i += 1
            continue
        if re.match(r"^\d+$", line) and int(line) < 100000:
            i += 1
            continue

        # Detect date-like patterns
        if re.match(r"^\d+[天時分秒]", line) or re.match(r"^\d{4}-\d{1,2}-\d{1,2}", line):
            i += 1
            continue

        # This looks like actual content. Require at least 10 chars of real text
        # (Chinese post/reply worth analyzing) and presence of non-URL substance.
        if len(line) >= 10 and current_author:
            reviews.append({
                "content": line[:500],
                "author": current_author,
                "source_url": source_url,
                "parent_title": "[Threads]",
                "published_at": None,
                "fetched_at": fetched_at,
            })

        i += 1

    return reviews
