import asyncio
import httpx

from app.config import Settings
from app.services.google_news_rss_service import GoogleNewsRssService
from app.services.duckduckgo_service import DuckDuckGoService
from app.services.firecrawl_service import FirecrawlService
from app.services.serpapi_service import SerpApiService


def test_firecrawl_service_searches_all_queries_in_batches(monkeypatch) -> None:
    service = FirecrawlService(Settings(firecrawl_api_key="fc-test", firecrawl_query_limit=2))
    seen_queries: list[str] = []

    async def fake_run_search_query(client, *, query: str, limit: int, fetched_at: str) -> list[dict]:
        seen_queries.append(query)
        return [{"url": f"https://example.org/{query}", "title": query}]

    monkeypatch.setattr(service, "_run_search_query", fake_run_search_query)

    results = asyncio.run(service.search_reviews(["q1", "q2", "q3", "q4", "q5"]))

    assert seen_queries == ["q1", "q2", "q3", "q4", "q5"]
    assert len(results) == 5


def test_serpapi_service_searches_all_queries_in_batches(monkeypatch) -> None:
    service = SerpApiService(Settings(serpapi_api_key="serp-test", serpapi_web_query_limit=2))
    seen_queries: list[str] = []

    async def fake_run_search_query(client, *, query: str, limit: int, fetched_at: str, api_key: str) -> list[dict]:
        seen_queries.append(query)
        return [{"url": f"https://example.org/{query}", "title": query}]

    monkeypatch.setattr(service, "_run_search_query", fake_run_search_query)

    results = asyncio.run(service.search_reviews(["q1", "q2", "q3", "q4", "q5"]))

    assert seen_queries == ["q1", "q2", "q3", "q4", "q5"]
    assert len(results) == 5


def test_firecrawl_service_stops_after_payment_required(monkeypatch) -> None:
    service = FirecrawlService(Settings(firecrawl_api_key="fc-test", firecrawl_query_limit=2))
    seen_queries: list[str] = []

    async def fake_run_search_query(client, *, query: str, limit: int, fetched_at: str) -> list[dict]:
        seen_queries.append(query)
        if query == "q2":
            request = httpx.Request("POST", "https://api.firecrawl.dev/v2/search")
            response = httpx.Response(402, request=request)
            raise httpx.HTTPStatusError("Payment required", request=request, response=response)
        return [{"url": f"https://example.org/{query}", "title": query}]

    monkeypatch.setattr(service, "_run_search_query", fake_run_search_query)

    results = asyncio.run(service.search_reviews(["q1", "q2", "q3", "q4"]))

    assert seen_queries == ["q1", "q2"]
    assert len(results) == 1


def test_serpapi_service_stops_after_payment_required(monkeypatch) -> None:
    service = SerpApiService(Settings(serpapi_api_key="serp-test", serpapi_web_query_limit=2))
    seen_queries: list[str] = []

    async def fake_run_search_query(client, *, query: str, limit: int, fetched_at: str, api_key: str) -> list[dict]:
        seen_queries.append(query)
        if query == "q2":
            request = httpx.Request("GET", "https://serpapi.com/search.json")
            response = httpx.Response(402, request=request)
            raise httpx.HTTPStatusError("Payment required", request=request, response=response)
        return [{"url": f"https://example.org/{query}", "title": query}]

    monkeypatch.setattr(service, "_run_search_query", fake_run_search_query)

    results = asyncio.run(service.search_reviews(["q1", "q2", "q3", "q4"]))

    assert seen_queries == ["q1", "q2"]
    assert len(results) == 1


def test_duckduckgo_service_parses_html_results_and_decodes_redirect_links() -> None:
    service = DuckDuckGoService(Settings())

    html = """
    <html>
      <body>
        <div class=\"result\">
          <a class=\"result__a\" href=\"//duckduckgo.com/l/?uddg=https%3A%2F%2Fnews.example.org%2Fstory-1\">董旺旺近況</a>
          <a class=\"result__snippet\">這是一段新聞摘要</a>
          <span class=\"result__url\">news.example.org</span>
        </div>
      </body>
    </html>
    """

    results = service._parse_search_results(html, query="董旺旺", fetched_at="2026-04-02T00:00:00+00:00", limit=5)

    assert len(results) == 1
    assert results[0]["url"] == "https://news.example.org/story-1"
    assert results[0]["title"] == "董旺旺近況"
    assert results[0]["matched_query"] == "董旺旺"


def test_google_news_rss_service_parses_feed_items() -> None:
    service = GoogleNewsRssService(Settings())
    xml = """
    <rss version="2.0">
      <channel>
        <item>
          <title>董旺旺園區近況整理 - Example News</title>
          <link>https://news.google.com/rss/articles/test-article?oc=5</link>
          <pubDate>Thu, 02 Apr 2026 04:00:00 GMT</pubDate>
          <description>&lt;a href="https://news.google.com/rss/articles/test-article?oc=5"&gt;董旺旺園區近況整理&lt;/a&gt;&amp;nbsp;&amp;nbsp;&lt;font color="#6f6f6f"&gt;Example News&lt;/font&gt;</description>
          <source url="https://news.example.org">Example News</source>
        </item>
      </channel>
    </rss>
    """

    results = service._parse_feed(xml, query="董旺旺", fetched_at="2026-04-02T04:30:00+00:00", limit=5)

    assert len(results) == 1
    assert results[0]["url"] == "https://news.google.com/rss/articles/test-article?oc=5"
    assert results[0]["title"] == "董旺旺園區近況整理 - Example News"
    assert results[0]["source"] == "Example News"
    assert results[0]["source_type"] == "news"
    assert results[0]["matched_query"] == "董旺旺"
    assert results[0]["published_date"] == "2026-04-02"


def test_google_news_rss_service_resolves_wrapper_url_via_batchexecute() -> None:
    service = GoogleNewsRssService(Settings())
    wrapper_url = "https://news.google.com/rss/articles/test-article?oc=5"
    article_html = """
    <html>
      <body>
        <c-wiz data-p='%.@.[["zh-TW","TW",["FINANCE_TOP_INDICES","WEB_TEST_1_0_0"],null,null,1,1,"TW:zh-Hant",null,null,null,null,null,null,null,false,5],"zh-TW","TW",true,[3,5,9,19],1,true,"891491264",null,null,null,false],"test-article",1,1,null,false,1775105397,"sig-token"]'></c-wiz>
      </body>
    </html>
    """

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and str(request.url).startswith("https://news.google.com/rss/articles/test-article"):
            return httpx.Response(200, request=request, text=article_html)
        if request.method == "POST" and request.url.path == "/_/DotsSplashUi/data/batchexecute":
            assert b"f.req=" in request.content
            return httpx.Response(
                200,
                request=request,
                text=")]}'\n\n[[\"wrb.fr\",\"Fbv4je\",\"[\\\"garturlres\\\",\\\"https://news.example.org/story-1\\\",1]\",null,null,null,\"generic\"]]",
            )
        return httpx.Response(404, request=request)

    async def run() -> str | None:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport, headers={"User-Agent": "Mozilla/5.0"}, follow_redirects=True) as client:
            return await service._resolve_google_news_url(client, wrapper_url)

    decoded = asyncio.run(run())

    assert decoded == "https://news.example.org/story-1"


def test_google_news_rss_service_keeps_wrapper_url_when_decode_payload_missing() -> None:
    service = GoogleNewsRssService(Settings())
    wrapper_url = "https://news.google.com/rss/articles/test-article?oc=5"

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and str(request.url).startswith("https://news.google.com/rss/articles/test-article"):
            return httpx.Response(200, request=request, text="<html><body>No payload</body></html>")
        return httpx.Response(404, request=request)

    async def run() -> str | None:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport, headers={"User-Agent": "Mozilla/5.0"}, follow_redirects=True) as client:
            return await service._resolve_google_news_url(client, wrapper_url)

    decoded = asyncio.run(run())

    assert decoded == wrapper_url
