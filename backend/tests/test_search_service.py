import asyncio
import logging

from app.config import Settings
from app.models.search import BalancedSummary, EvidenceCard
from app.services.persistence_service import PersistenceService
from app.services.search_service import SearchService


def _seed_cached_snapshot(
    persistence: PersistenceService,
    *,
    entity_name: str,
    search_mode: str = "general",
    source_count: int = 4,
) -> None:
    raw_results: list[dict[str, str]] = []
    evidence_cards: list[EvidenceCard] = []
    for index in range(source_count):
        url = f"https://example.org/{entity_name}/{search_mode}/{index}"
        raw_results.append(
            {
                "title": f"{entity_name} 公開資料整理 {index}",
                "url": url,
                "content": f"{entity_name} 近期公開資料整理，包含評價、照護與新聞摘要 {index}。" * 4,
                "source": "Example News",
                "source_type": "news",
                "published_date": "2026-04-02",
                "fetched_at": "2026-04-02T00:00:00+00:00",
            }
        )
        evidence_cards.append(
            EvidenceCard(
                title=f"{entity_name} 公開資料整理 {index}",
                url=url,
                source="Example News",
                source_type="news",
                snippet=f"{entity_name} 近期公開資料整理 {index}",
                excerpt=f"{entity_name} 近期公開資料整理，包含評價、照護與新聞摘要 {index}。",
                ai_summary="摘要",
                extracted_at="2026-04-02T00:00:00+00:00",
                published_at="2026-04-02",
                stance="neutral",
                claim_type="animal_welfare" if search_mode == "animal_law" else "general_reputation",
                evidence_strength="medium",
                first_hand_score=42,
                relevance_score=81,
                credibility_score=67,
                recency_label="recent",
                duplicate_risk="low",
                notes="待人工複核",
            )
        )

    persistence.cache_raw_sources(raw_results)
    summary = BalancedSummary(
        verdict=f"{entity_name} 已有固定背景資料可供查詢。",
        confidence=78,
        supporting_points=["已有多筆快取資料。"],
        opposing_points=["仍需不定期補查。"],
        uncertain_points=["個別事件仍可能需要即時搜尋。"],
        suggested_follow_up=["持續追蹤公開新聞與官方公告。"],
    )
    query_id = persistence.save_search_run(
        entity_name=entity_name,
        question="近期整體公開評價偏正面還是偏負面？",
        expanded_queries=[f"{entity_name} 評論", f"{entity_name} 新聞"],
        mode="cached",
        search_mode=search_mode,
        animal_focus=search_mode == "animal_law",
        summary=summary,
        evidence_cards=evidence_cards,
    )
    persistence.save_entity_summary_snapshot(
        entity_name=entity_name,
        search_mode=search_mode,
        summary=summary,
        evidence_cards=evidence_cards,
        latest_query_id=query_id,
        source_window_days=30,
    )


def test_build_queries_deduplicates_keywords() -> None:
    service = SearchService(Settings())

    queries = service.build_queries("測試園區", "是否有動物福利爭議與官方改善？")

    assert len(queries) == len(set(queries))
    assert "測試園區 評論" in queries
    assert "測試園區 心得" in queries
    assert "site:dcard.tw 測試園區" in queries
    assert "site:facebook.com 測試園區" in queries
    assert "site:instagram.com 測試園區" in queries
    assert "site:threads.net 測試園區" in queries
    assert "site:ptt.cc/bbs 測試園區" in queries
    assert "site:maps.google.com 測試園區" in queries


def test_search_service_uses_configured_result_limits() -> None:
    settings = Settings(
        search_result_limit=100,
        firecrawl_query_limit=12,
        firecrawl_results_per_query=10,
        metadata_enrich_limit=24,
        metadata_enrich_concurrency=6,
        ptt_max_results=20,
        google_maps_max_results=20,
    )
    service = SearchService(settings)

    assert service._bounded_limit(settings.search_result_limit, default=100, maximum=500) == 100
    assert service._bounded_limit(settings.firecrawl_query_limit, default=12, maximum=20) == 12
    assert service._bounded_limit(settings.firecrawl_results_per_query, default=10, maximum=20) == 10
    assert service._metadata_enrich_limit() == 24
    assert service._metadata_enrich_concurrency() == 6


def test_search_service_hydrates_cached_sources(tmp_path) -> None:
    persistence = PersistenceService(Settings(database_path=str(tmp_path / "cache.db")))
    persistence.initialize()
    persistence.cache_raw_sources(
        [
            {
                "title": "已快取標題",
                "url": "https://example.org/cached",
                "content": "已快取內容",
                "source": "Cached Source",
                "source_type": "news",
                "published_date": "2026-03-20",
                "fetched_at": "2026-03-27T00:00:00+00:00",
            }
        ]
    )

    service = SearchService(Settings(database_path=str(tmp_path / "cache.db")), persistence_service=persistence)
    hydrated = service._hydrate_cached_sources(
        [
            {
                "url": "https://example.org/cached",
                "title": "",
                "content": "",
                "source": "",
            }
        ]
    )

    assert hydrated[0]["title"] == "已快取標題"
    assert hydrated[0]["content"] == "已快取內容"
    assert hydrated[0]["source"] == "Cached Source"


def test_build_queries_prioritizes_site_queries() -> None:
    service = SearchService(Settings())

    queries = service.build_queries("董旺旺", "是否有動物福利爭議？")

    assert "site:dcard.tw 董旺旺" in queries
    assert "site:facebook.com 董旺旺" in queries
    assert "site:instagram.com 董旺旺" in queries
    assert "site:threads.net 董旺旺" in queries
    assert "site:ptt.cc/bbs 董旺旺" in queries
    assert "site:maps.google.com 董旺旺" in queries


def test_build_queries_expands_entity_variants_for_dog_garden() -> None:
    service = SearchService(Settings())

    queries = service.build_queries("菩提狗園", "評價如何")

    assert "菩提 評論" in queries
    assert "菩提寵物樂園 評論" in queries
    assert "菩提樂園 評論" in queries


def test_build_queries_prioritizes_fundraising_evidence_for_controversy_questions() -> None:
    service = SearchService(Settings())

    queries = service.build_queries("董旺旺狗園", "是否有募資爭議？")

    assert queries[0] == "董旺旺狗園 募資"
    assert "董旺旺狗園 財務透明" in queries[:16]
    assert "董旺旺狗園 爭議" in queries[:16]
    assert "董旺旺狗園 新聞" in queries[:24]
    assert "董旺旺狗園 報導" in queries[:24]
    assert "site:flyingv.cc 董旺旺狗園" in queries[:16]
    assert "site:sasw.mohw.gov.tw 董旺旺狗園" in queries[:16]
    assert "site:donate.newebpay.com 董旺旺狗園" in queries[:16]
    assert "site:facebook.com 董旺旺狗園 聲明" in queries[:16]


def test_build_queries_adds_animal_focus_keywords_when_enabled() -> None:
    service = SearchService(Settings())

    queries = service.build_queries("董旺旺狗園", "是否有動物福利疑慮？", animal_focus=True)

    assert "董旺旺狗園 動保" in queries[:12]
    assert "董旺旺狗園 動保法" in queries[:16]
    assert "董旺旺狗園 動物福利" in queries[:16]
    assert "董旺旺狗園 虐待" in queries[:20]
    assert "董旺旺狗園 飼養環境" in queries[:24]
    assert "site:news 董旺旺狗園 動保" in queries[:24]


def test_search_service_skips_network_enrich_for_complete_items() -> None:
    service = SearchService(Settings())

    item = {
        "url": "https://example.org/post",
        "title": "完整標題",
        "source": "Example",
        "published_date": "2026-03-27",
        "content": "這是一段已經夠長的內容。" * 12,
    }

    assert service._needs_network_enrich(item) is False


def test_search_service_filters_low_signal_social_pages() -> None:
    service = SearchService(Settings())

    items = [
        {
            "url": "https://www.facebook.com/",
            "title": "www.facebook.com",
            "snippet": "Explore the things you love. Log into Facebook",
        },
        {
            "url": "https://www.facebook.com/dongwangwang/posts/1",
            "title": "董旺旺志工貼文",
            "snippet": "董旺旺園區近況與照護更新",
        },
    ]

    filtered = service._filter_low_signal_results(items, "董旺旺")

    assert len(filtered) == 1
    assert "dongwangwang/posts/1" in filtered[0]["url"]


def test_search_service_filters_svg_garbage_results() -> None:
    service = SearchService(Settings())

    items = [
        {
            "url": "https://www.facebook.com/example/posts/garbage",
            "title": "現在很多標榜送糧的狗園好像有詐騙的",
            "content": "12w ... ' d'z' fill'url(%23paint0_linear_15251_63610)' userSpaceOnUse gra'rotate(45",
        },
        {
            "url": "https://www.facebook.com/example/posts/real",
            "title": "菩提狗園討論",
            "content": "這篇有實際留言與評價內容，討論照護與捐款。",
        },
    ]

    filtered = service._filter_low_signal_results(items, "菩提狗園")

    assert len(filtered) == 1
    assert filtered[0]["url"].endswith("/real")


def test_search_service_filters_no_results_template_pages() -> None:
    service = SearchService(Settings())

    items = [
        {
            "url": "https://dongwangwang.bobo.care/missing-page",
            "title": "募資進行式- 董旺旺狗園 援助計畫",
            "content": "* * * * * * * * * * Select Page * * * * * * * * * * # No Results Found The page you requested could not be found. Try refining your search, or use the navigation above to locate the post.",
            "source": "bobo.care",
            "source_type": "official",
        },
        {
            "url": "https://dongwangwang.bobo.care/product/real",
            "title": "董旺旺狗園真實募資頁",
            "content": "這裡有募資項目、用途與照護說明。",
            "source": "bobo.care",
            "source_type": "official",
        },
    ]

    filtered = service._filter_low_signal_results(items, "董旺旺狗園")

    assert len(filtered) == 1
    assert filtered[0]["url"].endswith("/real")


def test_search_service_deduplicates_same_host_and_title() -> None:
    service = SearchService(Settings())

    deduped = service._deduplicate_by_url(
        [
            {
                "url": "https://sasw.mohw.gov.tw/page-a",
                "title": "董旺旺流浪毛小孩生命照護認養會 公益勸募管理系統 - 衛生福利部",
            },
            {
                "url": "https://sasw.mohw.gov.tw/page-b",
                "title": "董旺旺流浪毛小孩生命照護認養會 公益勸募管理系統 - 衛生福利部",
            },
        ]
    )

    assert len(deduped) == 1


def test_search_service_merges_platform_results(monkeypatch) -> None:
    service = SearchService(Settings(firecrawl_api_key=None))

    async def fake_platform_sources(entity_name: str) -> list[dict]:
        assert entity_name == "董旺旺"
        return [
            {
                "url": "https://www.ptt.cc/bbs/pet/M.123.html",
                "title": "[PTT/pet] 董旺旺參訪心得",
                "content": "董旺旺 志工與照護狀況分享",
                "source": "PTT pet",
                "source_type": "forum",
                "published_date": "2026-03-27",
            },
            {
                "url": "https://www.google.com/maps/place/?q=place_id:test",
                "title": "[Google Maps] 董旺旺狗園 — 評分 4.6/5",
                "content": "Google Maps 平均評分 4.6/5，共 120 則評論。",
                "source": "Google Maps",
                "source_type": "other",
                "published_date": None,
            },
        ]

    monkeypatch.setattr(service, "_search_platform_sources", fake_platform_sources)

    _, results, mode, diagnostics = asyncio.run(service.search("董旺旺", "最近評價如何"))

    assert mode == "live"
    assert any("ptt.cc" in str(item["url"]) for item in results)
    assert any("google.com/maps" in str(item["url"]) for item in results)
    assert diagnostics.providers.platform_results == 2


def test_search_service_merges_free_discovery_results_into_hybrid_search(monkeypatch) -> None:
    service = SearchService(Settings(firecrawl_api_key=None, serpapi_api_key=None))

    async def fake_duckduckgo_search(queries: list[str]) -> list[dict]:
        assert queries
        return [
            {
                "url": "https://news.example.org/dongwangwang-care",
                "title": "董旺旺照護與園區近況整理",
                "content": "這篇新聞整理董旺旺的照護、環境與近期公開回應。" * 5,
                "snippet": "董旺旺照護與園區近況整理",
                "matched_query": queries[0],
                "source": "Example News",
                "source_type": "news",
                "published_date": "2026-04-02",
            }
        ]

    async def fake_platform_sources(_entity_name: str) -> list[dict]:
        return []

    async def passthrough_crawl(items: list[dict]) -> list[dict]:
        return items

    monkeypatch.setattr(service.duckduckgo_service, "search_reviews", fake_duckduckgo_search)
    monkeypatch.setattr(service, "_search_platform_sources", fake_platform_sources)
    monkeypatch.setattr(service.crawl4ai_service, "enrich_results", passthrough_crawl)

    _, results, mode, diagnostics = asyncio.run(service.search("董旺旺", "最近評價如何？"))

    assert mode == "live"
    assert diagnostics.providers.duckduckgo_results == 1
    assert any("news.example.org/dongwangwang-care" in str(item["url"]) for item in results)


def test_search_service_merges_google_news_rss_results_into_hybrid_search(monkeypatch) -> None:
    service = SearchService(Settings(firecrawl_api_key=None, serpapi_api_key=None))

    async def fake_google_news_search(queries: list[str]) -> list[dict]:
        assert queries
        return [
            {
                "url": "https://news.google.com/rss/articles/example?oc=5",
                "title": "董旺旺照護近況新聞",
                "content": "董旺旺照護近況新聞摘要" * 4,
                "snippet": "董旺旺照護近況新聞",
                "matched_query": queries[0],
                "source": "Example News",
                "source_type": "news",
                "published_date": "2026-04-02",
            }
        ]

    async def fake_duckduckgo_search(_queries: list[str]) -> list[dict]:
        return []

    async def fake_platform_sources(_entity_name: str) -> list[dict]:
        return []

    async def passthrough_crawl(items: list[dict]) -> list[dict]:
        return items

    monkeypatch.setattr(service.google_news_rss_service, "search_reviews", fake_google_news_search)
    monkeypatch.setattr(service.duckduckgo_service, "search_reviews", fake_duckduckgo_search)
    monkeypatch.setattr(service, "_search_platform_sources", fake_platform_sources)
    monkeypatch.setattr(service.crawl4ai_service, "enrich_results", passthrough_crawl)

    _, results, mode, diagnostics = asyncio.run(service.search("董旺旺", "最近新聞如何？"))

    assert mode == "live"
    assert diagnostics.providers.google_news_rss_results == 1
    assert any("news.google.com/rss/articles/example" in str(item["url"]) for item in results)


def test_search_service_keeps_relevant_evidence_sources() -> None:
    service = SearchService(Settings())

    filtered = service._filter_to_relevant_sources(
        [
            {
                "url": "https://www.facebook.com/example/posts/1",
                "title": "董旺旺粉專更新",
                "content": "志工留言與大家評論",
            },
            {
                "url": "https://news.example.org/story",
                "title": "董旺旺年度活動報導",
                "content": "這是一篇活動新聞，主要介紹年度捐贈活動與流程。",
            },
        ],
        "董旺旺",
    )

    assert len(filtered) == 2
    assert any("facebook.com" in item["url"] for item in filtered)
    assert any("news.example.org" in item["url"] for item in filtered)


def test_search_service_keeps_fundraising_evidence_for_controversy_questions() -> None:
    service = SearchService(Settings())

    filtered = service._filter_to_relevant_sources(
        [
            {
                "url": "https://www.flyingv.cc/projects/dongwangwang",
                "title": "董旺旺狗園｜募集飼料與醫療經費",
                "content": "專案頁說明園區收容量、募資用途與執行方式。",
                "source": "flyingV",
            },
            {
                "url": "https://sasw.mohw.gov.tw/app39/list.html",
                "title": "董旺旺流浪毛小孩生命照護認養會 公益勸募管理系統 - 衛生福利部",
                "content": "公益勸募許可與勸募活動資訊。",
                "source": "衛生福利部",
            },
            {
                "url": "https://news.example.org/story",
                "title": "董旺旺年度活動報導",
                "content": "這是一篇活動新聞，主要介紹年度活動流程。",
                "source": "新聞",
            },
        ],
        "董旺旺狗園",
        "是否有募資爭議？",
    )

    assert len(filtered) == 3
    assert any("flyingv.cc" in item["url"] for item in filtered)
    assert any("sasw.mohw.gov.tw" in item["url"] for item in filtered)
    assert any("news.example.org" in item["url"] for item in filtered)


def test_search_service_keeps_site_query_matches_even_when_page_text_is_sparse() -> None:
    service = SearchService(Settings())

    filtered = service._filter_to_relevant_sources(
        [
            {
                "url": "https://www.flyingv.cc/projects/14186?lang=ja",
                "title": "浪浪飼料募資計畫 - flyingV",
                "content": "日本語 中文 English",
                "source": "flyingV",
                "matched_query": "site:flyingv.cc 董旺旺狗園",
            },
            {
                "url": "https://www.flyingv.cc/projects/other",
                "title": "其他毛孩募資計畫 - flyingV",
                "content": "這是一個無關專案",
                "source": "flyingV",
                "matched_query": "site:flyingv.cc 其他園區",
            },
        ],
        "董旺旺狗園",
        "募資爭議",
    )

    assert len(filtered) == 1
    assert "14186" in filtered[0]["url"]


def test_search_service_rejects_non_animal_results_in_animal_mode() -> None:
    service = SearchService(Settings())

    filtered = service._filter_to_relevant_sources(
        [
            {
                "url": "https://news.example.org/animal-case",
                "title": "董旺旺狗園疑涉虐待與飼養環境不良",
                "content": "報導提到犬隻受傷、收容過密、環境惡臭，並提及動保單位稽查。",
                "source": "新聞",
            },
            {
                "url": "https://event.example.org/complaint",
                "title": "董旺旺狗園活動排隊抱怨",
                "content": "民眾抱怨停車、排隊與票務安排，沒有提到動物照護、收容或動保法。",
                "source": "活動論壇",
            },
        ],
        "董旺旺狗園",
        "是否可能涉及動保法問題？",
        animal_focus=True,
    )

    assert len(filtered) == 1
    assert filtered[0]["url"] == "https://news.example.org/animal-case"


def test_search_service_prioritizes_diverse_recall_sources() -> None:
    service = SearchService(Settings())

    ranked = service._prioritize_evidence_results(
        [
            {
                "url": "https://dongwangwang.bobo.care/a",
                "title": "董旺旺狗園 募資計畫 A",
                "content": "官方募資頁面與專案說明。",
                "source": "董旺旺官網",
                "source_type": "official",
            },
            {
                "url": "https://dongwangwang.bobo.care/b",
                "title": "董旺旺狗園 募資計畫 B",
                "content": "官方募資頁面與專案說明。",
                "source": "董旺旺官網",
                "source_type": "official",
            },
            {
                "url": "https://news.example.org/dongwangwang",
                "title": "董旺旺狗園募資爭議報導",
                "content": "新聞整理 2018 年募資與道歉聲明。",
                "source": "新聞",
                "source_type": "news",
            },
            {
                "url": "https://www.ptt.cc/bbs/dog/M.123.html",
                "title": "董旺旺狗園捐款請益",
                "content": "PTT 討論捐款與爭議整理。",
                "source": "PTT",
                "source_type": "forum",
            },
        ],
        "董旺旺狗園",
        "募資爭議",
    )

    top_three_urls = [str(item["url"]) for item in ranked[:3]]

    assert any("news.example.org" in url for url in top_three_urls)
    assert any("ptt.cc" in url for url in top_three_urls)


def test_search_service_caps_official_results_in_top_slots_for_fundraising_controversy() -> None:
    service = SearchService(Settings())

    ranked = service._prioritize_evidence_results(
        [
            {
                "url": f"https://dongwangwang.bobo.care/project-{index}",
                "title": f"董旺旺狗園 募資計畫 {index}",
                "content": "官方募資頁面與專案說明。",
                "source": "董旺旺官網",
                "source_type": "official",
            }
            for index in range(1, 6)
        ] + [
            {
                "url": "https://www.flyingv.cc/projects/14186",
                "title": "浪浪飼料募資計畫 - flyingV",
                "content": "2018 年歷史募資專案與說明，涉及董旺旺狗園。",
                "source": "flyingV",
                "source_type": "other",
                "matched_query": "site:flyingv.cc 董旺旺狗園",
            },
            {
                "url": "https://news.example.org/dongwangwang-fundraising",
                "title": "董旺旺狗園募資爭議報導",
                "content": "新聞整理 2018 年募資與道歉聲明。",
                "source": "新聞",
                "source_type": "news",
            },
            {
                "url": "https://www.ptt.cc/bbs/dog/M.123.html",
                "title": "董旺旺狗園捐款請益",
                "content": "PTT 討論捐款與爭議整理。",
                "source": "PTT",
                "source_type": "forum",
            },
        ],
        "董旺旺狗園",
        "募資爭議",
    )

    top_five = ranked[:5]
    official_count = sum(1 for item in top_five if item.get("source_type") == "official")

    assert official_count <= 2
    assert any("flyingv.cc" in str(item["url"]) for item in top_five)
    assert any("news.example.org" in str(item["url"]) for item in top_five)


def test_search_service_uses_firecrawl_results_without_serpapi_fallback(monkeypatch) -> None:
    service = SearchService(Settings(firecrawl_api_key="fc-test", serpapi_api_key="serp-test"))

    async def fake_firecrawl(queries: list[str]) -> list[dict]:
        return [
            {
                "url": "https://example.org/review",
                "title": "董旺旺 評論整理",
                "content": "這裡有對董旺旺的評論內容",
                "source": "Example",
                "published_date": "2026-03-27",
            }
        ]

    async def fake_platform_sources(entity_name: str) -> list[dict]:
        return []

    async def fake_google_news_search(_queries: list[str]) -> list[dict]:
        return []

    async def fake_duckduckgo_search(_queries: list[str]) -> list[dict]:
        return []

    async def fake_serpapi(queries: list[str]) -> list[dict]:
        raise AssertionError("SerpApi fallback should not run when Firecrawl results are sufficient")

    monkeypatch.setattr(service.google_news_rss_service, "search_reviews", fake_google_news_search)
    monkeypatch.setattr(service.duckduckgo_service, "search_reviews", fake_duckduckgo_search)
    monkeypatch.setattr(service.firecrawl_service, "search_reviews", fake_firecrawl)
    monkeypatch.setattr(service.serpapi_service, "search_reviews", fake_serpapi)
    monkeypatch.setattr(service, "_search_platform_sources", fake_platform_sources)

    _, results, mode, diagnostics = asyncio.run(service.search("董旺旺", "最近評價如何"))

    assert mode == "live"
    assert len(results) == 1
    assert results[0]["url"] == "https://example.org/review"
    assert diagnostics.providers.firecrawl_results == 1
    assert diagnostics.providers.serpapi_results == 0


def test_search_service_uses_serpapi_fallback_when_firecrawl_returns_too_few(monkeypatch) -> None:
    service = SearchService(Settings(firecrawl_api_key="fc-test", serpapi_api_key="serp-test"))

    async def fake_firecrawl(queries: list[str]) -> list[dict]:
        return [
            {
                "url": "https://example.org/one",
                "title": "董旺旺資料",
                "content": "只有一筆結果",
                "source": "Example",
            }
        ]

    async def fake_serpapi(queries: list[str]) -> list[dict]:
        return [
            {
                "url": "https://sasw.mohw.gov.tw/app39/dongwangwang",
                "title": "董旺旺流浪毛小孩生命照護認養會 公益勸募管理系統 - 衛生福利部",
                "content": "公益勸募許可與相關資料。",
                "source": "衛福部",
            }
        ]

    async def fake_platform_sources(entity_name: str) -> list[dict]:
        return []

    async def fake_google_news_search(_queries: list[str]) -> list[dict]:
        return []

    async def fake_duckduckgo_search(_queries: list[str]) -> list[dict]:
        return []

    async def fake_crawl4ai(items: list[dict]) -> list[dict]:
        return items

    monkeypatch.setattr(service.google_news_rss_service, "search_reviews", fake_google_news_search)
    monkeypatch.setattr(service.duckduckgo_service, "search_reviews", fake_duckduckgo_search)
    monkeypatch.setattr(service.firecrawl_service, "search_reviews", fake_firecrawl)
    monkeypatch.setattr(service.serpapi_service, "search_reviews", fake_serpapi)
    monkeypatch.setattr(service.crawl4ai_service, "enrich_results", fake_crawl4ai)
    monkeypatch.setattr(service, "_search_platform_sources", fake_platform_sources)

    _, results, mode, diagnostics = asyncio.run(service.search("董旺旺狗園", "募資爭議"))

    assert mode == "live"
    assert any("sasw.mohw.gov.tw" in str(item["url"]) for item in results)
    assert diagnostics.providers.firecrawl_results == 1
    assert diagnostics.providers.serpapi_results == 1


def test_search_service_supplements_live_results_with_cached_sources(tmp_path, monkeypatch) -> None:
    persistence = PersistenceService(Settings(database_path=str(tmp_path / "cache.db")))
    persistence.initialize()
    summary = BalancedSummary(
        verdict="已有募資相關資料。",
        confidence=73,
        supporting_points=["找到募資頁資料。"],
        opposing_points=["仍需更多官方說明。"],
        uncertain_points=["需補查後續處理。"],
        suggested_follow_up=["持續追蹤募資與官方聲明。"],
    )
    persistence.save_search_run(
        entity_name="董旺旺狗園",
        question="募資爭議",
        expanded_queries=["site:flyingv.cc 董旺旺狗園", "董旺旺狗園 爭議"],
        mode="live",
        search_mode="general",
        animal_focus=False,
        summary=summary,
        evidence_cards=[
            EvidenceCard(
                title="浪浪飼料募資計畫 - flyingV",
                url="https://www.flyingv.cc/projects/14186",
                source="flyingV",
                source_type="other",
                snippet="董旺旺狗園 歷史募資專案與說明。",
                excerpt="董旺旺狗園 歷史募資專案與說明。",
                ai_summary="募資頁證據",
                extracted_at="2026-03-27T00:00:00+00:00",
                published_at="2018-01-01",
                stance="supporting",
                claim_type="general_reputation",
                evidence_strength="medium",
                first_hand_score=55,
                relevance_score=84,
                credibility_score=66,
                recency_label="dated",
                duplicate_risk="low",
                notes="曾被分析採信",
            )
        ],
    )
    persistence.cache_raw_sources(
        [
            {
                "title": "浪浪飼料募資計畫 - flyingV",
                "url": "https://www.flyingv.cc/projects/14186",
                "content": "董旺旺狗園 歷史募資專案與說明。",
                "source": "flyingV",
                "source_type": "other",
                "published_date": "2018-01-01",
                "fetched_at": "2026-03-27T00:00:00+00:00",
            }
        ]
    )
    service = SearchService(Settings(database_path=str(tmp_path / "cache.db")), persistence_service=persistence)

    async def fake_query_sources(queries: list[str], diagnostics=None) -> list[dict]:
        return [
            {
                "url": "https://dongwangwang.bobo.care/project",
                "title": "董旺旺狗園官網募資頁",
                "content": "官方頁說明目前募資項目。",
                "source": "董旺旺官網",
                "source_type": "official",
            }
        ]

    async def fake_platform_sources(entity_name: str) -> list[dict]:
        return []

    async def fake_crawl4ai(items: list[dict]) -> list[dict]:
        return items

    monkeypatch.setattr(service, "_search_query_sources", fake_query_sources)
    monkeypatch.setattr(service, "_search_platform_sources", fake_platform_sources)
    monkeypatch.setattr(service.crawl4ai_service, "enrich_results", fake_crawl4ai)

    _, results, mode, diagnostics = asyncio.run(service.search("董旺旺狗園", "募資爭議"))

    assert mode == "live"
    assert any("flyingv.cc" in str(item["url"]) for item in results)
    assert diagnostics.providers.cached_results >= 1


def test_search_service_does_not_reuse_raw_only_cached_sources(tmp_path, monkeypatch) -> None:
    settings = Settings(database_path=str(tmp_path / "raw_only_cached.db"))
    persistence = PersistenceService(settings)
    persistence.initialize()
    persistence.cache_raw_sources(
        [
            {
                "title": "董旺旺狗園 募資留言整理",
                "url": "https://example.org/raw-only-commentary",
                "content": "董旺旺狗園 募資 爭議 留言整理，但這篇沒有被分析採信。",
                "source": "Example Forum",
                "source_type": "forum",
                "published_date": "2026-03-28",
                "fetched_at": "2026-03-28T00:00:00+00:00",
            }
        ]
    )
    service = SearchService(settings, persistence_service=persistence)

    async def fake_query_sources(_queries: list[str], diagnostics=None) -> list[dict]:
        return [
            {
                "url": "https://news.example.org/dongwangwang-update",
                "title": "董旺旺狗園最新說明",
                "content": "董旺旺狗園最新說明與公開資料整理。" * 5,
                "source": "Example News",
                "source_type": "news",
                "published_date": "2026-04-02",
            }
        ]

    async def fake_platform_sources(_entity_name: str) -> list[dict]:
        return []

    async def passthrough_crawl(items: list[dict]) -> list[dict]:
        return items

    monkeypatch.setattr(service, "_search_query_sources", fake_query_sources)
    monkeypatch.setattr(service, "_search_platform_sources", fake_platform_sources)
    monkeypatch.setattr(service.crawl4ai_service, "enrich_results", passthrough_crawl)

    _, results, mode, diagnostics = asyncio.run(service.search("董旺旺狗園", "募資爭議"))

    assert mode == "live"
    assert diagnostics.providers.cached_results == 0
    assert any("news.example.org/dongwangwang-update" in str(item["url"]) for item in results)


def test_search_service_prefers_cached_sources_when_snapshot_is_recent_and_sufficient(tmp_path, monkeypatch, caplog) -> None:
    settings = Settings(
        database_path=str(tmp_path / "cached_search.db"),
        db_first_min_cached_results=4,
        db_first_min_snapshot_sources=4,
    )
    persistence = PersistenceService(settings)
    persistence.initialize()
    _seed_cached_snapshot(persistence, entity_name="台北市立動物園")
    service = SearchService(settings, persistence_service=persistence)

    async def should_not_run_live_search(_queries: list[str], diagnostics=None) -> list[dict]:
        raise AssertionError("live search should not run when cached data is sufficient")

    async def should_not_fetch_platform_sources(_entity_name: str) -> list[dict]:
        raise AssertionError("platform lookup should not run when cached data is sufficient")

    async def passthrough_crawl(items: list[dict]) -> list[dict]:
        return items

    monkeypatch.setattr(service, "_search_query_sources", should_not_run_live_search)
    monkeypatch.setattr(service, "_search_platform_sources", should_not_fetch_platform_sources)
    monkeypatch.setattr(service.crawl4ai_service, "enrich_results", passthrough_crawl)
    caplog.set_level(logging.INFO, logger="uvicorn.error.app.services.search_service")

    _, results, mode, diagnostics = asyncio.run(service.search("台北市立動物園", "整體評價如何？"))

    assert mode == "cached"
    assert len(results) == 4
    assert diagnostics.providers.cached_results >= 4
    assert "use_cached=True" in caplog.text
    assert "reason=fresh_snapshot" in caplog.text


def test_search_service_runs_live_search_when_snapshot_is_stale(tmp_path, monkeypatch, caplog) -> None:
    settings = Settings(
        database_path=str(tmp_path / "stale_search.db"),
        db_first_min_cached_results=4,
        db_first_min_snapshot_sources=4,
        entity_snapshot_ttl_hours=72,
    )
    persistence = PersistenceService(settings)
    persistence.initialize()
    _seed_cached_snapshot(persistence, entity_name="壽山動物園")
    with persistence._connect() as connection:
        connection.execute(
            "UPDATE entity_summary_snapshots SET generated_at = '2026-03-20 00:00:00', updated_at = '2026-03-20 00:00:00'"
        )

    service = SearchService(settings, persistence_service=persistence)
    live_search_called = False

    async def fake_query_sources(_queries: list[str], diagnostics=None) -> list[dict]:
        nonlocal live_search_called
        live_search_called = True
        return [
            {
                "url": "https://news.example.org/shoushan-update",
                "title": "壽山動物園最新公開資料",
                "content": "壽山動物園最新公開資料整理。" * 6,
                "source": "Example News",
                "source_type": "news",
                "published_date": "2026-04-02",
            }
        ]

    async def fake_platform_sources(_entity_name: str) -> list[dict]:
        return []

    async def passthrough_crawl(items: list[dict]) -> list[dict]:
        return items

    monkeypatch.setattr(service, "_search_query_sources", fake_query_sources)
    monkeypatch.setattr(service, "_search_platform_sources", fake_platform_sources)
    monkeypatch.setattr(service.crawl4ai_service, "enrich_results", passthrough_crawl)
    caplog.set_level(logging.INFO, logger="uvicorn.error.app.services.search_service")

    _, results, mode, diagnostics = asyncio.run(service.search("壽山動物園", "整體評價如何？"))

    assert live_search_called is True
    assert mode == "live"
    assert results
    assert diagnostics.providers.cached_results >= 4
    assert "use_cached=False" in caplog.text
    assert "reason=stale_snapshot" in caplog.text


def test_search_service_runs_live_search_for_recent_questions_when_snapshot_is_not_fresh_enough(tmp_path, monkeypatch) -> None:
    settings = Settings(
        database_path=str(tmp_path / "recent_search.db"),
        db_first_min_cached_results=4,
        db_first_min_snapshot_sources=4,
        entity_snapshot_ttl_hours=72,
        recency_sensitive_snapshot_ttl_hours=24,
    )
    persistence = PersistenceService(settings)
    persistence.initialize()
    _seed_cached_snapshot(persistence, entity_name="新竹市立動物園")
    with persistence._connect() as connection:
        connection.execute(
            "UPDATE entity_summary_snapshots SET generated_at = '2026-04-01 00:00:00', updated_at = '2026-04-01 00:00:00'"
        )

    service = SearchService(settings, persistence_service=persistence)
    live_search_called = False

    async def fake_query_sources(_queries: list[str], diagnostics=None) -> list[dict]:
        nonlocal live_search_called
        live_search_called = True
        return [
            {
                "url": "https://news.example.org/hsinchu-latest",
                "title": "新竹市立動物園近期新聞",
                "content": "新竹市立動物園近期新聞整理。" * 6,
                "source": "Example News",
                "source_type": "news",
                "published_date": "2026-04-02",
            }
        ]

    async def fake_platform_sources(_entity_name: str) -> list[dict]:
        return []

    async def passthrough_crawl(items: list[dict]) -> list[dict]:
        return items

    monkeypatch.setattr(service, "_search_query_sources", fake_query_sources)
    monkeypatch.setattr(service, "_search_platform_sources", fake_platform_sources)
    monkeypatch.setattr(service.crawl4ai_service, "enrich_results", passthrough_crawl)

    _, results, mode, _diagnostics = asyncio.run(service.search("新竹市立動物園", "最近有沒有新的負面新聞？"))

    assert live_search_called is True
    assert mode == "live"
    assert any("news.example.org/hsinchu-latest" in str(item["url"]) for item in results)


def test_search_service_prioritizes_authoritative_fundraising_sources() -> None:
    service = SearchService(Settings())

    ranked = service._prioritize_evidence_results(
        [
            {
                "url": "https://www.instagram.com/p/example",
                "title": "董旺旺狗園推薦貼文",
                "content": "支持董旺旺狗園，覺得很有愛心。",
                "source": "Instagram",
            },
            {
                "url": "https://sasw.mohw.gov.tw/app39/dongwangwang",
                "title": "董旺旺流浪毛小孩生命照護認養會 公益勸募管理系統 - 衛生福利部",
                "content": "公益勸募許可與募款相關資料。",
                "source": "衛生福利部",
            },
        ],
        "董旺旺狗園",
        "募資爭議",
    )

    assert "sasw.mohw.gov.tw" in ranked[0]["url"]


def test_search_service_reclassifies_official_fundraising_pages_from_other() -> None:
    service = SearchService(Settings())

    annotated = service._annotate_source_type(
        {
            "url": "https://dongwangwang.bobo.care/product-category/%E5%B0%88%E6%A1%88%E5%8B%9F%E8%B3%87/",
            "title": "〈專案募資〉彙整頁面 - 董旺旺狗園",
            "source": "dongwangwang.bobo.care",
            "source_type": "other",
        },
        "董旺旺狗園",
    )

    assert annotated["source_type"] == "official"


def test_search_service_filters_empty_social_cards() -> None:
    service = SearchService(Settings())

    items = [
        {
            "url": "https://www.facebook.com/puticarelife",
            "title": "菩提護生協會(@puticarelife) - Facebook",
            "content": "目前沒有可用的摘要內容。",
            "source": "www.facebook.com",
        },
        {
            "url": "https://www.facebook.com/puticarelife/posts/123",
            "title": "菩提護生協會近況更新",
            "content": "近期有民眾留言分享照護心得，也有人討論園區環境。",
            "source": "www.facebook.com",
        },
    ]

    filtered = service._filter_low_signal_results(items, "菩提狗園")

    assert len(filtered) == 1
    assert filtered[0]["url"].endswith("/posts/123")


def test_search_service_filters_list_pages_and_mirror_sites() -> None:
    service = SearchService(Settings())

    items = [
        {
            "url": "https://www.ptt.cc/bbs/dog/index.html",
            "title": "精華區dog 文章列表 - 批踢踢實業坊",
            "content": "精華區dog 文章列表",
        },
        {
            "url": "https://www.pttweb.cc/bbs/Wanted/M.1694597765.A.99E",
            "title": "徵求 善款流浪動物- 看板Wanted",
            "content": "社團法人臺南市董旺旺流浪毛小孩生命照護協會 捐款帳號",
        },
        {
            "url": "https://www.ptt.cc/bbs/dog/M.123.html",
            "title": "[心得] 狗狗臨終到離開+菩提寵物樂園心得- 看板dog",
            "content": "這篇是在討論菩提寵物樂園的實際心得與評價。",
        },
    ]

    filtered = service._filter_low_signal_results(items, "菩提狗園")

    assert len(filtered) == 1
    assert filtered[0]["url"].endswith("M.123.html")
