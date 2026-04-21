"""Verify a shelter/animal welfare organization exists using OpenAI + Tavily."""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import httpx

try:
    from openai import AsyncOpenAI
except ImportError:  # pragma: no cover
    AsyncOpenAI = None  # type: ignore[assignment]

from app.config import Settings
from app.models.shelter import ShelterCandidate

logger = logging.getLogger(__name__)

TAVILY_ENDPOINT = "https://api.tavily.com/search"

SYSTEM_PROMPT = (
    "你是一位協助核實台灣動物收容單位（狗園、動物之家、私人收容所）的研究員。"
    "使用者會給你一個名稱，你必須使用 web_search 工具找資料，"
    "確認該單位是否真實存在。你必須呼叫 web_search 工具至少一次。"
    "完成調查後，請以單一 JSON 物件回覆，欄位如下：\n"
    "{\n"
    '  "verified": true 或 false,\n'
    '  "canonical_name": 正式名稱 (string),\n'
    '  "entity_type": "公立動物之家" | "私人狗園" | "收容所" | "保護協會" 或其他 (string),\n'
    '  "address": 地址，不確定可留空 (string),\n'
    '  "website": 官網網址 (string),\n'
    '  "facebook_url": Facebook 粉絲頁 (string),\n'
    '  "aliases": 常見別名陣列 (array of string),\n'
    '  "introduction": 一句話介紹，中文，40 字內 (string),\n'
    '  "cover_image_url": 一張能代表這個單位的圖片網址 (string，可留空)。'
    "偏好：官方網站 og:image、Facebook 粉絲頁封面、官方新聞報導內的照片。"
    "不要使用 Google Maps 街景。網址必須是 https:// 開頭，直接能載入的 .jpg/.png/.webp 或可 embed 的 URL,\n"
    '  "evidence_urls": 實際引用來源 URL 陣列 (array of string，至少 1 個),\n'
    '  "reason": 若 verified=false，解釋為何 (string)\n'
    "}\n"
    "只輸出 JSON，不要解釋。若 web_search 找不到任何相關資料，"
    "或找到的資料明顯不是動物收容相關，請回傳 verified=false 並說明原因。"
)

TOOL_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "搜尋網路資料以核實狗園或動物收容組織是否真實存在。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "搜尋字串，例如 '台北市動物之家 地址'",
                    }
                },
                "required": ["query"],
            },
        },
    }
]


class ShelterVerificationService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def is_available(self) -> bool:
        return (
            AsyncOpenAI is not None
            and bool(self.settings.openai_api_key)
            and bool(self.settings.tavily_api_key)
        )

    async def verify(self, query: str) -> tuple[bool, ShelterCandidate | None, str]:
        if not self.is_available():
            return False, None, "verification_unavailable"

        query = query.strip()
        if not query:
            return False, None, "empty_query"

        try:
            raw = await asyncio.wait_for(
                self._run_verification_loop(query),
                timeout=float(self.settings.shelter_verification_timeout_seconds),
            )
        except asyncio.TimeoutError:
            logger.warning("shelter_verification_timeout query=%s", query)
            return False, None, "verification_timeout"
        except Exception as exc:  # noqa: BLE001
            logger.exception("shelter_verification_error query=%s", query)
            return False, None, f"verification_error: {exc.__class__.__name__}"

        if raw is None:
            return False, None, "no_model_response"

        verified = bool(raw.get("verified"))
        canonical_name = str(raw.get("canonical_name") or "").strip()
        evidence_urls = [str(u).strip() for u in (raw.get("evidence_urls") or []) if str(u).strip()]

        if not verified:
            return False, None, str(raw.get("reason") or "model_rejected")

        if not canonical_name:
            return False, None, "missing_canonical_name"

        if not evidence_urls:
            return False, None, "no_evidence_urls"

        import html as _html
        cover_image_url = _html.unescape(str(raw.get("cover_image_url") or "").strip())
        if cover_image_url and not cover_image_url.startswith(("http://", "https://")):
            cover_image_url = ""

        candidate = ShelterCandidate(
            canonical_name=canonical_name,
            entity_type=str(raw.get("entity_type") or "").strip(),
            address=str(raw.get("address") or "").strip(),
            website=str(raw.get("website") or "").strip(),
            facebook_url=str(raw.get("facebook_url") or "").strip(),
            aliases=[
                str(a).strip()
                for a in (raw.get("aliases") or [])
                if str(a).strip() and str(a).strip() != canonical_name
            ],
            introduction=str(raw.get("introduction") or "").strip(),
            cover_image_url=cover_image_url,
            evidence_urls=evidence_urls,
        )
        return True, candidate, ""

    async def _run_verification_loop(self, query: str) -> dict[str, Any] | None:
        client = AsyncOpenAI(
            api_key=self.settings.openai_api_key,
            timeout=float(self.settings.openai_timeout_seconds),
        )
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"請核實這個狗園/收容所：{query}"},
        ]

        max_calls = max(1, int(self.settings.shelter_verification_max_tool_calls))
        tool_calls_made = 0

        async with httpx.AsyncClient(timeout=15.0) as http_client:
            for _ in range(max_calls + 1):
                response = await client.chat.completions.create(
                    model=self.settings.openai_model,
                    messages=messages,
                    tools=TOOL_SCHEMA,
                    tool_choice="auto" if tool_calls_made < max_calls else "none",
                    response_format={"type": "json_object"}
                    if tool_calls_made >= max_calls
                    else None,
                )
                message = response.choices[0].message
                if not message.tool_calls:
                    content = (message.content or "").strip()
                    if not content:
                        return None
                    try:
                        return json.loads(content)
                    except json.JSONDecodeError:
                        logger.warning("shelter_verification_bad_json content=%s", content[:200])
                        return None

                messages.append(
                    {
                        "role": "assistant",
                        "content": message.content or "",
                        "tool_calls": [
                            {
                                "id": tc.id,
                                "type": "function",
                                "function": {
                                    "name": tc.function.name,
                                    "arguments": tc.function.arguments,
                                },
                            }
                            for tc in message.tool_calls
                        ],
                    }
                )

                for tool_call in message.tool_calls:
                    if tool_call.function.name != "web_search":
                        tool_result = json.dumps({"error": "unknown tool"})
                    else:
                        try:
                            args = json.loads(tool_call.function.arguments or "{}")
                        except json.JSONDecodeError:
                            args = {}
                        search_q = str(args.get("query") or "").strip() or query
                        results = await self._tavily_search(http_client, search_q)
                        tool_result = json.dumps(results, ensure_ascii=False)
                        tool_calls_made += 1

                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "content": tool_result,
                        }
                    )

                if tool_calls_made >= max_calls:
                    # On the next iteration tool_choice="none" forces a final answer.
                    continue

        return None

    async def _tavily_search(
        self,
        http_client: httpx.AsyncClient,
        query: str,
    ) -> list[dict[str, Any]]:
        try:
            response = await http_client.post(
                TAVILY_ENDPOINT,
                json={
                    "api_key": self.settings.tavily_api_key,
                    "query": query,
                    "search_depth": "basic",
                    "max_results": 5,
                    "include_answer": False,
                },
            )
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPError as exc:
            logger.warning("tavily_http_error query=%s err=%s", query, exc)
            return []

        results = []
        for item in (data.get("results") or [])[:5]:
            results.append(
                {
                    "title": str(item.get("title") or "")[:200],
                    "url": str(item.get("url") or ""),
                    "snippet": str(item.get("content") or "")[:500],
                }
            )
        return results
