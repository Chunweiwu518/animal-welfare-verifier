"""PTT crawler powered by agent-browser.

Uses real browser automation instead of HTTP + BeautifulSoup.
Designed to be called from a weekly scheduled crawl — not from the
real-time search path (too slow for interactive use).

Snapshot format (search result page):
    - link "[心得] 壽山動物園領養米克斯三年" [ref=e7]
    - generic
      - StaticText "Romiany"
      - StaticText "2/14"

Article page:
    - StaticText "作者sony577 (...)"
    - StaticText "標題[資訊] 高雄壽山動物園..."
    - StaticText "時間Sat Jan  8 17:42:51 2022"
    - StaticText "<article body>"
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from urllib.parse import quote

from app.services.agent_browser_service import AgentBrowserService

logger = logging.getLogger(__name__)

PTT_BASE = "https://www.ptt.cc"
BOARDS = ["pet", "dog", "cat", "AnimalForest", "AnimalRight", "Gossiping", "WomenTalk"]
COMMON_SUFFIXES = ("狗園", "流浪狗園", "協會", "園區", "動保", "毛小孩")

_ARTICLE_REF_PATTERN = re.compile(r'\[ref=(\w+)\]')
_PUSH_COUNT_PATTERN = re.compile(r'^\s*(\d+|爆|X\d*)\s*$')


def _build_search_keywords(entity_name: str) -> list[str]:
    normalized = entity_name.strip()
    tokens = [t for t in re.split(r'[\s　]+', normalized) if t]
    keywords = [normalized]
    for token in tokens:
        if len(token) >= 2 and token != normalized:
            keywords.append(token)
    for suffix in COMMON_SUFFIXES:
        if suffix not in normalized:
            keywords.append(f"{normalized}{suffix}")
    seen: set[str] = set()
    ordered: list[str] = []
    for kw in keywords:
        v = kw.strip()
        if v and v not in seen:
            seen.add(v)
            ordered.append(v)
    return ordered[:6]


def _matches_entity(text: str, entity_name: str) -> bool:
    lower = text.lower()
    for kw in _build_search_keywords(entity_name):
        if len(kw) >= 2 and kw.lower() in lower:
            return True
    return False


def _parse_search_result_links(snapshot: str) -> list[dict[str, str]]:
    """Parse search-result snapshot into list of {title, ref}."""
    results: list[dict[str, str]] = []
    for line in snapshot.splitlines():
        stripped = line.strip()
        if not stripped.startswith("- link "):
            continue
        # Skip navigation links
        text_match = re.search(r'"([^"]*)"', stripped)
        ref_match = re.search(r'\[ref=(\w+)\]', stripped)
        if not text_match or not ref_match:
            continue
        text = text_match.group(1)
        # PTT article links start with [TAG]
        if not text.startswith("["):
            continue
        results.append({"title": text, "ref": ref_match.group(1)})
    return results


def _find_ref_by_title(snapshot: str, title: str) -> str | None:
    """Find a fresh ref for a link matching *title* in the snapshot."""
    for line in snapshot.splitlines():
        stripped = line.strip()
        if not stripped.startswith("- link "):
            continue
        text_match = re.search(r'"([^"]*)"', stripped)
        ref_match = re.search(r'\[ref=(\w+)\]', stripped)
        if text_match and ref_match and text_match.group(1) == title:
            return ref_match.group(1)
    return None


def _parse_article_snapshot(snapshot: str) -> dict[str, str]:
    """Extract author, date, title, content from an article-page snapshot."""
    author = ""
    date_str = ""
    title = ""
    content_parts: list[str] = []
    in_content = False

    for line in snapshot.splitlines():
        stripped = line.strip()
        if "StaticText" not in stripped and not in_content:
            continue

        text_match = re.search(r'"([^"]*)"', stripped)
        if not text_match:
            # Multi-line StaticText block (no quotes, raw text)
            if in_content and stripped and not stripped.startswith("-"):
                content_parts.append(stripped)
            continue

        text = text_match.group(1)

        if text.startswith("作者"):
            author = text.removeprefix("作者").strip()
            continue
        if text.startswith("標題"):
            title = text.removeprefix("標題").strip()
            continue
        if text.startswith("時間"):
            date_str = text.removeprefix("時間").strip()
            in_content = True
            continue

        if in_content:
            # Stop at push/comment section
            if text.startswith("推 ") or text.startswith("噓 ") or text.startswith("→ "):
                break
            if "推文自動更新" in text:
                break
            content_parts.append(text)

    # Also capture the large StaticText block that contains the article body
    # agent-browser sometimes outputs the full article as one big StaticText
    body_match = re.search(r'StaticText "時間[^"]*"\n([\s\S]*?)(?:- generic\s*\[ref=|$)', snapshot)
    if body_match:
        raw_body = body_match.group(1).strip()
        # Clean up the raw body: remove leading StaticText markers
        lines = []
        for raw_line in raw_body.splitlines():
            cleaned = raw_line.strip()
            if cleaned.startswith("- StaticText "):
                m = re.search(r'"([^"]*)"', cleaned)
                if m:
                    lines.append(m.group(1))
            elif cleaned.startswith("- link "):
                m = re.search(r'"([^"]*)"', cleaned)
                if m:
                    lines.append(m.group(1))
            elif cleaned and not cleaned.startswith("-"):
                lines.append(cleaned)
        if lines:
            content_parts = lines

    content = "\n".join(content_parts).strip()
    # The big StaticText block uses literal \n
    content = content.replace("\\n", "\n").strip()

    return {
        "author": author,
        "date": date_str,
        "title": title,
        "content": content[:1500],
    }


def _parse_ptt_datetime(raw: str) -> str | None:
    """Parse PTT datetime like 'Sat Jan  8 17:42:51 2022'."""
    if not raw:
        return None
    try:
        dt = datetime.strptime(raw.strip(), "%a %b %d %H:%M:%S %Y")
        return dt.strftime("%Y-%m-%d")
    except ValueError:
        return None


def _parse_ptt_short_date(date_str: str) -> str | None:
    """Parse short date like '3/25' into ISO date."""
    if not date_str or "/" not in date_str:
        return None
    try:
        parts = date_str.strip().split("/")
        month, day = int(parts[0]), int(parts[1])
        year = datetime.now().year
        return f"{year}-{month:02d}-{day:02d}"
    except (ValueError, IndexError):
        return None


async def crawl_ptt_for_entity(
    entity_name: str,
    *,
    max_results: int = 30,
    boards: list[str] | None = None,
) -> list[dict]:
    """Crawl PTT boards for posts about *entity_name* using agent-browser.

    Returns list of dicts compatible with ``cache_raw_sources()``:
    ``{url, title, content, source, source_type, author, published_date, fetched_at, platform}``
    """
    browser = AgentBrowserService(timeout=20.0)
    target_boards = boards or BOARDS
    results: list[dict] = []
    seen_urls: set[str] = set()
    now = datetime.now(timezone.utc).isoformat()

    try:
        for board in target_boards:
            if len(results) >= max_results:
                break

            for keyword in _build_search_keywords(entity_name)[:3]:
                if len(results) >= max_results:
                    break

                search_url = f"{PTT_BASE}/bbs/{board}/search?q={quote(keyword)}"
                if not await browser.open(search_url):
                    continue

                snapshot = await browser.snapshot()
                if not snapshot:
                    continue

                article_links = _parse_search_result_links(snapshot)
                logger.info(
                    "ptt_browser_crawl board=%s keyword=%s found=%d",
                    board, keyword, len(article_links),
                )

                # Collect titles we want to visit (refs go stale after navigation)
                wanted_titles = [
                    link_info["title"]
                    for link_info in article_links[:5]
                    if _matches_entity(link_info["title"], entity_name)
                ]

                for wanted_title in wanted_titles:
                    if len(results) >= max_results:
                        break

                    # Re-open search page to get fresh refs
                    if not await browser.open(search_url):
                        break
                    fresh_snapshot = await browser.snapshot()
                    if not fresh_snapshot:
                        break

                    # Find the fresh ref for this title
                    fresh_ref = _find_ref_by_title(fresh_snapshot, wanted_title)
                    if not fresh_ref:
                        continue

                    if not await browser.click(f"@{fresh_ref}"):
                        continue

                    article_url = await browser.get_url()
                    if not article_url or article_url in seen_urls:
                        continue

                    article_snapshot = await browser.snapshot()
                    parsed = _parse_article_snapshot(article_snapshot)

                    # Validate content relevance
                    content = parsed["content"]
                    if content and not _matches_entity(content, entity_name):
                        continue

                    published_date = _parse_ptt_datetime(parsed["date"])
                    seen_urls.add(article_url)
                    results.append({
                        "url": article_url,
                        "title": f"[PTT/{board}] {parsed['title'] or wanted_title}",
                        "content": content,
                        "source": f"PTT {board}",
                        "source_type": "forum",
                        "author": parsed["author"],
                        "published_date": published_date,
                        "fetched_at": now,
                        "platform": "ptt",
                    })
                    logger.info("ptt_browser_crawl captured url=%s title=%s", article_url, wanted_title[:40])

    except Exception as exc:
        logger.error("ptt_browser_crawl failed: %s", exc)
    finally:
        await browser.close()

    logger.info(
        "ptt_browser_crawl entity=%s total_results=%d boards_scanned=%d",
        entity_name, len(results), len(target_boards),
    )
    return results
