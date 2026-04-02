from app.config import Settings
from app.services.crawl4ai_service import Crawl4AIService


def test_crawl4ai_service_selects_supported_platform_urls() -> None:
    service = Crawl4AIService(Settings(crawl4ai_url_limit=2))

    selected = service._select_target_indexes(
        [
            {"url": "https://www.dcard.tw/f/pet/p/123", "content": "短內容"},
            {"url": "https://www.facebook.com/story.php?story_fbid=1&id=2", "content": ""},
            {"url": "https://example.org/news", "content": ""},
        ]
    )

    assert selected == {0, 1}


def test_crawl4ai_service_selects_supported_news_and_fundraising_urls() -> None:
    service = Crawl4AIService(Settings(crawl4ai_url_limit=3))

    selected = service._select_target_indexes(
        [
            {"url": "https://www.flyingv.cc/projects/14186", "content": "短內容"},
            {"url": "https://news.example.org/dongwangwang", "content": "短內容"},
            {"url": "https://example.org/landing", "content": "短內容"},
        ]
    )

    assert selected == {0, 1}


def test_crawl4ai_service_keeps_crawling_supported_official_pages_with_medium_length_text() -> None:
    service = Crawl4AIService(Settings(crawl4ai_url_limit=3))

    selected = service._select_target_indexes(
        [
            {"url": "https://dongwangwang.bobo.care/faq/", "content": "這是一段中等長度內容。" * 20, "source_type": "official"},
            {"url": "https://example.org/landing", "content": "短內容", "source_type": "other"},
        ]
    )

    assert selected == {0}


def test_crawl4ai_service_merges_markdown_content() -> None:
    service = Crawl4AIService(Settings())

    merged = service._merge_crawl_result(
        {"url": "https://www.dcard.tw/f/pet/p/123", "title": "原始標題", "content": "短內容"},
        {
            "url": "https://www.dcard.tw/f/pet/p/123",
            "success": True,
            "metadata": {"title": "整理後標題"},
            "markdown": {"fit_markdown": "這是 crawl4ai 抽出的乾淨正文。"},
        },
    )

    assert merged["title"] == "整理後標題"
    assert merged["content"] == "這是 crawl4ai 抽出的乾淨正文。"
    assert merged["crawl_status"] == "ok"


def test_crawl4ai_service_normalizes_model_dump_results() -> None:
    service = Crawl4AIService(Settings())

    class DummyResult:
        def model_dump(self) -> dict[str, object]:
            return {"url": "https://www.threads.net/@demo/post/1", "success": True}

    normalized = service._normalize_crawl_result(DummyResult())

    assert normalized["url"] == "https://www.threads.net/@demo/post/1"
    assert normalized["success"] is True
