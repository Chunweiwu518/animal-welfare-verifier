import asyncio

from app.config import Settings
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
    service = AnalysisService(Settings())
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
