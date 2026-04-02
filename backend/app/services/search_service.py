from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx
from trafilatura.metadata import extract_metadata

from app.config import Settings
from app.models.search import ProviderDiagnostics, SearchDiagnostics
from app.services.crawl4ai_service import Crawl4AIService
from app.services.duckduckgo_service import DuckDuckGoService
from app.services.firecrawl_service import FirecrawlService
from app.services.google_news_rss_service import GoogleNewsRssService
from app.services.persistence_service import PersistenceService
from app.services.serpapi_service import SerpApiService
from app.services.scrapers.google_maps_scraper import search_google_maps
from app.services.scrapers.ptt_scraper import search_ptt

logger = logging.getLogger("uvicorn.error").getChild(__name__)
logger.setLevel(logging.INFO)

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

NO_RESULTS_TEMPLATE_MARKERS = (
    "no results found",
    "the page you requested could not be found",
    "try refining your search",
    "select page",
    "use the navigation above to locate the",
)

FUNDRAISING_MARKERS = (
    "募資",
    "捐款",
    "善款",
    "勸募",
    "公益勸募",
    "財務",
    "透明",
    "經費",
    "款項",
    "flyingv",
)

CONTROVERSY_MARKERS = (
    "爭議",
    "質疑",
    "疑慮",
    "風波",
    "道歉",
    "聲明",
    "澄清",
)

EVIDENCE_MARKERS = (
    "聲明",
    "公告",
    "新聞",
    "報導",
    "facebook",
    "instagram",
    "threads",
    "dcard",
    "ptt",
    "google",
    "maps",
    "募資",
    "捐款",
    "公益勸募",
)

RECENCY_QUESTION_MARKERS = (
    "最近",
    "近期",
    "最新",
    "今天",
    "本週",
    "本月",
    "近況",
    "最近有沒有",
)

AUTHORITATIVE_HOST_MARKERS = (
    "sasw.mohw.gov.tw",
    "mohw.gov.tw",
    ".gov.tw",
    ".gov",
    "dongwangwang.bobo.care",
    "flyingv.cc",
    "donate.newebpay.com",
)

ANIMAL_QUERY_MARKERS = (
    "動保",
    "動保法",
    "動物福利",
    "虐待",
    "棄養",
    "飼養環境",
    "超收",
    "死亡",
    "照護",
    "非法繁殖",
    "收容",
    "救援",
    "絕育",
    "展演",
    "稽查",
    "裁罰",
)

ANIMAL_RELATED_MARKERS = (
    "動物",
    "犬",
    "狗",
    "貓",
    "毛孩",
    "收容",
    "救援",
    "棄養",
    "虐待",
    "受傷",
    "死亡",
    "飼養",
    "籠養",
    "超收",
    "惡臭",
    "環境",
    "照護",
    "醫療",
    "絕育",
    "繁殖",
    "非法繁殖",
    "展演",
    "稽查",
    "裁罰",
    "動保",
    "動保法",
    "動物福利",
)

STRONG_ANIMAL_RELATED_MARKERS = (
    "動保法",
    "動物福利",
    "虐待",
    "棄養",
    "非法繁殖",
    "超收",
    "稽查",
    "裁罰",
    "救援",
    "收容",
    "飼養環境",
)

ANIMAL_EXCLUSION_MARKERS = (
    "購物",
    "商城",
    "票務",
    "排隊",
    "候位",
    "演唱會",
    "活動",
    "娛樂",
    "明星",
    "八卦",
    "旅遊",
    "打卡",
    "美食",
    "展覽",
)

ANIMAL_NEGATION_MARKERS = (
    "與動物無關",
    "沒有提到動物",
    "沒有提到動保",
    "沒有提到動物照護",
    "沒有提到收容",
    "沒有提到飼養",
    "不涉及動保",
    "非動物相關",
)


class SearchService:
    def __init__(self, settings: Settings, persistence_service: PersistenceService | None = None):
        self.settings = settings
        self.persistence_service = persistence_service
        self.google_news_rss_service = GoogleNewsRssService(settings)
        self.duckduckgo_service = DuckDuckGoService(settings)
        self.firecrawl_service = FirecrawlService(settings)
        self.serpapi_service = SerpApiService(settings)
        self.crawl4ai_service = Crawl4AIService(settings)
        self.last_diagnostics = SearchDiagnostics(providers=ProviderDiagnostics())

    def _bounded_limit(self, value: int, *, default: int, minimum: int = 1, maximum: int = 500) -> int:
        if value < minimum:
            return default
        return min(value, maximum)

    def _metadata_enrich_limit(self) -> int:
        return self._bounded_limit(self.settings.metadata_enrich_limit, default=24, maximum=100)

    def _metadata_enrich_concurrency(self) -> int:
        return self._bounded_limit(self.settings.metadata_enrich_concurrency, default=6, maximum=20)

    def _cached_entity_decision(
        self,
        *,
        entity_name: str,
        question: str,
        animal_focus: bool,
        cached_results: list[dict],
    ) -> dict[str, object]:
        if self.persistence_service is None:
            return {
                "use_cached": False,
                "reason": "no_persistence_service",
                "search_mode": "animal_law" if animal_focus else "general",
                "snapshot_found": False,
                "snapshot_source_count": 0,
                "snapshot_age_hours": None,
                "freshness_ttl_hours": None,
            }

        minimum_cached_results = self._bounded_limit(
            self.settings.db_first_min_cached_results,
            default=4,
            maximum=30,
        )
        if len(cached_results) < minimum_cached_results:
            return {
                "use_cached": False,
                "reason": "insufficient_cached_sources",
                "search_mode": "animal_law" if animal_focus else "general",
                "snapshot_found": False,
                "snapshot_source_count": 0,
                "snapshot_age_hours": None,
                "freshness_ttl_hours": None,
            }

        search_mode = "animal_law" if animal_focus else "general"
        snapshot = self.persistence_service.get_entity_summary_snapshot(entity_name, search_mode)
        if snapshot is None:
            return {
                "use_cached": False,
                "reason": "missing_snapshot",
                "search_mode": search_mode,
                "snapshot_found": False,
                "snapshot_source_count": 0,
                "snapshot_age_hours": None,
                "freshness_ttl_hours": None,
            }

        minimum_snapshot_sources = self._bounded_limit(
            self.settings.db_first_min_snapshot_sources,
            default=4,
            maximum=100,
        )
        snapshot_source_count = max(int(snapshot.source_count or 0), len(snapshot.evidence_cards))
        snapshot_age_hours = self._snapshot_age_hours(snapshot.generated_at)
        freshness_ttl_hours = self._bounded_limit(
            self.settings.recency_sensitive_snapshot_ttl_hours,
            default=24,
            maximum=720,
        ) if self._is_recency_sensitive_question(question) else self._bounded_limit(
            self.settings.entity_snapshot_ttl_hours,
            default=72,
            maximum=720,
        )

        if snapshot_source_count < minimum_snapshot_sources:
            return {
                "use_cached": False,
                "reason": "insufficient_snapshot_sources",
                "search_mode": search_mode,
                "snapshot_found": True,
                "snapshot_source_count": snapshot_source_count,
                "snapshot_age_hours": snapshot_age_hours,
                "freshness_ttl_hours": freshness_ttl_hours,
            }
        if snapshot_age_hours is None:
            return {
                "use_cached": False,
                "reason": "snapshot_age_unknown",
                "search_mode": search_mode,
                "snapshot_found": True,
                "snapshot_source_count": snapshot_source_count,
                "snapshot_age_hours": None,
                "freshness_ttl_hours": freshness_ttl_hours,
            }
        if snapshot_age_hours > freshness_ttl_hours:
            return {
                "use_cached": False,
                "reason": "stale_snapshot",
                "search_mode": search_mode,
                "snapshot_found": True,
                "snapshot_source_count": snapshot_source_count,
                "snapshot_age_hours": snapshot_age_hours,
                "freshness_ttl_hours": freshness_ttl_hours,
            }

        return {
            "use_cached": True,
            "reason": "fresh_snapshot",
            "search_mode": search_mode,
            "snapshot_found": True,
            "snapshot_source_count": snapshot_source_count,
            "snapshot_age_hours": snapshot_age_hours,
            "freshness_ttl_hours": freshness_ttl_hours,
        }

    def build_queries(self, entity_name: str, question: str, animal_focus: bool = False) -> list[str]:
        variants = self._expand_entity_variants(entity_name)
        prioritized_templates = self._question_query_templates(question, animal_focus=animal_focus)
        generic_templates = [
            "{base} 爭議",
            "{base} 聲明",
            "{base} 公告",
            "{base} 新聞",
            "{base} 報導",
            "{base} 募資",
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
            "site:flyingv.cc {base}",
            "site:sasw.mohw.gov.tw {base}",
            "\"{base}\" Google 評論",
            "\"{base}\" PTT",
        ]
        candidate_queries: list[str] = []
        primary_variant = variants[0] if variants else entity_name.strip()
        for template in prioritized_templates:
            candidate_queries.append(template.format(base=primary_variant))
        for template in generic_templates:
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
        return self._order_queries_for_recall(unique_queries, question, animal_focus=animal_focus)

    def _expand_entity_variants(self, entity_name: str) -> list[str]:
        base = entity_name.strip()
        variants = [base]
        if base.endswith("狗園"):
            root = base.removesuffix("狗園").strip()
            variants.append(root)
            variants.extend(
                [
                    f"{root}寵物樂園",
                    f"{root}樂園",
                    f"{root}園區",
                ]
            )
        if base.endswith("樂園"):
            root = base.removesuffix("樂園").strip()
            variants.extend([root, f"{root}狗園", f"{root}寵物樂園"])

        seen: set[str] = set()
        ordered: list[str] = []
        for variant in variants:
            value = variant.strip()
            if not value or value in seen:
                continue
            seen.add(value)
            ordered.append(value)
        return ordered[:4]

    def _animal_focus_templates(self) -> list[str]:
        return [
            "{base} 動保",
            "{base} 動保法",
            "{base} 動物福利",
            "{base} 虐待",
            "{base} 棄養",
            "{base} 飼養環境",
            "{base} 超收",
            "{base} 死亡",
            "{base} 照護",
            "{base} 非法繁殖",
            "{base} 收容",
            "{base} 救援",
            "{base} 絕育",
            "{base} 展演",
            "{base} 稽查",
            "{base} 裁罰",
            "site:news {base} 動保",
            "site:ptt.cc/bbs {base} 虐待",
            "site:dcard.tw {base} 動物",
        ]

    def _question_query_templates(self, question: str, animal_focus: bool = False) -> list[str]:
        templates: list[str] = []
        if animal_focus:
            templates.extend(self._animal_focus_templates())
        if self._question_focuses_on_fundraising(question):
            templates.extend(
                [
                    "{base} 募資",
                    "{base} 財務透明",
                    "{base} 捐款",
                    "{base} 公益勸募",
                    "{base} 勸募許可",
                    "{base} 捐款帳號",
                    "{base} 善款",
                    "{base} 聲明",
                    "{base} 道歉",
                    "site:flyingv.cc {base}",
                    "site:sasw.mohw.gov.tw {base}",
                    "site:donate.newebpay.com {base}",
                    "site:bobo.care {base}",
                    "site:facebook.com {base} 聲明",
                ]
            )
            templates.extend(
                [
                    "{base} 爭議",
                    "{base} 質疑",
                    "{base} 新聞",
                    "{base} 報導",
                ]
            )
        if self._question_focuses_on_controversy(question):
            templates.extend(
                [
                    "{base} 爭議",
                    "{base} 質疑",
                    "{base} 聲明",
                    "{base} 澄清",
                    "site:facebook.com {base} 聲明",
                    "site:ptt.cc/bbs {base} 爭議",
                ]
            )
        return templates

    def _order_queries_for_recall(self, queries: list[str], question: str, animal_focus: bool = False) -> list[str]:
        if not queries:
            return []

        grouped: dict[str, list[str]] = {}
        for query in queries:
            grouped.setdefault(self._query_bucket(query, question, animal_focus=animal_focus), []).append(query)

        ordered: list[str] = []
        seen: set[str] = set()
        for bucket, take_count in self._preferred_query_bucket_quotas(question, animal_focus=animal_focus):
            bucket_queries = grouped.get(bucket, [])
            taken = 0
            while bucket_queries and taken < take_count:
                candidate = bucket_queries.pop(0)
                if candidate in seen:
                    continue
                seen.add(candidate)
                ordered.append(candidate)
                taken += 1

        bucket_order = self._preferred_query_bucket_order(question, animal_focus=animal_focus)
        added = True
        while added:
            added = False
            for bucket in bucket_order:
                bucket_queries = grouped.get(bucket, [])
                while bucket_queries:
                    candidate = bucket_queries.pop(0)
                    if candidate in seen:
                        continue
                    seen.add(candidate)
                    ordered.append(candidate)
                    added = True
                    break

        for query in queries:
            if query in seen:
                continue
            seen.add(query)
            ordered.append(query)
        return ordered

    def _preferred_query_bucket_order(self, question: str, animal_focus: bool = False) -> list[str]:
        if animal_focus:
            return ["animal", "controversy", "news", "official", "community", "fundraising", "reviews", "general"]
        if self._question_focuses_on_fundraising(question):
            return ["fundraising", "controversy", "official", "news", "community", "reviews", "general"]
        if self._question_focuses_on_controversy(question):
            return ["controversy", "news", "official", "community", "fundraising", "reviews", "general"]
        return ["reviews", "community", "news", "official", "fundraising", "controversy", "general"]

    def _preferred_query_bucket_quotas(self, question: str, animal_focus: bool = False) -> list[tuple[str, int]]:
        if animal_focus:
            return [
                ("animal", 12),
                ("controversy", 3),
                ("news", 3),
                ("official", 2),
                ("community", 2),
            ]
        if self._question_focuses_on_fundraising(question):
            return [
                ("fundraising", 10),
                ("controversy", 4),
                ("official", 3),
                ("news", 2),
                ("community", 1),
                ("reviews", 1),
            ]
        if self._question_focuses_on_controversy(question):
            return [
                ("controversy", 4),
                ("news", 3),
                ("official", 2),
                ("community", 2),
                ("fundraising", 1),
            ]
        return [
            ("reviews", 3),
            ("community", 3),
            ("news", 2),
            ("official", 2),
        ]

    def _query_bucket(self, query: str, question: str, animal_focus: bool = False) -> str:
        lowered = query.lower()
        if "site:news" in lowered:
            return "news"
        if animal_focus and any(marker in lowered for marker in ANIMAL_QUERY_MARKERS):
            return "animal"
        if any(marker in lowered for marker in ("site:sasw.mohw.gov.tw", "site:donate.newebpay.com", "site:bobo.care")):
            return "official"
        if any(marker in lowered for marker in ("site:flyingv.cc", "公益勸募", "勸募許可", "財務透明", "捐款", "善款", "募資")):
            return "fundraising"
        if any(marker in lowered for marker in ("爭議", "質疑", "道歉", "澄清", "聲明")):
            return "controversy"
        if any(marker in lowered for marker in ("新聞", "報導")):
            return "news"
        if any(marker in lowered for marker in ("site:facebook.com", "site:instagram.com", "site:threads.net", "site:ptt.cc/bbs", "site:dcard.tw", "ptt", "dcard", "facebook", "instagram", "threads")):
            return "community"
        if any(marker in lowered for marker in ("評論", "評價", "心得", "口碑", "google 評論", "推薦", "不推", "好評", "負評")):
            return "reviews"
        return "general"

    def _question_focuses_on_fundraising(self, question: str) -> bool:
        lowered = question.lower()
        return any(marker in lowered for marker in FUNDRAISING_MARKERS)

    def _question_focuses_on_controversy(self, question: str) -> bool:
        lowered = question.lower()
        return any(marker in lowered for marker in CONTROVERSY_MARKERS)

    async def search(
        self,
        entity_name: str,
        question: str,
        animal_focus: bool = False,
        force_live: bool = False,
    ) -> tuple[list[str], list[dict], str, SearchDiagnostics]:
        queries = self.build_queries(entity_name, question, animal_focus=animal_focus)
        result_limit = self._bounded_limit(self.settings.search_result_limit, default=100, maximum=500)
        diagnostics = SearchDiagnostics(
            query_count=len(queries),
            providers=ProviderDiagnostics(),
        )

        cached_results = self._load_cached_entity_sources(entity_name, question, queries, [], animal_focus=animal_focus)
        diagnostics.providers.cached_results = len(cached_results)
        cache_decision = self._cached_entity_decision(
            entity_name=entity_name,
            question=question,
            animal_focus=animal_focus,
            cached_results=cached_results,
        )
        logger.info(
            "entity_cache_decision entity=%s search_mode=%s animal_focus=%s force_live=%s cached_source_count=%s snapshot_found=%s snapshot_source_count=%s snapshot_age_hours=%s freshness_ttl_hours=%s use_cached=%s reason=%s question=%s",
            entity_name,
            cache_decision["search_mode"],
            animal_focus,
            force_live,
            len(cached_results),
            cache_decision["snapshot_found"],
            cache_decision["snapshot_source_count"],
            None if cache_decision["snapshot_age_hours"] is None else round(float(cache_decision["snapshot_age_hours"]), 2),
            cache_decision["freshness_ttl_hours"],
            cache_decision["use_cached"],
            cache_decision["reason"],
            question,
        )

        if not force_live and bool(cache_decision["use_cached"]):
            cached_final_results = await self._finalize_results(
                merged=cached_results,
                entity_name=entity_name,
                question=question,
                animal_focus=animal_focus,
                result_limit=result_limit,
                diagnostics=diagnostics,
            )
            if cached_final_results:
                logger.info(
                    "search_completed entity=%s mode=cached final_results=%s cached_source_count=%s question=%s",
                    entity_name,
                    len(cached_final_results),
                    len(cached_results),
                    question,
                )
                self.last_diagnostics = diagnostics
                return queries, cached_final_results, "cached", diagnostics

        if force_live:
            logger.info(
                "entity_cache_bypassed entity=%s search_mode=%s reason=force_live question=%s",
                entity_name,
                cache_decision["search_mode"],
                question,
            )
        else:
            logger.info(
                "entity_cache_fallback_live entity=%s search_mode=%s cached_source_count=%s reason=%s question=%s",
                entity_name,
                cache_decision["search_mode"],
                len(cached_results),
                cache_decision["reason"],
                question,
            )

        merged = await self._search_query_sources(queries, diagnostics)
        diagnostics.raw_merged_results = len(merged)

        platform_results = await self._search_platform_sources(entity_name)
        diagnostics.providers.platform_results = len(platform_results)
        merged.extend(platform_results)
        merged_urls = {str(item.get("url") or "").strip() for item in merged}
        cached_results = [item for item in cached_results if str(item.get("url") or "").strip() not in merged_urls]
        merged.extend(cached_results)
        diagnostics.raw_merged_results = len(merged)

        if not merged:
            mock_results = self._mock_results(entity_name, question)
            diagnostics.final_results = len(mock_results)
            self.last_diagnostics = diagnostics
            return queries, mock_results, "mock", diagnostics

        final_results = await self._finalize_results(
            merged=merged,
            entity_name=entity_name,
            question=question,
            animal_focus=animal_focus,
            result_limit=result_limit,
            diagnostics=diagnostics,
        )
        if not final_results:
            mock_results = self._mock_results(entity_name, question)
            diagnostics.final_results = len(mock_results)
            logger.info(
                "search_completed entity=%s mode=mock final_results=%s question=%s",
                entity_name,
                len(mock_results),
                question,
            )
            self.last_diagnostics = diagnostics
            return queries, mock_results, "mock", diagnostics
        logger.info(
            "search_completed entity=%s mode=live final_results=%s raw_merged_results=%s cached_source_count=%s question=%s",
            entity_name,
            len(final_results),
            diagnostics.raw_merged_results,
            diagnostics.providers.cached_results,
            question,
        )
        self.last_diagnostics = diagnostics
        return queries, final_results, "live", diagnostics

    async def _finalize_results(
        self,
        *,
        merged: list[dict],
        entity_name: str,
        question: str,
        animal_focus: bool,
        result_limit: int,
        diagnostics: SearchDiagnostics,
    ) -> list[dict]:
        diagnostics.raw_merged_results = len(merged)
        unique = self._deduplicate_by_url(merged)
        diagnostics.deduplicated_results = len(unique)
        unique = self._hydrate_cached_sources(unique)
        unique = self._annotate_source_types(unique, entity_name)
        unique = await self.crawl4ai_service.enrich_results(unique)
        before_low_signal = len(unique)
        unique = self._filter_low_signal_results(unique, entity_name)
        diagnostics.low_signal_filtered = max(0, before_low_signal - len(unique))
        before_relevance = len(unique)
        unique = self._filter_to_relevant_sources(unique, entity_name, question, animal_focus=animal_focus)
        diagnostics.relevance_filtered = max(0, before_relevance - len(unique))
        unique = self._prioritize_evidence_results(unique, entity_name, question, animal_focus=animal_focus)
        diagnostics.prioritized_results = len(unique)
        final_results = unique[:result_limit]
        diagnostics.final_results = len(final_results)
        return final_results

    async def _search_query_sources(self, queries: list[str], diagnostics: SearchDiagnostics | None = None) -> list[dict]:
        merged: list[dict] = []
        google_news_queries = self._select_provider_queries(
            queries,
            limit=self._bounded_limit(self.settings.google_news_rss_query_limit, default=10, maximum=20),
        )
        google_news_results: list[dict] = []
        if google_news_queries:
            try:
                google_news_results = await self.google_news_rss_service.search_reviews(google_news_queries)
            except Exception as exc:
                logger.warning("Google News RSS search failed: %s", exc)
                google_news_results = []
        if diagnostics is not None:
            diagnostics.providers.google_news_rss_results = len(google_news_results)

        merged.extend(google_news_results)

        duckduckgo_queries = self._select_provider_queries(
            queries,
            limit=self._bounded_limit(self.settings.duckduckgo_query_limit, default=12, maximum=24),
        )
        duckduckgo_results: list[dict] = []
        if duckduckgo_queries:
            try:
                duckduckgo_results = await self.duckduckgo_service.search_reviews(duckduckgo_queries)
            except Exception as exc:
                logger.warning("DuckDuckGo search failed: %s", exc)
                duckduckgo_results = []
        if diagnostics is not None:
            diagnostics.providers.duckduckgo_results = len(duckduckgo_results)

        merged.extend(duckduckgo_results)

        firecrawl_results: list[dict] = []
        firecrawl_failed = False
        firecrawl_queries = self._select_provider_queries(
            queries,
            limit=self._bounded_limit(self.settings.firecrawl_primary_query_limit, default=6, maximum=12),
        )
        serpapi_queries = self._select_provider_queries(
            queries,
            limit=self._bounded_limit(self.settings.serpapi_web_query_limit, default=16, maximum=30),
        )

        if self.settings.firecrawl_api_key and firecrawl_queries:
            try:
                firecrawl_results = await self.firecrawl_service.search_reviews(firecrawl_queries)
            except Exception as exc:
                firecrawl_failed = True
                logger.warning("Firecrawl search failed: %s", exc)
                firecrawl_results = []
        if diagnostics is not None:
            diagnostics.providers.firecrawl_results = len(firecrawl_results)

        merged.extend(firecrawl_results)

        should_use_serpapi = bool(self.settings.serpapi_api_key) and (firecrawl_failed or len(firecrawl_results) < 8)
        if should_use_serpapi and serpapi_queries:
            try:
                serpapi_results = await self.serpapi_service.search_reviews(serpapi_queries)
                if diagnostics is not None:
                    diagnostics.providers.serpapi_results = len(serpapi_results)
                merged.extend(serpapi_results)
            except Exception as exc:
                logger.warning("SerpApi web search failed: %s", exc)

        return merged

    def _select_provider_queries(self, queries: list[str], limit: int) -> list[str]:
        normalized_limit = max(1, limit)
        return queries[:normalized_limit]

    def _load_cached_entity_sources(
        self,
        entity_name: str,
        question: str,
        queries: list[str],
        existing_items: list[dict],
        *,
        animal_focus: bool,
    ) -> list[dict]:
        if self.persistence_service is None:
            return []
        limit = self._bounded_limit(self.settings.cached_source_limit, default=12, maximum=30)
        cached_items = self.persistence_service.find_relevant_cached_sources(
            entity_name=entity_name,
            question=question,
            expanded_queries=queries,
            limit=limit,
            search_mode="animal_law" if animal_focus else "general",
        )
        existing_urls = {str(item.get("url") or "").strip() for item in existing_items}
        return [item for item in cached_items if str(item.get("url") or "").strip() not in existing_urls]

    def _is_recency_sensitive_question(self, question: str) -> bool:
        normalized = question.strip().lower()
        return any(marker in normalized for marker in RECENCY_QUESTION_MARKERS)

    def _snapshot_age_hours(self, generated_at: str | None) -> float | None:
        if not generated_at:
            return None

        normalized = generated_at.strip()
        parsed: datetime | None = None
        for candidate in (normalized.replace("Z", "+00:00"), normalized):
            try:
                parsed = datetime.fromisoformat(candidate)
                break
            except ValueError:
                continue

        if parsed is None:
            try:
                parsed = datetime.strptime(normalized, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                return None

        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return max(0.0, (datetime.now(timezone.utc) - parsed.astimezone(timezone.utc)).total_seconds() / 3600)

    def _filter_to_relevant_sources(
        self,
        items: list[dict],
        entity_name: str,
        question: str = "",
        animal_focus: bool = False,
    ) -> list[dict]:
        filtered: list[dict] = []
        entity_tokens = self._entity_tokens(entity_name)
        relaxed_entity_tokens = self._relaxed_entity_tokens(entity_name)
        review_markers = ("評論", "評價", "心得", "推薦", "不推", "好評", "負評", "留言", "reviews", "review", "star", "評分")
        social_hosts = ("facebook.com", "instagram.com", "threads.net", "dcard.tw", "ptt.cc", "google.com", "maps.google.com")
        question_markers = self._question_markers(question, animal_focus=animal_focus)
        trusted_hosts = ("flyingv.cc", "sasw.mohw.gov.tw", "facebook.com", "ptt.cc", "dcard.tw", "threads.net", "instagram.com")
        for item in items:
            url = str(item.get("url") or "").lower()
            title = str(item.get("title") or "").lower()
            text = str(item.get("content") or item.get("snippet") or "").lower()
            source = str(item.get("source") or "").lower()
            matched_query = str(item.get("matched_query") or "").lower()
            haystack = f"{title} {text} {source} {url} {matched_query}"
            host_match = any(marker in url for marker in social_hosts)
            review_match = any(marker in haystack for marker in review_markers)
            entity_match = any(token in haystack or token in url for token in entity_tokens)
            relaxed_entity_match = any(token in haystack for token in relaxed_entity_tokens)
            evidence_match = any(marker in haystack for marker in EVIDENCE_MARKERS)
            question_match = any(marker in haystack for marker in question_markers)
            trusted_host_match = any(marker in url for marker in trusted_hosts)
            has_meaningful_text = len(text.strip()) >= 20 and not any(marker in haystack for marker in EMPTY_CONTENT_MARKERS)
            has_usable_title = len(title.strip()) >= 8
            if animal_focus:
                if self._is_animal_focus_match(
                    haystack=haystack,
                    url=url,
                    entity_match=entity_match,
                    relaxed_entity_match=relaxed_entity_match,
                    question_match=question_match,
                    trusted_host_match=trusted_host_match,
                    has_meaningful_text=has_meaningful_text,
                    has_usable_title=has_usable_title,
                ):
                    filtered.append(item)
                continue
            if host_match and entity_match and has_meaningful_text:
                filtered.append(item)
                continue
            if entity_match and question_match:
                filtered.append(item)
                continue
            if review_match and entity_match:
                filtered.append(item)
                continue
            if trusted_host_match and relaxed_entity_match and question_match and (has_meaningful_text or has_usable_title):
                filtered.append(item)
                continue
            if entity_match and (evidence_match or trusted_host_match) and (has_meaningful_text or has_usable_title):
                filtered.append(item)
        if animal_focus:
            return filtered
        return filtered or items

    def _is_animal_focus_match(
        self,
        *,
        haystack: str,
        url: str,
        entity_match: bool,
        relaxed_entity_match: bool,
        question_match: bool,
        trusted_host_match: bool,
        has_meaningful_text: bool,
        has_usable_title: bool,
    ) -> bool:
        if any(marker in haystack for marker in ANIMAL_NEGATION_MARKERS):
            return False
        animal_hits = sum(1 for marker in ANIMAL_RELATED_MARKERS if marker in haystack)
        strong_animal_hit = any(marker in haystack for marker in STRONG_ANIMAL_RELATED_MARKERS)
        exclusion_hits = sum(1 for marker in ANIMAL_EXCLUSION_MARKERS if marker in haystack)
        if exclusion_hits >= 2 and animal_hits < 2 and not strong_animal_hit:
            return False
        if not (entity_match or relaxed_entity_match):
            return False
        if trusted_host_match and strong_animal_hit and (has_meaningful_text or has_usable_title):
            return True
        if animal_hits >= 2 and (has_meaningful_text or has_usable_title):
            return True
        if strong_animal_hit and question_match and (has_meaningful_text or has_usable_title):
            return True
        return False

    def _prioritize_evidence_results(
        self,
        items: list[dict],
        entity_name: str,
        question: str = "",
        animal_focus: bool = False,
    ) -> list[dict]:
        entity_tokens = self._entity_tokens(entity_name)
        question_markers = self._question_markers(question, animal_focus=animal_focus)
        review_markers = ("評論", "評價", "心得", "推薦", "不推", "好評", "負評", "留言", "星等", "評分", "review", "reviews")
        historical_markers = ("2018", "2017", "道歉", "財務", "透明", "延遲", "聲明", "爭議", "質疑", "募資")

        def rank(item: dict) -> tuple[int, int, int]:
            url = str(item.get("url") or "").lower()
            title = str(item.get("title") or "").lower()
            text = str(item.get("content") or item.get("snippet") or "").lower()
            source = str(item.get("source") or "").lower()
            matched_query = str(item.get("matched_query") or "").lower()
            haystack = f"{title} {text} {source} {url} {matched_query}"
            bucket = self._result_bucket(item)
            platform_bonus = 0
            if any(host in url for host in AUTHORITATIVE_HOST_MARKERS):
                platform_bonus = 8
            elif "ptt.cc" in url:
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
            question_hits = sum(1 for marker in question_markers if marker in haystack)
            evidence_hits = sum(1 for marker in EVIDENCE_MARKERS if marker in haystack)
            authoritative_hits = sum(1 for marker in AUTHORITATIVE_HOST_MARKERS if marker in haystack)
            historical_hits = sum(1 for marker in historical_markers if marker in haystack)
            entity_hit = int(any(token in haystack for token in entity_tokens))
            text_quality = min(len(text.strip()), 500)
            controversy_boost = 0
            animal_boost = 0
            if self._question_focuses_on_fundraising(question) or self._question_focuses_on_controversy(question):
                if bucket in {"news", "forum", "fundraising"}:
                    controversy_boost += 6
                if bucket == "official":
                    controversy_boost -= 5
                controversy_boost += historical_hits * 2
            if animal_focus:
                animal_hits = sum(1 for marker in ANIMAL_RELATED_MARKERS if marker in haystack)
                strong_animal_hits = sum(1 for marker in STRONG_ANIMAL_RELATED_MARKERS if marker in haystack)
                animal_boost = animal_hits + strong_animal_hits * 3
            return (
                entity_hit * 12 + question_hits * 3 + evidence_hits + review_hits + authoritative_hits * 3 + platform_bonus + controversy_boost + animal_boost,
                question_hits + evidence_hits + authoritative_hits + historical_hits + animal_boost,
                text_quality,
            )
        sorted_items = sorted(items, key=rank, reverse=True)
        return self._diversify_ranked_results(sorted_items, question)

    def _annotate_source_types(self, items: list[dict], entity_name: str) -> list[dict]:
        return [self._annotate_source_type(item, entity_name) for item in items]

    def _annotate_source_type(self, item: dict, entity_name: str) -> dict:
        annotated = dict(item)
        if annotated.get("source_type") in {"official", "news", "forum", "social"}:
            return annotated

        url = str(annotated.get("url") or "").lower()
        source = str(annotated.get("source") or "").lower()
        title = str(annotated.get("title") or "").lower()
        entity_tokens = self._entity_tokens(entity_name)
        host = urlparse(url).netloc.lower()

        if any(marker in host for marker in ("gov.tw", ".gov", "official")):
            annotated["source_type"] = "official"
            return annotated
        if any(marker in host for marker in ("facebook.com", "instagram.com", "threads.net", "youtube.com", "tiktok.com")):
            annotated["source_type"] = "social"
            return annotated
        if any(marker in host for marker in ("ptt.cc", "dcard.tw", "mobile01.com", "disp.cc")):
            annotated["source_type"] = "forum"
            return annotated
        if any(marker in f"{host} {source}" for marker in ("news", "ettoday", "yahoo", "udn", "cna", "ltn", "tvbs", "storm")):
            annotated["source_type"] = "news"
            return annotated
        if any(marker in host for marker in ("dongwangwang.bobo.care", "newebpay.com")) and any(token in f"{host} {title}" for token in entity_tokens):
            annotated["source_type"] = "official"
            return annotated
        if "flyingv.cc" in host:
            annotated["source_type"] = "other"
            return annotated

        annotated["source_type"] = "other"
        return annotated

    def _entity_tokens(self, entity_name: str) -> list[str]:
        variants = [variant.lower() for variant in self._expand_entity_variants(entity_name)]
        tokens = [token.lower() for token in entity_name.replace("　", " ").split() if token.strip()]
        ordered: list[str] = []
        seen: set[str] = set()
        for token in variants + tokens:
            normalized = token.strip()
            if len(normalized) < 2 or normalized in seen:
                continue
            seen.add(normalized)
            ordered.append(normalized)
        return ordered

    def _relaxed_entity_tokens(self, entity_name: str) -> list[str]:
        variants = self._expand_entity_variants(entity_name)
        pieces: list[str] = []
        for variant in variants:
            normalized = variant.strip().lower()
            if not normalized:
                continue
            pieces.append(normalized)
            for suffix in ("狗園", "樂園", "園區", "協會", "流浪狗園", "流浪毛小孩生命照護協會"):
                if normalized.endswith(suffix):
                    root = normalized.removesuffix(suffix).strip()
                    if len(root) >= 2:
                        pieces.append(root)

        ordered: list[str] = []
        seen: set[str] = set()
        for piece in pieces:
            if len(piece) < 2 or piece in seen:
                continue
            seen.add(piece)
            ordered.append(piece)
        return ordered

    def _diversify_ranked_results(self, items: list[dict], question: str) -> list[dict]:
        if len(items) <= 3:
            return items

        selected: list[dict] = []
        used_urls: set[str] = set()
        is_controversy_search = self._question_focuses_on_fundraising(question) or self._question_focuses_on_controversy(question)
        per_bucket_limits = {
            "official": 1 if is_controversy_search else 2,
            "news": 2 if is_controversy_search else 2,
            "forum": 2 if is_controversy_search else 2,
            "social": 1 if is_controversy_search else 2,
            "fundraising": 2 if is_controversy_search else 1,
            "other": 1 if is_controversy_search else 2,
        }
        grouped: dict[str, list[dict]] = {}
        for item in items:
            grouped.setdefault(self._result_bucket(item), []).append(item)

        bucket_order = ("news", "forum", "fundraising", "social", "official", "other") if is_controversy_search else ("official", "news", "forum", "social", "fundraising", "other")
        for bucket in bucket_order:
            bucket_items = grouped.get(bucket, [])
            taken = 0
            for item in bucket_items:
                url = str(item.get("url") or "")
                if not url or url in used_urls or taken >= per_bucket_limits.get(bucket, 1):
                    continue
                used_urls.add(url)
                selected.append(item)
                taken += 1

        for item in items:
            url = str(item.get("url") or "")
            if not url or url in used_urls:
                continue
            used_urls.add(url)
            selected.append(item)
        return selected

    def _result_bucket(self, item: dict) -> str:
        source_type = str(item.get("source_type") or "")
        url = str(item.get("url") or "").lower()
        if "flyingv.cc" in url:
            return "fundraising"
        if "donate.newebpay.com" in url:
            return "official"
        if source_type in {"official", "news", "forum", "social"}:
            return source_type
        return "other"

    def _question_markers(self, question: str, animal_focus: bool = False) -> tuple[str, ...]:
        if animal_focus:
            return ANIMAL_QUERY_MARKERS + CONTROVERSY_MARKERS
        if self._question_focuses_on_fundraising(question):
            return FUNDRAISING_MARKERS + CONTROVERSY_MARKERS
        if self._question_focuses_on_controversy(question):
            return CONTROVERSY_MARKERS
        return ()

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

        if any(marker in combined for marker in NO_RESULTS_TEMPLATE_MARKERS):
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
