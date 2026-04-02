from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

import httpx

from app.config import Settings

logger = logging.getLogger(__name__)


class FirecrawlService:
    def __init__(self, settings: Settings):
        self.settings = settings

    async def search_reviews(self, queries: list[str]) -> list[dict[str, Any]]:
        api_key = self.settings.firecrawl_api_key
        if not api_key:
            return []

        query_limit = max(1, min(self.settings.firecrawl_query_limit, 15))
        results_per_query = max(1, min(self.settings.firecrawl_results_per_query, 10))
        timeout_seconds = max(5, self.settings.firecrawl_timeout_seconds)

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        now = datetime.now(timezone.utc).isoformat()
        merged: list[dict[str, Any]] = []
        stop_due_to_quota = False

        async with httpx.AsyncClient(timeout=float(timeout_seconds), headers=headers) as client:
            for index in range(0, len(queries), query_limit):
                if stop_due_to_quota:
                    break
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
                        logger.warning("Firecrawl search failed: %s", payload)
                        if self._is_payment_required_error(payload):
                            stop_due_to_quota = True
                            break
                        continue
                    merged.extend(payload)

        return merged

    def _is_payment_required_error(self, error: Exception) -> bool:
        return (
            isinstance(error, httpx.HTTPStatusError)
            and error.response is not None
            and error.response.status_code == 402
        )

    async def _run_search_query(
        self,
        client: httpx.AsyncClient,
        *,
        query: str,
        limit: int,
        fetched_at: str,
    ) -> list[dict[str, Any]]:
        response = await client.post(
            "https://api.firecrawl.dev/v2/search",
            json={
                "query": query,
                "limit": limit,
                "sources": ["web"],
                "scrapeOptions": {
                    "formats": ["markdown"],
                    "onlyMainContent": True,
                },
            },
        )
        response.raise_for_status()
        payload = response.json()
        data = payload.get("data")
        if isinstance(data, dict):
            raw_results = data.get("web", [])
        elif isinstance(data, list):
            raw_results = data
        else:
            raw_results = []

        results: list[dict[str, Any]] = []
        for item in raw_results:
            if not isinstance(item, dict):
                continue
            url = str(item.get("url") or "").strip()
            if not url:
                continue
            metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
            results.append(
                {
                    "url": url,
                    "title": str(item.get("title") or metadata.get("title") or "").strip(),
                    "content": str(item.get("markdown") or "").strip(),
                    "snippet": str(item.get("description") or item.get("snippet") or "").strip(),
                    "matched_query": query,
                    "source": str(metadata.get("sourceURL") or metadata.get("siteName") or "").strip(),
                    "source_type": "",
                    "published_date": str(metadata.get("publishedTime") or metadata.get("published_time") or "").strip() or None,
                    "fetched_at": fetched_at,
                }
            )
        return results
