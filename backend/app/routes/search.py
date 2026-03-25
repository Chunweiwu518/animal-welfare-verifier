from fastapi import APIRouter, Depends, HTTPException

from app.config import Settings, get_settings
from app.models.profile import EntityAliasRequest, EntityListResponse, EntityProfileResponse
from app.models.search import SearchRequest, SearchResponse
from app.services.analysis_service import AnalysisService
from app.services.persistence_service import PersistenceService
from app.services.search_service import SearchService

router = APIRouter(prefix="/api", tags=["search"])


@router.get("/health")
async def healthcheck() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/entities/{entity_name}/profile", response_model=EntityProfileResponse)
async def get_entity_profile(
    entity_name: str,
    settings: Settings = Depends(get_settings),
) -> EntityProfileResponse:
    persistence_service = PersistenceService(settings)
    profile = persistence_service.get_entity_profile(entity_name)
    if profile is None:
        raise HTTPException(status_code=404, detail="Entity profile not found")
    return profile


@router.post("/entities/alias")
async def register_entity_alias(
    request: EntityAliasRequest,
    settings: Settings = Depends(get_settings),
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
    settings: Settings = Depends(get_settings),
) -> EntityListResponse:
    persistence_service = PersistenceService(settings)
    return persistence_service.list_entities(query=q, limit=min(max(limit, 1), 100))


@router.post("/search", response_model=SearchResponse)
async def search_reputation(
    request: SearchRequest,
    settings: Settings = Depends(get_settings),
) -> SearchResponse:
    search_service = SearchService(settings)
    analysis_service = AnalysisService(settings)
    persistence_service = PersistenceService(settings)

    expanded_queries, raw_results, mode = await search_service.search(
        entity_name=request.entity_name,
        question=request.question,
    )
    summary, evidence_cards = await analysis_service.analyze(
        entity_name=request.entity_name,
        question=request.question,
        raw_results=raw_results,
    )
    persistence_service.save_search_run(
        entity_name=request.entity_name,
        question=request.question,
        expanded_queries=expanded_queries,
        mode=mode,
        summary=summary,
        evidence_cards=evidence_cards,
    )

    return SearchResponse(
        mode=mode,
        expanded_queries=expanded_queries,
        summary=summary,
        evidence_cards=evidence_cards,
    )
