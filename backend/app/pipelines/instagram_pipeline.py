from __future__ import annotations

from app.pipelines.base import BasePipeline, PipelineResult
from app.pipelines.registry import register
from app.services.scrapers.apify_scraper import (
    crawl_instagram_comments,
    crawl_instagram_posts,
)


@register
class InstagramPostsPipeline(BasePipeline):
    platform = "instagram_posts"

    def is_available(self) -> bool:
        return bool(self.settings.apify_api_token)

    async def crawl_entity(
        self, entity_name: str, aliases: list[str], max_results: int = 10,
    ) -> PipelineResult:
        try:
            reviews = await crawl_instagram_posts(
                entity_name,
                apify_token=self.settings.apify_api_token,
                max_results=max_results,
            )
            return PipelineResult(platform=self.platform, entity_name=entity_name, reviews=reviews)
        except Exception as exc:
            return PipelineResult(platform=self.platform, entity_name=entity_name, errors=[str(exc)])


@register
class InstagramCommentsPipeline(BasePipeline):
    platform = "instagram_comments"

    def is_available(self) -> bool:
        return bool(self.settings.apify_api_token)

    async def crawl_entity(
        self, entity_name: str, aliases: list[str], max_results: int = 50,
    ) -> PipelineResult:
        try:
            reviews = await crawl_instagram_comments(
                entity_name,
                apify_token=self.settings.apify_api_token,
                max_results=max_results,
            )
            return PipelineResult(platform=self.platform, entity_name=entity_name, reviews=reviews)
        except Exception as exc:
            return PipelineResult(platform=self.platform, entity_name=entity_name, errors=[str(exc)])
