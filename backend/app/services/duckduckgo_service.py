from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

import httpx
from bs4 import BeautifulSoup

from app.config import Settings

logger = logging.getLogger(__name__)


class DuckDuckGoService:
    def __init__(self, settings: Settings):
        self.settings = settings

    async def search_reviews(self, queries: list[str]) -> list[dict[str, Any]]:
        query_limit = max(1, min(self.settings.duckduckgo_query_limit, 20))
        results_per_query = max(1, min(self.settings.duckduckgo_results_per_query, 10))
        timeout_seconds = max(5, self.settings.duckduckgo_timeout_seconds)
        now = datetime.now(timezone.utc).isoformat()
        merged: list[dict[str, Any]] = []
        headers = {
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36",
        }

        async with httpx.AsyncClient(timeout=float(timeout_seconds), follow_redirects=True, headers=headers) as client:
            for index in range(0, len(queries), query_limit):
                batch = queries[index:index + query_limit]
                payloads = await asyncio.gather(
                    *[
                        self._run_search_query(client, query=query, limit=results_per_query, fetched_at=now)
                        for query in batch
                    ],
                    return_exceptions=True,
                )
                for payload in payloads:
                    if isinstance(payload, Exception):
                        logger.warning("DuckDuckGo search failed: %s", payload)
                        continue
                    merged.extend(payload)

        return merged

    async def _run_search_query(
        self,
        client: httpx.AsyncClient,
        *,
        query: str,
        limit: int,
        fetched_at: str,
    ) -> list[dict[str, Any]]:
        response = await client.post(
            "https://html.duckduckgo.com/html/",
            data={"q": query, "kl": "tw-tzh", "kp": "-2"},
        )
        response.raise_for_status()
        return self._parse_search_results(response.text, query=query, fetched_at=fetched_at, limit=limit)

    def _parse_search_results(self, html: str, *, query: str, fetched_at: str, limit: int) -> list[dict[str, Any]]:
        soup = BeautifulSoup(html, "html.parser")
        results: list[dict[str, Any]] = []

        for item in soup.select(".result"):
            if len(results) >= limit:
                break

            link = item.select_one(".result__a")
            if link is None:
                continue

            url = self._extract_result_url(str(link.get("href") or ""))
            if not url:
                continue

            snippet_node = item.select_one(".result__snippet")
            snippet = snippet_node.get_text(" ", strip=True) if snippet_node is not None else ""
            source_node = item.select_one(".result__url")
            source = source_node.get_text(" ", strip=True) if source_node is not None else urlparse(url).netloc
            title = link.get_text(" ", strip=True)

            results.append(
                {
                    "url": url,
                    "title": title,
                    "content": snippet,
                    "snippet": snippet,
                    "matched_query": query,
                    "source": source,
                    "source_type": "",
                    "published_date": None,
                    "fetched_at": fetched_at,
                }
            )

        return results

    def _extract_result_url(self, href: str) -> str:
        raw = href.strip()
        if not raw:
            return ""
        if raw.startswith("//"):
            raw = f"https:{raw}"

        parsed = urlparse(raw)
        if "duckduckgo.com" not in parsed.netloc:
            return raw

        encoded = parse_qs(parsed.query).get("uddg", [""])[0].strip()
        return unquote(encoded) if encoded else ""