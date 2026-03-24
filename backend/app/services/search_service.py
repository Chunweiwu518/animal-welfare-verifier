from __future__ import annotations

from datetime import datetime, timezone

import httpx

from app.config import Settings


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
        if not self.settings.tavily_api_key:
            return queries, self._mock_results(entity_name, question), "mock"

        results = await self._search_tavily(queries)
        if not results:
            return queries, self._mock_results(entity_name, question), "mock"
        return queries, results, "live"

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

        seen: set[str] = set()
        unique_results = []
        for item in aggregated:
            url = item.get("url")
            if not url or url in seen:
                continue
            seen.add(url)
            unique_results.append(item)
        return unique_results[:10]

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
