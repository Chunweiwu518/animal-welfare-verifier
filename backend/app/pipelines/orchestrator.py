from __future__ import annotations

import logging

from app.config import Settings
from app.pipelines.base import PipelineResult
from app.pipelines.registry import get_pipeline, list_available
from app.services.persistence_service import PersistenceService

# Ensure all pipelines are registered
import app.pipelines.ptt_pipeline  # noqa: F401
import app.pipelines.news_pipeline  # noqa: F401
import app.pipelines.threads_pipeline  # noqa: F401
import app.pipelines.google_maps_pipeline  # noqa: F401
import app.pipelines.instagram_pipeline  # noqa: F401
import app.pipelines.facebook_pipeline  # noqa: F401

logger = logging.getLogger(__name__)


class CrawlOrchestrator:
    def __init__(self, settings: Settings, persistence: PersistenceService) -> None:
        self.settings = settings
        self.persistence = persistence

    async def run_pipeline_for_entity(
        self,
        platform: str,
        entity_name: str,
        aliases: list[str] | None = None,
        max_results: int = 50,
    ) -> int:
        """Run one pipeline for one entity. Returns count of reviews saved."""
        pipeline = get_pipeline(platform, self.settings)
        if pipeline is None:
            logger.warning("Pipeline %s not available", platform)
            return 0

        result = await pipeline.crawl_entity(
            entity_name, aliases or [], max_results=max_results,
        )

        if result.errors:
            for err in result.errors:
                logger.error("Pipeline %s error for %s: %s", platform, entity_name, err)
            self.persistence.log_pipeline_run(
                platform, entity_name, "failed",
                error_message="; ".join(result.errors),
            )
            return 0

        saved = self.persistence.save_reviews(entity_name, platform, result.reviews)
        self.persistence.log_pipeline_run(
            platform, entity_name, "success", reviews_written=saved,
        )
        logger.info(
            "Pipeline %s entity=%s crawled=%d saved=%d",
            platform, entity_name, len(result.reviews), saved,
        )
        return saved

    async def run_all_for_entity(
        self,
        entity_name: str,
        aliases: list[str] | None = None,
        platforms: list[str] | None = None,
        max_results: int = 50,
    ) -> dict[str, int]:
        """Run all (or selected) pipelines for one entity."""
        targets = platforms or list_available(self.settings)
        results: dict[str, int] = {}
        for platform in targets:
            saved = await self.run_pipeline_for_entity(
                platform, entity_name, aliases, max_results,
            )
            results[platform] = saved
        return results

    async def run_pipeline_for_watchlist(
        self,
        platform: str,
        max_results: int = 50,
    ) -> dict[str, int]:
        """Run one pipeline for all watchlist entities."""
        entities = self.persistence.list_due_watchlist_entities(limit=200)
        results: dict[str, int] = {}
        for entity in entities:
            name = entity.entity_name
            aliases = entity.aliases
            saved = await self.run_pipeline_for_entity(
                platform, name, aliases, max_results,
            )
            results[name] = saved
        return results
