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
    "你是一位動物福利議題研究員，負責判斷一則網路內容是否真的在討論指定的動物保護組織/狗園，"
    "並分辨這則內容是第三方評價、還是組織自己發的宣傳/公告/新聞。\n"
    "輸出單一 JSON 物件，無多餘文字：\n"
    '{\n'
    '  "relevance_score": 0.0 到 1.0 (0=完全無關, 0.5=提到但非主題, 1.0=主要談論該組織),\n'
    '  "content_type": "review" | "self_post" | "announcement" | "news" | "unrelated",\n'
    '  "stance": "supporting" | "opposing" | "neutral" | "unclear",\n'
    '  "short_summary": 30 字內中文，一句話說明這則內容講什麼 (可空字串)\n'
    '}\n'
    "規則：\n"
    "- 若內容只是順帶提名稱但主題完全不同 (例如「台大」出現在貓咪咖啡廳介紹)，relevance_score < 0.3，content_type = unrelated\n"
    "- content_type 定義：\n"
    "  * review：第三方使用者/志工/領養人對該組織的評價、心得、抱怨、推薦\n"
    "  * self_post：該組織自己發的貼文（自稱「我們」「本園」「小編」、募款公告、活動宣傳、領養徵求、"
    "宣傳短片或流行梗圖文案、感謝贊助者）\n"
    "  * announcement：公部門或合作方發的公告、通報、稽查結果\n"
    "  * news：新聞媒體報導\n"
    "  * unrelated：無關內容\n"
    "- 判斷 self_post 的訊號：第一人稱自稱、號召捐款/認養、感性文案、影片宣傳台詞、招募志工、活動預告；"
    "即使內容是抱怨狗狗調皮或工作辛苦，只要語氣是「組織自述」就算 self_post，不是 review\n"
    "- 若內容在讚美/感謝/推薦該組織，stance = supporting\n"
    "- 若內容在投訴/質疑/批評該組織，stance = opposing\n"
    "- 若是該組織自己發的公告/活動/中性新聞，stance = neutral\n"
    "- 若看不出立場，stance = unclear\n"
    "- short_summary 不要 JSON 引號跳脫，直接寫中文即可。不要提組織名稱（重複）"
)

VALID_CONTENT_TYPES = {"review", "self_post", "announcement", "news", "unrelated"}


@dataclass(frozen=True)
class ReviewAnalysis:
    relevance_score: float
    stance: str
    short_summary: str
    content_type: str = "review"

    @classmethod
    def unknown(cls) -> "ReviewAnalysis":
        return cls(
            relevance_score=0.0,
            stance="unclear",
            short_summary="",
            content_type="unrelated",
        )


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
                max_tokens=260,
            )
            raw = (response.choices[0].message.content or "").strip()
            data = json.loads(raw)
            content_type = str(data.get("content_type") or "review").strip().lower()
            if content_type not in VALID_CONTENT_TYPES:
                content_type = "review"
            return ReviewAnalysis(
                relevance_score=float(
                    max(0.0, min(1.0, data.get("relevance_score") or 0.0))
                ),
                stance=str(data.get("stance") or "unclear").strip().lower(),
                short_summary=str(data.get("short_summary") or "").strip()[:80],
                content_type=content_type,
            )
        except (json.JSONDecodeError, ValueError, KeyError) as exc:
            logger.warning("review analysis parse error: %s", exc)
            return ReviewAnalysis.unknown()
        except Exception as exc:  # noqa: BLE001
            logger.warning("review analysis API error: %s", exc)
            return ReviewAnalysis.unknown()
