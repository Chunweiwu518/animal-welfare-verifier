from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

import httpx

from app.config import Settings

logger = logging.getLogger(__name__)


class ExaService:
    def __init__(self, settings: Settings):
        self.settings = settings

    async def search_reviews(self, queries: list[str]) -> list[dict[str, Any]]:
        api_key = self.settings.exa_api_key
        if not api_key:
            return []

        query_limit = max(1, min(self.settings.exa_query_limit, 15))
        results_per_query = max(1, min(self.settings.exa_results_per_query, 10))
        timeout_seconds = max(5, self.settings.exa_timeout_seconds)
        now = datetime.now(timezone.utc).isoformat()
        merged: list[dict[str, Any]] = []
        stop_due_to_quota = False

        headers = {
            "x-api-key": api_key,
            "Content-Type": "application/json",
        }

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
                        logger.warning("Exa search failed: %s", payload)
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
            "https://api.exa.ai/search",
            json={
                "query": query,
                "numResults": limit,
                "text": True,
                "livecrawl": "always",
            },
        )
        response.raise_for_status()
        payload = response.json()
        raw_results = payload.get("results", []) if isinstance(payload, dict) else []

        results: list[dict[str, Any]] = []
        for item in raw_results:
            if not isinstance(item, dict):
                continue
            url = str(item.get("url") or "").strip()
            if not url:
                continue
            results.append(
                {
                    "url": url,
                    "title": str(item.get("title") or "").strip(),
                    "content": str(item.get("text") or "").strip(),
                    "snippet": str(item.get("text") or item.get("highlight") or "").strip()[:700],
                    "matched_query": query,
                    "source": str(item.get("author") or item.get("siteName") or "").strip(),
                    "source_type": "",
                    "published_date": str(item.get("publishedDate") or "").strip() or None,
                    "fetched_at": fetched_at,
                }
            )
        return results
