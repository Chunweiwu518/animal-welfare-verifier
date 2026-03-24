import json
import sqlite3
from pathlib import Path

from app.config import Settings
from app.models.search import BalancedSummary, EvidenceCard
from app.services.persistence_service import PersistenceService


def test_persistence_service_saves_search_run(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    settings = Settings(database_path=str(db_path))
    service = PersistenceService(settings)
    service.initialize()

    summary = BalancedSummary(
        verdict="目前資料正反並存。",
        confidence=72,
        supporting_points=["支持點"],
        opposing_points=["反駁點"],
        uncertain_points=["待確認點"],
        suggested_follow_up=["再查近期官方聲明"],
    )
    cards = [
        EvidenceCard(
            title="測試來源",
            url="https://example.org/post",
            source="example.org",
            source_type="other",
            snippet="這是一段測試摘要",
            extracted_at="2026-03-24T12:00:00+00:00",
            published_at="2026-03-20",
            stance="neutral",
            claim_type="general_reputation",
            evidence_strength="weak",
            first_hand_score=40,
            relevance_score=66,
            credibility_score=58,
            recency_label="recent",
            duplicate_risk="low",
            notes="測試備註",
        )
    ]

    query_id = service.save_search_run(
        entity_name="測試園區",
        question="是否有爭議？",
        expanded_queries=["測試園區 是否有爭議？", "測試園區 爭議"],
        mode="live",
        summary=summary,
        evidence_cards=cards,
    )

    connection = sqlite3.connect(db_path)
    entity_row = connection.execute("SELECT name FROM entities").fetchone()
    query_row = connection.execute(
        "SELECT question, expanded_queries_json, mode FROM search_queries WHERE id = ?",
        (query_id,),
    ).fetchone()
    source_row = connection.execute(
        "SELECT url, published_at FROM sources",
    ).fetchone()
    evidence_row = connection.execute(
        "SELECT credibility_score, relevance_score FROM evidence_cards",
    ).fetchone()

    assert entity_row == ("測試園區",)
    assert query_row[0] == "是否有爭議？"
    assert json.loads(query_row[1]) == ["測試園區 是否有爭議？", "測試園區 爭議"]
    assert query_row[2] == "live"
    assert source_row == ("https://example.org/post", "2026-03-20")
    assert evidence_row == (58, 66)
