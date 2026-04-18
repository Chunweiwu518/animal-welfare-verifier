from __future__ import annotations

from app.pipelines.base import BasePipeline, PipelineResult
from app.pipelines.registry import register
from app.services.scrapers.ptt_scraper import crawl_ptt_reviews


@register
class PttPipeline(BasePipeline):
    platform = "ptt"

    async def crawl_entity(
        self, entity_name: str, aliases: list[str], max_results: int = 50,
    ) -> PipelineResult:
        try:
            reviews = await crawl_ptt_reviews(entity_name, max_articles=max_results)
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
