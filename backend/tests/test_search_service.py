import asyncio

from app.config import Settings
from app.services.persistence_service import PersistenceService
from app.services.search_service import SearchService


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

    assert "菩提寵物樂園 評論" in queries
    assert "菩提樂園 評論" in queries


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

    _, results, mode = asyncio.run(service.search("董旺旺", "最近評價如何"))

    assert mode == "live"
    assert any("ptt.cc" in str(item["url"]) for item in results)
    assert any("google.com/maps" in str(item["url"]) for item in results)


def test_search_service_prefers_review_sources() -> None:
    service = SearchService(Settings())

    filtered = service._filter_to_review_sources(
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

    assert len(filtered) == 1
    assert "facebook.com" in filtered[0]["url"]


def test_search_service_uses_firecrawl_results_without_exa_fallback(monkeypatch) -> None:
    service = SearchService(Settings(firecrawl_api_key="fc-test"))

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

    monkeypatch.setattr(service.firecrawl_service, "search_reviews", fake_firecrawl)
    monkeypatch.setattr(service, "_search_platform_sources", fake_platform_sources)

    _, results, mode = asyncio.run(service.search("董旺旺", "最近評價如何"))

    assert mode == "live"
    assert len(results) == 1
    assert results[0]["url"] == "https://example.org/review"


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
