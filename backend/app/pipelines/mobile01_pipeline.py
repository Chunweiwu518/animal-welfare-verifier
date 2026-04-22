from __future__ import annotations

from app.pipelines.base import BasePipeline, PipelineResult
from app.pipelines.registry import register
from app.services.scrapers.mobile01_scraper import crawl_mobile01_reviews


@register
class Mobile01Pipeline(BasePipeline):
    platform = "mobile01"

    def is_available(self) -> bool:
        return bool(self.settings.serpapi_api_key)

    async def crawl_entity(
        self, entity_name: str, aliases: list[str], max_results: int = 30,
    ) -> PipelineResult:
        try:
            reviews = await crawl_mobile01_reviews(
                entity_name, self.settings, max_results=max_results,
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
