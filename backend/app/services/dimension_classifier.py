"""Classify each review into animal-welfare-relevant dimensions.

Dimensions are INFORMATION CATEGORIES, not ratings. Each review can map to 0, 1,
or multiple dimensions. The platform does NOT aggregate these into an overall
score — that is a deliberate product decision.
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

BATCH_CONCURRENCY = 6
MAX_CONTENT_LENGTH = 600

DIMENSIONS = [
    "staff_attitude",
    "transparency",
    "environment",
    "animal_care",
    "communication",
    "adoption_process",
]

DIMENSION_LABELS = {
    "staff_attitude": "工作人員態度",
    "transparency": "資訊透明度",
    "environment": "環境整潔",
    "animal_care": "照護狀況",
    "communication": "對外溝通",
    "adoption_process": "送養流程",
}

SYSTEM_PROMPT = (
    "你是動物保護組織公信力平台的資訊分類員。使用者會給你一則網路評論，"
    "你要判斷這則評論討論了下列哪些維度，並標記該維度的立場和擷取原文：\n"
    "\n"
    "維度清單：\n"
    "- staff_attitude（工作人員態度）：志工/員工是否友善、專業、回應方式\n"
    "- transparency（資訊透明度）：財務公開、捐款去向、動物現況更新\n"
    "- environment（環境整潔）：欄舍清潔、空間大小、異味\n"
    "- animal_care（照護狀況）：醫療、飲食、運動、精神健康\n"
    "- communication（對外溝通）：回覆速度、客服、訊息更新\n"
    "- adoption_process（送養流程）：申請效率、審核合理度、後續追蹤\n"
    "\n"
    "輸出 JSON 格式：\n"
    '{"tags": [\n'
    '  {"dim": "staff_attitude", "stance": "supporting|opposing|neutral", "excerpt": "原文 30 字內引用"}\n'
    "]}\n"
    "\n"
    "規則：\n"
    "- 一則評論可以 tag 多個維度，也可以完全不 tag（回傳 {\"tags\": []}）\n"
    "- 若評論只是提到組織名但沒描述具體行為/感受，回傳空 tags\n"
    "- excerpt 必須從原文直接擷取，不要改寫\n"
    "- stance：supporting=正面/讚美；opposing=負面/投訴；neutral=中性敘述\n"
    "- 只輸出 JSON，不要其他文字"
)


@dataclass(frozen=True)
class DimensionTag:
    dim: str
    stance: str
    excerpt: str

    def to_dict(self) -> dict[str, str]:
        return {"dim": self.dim, "stance": self.stance, "excerpt": self.excerpt}


class ReviewDimensionClassifier:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def is_available(self) -> bool:
        return AsyncOpenAI is not None and bool(self.settings.openai_api_key)

    async def classify_batch(
        self, reviews: list[dict]
    ) -> list[list[DimensionTag]]:
        if not self.is_available() or not reviews:
            return [[] for _ in reviews]

        client = AsyncOpenAI(
            api_key=self.settings.openai_api_key,
            timeout=float(self.settings.openai_timeout_seconds) * 2,
        )
        semaphore = asyncio.Semaphore(BATCH_CONCURRENCY)

        async def _one(review: dict) -> list[DimensionTag]:
            async with semaphore:
                return await self._classify_one(client, review)

        return await asyncio.gather(*[_one(r) for r in reviews])

    async def _classify_one(
        self, client: Any, review: dict
    ) -> list[DimensionTag]:
        content = str(review.get("content") or "")[:MAX_CONTENT_LENGTH]
        title = str(review.get("parent_title") or "")[:80]
        entity = str(review.get("entity_name") or "")
        platform = str(review.get("platform") or "")

        user_msg = (
            f"組織：{entity}\n"
            f"平台：{platform}\n"
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
                max_tokens=400,
            )
            raw = (response.choices[0].message.content or "").strip()
            data = json.loads(raw)
        except (json.JSONDecodeError, ValueError) as exc:
            logger.warning("dimension parse error: %s", exc)
            return []
        except Exception as exc:  # noqa: BLE001
            logger.warning("dimension api error: %s", exc)
            return []

        tags: list[DimensionTag] = []
        raw_tags = data.get("tags") if isinstance(data, dict) else []
        for t in raw_tags or []:
            if not isinstance(t, dict):
                continue
            dim = str(t.get("dim") or "").strip()
            stance = str(t.get("stance") or "").strip().lower()
            excerpt = str(t.get("excerpt") or "").strip()[:120]
            if dim not in DIMENSIONS:
                continue
            if stance not in ("supporting", "opposing", "neutral"):
                stance = "neutral"
            tags.append(DimensionTag(dim=dim, stance=stance, excerpt=excerpt))
        return tags
