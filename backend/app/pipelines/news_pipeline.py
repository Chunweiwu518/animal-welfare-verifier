from __future__ import annotations

from app.pipelines.base import BasePipeline, PipelineResult
from app.pipelines.registry import register
from app.services.scrapers.news_scraper import crawl_news_reviews


@register
class NewsPipeline(BasePipeline):
    platform = "news"

    async def crawl_entity(
        self, entity_name: str, aliases: list[str], max_results: int = 50,
    ) -> PipelineResult:
        try:
            reviews = await crawl_news_reviews(entity_name, self.settings, max_results=max_results)
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
