import asyncio
from pathlib import Path

from app.config import Settings
from app.services.official_image_service import OfficialImageService
from app.services.persistence_service import PersistenceService


class StubCrawlService:
    async def fetch_pages(self, urls: list[str]) -> dict[str, dict]:
        return {
            urls[0]: {
                "url": urls[0],
                "metadata": {
                    "title": "台北市立動物園官方網站",
                    "og:image": "https://www.zoo.gov.taipei/images/cover.jpg",
                },
                "html": """
                    <html>
                      <head>
                        <meta property='og:image' content='https://www.zoo.gov.taipei/images/cover.jpg'>
                      </head>
                      <body>
                        <img src='/images/panda.jpg' alt='大貓熊館'>
                        <img src='https://www.zoo.gov.taipei/images/koala.jpg' alt='無尾熊館'>
                      </body>
                    </html>
                """,
            }
        }


class StubCrawlServiceWithBlockedOgImage:
    async def fetch_pages(self, urls: list[str]) -> dict[str, dict]:
        return {
            urls[0]: {
                "url": urls[0],
                "metadata": {
                    "title": "臺南市董旺旺流浪毛小孩生命照護協會",
                    "description": "致力於流浪毛小孩照護、送養與公益募款資訊整理。",
                    "og:image": "https://example.org/blocked-cover.png",
                },
                "html": """
                    <html>
                      <body>
                        <p>臺南市董旺旺流浪毛小孩生命照護協會長期投入流浪動物照護、送養與募款活動。</p>
                        <img src='https://example.org/blocked-cover.png' alt='被擋住的封面'>
                        <img src='/images/shelter-dogs.jpg' alt='園區狗舍'>
                      </body>
                    </html>
                """,
            }
        }


def test_official_image_service_updates_entity_page_profile_from_official_page(tmp_path: Path) -> None:
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()
    settings = Settings(
        database_path=str(tmp_path / "image-service.db"),
        frontend_dist_dir=str(dist_dir),
        bootstrap_seed_watchlist=True,
    )
    persistence = PersistenceService(settings)
    persistence.initialize()
    service = OfficialImageService(
        settings,
        persistence_service=persistence,
        crawl_service=StubCrawlService(),
        image_url_checker=lambda url: True,
    )

    asyncio.run(
        service.refresh_entity_page_images(
            entity_name="台北市立動物園",
            raw_results=[
                {
                    "url": "https://www.zoo.gov.taipei/News_Content.aspx?n=123",
                    "title": "台北市立動物園官方頁面",
                    "source": "Taipei Zoo",
                    "source_type": "official",
                }
            ],
        )
    )

    page = persistence.get_entity_page("台北市立動物園")

    assert page is not None
    assert page.cover_image_url == "https://www.zoo.gov.taipei/images/cover.jpg"
    assert page.gallery[0].url == "https://www.zoo.gov.taipei/images/cover.jpg"
    assert page.gallery[0].source_page_url == "https://www.zoo.gov.taipei/News_Content.aspx?n=123"
    assert any(item.url == "https://www.zoo.gov.taipei/images/panda.jpg" for item in page.gallery)
    assert any(item.url == "https://www.zoo.gov.taipei/images/koala.jpg" for item in page.gallery)
    assert all(item.source_page_url == "https://www.zoo.gov.taipei/News_Content.aspx?n=123" for item in page.gallery)


def test_official_image_service_skips_blocked_images_and_backfills_intro(tmp_path: Path) -> None:
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()
    settings = Settings(
        database_path=str(tmp_path / "image-service-fallback.db"),
        frontend_dist_dir=str(dist_dir),
        bootstrap_seed_watchlist=True,
    )
    persistence = PersistenceService(settings)
    persistence.initialize()
    service = OfficialImageService(
        settings,
        persistence_service=persistence,
        crawl_service=StubCrawlServiceWithBlockedOgImage(),
        image_url_checker=lambda url: url.endswith("shelter-dogs.jpg"),
    )

    asyncio.run(
        service.refresh_entity_page_images(
            entity_name="董旺旺",
            raw_results=[
                {
                    "url": "https://example.org/official-page",
                    "title": "董旺旺官方頁面",
                    "source": "Dong Wang Wang",
                    "source_type": "official",
                }
            ],
        )
    )

    page = persistence.get_entity_page("董旺旺")

    assert page is not None
    assert page.cover_image_url == "https://example.org/images/shelter-dogs.jpg"
    assert all(item.url != "https://example.org/blocked-cover.png" for item in page.gallery)
    assert page.headline == "臺南市董旺旺流浪毛小孩生命照護協會"
    assert "流浪毛小孩照護" in page.introduction