from __future__ import annotations

from app.config import Settings
from app.models.watchlist import WatchlistRefreshRunResult
from app.seed_data import question_templates_for
from app.services.analysis_service import AnalysisService
from app.services.persistence_service import PersistenceService
from app.services.search_service import SearchService


class WatchlistRefreshService:
    def __init__(
        self,
        settings: Settings,
        persistence_service: PersistenceService | None = None,
        search_service: object | None = None,
        analysis_service: object | None = None,
    ) -> None:
        self.settings = settings
        self.persistence_service = persistence_service or PersistenceService(settings)
        self.search_service = search_service or SearchService(settings, persistence_service=self.persistence_service)
        self.analysis_service = analysis_service or AnalysisService(settings)

    async def refresh_due_entities(
        self,
        limit: int | None = None,
        entity_names: list[str] | None = None,
        include_modes: list[str] | None = None,
        questions_per_mode: int | None = None,
    ) -> WatchlistRefreshRunResult:
        self.persistence_service.initialize()
        due_entities = self.persistence_service.list_due_watchlist_entities(
            limit=limit or self.settings.watchlist_refresh_limit,
            entity_names=entity_names,
        )
        result = WatchlistRefreshRunResult()
        questions_limit = max(1, questions_per_mode or self.settings.watchlist_refresh_questions_per_mode)

        for entity in due_entities:
            result.processed += 1
            try:
                modes = include_modes or [entity.default_mode]
                unique_modes: list[str] = []
                for mode in modes:
                    if mode not in {"general", "animal_law"} or mode in unique_modes:
                        continue
                    unique_modes.append(mode)

                if not unique_modes:
                    result.skipped += 1
                    result.details.append(f"skip:{entity.entity_name}:no_valid_mode")
                    continue

                for mode in unique_modes:
                    animal_focus = mode == "animal_law"
                    templates = question_templates_for(entity.entity_type, mode)[:questions_limit]
                    for _, question in templates:
                        expanded_queries, raw_results, search_mode_label, _diagnostics = await self.search_service.search(
                            entity_name=entity.entity_name,
                            question=question,
                            animal_focus=animal_focus,
                            force_live=True,
                        )
                        self.persistence_service.cache_raw_sources(raw_results)
                        summary, evidence_cards = await self.analysis_service.analyze(
                            entity_name=entity.entity_name,
                            question=question,
                            raw_results=raw_results,
                            animal_focus=animal_focus,
                        )
                        query_id = self.persistence_service.save_search_run(
                            entity_name=entity.entity_name,
                            question=question,
                            expanded_queries=expanded_queries,
                            mode=search_mode_label,
                            search_mode=mode,
                            animal_focus=animal_focus,
                            summary=summary,
                            evidence_cards=evidence_cards,
                        )
                        self.persistence_service.save_entity_summary_snapshot(
                            entity_name=entity.entity_name,
                            search_mode=mode,
                            summary=summary,
                            evidence_cards=evidence_cards,
                            latest_query_id=query_id,
                            source_window_days=30,
                        )
                        self.persistence_service.refresh_entity_question_suggestions(
                            entity_name=entity.entity_name,
                            search_mode=mode,
                            latest_summary=summary,
                        )

                self.persistence_service.mark_watchlist_refresh_success(entity.entity_name)
                result.succeeded += 1
                result.details.append(f"success:{entity.entity_name}")
            except Exception as exc:  # pragma: no cover - exercised via tests with fake services
                self.persistence_service.mark_watchlist_refresh_failure(entity.entity_name, str(exc))
                result.failed += 1
                result.details.append(f"failed:{entity.entity_name}:{exc}")

        return result