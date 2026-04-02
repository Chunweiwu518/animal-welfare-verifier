from __future__ import annotations

import asyncio
import base64
import json
import logging
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import quote, urlparse
from xml.etree import ElementTree

import httpx
from bs4 import BeautifulSoup

from app.config import Settings

logger = logging.getLogger(__name__)


class GoogleNewsRssService:
    _BINARY_PREFIX = b"\x08\x13\x22"
    _BINARY_SUFFIX = b"\xd2\x01\x00"

    def __init__(self, settings: Settings):
        self.settings = settings

    async def search_reviews(self, queries: list[str]) -> list[dict[str, Any]]:
        query_limit = max(1, min(self.settings.google_news_rss_query_limit, 20))
        results_per_query = max(1, min(self.settings.google_news_rss_results_per_query, 10))
        timeout_seconds = max(5, self.settings.google_news_rss_timeout_seconds)
        now = datetime.now(timezone.utc).isoformat()
        headers = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"}
        merged: list[dict[str, Any]] = []

        async with httpx.AsyncClient(timeout=float(timeout_seconds), headers=headers, follow_redirects=True) as client:
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
                        logger.warning("Google News RSS search failed: %s", payload)
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
        encoded_query = quote(query, safe="")
        url = f"https://news.google.com/rss/search?q={encoded_query}&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
        response = await client.get(url)
        response.raise_for_status()
        parsed_results = self._parse_feed(response.text, query=query, fetched_at=fetched_at, limit=limit)
        return await self._resolve_google_news_result_urls(client, parsed_results)

    def _parse_feed(self, xml_text: str, *, query: str, fetched_at: str, limit: int) -> list[dict[str, Any]]:
        root = ElementTree.fromstring(xml_text)
        results: list[dict[str, Any]] = []

        for item in root.findall("./channel/item"):
            if len(results) >= limit:
                break

            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            description = (item.findtext("description") or "").strip()
            source_node = item.find("source")
            source_name = (source_node.text or "").strip() if source_node is not None and source_node.text else "Google News"
            published_at = self._normalize_pub_date((item.findtext("pubDate") or "").strip())
            snippet = self._description_to_snippet(description) or title

            if not title or not link:
                continue

            results.append(
                {
                    "url": link,
                    "title": title,
                    "content": snippet,
                    "snippet": snippet,
                    "matched_query": query,
                    "source": source_name or urlparse(link).netloc or "Google News",
                    "source_type": "news",
                    "published_date": published_at,
                    "fetched_at": fetched_at,
                }
            )

        return results

    def _normalize_pub_date(self, raw_value: str) -> str | None:
        if not raw_value:
            return None
        try:
            return parsedate_to_datetime(raw_value).date().isoformat()
        except (TypeError, ValueError, IndexError, OverflowError):
            return None

    def _description_to_snippet(self, raw_value: str) -> str:
        if not raw_value:
            return ""
        soup = BeautifulSoup(raw_value, "html.parser")
        return soup.get_text(" ", strip=True)

    async def _resolve_google_news_result_urls(
        self,
        client: httpx.AsyncClient,
        results: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if not results:
            return results

        payloads = await asyncio.gather(
            *[self._resolve_google_news_url(client, str(item.get("url") or "")) for item in results],
            return_exceptions=True,
        )
        resolved_results: list[dict[str, Any]] = []
        for item, payload in zip(results, payloads, strict=False):
            resolved_url = item.get("url")
            if isinstance(payload, Exception):
                logger.warning("Google News URL decode failed: %s", payload)
            elif isinstance(payload, str) and payload:
                resolved_url = payload
            resolved_results.append({**item, "url": resolved_url})

        return resolved_results

    async def _resolve_google_news_url(self, client: httpx.AsyncClient, url: str) -> str | None:
        normalized = url.strip()
        if not normalized:
            return None
        parsed = urlparse(normalized)
        parts = [part for part in parsed.path.split("/") if part]
        if parsed.netloc != "news.google.com" or len(parts) < 2 or parts[-2] != "articles":
            return normalized

        encoded = parts[-1]
        offline_decoded = self._decode_legacy_encoded_url(encoded)
        if offline_decoded:
            return offline_decoded

        live_decoded = await self._decode_google_news_url_with_batchexecute(client, normalized)
        return live_decoded or normalized

    async def _decode_google_news_url_with_batchexecute(self, client: httpx.AsyncClient, url: str) -> str | None:
        article_response = await client.get(url)
        article_response.raise_for_status()
        payload = self._build_batchexecute_payload(article_response.text)
        if not payload:
            return None

        decode_response = await client.post(
            "https://news.google.com/_/DotsSplashUi/data/batchexecute",
            headers={
                "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
                "Referer": "https://news.google.com/",
            },
            data={"f.req": payload},
        )
        decode_response.raise_for_status()
        return self._parse_batchexecute_response(decode_response.text)

    def _build_batchexecute_payload(self, html_text: str) -> str | None:
        soup = BeautifulSoup(html_text, "html.parser")
        payload_node = soup.select_one("c-wiz[data-p]")
        raw_payload = str(payload_node.get("data-p") or "").strip() if payload_node is not None else ""
        if not raw_payload.startswith("%.@."):
            return None

        try:
            request_payload = json.loads(raw_payload.replace("%.@.", '["garturlreq",', 1))
        except ValueError:
            return None
        if not isinstance(request_payload, list) or len(request_payload) < 8:
            return None

        compact_payload = request_payload[:-6] + request_payload[-2:]
        return json.dumps(
            [[["Fbv4je", json.dumps(compact_payload, ensure_ascii=False), None, "generic"]]],
            ensure_ascii=False,
        )

    def _parse_batchexecute_response(self, raw_text: str) -> str | None:
        normalized = raw_text.lstrip()
        if normalized.startswith(")]}'"):
            normalized = normalized[4:].lstrip()

        try:
            payload = json.loads(normalized)
        except ValueError:
            return None
        if not isinstance(payload, list):
            return None

        for item in payload:
            if not isinstance(item, list) or len(item) < 3 or not isinstance(item[2], str):
                continue
            try:
                nested_payload = json.loads(item[2])
            except ValueError:
                continue
            if (
                isinstance(nested_payload, list)
                and len(nested_payload) >= 2
                and nested_payload[0] == "garturlres"
                and isinstance(nested_payload[1], str)
                and nested_payload[1].startswith("http")
            ):
                return nested_payload[1]

        return None

    def _decode_legacy_encoded_url(self, encoded: str) -> str | None:
        padded = encoded + "=" * (-len(encoded) % 4)
        try:
            raw_bytes = base64.urlsafe_b64decode(padded)
        except (ValueError, TypeError):
            return None

        if raw_bytes.startswith(self._BINARY_PREFIX):
            raw_bytes = raw_bytes[len(self._BINARY_PREFIX):]
        if raw_bytes.endswith(self._BINARY_SUFFIX):
            raw_bytes = raw_bytes[: -len(self._BINARY_SUFFIX)]
        if not raw_bytes:
            return None

        skip = 2 if raw_bytes[0] >= 0x80 and len(raw_bytes) >= 2 else 1
        candidate = raw_bytes[skip:]
        match = re.search(rb"https?://[^\s\x00\xd2]+", candidate)
        if not match:
            return None

        try:
            return match.group(0).decode("utf-8")
        except UnicodeDecodeError:
            return None