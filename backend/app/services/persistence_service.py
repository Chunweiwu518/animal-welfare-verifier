from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from app.config import Settings
from app.models.profile import EntityProfileResponse, RecentQueryItem, SourceBreakdownItem
from app.models.search import BalancedSummary, EvidenceCard


class PersistenceService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.db_path = Path(settings.database_path)

    def initialize(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(
                """
                PRAGMA foreign_keys = ON;

                CREATE TABLE IF NOT EXISTS entities (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    entity_type TEXT NOT NULL DEFAULT 'organization',
                    alias_json TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS search_queries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    entity_id INTEGER NOT NULL,
                    question TEXT NOT NULL,
                    normalized_question TEXT NOT NULL,
                    expanded_queries_json TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (entity_id) REFERENCES entities(id)
                );

                CREATE TABLE IF NOT EXISTS sources (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    url TEXT NOT NULL UNIQUE,
                    domain TEXT NOT NULL,
                    site_name TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    author TEXT,
                    published_at TEXT,
                    fetched_at TEXT,
                    raw_title TEXT NOT NULL,
                    raw_content TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS query_summaries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    query_id INTEGER NOT NULL UNIQUE,
                    verdict TEXT NOT NULL,
                    confidence INTEGER NOT NULL,
                    supporting_points_json TEXT NOT NULL,
                    opposing_points_json TEXT NOT NULL,
                    uncertain_points_json TEXT NOT NULL,
                    suggested_follow_up_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (query_id) REFERENCES search_queries(id)
                );

                CREATE TABLE IF NOT EXISTS evidence_cards (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    query_id INTEGER NOT NULL,
                    source_id INTEGER NOT NULL,
                    title TEXT NOT NULL,
                    snippet TEXT NOT NULL,
                    stance TEXT NOT NULL,
                    claim_type TEXT NOT NULL,
                    evidence_strength TEXT NOT NULL,
                    first_hand_score INTEGER NOT NULL,
                    relevance_score INTEGER NOT NULL,
                    credibility_score INTEGER NOT NULL,
                    recency_label TEXT NOT NULL,
                    duplicate_risk TEXT NOT NULL,
                    notes TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (query_id) REFERENCES search_queries(id),
                    FOREIGN KEY (source_id) REFERENCES sources(id)
                );

                CREATE TABLE IF NOT EXISTS review_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    evidence_card_id INTEGER NOT NULL,
                    review_status TEXT NOT NULL DEFAULT 'pending',
                    review_reason TEXT,
                    reviewed_by TEXT,
                    reviewed_at TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (evidence_card_id) REFERENCES evidence_cards(id)
                );
                """
            )

    def save_search_run(
        self,
        entity_name: str,
        question: str,
        expanded_queries: list[str],
        mode: str,
        summary: BalancedSummary,
        evidence_cards: list[EvidenceCard],
    ) -> int:
        with self._connect() as connection:
            entity_id = self._upsert_entity(connection, entity_name)
            query_id = self._insert_query(connection, entity_id, question, expanded_queries, mode)
            self._insert_summary(connection, query_id, summary)

            for card in evidence_cards:
                source_id = self._upsert_source(connection, card)
                connection.execute(
                    """
                    INSERT INTO evidence_cards (
                        query_id,
                        source_id,
                        title,
                        snippet,
                        stance,
                        claim_type,
                        evidence_strength,
                        first_hand_score,
                        relevance_score,
                        credibility_score,
                        recency_label,
                        duplicate_risk,
                        notes
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        query_id,
                        source_id,
                        card.title,
                        card.snippet,
                        card.stance,
                        card.claim_type,
                        card.evidence_strength,
                        card.first_hand_score,
                        card.relevance_score,
                        card.credibility_score,
                        card.recency_label,
                        card.duplicate_risk,
                        card.notes,
                    ),
                )

            connection.commit()
            return query_id

    def get_entity_profile(self, entity_name: str) -> EntityProfileResponse | None:
        with self._connect() as connection:
            entity_row = connection.execute(
                "SELECT id, name FROM entities WHERE name = ?",
                (entity_name,),
            ).fetchone()
            if not entity_row:
                return None

            entity_id = int(entity_row["id"])
            aggregate_row = connection.execute(
                """
                SELECT
                    COUNT(DISTINCT q.id) AS total_queries,
                    COUNT(DISTINCT ec.source_id) AS total_sources,
                    COALESCE(ROUND(AVG(qs.confidence)), 0) AS average_confidence,
                    COALESCE(ROUND(AVG(ec.credibility_score)), 0) AS average_credibility
                FROM search_queries q
                LEFT JOIN query_summaries qs ON qs.query_id = q.id
                LEFT JOIN evidence_cards ec ON ec.query_id = q.id
                WHERE q.entity_id = ?
                """,
                (entity_id,),
            ).fetchone()

            source_rows = connection.execute(
                """
                SELECT s.source_type, COUNT(*) AS count
                FROM evidence_cards ec
                JOIN sources s ON s.id = ec.source_id
                JOIN search_queries q ON q.id = ec.query_id
                WHERE q.entity_id = ?
                GROUP BY s.source_type
                ORDER BY count DESC, s.source_type ASC
                """,
                (entity_id,),
            ).fetchall()

            recent_rows = connection.execute(
                """
                SELECT q.id AS query_id, q.question, q.mode, q.created_at, COALESCE(qs.confidence, 0) AS confidence
                FROM search_queries q
                LEFT JOIN query_summaries qs ON qs.query_id = q.id
                WHERE q.entity_id = ?
                ORDER BY q.id DESC
                LIMIT 5
                """,
                (entity_id,),
            ).fetchall()

            return EntityProfileResponse(
                entity_name=str(entity_row["name"]),
                total_queries=int(aggregate_row["total_queries"] or 0),
                total_sources=int(aggregate_row["total_sources"] or 0),
                average_confidence=int(aggregate_row["average_confidence"] or 0),
                average_credibility=int(aggregate_row["average_credibility"] or 0),
                source_breakdown=[
                    SourceBreakdownItem(
                        source_type=str(row["source_type"]),
                        count=int(row["count"]),
                    )
                    for row in source_rows
                ],
                recent_queries=[
                    RecentQueryItem(
                        query_id=int(row["query_id"]),
                        question=str(row["question"]),
                        mode=str(row["mode"]),
                        confidence=int(row["confidence"]),
                        created_at=str(row["created_at"]),
                    )
                    for row in recent_rows
                ],
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _upsert_entity(self, connection: sqlite3.Connection, entity_name: str) -> int:
        existing = connection.execute(
            "SELECT id FROM entities WHERE name = ?",
            (entity_name,),
        ).fetchone()
        if existing:
            return int(existing["id"])

        cursor = connection.execute(
            "INSERT INTO entities (name) VALUES (?)",
            (entity_name,),
        )
        return int(cursor.lastrowid)

    def _insert_query(
        self,
        connection: sqlite3.Connection,
        entity_id: int,
        question: str,
        expanded_queries: list[str],
        mode: str,
    ) -> int:
        cursor = connection.execute(
            """
            INSERT INTO search_queries (
                entity_id,
                question,
                normalized_question,
                expanded_queries_json,
                mode
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                entity_id,
                question,
                question.strip().lower(),
                json.dumps(expanded_queries, ensure_ascii=False),
                mode,
            ),
        )
        return int(cursor.lastrowid)

    def _insert_summary(
        self,
        connection: sqlite3.Connection,
        query_id: int,
        summary: BalancedSummary,
    ) -> None:
        connection.execute(
            """
            INSERT INTO query_summaries (
                query_id,
                verdict,
                confidence,
                supporting_points_json,
                opposing_points_json,
                uncertain_points_json,
                suggested_follow_up_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                query_id,
                summary.verdict,
                summary.confidence,
                json.dumps(summary.supporting_points, ensure_ascii=False),
                json.dumps(summary.opposing_points, ensure_ascii=False),
                json.dumps(summary.uncertain_points, ensure_ascii=False),
                json.dumps(summary.suggested_follow_up, ensure_ascii=False),
            ),
        )

    def _upsert_source(self, connection: sqlite3.Connection, card: EvidenceCard) -> int:
        existing = connection.execute(
            "SELECT id FROM sources WHERE url = ?",
            (str(card.url),),
        ).fetchone()

        payload = (
            self._domain_from_url(str(card.url)),
            card.source,
            card.source_type,
            card.published_at,
            card.extracted_at,
            card.title,
            card.snippet,
            str(card.url),
        )

        if existing:
            connection.execute(
                """
                UPDATE sources
                SET domain = ?,
                    site_name = ?,
                    source_type = ?,
                    published_at = COALESCE(?, published_at),
                    fetched_at = COALESCE(?, fetched_at),
                    raw_title = ?,
                    raw_content = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE url = ?
                """,
                payload,
            )
            return int(existing["id"])

        cursor = connection.execute(
            """
            INSERT INTO sources (
                url,
                domain,
                site_name,
                source_type,
                published_at,
                fetched_at,
                raw_title,
                raw_content
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(card.url),
                self._domain_from_url(str(card.url)),
                card.source,
                card.source_type,
                card.published_at,
                card.extracted_at,
                card.title,
                card.snippet,
            ),
        )
        return int(cursor.lastrowid)

    def _domain_from_url(self, url: str) -> str:
        return url.split("/")[2] if "://" in url else url
