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
        search_mode="general",
        animal_focus=False,
        summary=summary,
        evidence_cards=cards,
    )

    connection = sqlite3.connect(db_path)
    entity_row = connection.execute("SELECT name FROM entities WHERE name = ?", ("測試園區",)).fetchone()
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


def test_persistence_service_merges_alias_into_existing_entity(tmp_path: Path) -> None:
    db_path = tmp_path / "test_alias.db"
    settings = Settings(database_path=str(db_path))
    service = PersistenceService(settings)
    service.initialize()

    summary = BalancedSummary(
        verdict="摘要",
        confidence=60,
        supporting_points=["支持"],
        opposing_points=["反對"],
        uncertain_points=["待確認"],
        suggested_follow_up=["補充查核"],
    )
    card = EvidenceCard(
        title="測試來源",
        url="https://example.org/alias",
        source="example.org",
        source_type="other",
        snippet="測試摘要",
        extracted_at="2026-03-25T00:00:00+00:00",
        published_at=None,
        stance="neutral",
        claim_type="general_reputation",
        evidence_strength="weak",
        first_hand_score=40,
        relevance_score=60,
        credibility_score=50,
        recency_label="unknown",
        duplicate_risk="low",
        notes="備註",
    )

    service.save_search_run(
        "流浪動物永續發展協會",
        "是否有爭議？",
        ["流浪動物永續發展協會 爭議"],
        "live",
        "general",
        False,
        summary,
        [card],
    )
    service.register_entity_alias("流浪動物永續發展協會", "TSSDA")
    service.save_search_run("TSSDA", "是否有爭議？", ["TSSDA 爭議"], "live", "general", False, summary, [card])

    profile = service.get_entity_profile("TSSDA")

    connection = sqlite3.connect(db_path)
    entity_count = connection.execute(
        "SELECT COUNT(*) FROM entities WHERE name = ?",
        ("流浪動物永續發展協會",),
    ).fetchone()[0]

    assert entity_count == 1
    assert profile is not None
    assert profile.entity_name == "流浪動物永續發展協會"
    assert "TSSDA" in profile.aliases


def test_persistence_service_lists_entities(tmp_path: Path) -> None:
    db_path = tmp_path / "test_list.db"
    settings = Settings(database_path=str(db_path))
    service = PersistenceService(settings)
    service.initialize()

    summary = BalancedSummary(
        verdict="摘要",
        confidence=70,
        supporting_points=["支持"],
        opposing_points=["反對"],
        uncertain_points=["待確認"],
        suggested_follow_up=["補充查核"],
    )
    card = EvidenceCard(
        title="來源",
        url="https://example.org/list",
        source="example.org",
        source_type="other",
        snippet="摘要",
        extracted_at="2026-03-25T00:00:00+00:00",
        published_at=None,
        stance="neutral",
        claim_type="general_reputation",
        evidence_strength="weak",
        first_hand_score=40,
        relevance_score=60,
        credibility_score=50,
        recency_label="unknown",
        duplicate_risk="low",
        notes="備註",
    )

    service.save_search_run("台北市立動物園", "是否有爭議？", ["台北市立動物園 爭議"], "live", "general", False, summary, [card])
    service.register_entity_alias("台北市立動物園", "木柵動物園")

    response = service.list_entities(query="木柵", limit=10)

    assert len(response.items) == 1
    assert response.items[0].entity_name == "台北市立動物園"
    assert "木柵動物園" in response.items[0].aliases


def test_persistence_service_caches_and_reads_raw_sources(tmp_path: Path) -> None:
    db_path = tmp_path / "test_cache.db"
    settings = Settings(database_path=str(db_path))
    service = PersistenceService(settings)
    service.initialize()

    cached_count = service.cache_raw_sources(
        [
            {
                "title": "快取來源",
                "url": "https://example.org/cache",
                "content": "這是已快取的原始內容",
                "source": "Example",
                "source_type": "news",
                "published_date": "2026-03-26",
                "fetched_at": "2026-03-27T00:00:00+00:00",
            }
        ]
    )

    cached = service.get_sources_by_urls(["https://example.org/cache"])

    assert cached_count == 1
    assert cached["https://example.org/cache"]["title"] == "快取來源"
    assert cached["https://example.org/cache"]["content"] == "這是已快取的原始內容"


def test_persistence_service_finds_relevant_cached_sources(tmp_path: Path) -> None:
    db_path = tmp_path / "test_cached_lookup.db"
    settings = Settings(database_path=str(db_path))
    service = PersistenceService(settings)
    service.initialize()

    summary = BalancedSummary(
        verdict="已有具體募資爭議資料。",
        confidence=74,
        supporting_points=["找到募資頁與討論。"],
        opposing_points=["仍需更多官方說明。"],
        uncertain_points=["尚待比對完整時間線。"],
        suggested_follow_up=["補查官方聲明。"],
    )
    service.save_search_run(
        entity_name="董旺旺狗園",
        question="募資爭議",
        expanded_queries=["site:flyingv.cc 董旺旺狗園", "董旺旺狗園 爭議"],
        mode="live",
        search_mode="general",
        animal_focus=False,
        summary=summary,
        evidence_cards=[
            EvidenceCard(
                title="浪浪飼料募資計畫 - flyingV",
                url="https://www.flyingv.cc/projects/14186",
                source="flyingV",
                source_type="other",
                snippet="董旺旺狗園 歷史募資專案與說明。",
                excerpt="董旺旺狗園 歷史募資專案與說明。",
                ai_summary="募資頁證據",
                extracted_at="2026-03-27T00:00:00+00:00",
                published_at="2018-01-01",
                stance="supporting",
                claim_type="general_reputation",
                evidence_strength="medium",
                first_hand_score=55,
                relevance_score=84,
                credibility_score=66,
                recency_label="dated",
                duplicate_risk="low",
                notes="曾被分析採信",
            )
        ],
    )

    service.cache_raw_sources(
        [
            {
                "title": "浪浪飼料募資計畫 - flyingV",
                "url": "https://www.flyingv.cc/projects/14186",
                "content": "董旺旺狗園 與董爸相關的募資說明與歷史專案。",
                "source": "flyingV",
                "source_type": "other",
                "published_date": "2018-01-01",
                "fetched_at": "2026-03-27T00:00:00+00:00",
            },
            {
                "title": "其他園區文章",
                "url": "https://example.org/other",
                "content": "完全無關內容",
                "source": "Example",
                "source_type": "news",
                "published_date": "2026-03-27",
                "fetched_at": "2026-03-27T00:00:00+00:00",
            },
            {
                "title": "董旺旺狗園 募資留言整理",
                "url": "https://example.org/noisy-commentary",
                "content": "董旺旺狗園 募資 爭議 留言整理，但這篇只是零散評論，沒有被分析採信。",
                "source": "Example Forum",
                "source_type": "forum",
                "published_date": "2026-03-28",
                "fetched_at": "2026-03-28T00:00:00+00:00",
            },
        ]
    )

    items = service.find_relevant_cached_sources(
        entity_name="董旺旺狗園",
        question="募資爭議",
        expanded_queries=["site:flyingv.cc 董旺旺狗園", "董旺旺狗園 爭議"],
        limit=10,
    )

    assert len(items) == 1
    assert items[0]["url"] == "https://www.flyingv.cc/projects/14186"


def test_persistence_service_ignores_raw_only_cached_sources_without_evidence_backing(tmp_path: Path) -> None:
    db_path = tmp_path / "test_cached_lookup_raw_only.db"
    settings = Settings(database_path=str(db_path))
    service = PersistenceService(settings)
    service.initialize()

    service.cache_raw_sources(
        [
            {
                "title": "董旺旺狗園 募資留言整理",
                "url": "https://example.org/raw-only-commentary",
                "content": "董旺旺狗園 募資 爭議 留言整理，但這篇沒有被分析採信。",
                "source": "Example Forum",
                "source_type": "forum",
                "published_date": "2026-03-28",
                "fetched_at": "2026-03-28T00:00:00+00:00",
            }
        ]
    )

    items = service.find_relevant_cached_sources(
        entity_name="董旺旺狗園",
        question="募資爭議",
        expanded_queries=["董旺旺狗園 募資", "董旺旺狗園 爭議"],
        limit=10,
    )

    assert items == []


def test_persistence_service_bootstraps_builtin_watchlist(tmp_path: Path) -> None:
    db_path = tmp_path / "test_watchlist.db"
    settings = Settings(database_path=str(db_path), bootstrap_seed_watchlist=True)
    service = PersistenceService(settings)
    service.initialize()

    connection = sqlite3.connect(db_path)
    entity_row = connection.execute(
        "SELECT name, entity_type FROM entities WHERE name = ?",
        ("台北市立動物園",),
    ).fetchone()
    watchlist_row = connection.execute(
        "SELECT priority, refresh_interval_hours, default_mode FROM entity_watchlists ew JOIN entities e ON e.id = ew.entity_id WHERE e.name = ?",
        ("台北市立動物園",),
    ).fetchone()
    non_zoo_watchlist_row = connection.execute(
        "SELECT 1 FROM entity_watchlists ew JOIN entities e ON e.id = ew.entity_id WHERE e.name = ?",
        ("台北市動物之家",),
    ).fetchone()
    keyword_rows = connection.execute(
        "SELECT keyword FROM entity_keywords ek JOIN entities e ON e.id = ek.entity_id WHERE e.name = ? ORDER BY keyword ASC",
        ("台北市立動物園",),
    ).fetchall()

    assert entity_row == ("台北市立動物園", "zoo")
    assert watchlist_row == (1, 24, "general")
    assert non_zoo_watchlist_row is None
    assert ("木柵動物園",) in keyword_rows


def test_persistence_service_saves_snapshot_and_question_suggestions(tmp_path: Path) -> None:
    db_path = tmp_path / "test_snapshot.db"
    settings = Settings(database_path=str(db_path), bootstrap_seed_watchlist=True)
    service = PersistenceService(settings)
    service.initialize()

    summary = BalancedSummary(
        verdict="依目前公開資料可能與照護環境疑慮有關，仍需進一步查核。",
        confidence=74,
        supporting_points=["近期有公開資料提到收容密度與氣味問題。"],
        opposing_points=["目前也有資料提到部分改善措施。"],
        uncertain_points=["仍需更多第一手或官方資料交叉確認。"],
        suggested_follow_up=["補查主管機關近期稽查與改善紀錄。"],
    )
    cards = [
        EvidenceCard(
            title="台北市立動物園照護環境討論",
            url="https://example.org/zoo-care",
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

    query_id = service.save_search_run(
        entity_name="台北市立動物園",
        question="是否可能涉及動保法相關疑慮？",
        expanded_queries=["台北市立動物園 動保"],
        mode="live",
        search_mode="animal_law",
        animal_focus=True,
        summary=summary,
        evidence_cards=cards,
    )
    service.save_entity_summary_snapshot(
        entity_name="台北市立動物園",
        search_mode="animal_law",
        summary=summary,
        evidence_cards=cards,
        latest_query_id=query_id,
        source_window_days=30,
    )
    service.refresh_entity_question_suggestions(
        entity_name="台北市立動物園",
        search_mode="animal_law",
        latest_summary=summary,
    )

    snapshot = service.get_entity_summary_snapshot("木柵動物園", "animal_law")
    suggestions = service.get_entity_question_suggestions("台北市立動物園", "animal_law")

    assert snapshot is not None
    assert snapshot.entity_name == "台北市立動物園"
    assert snapshot.animal_focus is True
    assert snapshot.summary.verdict.startswith("依目前公開資料可能")
    assert str(snapshot.evidence_cards[0].url) == "https://example.org/zoo-care"
    assert suggestions.items
    assert any("動保法" in item.question_text or "照護" in item.question_text for item in suggestions.items)


def test_persistence_service_keeps_snapshot_history_and_deduplicates_identical_versions(tmp_path: Path) -> None:
    db_path = tmp_path / "test_snapshot_history.db"
    settings = Settings(database_path=str(db_path), bootstrap_seed_watchlist=True)
    service = PersistenceService(settings)
    service.initialize()

    base_summary = BalancedSummary(
        verdict="第一版摘要",
        confidence=70,
        supporting_points=["第一版支持點"],
        opposing_points=["第一版反駁點"],
        uncertain_points=["第一版待確認"],
        suggested_follow_up=["第一版追問"],
    )
    next_summary = BalancedSummary(
        verdict="第二版摘要",
        confidence=82,
        supporting_points=["第二版支持點"],
        opposing_points=["第二版反駁點"],
        uncertain_points=["第二版待確認"],
        suggested_follow_up=["第二版追問"],
    )
    first_cards = [
        EvidenceCard(
            title="第一版來源",
            url="https://example.org/history-v1",
            source="Example News",
            source_type="news",
            snippet="第一版摘要",
            excerpt="第一版摘要",
            ai_summary="第一版",
            extracted_at="2026-04-01T00:00:00+00:00",
            published_at="2026-04-01",
            stance="neutral",
            claim_type="animal_welfare",
            evidence_strength="medium",
            first_hand_score=40,
            relevance_score=70,
            credibility_score=65,
            recency_label="recent",
            duplicate_risk="low",
            notes="v1",
        )
    ]
    second_cards = [
        EvidenceCard(
            title="第二版來源",
            url="https://example.org/history-v2",
            source="Example News",
            source_type="news",
            snippet="第二版摘要",
            excerpt="第二版摘要",
            ai_summary="第二版",
            extracted_at="2026-04-02T00:00:00+00:00",
            published_at="2026-04-02",
            stance="supporting",
            claim_type="animal_welfare",
            evidence_strength="strong",
            first_hand_score=52,
            relevance_score=88,
            credibility_score=71,
            recency_label="recent",
            duplicate_risk="low",
            notes="v2",
        )
    ]

    first_query_id = service.save_search_run(
        entity_name="台北市立動物園",
        question="第一版問題",
        expanded_queries=["台北市立動物園 第一版"],
        mode="live",
        search_mode="animal_law",
        animal_focus=True,
        summary=base_summary,
        evidence_cards=first_cards,
    )
    service.save_entity_summary_snapshot(
        entity_name="台北市立動物園",
        search_mode="animal_law",
        summary=base_summary,
        evidence_cards=first_cards,
        latest_query_id=first_query_id,
        source_window_days=30,
    )

    second_query_id = service.save_search_run(
        entity_name="台北市立動物園",
        question="第二版問題",
        expanded_queries=["台北市立動物園 第二版"],
        mode="live",
        search_mode="animal_law",
        animal_focus=True,
        summary=next_summary,
        evidence_cards=second_cards,
    )
    service.save_entity_summary_snapshot(
        entity_name="台北市立動物園",
        search_mode="animal_law",
        summary=next_summary,
        evidence_cards=second_cards,
        latest_query_id=second_query_id,
        source_window_days=30,
    )
    service.save_entity_summary_snapshot(
        entity_name="台北市立動物園",
        search_mode="animal_law",
        summary=next_summary,
        evidence_cards=second_cards,
        latest_query_id=second_query_id,
        source_window_days=30,
    )

    latest_snapshot = service.get_entity_summary_snapshot("木柵動物園", "animal_law")
    connection = sqlite3.connect(db_path)
    rows = connection.execute(
        "SELECT summary_json FROM entity_summary_snapshots WHERE entity_id = (SELECT id FROM entities WHERE name = ?) AND mode = ? ORDER BY id ASC",
        ("台北市立動物園", "animal_law"),
    ).fetchall()

    assert latest_snapshot is not None
    assert latest_snapshot.summary.verdict == "第二版摘要"
    assert str(latest_snapshot.evidence_cards[0].url) == "https://example.org/history-v2"
    assert len(rows) == 2
    assert json.loads(rows[0][0])["verdict"] == "第一版摘要"
    assert json.loads(rows[1][0])["verdict"] == "第二版摘要"


def test_persistence_service_lists_due_watchlist_entities_and_marks_success(tmp_path: Path) -> None:
    db_path = tmp_path / "test_watchlist_due.db"
    settings = Settings(database_path=str(db_path), bootstrap_seed_watchlist=True)
    service = PersistenceService(settings)
    service.initialize()

    due_items = service.list_due_watchlist_entities(limit=3)

    assert due_items
    assert all(item.entity_type == "zoo" for item in due_items)
    target = next(item for item in due_items if item.entity_name == "台北市立動物園")
    assert target.default_mode == "general"
    assert "木柵動物園" in target.aliases

    service.mark_watchlist_refresh_success("台北市立動物園")

    due_after_success = service.list_due_watchlist_entities(limit=20)
    assert all(item.entity_name != "台北市立動物園" for item in due_after_success)
