from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

import httpx
from trafilatura.metadata import extract_metadata

from app.config import Settings

logger = logging.getLogger(__name__)


class SearchService:
    def __init__(self, settings: Settings):
        self.settings = settings

    def build_queries(self, entity_name: str, question: str) -> list[str]:
        base = entity_name.strip()
        normalized_question = question.strip()
        return [
            f"{base} {normalized_question}",
            f"{base} 評價",
            f"{base} 爭議",
            f"{base} 新聞",
            f"{base} 動物福利",
        ]

    async def search(self, entity_name: str, question: str) -> tuple[list[str], list[dict], str]:
        queries = self.build_queries(entity_name, question)

        # Run all scrapers in parallel
        tasks: list[asyncio.Task] = []

        # Tavily (Google search proxy)
        if self.settings.tavily_api_key:
            tasks.append(asyncio.create_task(self._search_tavily(queries)))

        # Platform-specific scrapers
        tasks.append(asyncio.create_task(self._search_platforms(entity_name)))

        if not tasks:
            return queries, self._mock_results(entity_name, question), "mock"

        all_results_lists = await asyncio.gather(*tasks, return_exceptions=True)

        # Flatten and merge
        merged: list[dict] = []
        for result in all_results_lists:
            if isinstance(result, Exception):
                logger.warning("Scraper task failed: %s", result)
                continue
            if isinstance(result, list):
                merged.extend(result)

        if not merged:
            return queries, self._mock_results(entity_name, question), "mock"

        # Deduplicate by URL
        seen: set[str] = set()
        unique: list[dict] = []
        for item in merged:
            url = item.get("url", "")
            if not url or url in seen:
                continue
            seen.add(url)
            unique.append(item)

        return queries, unique[:30], "live"

    async def _search_platforms(self, entity_name: str) -> list[dict]:
        """Run all platform-specific scrapers in parallel."""
        from app.services.scrapers.ptt_scraper import search_ptt
        from app.services.scrapers.dcard_scraper import search_dcard
        from app.services.scrapers.facebook_scraper_service import search_facebook
        from app.services.scrapers.google_maps_scraper import search_google_maps

        fb_page_ids = None
        if self.settings.facebook_page_ids:
            fb_page_ids = [p.strip() for p in self.settings.facebook_page_ids.split(",") if p.strip()]

        scraper_tasks = [
            asyncio.create_task(search_ptt(entity_name, max_results=8)),
            asyncio.create_task(search_dcard(entity_name, max_results=8)),
            asyncio.create_task(search_facebook(
                entity_name,
                page_ids=fb_page_ids,
                max_results=5,
                cookies_path=self.settings.facebook_cookies_path,
            )),
            asyncio.create_task(search_google_maps(
                entity_name,
                serpapi_key=self.settings.serpapi_api_key,
                max_results=8,
            )),
        ]

        results_lists = await asyncio.gather(*scraper_tasks, return_exceptions=True)

        merged: list[dict] = []
        for result in results_lists:
            if isinstance(result, Exception):
                logger.warning("Platform scraper failed: %s", result)
                continue
            if isinstance(result, list):
                merged.extend(result)

        return merged

    async def _search_tavily(self, queries: list[str]) -> list[dict]:
        aggregated: list[dict] = []
        async with httpx.AsyncClient(timeout=20.0) as client:
            for query in queries[:3]:
                response = await client.post(
                    "https://api.tavily.com/search",
                    json={
                        "api_key": self.settings.tavily_api_key,
                        "query": query,
                        "search_depth": "advanced",
                        "max_results": 5,
                        "include_answer": False,
                        "include_raw_content": True,
                    },
                )
                response.raise_for_status()
                payload = response.json()
                aggregated.extend(payload.get("results", []))

            enriched_results = []
            for item in aggregated:
                enriched_results.append(await self._enrich_result(item, client))

        seen: set[str] = set()
        unique_results = []
        for item in enriched_results:
            url = item.get("url")
            if not url or url in seen:
                continue
            seen.add(url)
            unique_results.append(item)
        return unique_results[:10]

    async def _enrich_result(self, item: dict, client: httpx.AsyncClient) -> dict:
        enriched = dict(item)
        enriched.setdefault("fetched_at", datetime.now(timezone.utc).isoformat())
        if enriched.get("published_date") and enriched.get("source"):
            return enriched

        url = enriched.get("url")
        if not url:
            return enriched

        try:
            response = await client.get(
                url,
                follow_redirects=True,
                timeout=8.0,
                headers={"User-Agent": "AnimalWelfareVerifier/0.1"},
            )
            response.raise_for_status()
            metadata = extract_metadata(response.text, default_url=str(response.url))
        except Exception:
            return enriched

        if not enriched.get("published_date") and getattr(metadata, "date", None):
            enriched["published_date"] = metadata.date
        if not enriched.get("source") and getattr(metadata, "sitename", None):
            enriched["source"] = metadata.sitename
        if not enriched.get("title") and getattr(metadata, "title", None):
            enriched["title"] = metadata.title
        return enriched

    def _mock_results(self, entity_name: str, question: str) -> list[dict]:
        now = datetime.now(timezone.utc).isoformat()
        return [
            {
                "title": f"{entity_name} 官方說明與改善聲明",
                "url": "https://example.org/official-statement",
                "content": (
                    f"官方針對「{question}」相關疑慮表示，部分流程已改善，"
                    "並公開新的照護與退款說明。"
                ),
                "published_date": "2025-12-10",
                "source": "Official site",
                "fetched_at": now,
            },
            {
                "title": f"{entity_name} 新聞報導：民眾投訴與後續回應",
                "url": "https://example.org/news-report",
                "content": (
                    "新聞彙整多位民眾意見，有人質疑募資透明度與現場環境，"
                    "也有受訪者表示近期已有改善。"
                ),
                "published_date": "2026-01-08",
                "source": "News",
                "fetched_at": now,
            },
            {
                "title": f"{entity_name} 訪客分享：實地參訪觀察",
                "url": "https://example.org/forum-post",
                "content": (
                    "訪客描述實際參訪經驗，提到環境整潔與工作人員態度不錯，"
                    "但也表示票務資訊不夠清楚。"
                ),
                "published_date": "2026-02-02",
                "source": "Forum",
                "fetched_at": now,
            },
        ]
