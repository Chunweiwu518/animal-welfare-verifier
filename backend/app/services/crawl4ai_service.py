from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlparse

from app.config import Settings

logger = logging.getLogger(__name__)


class Crawl4AIService:
    def __init__(self, settings: Settings):
        self.settings = settings

    async def fetch_pages(self, urls: list[str]) -> dict[str, dict[str, Any]]:
        normalized_urls = [str(url).strip() for url in urls if str(url).strip()]
        if not normalized_urls or not self.settings.crawl4ai_enabled:
            return {}
        return await self._crawl_urls(normalized_urls)

    async def enrich_results(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not self.settings.crawl4ai_enabled:
            return items

        target_indexes = self._select_target_indexes(items)
        if not target_indexes:
            return items

        urls = [str(items[index].get("url") or "").strip() for index in target_indexes]
        results_by_url = await self._crawl_urls(urls)
        if not results_by_url:
            return items

        enriched_items: list[dict[str, Any]] = []
        for index, item in enumerate(items):
            if index not in target_indexes:
                enriched_items.append(item)
                continue
            url = str(item.get("url") or "").strip()
            crawl_result = results_by_url.get(url)
            if not crawl_result:
                enriched_items.append(item)
                continue
            enriched_items.append(self._merge_crawl_result(item, crawl_result))
        return enriched_items

    def _select_target_indexes(self, items: list[dict[str, Any]]) -> set[int]:
        limit = max(1, min(self.settings.crawl4ai_url_limit, 30))
        selected: set[int] = set()
        for index, item in enumerate(items):
            url = str(item.get("url") or "").strip()
            if not url or not self._should_crawl_url(url):
                continue
            text = str(item.get("content") or item.get("snippet") or "").strip()
            source_type = str(item.get("source_type") or "")
            if len(text) >= 1200 and source_type in {"official", "news"}:
                continue
            selected.add(index)
            if len(selected) >= limit:
                break
        return selected

    async def _crawl_urls(self, urls: list[str]) -> dict[str, dict[str, Any]]:
        try:
            from crawl4ai import AsyncWebCrawler, BrowserConfig, CacheMode, CrawlerRunConfig
        except Exception as exc:
            logger.warning("Crawl4AI local import failed: %s", exc)
            return {}

        run_config = CrawlerRunConfig(
            cache_mode=CacheMode.BYPASS,
            verbose=False,
            page_timeout=max(1, int(self.settings.crawl4ai_timeout_seconds)) * 1000,
            remove_overlay_elements=True,
            remove_consent_popups=True,
            simulate_user=True,
        )
        browser_config = BrowserConfig(headless=True, verbose=False)

        parsed_results: dict[str, dict[str, Any]] = {}
        try:
            async with AsyncWebCrawler(config=browser_config) as crawler:
                results = await crawler.arun_many(urls=urls, config=run_config)
                for result in results:
                    normalized = self._normalize_crawl_result(result)
                    if not normalized:
                        continue
                    url = str(normalized.get("url") or "").strip()
                    if not url:
                        continue
                    parsed_results[url] = normalized
        except Exception as exc:
            logger.warning("Crawl4AI local crawl failed: %s", exc)
            return {}

        return parsed_results

    def _normalize_crawl_result(self, result: Any) -> dict[str, Any]:
        if result is None:
            return {}
        if isinstance(result, dict):
            return result

        model_dump = getattr(result, "model_dump", None)
        if callable(model_dump):
            dumped = model_dump()
            return dumped if isinstance(dumped, dict) else {}

        as_dict = getattr(result, "dict", None)
        if callable(as_dict):
            dumped = as_dict()
            return dumped if isinstance(dumped, dict) else {}

        return {}

    def _merge_crawl_result(self, item: dict[str, Any], crawl_result: dict[str, Any]) -> dict[str, Any]:
        merged = dict(item)
        markdown = crawl_result.get("markdown")
        title = self._extract_title(crawl_result)
        content = self._extract_markdown(markdown) or self._extract_text(crawl_result)

        if title and len(title.strip()) >= 4:
            merged["title"] = title.strip()
        if content and len(content.strip()) >= 20:
            merged["content"] = content.strip()
            merged["snippet"] = content.strip()[:700]
        if crawl_result.get("success") is False:
            merged.setdefault("crawl_status", "failed")
        else:
            merged["crawl_status"] = "ok"
        return merged

    def _extract_markdown(self, markdown: Any) -> str:
        if isinstance(markdown, str):
            return markdown
        if isinstance(markdown, dict):
            for key in ("fit_markdown", "raw_markdown", "markdown"):
                value = markdown.get(key)
                if isinstance(value, str) and value.strip():
                    return value
        return ""

    def _extract_text(self, crawl_result: dict[str, Any]) -> str:
        for key in ("cleaned_html", "html", "text"):
            value = crawl_result.get(key)
            if isinstance(value, str) and value.strip():
                return value
        return ""

    def _extract_title(self, crawl_result: dict[str, Any]) -> str:
        metadata = crawl_result.get("metadata")
        if isinstance(metadata, dict):
            for key in ("title", "og:title", "twitter:title"):
                value = metadata.get(key)
                if isinstance(value, str) and value.strip():
                    return value
        title = crawl_result.get("title")
        return title if isinstance(title, str) else ""

    def _should_crawl_url(self, url: str) -> bool:
        host = urlparse(url).netloc.lower()
        return any(
            marker in host
            for marker in (
                "dcard.tw",
                "facebook.com",
                "m.facebook.com",
                "threads.net",
                "instagram.com",
                "ptt.cc",
                "bobo.care",
                "flyingv.cc",
                "newebpay.com",
                "news.",
            )
        )
