from fastapi import APIRouter, Depends

from app.config import Settings, get_settings
from app.models.search import SearchRequest, SearchResponse
from app.services.analysis_service import AnalysisService
from app.services.search_service import SearchService

router = APIRouter(prefix="/api", tags=["search"])


@router.get("/health")
async def healthcheck() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/search", response_model=SearchResponse)
async def search_reputation(
    request: SearchRequest,
    settings: Settings = Depends(get_settings),
) -> SearchResponse:
    search_service = SearchService(settings)
    analysis_service = AnalysisService(settings)

    expanded_queries, raw_results, mode = await search_service.search(
        entity_name=request.entity_name,
        question=request.question,
    )
    summary, evidence_cards = await analysis_service.analyze(
        entity_name=request.entity_name,
        question=request.question,
        raw_results=raw_results,
    )

    return SearchResponse(
        mode=mode,
        expanded_queries=expanded_queries,
        summary=summary,
        evidence_cards=evidence_cards,
    )
