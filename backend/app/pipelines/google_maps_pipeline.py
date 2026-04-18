from __future__ import annotations

from app.pipelines.base import BasePipeline, PipelineResult
from app.pipelines.registry import register
from app.services.scrapers.google_maps_review_scraper import crawl_google_maps_reviews


@register
class GoogleMapsPipeline(BasePipeline):
    platform = "google_maps"

    def is_available(self) -> bool:
        return bool(self.settings.serpapi_api_key)

    async def crawl_entity(
        self, entity_name: str, aliases: list[str], max_results: int = 50,
    ) -> PipelineResult:
        try:
            reviews = await crawl_google_maps_reviews(
                entity_name,
                serpapi_key=self.settings.serpapi_api_key,
                max_results=max_results,
            )
            return PipelineResult(
                platform=self.platform,
                entity_name=entity_name,
                reviews=reviews,
            )
        except Exception as exc:
            return PipelineResult(
                platform=self.platform,
                entity_name=entity_name,
                errors=[str(exc)],
            )
