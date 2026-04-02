from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

import httpx

from app.config import Settings

logger = logging.getLogger(__name__)

SERPAPI_BASE = "https://serpapi.com/search.json"


class SerpApiService:
    def __init__(self, settings: Settings):
        self.settings = settings

    async def search_reviews(self, queries: list[str]) -> list[dict[str, Any]]:
        api_key = self.settings.serpapi_api_key
        if not api_key:
            return []

        query_limit = max(1, min(self.settings.serpapi_web_query_limit, 20))
        results_per_query = max(1, min(self.settings.serpapi_web_results_per_query, 10))
        timeout_seconds = max(5, self.settings.serpapi_timeout_seconds)
        now = datetime.now(timezone.utc).isoformat()
        merged: list[dict[str, Any]] = []

        async with httpx.AsyncClient(timeout=float(timeout_seconds), follow_redirects=True) as client:
            for index in range(0, len(queries), query_limit):
                batch = queries[index:index + query_limit]
                payloads = await asyncio.gather(
                    *[
                        self._run_search_query(client, query=query, limit=results_per_query, fetched_at=now, api_key=api_key)
                        for query in batch
                    ],
                    return_exceptions=True,
                )

                stop_due_to_auth = False
                for payload in payloads:
                    if isinstance(payload, Exception):
                        logger.warning("SerpApi web search failed: %s", payload)
                        if self._is_auth_or_quota_error(payload):
                            stop_due_to_auth = True
                            break
                        continue
                    merged.extend(payload)
                if stop_due_to_auth:
                    break

        return merged

    async def _run_search_query(
        self,
        client: httpx.AsyncClient,
        *,
        query: str,
        limit: int,
        fetched_at: str,
        api_key: str,
    ) -> list[dict[str, Any]]:
        response = await client.get(
            SERPAPI_BASE,
            params={
                "engine": "google",
                "q": query,
                "api_key": api_key,
                "hl": "zh-tw",
                "google_domain": "google.com.tw",
                "num": limit,
            },
        )
        response.raise_for_status()
        payload = response.json()
        raw_results = payload.get("organic_results", []) if isinstance(payload, dict) else []

        results: list[dict[str, Any]] = []
        for item in raw_results[:limit]:
            if not isinstance(item, dict):
                continue
            url = str(item.get("link") or "").strip()
            if not url:
                continue
            snippet = str(item.get("snippet") or "").strip()
            publication_info = item.get("publication_info") if isinstance(item.get("publication_info"), dict) else {}
            source = str(item.get("source") or publication_info.get("summary") or "").strip()
            date = str(item.get("date") or "").strip() or None
            results.append(
                {
                    "url": url,
                    "title": str(item.get("title") or "").strip(),
                    "content": snippet,
                    "snippet": snippet,
                    "matched_query": query,
                    "source": source,
                    "source_type": "",
                    "published_date": date,
                    "fetched_at": fetched_at,
                }
            )
        return results

    def _is_auth_or_quota_error(self, error: Exception) -> bool:
        return (
            isinstance(error, httpx.HTTPStatusError)
            and error.response is not None
            and error.response.status_code in {401, 402, 403, 429}
        )
