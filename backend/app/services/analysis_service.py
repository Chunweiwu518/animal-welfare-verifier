from __future__ import annotations

from collections import Counter
from typing import Any

try:
    from openai import AsyncOpenAI
except ImportError:  # pragma: no cover
    AsyncOpenAI = None

from app.config import Settings
from app.models.search import BalancedSummary, EvidenceCard


class AnalysisService:
    def __init__(self, settings: Settings):
        self.settings = settings

    async def analyze(
        self,
        entity_name: str,
        question: str,
        raw_results: list[dict[str, Any]],
    ) -> tuple[BalancedSummary, list[EvidenceCard]]:
        cards = [self._to_card(result, question) for result in raw_results]
        if self.settings.openai_api_key and AsyncOpenAI is not None:
            try:
                summary = await self._summarize_with_openai(entity_name, question, cards)
                return summary, cards
            except Exception:
                return self._summarize_heuristically(cards, question), cards
        return self._summarize_heuristically(cards, question), cards

    def _to_card(self, result: dict[str, Any], question: str) -> EvidenceCard:
        text = (
            result.get("content")
            or result.get("raw_content")
            or result.get("snippet")
            or "No snippet available."
        )
        lower = text.lower()

        if any(word in lower for word in ["質疑", "投訴", "爭議", "退款", "不透明", "疑慮"]):
            stance = "supporting"
            evidence_strength = "medium"
        elif any(word in lower for word in ["改善", "澄清", "反駁", "良好", "整潔"]):
            stance = "opposing"
            evidence_strength = "medium"
        else:
            stance = "neutral"
            evidence_strength = "weak"

        claim_type = self._claim_type(question, text)
        first_hand_score = 85 if any(word in text for word in ["實地", "參訪", "親自", "我看到"]) else 40

        return EvidenceCard(
            title=result.get("title") or "Untitled evidence",
            url=result["url"],
            source=result.get("source") or self._source_name(result.get("url", "")),
            snippet=text[:700],
            extracted_at=result.get("fetched_at"),
            published_at=result.get("published_date"),
            stance=stance,
            claim_type=claim_type,
            evidence_strength=evidence_strength,
            first_hand_score=first_hand_score,
            notes=self._notes_for_card(stance, evidence_strength, first_hand_score),
        )

    def _claim_type(self, question: str, text: str) -> str:
        joined = f"{question} {text}"
        if "詐騙" in joined:
            return "fraud"
        if "退款" in joined:
            return "refund"
        if "募資" in joined or "透明" in joined:
            return "fundraising"
        if "動物" in joined or "環境" in joined or "福利" in joined:
            return "animal_welfare"
        return "general_reputation"

    def _notes_for_card(self, stance: str, strength: str, first_hand_score: int) -> str:
        perspective = {
            "supporting": "This source supports the concern raised by the user.",
            "opposing": "This source pushes back on the concern or highlights improvements.",
            "neutral": "This source gives context without clearly taking a side.",
            "unclear": "The stance is ambiguous and needs manual review.",
        }[stance]
        return f"{perspective} Evidence strength is {strength}. First-hand score: {first_hand_score}/100."

    def _source_name(self, url: str) -> str:
        return url.split("/")[2] if "://" in url else "Unknown"

    def _summarize_heuristically(self, cards: list[EvidenceCard], question: str) -> BalancedSummary:
        stances = Counter(card.stance for card in cards)
        supporting = [card.title for card in cards if card.stance == "supporting"][:3]
        opposing = [card.title for card in cards if card.stance == "opposing"][:3]
        neutral = [card.title for card in cards if card.stance in {"neutral", "unclear"}][:3]

        confidence = min(85, 40 + len(cards) * 10)
        if stances["supporting"] > stances["opposing"]:
            verdict = f"目前公開資料對「{question}」有一定支持，但仍需人工複核原文與時間序。"
        elif stances["opposing"] > stances["supporting"]:
            verdict = f"目前公開資料較偏向反駁或淡化「{question}」的疑慮，但不能視為完全排除。"
        else:
            verdict = f"目前公開資料正反並存，對「{question}」尚不足以下定論。"

        return BalancedSummary(
            verdict=verdict,
            confidence=confidence,
            supporting_points=supporting or ["尚未找到足夠明確的支持性來源。"],
            opposing_points=opposing or ["尚未找到足夠明確的反駁來源。"],
            uncertain_points=neutral or ["大多數來源仍偏情緒性或細節不足。"],
            suggested_follow_up=[
                "補抓更近期的新聞與官方聲明",
                "區分第一手描述與轉述內容",
                "人工確認關鍵指控是否有具體時間、地點、金額或影像佐證",
            ],
        )

    async def _summarize_with_openai(
        self,
        entity_name: str,
        question: str,
        cards: list[EvidenceCard],
    ) -> BalancedSummary:
        client = AsyncOpenAI(api_key=self.settings.openai_api_key, timeout=20.0)
        evidence_lines = [
            f"- {card.title} | stance={card.stance} | strength={card.evidence_strength} | snippet={card.snippet}"
            for card in cards[:8]
        ]
        prompt = (
            "你是一個公正的查核助手。請根據以下證據，輸出平衡摘要。"
            "不要直接認定違法，只能描述目前公開資料能支持、反駁、以及無法確認的部分。\n\n"
            f"對象：{entity_name}\n"
            f"問題：{question}\n"
            "證據：\n"
            + "\n".join(evidence_lines)
        )

        response = await client.responses.create(
            model=self.settings.openai_model,
            input=prompt,
        )
        text = response.output_text.strip() or "LLM 未回傳摘要，已改用保守判讀。"
        heuristic = self._summarize_heuristically(cards, question)
        return BalancedSummary(
            verdict=text,
            confidence=min(90, heuristic.confidence + 5),
            supporting_points=heuristic.supporting_points,
            opposing_points=heuristic.opposing_points,
            uncertain_points=heuristic.uncertain_points,
            suggested_follow_up=heuristic.suggested_follow_up,
        )
