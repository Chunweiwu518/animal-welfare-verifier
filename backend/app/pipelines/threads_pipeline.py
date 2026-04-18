from __future__ import annotations

from app.pipelines.base import BasePipeline, PipelineResult
from app.pipelines.registry import register
from app.services.scrapers.threads_scraper import crawl_threads_reviews


@register
class ThreadsPipeline(BasePipeline):
    platform = "threads"

    def is_available(self) -> bool:
        return bool(self.settings.exa_api_key)

    async def crawl_entity(
        self, entity_name: str, aliases: list[str], max_results: int = 20,
    ) -> PipelineResult:
        try:
            reviews = await crawl_threads_reviews(
                entity_name,
                exa_api_key=self.settings.exa_api_key,
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
