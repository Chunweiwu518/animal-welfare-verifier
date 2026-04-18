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


async def crawl_ptt_reviews(
    entity_name: str,
    max_articles: int = 10,
) -> list[dict]:
    """Crawl PTT articles and extract pushes (推/噓/→) as individual reviews.

    Returns list of dicts ready for PersistenceService.save_reviews().
    """
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        logger.warning("beautifulsoup4 not installed, skipping PTT review crawl")
        return []

    reviews: list[dict] = []
    now = datetime.now(timezone.utc).isoformat()
    seen_urls: set[str] = set()

    async with httpx.AsyncClient(
        timeout=15.0,
        headers=HEADERS,
        cookies=PTT_COOKIES,
        follow_redirects=True,
    ) as client:
        for board in BOARDS:
            if len(seen_urls) >= max_articles:
                break
            for keyword in _build_search_keywords(entity_name)[:3]:
                if len(seen_urls) >= max_articles:
                    break
                search_url = f"{PTT_BASE}/bbs/{board}/search?q={quote(keyword)}"
                try:
                    resp = await client.get(search_url)
                    if resp.status_code != 200:
                        continue
                except Exception as exc:
                    logger.warning("PTT search error board=%s: %s", board, exc)
                    continue

                soup = BeautifulSoup(resp.text, "html.parser")
                entries = soup.select("div.r-ent")

                for entry in entries[:10]:
                    if len(seen_urls) >= max_articles:
                        break
                    title_tag = entry.select_one("div.title a")
                    if not title_tag:
                        continue
                    title = title_tag.get_text(strip=True)
                    href = title_tag.get("href", "")
                    post_url = urljoin(PTT_BASE, href)

                    if post_url in seen_urls:
                        continue
                    if not _matches_entity(title, entity_name):
                        continue

                    seen_urls.add(post_url)
                    pushes = await _fetch_article_pushes(
                        client, post_url, board, title, BeautifulSoup,
                    )
                    reviews.extend(pushes)

    logger.info(
        "PTT review crawl entity=%s articles=%d reviews=%d",
        entity_name, len(seen_urls), len(reviews),
    )
    return reviews


async def _fetch_article_pushes(
    client: httpx.AsyncClient,
    url: str,
    board: str,
    article_title: str,
    BeautifulSoup: type,
) -> list[dict]:
    """Fetch a PTT article and extract all pushes as review dicts."""
    now = datetime.now(timezone.utc).isoformat()
    try:
        resp = await client.get(url)
        if resp.status_code != 200:
            return []
        soup = BeautifulSoup(resp.text, "html.parser")

        # Parse article date from metalines
        article_date = None
        for meta in soup.select("div.article-metaline"):
            tag = meta.select_one("span.article-meta-tag")
            value = meta.select_one("span.article-meta-value")
            if tag and value and "時間" in tag.get_text():
                article_date = _parse_ptt_full_date(value.get_text(strip=True))

        pushes = soup.select("div.push")
        results: list[dict] = []
        for push in pushes:
            tag_el = push.select_one("span.push-tag")
            uid_el = push.select_one("span.push-userid")
            content_el = push.select_one("span.push-content")
            time_el = push.select_one("span.push-ipdatetime")

            if not content_el:
                continue

            sentiment_raw = tag_el.get_text(strip=True) if tag_el else ""
            content_text = content_el.get_text(strip=True)
            if content_text.startswith(": "):
                content_text = content_text[2:]
            content_text = content_text.strip()
            if not content_text:
                continue

            author = uid_el.get_text(strip=True) if uid_el else None
            push_time = time_el.get_text(strip=True) if time_el else None

            sentiment = None
            if "推" in sentiment_raw:
                sentiment = "推"
            elif "噓" in sentiment_raw:
                sentiment = "噓"
            elif "→" in sentiment_raw:
                sentiment = "→"

            published_at = _parse_push_datetime(push_time, article_date)

            results.append({
                "content": content_text,
                "author": author,
                "sentiment": sentiment,
                "source_url": url,
                "parent_title": f"[PTT/{board}] {article_title}",
                "published_at": published_at,
                "fetched_at": now,
            })

        return results
    except Exception as exc:
        logger.warning("PTT fetch pushes error url=%s: %s", url, exc)
        return []


def _parse_ptt_full_date(date_str: str) -> str | None:
    """Parse PTT full date like 'Sat Jan  8 17:42:51 2022'."""
    try:
        dt = datetime.strptime(date_str.strip(), "%a %b %d %H:%M:%S %Y")
        return dt.strftime("%Y-%m-%d")
    except (ValueError, AttributeError):
        return None


def _parse_push_datetime(push_time: str | None, article_date: str | None) -> str | None:
    """Parse push datetime like '01/08 17:45' using article year context."""
    if not push_time:
        return article_date
    match = re.search(r"(\d{1,2})/(\d{1,2})\s+(\d{1,2}):(\d{2})", push_time)
    if not match:
        return article_date
    month, day = int(match.group(1)), int(match.group(2))
    year = datetime.now().year
    if article_date:
        try:
            year = int(article_date[:4])
        except (ValueError, IndexError):
            pass
    return f"{year}-{month:02d}-{day:02d}"


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
