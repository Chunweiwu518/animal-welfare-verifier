import asyncio
import sqlite3
from pathlib import Path

from app.config import Settings
from app.models.search import BalancedSummary, EvidenceCard, ProviderDiagnostics, SearchDiagnostics
from app.services.persistence_service import PersistenceService
from app.services.watchlist_refresh_service import WatchlistRefreshService


class FakeSearchService:
    def __init__(self) -> None:
        self.force_live_calls: list[bool] = []

    async def search(self, entity_name: str, question: str, animal_focus: bool = False, force_live: bool = False):
        self.force_live_calls.append(force_live)
        return (
            [f"{entity_name} {'動保' if animal_focus else '評價'}"],
            [
                {
                    "url": f"https://example.org/{entity_name}",
                    "title": f"{entity_name} 公開資料整理",
                    "content": "近期有公開資料提到照護環境、管理與改善措施。",
                    "source": "Example News",
                    "source_type": "news",
                    "published_date": "2026-04-01",
                }
            ],
            "live",
            SearchDiagnostics(providers=ProviderDiagnostics()),
        )


class FakeAnalysisService:
    async def analyze(self, entity_name: str, question: str, raw_results: list[dict], animal_focus: bool = False):
        return (
            BalancedSummary(
                verdict="依目前公開資料可能與照護環境疑慮有關，仍需進一步查核。",
                confidence=76,
                supporting_points=["近期公開資料提到照護與環境議題。"],
                opposing_points=["也看到部分改善資訊。"],
                uncertain_points=["仍需更多第一手資料。"],
                suggested_follow_up=["補查主管機關稽查資料。"],
            ),
            [
                EvidenceCard(
                    title=f"{entity_name} 公開資料整理",
                    url=f"https://example.org/{entity_name}",
                    source="Example News",
                    source_type="news",
                    snippet="近期有公開資料提到照護環境、管理與改善措施。",
                    excerpt="近期有公開資料提到照護環境、管理與改善措施。",
                    ai_summary="摘要",
                    extracted_at="2026-04-01T00:00:00+00:00",
                    published_at="2026-04-01",
                    stance="supporting",
                    claim_type="animal_welfare" if animal_focus else "general_reputation",
                    evidence_strength="medium",
                    first_hand_score=42,
                    relevance_score=81,
                    credibility_score=67,
                    recency_label="recent",
                    duplicate_risk="low",
                    notes="待人工複核",
                )
            ],
        )


class FailingSearchService:
    async def search(self, entity_name: str, question: str, animal_focus: bool = False, force_live: bool = False):
        raise RuntimeError(f"failed for {entity_name}")


def test_watchlist_refresh_service_refreshes_due_entities_and_updates_snapshots(tmp_path: Path) -> None:
    db_path = tmp_path / "refresh.db"
    settings = Settings(database_path=str(db_path), bootstrap_seed_watchlist=True)
    persistence = PersistenceService(settings)
    persistence.initialize()
    fake_search_service = FakeSearchService()
    refresh_service = WatchlistRefreshService(
        settings,
        persistence_service=persistence,
        search_service=fake_search_service,
        analysis_service=FakeAnalysisService(),
    )

    result = asyncio.run(
        refresh_service.refresh_due_entities(limit=1, entity_names=["台北市立動物園"], include_modes=["general"])
    )

    snapshot = persistence.get_entity_summary_snapshot("台北市立動物園", "general")
    suggestions = persistence.get_entity_question_suggestions("台北市立動物園", "general")
    connection = sqlite3.connect(db_path)
    watchlist_row = connection.execute(
        "SELECT last_success_at, next_crawl_at, last_error_message FROM entity_watchlists ew JOIN entities e ON e.id = ew.entity_id WHERE e.name = ?",
        ("台北市立動物園",),
    ).fetchone()

    assert result.processed == 1
    assert result.succeeded == 1
    assert result.failed == 0
    assert snapshot is not None
    assert snapshot.animal_focus is False
    assert suggestions is not None and suggestions.items
    assert watchlist_row[0] is not None
    assert watchlist_row[1] is not None
    assert watchlist_row[2] in (None, "")
    assert fake_search_service.force_live_calls
    assert all(value is True for value in fake_search_service.force_live_calls)


def test_watchlist_refresh_service_records_failures(tmp_path: Path) -> None:
    db_path = tmp_path / "refresh_fail.db"
    settings = Settings(database_path=str(db_path), bootstrap_seed_watchlist=True)
    persistence = PersistenceService(settings)
    persistence.initialize()
    refresh_service = WatchlistRefreshService(
        settings,
        persistence_service=persistence,
        search_service=FailingSearchService(),
        analysis_service=FakeAnalysisService(),
    )

    result = asyncio.run(
        refresh_service.refresh_due_entities(limit=1, entity_names=["台北市立動物園"], include_modes=["general"])
    )

    connection = sqlite3.connect(db_path)
    watchlist_row = connection.execute(
        "SELECT last_error_at, last_error_message, next_crawl_at FROM entity_watchlists ew JOIN entities e ON e.id = ew.entity_id WHERE e.name = ?",
        ("台北市立動物園",),
    ).fetchone()

    assert result.processed == 1
    assert result.succeeded == 0
    assert result.failed == 1
    assert watchlist_row[0] is not None
    assert "failed for 台北市立動物園" in (watchlist_row[1] or "")
    assert watchlist_row[2] is not None