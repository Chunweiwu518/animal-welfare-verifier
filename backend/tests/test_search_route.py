import logging

from fastapi.testclient import TestClient

import app.routes.search as search_module
from app.config import Settings
from app.main import create_app
from app.services.persistence_service import PersistenceService
from app.models.search import (
    BalancedSummary,
    EvidenceCard,
    ProviderDiagnostics,
    SearchDiagnostics,
    SearchRequest,
)


def test_search_request_defaults_animal_focus_to_false() -> None:
    request = SearchRequest(entity_name="董旺旺狗園", question="是否有動物福利疑慮？")

    assert request.animal_focus is False


def test_search_endpoint_returns_search_mode_and_animal_focus(tmp_path, monkeypatch) -> None:
    async def fake_search(self, entity_name: str, question: str, animal_focus: bool = False):
        assert entity_name == "董旺旺狗園"
        assert question == "是否可能涉及動保法問題？"
        assert animal_focus is True
        return (
            ["董旺旺狗園 動保"],
            [
                {
                    "url": "https://news.example.org/animal-case",
                    "title": "董旺旺狗園疑涉虐待與超收",
                    "content": "報導提到犬隻受傷、飼養環境不良與稽查資訊。",
                    "source": "新聞",
                    "source_type": "news",
                    "published_date": "2026-03-27",
                }
            ],
            "live",
            SearchDiagnostics(providers=ProviderDiagnostics()),
        )

    async def fake_analyze(
        self,
        entity_name: str,
        question: str,
        raw_results: list[dict],
        animal_focus: bool = False,
    ):
        assert entity_name == "董旺旺狗園"
        assert question == "是否可能涉及動保法問題？"
        assert animal_focus is True
        assert raw_results[0]["url"] == "https://news.example.org/animal-case"
        return (
            BalancedSummary(
                verdict="依目前公開資料可能與下列動物福利問題有關，仍需主管機關進一步認定。",
                confidence=71,
                supporting_points=["董旺旺狗園疑涉虐待與超收（新聞轉述）"],
                opposing_points=["目前未見完整官方裁罰結論。"],
                uncertain_points=["仍需補查更完整的稽查紀錄。"],
                suggested_follow_up=["補查主管機關稽查、裁罰與改善資料。"],
            ),
            [
                EvidenceCard(
                    title="董旺旺狗園疑涉虐待與超收",
                    url="https://news.example.org/animal-case",
                    source="新聞",
                    source_type="news",
                    snippet="報導提到犬隻受傷、飼養環境不良與稽查資訊。",
                    excerpt="報導提到犬隻受傷、飼養環境不良與稽查資訊。",
                    ai_summary="這則內容提到動物福利與稽查疑慮。",
                    extracted_at=None,
                    published_at="2026-03-27",
                    stance="supporting",
                    claim_type="animal_welfare",
                    evidence_strength="medium",
                    first_hand_score=60,
                    relevance_score=88,
                    credibility_score=72,
                    recency_label="recent",
                    duplicate_risk="low",
                    notes="可作為動保模式線索",
                )
            ],
        )

    monkeypatch.setattr(search_module.SearchService, "search", fake_search)
    monkeypatch.setattr(search_module.AnalysisService, "analyze", fake_analyze)

    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()
    app = create_app(Settings(database_path=str(tmp_path / "test.db"), frontend_dist_dir=str(dist_dir)))

    with TestClient(app) as client:
        response = client.post(
            "/api/search",
            json={
                "entity_name": "董旺旺狗園",
                "question": "是否可能涉及動保法問題？",
                "animal_focus": True,
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["search_mode"] == "animal_law"
    assert payload["animal_focus"] is True
    assert payload["expanded_queries"] == ["董旺旺狗園 動保"]


def test_search_endpoint_returns_cached_query_result_before_live_search(tmp_path, monkeypatch, caplog) -> None:
    def fail_search(*args, **kwargs):  # pragma: no cover - should not be called
        raise AssertionError("live search should not run when cached result exists")

    def fail_analyze(*args, **kwargs):  # pragma: no cover - should not be called
        raise AssertionError("analysis should not run when cached result exists")

    db_path = tmp_path / "cached.db"
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()
    settings = Settings(
        database_path=str(db_path),
        frontend_dist_dir=str(dist_dir),
        bootstrap_seed_watchlist=True,
        query_cache_ttl_hours=72,
    )
    persistence = PersistenceService(settings)
    persistence.initialize()
    summary = BalancedSummary(
        verdict="依目前公開資料可能與照護環境疑慮有關，仍需進一步查核。",
        confidence=73,
        supporting_points=["近期公開資料提到照護與環境議題。"],
        opposing_points=["目前也看到部分改善描述。"],
        uncertain_points=["仍需更多第一手資料。"],
        suggested_follow_up=["補查主管機關稽查資料。"],
    )
    cards = [
        EvidenceCard(
            title="台北市立動物園照護環境討論",
            url="https://example.org/cached-zoo",
            source="Example News",
            source_type="news",
            snippet="近期有公開資料提到收容密度、環境與照護問題。",
            excerpt="近期有公開資料提到收容密度、環境與照護問題。",
            ai_summary="摘要",
            extracted_at="2026-04-01T00:00:00+00:00",
            published_at="2026-03-30",
            stance="supporting",
            claim_type="animal_welfare",
            evidence_strength="medium",
            first_hand_score=45,
            relevance_score=82,
            credibility_score=68,
            recency_label="recent",
            duplicate_risk="low",
            notes="待人工複核",
        )
    ]
    persistence.save_search_run(
        entity_name="台北市立動物園",
        question="是否可能涉及動保法相關疑慮？",
        expanded_queries=["台北市立動物園 動保"],
        mode="live",
        search_mode="animal_law",
        animal_focus=True,
        summary=summary,
        evidence_cards=cards,
    )

    monkeypatch.setattr(search_module.SearchService, "search", fail_search)
    monkeypatch.setattr(search_module.AnalysisService, "analyze", fail_analyze)
    caplog.set_level(logging.INFO, logger="uvicorn.error.app.routes.search")

    app = create_app(settings)
    with TestClient(app) as client:
        response = client.post(
            "/api/search",
            json={
                "entity_name": "木柵動物園",
                "question": "是否可能涉及動保法相關疑慮？",
                "animal_focus": True,
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "cached"
    assert payload["search_mode"] == "animal_law"
    assert payload["animal_focus"] is True
    assert payload["summary"]["verdict"].startswith("依目前公開資料可能")
    assert payload["evidence_cards"][0]["url"] == "https://example.org/cached-zoo"
    assert "exact_query_cache_hit" in caplog.text


def test_search_endpoint_triggers_official_image_refresh(tmp_path, monkeypatch) -> None:
    calls: list[tuple[str, list[dict]]] = []

    async def fake_search(self, entity_name: str, question: str, animal_focus: bool = False):
        return (
            ["台北市立動物園 官方網站"],
            [
                {
                    "url": "https://www.zoo.gov.taipei/",
                    "title": "台北市立動物園官方網站",
                    "content": "官方園區介紹",
                    "source": "Taipei Zoo",
                    "source_type": "official",
                    "published_date": "2026-04-02",
                }
            ],
            "live",
            SearchDiagnostics(providers=ProviderDiagnostics()),
        )

    async def fake_analyze(self, entity_name: str, question: str, raw_results: list[dict], animal_focus: bool = False):
        return (
            BalancedSummary(
                verdict="可先參考官方園區介紹。",
                confidence=60,
                supporting_points=["有官方說明頁。"],
                opposing_points=[],
                uncertain_points=[],
                suggested_follow_up=[],
            ),
            [
                EvidenceCard(
                    title="台北市立動物園官方網站",
                    url="https://www.zoo.gov.taipei/",
                    source="Taipei Zoo",
                    source_type="official",
                    snippet="官方園區介紹",
                    excerpt="官方園區介紹",
                    ai_summary="官方頁面",
                    extracted_at=None,
                    published_at="2026-04-02",
                    stance="neutral",
                    claim_type="official_statement",
                    evidence_strength="medium",
                    first_hand_score=90,
                    relevance_score=80,
                    credibility_score=90,
                    recency_label="recent",
                    duplicate_risk="low",
                    notes="",
                )
            ],
        )

    async def fake_refresh(self, entity_name: str, raw_results: list[dict]):
        calls.append((entity_name, raw_results))

    monkeypatch.setattr(search_module.SearchService, "search", fake_search)
    monkeypatch.setattr(search_module.AnalysisService, "analyze", fake_analyze)
    monkeypatch.setattr(search_module.OfficialImageService, "refresh_entity_page_images", fake_refresh)

    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()
    app = create_app(Settings(database_path=str(tmp_path / "image-refresh.db"), frontend_dist_dir=str(dist_dir)))

    with TestClient(app) as client:
        response = client.post(
            "/api/search",
            json={
                "entity_name": "台北市立動物園",
                "question": "有哪些官方資料可以參考？",
            },
        )

    assert response.status_code == 200
    assert calls
    assert calls[0][0] == "台北市立動物園"
    assert calls[0][1][0]["source_type"] == "official"


def test_snapshot_and_suggestions_endpoints_return_entity_data(tmp_path) -> None:
    db_path = tmp_path / "entity_page.db"
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()
    settings = Settings(database_path=str(db_path), frontend_dist_dir=str(dist_dir), bootstrap_seed_watchlist=True)
    persistence = PersistenceService(settings)
    persistence.initialize()
    summary = BalancedSummary(
        verdict="依目前公開資料可能與照護環境疑慮有關，仍需進一步查核。",
        confidence=73,
        supporting_points=["近期公開資料提到照護與環境議題。"],
        opposing_points=["目前也看到部分改善描述。"],
        uncertain_points=["仍需更多第一手資料。"],
        suggested_follow_up=["補查主管機關稽查資料。"],
    )
    cards = [
        EvidenceCard(
            title="台北市立動物園照護環境討論",
            url="https://example.org/cached-zoo",
            source="Example News",
            source_type="news",
            snippet="近期有公開資料提到收容密度、環境與照護問題。",
            excerpt="近期有公開資料提到收容密度、環境與照護問題。",
            ai_summary="摘要",
            extracted_at="2026-04-01T00:00:00+00:00",
            published_at="2026-03-30",
            stance="supporting",
            claim_type="animal_welfare",
            evidence_strength="medium",
            first_hand_score=45,
            relevance_score=82,
            credibility_score=68,
            recency_label="recent",
            duplicate_risk="low",
            notes="待人工複核",
        )
    ]
    query_id = persistence.save_search_run(
        entity_name="台北市立動物園",
        question="是否可能涉及動保法相關疑慮？",
        expanded_queries=["台北市立動物園 動保"],
        mode="live",
        search_mode="animal_law",
        animal_focus=True,
        summary=summary,
        evidence_cards=cards,
    )
    persistence.save_entity_summary_snapshot(
        entity_name="台北市立動物園",
        search_mode="animal_law",
        summary=summary,
        evidence_cards=cards,
        latest_query_id=query_id,
        source_window_days=30,
    )
    persistence.refresh_entity_question_suggestions(
        entity_name="台北市立動物園",
        search_mode="animal_law",
        latest_summary=summary,
    )

    app = create_app(settings)
    with TestClient(app) as client:
        snapshot_response = client.get("/api/entities/%E6%9C%A8%E6%9F%B5%E5%8B%95%E7%89%A9%E5%9C%92/snapshot?animal_focus=true")
        suggestions_response = client.get("/api/entities/%E5%8F%B0%E5%8C%97%E5%B8%82%E7%AB%8B%E5%8B%95%E7%89%A9%E5%9C%92/suggestions?animal_focus=true")

    assert snapshot_response.status_code == 200
    snapshot_payload = snapshot_response.json()
    assert snapshot_payload["entity_name"] == "台北市立動物園"
    assert snapshot_payload["animal_focus"] is True
    assert snapshot_payload["evidence_cards"][0]["url"] == "https://example.org/cached-zoo"

    assert suggestions_response.status_code == 200
    suggestions_payload = suggestions_response.json()
    assert suggestions_payload["entity_name"] == "台北市立動物園"
    assert suggestions_payload["animal_focus"] is True
    assert suggestions_payload["items"]