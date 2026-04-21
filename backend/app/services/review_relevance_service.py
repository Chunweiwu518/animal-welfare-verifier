"""Batch-analyze reviews via LLM to score relevance, stance, and generate a one-line summary.

For each review we ask gpt-4.1-mini:
  - relevance_score: 0.0-1.0 (是否真的在講這個 entity)
  - stance: supporting / opposing / neutral / unclear
  - short_summary: 30 字內中文摘要

Designed to be idempotent: only processes reviews with analyzed_at IS NULL.
"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Any

try:
    from openai import AsyncOpenAI
except ImportError:  # pragma: no cover
    AsyncOpenAI = None  # type: ignore[assignment]

from app.config import Settings

logger = logging.getLogger(__name__)

BATCH_CONCURRENCY = 8
MAX_CONTENT_LENGTH = 600  # trim long PTT articles to keep token cost bounded

SYSTEM_PROMPT = (
    "你是一位動物福利議題研究員，負責判斷一則網路內容是否真的在討論指定的動物保護組織/狗園。\n"
    "輸出單一 JSON 物件，無多餘文字：\n"
    '{\n'
    '  "relevance_score": 0.0 到 1.0 (0=完全無關, 0.5=提到但非主題, 1.0=主要談論該組織),\n'
    '  "stance": "supporting" | "opposing" | "neutral" | "unclear",\n'
    '  "short_summary": 30 字內中文，一句話說明這則內容講什麼 (可空字串)\n'
    '}\n'
    "規則：\n"
    "- 若內容只是順帶提名稱但主題完全不同 (例如「台大」出現在貓咪咖啡廳介紹)，relevance_score < 0.3\n"
    "- 若內容在讚美/感謝/推薦該組織，stance = supporting\n"
    "- 若內容在投訴/質疑/批評該組織，stance = opposing\n"
    "- 若是該組織自己發的公告/活動/中性新聞，stance = neutral\n"
    "- 若看不出立場，stance = unclear\n"
    "- short_summary 不要 JSON 引號跳脫，直接寫中文即可。不要提組織名稱（重複）"
)


@dataclass(frozen=True)
class ReviewAnalysis:
    relevance_score: float
    stance: str
    short_summary: str

    @classmethod
    def unknown(cls) -> "ReviewAnalysis":
        return cls(relevance_score=0.0, stance="unclear", short_summary="")


class ReviewRelevanceService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def is_available(self) -> bool:
        return AsyncOpenAI is not None and bool(self.settings.openai_api_key)

    async def analyze_batch(
        self,
        entity_name: str,
        reviews: list[dict],
    ) -> list[ReviewAnalysis]:
        """Run analysis over a batch of reviews with limited concurrency."""
        if not self.is_available() or not reviews:
            return [ReviewAnalysis.unknown()] * len(reviews)

        client = AsyncOpenAI(
            api_key=self.settings.openai_api_key,
            timeout=float(self.settings.openai_timeout_seconds) * 2,
        )
        semaphore = asyncio.Semaphore(BATCH_CONCURRENCY)

        async def _one(review: dict) -> ReviewAnalysis:
            async with semaphore:
                return await self._classify_one(client, entity_name, review)

        tasks = [_one(r) for r in reviews]
        return await asyncio.gather(*tasks)

    async def _classify_one(
        self,
        client: Any,
        entity_name: str,
        review: dict,
    ) -> ReviewAnalysis:
        content = str(review.get("content") or "")[:MAX_CONTENT_LENGTH]
        title = str(review.get("parent_title") or "")[:100]
        platform = str(review.get("platform") or "")

        user_msg = (
            f"目標組織：{entity_name}\n"
            f"來源平台：{platform}\n"
            f"標題：{title}\n"
            f"內容：{content}"
        )

        try:
            response = await client.chat.completions.create(
                model=self.settings.openai_model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_msg},
                ],
                response_format={"type": "json_object"},
                max_tokens=200,
            )
            raw = (response.choices[0].message.content or "").strip()
            data = json.loads(raw)
            return ReviewAnalysis(
                relevance_score=float(
                    max(0.0, min(1.0, data.get("relevance_score") or 0.0))
                ),
                stance=str(data.get("stance") or "unclear").strip().lower(),
                short_summary=str(data.get("short_summary") or "").strip()[:80],
            )
        except (json.JSONDecodeError, ValueError, KeyError) as exc:
            logger.warning("review analysis parse error: %s", exc)
            return ReviewAnalysis.unknown()
        except Exception as exc:  # noqa: BLE001
            logger.warning("review analysis API error: %s", exc)
            return ReviewAnalysis.unknown()
