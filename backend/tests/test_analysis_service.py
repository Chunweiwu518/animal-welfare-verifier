import asyncio
from types import SimpleNamespace

from app.config import Settings
import app.services.analysis_service as analysis_module
from app.models.search import EvidenceCard
from app.services.analysis_service import AnalysisService, clean_content, clean_summary_text


def test_clean_content_strips_svg_and_encoded_noise() -> None:
    raw = """
    <div>台北動物之家現場改善說明</div>
    <svg><path d="M10 10 L20 20"/></svg>
    data:image/png;base64,aaaa
    %3Cpath%20fill%3D%22red%22%3E
    """

    cleaned = clean_content(raw)

    assert "台北動物之家現場改善說明" in cleaned
    assert "svg" not in cleaned.lower()
    assert "data:image" not in cleaned.lower()


def test_analyze_keeps_reported_news_out_of_primary_concerns() -> None:
    service = AnalysisService(Settings(openai_api_key=None))
    raw_results = [
        {
            "title": "Yahoo新聞：私人狗場不合法爆超收危機恐難控管",
            "url": "https://news.example.org/story",
            "content": "新聞報導引述受訪者表示園區疑似超收，但未附照片、公文或裁罰資料。",
            "source": "Yahoo新聞",
            "published_date": "2026-03-01",
        },
        {
            "title": "台北動物之家官方說明與改善措施",
            "url": "https://official.example.org/statement",
            "content": "官方公告說明近期已完成環境改善並公開照護流程。",
            "source": "台北動物之家",
            "published_date": "2026-03-05",
        },
    ]

    summary, cards = asyncio.run(
        service.analyze(
            entity_name="台北動物之家",
            question="是否有動物福利爭議？",
            raw_results=raw_results,
        )
    )

    assert len(cards) == 1
    assert cards[0].title == "台北動物之家官方說明與改善措施"
    assert summary.supporting_points == ["目前沒有足夠直接證據可列為主要疑慮。"]
    assert any("官方說明" in point for point in summary.opposing_points)


def test_analyze_filters_noise_results() -> None:
    service = AnalysisService(Settings())
    raw_results = [
        {
            "title": "began-item-visibility-effects.trycloudflare.com",
            "url": "https://began-item-visibility-effects.trycloudflare.com",
            "content": "function(){return visibility-effects}",
            "source": "trycloudflare",
            "published_date": None,
        },
        {
            "title": "董旺旺志工現場拍攝照片",
            "url": "https://forum.example.org/post-1",
            "content": "董旺旺志工表示自己在現場拍到園區籠舍清潔狀況，並附上照片。",
            "source": "Forum",
            "published_date": "2026-03-02",
        },
    ]

    _, cards = asyncio.run(
        service.analyze(
            entity_name="董旺旺",
            question="是否有動物福利爭議？",
            raw_results=raw_results,
        )
    )

    assert len(cards) == 1
    assert "trycloudflare" not in cards[0].title.lower()


def test_analyze_filters_no_results_template_cards() -> None:
    service = AnalysisService(Settings(openai_api_key=None))
    raw_results = [
        {
            "title": "募資進行式- 董旺旺狗園 援助計畫",
            "url": "https://dongwangwang.bobo.care/missing-page",
            "content": "* * * * * * * * * * Select Page * * * * * * * * * * # No Results Found The page you requested could not be found. Try refining your search, or use the navigation above to locate the post.",
            "source": "bobo.care",
            "published_date": None,
        },
        {
            "title": "董旺旺狗園真實頁面",
            "url": "https://dongwangwang.bobo.care/product/real",
            "content": "這裡有募資項目、用途與照護說明。",
            "source": "bobo.care",
            "published_date": "2026-03-02",
        },
    ]

    _, cards = asyncio.run(
        service.analyze(
            entity_name="董旺旺狗園",
            question="募資爭議",
            raw_results=raw_results,
        )
    )

    assert len(cards) == 1
    assert str(cards[0].url) == "https://dongwangwang.bobo.care/product/real"


def test_clean_summary_text_removes_replacement_chars_and_noise() -> None:
    raw = "董旺旺流浪毛小�\n\n˙˙\n第一手整理"

    cleaned = clean_summary_text(raw)

    assert "�" not in cleaned
    assert "˙˙" not in cleaned
    assert "第一手整理" in cleaned


def test_analyze_diversifies_cards_across_platforms() -> None:
    service = AnalysisService(Settings(analysis_card_limit=10))
    raw_results = [
        {
            "title": f"Facebook 貼文 {index}",
            "url": f"https://www.facebook.com/post/{index}",
            "content": "董旺旺 志工現場說明與照片紀錄 " * 6,
            "source": "Facebook",
            "published_date": "2026-03-20",
        }
        for index in range(1, 5)
    ] + [
        {
            "title": f"Dcard 討論 {index}",
            "url": f"https://www.dcard.tw/f/pet/p/{index}",
            "content": "董旺旺 使用者分享參訪經驗與照護觀察 " * 6,
            "source": "Dcard",
            "published_date": "2026-03-21",
        }
        for index in range(1, 3)
    ] + [
        {
            "title": f"新聞報導 {index}",
            "url": f"https://news.example.org/story-{index}",
            "content": "董旺旺 新聞報導園區近況與改善內容 " * 6,
            "source": "Yahoo新聞",
            "published_date": "2026-03-22",
        }
        for index in range(1, 3)
    ]

    _, cards = asyncio.run(
        service.analyze(
            entity_name="董旺旺",
            question="最近評價如何？",
            raw_results=raw_results,
        )
    )

    urls = [str(card.url) for card in cards]
    assert sum("facebook.com" in url for url in urls) >= 2
    assert sum("dcard.tw" in url for url in urls) >= 2
    assert sum("news.example.org" in url for url in urls) >= 2


def test_analyze_builds_excerpt_and_card_summary() -> None:
    service = AnalysisService(Settings(openai_api_key=None))
    raw_results = [
        {
            "title": "Yahoo新聞：董旺旺狗園近況",
            "url": "https://news.example.org/dongwangwang",
            "content": (
                "董旺旺狗園近期持續救援流浪犬隻。新聞提到志工說明目前飼料募集壓力很大，"
                "但園區仍維持基本照護與醫療安排。另有外界關注募資透明度。"
            ),
            "source": "Yahoo新聞",
            "published_date": "2026-03-20",
        }
    ]

    _, cards = asyncio.run(
        service.analyze(
            entity_name="董旺旺",
            question="最近評價如何？",
            raw_results=raw_results,
        )
    )

    assert len(cards) == 1
    assert cards[0].excerpt
    assert "董旺旺" in cards[0].excerpt
    assert cards[0].ai_summary
    assert "新聞整理" in cards[0].ai_summary


def test_analyze_prioritizes_historical_fundraising_controversy_over_generic_official_pages() -> None:
    service = AnalysisService(Settings())
    raw_results = [
        {
            "title": f"董旺旺狗園官方募資頁 {index}",
            "url": f"https://dongwangwang.bobo.care/project-{index}",
            "content": "募資用途與專案介紹。",
            "source": "董旺旺官網",
            "source_type": "official",
            "published_date": "2025-12-01",
        }
        for index in range(1, 5)
    ] + [
        {
            "title": "董旺旺狗園募資爭議報導",
            "url": "https://news.example.org/dongwangwang-fundraising",
            "content": "2018 年募資爭議、財務延遲與道歉聲明整理。",
            "source": "新聞",
            "source_type": "news",
            "published_date": "2018-03-12",
        },
        {
            "title": "浪浪飼料募資計畫 - flyingV",
            "url": "https://www.flyingv.cc/projects/14186",
            "content": "董旺旺狗園相關歷史募資專案與計畫說明。",
            "source": "flyingV",
            "source_type": "other",
            "published_date": "2018-01-01",
        },
        {
            "title": "董旺旺狗園捐款請益",
            "url": "https://www.ptt.cc/bbs/dog/M.123.html",
            "content": "PTT 討論指出董旺旺狗園是爭議較多的團體之一，提醒捐款需謹慎。",
            "source": "PTT",
            "source_type": "forum",
            "published_date": "2016-10-16",
        },
    ]

    _, cards = asyncio.run(
        service.analyze(
            entity_name="董旺旺狗園",
            question="募資爭議",
            raw_results=raw_results,
        )
    )

    top_three_urls = [str(card.url) for card in cards[:3]]

    assert any("news.example.org" in url for url in top_three_urls)
    assert any("flyingv.cc" in url for url in top_three_urls)


def test_heuristic_verdict_mentions_opposing_when_opposing_cards_dominate() -> None:
    service = AnalysisService(Settings(openai_api_key=None))
    raw_results = [
        {
            "title": "董旺旺狗園官方說明",
            "url": "https://dongwangwang.bobo.care/statement",
            "content": "官方公開說明募資用途與改善措施。",
            "source": "董旺旺官網",
            "source_type": "official",
            "published_date": "2026-03-20",
        },
        {
            "title": "董旺旺狗園改善與公開明細",
            "url": "https://news.example.org/dongwangwang-improve",
            "content": "新聞整理公開明細與改善資訊，偏向反駁疑慮。",
            "source": "新聞",
            "source_type": "news",
            "published_date": "2026-03-18",
        },
    ]

    summary, _ = asyncio.run(
        service.analyze(
            entity_name="董旺旺狗園",
            question="募資爭議",
            raw_results=raw_results,
        )
    )

    assert "反駁" in summary.verdict or "較少" in summary.verdict


def test_analyze_animal_focus_uses_cautious_animal_welfare_verdict() -> None:
    service = AnalysisService(Settings(openai_api_key=None))
    raw_results = [
        {
            "title": "董旺旺狗園疑涉超收與飼養環境不良",
            "url": "https://news.example.org/animal-case",
            "content": "報導提到犬隻受傷、收容過密、環境惡臭，可能涉及動物福利疑慮。",
            "source": "新聞",
            "published_date": "2026-03-20",
        }
    ]

    summary, cards = asyncio.run(
        service.analyze(
            entity_name="董旺旺狗園",
            question="是否可能涉及動保法問題？",
            raw_results=raw_results,
            animal_focus=True,
        )
    )

    assert len(cards) == 1
    assert "可能涉及" in summary.verdict
    assert "公開資料" in summary.verdict
    combined_points = summary.supporting_points + summary.opposing_points + summary.uncertain_points
    assert any("超收" in point or "飼養環境" in point or "動物福利" in point for point in combined_points)


def test_summarize_with_openai_uses_animal_focus_prompt_rules(monkeypatch) -> None:
    service = AnalysisService(Settings(openai_api_key="test-key"))
    cards = [
        EvidenceCard(
            title="董旺旺狗園疑涉超收與飼養環境不良",
            url="https://news.example.org/animal-case",
            source="新聞",
            source_type="news",
            snippet="報導提到犬隻受傷、收容過密、環境惡臭與稽查資訊。",
            excerpt="報導提到犬隻受傷、收容過密、環境惡臭與稽查資訊。",
            ai_summary="AI 摘要",
            extracted_at=None,
            published_at="2026-03-20",
            stance="supporting",
            claim_type="animal_welfare",
            evidence_strength="medium",
            first_hand_score=58,
            relevance_score=86,
            credibility_score=70,
            recency_label="recent",
            duplicate_risk="low",
            notes="待查",
        )
    ]

    class FakeResponses:
        async def create(self, model: str, input: str) -> SimpleNamespace:
            assert "只討論與動物福利" in input
            assert "可能涉及" in input
            assert "動保法" in input
            return SimpleNamespace(
                output_text=(
                    '{"verdict":"依目前公開資料可能與下列問題有關，仍需主管機關進一步認定。",'
                    '"confidence":74,'
                    '"supporting_points":["董旺旺狗園疑涉超收與飼養環境不良。"],'
                    '"opposing_points":["目前未見完整裁罰結論。"],'
                    '"uncertain_points":["仍需補查稽查原始紀錄。"],'
                    '"suggested_follow_up":["補查主管機關裁罰與改善資料。"]}'
                )
            )

    class FakeClient:
        def __init__(self, *args, **kwargs) -> None:
            self.responses = FakeResponses()

    monkeypatch.setattr(analysis_module, "AsyncOpenAI", FakeClient)

    summary = asyncio.run(
        service._summarize_with_openai(
            entity_name="董旺旺狗園",
            question="是否可能涉及動保法問題？",
            cards=cards,
            animal_focus=True,
        )
    )

    assert "可能與下列問題有關" in summary.verdict
    assert summary.supporting_points == ["董旺旺狗園疑涉超收與飼養環境不良。"]


def test_parse_llm_summary_accepts_json_payload() -> None:
    service = AnalysisService(Settings())

    parsed = service._parse_llm_summary(
        """```json
        {
          "verdict": "整體評價偏混合，負面與支持聲音並存。",
          "confidence": 68,
          "supporting_points": ["部分評論提到照護與募款壓力。"],
          "opposing_points": ["也有貼文表示持續救援與投入照護。"],
          "uncertain_points": ["目前缺少更近期且直接的負評證據。"],
          "suggested_follow_up": ["補查近一年 Google 與社群評論。"]
        }
        ```"""
    )

    assert parsed is not None
    assert parsed["confidence"] == 68
    assert parsed["supporting_points"][0] == "部分評論提到照護與募款壓力。"


def test_filter_gray_pages_with_openai_drops_template_like_cards(monkeypatch) -> None:
    service = AnalysisService(Settings(openai_api_key="test-key"))
    cards = [
        EvidenceCard(
            title="董旺旺狗園分類頁面",
            url="https://example.org/category/dongwangwang",
            source="Example",
            source_type="other",
            snippet="這裡整理多篇文章、上一篇、下一篇、分類彙整與站內導覽，沒有具體內容。",
            excerpt="這裡整理多篇文章、上一篇、下一篇、分類彙整與站內導覽，沒有具體內容。",
            ai_summary="背景頁",
            extracted_at=None,
            published_at=None,
            stance="neutral",
            claim_type="fundraising",
            evidence_strength="weak",
            first_hand_score=20,
            relevance_score=62,
            credibility_score=40,
            recency_label="unknown",
            duplicate_risk="low",
            notes="待查",
        ),
        EvidenceCard(
            title="董旺旺狗園募資說明與用途",
            url="https://example.org/projects/dongwangwang",
            source="Example",
            source_type="official",
            snippet="頁面列出募資用途、醫療支出與照護計畫，並有具體段落說明。",
            excerpt="頁面列出募資用途、醫療支出與照護計畫，並有具體段落說明。",
            ai_summary="AI 摘要",
            extracted_at=None,
            published_at="2026-03-20",
            stance="opposing",
            claim_type="fundraising",
            evidence_strength="medium",
            first_hand_score=45,
            relevance_score=83,
            credibility_score=76,
            recency_label="recent",
            duplicate_risk="low",
            notes="可參考",
        ),
    ]

    class FakeResponses:
        async def create(self, model: str, input: str) -> SimpleNamespace:
            assert "請只回傳 JSON" in input
            return SimpleNamespace(output_text='{"drop_indices":[1]}')

    class FakeClient:
        def __init__(self, *args, **kwargs) -> None:
            self.responses = FakeResponses()

    monkeypatch.setattr(analysis_module, "AsyncOpenAI", FakeClient)

    filtered = asyncio.run(service._filter_gray_pages_with_openai("募資爭議", cards))

    assert len(filtered) == 1
    assert str(filtered[0].url) == "https://example.org/projects/dongwangwang"


def test_filter_gray_pages_with_openai_keeps_cards_on_invalid_response(monkeypatch) -> None:
    service = AnalysisService(Settings(openai_api_key="test-key"))
    cards = [
        EvidenceCard(
            title="董旺旺狗園文章彙整",
            url="https://example.org/tag/dongwangwang",
            source="Example",
            source_type="other",
            snippet="分類頁與文章索引。",
            excerpt="分類頁與文章索引。",
            ai_summary="背景頁",
            extracted_at=None,
            published_at=None,
            stance="neutral",
            claim_type="general",
            evidence_strength="weak",
            first_hand_score=10,
            relevance_score=58,
            credibility_score=36,
            recency_label="unknown",
            duplicate_risk="low",
            notes="待查",
        ),
    ]

    class FakeResponses:
        async def create(self, model: str, input: str) -> SimpleNamespace:
            return SimpleNamespace(output_text="not-json")

    class FakeClient:
        def __init__(self, *args, **kwargs) -> None:
            self.responses = FakeResponses()

    monkeypatch.setattr(analysis_module, "AsyncOpenAI", FakeClient)

    filtered = asyncio.run(service._filter_gray_pages_with_openai("募資爭議", cards))

    assert len(filtered) == 1
    assert str(filtered[0].url) == "https://example.org/tag/dongwangwang"
