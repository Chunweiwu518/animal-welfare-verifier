"""PTT (ptt.cc) scraper using requests + BeautifulSoup.

PTT Web 版是簡單的 HTML，只需帶 cookie over18=1 即可存取。
搜尋路徑: https://www.ptt.cc/bbs/{board}/search?q={keyword}
"""

from __future__ import annotations

import logging
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
BOARDS = ["Gossiping", "pet", "AnimalRight", "WomenTalk", "Lifeismoney"]


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
                search_url = f"{PTT_BASE}/bbs/{board}/search?q={quote(entity_name)}"
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

                    # Get date
                    date_tag = entry.select_one("div.date")
                    date_str = date_tag.get_text(strip=True) if date_tag else ""

                    # Get push count
                    push_tag = entry.select_one("div.nrec span")
                    push_count = push_tag.get_text(strip=True) if push_tag else "0"

                    # Fetch article content (first 500 chars)
                    content = await _fetch_article_content(client, post_url, BeautifulSoup)

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

    return results


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

