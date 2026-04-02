import logging

from fastapi import APIRouter, Depends, HTTPException, status

from app.config import Settings, get_request_settings
from app.models.profile import (
    EntityAliasRequest,
    EntityCommentCreateRequest,
    EntityCommentResponse,
    EntityListResponse,
    EntityPageResponse,
    EntityProfileResponse,
    EntityQuestionSuggestionsResponse,
    EntitySummarySnapshotResponse,
)
from app.models.search import ProviderDiagnostics, SearchDiagnostics, SearchRequest, SearchResponse
from app.services.analysis_service import AnalysisService
from app.services.official_image_service import OfficialImageService
from app.services.persistence_service import PersistenceService
from app.services.search_service import SearchService

router = APIRouter(prefix="/api", tags=["search"])
logger = logging.getLogger("uvicorn.error").getChild(__name__)
logger.setLevel(logging.INFO)


@router.get("/health")
async def healthcheck() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/entities/{entity_name}/profile", response_model=EntityProfileResponse)
async def get_entity_profile(
    entity_name: str,
    settings: Settings = Depends(get_request_settings),
) -> EntityProfileResponse:
    persistence_service = PersistenceService(settings)
    profile = persistence_service.get_entity_profile(entity_name)
    if profile is None:
        raise HTTPException(status_code=404, detail="Entity profile not found")
    return profile


@router.get("/entities/{entity_name}/page", response_model=EntityPageResponse)
async def get_entity_page(
    entity_name: str,
    settings: Settings = Depends(get_request_settings),
) -> EntityPageResponse:
    persistence_service = PersistenceService(settings)
    page = persistence_service.get_entity_page(entity_name)
    if page is None:
        raise HTTPException(status_code=404, detail="Entity page not found")
    return page


@router.post(
    "/entities/{entity_name}/comments",
    response_model=EntityCommentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_entity_comment(
    entity_name: str,
    request: EntityCommentCreateRequest,
    settings: Settings = Depends(get_request_settings),
) -> EntityCommentResponse:
    normalized_comment = request.comment.strip()
    if not normalized_comment:
        raise HTTPException(status_code=400, detail="Comment cannot be empty")

    persistence_service = PersistenceService(settings)
    return persistence_service.save_entity_comment(entity_name, normalized_comment)


@router.get("/entities/{entity_name}/snapshot", response_model=EntitySummarySnapshotResponse)
async def get_entity_snapshot(
    entity_name: str,
    animal_focus: bool = False,
    settings: Settings = Depends(get_request_settings),
) -> EntitySummarySnapshotResponse:
    persistence_service = PersistenceService(settings)
    snapshot = persistence_service.get_entity_summary_snapshot(
        entity_name,
        "animal_law" if animal_focus else "general",
    )
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Entity snapshot not found")
    return snapshot


@router.get("/entities/{entity_name}/suggestions", response_model=EntityQuestionSuggestionsResponse)
async def get_entity_question_suggestions(
    entity_name: str,
    animal_focus: bool = False,
    settings: Settings = Depends(get_request_settings),
) -> EntityQuestionSuggestionsResponse:
    persistence_service = PersistenceService(settings)
    suggestions = persistence_service.get_entity_question_suggestions(
        entity_name,
        "animal_law" if animal_focus else "general",
    )
    if suggestions is None:
        raise HTTPException(status_code=404, detail="Entity suggestions not found")
    return suggestions


@router.post("/entities/alias")
async def register_entity_alias(
    request: EntityAliasRequest,
    settings: Settings = Depends(get_request_settings),
) -> dict[str, str]:
    persistence_service = PersistenceService(settings)
    persistence_service.register_entity_alias(
        canonical_name=request.canonical_name.strip(),
        alias=request.alias.strip(),
    )
    return {"status": "ok"}


@router.get("/entities", response_model=EntityListResponse)
async def list_entities(
    q: str | None = None,
    limit: int = 20,
    settings: Settings = Depends(get_request_settings),
) -> EntityListResponse:
    persistence_service = PersistenceService(settings)
    return persistence_service.list_entities(query=q, limit=min(max(limit, 1), 100))


@router.post("/search", response_model=SearchResponse)
async def search_reputation(
    request: SearchRequest,
    settings: Settings = Depends(get_request_settings),
) -> SearchResponse:
    persistence_service = PersistenceService(settings)
    search_service = SearchService(settings, persistence_service=persistence_service)
    analysis_service = AnalysisService(settings)
    search_mode = "animal_law" if request.animal_focus else "general"

    cached_result = persistence_service.get_cached_query_result(
        entity_name=request.entity_name,
        question=request.question,
        search_mode=search_mode,
        max_age_hours=max(1, settings.query_cache_ttl_hours),
    )
    if cached_result is not None:
        evidence_cards = cached_result["evidence_cards"]
        logger.info(
            "exact_query_cache_hit entity=%s search_mode=%s animal_focus=%s evidence_count=%s",
            request.entity_name,
            search_mode,
            request.animal_focus,
            len(evidence_cards),
        )
        diagnostics = SearchDiagnostics(
            query_count=len(cached_result["expanded_queries"]),
            raw_merged_results=len(evidence_cards),
            deduplicated_results=len(evidence_cards),
            cached_results=len(evidence_cards),
            final_results=len(evidence_cards),
            providers=ProviderDiagnostics(cached_results=len(evidence_cards)),
        )
        return SearchResponse(
            mode="cached",
            search_mode=search_mode,
            animal_focus=request.animal_focus,
            expanded_queries=cached_result["expanded_queries"],
            summary=cached_result["summary"],
            evidence_cards=evidence_cards,
            diagnostics=diagnostics,
        )

    logger.info(
        "exact_query_cache_miss entity=%s search_mode=%s animal_focus=%s question=%s",
        request.entity_name,
        search_mode,
        request.animal_focus,
        request.question,
    )

    expanded_queries, raw_results, mode, diagnostics = await search_service.search(
        entity_name=request.entity_name,
        question=request.question,
        animal_focus=request.animal_focus,
    )
    persistence_service.cache_raw_sources(raw_results)
    summary, evidence_cards = await analysis_service.analyze(
        entity_name=request.entity_name,
        question=request.question,
        raw_results=raw_results,
        animal_focus=request.animal_focus,
    )
    query_id = persistence_service.save_search_run(
        entity_name=request.entity_name,
        question=request.question,
        expanded_queries=expanded_queries,
        mode=mode,
        search_mode=search_mode,
        animal_focus=request.animal_focus,
        summary=summary,
        evidence_cards=evidence_cards,
    )
    persistence_service.save_entity_summary_snapshot(
        entity_name=request.entity_name,
        search_mode=search_mode,
        summary=summary,
        evidence_cards=evidence_cards,
        latest_query_id=query_id,
        source_window_days=30,
    )
    persistence_service.refresh_entity_question_suggestions(
        entity_name=request.entity_name,
        search_mode=search_mode,
        latest_summary=summary,
    )
    official_image_service = OfficialImageService(settings, persistence_service=persistence_service)
    await official_image_service.refresh_entity_page_images(
        entity_name=request.entity_name,
        raw_results=raw_results,
    )
    logger.info(
        "search_response_ready entity=%s search_mode=%s animal_focus=%s mode=%s evidence_count=%s raw_results=%s cached_provider_results=%s",
        request.entity_name,
        search_mode,
        request.animal_focus,
        mode,
        len(evidence_cards),
        len(raw_results),
        diagnostics.providers.cached_results,
    )

    return SearchResponse(
        mode=mode,
        search_mode=search_mode,
        animal_focus=request.animal_focus,
        expanded_queries=expanded_queries,
        summary=summary,
        evidence_cards=evidence_cards,
        diagnostics=diagnostics.model_copy(
            update={"analysis": analysis_service.last_diagnostics}
        ),
    )
