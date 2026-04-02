from __future__ import annotations

import inspect
import logging
import re
from html import unescape
from typing import Any, Awaitable, Callable
from urllib.parse import urljoin, urlparse

import httpx

from app.config import Settings
from app.models.profile import EntityPageImageItem
from app.services.crawl4ai_service import Crawl4AIService
from app.services.persistence_service import PersistenceService

logger = logging.getLogger(__name__)


class OfficialImageService:
    def __init__(
        self,
        settings: Settings,
        *,
        persistence_service: PersistenceService | None = None,
        crawl_service: Crawl4AIService | Any | None = None,
        image_url_checker: Callable[[str], bool | Awaitable[bool]] | None = None,
    ) -> None:
        self.settings = settings
        self.persistence_service = persistence_service or PersistenceService(settings)
        self.crawl_service = crawl_service or Crawl4AIService(settings)
        self.image_url_checker = image_url_checker or self._is_reachable_image_url

    async def refresh_entity_page_images(self, entity_name: str, raw_results: list[dict[str, Any]]) -> None:
        official_urls = self._select_official_urls(raw_results)
        if not official_urls:
            return

        try:
            page_results = await self.crawl_service.fetch_pages(official_urls)
        except Exception as exc:  # pragma: no cover - defensive logging path
            logger.warning("Official image crawl failed for %s: %s", entity_name, exc)
            return

        if not page_results:
            return

        headline, introduction = self._build_page_copy(entity_name, official_urls, page_results)
        gallery = await self._filter_reachable_images(self._build_gallery(official_urls, page_results))
        if not gallery and not headline and not introduction:
            return

        self.persistence_service.upsert_entity_page_images(
            entity_name=entity_name,
            cover_image_url=gallery[0].url if gallery else "",
            cover_image_alt=gallery[0].alt_text if gallery else "",
            gallery=gallery,
            headline=headline,
            introduction=introduction,
            replace_gallery=True,
        )

    def _select_official_urls(self, raw_results: list[dict[str, Any]]) -> list[str]:
        urls: list[str] = []
        seen: set[str] = set()
        for item in raw_results:
            if str(item.get("source_type") or "") != "official":
                continue
            url = str(item.get("url") or "").strip()
            if not url or url in seen:
                continue
            seen.add(url)
            urls.append(url)
            if len(urls) >= 3:
                break
        return urls

    def _build_gallery(
        self,
        official_urls: list[str],
        page_results: dict[str, dict[str, Any]],
    ) -> list[EntityPageImageItem]:
        items: list[EntityPageImageItem] = []
        seen: set[str] = set()

        for source_url in official_urls:
            crawl_result = page_results.get(source_url)
            if not crawl_result:
                continue
            page_title = self._extract_page_title(crawl_result)
            for image in self._extract_image_candidates(source_url, crawl_result, page_title):
                normalized = image.url.strip()
                if not normalized or normalized in seen:
                    continue
                seen.add(normalized)
                items.append(image)
                if len(items) >= 6:
                    return items
        return items

    def _build_page_copy(
        self,
        entity_name: str,
        official_urls: list[str],
        page_results: dict[str, dict[str, Any]],
    ) -> tuple[str, str]:
        for source_url in official_urls:
            crawl_result = page_results.get(source_url)
            if not crawl_result:
                continue
            headline = self._extract_page_title(crawl_result)
            introduction = self._extract_page_description(crawl_result)
            if headline or introduction:
                cleaned_headline = headline.strip() or f"{entity_name} 官方資料頁"
                cleaned_intro = introduction.strip()
                if cleaned_intro:
                    return cleaned_headline[:120], cleaned_intro[:320]
                return cleaned_headline[:120], ""
        return "", ""

    async def _filter_reachable_images(self, candidates: list[EntityPageImageItem]) -> list[EntityPageImageItem]:
        accepted: list[EntityPageImageItem] = []
        seen: set[str] = set()
        for item in candidates:
            normalized_url = item.url.strip()
            if not normalized_url or normalized_url in seen:
                continue
            if await self._check_image_url(normalized_url):
                seen.add(normalized_url)
                accepted.append(item)
            if len(accepted) >= 6:
                break
        return accepted

    async def _check_image_url(self, image_url: str) -> bool:
        result = self.image_url_checker(image_url)
        if inspect.isawaitable(result):
            result = await result
        return bool(result)

    def _extract_image_candidates(
        self,
        source_url: str,
        crawl_result: dict[str, Any],
        page_title: str,
    ) -> list[EntityPageImageItem]:
        metadata = crawl_result.get("metadata") if isinstance(crawl_result.get("metadata"), dict) else {}
        html = self._extract_html(crawl_result)
        candidates: list[EntityPageImageItem] = []

        meta_urls = [
            self._normalize_image_url(source_url, str(metadata.get(key) or ""))
            for key in ("og:image", "og:image:url", "twitter:image", "image")
        ]
        if html:
            meta_urls.extend(self._extract_meta_image_urls(source_url, html))
        for url in meta_urls:
            if self._is_usable_image_url(url):
                candidates.append(
                    EntityPageImageItem(
                        url=url,
                        alt_text=page_title,
                        caption=f"自動擷取自官方頁：{page_title}" if page_title else "自動擷取自官方頁",
                        source_page_url=source_url,
                    )
                )

        if html:
            candidates.extend(self._extract_img_tag_candidates(source_url, html, page_title))
        return candidates

    def _extract_page_title(self, crawl_result: dict[str, Any]) -> str:
        metadata = crawl_result.get("metadata") if isinstance(crawl_result.get("metadata"), dict) else {}
        for key in ("title", "og:title", "twitter:title"):
            value = str(metadata.get(key) or "").strip()
            if value:
                return value
        return str(crawl_result.get("title") or "").strip()

    def _extract_page_description(self, crawl_result: dict[str, Any]) -> str:
        metadata = crawl_result.get("metadata") if isinstance(crawl_result.get("metadata"), dict) else {}
        for key in ("description", "og:description", "twitter:description"):
            value = self._normalize_text(str(metadata.get(key) or ""))
            if len(value) >= 20:
                return value

        html = self._extract_html(crawl_result)
        html_description = self._extract_meta_description(html)
        if len(html_description) >= 20:
            return html_description

        for candidate in (
            self._extract_markdown_text(crawl_result.get("markdown")),
            self._normalize_text(crawl_result.get("text") if isinstance(crawl_result.get("text"), str) else ""),
            self._normalize_text(html),
        ):
            if len(candidate) >= 20:
                return candidate[:320]
        return ""

    def _extract_html(self, crawl_result: dict[str, Any]) -> str:
        for key in ("cleaned_html", "html"):
            value = crawl_result.get(key)
            if isinstance(value, str) and value.strip():
                return value
        return ""

    def _extract_markdown_text(self, markdown: Any) -> str:
        if isinstance(markdown, str):
            return self._normalize_text(markdown)
        if isinstance(markdown, dict):
            for key in ("fit_markdown", "raw_markdown", "markdown"):
                value = markdown.get(key)
                if isinstance(value, str) and value.strip():
                    return self._normalize_text(value)
        return ""

    def _extract_meta_description(self, html: str) -> str:
        if not html:
            return ""
        matches = re.findall(
            r"<meta[^>]+(?:property|name)=['\"](?:description|og:description|twitter:description)['\"][^>]+content=['\"]([^'\"]+)['\"]",
            html,
            flags=re.IGNORECASE,
        )
        for match in matches:
            value = self._normalize_text(match)
            if value:
                return value
        return ""

    def _extract_meta_image_urls(self, source_url: str, html: str) -> list[str]:
        matches = re.findall(
            r"<meta[^>]+(?:property|name)=['\"](?:og:image|og:image:url|twitter:image|image)['\"][^>]+content=['\"]([^'\"]+)['\"]",
            html,
            flags=re.IGNORECASE,
        )
        return [self._normalize_image_url(source_url, match) for match in matches]

    def _extract_img_tag_candidates(self, source_url: str, html: str, page_title: str) -> list[EntityPageImageItem]:
        items: list[EntityPageImageItem] = []
        for tag in re.findall(r"<img\b[^>]*>", html, flags=re.IGNORECASE):
            src_match = re.search(r"\bsrc=['\"]([^'\"]+)['\"]", tag, flags=re.IGNORECASE)
            if not src_match:
                continue
            image_url = self._normalize_image_url(source_url, src_match.group(1))
            if not self._is_usable_image_url(image_url):
                continue
            alt_match = re.search(r"\balt=['\"]([^'\"]*)['\"]", tag, flags=re.IGNORECASE)
            alt_text = alt_match.group(1).strip() if alt_match else page_title
            items.append(
                EntityPageImageItem(
                    url=image_url,
                    alt_text=alt_text,
                    caption=f"自動擷取自官方頁：{page_title}" if page_title else "自動擷取自官方頁",
                    source_page_url=source_url,
                )
            )
        return items

    def _normalize_image_url(self, source_url: str, candidate_url: str) -> str:
        normalized = candidate_url.strip()
        if not normalized:
            return ""
        return urljoin(source_url, normalized)

    async def _is_reachable_image_url(self, image_url: str) -> bool:
        timeout_seconds = float(max(2, min(self.settings.crawl4ai_timeout_seconds, 8)))
        headers = {
            "User-Agent": "Mozilla/5.0 (compatible; AnimalWelfareVerifier/1.0)",
            "Accept": "image/*,*/*;q=0.8",
        }
        try:
            async with httpx.AsyncClient(timeout=timeout_seconds, follow_redirects=True, headers=headers) as client:
                head_response = await client.head(image_url)
                if self._is_successful_image_response(head_response, image_url):
                    return True
                if head_response.status_code not in {405, 501}:
                    return False

                get_response = await client.get(image_url, headers={**headers, "Range": "bytes=0-0"})
                return self._is_successful_image_response(get_response, image_url)
        except Exception:
            return False

    def _is_successful_image_response(self, response: httpx.Response, image_url: str) -> bool:
        if response.status_code >= 400:
            return False
        content_type = str(response.headers.get("content-type") or "").lower()
        if content_type.startswith("image/"):
            return True
        path = urlparse(image_url).path.lower()
        return path.endswith((".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".heic", ".avif"))

    def _is_usable_image_url(self, image_url: str) -> bool:
        normalized = image_url.strip().lower()
        if not normalized or normalized.startswith("data:"):
            return False
        parsed = urlparse(normalized)
        if parsed.scheme not in {"http", "https"}:
            return False
        if any(marker in parsed.path for marker in ("favicon", "sprite", "avatar", "icon", "logo")):
            return False
        if normalized.endswith(".svg"):
            return False
        return True

    def _normalize_text(self, raw_text: str) -> str:
        if not raw_text:
            return ""
        text = re.sub(r"<script\b[^>]*>.*?</script>", " ", raw_text, flags=re.IGNORECASE | re.DOTALL)
        text = re.sub(r"<style\b[^>]*>.*?</style>", " ", text, flags=re.IGNORECASE | re.DOTALL)
        text = re.sub(r"<[^>]+>", " ", text)
        text = unescape(text)
        text = re.sub(r"[#*_>`\-]+", " ", text)
        text = re.sub(r"\s+", " ", text)
        return text.strip()