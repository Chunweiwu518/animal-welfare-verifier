"""PTT (ptt.cc) scraper using requests + BeautifulSoup.

PTT Web 版是簡單的 HTML，只需帶 cookie over18=1 即可存取。
搜尋路徑: https://www.ptt.cc/bbs/{board}/search?q={keyword}
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from urllib.parse import quote, urljoin

import httpx

logger = logging.getLogger(__name__)

PTT_BASE = "https://www.ptt.cc"
PTT_COOKIES = {"over18": "1"}
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
}

# Boards most relevant to animal welfare discussions
BOARDS = ["pet", "dog", "cat", "AnimalForest", "AnimalRight", "Gossiping", "WomenTalk"]
COMMON_SUFFIXES = ("狗園", "流浪狗園", "協會", "園區", "動保", "毛小孩")


async def search_ptt(entity_name: str, max_results: int = 10) -> list[dict]:
    """Search PTT boards for posts mentioning the entity.

    Returns list of dicts with keys: title, url, content, source, published_date, fetched_at
    """
    results: list[dict] = []
    now = datetime.now(timezone.utc).isoformat()

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        logger.warning("beautifulsoup4 not installed, skipping PTT scraper")
        return []

    async with httpx.AsyncClient(
        timeout=15.0,
        headers=HEADERS,
        cookies=PTT_COOKIES,
        follow_redirects=True,
    ) as client:
        for board in BOARDS:
            if len(results) >= max_results:
                break
            try:
                for keyword in _build_search_keywords(entity_name):
                    if len(results) >= max_results:
                        break
                    search_url = f"{PTT_BASE}/bbs/{board}/search?q={quote(keyword)}"
                    resp = await client.get(search_url)
                    if resp.status_code != 200:
                        continue

                    soup = BeautifulSoup(resp.text, "html.parser")
                    entries = soup.select("div.r-ent")

                    for entry in entries[:5]:
                        if len(results) >= max_results:
                            break

                        title_tag = entry.select_one("div.title a")
                        if not title_tag:
                            continue

                        title = title_tag.get_text(strip=True)
                        href = title_tag.get("href", "")
                        post_url = urljoin(PTT_BASE, href)

                        if not _matches_entity(title, entity_name):
                            continue

                        date_tag = entry.select_one("div.date")
                        date_str = date_tag.get_text(strip=True) if date_tag else ""

                        push_tag = entry.select_one("div.nrec span")
                        push_count = push_tag.get_text(strip=True) if push_tag else "0"

                        content = await _fetch_article_content(client, post_url, BeautifulSoup)
                        if content and not _matches_entity(content, entity_name):
                            continue

                        results.append({
                            "title": f"[PTT/{board}] {title}",
                            "url": post_url,
                            "content": content,
                            "source": f"PTT {board}",
                            "source_type": "forum",
                            "published_date": _parse_ptt_date(date_str),
                            "fetched_at": now,
                            "push_count": push_count,
                            "platform": "ptt",
                        })
            except Exception as exc:
                logger.warning("PTT scrape error for board %s: %s", board, exc)
                continue

    return _deduplicate_results(results)[:max_results]


async def _fetch_article_content(
    client: httpx.AsyncClient,
    url: str,
    BeautifulSoup: type,
) -> str:
    """Fetch and extract main text from a PTT article."""
    try:
        resp = await client.get(url)
        if resp.status_code != 200:
            return ""
        soup = BeautifulSoup(resp.text, "html.parser")

        # Remove metadata header lines
        for meta in soup.select("div.article-metaline, div.article-metaline-right"):
            meta.decompose()

        main_content = soup.select_one("div#main-content")
        if not main_content:
            return ""

        # Remove push (comment) section
        for push in main_content.select("div.push"):
            push.decompose()

        text = main_content.get_text(strip=True)
        return text[:700]
    except Exception:
        return ""


def _parse_ptt_date(date_str: str) -> str | None:
    """Parse PTT date format like '3/25' into ISO date string."""
    if not date_str or "/" not in date_str:
        return None
    try:
        parts = date_str.strip().split("/")
        month = int(parts[0])
        day = int(parts[1])
        year = datetime.now().year
        return f"{year}-{month:02d}-{day:02d}"
    except (ValueError, IndexError):
        return None


def _build_search_keywords(entity_name: str) -> list[str]:
    normalized = entity_name.strip()
    tokens = [token for token in re.split(r"[\s　]+", normalized) if token]
    keywords = [normalized]

    for token in tokens:
        if len(token) >= 2:
            keywords.append(token)

    for suffix in COMMON_SUFFIXES:
        if suffix not in normalized:
            keywords.append(f"{normalized}{suffix}")

    seen: set[str] = set()
    ordered: list[str] = []
    for keyword in keywords:
        value = keyword.strip()
        if not value or value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered[:6]


def _matches_entity(text: str, entity_name: str) -> bool:
    normalized_text = text.lower()
    for keyword in _build_search_keywords(entity_name):
        normalized_keyword = keyword.lower()
        if len(normalized_keyword) >= 2 and normalized_keyword in normalized_text:
            return True
    tokens = [token.lower() for token in re.split(r"[\s　]+", entity_name) if token.strip()]
    return any(len(token) >= 2 and token in normalized_text for token in tokens)


def _deduplicate_results(results: list[dict]) -> list[dict]:
    seen_urls: set[str] = set()
    deduped: list[dict] = []
    for result in results:
        url = str(result.get("url") or "").strip()
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        deduped.append(result)
    return deduped
