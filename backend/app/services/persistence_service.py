from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from app.config import Settings
from app.models.media import MediaFileResponse, MediaListResponse, MediaStatsResponse
from app.models.profile import (
    EntityListItem,
    EntityListResponse,
    EntityProfileResponse,
    RecentQueryItem,
    SourceBreakdownItem,
)
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

                CREATE TABLE IF NOT EXISTS media_files (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    entity_name TEXT NOT NULL,
                    file_name TEXT NOT NULL UNIQUE,
                    original_name TEXT NOT NULL,
                    media_type TEXT NOT NULL DEFAULT 'image',
                    mime_type TEXT NOT NULL,
                    file_size INTEGER NOT NULL DEFAULT 0,
                    width INTEGER,
                    height INTEGER,
                    duration_seconds REAL,
                    caption TEXT NOT NULL DEFAULT '',
                    uploader_ip TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE INDEX IF NOT EXISTS idx_media_entity ON media_files(entity_name);
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
            entity_row = self._find_entity_by_name_or_alias(connection, entity_name)
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
                aliases=self._load_aliases(entity_row["alias_json"]),
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

    def register_entity_alias(self, canonical_name: str, alias: str) -> int:
        with self._connect() as connection:
            entity_row = self._find_entity_by_name_or_alias(connection, canonical_name)
            if not entity_row:
                entity_id = self._upsert_entity(connection, canonical_name)
                entity_row = connection.execute(
                    "SELECT id, name, alias_json FROM entities WHERE id = ?",
                    (entity_id,),
                ).fetchone()

            aliases = self._load_aliases(entity_row["alias_json"])
            canonical_value = str(entity_row["name"])
            if alias != canonical_value and alias not in aliases:
                aliases.append(alias)
                connection.execute(
                    """
                    UPDATE entities
                    SET alias_json = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (json.dumps(sorted(aliases), ensure_ascii=False), int(entity_row["id"])),
                )
                connection.commit()
            return int(entity_row["id"])

    def list_entities(self, query: str | None = None, limit: int = 20) -> EntityListResponse:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    e.id,
                    e.name,
                    e.alias_json,
                    COUNT(DISTINCT q.id) AS total_queries,
                    COUNT(DISTINCT ec.source_id) AS total_sources
                FROM entities e
                LEFT JOIN search_queries q ON q.entity_id = e.id
                LEFT JOIN evidence_cards ec ON ec.query_id = q.id
                GROUP BY e.id, e.name, e.alias_json
                ORDER BY total_queries DESC, e.updated_at DESC, e.name ASC
                """
            ).fetchall()

            normalized_query = query.strip().lower() if query else None
            items: list[EntityListItem] = []
            for row in rows:
                aliases = self._load_aliases(row["alias_json"])
                if normalized_query:
                    haystack = " ".join([str(row["name"]), *aliases]).lower()
                    if normalized_query not in haystack:
                        continue
                items.append(
                    EntityListItem(
                        entity_name=str(row["name"]),
                        aliases=aliases,
                        total_queries=int(row["total_queries"] or 0),
                        total_sources=int(row["total_sources"] or 0),
                    )
                )
                if len(items) >= limit:
                    break

            return EntityListResponse(items=items)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _upsert_entity(self, connection: sqlite3.Connection, entity_name: str) -> int:
        existing = self._find_entity_by_name_or_alias(connection, entity_name)
        if existing:
            aliases = self._load_aliases(existing["alias_json"])
            canonical_name = str(existing["name"])
            if entity_name != canonical_name and entity_name not in aliases:
                aliases.append(entity_name)
                connection.execute(
                    """
                    UPDATE entities
                    SET alias_json = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (json.dumps(sorted(aliases), ensure_ascii=False), int(existing["id"])),
                )
            return int(existing["id"])

        cursor = connection.execute(
            "INSERT INTO entities (name) VALUES (?)",
            (entity_name,),
        )
        return int(cursor.lastrowid)

    def _find_entity_by_name_or_alias(
        self,
        connection: sqlite3.Connection,
        entity_name: str,
    ) -> sqlite3.Row | None:
        direct_match = connection.execute(
            "SELECT id, name, alias_json FROM entities WHERE name = ?",
            (entity_name,),
        ).fetchone()
        if direct_match:
            return direct_match

        rows = connection.execute(
            "SELECT id, name, alias_json FROM entities",
        ).fetchall()
        for row in rows:
            aliases = self._load_aliases(row["alias_json"])
            if entity_name in aliases:
                return row
        return None

    def _load_aliases(self, raw_aliases: str | None) -> list[str]:
        if not raw_aliases:
            return []
        try:
            parsed = json.loads(raw_aliases)
        except json.JSONDecodeError:
            return []
        return [item for item in parsed if isinstance(item, str)]

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


    # ── Media file methods ──────────────────────────────────────────

    def save_media_file(
        self,
        entity_name: str,
        file_name: str,
        original_name: str,
        media_type: str,
        mime_type: str,
        file_size: int,
        uploader_ip: str = "",
        caption: str = "",
        width: int | None = None,
        height: int | None = None,
        duration_seconds: float | None = None,
    ) -> int:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO media_files (
                    entity_name, file_name, original_name, media_type,
                    mime_type, file_size, width, height, duration_seconds,
                    caption, uploader_ip
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    entity_name, file_name, original_name, media_type,
                    mime_type, file_size, width, height, duration_seconds,
                    caption, uploader_ip,
                ),
            )
            connection.commit()
            return int(cursor.lastrowid)

    def get_media_file(self, file_id: int) -> MediaFileResponse | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM media_files WHERE id = ?", (file_id,)
            ).fetchone()
            if not row:
                return None
            return self._row_to_media_response(row)

    def list_media_files(
        self,
        entity_name: str | None = None,
        media_type: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> MediaListResponse:
        with self._connect() as connection:
            conditions: list[str] = []
            params: list[str | int] = []

            if entity_name:
                conditions.append("entity_name = ?")
                params.append(entity_name)
            if media_type:
                conditions.append("media_type = ?")
                params.append(media_type)

            where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

            total_row = connection.execute(
                f"SELECT COUNT(*) AS cnt FROM media_files {where}", params
            ).fetchone()
            total = int(total_row["cnt"]) if total_row else 0

            rows = connection.execute(
                f"SELECT * FROM media_files {where} ORDER BY id DESC LIMIT ? OFFSET ?",
                [*params, limit, offset],
            ).fetchall()

            items = [self._row_to_media_response(row) for row in rows]
            return MediaListResponse(items=items, total=total)

    def get_media_stats(self, entity_name: str | None = None) -> MediaStatsResponse:
        with self._connect() as connection:
            where = "WHERE entity_name = ?" if entity_name else ""
            params: list[str] = [entity_name] if entity_name else []

            row = connection.execute(
                f"""
                SELECT
                    COUNT(*) AS total_files,
                    COALESCE(SUM(file_size), 0) AS total_size_bytes,
                    COALESCE(SUM(CASE WHEN media_type = 'image' THEN 1 ELSE 0 END), 0) AS image_count,
                    COALESCE(SUM(CASE WHEN media_type = 'video' THEN 1 ELSE 0 END), 0) AS video_count
                FROM media_files {where}
                """,
                params,
            ).fetchone()

            return MediaStatsResponse(
                total_files=int(row["total_files"]) if row else 0,
                total_size_bytes=int(row["total_size_bytes"]) if row else 0,
                image_count=int(row["image_count"]) if row else 0,
                video_count=int(row["video_count"]) if row else 0,
            )

    def delete_media_file(self, file_id: int) -> bool:
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM media_files WHERE id = ?", (file_id,)
            )
            connection.commit()
            return cursor.rowcount > 0

    def _row_to_media_response(self, row: sqlite3.Row) -> MediaFileResponse:
        return MediaFileResponse(
            id=int(row["id"]),
            entity_name=str(row["entity_name"]),
            file_name=str(row["file_name"]),
            original_name=str(row["original_name"]),
            media_type=str(row["media_type"]),
            mime_type=str(row["mime_type"]),
            file_size=int(row["file_size"]),
            width=int(row["width"]) if row["width"] else None,
            height=int(row["height"]) if row["height"] else None,
            duration_seconds=float(row["duration_seconds"]) if row["duration_seconds"] else None,
            caption=str(row["caption"] or ""),
            uploader_ip=str(row["uploader_ip"] or ""),
            created_at=str(row["created_at"]),
            url=f"/api/media/file/{row['file_name']}",
        )