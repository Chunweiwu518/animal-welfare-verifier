from __future__ import annotations

from collections import Counter
from datetime import date, datetime
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
        cards = [self._to_card(result, entity_name, question) for result in raw_results]
        cards = self._rank_and_filter_cards(cards)
        if self.settings.openai_api_key and AsyncOpenAI is not None:
            try:
                summary = await self._summarize_with_openai(entity_name, question, cards)
                return summary, cards
            except Exception:
                return self._summarize_heuristically(cards, question), cards
        return self._summarize_heuristically(cards, question), cards

    def _to_card(self, result: dict[str, Any], entity_name: str, question: str) -> EvidenceCard:
        text = (
            result.get("content")
            or result.get("raw_content")
            or result.get("snippet")
            or "目前沒有可用的摘要內容。"
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
        source = result.get("source") or self._source_name(result.get("url", ""))
        source_type = self._source_type(result.get("url", ""), result.get("source"))
        published_at = result.get("published_date")
        first_hand_score = 85 if any(word in text for word in ["實地", "參訪", "親自", "我看到"]) else 40
        relevance_score = self._relevance_score(entity_name, question, result.get("title") or "", text)
        recency_label = self._recency_label(published_at)
        duplicate_risk = self._duplicate_risk(result.get("url", ""), result.get("title") or "")
        credibility_score = self._credibility_score(
            source_type=source_type,
            first_hand_score=first_hand_score,
            relevance_score=relevance_score,
            recency_label=recency_label,
            duplicate_risk=duplicate_risk,
        )

        return EvidenceCard(
            title=result.get("title") or "未命名來源",
            url=result["url"],
            source=source,
            source_type=source_type,
            snippet=text[:700],
            extracted_at=result.get("fetched_at"),
            published_at=published_at,
            stance=stance,
            claim_type=claim_type,
            evidence_strength=evidence_strength,
            first_hand_score=first_hand_score,
            relevance_score=relevance_score,
            credibility_score=credibility_score,
            recency_label=recency_label,
            duplicate_risk=duplicate_risk,
            notes=self._notes_for_card(
                stance=stance,
                strength=evidence_strength,
                first_hand_score=first_hand_score,
                credibility_score=credibility_score,
                relevance_score=relevance_score,
                recency_label=recency_label,
                duplicate_risk=duplicate_risk,
            ),
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

    def _notes_for_card(
        self,
        stance: str,
        strength: str,
        first_hand_score: int,
        credibility_score: int,
        relevance_score: int,
        recency_label: str,
        duplicate_risk: str,
    ) -> str:
        perspective = {
            "supporting": "這則來源內容較支持使用者提出的疑慮。",
            "opposing": "這則來源內容較偏向反駁疑慮，或提到改善與回應。",
            "neutral": "這則來源主要提供背景資訊，沒有明確站在某一邊。",
            "unclear": "這則來源立場不夠清楚，建議人工再讀原文確認。",
        }[stance]
        strength_label = {
            "weak": "弱",
            "medium": "中",
            "strong": "強",
        }[strength]
        recency_text = {
            "recent": "近期",
            "dated": "較舊",
            "unknown": "時間未知",
        }[recency_label]
        duplicate_text = {
            "low": "低",
            "medium": "中",
            "high": "高",
        }[duplicate_risk]
        return (
            f"{perspective} 證據強度為{strength_label}，第一手程度為 {first_hand_score}/100，"
            f"相關性 {relevance_score}/100，可信度 {credibility_score}/100，"
            f"時間判讀為{recency_text}，重複轉載風險為{duplicate_text}。"
        )

    def _source_name(self, url: str) -> str:
        return url.split("/")[2] if "://" in url else "未知來源"

    def _source_type(self, url: str, source: str | None) -> str:
        host = (source or self._source_name(url)).lower()

        official_markers = [
            ".gov",
            ".gov.tw",
            ".edu",
            ".org.tw",
            "official",
            "zoo.gov.taipei",
        ]
        news_markers = [
            "news",
            "ettoday",
            "yahoo",
            "ltn",
            "udn",
            "cna",
            "newslens",
            "chinatimes",
            "cts",
            "tvbs",
            "storm",
        ]
        forum_markers = [
            "ptt",
            "dcard",
            "mobile01",
            "forum",
            "disp",
        ]
        social_markers = [
            "facebook",
            "instagram",
            "threads.net",
            "x.com",
            "twitter",
            "youtube",
            "tiktok",
            "line.me",
        ]

        if any(marker in host for marker in official_markers):
            return "official"
        if any(marker in host for marker in news_markers):
            return "news"
        if any(marker in host for marker in forum_markers):
            return "forum"
        if any(marker in host for marker in social_markers):
            return "social"
        return "other"

    def _relevance_score(self, entity_name: str, question: str, title: str, text: str) -> int:
        haystack = f"{title} {text}".lower()
        entity_tokens = [token.lower() for token in entity_name.replace("　", " ").split() if token.strip()]
        if not entity_tokens:
            entity_tokens = [entity_name.lower()]

        question_keywords = [
            keyword
            for keyword in ["詐騙", "退款", "爭議", "動物", "福利", "募資", "透明", "環境", "評價"]
            if keyword in question
        ]

        score = 20
        if any(token and token in haystack for token in entity_tokens):
            score += 35
        if entity_name.lower() in haystack:
            score += 20
        score += min(25, sum(8 for keyword in question_keywords if keyword.lower() in haystack))
        if "search?" in haystack or "prequalify" in haystack or "credit card" in haystack:
            score -= 35
        return max(0, min(100, score))

    def _recency_label(self, published_at: str | None) -> str:
        if not published_at:
            return "unknown"

        raw = published_at.split("T")[0]
        try:
            published_date = date.fromisoformat(raw)
        except ValueError:
            try:
                published_date = datetime.fromisoformat(published_at.replace("Z", "+00:00")).date()
            except ValueError:
                return "unknown"

        days_old = (date.today() - published_date).days
        if days_old <= 365:
            return "recent"
        return "dated"

    def _duplicate_risk(self, url: str, title: str) -> str:
        normalized = f"{url} {title}".lower()
        if any(marker in normalized for marker in ["yahoo.com", "msn.com", "line.today"]):
            return "high"
        if any(marker in normalized for marker in ["news", "rss", "xml"]):
            return "medium"
        return "low"

    def _credibility_score(
        self,
        source_type: str,
        first_hand_score: int,
        relevance_score: int,
        recency_label: str,
        duplicate_risk: str,
    ) -> int:
        base = {
            "official": 78,
            "news": 68,
            "forum": 48,
            "social": 42,
            "other": 36,
        }[source_type]
        recency_bonus = {"recent": 8, "dated": 0, "unknown": -4}[recency_label]
        duplicate_penalty = {"low": 0, "medium": -6, "high": -12}[duplicate_risk]
        score = base + recency_bonus + duplicate_penalty + round(first_hand_score * 0.12) + round(relevance_score * 0.18)
        return max(0, min(100, score))

    def _rank_and_filter_cards(self, cards: list[EvidenceCard]) -> list[EvidenceCard]:
        sorted_cards = sorted(
            cards,
            key=lambda card: (card.relevance_score, card.credibility_score, card.first_hand_score),
            reverse=True,
        )
        filtered_cards = [card for card in sorted_cards if card.relevance_score >= 35]
        if filtered_cards:
            return filtered_cards[:10]
        return sorted_cards[:5]

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
