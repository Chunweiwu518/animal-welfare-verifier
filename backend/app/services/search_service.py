from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx
from trafilatura.metadata import extract_metadata

from app.config import Settings
from app.services.firecrawl_service import FirecrawlService
from app.services.persistence_service import PersistenceService
from app.services.scrapers.google_maps_scraper import search_google_maps
from app.services.scrapers.ptt_scraper import search_ptt

logger = logging.getLogger(__name__)

LOW_SIGNAL_SOCIAL_MARKERS = (
    "log into facebook",
    "sign up for facebook",
    "explore the things you love",
    "privacy policy",
    "messenger",
    "meta pay",
    "ray-ban meta",
    "create ad",
    "about create ad",
    "more languages",
    "mentions facebook",
    "paint0_linear",
    "paint1_ra",
    "userSpaceOnUse",
    "stop-color",
    "fill'url(%23",
    "error 403",
    "that’s an error",
    "播放影片",
    "current time 0:00",
    "stream type live",
    "skip navigation",
)

EMPTY_CONTENT_MARKERS = (
    "目前沒有可用的摘要內容",
    "目前沒有可用的相關段落",
    "no summary available",
)


class SearchService:
    def __init__(self, settings: Settings, persistence_service: PersistenceService | None = None):
        self.settings = settings
        self.persistence_service = persistence_service
        self.firecrawl_service = FirecrawlService(settings)

    def _bounded_limit(self, value: int, *, default: int, minimum: int = 1, maximum: int = 500) -> int:
        if value < minimum:
            return default
        return min(value, maximum)

    def _metadata_enrich_limit(self) -> int:
        return self._bounded_limit(self.settings.metadata_enrich_limit, default=24, maximum=100)

    def _metadata_enrich_concurrency(self) -> int:
        return self._bounded_limit(self.settings.metadata_enrich_concurrency, default=6, maximum=20)

    def build_queries(self, entity_name: str, question: str) -> list[str]:
        variants = self._expand_entity_variants(entity_name)
        templates = [
            "{base} 評論",
            "{base} 評價",
            "{base} 心得",
            "{base} 口碑",
            "{base} 推薦 不推",
            "{base} 好評 負評",
            "{base} Google 評論",
            "{base} PTT",
            "{base} Dcard",
            "{base} Facebook 評價",
            "{base} Instagram",
            "{base} Threads",
            "site:dcard.tw {base}",
            "site:facebook.com {base}",
            "site:instagram.com {base}",
            "site:threads.net {base}",
            "site:ptt.cc/bbs {base}",
            "site:maps.google.com {base}",
            "\"{base}\" Google 評論",
            "\"{base}\" PTT",
        ]
        candidate_queries: list[str] = []
        for template in templates:
            for base in variants:
                candidate_queries.append(template.format(base=base))

        unique_queries: list[str] = []
        seen: set[str] = set()
        for query in candidate_queries:
            normalized = query.strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            unique_queries.append(normalized)
        return unique_queries

    def _expand_entity_variants(self, entity_name: str) -> list[str]:
        base = entity_name.strip()
        variants = [base]
        if base.endswith("狗園"):
            root = base.removesuffix("狗園").strip()
            variants.extend(
                [
                    f"{root}寵物樂園",
                    f"{root}樂園",
                    f"{root}園區",
                ]
            )
        if base.endswith("樂園"):
            root = base.removesuffix("樂園").strip()
            variants.extend([f"{root}狗園", f"{root}寵物樂園"])

        seen: set[str] = set()
        ordered: list[str] = []
        for variant in variants:
            value = variant.strip()
            if not value or value in seen:
                continue
            seen.add(value)
            ordered.append(value)
        return ordered[:4]

    async def search(self, entity_name: str, question: str) -> tuple[list[str], list[dict], str]:
        queries = self.build_queries(entity_name, question)
        result_limit = self._bounded_limit(self.settings.search_result_limit, default=100, maximum=500)

        merged: list[dict] = []
        if self.settings.firecrawl_api_key:
            try:
                merged = await self.firecrawl_service.search_reviews(queries)
            except Exception as exc:
                logger.warning("Firecrawl search failed: %s", exc)
                merged = []

        platform_results = await self._search_platform_sources(entity_name)
        merged.extend(platform_results)

        if not merged:
            return queries, self._mock_results(entity_name, question), "mock"

        unique = self._deduplicate_by_url(merged)
        unique = self._hydrate_cached_sources(unique)
        unique = self._filter_low_signal_results(unique, entity_name)
        unique = self._filter_to_review_sources(unique, entity_name)
        unique = self._prioritize_review_results(unique, entity_name)
        if not unique:
            return queries, self._mock_results(entity_name, question), "mock"
        return queries, unique[:result_limit], "live"

    def _filter_to_review_sources(self, items: list[dict], entity_name: str) -> list[dict]:
        filtered: list[dict] = []
        entity_lower = entity_name.lower().strip()
        review_markers = ("評論", "評價", "心得", "推薦", "不推", "好評", "負評", "留言", "reviews", "review", "star", "評分")
        social_hosts = ("facebook.com", "instagram.com", "threads.net", "dcard.tw", "ptt.cc", "google.com", "maps.google.com")
        for item in items:
            url = str(item.get("url") or "").lower()
            title = str(item.get("title") or "").lower()
            text = str(item.get("content") or item.get("snippet") or "").lower()
            haystack = f"{title} {text}"
            host_match = any(marker in url for marker in social_hosts)
            review_match = any(marker in haystack for marker in review_markers)
            entity_match = entity_lower in haystack or entity_lower in url
            has_meaningful_text = len(text.strip()) >= 40 and not any(marker in haystack for marker in EMPTY_CONTENT_MARKERS)
            if host_match and entity_match and has_meaningful_text:
                filtered.append(item)
                continue
            if review_match and entity_match:
                filtered.append(item)
        return filtered or items

    def _prioritize_review_results(self, items: list[dict], entity_name: str) -> list[dict]:
        entity_lower = entity_name.lower().strip()
        review_markers = ("評論", "評價", "心得", "推薦", "不推", "好評", "負評", "留言", "星等", "評分", "review", "reviews")

        def rank(item: dict) -> tuple[int, int, int]:
            url = str(item.get("url") or "").lower()
            title = str(item.get("title") or "").lower()
            text = str(item.get("content") or item.get("snippet") or "").lower()
            source = str(item.get("source") or "").lower()
            haystack = f"{title} {text} {source}"
            platform_bonus = 0
            if "ptt.cc" in url:
                platform_bonus = 5
            elif "google.com/maps" in url or "maps.google" in url:
                platform_bonus = 4
            elif "dcard.tw" in url:
                platform_bonus = 4
            elif any(host in url for host in ("facebook.com", "instagram.com", "threads.net")):
                platform_bonus = 2
            elif "news" in source or "新聞" in source:
                platform_bonus = 1

            review_hits = sum(1 for marker in review_markers if marker in haystack)
            entity_hit = int(entity_lower in haystack or entity_lower in url)
            text_quality = min(len(text.strip()), 500)
            return (entity_hit * 10 + review_hits + platform_bonus, review_hits, text_quality)

        return sorted(items, key=rank, reverse=True)

    async def _search_platform_sources(self, entity_name: str) -> list[dict]:
        tasks = [
            search_ptt(
                entity_name,
                max_results=self._bounded_limit(self.settings.ptt_max_results, default=20, maximum=50),
            ),
            search_google_maps(
                entity_name,
                serpapi_key=self.settings.serpapi_api_key,
                max_results=self._bounded_limit(self.settings.google_maps_max_results, default=20, maximum=50),
            ),
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        merged: list[dict] = []
        for result in results:
            if isinstance(result, Exception):
                logger.warning("Platform search failed: %s", result)
                continue
            merged.extend(result)
        return merged

    def _deduplicate_by_url(self, items: list[dict]) -> list[dict]:
        seen_urls: set[str] = set()
        seen_signatures: set[str] = set()
        unique_items: list[dict] = []
        for item in items:
            url = str(item.get("url") or "").strip()
            title = str(item.get("title") or "").strip().lower()
            host = urlparse(url).netloc.lower()
            signature = f"{host}|{title[:80]}"
            if not url or url in seen_urls or (title and signature in seen_signatures):
                continue
            seen_urls.add(url)
            if title:
                seen_signatures.add(signature)
            unique_items.append(item)
        return unique_items

    def _filter_low_signal_results(self, items: list[dict], entity_name: str) -> list[dict]:
        return [item for item in items if not self._is_low_signal_result(item, entity_name)]

    def _is_low_signal_result(self, item: dict, entity_name: str) -> bool:
        url = str(item.get("url") or "").strip()
        if not url:
            return True

        parsed = urlparse(url)
        host = parsed.netloc.lower()
        path = parsed.path.lower().strip("/")
        title = str(item.get("title") or "").strip().lower()
        text = str(item.get("content") or item.get("snippet") or "").strip().lower()
        combined = f"{title} {text}"
        entity_tokens = [variant.lower() for variant in self._expand_entity_variants(entity_name)]
        entity_match = any(token and (token in combined or token in url.lower()) for token in entity_tokens)
        social_host = any(marker in host for marker in ("facebook.com", "instagram.com", "threads.net"))
        profile_like_path = path.count("/") <= 1 and not any(marker in path for marker in ("posts", "p/", "reel", "videos", "photos"))
        has_meaningful_text = len(text) >= 10 and not any(marker in text for marker in EMPTY_CONTENT_MARKERS)

        if any(marker in combined for marker in LOW_SIGNAL_SOCIAL_MARKERS):
            return True

        if any(marker in url.lower() for marker in ("pttweb.cc", "/search?q=thread", "/bbs/")) and "ptt.cc" not in host:
            return True

        if any(marker in combined for marker in ("文章列表", "精華區", "search?q=thread", "latest all comments")):
            return True

        if "facebook.com" in host and (not path or path in {"login", "pages", "watch", "groups"}):
            return True

        if "instagram.com" in host and (not path or path in {"", "accounts", "explore", "direct"}):
            return True

        if "threads.net" in host and not entity_match and (not path or path in {"", "login"}):
            return True

        if ("facebook.com" in host or "instagram.com" in host or "threads.net" in host) and not entity_match:
            if any(marker in combined for marker in ("privacy", "meta", "sign up", "log in", "login")):
                return True

        if any(marker in combined for marker in ("paint0_linear", "paint1_ra", "userspaceonuse", "stop-color", "fill'url(%23")):
            return True

        if social_host and (profile_like_path or not has_meaningful_text):
            return True

        if "facebook.com" in host and "posts" not in path and "permalink" not in path and "share" not in path:
            return True

        if "youtube.com" in host and any(marker in combined for marker in ("error 403", "that’s an error", "skip navigation")):
            return True

        return False

    async def _enrich_results(
        self,
        items: list[dict],
        client: httpx.AsyncClient,
        cached_sources: dict[str, dict[str, str | None]],
    ) -> list[dict]:
        enrich_limit = self._metadata_enrich_limit()
        semaphore = asyncio.Semaphore(self._metadata_enrich_concurrency())
        remaining_slots = enrich_limit
        tasks: list[asyncio.Task[dict]] = []
        passthrough: list[dict | None] = [None] * len(items)

        async def run(item: dict, cached_source: dict[str, str | None] | None) -> dict:
            async with semaphore:
                return await self._enrich_result(item, client, cached_source=cached_source)

        for index, item in enumerate(items):
            url = str(item.get("url") or "").strip()
            cached_source = cached_sources.get(url)
            hydrated_item = self._merge_cached_source(item, cached_source or {}) if cached_source else dict(item)
            needs_network_enrich = self._needs_network_enrich(hydrated_item)
            if needs_network_enrich and remaining_slots > 0:
                remaining_slots -= 1
                tasks.append(asyncio.create_task(run(item, cached_source)))
                continue
            passthrough[index] = hydrated_item

        if not tasks:
            return [item for item in passthrough if item is not None]

        task_results = await asyncio.gather(*tasks, return_exceptions=True)
        result_iter = iter(task_results)
        final_results: list[dict] = []
        for item in passthrough:
            if item is not None:
                final_results.append(item)
                continue
            task_result = next(result_iter)
            if isinstance(task_result, Exception):
                logger.warning("Result enrichment failed: %s", task_result)
                final_results.append({})
                continue
            final_results.append(task_result)
        return [item for item in final_results if item]

    async def _enrich_result(
        self,
        item: dict,
        client: httpx.AsyncClient,
        cached_source: dict[str, str | None] | None = None,
    ) -> dict:
        enriched = dict(item)
        if cached_source:
            enriched = self._merge_cached_source(enriched, cached_source)

        enriched.setdefault("fetched_at", datetime.now(timezone.utc).isoformat())
        if enriched.get("published_date") and enriched.get("source"):
            return enriched

        url = enriched.get("url")
        if not url:
            return enriched

        has_usable_content = bool((enriched.get("content") or enriched.get("snippet") or "").strip())
        has_usable_title = bool((enriched.get("title") or "").strip())
        if has_usable_content and has_usable_title:
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

    def _needs_network_enrich(self, item: dict) -> bool:
        text = str(item.get("content") or item.get("snippet") or "").strip()
        title = str(item.get("title") or "").strip()
        source = str(item.get("source") or "").strip()
        published_date = str(item.get("published_date") or "").strip()
        return not (len(text) >= 140 and title and source and published_date)

    def _load_cached_sources(self, items: list[dict]) -> dict[str, dict[str, str | None]]:
        if self.persistence_service is None:
            return {}
        urls = [str(item.get("url") or "").strip() for item in items if str(item.get("url") or "").strip()]
        return self.persistence_service.get_sources_by_urls(urls)

    def _merge_cached_source(
        self,
        item: dict,
        cached_source: dict[str, str | None],
    ) -> dict:
        merged = dict(item)
        field_map = {
            "source": "source",
            "source_type": "source_type",
            "author": "author",
            "published_date": "published_date",
            "fetched_at": "fetched_at",
            "title": "title",
            "content": "content",
        }
        for target_field, cache_field in field_map.items():
            if merged.get(target_field):
                continue
            cached_value = cached_source.get(cache_field)
            if cached_value:
                merged[target_field] = cached_value
        return merged

    def _hydrate_cached_sources(self, items: list[dict]) -> list[dict]:
        cached_sources = self._load_cached_sources(items)
        if not cached_sources:
            return items
        return [
            self._merge_cached_source(item, cached_sources.get(str(item.get("url") or "").strip(), {}))
            for item in items
        ]

    def _domain_from_url(self, url: str) -> str:
        parsed = urlparse(url)
        return parsed.netloc or url

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
