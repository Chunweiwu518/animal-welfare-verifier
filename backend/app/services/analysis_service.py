from __future__ import annotations

import html
import json
import re
import unicodedata
from datetime import date, datetime
from typing import Any

try:
    from openai import AsyncOpenAI
except ImportError:  # pragma: no cover
    AsyncOpenAI = None

from app.config import Settings
from app.models.search import AnalysisDiagnostics, BalancedSummary, EvidenceCard


# ── 文字清洗工具 ──────────────────────────────────────────────

_RE_SVG_BLOCK = re.compile(r"<svg[\s\S]*?</svg>", re.IGNORECASE)
_RE_HTML_TAG = re.compile(r"<[^>]{1,500}>")
_RE_URL_ENCODED = re.compile(r"(%[0-9A-Fa-f]{2}){3,}")
_RE_CSS_BLOCK = re.compile(r"\{[^}]*:[^}]*\}")
_RE_DATA_URI = re.compile(r"data:[a-zA-Z/+]+;base64,[A-Za-z0-9+/=]+")
_RE_MULTI_SPACE = re.compile(r"\s{2,}")
_RE_JS_BLOCK = re.compile(r"(function\s*\([^)]*\)\s*\{[^}]*\}|var\s+\w+\s*=)")
_RE_URL = re.compile(r"https?://[^\s]+")
_RE_MARKDOWN_LINK = re.compile(r"\[[^\]]+\]\([^)]+\)")
_RE_BRACKET_NOISE = re.compile(r"[\[\]{}<>|`~^]+")
_RE_SYMBOL_RUN = re.compile(r"[=_*#@+\-]{4,}")
_RE_NON_TEXT_SEPARATORS = re.compile(r"[\u200b-\u200f\u202a-\u202e\ufeff]")
_RE_REPLACEMENT_CHAR = re.compile(r"\ufffd+")
_RE_GARBLED_PUNCT = re.compile(r"[˙•◆■□▪︎]{2,}")
_RE_BROKEN_ENDING = re.compile(r"[一-龥A-Za-z0-9]{1,3}[�…]+$")
# SVG coordinate sequences: digits, dots, letters like M/c/S/C/Z, spaces/commas
_RE_SVG_COORDS = re.compile(r"[MmCcSsLlHhVvZzAaQqTt][0-9][0-9.,\s-]{8,}")
# fill='...' / stroke='...' / d='...' / opacity / url(#...) SVG attributes
_RE_SVG_ATTR = re.compile(r"(fill|stroke|opacity|d|url\(#)[^'\";\s)]{3,}", re.IGNORECASE)
# URL-encoded XML tags like %3E%3Cpath
_RE_ENCODED_XML = re.compile(r"%3[CEce][^%\s]{0,20}(%[0-9A-Fa-f]{2})+[^%\s]*")
_RE_DOMAIN_ONLY = re.compile(r"^(?:https?://)?[a-z0-9-]+(?:\.[a-z0-9-]+)+(?:/[^\s]*)?$", re.IGNORECASE)
_RE_SENTENCE_SPLIT = re.compile(r"(?<=[。！？!?])\s+|\n+")

NEGATIVE_KEYWORDS = ["質疑", "投訴", "爭議", "退款", "不透明", "疑慮", "違法", "虐待", "惡臭", "超收", "髒亂"]
POSITIVE_KEYWORDS = ["改善", "澄清", "反駁", "良好", "整潔", "合格", "透明", "公開", "說明"]
FIRST_HAND_MARKERS = ["實地", "參訪", "親自", "我看到", "我拍到", "現場", "親眼", "我去", "我們到場"]
REPORTED_SPEECH_MARKERS = ["受訪", "表示", "指出", "說", "提到", "新聞資料", "報導", "訪談", "轉述", "引述"]
HARD_EVIDENCE_MARKERS = ["照片", "影片", "裁罰", "公文", "公告", "判決", "稽查", "現場畫面", "檢舉"]
HISTORICAL_CONTROVERSY_MARKERS = ["2018", "2017", "道歉", "財務", "延遲", "透明", "爭議", "質疑", "募資", "flyingv"]
NOISE_MARKERS = [
    "trycloudflare.com",
    "visibility-effects",
    "function(",
    "__next",
    "webpack",
    "javascript",
    "css",
    "paint0_linear",
    "paint1_ra",
    "userspaceonuse",
    "stop-color",
    "fill'url(%23",
    "mentions facebook",
    "文章列表",
    "精華區",
    "error 403",
    "that’s an error",
    "skip navigation",
    "current time 0:00",
    "stream type live",
    "no results found",
    "the page you requested could not be found",
    "try refining your search",
    "select page",
]
GRAY_PAGE_HINTS = [
    "分類彙整",
    "文章列表",
    "標籤彙整",
    "搜尋結果",
    "站內搜尋",
    "上一篇",
    "下一篇",
    "related posts",
    "continue reading",
    "archive",
    "category",
    "tag archive",
    "search results",
    "no posts",
    "older posts",
]
GRAY_PAGE_URL_HINTS = [
    "/category/",
    "/tag/",
    "/search",
    "?s=",
    "/archives/",
    "/archive/",
    "/author/",
    "/page/",
]


def _is_readable(text: str) -> bool:
    """Check if text contains enough readable characters (CJK, Hangul, Kana, or Latin words)."""
    if not text:
        return False
    # Count CJK + readable latin chars
    readable = sum(1 for ch in text if '\u4e00' <= ch <= '\u9fff'  # CJK
                   or '\u3040' <= ch <= '\u30ff'  # Hiragana/Katakana
                   or ch.isalpha())
    ratio = readable / len(text) if text else 0
    return ratio > 0.3


def clean_content(raw: str) -> str:
    """Strip HTML, SVG, CSS, JS, data URIs and other non-text junk from scraped content."""
    if not raw:
        return raw
    text = unicodedata.normalize("NFKC", html.unescape(raw))
    text = _RE_SVG_BLOCK.sub("", text)
    text = _RE_ENCODED_XML.sub("", text)
    text = _RE_DATA_URI.sub("", text)
    text = _RE_CSS_BLOCK.sub("", text)
    text = _RE_JS_BLOCK.sub("", text)
    text = _RE_HTML_TAG.sub(" ", text)
    text = _RE_MARKDOWN_LINK.sub(" ", text)
    text = _RE_URL.sub(" ", text)
    text = _RE_URL_ENCODED.sub("", text)
    text = _RE_SVG_ATTR.sub("", text)
    text = _RE_SVG_COORDS.sub("", text)
    text = _RE_NON_TEXT_SEPARATORS.sub("", text)
    text = _RE_REPLACEMENT_CHAR.sub("", text)
    text = _RE_BRACKET_NOISE.sub(" ", text)
    text = _RE_GARBLED_PUNCT.sub(" ", text)
    text = _RE_SYMBOL_RUN.sub(" ", text)
    text = _RE_MULTI_SPACE.sub(" ", text).strip()
    cleaned_chars: list[str] = []
    for char in text:
        category = unicodedata.category(char)
        if category.startswith("C"):
            continue
        if category.startswith("S") and char not in "⭐☆%":
            continue
        if char == "�":
            continue
        cleaned_chars.append(char)
    text = "".join(cleaned_chars)
    text = _RE_BROKEN_ENDING.sub("", text)
    text = _RE_MULTI_SPACE.sub(" ", text).strip(" -_:/")
    # If after cleaning the text is mostly garbage, discard
    if len(text) < 15 or not _is_readable(text):
        return ""
    return text


def clean_summary_text(raw: str) -> str:
    if not raw:
        return ""
    text = unicodedata.normalize("NFKC", html.unescape(raw))
    text = _RE_NON_TEXT_SEPARATORS.sub("", text)
    text = _RE_REPLACEMENT_CHAR.sub("", text)
    text = _RE_GARBLED_PUNCT.sub(" ", text)
    text = text.replace("\r", "\n")
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    lines = [line.strip(" -_:/") for line in text.splitlines()]
    filtered_lines = [line for line in lines if line and not _RE_BROKEN_ENDING.search(line)]
    text = "\n".join(filtered_lines).strip()
    return text or "現有來源多為片段描述，仍需補查。"


def _contains_any(text: str, keywords: list[str]) -> bool:
    return any(keyword in text for keyword in keywords)


def _entity_variants(entity_name: str) -> list[str]:
    base = entity_name.strip()
    variants = [base]
    if base.endswith("狗園"):
        root = base.removesuffix("狗園").strip()
        variants.extend([f"{root}寵物樂園", f"{root}樂園", f"{root}園區"])
    if base.endswith("樂園"):
        root = base.removesuffix("樂園").strip()
        variants.extend([f"{root}狗園", f"{root}寵物樂園"])

    seen: set[str] = set()
    ordered: list[str] = []
    for variant in variants:
        value = variant.strip().lower()
        if not value or value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered


class AnalysisService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.last_diagnostics = AnalysisDiagnostics()

    def _card_limit(self) -> int:
        configured = self.settings.analysis_card_limit
        if configured < 1:
            return 100
        return min(configured, 500)

    async def analyze(
        self,
        entity_name: str,
        question: str,
        raw_results: list[dict[str, Any]],
        animal_focus: bool = False,
        ) -> tuple[BalancedSummary, list[EvidenceCard]]:
        cards = [self._to_card(result, entity_name, question) for result in raw_results]
        cards, diagnostics = self._rank_and_filter_cards(cards)
        if self.settings.openai_api_key and AsyncOpenAI is not None:
            try:
                before_gray_filter = len(cards)
                diagnostics.gray_candidates = sum(1 for card in cards if self._is_gray_quality_candidate(card) and not self._is_noise_card(card))
                cards = await self._filter_gray_pages_with_openai(question, cards)
                diagnostics.ai_gray_filtered = max(0, before_gray_filter - len(cards))
            except Exception:
                pass
        diagnostics.final_cards = len(cards)
        self.last_diagnostics = diagnostics
        if self.settings.openai_api_key and AsyncOpenAI is not None:
            try:
                cards = await self._summarize_cards_with_openai(question, cards)
                summary = await self._summarize_with_openai(
                    entity_name,
                    question,
                    cards,
                    animal_focus=animal_focus,
                )
                return summary, cards
            except Exception:
                return self._summarize_heuristically(cards, question, animal_focus=animal_focus), cards
        return self._summarize_heuristically(cards, question, animal_focus=animal_focus), cards

    def _to_card(self, result: dict[str, Any], entity_name: str, question: str) -> EvidenceCard:
        raw_text = (
            result.get("content")
            or result.get("raw_content")
            or result.get("snippet")
            or ""
        )
        url = result["url"]
        source = result.get("source") or self._source_name(url)
        raw_title = result.get("title") or ""
        title = self._sanitize_title(raw_title, url, source)
        text = clean_content(raw_text) or "目前沒有可用的摘要內容。"
        source_type = self._source_type(url, result.get("source"), result.get("source_type"))
        first_hand_score = self._first_hand_score(title=title, text=text, source_type=source_type)
        stance, evidence_strength = self._classify_stance_and_strength(
            title=title,
            text=text,
            source_type=source_type,
            first_hand_score=first_hand_score,
        )
        claim_type = self._claim_type(question, text)
        published_at = result.get("published_date")
        relevance_score = self._relevance_score(entity_name, question, title, text)
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
            title=title,
            url=url,
            source=source,
            source_type=source_type,
            snippet=text[:700],
            excerpt=self._build_excerpt(entity_name, question, title, text),
            ai_summary=self._build_card_summary(title, text, source_type, stance),
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
                source_type=source_type,
                credibility_score=credibility_score,
                relevance_score=relevance_score,
                recency_label=recency_label,
                duplicate_risk=duplicate_risk,
            ),
        )

    def _build_excerpt(self, entity_name: str, question: str, title: str, text: str) -> str:
        cleaned = clean_summary_text(text)
        if not cleaned:
            return "目前沒有可用的相關段落。"

        sentences = [segment.strip() for segment in _RE_SENTENCE_SPLIT.split(cleaned) if segment.strip()]
        if not sentences:
            return cleaned[:160]

        keywords = [entity_name.strip(), *[kw for kw in ["評價", "爭議", "動物", "福利", "募資", "透明", "照護", "救援", "評論"] if kw in question]]
        ranked_sentences = sorted(
            sentences,
            key=lambda sentence: (
                sum(4 for keyword in keywords if keyword and keyword in sentence),
                int(entity_name.strip() in sentence),
                min(len(sentence), 220),
            ),
            reverse=True,
        )
        picked: list[str] = []
        total_length = 0
        for sentence in ranked_sentences:
            if sentence in picked:
                continue
            picked.append(sentence)
            total_length += len(sentence)
            if len(picked) >= 2 or total_length >= 150:
                break

        excerpt = " ".join(picked) if picked else sentences[0]
        excerpt = clean_summary_text(excerpt)
        return excerpt[:180]

    def _build_card_summary(self, title: str, text: str, source_type: str, stance: str) -> str:
        excerpt = self._build_excerpt("", "", title, text)
        perspective = {
            "supporting": "這則內容偏向支持疑慮",
            "opposing": "這則內容偏向反駁疑慮",
            "neutral": "這則內容主要提供背景資訊",
            "unclear": "這則內容的立場不明確",
        }[stance]
        source_label = {
            "official": "官方說明",
            "news": "新聞整理",
            "forum": "論壇討論",
            "social": "社群貼文",
            "other": "公開來源",
        }[source_type]
        if excerpt == "目前沒有可用的相關段落。":
            return f"{source_label}，{perspective}。"
        return clean_summary_text(f"{source_label}，{perspective}：{excerpt}")

    def _sanitize_title(self, raw_title: str, url: str, source: str) -> str:
        cleaned_title = clean_summary_text(raw_title) if raw_title else ""
        if cleaned_title and not self._is_noise_text(cleaned_title):
            return cleaned_title[:120]
        cleaned_title = clean_content(raw_title) if raw_title else ""
        if cleaned_title and not self._is_noise_text(cleaned_title):
            return cleaned_title[:120]
        host = self._source_name(url)
        if source and not self._is_noise_text(source):
            return f"{source} 來源紀錄"
        return f"{host} 來源紀錄"

    def _evidence_origin_label(self, source_type: str, first_hand_score: int) -> str:
        if source_type == "official":
            return "官方說明"
        if first_hand_score >= 75:
            return "第一手描述"
        if source_type == "news":
            return "新聞轉述"
        if source_type in {"forum", "social"} and first_hand_score >= 55:
            return "社群第一手貼文"
        if source_type in {"forum", "social"}:
            return "社群討論"
        return "整理資料"

    def _first_hand_score(self, title: str, text: str, source_type: str) -> int:
        combined = f"{title} {text}"
        if source_type == "official":
            return 58
        if _contains_any(combined, FIRST_HAND_MARKERS):
            return 82 if source_type in {"forum", "social"} else 68
        if source_type == "news":
            return 32 if _contains_any(combined, REPORTED_SPEECH_MARKERS) else 38
        if source_type in {"forum", "social"}:
            return 48
        return 36

    def _classify_stance_and_strength(
        self,
        title: str,
        text: str,
        source_type: str,
        first_hand_score: int,
    ) -> tuple[str, str]:
        combined = f"{title} {text}"
        negative_hits = sum(1 for keyword in NEGATIVE_KEYWORDS if keyword in combined)
        positive_hits = sum(1 for keyword in POSITIVE_KEYWORDS if keyword in combined)
        has_hard_evidence = _contains_any(combined, HARD_EVIDENCE_MARKERS)
        is_reported = source_type == "news" and _contains_any(combined, REPORTED_SPEECH_MARKERS)

        if negative_hits == 0 and positive_hits == 0:
            return "neutral", "weak"

        if negative_hits > positive_hits:
            if is_reported and not has_hard_evidence and first_hand_score < 45:
                return "unclear", "weak"
            if has_hard_evidence and first_hand_score >= 60:
                return "supporting", "strong"
            if has_hard_evidence or first_hand_score >= 50:
                return "supporting", "medium"
            return "supporting", "weak"

        if positive_hits > negative_hits:
            if is_reported and not has_hard_evidence and first_hand_score < 45:
                return "neutral", "weak"
            if has_hard_evidence and first_hand_score >= 60:
                return "opposing", "strong"
            if has_hard_evidence or first_hand_score >= 50:
                return "opposing", "medium"
            return "opposing", "weak"

        return "unclear", "weak"

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
        source_type: str,
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
        origin_label = self._evidence_origin_label(source_type, first_hand_score)
        return (
            f"{perspective} 此來源屬於{origin_label}，證據強度為{strength_label}，第一手程度為 {first_hand_score}/100，"
            f"相關性 {relevance_score}/100，可信度 {credibility_score}/100，"
            f"時間判讀為{recency_text}，重複轉載風險為{duplicate_text}。"
        )

    def _source_name(self, url: str) -> str:
        return url.split("/")[2] if "://" in url else "未知來源"

    def _source_type(self, url: str, source: str | None, source_type: str | None = None) -> str:
        if source_type in {"official", "news", "forum", "social", "other"}:
            return source_type
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
        entity_lower = entity_name.lower().strip()
        entity_tokens = _entity_variants(entity_name) or [entity_lower]

        question_keywords = [
            keyword
            for keyword in ["詐騙", "退款", "爭議", "動物", "福利", "募資", "透明", "環境", "評價"]
            if keyword in question
        ]

        # ── 核心：實體名稱是否出現在內文中 ──
        entity_full_match = entity_lower in haystack or any(token in title.lower() for token in entity_tokens)
        entity_partial_match = any(token and token in haystack for token in entity_tokens)

        # 如果實體名稱（完整或部分）完全不在標題+內文中 → 極低相關性
        # 這防止泛論文章（如「動保蟑螂」通論）被誤關聯到特定組織
        if not entity_full_match and not entity_partial_match:
            return max(0, min(15, sum(3 for kw in question_keywords if kw in haystack)))

        score = 15
        if entity_partial_match:
            score += 25
        if entity_full_match:
            score += 30
        # 實體出現在標題中 → 高度相關
        if entity_lower in title.lower():
            score += 15
        score += min(15, sum(5 for keyword in question_keywords if keyword.lower() in haystack))
        if self._question_focuses_on_fundraising_or_controversy(question):
            score += min(12, sum(3 for keyword in HISTORICAL_CONTROVERSY_MARKERS if keyword in haystack))
            if "flyingv" in haystack or "ptt.cc" in haystack or "新聞" in title or "報導" in title:
                score += 8
            if any(marker in haystack for marker in ("官方募資頁", "faq", "checkout")) and "爭議" not in haystack and "道歉" not in haystack:
                score -= 8
        if "search?" in haystack or "prequalify" in haystack or "credit card" in haystack:
            score -= 35
        return max(0, min(100, score))

    def _question_focuses_on_fundraising_or_controversy(self, question: str) -> bool:
        lowered = question.lower()
        return any(keyword in lowered for keyword in ["募資", "捐款", "善款", "財務", "透明", "爭議", "質疑", "道歉", "聲明"])

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

    def _rank_and_filter_cards(self, cards: list[EvidenceCard]) -> tuple[list[EvidenceCard], AnalysisDiagnostics]:
        diagnostics = AnalysisDiagnostics(input_results=len(cards))
        card_limit = self._card_limit()
        sorted_cards = sorted(
            cards,
            key=lambda card: (card.relevance_score, card.credibility_score, card.first_hand_score),
            reverse=True,
        )
        after_noise = [card for card in sorted_cards if not self._is_noise_card(card)]
        diagnostics.noise_filtered = max(0, len(sorted_cards) - len(after_noise))
        # 門檻提高到 40：實體名稱必須出現在內文中才可能 ≥ 40
        filtered_cards = [card for card in after_noise if card.relevance_score >= 40]
        diagnostics.low_relevance_filtered = max(0, len(after_noise) - len(filtered_cards))
        if filtered_cards:
            diversified = self._diversify_cards(filtered_cards, card_limit)
            diagnostics.final_cards = len(diversified)
            return diversified, diagnostics
        # 如果全部都低於門檻，只取前 3 且標記為低相關
        fallback_cards = self._diversify_cards(after_noise[: min(card_limit, 20)], min(card_limit, 10))
        diagnostics.final_cards = len(fallback_cards)
        return fallback_cards, diagnostics

    def _diversify_cards(self, cards: list[EvidenceCard], card_limit: int) -> list[EvidenceCard]:
        if len(cards) <= 2:
            return cards[:card_limit]

        minimum_per_platform = 2
        if any(card.claim_type == "fundraising" for card in cards):
            minimum_per_platform = 1
        grouped: dict[str, list[EvidenceCard]] = {}
        for card in cards:
            platform = self._platform_bucket(card)
            grouped.setdefault(platform, []).append(card)

        selected: list[EvidenceCard] = []
        seen_urls: set[str] = set()

        ordered_platforms = list(grouped.keys())
        if any(card.claim_type == "fundraising" for card in cards):
            priority = ["news", "ptt", "dcard", "forum", "fundraising", "google", "facebook", "instagram", "threads", "official", "other"]
            ordered_platforms = [platform for platform in priority if platform in grouped] + [
                platform for platform in grouped if platform not in priority
            ]

        per_platform_limits = {platform: minimum_per_platform for platform in grouped}
        if any(card.claim_type == "fundraising" for card in cards):
            per_platform_limits["official"] = 1
            per_platform_limits["news"] = 2
            per_platform_limits["ptt"] = 2
            per_platform_limits["dcard"] = 2
            per_platform_limits["forum"] = 2
            per_platform_limits["fundraising"] = 2
            per_platform_limits["other"] = 2

        for platform in ordered_platforms:
            platform_cards = grouped[platform]
            for card in platform_cards[:per_platform_limits.get(platform, minimum_per_platform)]:
                url_key = str(card.url)
                if url_key in seen_urls or len(selected) >= card_limit:
                    continue
                seen_urls.add(url_key)
                selected.append(card)

        if len(selected) >= card_limit:
            return selected[:card_limit]

        for card in cards:
            url_key = str(card.url)
            if url_key in seen_urls:
                continue
            seen_urls.add(url_key)
            selected.append(card)
            if len(selected) >= card_limit:
                break

        return selected[:card_limit]

    def _platform_bucket(self, card: EvidenceCard) -> str:
        host = f"{card.source} {card.url}".lower()
        if "flyingv" in host or "newebpay" in host:
            return "fundraising"
        if "google" in host or "maps" in host:
            return "google"
        if "facebook" in host or "fb.com" in host:
            return "facebook"
        if "instagram" in host:
            return "instagram"
        if "threads" in host:
            return "threads"
        if "dcard" in host:
            return "dcard"
        if "ptt" in host:
            return "ptt"
        if card.source_type == "news":
            return "news"
        if card.source_type == "official":
            return "official"
        return card.source_type

    def _summarize_heuristically(
        self,
        cards: list[EvidenceCard],
        question: str,
        animal_focus: bool = False,
    ) -> BalancedSummary:
        direct_supporting_cards = [
            card
            for card in cards
            if card.stance == "supporting"
            and card.evidence_strength in {"medium", "strong"}
            and card.relevance_score >= 60
            and (card.first_hand_score >= 55 or card.source_type == "official")
        ]
        opposing_cards = [
            card
            for card in cards
            if card.stance == "opposing"
            and card.relevance_score >= 55
            and card.evidence_strength in {"medium", "strong"}
        ]
        uncertain_cards = [
            card
            for card in cards
            if card not in direct_supporting_cards and card not in opposing_cards
        ]

        supporting = [self._build_summary_point(card) for card in direct_supporting_cards[:3]]
        opposing = [self._build_summary_point(card) for card in opposing_cards[:3]]
        neutral = [self._build_summary_point(card) for card in uncertain_cards[:3]]

        confidence = min(
            80,
            22 + len(cards) * 2 + len(direct_supporting_cards) * 8 + len(opposing_cards) * 6,
        )
        verdict = self._compose_verdict(
            question,
            direct_supporting_cards,
            opposing_cards,
            animal_focus=animal_focus,
        )

        supporting_fallback = "目前沒有足夠直接的動物福利證據可列為主要疑慮。" if animal_focus else "目前沒有足夠直接證據可列為主要疑慮。"
        opposing_fallback = "目前未見足夠明確的改善、正式說明或裁罰結論。" if animal_focus else "尚未找到足夠明確的反駁或改善來源。"
        uncertain_fallback = "依目前公開資料，仍需補查動物照護、稽查或裁罰等更直接證據。" if animal_focus else "現有來源多為轉述、片段描述或細節不足，仍需補查。"
        follow_up = (
            [
                "補查主管機關稽查、裁罰與改善資料",
                "人工確認是否有具體時間、地點、動物數量或影像佐證",
                "區分第一手照護紀錄、新聞轉述與社群討論",
            ]
            if animal_focus
            else [
                "補抓更近期的新聞與官方聲明",
                "區分第一手描述與轉述內容",
                "人工確認關鍵指控是否有具體時間、地點、金額或影像佐證",
            ]
        )

        return BalancedSummary(
            verdict=clean_summary_text(verdict),
            confidence=confidence,
            supporting_points=self._clean_summary_points(supporting, supporting_fallback),
            opposing_points=self._clean_summary_points(opposing, opposing_fallback),
            uncertain_points=self._clean_summary_points(neutral, uncertain_fallback),
            suggested_follow_up=self._clean_summary_points(
                follow_up,
                "補查更直接的公開證據。",
            ),
        )

    def _compose_verdict(
        self,
        question: str,
        direct_supporting_cards: list[EvidenceCard],
        opposing_cards: list[EvidenceCard],
        animal_focus: bool = False,
    ) -> str:
        if animal_focus:
            if direct_supporting_cards and len(direct_supporting_cards) > len(opposing_cards):
                return f"依目前公開資料可能涉及「{question}」相關的動物福利疑慮，但仍需主管機關或完整證據進一步認定。"
            if opposing_cards and len(opposing_cards) > len(direct_supporting_cards):
                return f"依目前公開資料，已看到部分改善或反駁資訊；「{question}」是否成立，仍需主管機關或完整證據進一步認定。"
            if direct_supporting_cards or opposing_cards:
                return f"依目前公開資料可能與「{question}」有關，但正反資訊並存，仍需主管機關或完整證據進一步認定。"
            return f"依目前公開資料，暫無足夠直接證據確認是否涉及「{question}」。"
        if direct_supporting_cards and len(direct_supporting_cards) > len(opposing_cards):
            return f"目前公開資料有部分內容支持「{question}」成立，但仍需人工複核原文與時間序。"
        if opposing_cards and len(opposing_cards) > len(direct_supporting_cards):
            return f"目前找到較多反駁、改善或官方說明資訊；直接支持「{question}」的證據相對較少。"
        if direct_supporting_cards or opposing_cards:
            return f"目前公開資料正反並存，對「{question}」仍需結合原文脈絡判讀。"
        return f"目前可用公開資料不足，對「{question}」暫時無法下定論。"

    def _build_summary_point(self, card: EvidenceCard) -> str:
        origin_label = self._evidence_origin_label(card.source_type, card.first_hand_score)
        title = clean_summary_text(card.title)
        if len(title) < 6 or self._is_noise_text(title):
            title = clean_summary_text(f"{card.source} 來源整理")
        return f"{title}（{origin_label}）"

    def _clean_summary_points(self, points: list[str], fallback: str) -> list[str]:
        cleaned_points: list[str] = []
        seen: set[str] = set()
        for point in points:
            cleaned = clean_summary_text(point)
            if len(cleaned) < 6 or cleaned in seen:
                continue
            seen.add(cleaned)
            cleaned_points.append(cleaned)
        return cleaned_points or [fallback]

    def _is_noise_text(self, value: str) -> bool:
        normalized = value.strip().lower()
        if not normalized:
            return True
        if _RE_DOMAIN_ONLY.fullmatch(normalized):
            return True
        return any(marker in normalized for marker in NOISE_MARKERS)

    def _is_noise_card(self, card: EvidenceCard) -> bool:
        joined = " ".join([card.title, card.snippet, str(card.url), card.source]).lower()
        if any(marker in joined for marker in NOISE_MARKERS):
            return True
        if self._is_noise_text(card.title) and card.relevance_score < 70:
            return True
        return False

    def _is_gray_quality_candidate(self, card: EvidenceCard) -> bool:
        joined = " ".join(
            [
                clean_summary_text(card.title),
                clean_summary_text(card.snippet),
                clean_summary_text(card.excerpt or ""),
                str(card.url),
            ]
        ).lower()
        suspicion = 0
        if any(marker in joined for marker in GRAY_PAGE_HINTS):
            suspicion += 2
        if any(marker in str(card.url).lower() for marker in GRAY_PAGE_URL_HINTS):
            suspicion += 1
        if len(clean_summary_text(card.snippet)) < 90:
            suspicion += 1
        if self._is_noise_text(card.title):
            suspicion += 1
        return suspicion >= 2

    async def _filter_gray_pages_with_openai(
        self,
        question: str,
        cards: list[EvidenceCard],
    ) -> list[EvidenceCard]:
        if not cards or not self.settings.openai_api_key or AsyncOpenAI is None:
            return cards

        candidate_positions = [
            index for index, card in enumerate(cards)
            if self._is_gray_quality_candidate(card) and not self._is_noise_card(card)
        ]
        if not candidate_positions:
            return cards

        limited_positions = candidate_positions[:8]
        client = AsyncOpenAI(
            api_key=self.settings.openai_api_key,
            timeout=float(self.settings.openai_timeout_seconds),
        )
        candidate_lines = []
        for display_index, card_index in enumerate(limited_positions, start=1):
            card = cards[card_index]
            candidate_lines.append(
                (
                    f"{display_index}. title={clean_summary_text(card.title)} | "
                    f"source={card.source} | url={card.url} | "
                    f"snippet={clean_summary_text(card.excerpt or card.snippet)[:220]}"
                )
            )
        prompt = (
            "你是一個網頁品質檢查助手。以下來源雖然和主題有一定關聯，但其中可能混入模板頁、"
            "站內搜尋頁、分類頁、404 假頁、導覽頁、購物流程頁或半殘頁。"
            "請只挑出應該剔除的項目。\n\n"
            "【剔除規則】\n"
            "1. 內容主要是導覽、分類、搜尋結果、上一篇/下一篇、登入/購物流程，沒有具體正文。\n"
            "2. 頁面像是模板、空殼、半殘頁或缺少足夠可引用段落。\n"
            "3. 不要因為立場不同就剔除；只根據頁面品質與是否真的有可摘要正文判斷。\n"
            "4. 如果頁面像一般新聞、討論串、募資說明、官方公告，即使內容片段也應保留。\n\n"
            f"問題：{question}\n\n"
            "請只回傳 JSON，格式："
            '{"drop_indices":[1,3],"reasons":["1: 分類頁","3: 模板頁"]}\n\n'
            "候選來源：\n"
            + "\n".join(candidate_lines)
        )

        response = await client.responses.create(
            model=self.settings.openai_model,
            input=prompt,
        )
        parsed = self._parse_llm_summary(response.output_text.strip())
        if parsed is None:
            return cards

        raw_indices = parsed.get("drop_indices")
        if not isinstance(raw_indices, list):
            return cards

        drop_positions: set[int] = set()
        for value in raw_indices:
            try:
                normalized = int(value)
            except (TypeError, ValueError):
                continue
            if 1 <= normalized <= len(limited_positions):
                drop_positions.add(limited_positions[normalized - 1])

        if not drop_positions:
            return cards
        return [card for index, card in enumerate(cards) if index not in drop_positions]

    async def _summarize_with_openai(
        self,
        entity_name: str,
        question: str,
        cards: list[EvidenceCard],
        animal_focus: bool = False,
    ) -> BalancedSummary:
        client = AsyncOpenAI(
            api_key=self.settings.openai_api_key,
            timeout=float(self.settings.openai_timeout_seconds),
        )
        heuristic = self._summarize_heuristically(cards, question, animal_focus=animal_focus)
        evidence_lines = [
            (
                f"- title={clean_summary_text(card.title)} | platform={card.source} | "
                f"stance={card.stance} | strength={card.evidence_strength} | "
                f"first_hand={card.first_hand_score} | relevance={card.relevance_score} | "
                f"credibility={card.credibility_score} | excerpt={clean_summary_text(card.excerpt or card.snippet)[:240]}"
            )
            for card in cards[:12]
        ]
        animal_focus_rules = ""
        if animal_focus:
            animal_focus_rules = (
                "11. 只討論與動物福利、收容、繁殖、照護、虐待、棄養、救援、動保法、稽查或裁罰直接相關的內容。\n"
                "12. 如果內容主要是購物、排隊、娛樂、活動抱怨、名人八卦或其他非動物議題，必須忽略，不可寫入任何 summary 欄位。\n"
                "13. `verdict` 必須使用保守法律語氣，例如『可能涉及』、『依目前公開資料可能與下列問題有關』，並提醒仍需主管機關或完整證據進一步認定。\n\n"
            )
        prompt = (
            "你是一個公正的證據分析助手。請根據以下公開資料與證據，輸出給一般使用者看的總結。\n\n"
            "【重要規則】\n"
            f"1. 你只能引用「明確提到 {entity_name}」的來源作為證據。\n"
            "2. 如果某篇文章談的是整個產業的泛論、募集物資、缺糧公告、轉貼名單或文章列表，"
            f"但沒有直接點名 {entity_name}，你不能將它歸為 {entity_name} 的疑慮。\n"
            "3. 可以同時納入評論、心得、實際參訪、官方聲明、募資資料、政府資料、新聞報導與社群貼文；但要清楚區分它們的來源屬性，不要把不同性質的資料混成同一種證據。\n"
            "4. 不要直接認定違法，只能描述目前公開資料能支持、反駁、以及無法確認的部分。\n"
            "5. 如果可用證據太少或不夠直接，請明確說明「目前無足夠直接證據」。\n"
            "6. 請用繁體中文、白話、像產品頁摘要，不要只是重複文章標題。\n\n"
            "7. `supporting_points` 只能放『支持這個問題或疑慮成立』的證據，例如道歉、財務延遲、第三方質疑、政府紀錄、具體負評。\n"
            "8. `opposing_points` 只能放『反駁、淡化或改善這個疑慮』的證據，例如官方澄清、公開明細、改善措施、支持者正面觀察。\n"
            "9. 如果資料只是單純募資頁、介紹頁或支持者貼文，但沒有直接顯示爭議，優先放在 `uncertain_points` 或 `opposing_points`，不要放進 `supporting_points`。\n\n"
            "10. 如果反駁或改善資訊明顯多於支持疑慮的證據，`verdict` 要直接寫出『目前反駁/改善資訊較多，直接支持疑慮的證據較少』，不要籠統寫成『沒有』。\n\n"
        )
        prompt += animal_focus_rules
        prompt += (
            f"對象：{entity_name}\n"
            f"問題：{question}\n"
            "證據：\n"
            + "\n".join(evidence_lines)
            + "\n\n請只回傳 JSON，格式如下：\n"
            + '{'
            + '"verdict":"一句總結",'
            + '"confidence":70,'
            + '"supporting_points":["最多三點"],'
            + '"opposing_points":["最多三點"],'
            + '"uncertain_points":["最多三點"],'
            + '"suggested_follow_up":["最多三點"]'
            + '}'
        )

        response = await client.responses.create(
            model=self.settings.openai_model,
            input=prompt,
        )
        raw_text = response.output_text.strip()
        parsed = self._parse_llm_summary(raw_text)
        if parsed is None:
            return heuristic

        parsed_supporting = self._normalize_summary_list(parsed.get("supporting_points"))
        parsed_opposing = self._normalize_summary_list(parsed.get("opposing_points"))
        parsed_uncertain = self._normalize_summary_list(parsed.get("uncertain_points"))
        verdict = clean_summary_text(parsed.get("verdict") or heuristic.verdict)
        if parsed_opposing and any(token in verdict for token in ("沒有", "無足夠", "目前無")):
            supporting_cards = [card for card in cards if card.stance == "supporting" and card.evidence_strength in {"medium", "strong"}]
            opposing_cards = [card for card in cards if card.stance == "opposing" and card.evidence_strength in {"medium", "strong"}]
            verdict = self._compose_verdict(
                question,
                supporting_cards,
                opposing_cards,
                animal_focus=animal_focus,
            )

        return BalancedSummary(
            verdict=verdict,
            confidence=self._normalize_confidence(parsed.get("confidence"), heuristic.confidence),
            supporting_points=self._clean_summary_points(
                parsed_supporting,
                heuristic.supporting_points[0],
            ),
            opposing_points=self._clean_summary_points(
                parsed_opposing,
                heuristic.opposing_points[0],
            ),
            uncertain_points=self._clean_summary_points(
                parsed_uncertain,
                heuristic.uncertain_points[0],
            ),
            suggested_follow_up=self._clean_summary_points(
                self._normalize_summary_list(parsed.get("suggested_follow_up")),
                heuristic.suggested_follow_up[0],
            ),
        )

    async def _summarize_cards_with_openai(
        self,
        question: str,
        cards: list[EvidenceCard],
    ) -> list[EvidenceCard]:
        if not cards:
            return cards

        client = AsyncOpenAI(
            api_key=self.settings.openai_api_key,
            timeout=float(self.settings.openai_timeout_seconds),
        )
        card_lines = [
            (
                f"{index + 1}. title={clean_summary_text(card.title)} | source={card.source} | "
                f"stance={card.stance} | excerpt={clean_summary_text(card.excerpt or card.snippet)[:260]}"
            )
            for index, card in enumerate(cards[:25])
        ]
        prompt = (
            "你是一個證據摘要助手。請針對每一筆來源，根據標題與摘錄，輸出一句繁體中文摘要。\n"
            "要求：\n"
            "1. 每句 18 到 40 字。\n"
            "2. 要像 AI 幫使用者快速看懂這則內容，不要只是改寫標題。\n"
            "3. 可以指出這則內容偏向支持疑慮、反駁疑慮、背景資訊或待查證。\n"
            "4. 若摘錄明顯不足，就直說『這則內容主要提供背景，仍需看原文』。\n"
            f"5. 問題是：{question}\n\n"
            "請回傳 JSON：{\"summaries\":[\"...\"]}\n\n"
            "來源列表：\n"
            + "\n".join(card_lines)
        )

        response = await client.responses.create(
            model=self.settings.openai_model,
            input=prompt,
        )
        parsed = self._parse_llm_summary(response.output_text.strip())
        if parsed is None:
            return cards
        summaries = parsed.get("summaries")
        if not isinstance(summaries, list):
            return cards

        updated_cards: list[EvidenceCard] = []
        for index, card in enumerate(cards):
            if index < len(summaries):
                summary_text = clean_summary_text(str(summaries[index]))
                if summary_text:
                    updated_cards.append(card.model_copy(update={"ai_summary": summary_text}))
                    continue
            updated_cards.append(card)
        return updated_cards

    def _parse_llm_summary(self, raw_text: str) -> dict[str, Any] | None:
        if not raw_text:
            return None
        text = raw_text.strip()
        fenced_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
        if fenced_match:
            text = fenced_match.group(1).strip()
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            return None
        return payload if isinstance(payload, dict) else None

    def _normalize_summary_list(self, value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        return [clean_summary_text(str(item)) for item in value[:3] if clean_summary_text(str(item))]

    def _normalize_confidence(self, value: Any, fallback: int) -> int:
        try:
            return max(0, min(100, int(value)))
        except (TypeError, ValueError):
            return fallback
