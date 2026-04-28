from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from app.config import Settings
from app.models.media import MediaFileResponse, MediaListResponse, MediaStatsResponse
from app.models.profile import (
    EntityCommentResponse,
    EntityPageImageItem,
    EntityPageResponse,
    EntityQuestionSuggestionItem,
    EntityQuestionSuggestionsResponse,
    EntityListItem,
    EntityListResponse,
    EntityProfileResponse,
    EntitySummarySnapshotResponse,
    RecentQueryItem,
    SourceBreakdownItem,
)
from app.models.search import BalancedSummary, EvidenceCard
from app.models.watchlist import WatchlistEntity
from app.seed_data import ENTITY_PAGE_SEED, WATCHLIST_SEED, question_templates_for

logger = logging.getLogger(__name__)


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
                    search_mode TEXT NOT NULL DEFAULT 'general',
                    animal_focus INTEGER NOT NULL DEFAULT 0,
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

                CREATE TABLE IF NOT EXISTS entity_watchlists (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    entity_id INTEGER NOT NULL UNIQUE,
                    is_active INTEGER NOT NULL DEFAULT 1,
                    priority INTEGER NOT NULL DEFAULT 3,
                    refresh_interval_hours INTEGER NOT NULL DEFAULT 24,
                    default_mode TEXT NOT NULL DEFAULT 'general',
                    last_crawled_at TEXT,
                    next_crawl_at TEXT,
                    last_success_at TEXT,
                    last_error_at TEXT,
                    last_error_message TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (entity_id) REFERENCES entities(id)
                );

                CREATE TABLE IF NOT EXISTS entity_keywords (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    entity_id INTEGER NOT NULL,
                    keyword TEXT NOT NULL,
                    keyword_type TEXT NOT NULL DEFAULT 'alias',
                    weight INTEGER NOT NULL DEFAULT 50,
                    is_active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(entity_id, keyword),
                    FOREIGN KEY (entity_id) REFERENCES entities(id)
                );

                CREATE TABLE IF NOT EXISTS entity_summary_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    entity_id INTEGER NOT NULL,
                    mode TEXT NOT NULL,
                    snapshot_hash TEXT NOT NULL DEFAULT '',
                    summary_json TEXT NOT NULL,
                    evidence_cards_json TEXT NOT NULL,
                    source_window_days INTEGER NOT NULL DEFAULT 30,
                    source_count INTEGER NOT NULL DEFAULT 0,
                    latest_query_id INTEGER,
                    generated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(entity_id, mode, snapshot_hash),
                    FOREIGN KEY (entity_id) REFERENCES entities(id),
                    FOREIGN KEY (latest_query_id) REFERENCES search_queries(id)
                );

                CREATE TABLE IF NOT EXISTS entity_question_suggestions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    entity_id INTEGER NOT NULL,
                    mode TEXT NOT NULL,
                    category TEXT NOT NULL,
                    question_text TEXT NOT NULL,
                    confidence_score INTEGER NOT NULL DEFAULT 70,
                    generated_from TEXT NOT NULL DEFAULT 'seed',
                    is_active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(entity_id, mode, category, question_text),
                    FOREIGN KEY (entity_id) REFERENCES entities(id)
                );

                CREATE TABLE IF NOT EXISTS entity_page_profiles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    entity_id INTEGER NOT NULL UNIQUE,
                    headline TEXT NOT NULL DEFAULT '',
                    introduction TEXT NOT NULL DEFAULT '',
                    location TEXT NOT NULL DEFAULT '',
                    cover_image_url TEXT NOT NULL DEFAULT '',
                    cover_image_alt TEXT NOT NULL DEFAULT '',
                    gallery_json TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (entity_id) REFERENCES entities(id)
                );

                CREATE TABLE IF NOT EXISTS entity_comments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    entity_id INTEGER NOT NULL,
                    comment TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (entity_id) REFERENCES entities(id)
                );

                CREATE TABLE IF NOT EXISTS reviews (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    entity_id INTEGER NOT NULL,
                    platform TEXT NOT NULL,
                    author TEXT,
                    content TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    sentiment TEXT,
                    rating INTEGER,
                    source_url TEXT NOT NULL,
                    parent_title TEXT,
                    likes INTEGER NOT NULL DEFAULT 0,
                    published_at TEXT,
                    fetched_at TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (entity_id) REFERENCES entities(id)
                );

                CREATE TABLE IF NOT EXISTS pipeline_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    pipeline_name TEXT NOT NULL,
                    entity_name TEXT,
                    started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    finished_at TEXT,
                    status TEXT NOT NULL DEFAULT 'running',
                    reviews_written INTEGER NOT NULL DEFAULT 0,
                    error_message TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE INDEX IF NOT EXISTS idx_reviews_entity_platform ON reviews(entity_id, platform);
                CREATE INDEX IF NOT EXISTS idx_reviews_entity_published ON reviews(entity_id, published_at DESC);
                CREATE UNIQUE INDEX IF NOT EXISTS idx_reviews_dedup ON reviews(entity_id, platform, content_hash);
                CREATE INDEX IF NOT EXISTS idx_pipeline_runs_name ON pipeline_runs(pipeline_name, started_at DESC);
                CREATE INDEX IF NOT EXISTS idx_media_entity ON media_files(entity_name);
                CREATE INDEX IF NOT EXISTS idx_snapshots_entity_mode ON entity_summary_snapshots(entity_id, mode);
                CREATE INDEX IF NOT EXISTS idx_question_suggestions_entity_mode ON entity_question_suggestions(entity_id, mode, is_active);
                CREATE INDEX IF NOT EXISTS idx_entity_comments_entity_id ON entity_comments(entity_id, id DESC);
                """
            )
            self._ensure_entity_summary_snapshot_history(connection)
            self._ensure_search_query_columns(connection)
            self._ensure_review_analysis_columns(connection)
            self._ensure_user_tables(connection)
            self._ensure_comment_user_column(connection)
            self._ensure_review_comments_table(connection)
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_snapshots_entity_mode ON entity_summary_snapshots(entity_id, mode, generated_at DESC)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_search_queries_entity_mode ON search_queries(entity_id, search_mode, created_at DESC)"
            )
            if self.settings.bootstrap_seed_watchlist:
                self._bootstrap_builtin_watchlist(connection)

    def save_search_run(
        self,
        entity_name: str,
        question: str,
        expanded_queries: list[str],
        mode: str,
        search_mode: str,
        animal_focus: bool,
        summary: BalancedSummary,
        evidence_cards: list[EvidenceCard],
    ) -> int:
        with self._connect() as connection:
            entity_id = self._upsert_entity(connection, entity_name)
            self._auto_enroll_watchlist(connection, entity_id, search_mode)
            query_id = self._insert_query(
                connection,
                entity_id,
                question,
                expanded_queries,
                mode,
                search_mode,
                animal_focus,
            )
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

    def cache_raw_sources(self, raw_results: list[dict]) -> int:
        cached_count = 0
        with self._connect() as connection:
            for item in raw_results:
                url = str(item.get("url") or "").strip()
                if not url:
                    continue
                connection.execute(
                    """
                    INSERT INTO sources (
                        url,
                        domain,
                        site_name,
                        source_type,
                        author,
                        published_at,
                        fetched_at,
                        raw_title,
                        raw_content
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(url) DO UPDATE SET
                        domain = excluded.domain,
                        site_name = COALESCE(NULLIF(excluded.site_name, ''), site_name),
                        source_type = COALESCE(NULLIF(excluded.source_type, ''), source_type),
                        author = COALESCE(NULLIF(excluded.author, ''), author),
                        published_at = COALESCE(excluded.published_at, published_at),
                        fetched_at = COALESCE(excluded.fetched_at, fetched_at),
                        raw_title = COALESCE(NULLIF(excluded.raw_title, ''), raw_title),
                        raw_content = COALESCE(NULLIF(excluded.raw_content, ''), raw_content),
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    (
                        url,
                        self._domain_from_url(url),
                        str(item.get("source") or self._domain_from_url(url)),
                        str(item.get("source_type") or "other"),
                        str(item.get("author") or "") or None,
                        item.get("published_date"),
                        item.get("fetched_at"),
                        str(item.get("title") or ""),
                        str(item.get("content") or item.get("raw_content") or item.get("snippet") or ""),
                    ),
                )
                cached_count += 1

            connection.commit()
        return cached_count

    def get_sources_by_urls(self, urls: list[str]) -> dict[str, dict[str, str | None]]:
        normalized_urls = [url.strip() for url in urls if url.strip()]
        if not normalized_urls:
            return {}

        placeholders = ",".join("?" for _ in normalized_urls)
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT
                    url,
                    site_name,
                    source_type,
                    author,
                    published_at,
                    fetched_at,
                    raw_title,
                    raw_content
                FROM sources
                WHERE url IN ({placeholders})
                """,
                normalized_urls,
            ).fetchall()

        return {
            str(row["url"]): {
                "source": str(row["site_name"]) if row["site_name"] is not None else None,
                "source_type": str(row["source_type"]) if row["source_type"] is not None else None,
                "author": str(row["author"]) if row["author"] is not None else None,
                "published_date": str(row["published_at"]) if row["published_at"] is not None else None,
                "fetched_at": str(row["fetched_at"]) if row["fetched_at"] is not None else None,
                "title": str(row["raw_title"]) if row["raw_title"] is not None else None,
                "content": str(row["raw_content"]) if row["raw_content"] is not None else None,
            }
            for row in rows
        }

    def find_relevant_cached_sources(
        self,
        entity_name: str,
        question: str,
        expanded_queries: list[str],
        limit: int = 12,
        search_mode: str | None = None,
    ) -> list[dict[str, str | None]]:
        search_terms = self._build_cached_source_terms(entity_name, question, expanded_queries)
        if not search_terms:
            return []

        conditions = ["(raw_title LIKE ? OR raw_content LIKE ? OR url LIKE ?)" for _ in search_terms]
        params: list[str] = []
        for term in search_terms:
            like = f"%{term}%"
            params.extend([like, like, like])

        with self._connect() as connection:
            entity_row = self._find_entity_by_name_or_alias(connection, entity_name)
            if not entity_row:
                return []

            mode_clause = "AND q.search_mode = ?" if search_mode else ""
            mode_params = [search_mode] if search_mode else []
            query = f"""
                SELECT
                    s.url,
                    s.site_name,
                    s.source_type,
                    s.author,
                    s.published_at,
                    s.fetched_at,
                    s.raw_title,
                    s.raw_content,
                    MAX(ec.relevance_score) AS max_relevance_score,
                    MAX(ec.credibility_score) AS max_credibility_score,
                    MAX(q.id) AS latest_query_id
                FROM sources s
                JOIN evidence_cards ec ON ec.source_id = s.id
                JOIN search_queries q ON q.id = ec.query_id
                WHERE q.entity_id = ?
                  {mode_clause}
                  AND ({" OR ".join(conditions)})
                GROUP BY s.id, s.url, s.site_name, s.source_type, s.author, s.published_at, s.fetched_at, s.raw_title, s.raw_content
                ORDER BY max_relevance_score DESC, max_credibility_score DESC, latest_query_id DESC, s.updated_at DESC, s.published_at DESC
                LIMIT ?
            """
            rows = connection.execute(
                query,
                [int(entity_row["id"]), *mode_params, *params, max(1, limit * 3)],
            ).fetchall()

        aliases = self._load_aliases(entity_row["alias_json"])
        exact_terms = [
            term.lower()
            for candidate in [str(entity_row["name"]), *aliases, entity_name]
            for term in self._build_exact_entity_terms(candidate)
        ]
        question_terms = [term.lower() for term in self._extract_question_terms(question)]
        results: list[dict[str, str | None]] = []
        seen_urls: set[str] = set()
        for row in rows:
            url = str(row["url"] or "").strip()
            if not url or url in seen_urls:
                continue
            haystack = " ".join(
                [
                    str(row["raw_title"] or ""),
                    str(row["raw_content"] or ""),
                    str(row["site_name"] or ""),
                    url,
                ]
            ).lower()
            entity_match = any(term in haystack for term in exact_terms)
            question_match = not question_terms or any(term in haystack for term in question_terms)
            if not entity_match or not question_match:
                continue
            seen_urls.add(url)
            results.append(
                {
                    "url": url,
                    "title": str(row["raw_title"]) if row["raw_title"] is not None else None,
                    "content": str(row["raw_content"]) if row["raw_content"] is not None else None,
                    "source": str(row["site_name"]) if row["site_name"] is not None else None,
                    "source_type": str(row["source_type"]) if row["source_type"] is not None else None,
                    "author": str(row["author"]) if row["author"] is not None else None,
                    "published_date": str(row["published_at"]) if row["published_at"] is not None else None,
                    "fetched_at": str(row["fetched_at"]) if row["fetched_at"] is not None else None,
                }
            )
            if len(results) >= limit:
                break
        return results

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

    def get_entity_page(self, entity_name: str, media_limit: int = 12, comment_limit: int = 50) -> EntityPageResponse | None:
        with self._connect() as connection:
            entity_row = self._find_entity_by_name_or_alias(connection, entity_name)
            if not entity_row:
                return None

            entity_id = int(entity_row["id"])
            canonical_name = str(entity_row["name"])
            page_row = connection.execute(
                "SELECT * FROM entity_page_profiles WHERE entity_id = ?",
                (entity_id,),
            ).fetchone()
            comment_rows = connection.execute(
                """
                SELECT c.id, c.comment, c.created_at,
                       COALESCE(c.display_name, u.display_name, '') AS display_name,
                       u.avatar_url AS avatar_url
                FROM entity_comments c
                LEFT JOIN users u ON u.id = c.user_id
                WHERE c.entity_id = ?
                ORDER BY c.id DESC
                LIMIT ?
                """,
                (entity_id, max(1, comment_limit)),
            ).fetchall()
            total_comments_row = connection.execute(
                "SELECT COUNT(*) AS cnt FROM entity_comments WHERE entity_id = ?",
                (entity_id,),
            ).fetchone()
            media_rows = connection.execute(
                """
                SELECT *
                FROM media_files
                WHERE entity_name = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (canonical_name, max(1, media_limit)),
            ).fetchall()

            headline, introduction, location, cover_image_url, cover_image_alt, gallery = self._build_entity_page_content(
                entity_name=canonical_name,
                entity_type=str(entity_row["entity_type"] or "organization"),
                page_row=page_row,
            )

            return EntityPageResponse(
                entity_name=canonical_name,
                entity_type=str(entity_row["entity_type"] or "organization"),
                aliases=self._load_aliases(entity_row["alias_json"]),
                headline=headline,
                introduction=introduction,
                location=location,
                cover_image_url=cover_image_url,
                cover_image_alt=cover_image_alt,
                gallery=gallery,
                total_comments=int(total_comments_row["cnt"] or 0) if total_comments_row else 0,
                comments=[
                    EntityCommentResponse(
                        id=int(row["id"]),
                        entity_name=canonical_name,
                        comment=str(row["comment"]),
                        created_at=str(row["created_at"]),
                        display_name=str(row["display_name"] or "") if "display_name" in row.keys() else "",
                        avatar_url=str(row["avatar_url"] or "") if "avatar_url" in row.keys() else "",
                    )
                    for row in comment_rows
                ],
                recent_media=[self._row_to_media_response(row) for row in media_rows],
            )

    def save_entity_comment(
        self,
        entity_name: str,
        comment: str,
        *,
        user_id: int | None = None,
        display_name: str = "",
    ) -> EntityCommentResponse:
        normalized_comment = comment.strip()
        if not normalized_comment:
            raise ValueError("comment cannot be empty")

        with self._connect() as connection:
            entity_id = self._upsert_entity(connection, entity_name)
            entity_row = connection.execute(
                "SELECT name FROM entities WHERE id = ?",
                (entity_id,),
            ).fetchone()
            cursor = connection.execute(
                """
                INSERT INTO entity_comments (entity_id, comment, user_id, display_name)
                VALUES (?, ?, ?, ?)
                """,
                (entity_id, normalized_comment, user_id, display_name),
            )
            comment_row = connection.execute(
                """
                SELECT c.id, c.created_at, u.avatar_url
                FROM entity_comments c
                LEFT JOIN users u ON u.id = c.user_id
                WHERE c.id = ?
                """,
                (cursor.lastrowid,),
            ).fetchone()
            connection.commit()

            return EntityCommentResponse(
                id=int(comment_row["id"]),
                entity_name=str(entity_row["name"]),
                comment=normalized_comment,
                created_at=str(comment_row["created_at"]),
                display_name=display_name,
                avatar_url=str(comment_row["avatar_url"] or ""),
            )

    def upsert_entity_page_images(
        self,
        entity_name: str,
        cover_image_url: str,
        cover_image_alt: str,
        gallery: list[EntityPageImageItem],
        headline: str = "",
        introduction: str = "",
        replace_gallery: bool = False,
    ) -> None:
        normalized_gallery = [item.model_dump() for item in gallery if item.url.strip()]
        normalized_headline = headline.strip()
        normalized_introduction = introduction.strip()
        should_update_gallery = bool(normalized_gallery) or replace_gallery
        if not normalized_gallery and not normalized_headline and not normalized_introduction and not should_update_gallery:
            return

        with self._connect() as connection:
            entity_id = self._upsert_entity(connection, entity_name)
            connection.execute(
                """
                INSERT INTO entity_page_profiles (
                    entity_id,
                    headline,
                    introduction,
                    location,
                    cover_image_url,
                    cover_image_alt,
                    gallery_json,
                    updated_at
                ) VALUES (
                    ?,
                    ?,
                    ?,
                    COALESCE((SELECT location FROM entity_page_profiles WHERE entity_id = ?), ''),
                    ?,
                    ?,
                    ?,
                    CURRENT_TIMESTAMP
                )
                ON CONFLICT(entity_id) DO UPDATE SET
                    headline = CASE
                        WHEN TRIM(entity_page_profiles.headline) = '' AND TRIM(excluded.headline) <> ''
                        THEN excluded.headline
                        ELSE entity_page_profiles.headline
                    END,
                    introduction = CASE
                        WHEN TRIM(entity_page_profiles.introduction) = '' AND TRIM(excluded.introduction) <> ''
                        THEN excluded.introduction
                        ELSE entity_page_profiles.introduction
                    END,
                    cover_image_url = CASE
                        WHEN ? = 1 THEN excluded.cover_image_url
                        ELSE entity_page_profiles.cover_image_url
                    END,
                    cover_image_alt = CASE
                        WHEN ? = 1 THEN excluded.cover_image_alt
                        ELSE entity_page_profiles.cover_image_alt
                    END,
                    gallery_json = CASE
                        WHEN ? = 1 THEN excluded.gallery_json
                        ELSE entity_page_profiles.gallery_json
                    END,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    entity_id,
                    normalized_headline,
                    normalized_introduction,
                    entity_id,
                    cover_image_url.strip(),
                    cover_image_alt.strip(),
                    json.dumps(normalized_gallery, ensure_ascii=False),
                    1 if should_update_gallery else 0,
                    1 if should_update_gallery else 0,
                    1 if should_update_gallery else 0,
                ),
            )
            connection.commit()

    def get_cached_query_result(
        self,
        entity_name: str,
        question: str,
        search_mode: str,
        max_age_hours: int,
    ) -> dict[str, object] | None:
        with self._connect() as connection:
            entity_row = self._find_entity_by_name_or_alias(connection, entity_name)
            if not entity_row:
                return None

            row = connection.execute(
                """
                SELECT
                    q.id AS query_id,
                    q.mode,
                    q.search_mode,
                    q.animal_focus,
                    q.expanded_queries_json,
                    q.created_at,
                    qs.verdict,
                    qs.confidence,
                    qs.supporting_points_json,
                    qs.opposing_points_json,
                    qs.uncertain_points_json,
                    qs.suggested_follow_up_json
                FROM search_queries q
                JOIN query_summaries qs ON qs.query_id = q.id
                WHERE q.entity_id = ?
                  AND q.normalized_question = ?
                  AND q.search_mode = ?
                  AND q.created_at >= datetime('now', ?)
                ORDER BY q.id DESC
                LIMIT 1
                """,
                (
                    int(entity_row["id"]),
                    question.strip().lower(),
                    search_mode,
                    f"-{max(1, max_age_hours)} hours",
                ),
            ).fetchone()
            if not row:
                return None

            summary = BalancedSummary(
                verdict=str(row["verdict"]),
                confidence=int(row["confidence"] or 0),
                supporting_points=self._load_string_list(row["supporting_points_json"]),
                opposing_points=self._load_string_list(row["opposing_points_json"]),
                uncertain_points=self._load_string_list(row["uncertain_points_json"]),
                suggested_follow_up=self._load_string_list(row["suggested_follow_up_json"]),
            )
            evidence_cards = self._load_evidence_cards_for_query(connection, int(row["query_id"]))
            return {
                "mode": "cached",
                "search_mode": str(row["search_mode"]),
                "animal_focus": bool(row["animal_focus"]),
                "expanded_queries": self._load_string_list(row["expanded_queries_json"]),
                "summary": summary,
                "evidence_cards": evidence_cards,
                "created_at": str(row["created_at"]),
            }

    def save_entity_summary_snapshot(
        self,
        entity_name: str,
        search_mode: str,
        summary: BalancedSummary,
        evidence_cards: list[EvidenceCard],
        latest_query_id: int | None,
        source_window_days: int = 30,
    ) -> None:
        with self._connect() as connection:
            entity_id = self._upsert_entity(connection, entity_name)
            normalized_window_days = max(1, source_window_days)
            summary_payload = summary.model_dump(mode="json")
            evidence_payload = [card.model_dump(mode="json") for card in evidence_cards]
            snapshot_hash = self._build_snapshot_hash(
                mode=search_mode,
                summary_payload=summary_payload,
                evidence_payload=evidence_payload,
                source_window_days=normalized_window_days,
            )
            connection.execute(
                """
                INSERT INTO entity_summary_snapshots (
                    entity_id,
                    mode,
                    snapshot_hash,
                    summary_json,
                    evidence_cards_json,
                    source_window_days,
                    source_count,
                    latest_query_id,
                    generated_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                ON CONFLICT(entity_id, mode, snapshot_hash) DO UPDATE SET
                    latest_query_id = excluded.latest_query_id,
                    generated_at = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    entity_id,
                    search_mode,
                    snapshot_hash,
                    json.dumps(summary_payload, ensure_ascii=False),
                    json.dumps(evidence_payload, ensure_ascii=False),
                    normalized_window_days,
                    len(evidence_cards),
                    latest_query_id,
                ),
            )
            connection.commit()

    def get_entity_summary_snapshot(
        self,
        entity_name: str,
        search_mode: str,
    ) -> EntitySummarySnapshotResponse | None:
        with self._connect() as connection:
            entity_row = self._find_entity_by_name_or_alias(connection, entity_name)
            if not entity_row:
                return None

            row = connection.execute(
                """
                SELECT mode, summary_json, evidence_cards_json, source_window_days, source_count, generated_at
                FROM entity_summary_snapshots
                WHERE entity_id = ? AND mode = ?
                ORDER BY datetime(generated_at) DESC, id DESC
                LIMIT 1
                """,
                (int(entity_row["id"]), search_mode),
            ).fetchone()
            if not row:
                return None

            summary = BalancedSummary.model_validate(json.loads(str(row["summary_json"])))
            cards = [
                EvidenceCard.model_validate(item)
                for item in json.loads(str(row["evidence_cards_json"]))
                if isinstance(item, dict)
            ]
            return EntitySummarySnapshotResponse(
                entity_name=str(entity_row["name"]),
                mode=str(row["mode"]),
                animal_focus=str(row["mode"]) == "animal_law",
                source_count=int(row["source_count"] or 0),
                source_window_days=int(row["source_window_days"] or 30),
                generated_at=str(row["generated_at"]),
                summary=summary,
                evidence_cards=cards,
            )

    def refresh_entity_question_suggestions(
        self,
        entity_name: str,
        search_mode: str,
        latest_summary: BalancedSummary | None = None,
    ) -> None:
        with self._connect() as connection:
            entity_row = self._find_entity_by_name_or_alias(connection, entity_name)
            if not entity_row:
                return

            entity_id = int(entity_row["id"])
            entity_type = str(entity_row["entity_type"] or "organization")
            recent_rows = connection.execute(
                """
                SELECT question
                FROM search_queries
                WHERE entity_id = ? AND search_mode = ?
                ORDER BY id DESC
                LIMIT 4
                """,
                (entity_id, search_mode),
            ).fetchall()

            suggestions: list[tuple[str, str, int, str]] = []
            seen_questions: set[str] = set()
            for category, question_text in question_templates_for(entity_type, search_mode):
                normalized = question_text.strip()
                if normalized in seen_questions:
                    continue
                seen_questions.add(normalized)
                suggestions.append((category, normalized, 82, "seed"))

            for row in recent_rows:
                normalized = str(row["question"] or "").strip()
                if not normalized or normalized in seen_questions:
                    continue
                seen_questions.add(normalized)
                suggestions.append(("近期查核問題", normalized, 75, "search_history"))

            if latest_summary:
                follow_up_question = (
                    "目前有哪些與動物福利相關的部分仍待進一步查核？"
                    if search_mode == "animal_law"
                    else "目前哪些部分已有公開資料，哪些仍待進一步查核？"
                )
                if follow_up_question not in seen_questions:
                    suggestions.append(("近期爭議與待查問題", follow_up_question, 72, "summary_follow_up"))

            self._replace_question_suggestions(connection, entity_id, search_mode, suggestions[:8])
            connection.commit()

    def get_entity_question_suggestions(
        self,
        entity_name: str,
        search_mode: str,
        limit: int = 8,
    ) -> EntityQuestionSuggestionsResponse | None:
        with self._connect() as connection:
            entity_row = self._find_entity_by_name_or_alias(connection, entity_name)
            if not entity_row:
                return None

            rows = connection.execute(
                """
                SELECT category, question_text, confidence_score, generated_from
                FROM entity_question_suggestions
                WHERE entity_id = ? AND mode = ? AND is_active = 1
                ORDER BY confidence_score DESC, id ASC
                LIMIT ?
                """,
                (int(entity_row["id"]), search_mode, max(1, limit)),
            ).fetchall()

            if not rows:
                self.refresh_entity_question_suggestions(str(entity_row["name"]), search_mode)
                rows = connection.execute(
                    """
                    SELECT category, question_text, confidence_score, generated_from
                    FROM entity_question_suggestions
                    WHERE entity_id = ? AND mode = ? AND is_active = 1
                    ORDER BY confidence_score DESC, id ASC
                    LIMIT ?
                    """,
                    (int(entity_row["id"]), search_mode, max(1, limit)),
                ).fetchall()

            return EntityQuestionSuggestionsResponse(
                entity_name=str(entity_row["name"]),
                mode=search_mode,
                animal_focus=search_mode == "animal_law",
                items=[
                    EntityQuestionSuggestionItem(
                        category=str(row["category"]),
                        question_text=str(row["question_text"]),
                        confidence_score=int(row["confidence_score"] or 0),
                        generated_from=str(row["generated_from"]),
                    )
                    for row in rows
                ],
            )

    def list_due_watchlist_entities(
        self,
        limit: int = 10,
        entity_names: list[str] | None = None,
    ) -> list[WatchlistEntity]:
        with self._connect() as connection:
            allowed_names: set[str] | None = None
            allowed_entity_types = {
                entity_type.strip().lower()
                for entity_type in str(self.settings.watchlist_allowed_entity_types or "").split(",")
                if entity_type.strip()
            }
            if entity_names:
                allowed_names = set()
                for name in entity_names:
                    row = self._find_entity_by_name_or_alias(connection, name)
                    if row:
                        allowed_names.add(str(row["name"]))

            rows = connection.execute(
                """
                SELECT e.name, e.entity_type, e.alias_json, ew.priority, ew.refresh_interval_hours, ew.default_mode, ew.next_crawl_at
                FROM entity_watchlists ew
                JOIN entities e ON e.id = ew.entity_id
                WHERE ew.is_active = 1
                  AND (ew.next_crawl_at IS NULL OR ew.next_crawl_at <= CURRENT_TIMESTAMP)
                ORDER BY ew.priority ASC, e.name ASC
                """
            ).fetchall()

            items: list[WatchlistEntity] = []
            for row in rows:
                entity_name = str(row["name"])
                if allowed_names is not None and entity_name not in allowed_names:
                    continue
                entity_type = str(row["entity_type"] or "organization").lower()
                if allowed_names is None and allowed_entity_types and entity_type not in allowed_entity_types:
                    continue
                items.append(
                    WatchlistEntity(
                        entity_name=entity_name,
                        entity_type=entity_type,
                        aliases=self._load_aliases(row["alias_json"]),
                        priority=int(row["priority"] or 3),
                        refresh_interval_hours=int(row["refresh_interval_hours"] or 24),
                        default_mode=str(row["default_mode"] or "general"),
                        next_crawl_at=str(row["next_crawl_at"]) if row["next_crawl_at"] else None,
                    )
                )
                if len(items) >= max(1, limit):
                    break
            return items

    def _auto_enroll_watchlist(
        self,
        connection: sqlite3.Connection,
        entity_id: int,
        search_mode: str,
    ) -> None:
        """Auto-add an entity to the watchlist when it is searched for the first time."""
        existing = connection.execute(
            "SELECT 1 FROM entity_watchlists WHERE entity_id = ?",
            (entity_id,),
        ).fetchone()
        if existing:
            return
        default_mode = "animal_law" if search_mode == "animal_law" else "general"
        connection.execute(
            """
            INSERT INTO entity_watchlists (
                entity_id, is_active, priority, refresh_interval_hours,
                default_mode, updated_at
            ) VALUES (?, 1, 3, 168, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(entity_id) DO NOTHING
            """,
            (entity_id, default_mode),
        )
        logger.info("auto_enroll_watchlist entity_id=%d mode=%s", entity_id, default_mode)

    def mark_watchlist_refresh_success(self, entity_name: str) -> None:
        with self._connect() as connection:
            entity_row = self._find_entity_by_name_or_alias(connection, entity_name)
            if not entity_row:
                return
            connection.execute(
                """
                UPDATE entity_watchlists
                SET
                    last_crawled_at = CURRENT_TIMESTAMP,
                    last_success_at = CURRENT_TIMESTAMP,
                    last_error_at = NULL,
                    last_error_message = NULL,
                    next_crawl_at = datetime(CURRENT_TIMESTAMP, '+' || refresh_interval_hours || ' hours'),
                    updated_at = CURRENT_TIMESTAMP
                WHERE entity_id = ?
                """,
                (int(entity_row["id"]),),
            )
            connection.commit()

    def mark_watchlist_refresh_failure(self, entity_name: str, error_message: str) -> None:
        with self._connect() as connection:
            entity_row = self._find_entity_by_name_or_alias(connection, entity_name)
            if not entity_row:
                return
            connection.execute(
                """
                UPDATE entity_watchlists
                SET
                    last_crawled_at = CURRENT_TIMESTAMP,
                    last_error_at = CURRENT_TIMESTAMP,
                    last_error_message = ?,
                    next_crawl_at = datetime(CURRENT_TIMESTAMP, ?),
                    updated_at = CURRENT_TIMESTAMP
                WHERE entity_id = ?
                """,
                (
                    error_message[:500],
                    f"+{max(1, self.settings.watchlist_retry_delay_minutes)} minutes",
                    int(entity_row["id"]),
                ),
            )
            connection.commit()

    def find_entity(self, entity_name: str) -> dict | None:
        """Public entity lookup covering canonical name, alias_json, and keyword match."""
        normalized = entity_name.strip()
        if not normalized:
            return None
        with self._connect() as connection:
            row = self._find_entity_by_name_or_alias(connection, normalized)
            if row is None:
                return None
            return {
                "id": int(row["id"]),
                "name": str(row["name"]),
                "entity_type": str(row["entity_type"] or ""),
                "aliases": self._load_aliases(row["alias_json"]),
            }

    def create_shelter_full(
        self,
        *,
        canonical_name: str,
        entity_type: str,
        aliases: list[str],
        introduction: str,
        location: str,
        website: str,
        facebook_url: str,
        cover_image_url: str = "",
    ) -> tuple[int, bool]:
        """Create a new shelter with profile + watchlist in one transaction.

        Returns (entity_id, created). `created=False` means entity already existed
        (alias/name match); caller should treat as idempotent success.
        """
        normalized_name = canonical_name.strip()
        if not normalized_name:
            raise ValueError("canonical_name cannot be empty")

        cleaned_aliases = [a.strip() for a in aliases if a and a.strip() and a.strip() != normalized_name]

        with self._connect() as connection:
            connection.execute("BEGIN")
            try:
                existing = self._find_entity_by_name_or_alias(connection, normalized_name)
                if existing is None:
                    for alias in cleaned_aliases:
                        existing = self._find_entity_by_name_or_alias(connection, alias)
                        if existing is not None:
                            break

                if existing is not None:
                    connection.execute("COMMIT")
                    return int(existing["id"]), False

                cursor = connection.execute(
                    "INSERT INTO entities (name, entity_type, alias_json) VALUES (?, ?, ?)",
                    (
                        normalized_name,
                        entity_type or "organization",
                        json.dumps(sorted(cleaned_aliases), ensure_ascii=False),
                    ),
                )
                entity_id = int(cursor.lastrowid)

                for alias in cleaned_aliases:
                    connection.execute(
                        """
                        INSERT OR IGNORE INTO entity_keywords
                            (entity_id, keyword, keyword_type, weight, is_active)
                        VALUES (?, ?, 'alias', 70, 1)
                        """,
                        (entity_id, alias),
                    )

                headline = normalized_name
                profile_parts: list[str] = []
                if introduction:
                    profile_parts.append(introduction)
                if website:
                    profile_parts.append(f"官網：{website}")
                if facebook_url:
                    profile_parts.append(f"Facebook：{facebook_url}")
                stored_intro = "\n\n".join(profile_parts)

                cover_url = (cover_image_url or "").strip()
                cover_alt = f"{normalized_name} 介紹圖片" if cover_url else ""
                connection.execute(
                    """
                    INSERT INTO entity_page_profiles (
                        entity_id, headline, introduction, location,
                        cover_image_url, cover_image_alt, gallery_json, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, '[]', CURRENT_TIMESTAMP)
                    ON CONFLICT(entity_id) DO UPDATE SET
                        headline = excluded.headline,
                        introduction = excluded.introduction,
                        location = excluded.location,
                        cover_image_url = CASE
                            WHEN excluded.cover_image_url != '' THEN excluded.cover_image_url
                            ELSE entity_page_profiles.cover_image_url
                        END,
                        cover_image_alt = CASE
                            WHEN excluded.cover_image_url != '' THEN excluded.cover_image_alt
                            ELSE entity_page_profiles.cover_image_alt
                        END,
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    (entity_id, headline, stored_intro, location, cover_url, cover_alt),
                )

                refresh_hours = max(1, int(self.settings.shelter_default_refresh_interval_hours))
                # next_crawl_at=NULL → eligible for immediate crawl; the background
                # first-crawl task will update this timestamp after it runs.
                connection.execute(
                    """
                    INSERT INTO entity_watchlists (
                        entity_id, is_active, priority, refresh_interval_hours,
                        default_mode, next_crawl_at
                    ) VALUES (?, 1, 5, ?, 'general', NULL)
                    ON CONFLICT(entity_id) DO UPDATE SET
                        is_active = 1,
                        refresh_interval_hours = excluded.refresh_interval_hours,
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    (entity_id, refresh_hours),
                )

                connection.execute("COMMIT")
                return entity_id, True
            except Exception:
                connection.execute("ROLLBACK")
                raise

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

    # ── Review CRUD ──────────────────────────────────────────

    def save_reviews(
        self,
        entity_name: str,
        platform: str,
        reviews: list[dict],
    ) -> int:
        """Insert reviews, skip duplicates. Returns count of newly inserted rows."""
        with self._connect() as connection:
            entity_id = self._upsert_entity(connection, entity_name)
            inserted = 0
            for item in reviews:
                content = str(item.get("content") or "").strip()
                if not content:
                    continue
                author = item.get("author") or ""
                content_hash = hashlib.md5(
                    f"{entity_id}:{platform}:{author}:{content[:200]}".encode()
                ).hexdigest()
                existing = connection.execute(
                    "SELECT 1 FROM reviews WHERE entity_id = ? AND platform = ? AND content_hash = ?",
                    (entity_id, platform, content_hash),
                ).fetchone()
                if existing:
                    continue
                connection.execute(
                    """
                    INSERT INTO reviews (
                        entity_id, platform, author, content, content_hash, sentiment,
                        rating, source_url, parent_title, likes,
                        published_at, fetched_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        entity_id,
                        platform,
                        author or None,
                        content,
                        content_hash,
                        item.get("sentiment"),
                        item.get("rating"),
                        str(item.get("source_url") or ""),
                        item.get("parent_title"),
                        int(item.get("likes") or 0),
                        item.get("published_at"),
                        item.get("fetched_at") or datetime.now(timezone.utc).isoformat(),
                    ),
                )
                inserted += 1
            connection.commit()
            return inserted

    def get_reviews(
        self,
        entity_name: str,
        *,
        platform: str | None = None,
        limit: int = 20,
        offset: int = 0,
        min_relevance: float | None = 0.6,
        include_unanalyzed: bool = False,
        only_reviews: bool = True,
    ) -> list[dict]:
        """Fetch reviews for an entity, optionally filtered by LLM relevance score.

        min_relevance: only return reviews with relevance_score >= this value.
          Set to None to disable filtering.
        include_unanalyzed: if True, also include reviews where analyzed_at IS NULL
          (analysis not yet run). Useful while analyzer is still catching up.
        only_reviews: if True, exclude rows classified as self_post/announcement/news/unrelated.
          Set include_unanalyzed=True to include rows with NULL content_type.
        """
        with self._connect() as connection:
            entity_row = self._find_entity_by_name_or_alias(connection, entity_name)
            if not entity_row:
                return []
            entity_id = int(entity_row["id"])
            params: list[object] = [entity_id]
            where = "WHERE r.entity_id = ?"
            if platform:
                where += " AND r.platform = ?"
                params.append(platform)
            if min_relevance is not None:
                if include_unanalyzed:
                    where += " AND (r.analyzed_at IS NULL OR r.relevance_score >= ?)"
                else:
                    where += " AND r.relevance_score >= ?"
                params.append(float(min_relevance))
            if only_reviews:
                if include_unanalyzed:
                    where += " AND (r.content_type IS NULL OR r.content_type = 'review')"
                else:
                    where += " AND r.content_type = 'review'"
            params.extend([max(1, limit), max(0, offset)])
            rows = connection.execute(
                f"""
                SELECT r.id, r.platform, r.author, r.content, r.sentiment,
                       r.rating, r.source_url, r.parent_title, r.likes,
                       r.published_at, r.fetched_at,
                       r.relevance_score, r.stance, r.short_summary,
                       r.content_type,
                       r.dimension_tags_json
                FROM reviews r
                {where}
                ORDER BY
                    CASE WHEN r.relevance_score IS NULL THEN 0.5 ELSE r.relevance_score END DESC,
                    r.published_at DESC, r.id DESC
                LIMIT ? OFFSET ?
                """,
                params,
            ).fetchall()
            results = []
            for row in rows:
                d = dict(row)
                try:
                    d["dimension_tags"] = json.loads(d.pop("dimension_tags_json") or "[]")
                except (json.JSONDecodeError, TypeError):
                    d["dimension_tags"] = []
                results.append(d)
            return results

    def get_review_stats(
        self,
        entity_name: str,
        *,
        min_relevance: float | None = 0.6,
        include_unanalyzed: bool = False,
        only_reviews: bool = True,
    ) -> dict[str, int]:
        with self._connect() as connection:
            entity_row = self._find_entity_by_name_or_alias(connection, entity_name)
            if not entity_row:
                return {}
            params: list[object] = [int(entity_row["id"])]
            where = "WHERE entity_id = ?"
            if min_relevance is not None:
                if include_unanalyzed:
                    where += " AND (analyzed_at IS NULL OR relevance_score >= ?)"
                else:
                    where += " AND relevance_score >= ?"
                params.append(float(min_relevance))
            if only_reviews:
                if include_unanalyzed:
                    where += " AND (content_type IS NULL OR content_type = 'review')"
                else:
                    where += " AND content_type = 'review'"
            rows = connection.execute(
                f"SELECT platform, COUNT(*) AS cnt FROM reviews {where} GROUP BY platform",
                params,
            ).fetchall()
            return {str(row["platform"]): int(row["cnt"]) for row in rows}

    def suggest_entities(self, query: str, limit: int = 10) -> list[dict]:
        """Lightweight autocomplete: prefix-match + substring on name/alias/keywords."""
        normalized = query.strip().lower()
        if not normalized:
            return []
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT e.id, e.name, e.alias_json
                FROM entities e
                ORDER BY e.name ASC
                """,
            ).fetchall()
            results: list[dict] = []
            for row in rows:
                name = str(row["name"])
                aliases = self._load_aliases(row["alias_json"])
                haystack = [name, *aliases]
                matched = any(normalized in h.lower() for h in haystack)
                if not matched:
                    continue
                prefix = any(h.lower().startswith(normalized) for h in haystack)
                review_count = connection.execute(
                    "SELECT COUNT(*) AS cnt FROM reviews WHERE entity_id = ?",
                    (int(row["id"]),),
                ).fetchone()["cnt"]
                results.append({
                    "name": name,
                    "aliases": aliases,
                    "review_count": int(review_count),
                    "prefix_match": prefix,
                })
            results.sort(key=lambda x: (not x["prefix_match"], -x["review_count"], x["name"]))
            return [{"name": r["name"], "aliases": r["aliases"], "review_count": r["review_count"]} for r in results[:limit]]

    def log_pipeline_run(
        self,
        pipeline_name: str,
        entity_name: str | None,
        status: str,
        reviews_written: int = 0,
        error_message: str | None = None,
    ) -> int:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO pipeline_runs (pipeline_name, entity_name, status, reviews_written, error_message, finished_at)
                VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                (pipeline_name, entity_name, status, reviews_written, error_message),
            )
            connection.commit()
            return int(cursor.lastrowid)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _ensure_comment_user_column(self, connection: sqlite3.Connection) -> None:
        rows = connection.execute("PRAGMA table_info(entity_comments)").fetchall()
        columns = {str(row["name"]) for row in rows}
        if "user_id" not in columns:
            connection.execute("ALTER TABLE entity_comments ADD COLUMN user_id INTEGER")
        if "display_name" not in columns:
            connection.execute("ALTER TABLE entity_comments ADD COLUMN display_name TEXT NOT NULL DEFAULT ''")

    def _ensure_review_comments_table(self, connection: sqlite3.Connection) -> None:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS review_comments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                review_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                display_name TEXT NOT NULL DEFAULT '',
                comment TEXT NOT NULL,
                attachments_json TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (review_id) REFERENCES reviews(id),
                FOREIGN KEY (user_id) REFERENCES users(id)
            );
            CREATE INDEX IF NOT EXISTS idx_review_comments_review ON review_comments(review_id, id DESC);
            """
        )
        # Add columns for existing DBs (idempotent)
        cols = {str(r["name"]) for r in connection.execute("PRAGMA table_info(review_comments)")}
        if "attachments_json" not in cols:
            connection.execute(
                "ALTER TABLE review_comments ADD COLUMN attachments_json TEXT NOT NULL DEFAULT '[]'"
            )
        if "is_anonymous" not in cols:
            connection.execute(
                "ALTER TABLE review_comments ADD COLUMN is_anonymous INTEGER NOT NULL DEFAULT 0"
            )

    def _ensure_user_tables(self, connection: sqlite3.Connection) -> None:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                provider TEXT NOT NULL,
                provider_user_id TEXT NOT NULL,
                display_name TEXT NOT NULL DEFAULT '',
                avatar_url TEXT NOT NULL DEFAULT '',
                email TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                last_login_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(provider, provider_user_id)
            );
            CREATE TABLE IF NOT EXISTS user_sessions (
                token TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                expires_at TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id)
            );
            CREATE TABLE IF NOT EXISTS review_ratings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                review_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                score INTEGER NOT NULL CHECK (score BETWEEN 1 AND 5),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(review_id, user_id),
                FOREIGN KEY (review_id) REFERENCES reviews(id),
                FOREIGN KEY (user_id) REFERENCES users(id)
            );
            CREATE TABLE IF NOT EXISTS review_reactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                review_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                reaction TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(review_id, user_id, reaction),
                FOREIGN KEY (review_id) REFERENCES reviews(id),
                FOREIGN KEY (user_id) REFERENCES users(id)
            );
            CREATE INDEX IF NOT EXISTS idx_user_sessions_user ON user_sessions(user_id);
            CREATE INDEX IF NOT EXISTS idx_user_sessions_expires ON user_sessions(expires_at);
            CREATE INDEX IF NOT EXISTS idx_review_ratings_review ON review_ratings(review_id);
            CREATE INDEX IF NOT EXISTS idx_review_ratings_user ON review_ratings(user_id);
            CREATE INDEX IF NOT EXISTS idx_review_reactions_review ON review_reactions(review_id, reaction);
            """
        )

    def _ensure_review_analysis_columns(self, connection: sqlite3.Connection) -> None:
        rows = connection.execute("PRAGMA table_info(reviews)").fetchall()
        columns = {str(row["name"]) for row in rows}
        if "relevance_score" not in columns:
            connection.execute(
                "ALTER TABLE reviews ADD COLUMN relevance_score REAL"
            )
        if "stance" not in columns:
            connection.execute(
                "ALTER TABLE reviews ADD COLUMN stance TEXT"
            )
        if "short_summary" not in columns:
            connection.execute(
                "ALTER TABLE reviews ADD COLUMN short_summary TEXT"
            )
        if "analyzed_at" not in columns:
            connection.execute(
                "ALTER TABLE reviews ADD COLUMN analyzed_at TEXT"
            )
        if "dimension_tags_json" not in columns:
            connection.execute(
                "ALTER TABLE reviews ADD COLUMN dimension_tags_json TEXT NOT NULL DEFAULT '[]'"
            )
        if "dimensions_classified_at" not in columns:
            connection.execute(
                "ALTER TABLE reviews ADD COLUMN dimensions_classified_at TEXT"
            )
        if "content_type" not in columns:
            connection.execute(
                "ALTER TABLE reviews ADD COLUMN content_type TEXT"
            )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_reviews_analyzed ON reviews(entity_id, analyzed_at)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_reviews_content_type ON reviews(entity_id, content_type)"
        )

    def _ensure_search_query_columns(self, connection: sqlite3.Connection) -> None:
        rows = connection.execute("PRAGMA table_info(search_queries)").fetchall()
        columns = {str(row["name"]) for row in rows}
        if "search_mode" not in columns:
            connection.execute(
                "ALTER TABLE search_queries ADD COLUMN search_mode TEXT NOT NULL DEFAULT 'general'"
            )
        if "animal_focus" not in columns:
            connection.execute(
                "ALTER TABLE search_queries ADD COLUMN animal_focus INTEGER NOT NULL DEFAULT 0"
            )

    def _ensure_entity_summary_snapshot_history(self, connection: sqlite3.Connection) -> None:
        rows = connection.execute("PRAGMA table_info(entity_summary_snapshots)").fetchall()
        columns = {str(row["name"]) for row in rows}
        if not rows or "snapshot_hash" in columns:
            return

        legacy_rows = connection.execute(
            """
            SELECT entity_id, mode, summary_json, evidence_cards_json, source_window_days, source_count, latest_query_id, generated_at, updated_at
            FROM entity_summary_snapshots
            ORDER BY id ASC
            """
        ).fetchall()

        connection.execute("ALTER TABLE entity_summary_snapshots RENAME TO entity_summary_snapshots_legacy")
        connection.execute(
            """
            CREATE TABLE entity_summary_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                entity_id INTEGER NOT NULL,
                mode TEXT NOT NULL,
                snapshot_hash TEXT NOT NULL DEFAULT '',
                summary_json TEXT NOT NULL,
                evidence_cards_json TEXT NOT NULL,
                source_window_days INTEGER NOT NULL DEFAULT 30,
                source_count INTEGER NOT NULL DEFAULT 0,
                latest_query_id INTEGER,
                generated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(entity_id, mode, snapshot_hash),
                FOREIGN KEY (entity_id) REFERENCES entities(id),
                FOREIGN KEY (latest_query_id) REFERENCES search_queries(id)
            )
            """
        )

        for row in legacy_rows:
            summary_json = str(row["summary_json"] or "{}")
            evidence_json = str(row["evidence_cards_json"] or "[]")
            normalized_window_days = max(1, int(row["source_window_days"] or 30))
            snapshot_hash = self._build_snapshot_hash(
                mode=str(row["mode"] or "general"),
                summary_payload=self._load_json_value(summary_json, default={}),
                evidence_payload=self._load_json_value(evidence_json, default=[]),
                source_window_days=normalized_window_days,
            )
            connection.execute(
                """
                INSERT INTO entity_summary_snapshots (
                    entity_id,
                    mode,
                    snapshot_hash,
                    summary_json,
                    evidence_cards_json,
                    source_window_days,
                    source_count,
                    latest_query_id,
                    generated_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(entity_id, mode, snapshot_hash) DO UPDATE SET
                    latest_query_id = excluded.latest_query_id,
                    generated_at = excluded.generated_at,
                    updated_at = excluded.updated_at
                """,
                (
                    int(row["entity_id"]),
                    str(row["mode"] or "general"),
                    snapshot_hash,
                    summary_json,
                    evidence_json,
                    normalized_window_days,
                    int(row["source_count"] or 0),
                    row["latest_query_id"],
                    str(row["generated_at"] or "CURRENT_TIMESTAMP"),
                    str(row["updated_at"] or row["generated_at"] or "CURRENT_TIMESTAMP"),
                ),
            )

        connection.execute("DROP TABLE entity_summary_snapshots_legacy")

    def _build_snapshot_hash(
        self,
        *,
        mode: str,
        summary_payload: object,
        evidence_payload: object,
        source_window_days: int,
    ) -> str:
        serialized = json.dumps(
            {
                "mode": mode,
                "summary": summary_payload,
                "evidence_cards": evidence_payload,
                "source_window_days": max(1, source_window_days),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    def _load_json_value(self, raw_value: str, *, default: object) -> object:
        try:
            return json.loads(raw_value)
        except (TypeError, ValueError):
            return default

    def _bootstrap_builtin_watchlist(self, connection: sqlite3.Connection) -> None:
        for item in WATCHLIST_SEED:
            entity_id = self._upsert_entity(connection, str(item["canonical_name"]))
            aliases = [str(alias) for alias in item.get("aliases", []) if str(alias).strip()]
            merged_aliases = sorted(
                {
                    *self._load_aliases(
                        connection.execute(
                            "SELECT alias_json FROM entities WHERE id = ?",
                            (entity_id,),
                        ).fetchone()["alias_json"]
                    ),
                    *aliases,
                }
            )
            connection.execute(
                """
                UPDATE entities
                SET entity_type = ?, alias_json = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    str(item.get("entity_type") or "organization"),
                    json.dumps(merged_aliases, ensure_ascii=False),
                    entity_id,
                ),
            )
            keywords = [str(item["canonical_name"]), *aliases]
            for index, keyword in enumerate(keywords):
                if not keyword.strip():
                    continue
                connection.execute(
                    """
                    INSERT INTO entity_keywords (entity_id, keyword, keyword_type, weight, is_active, updated_at)
                    VALUES (?, ?, ?, ?, 1, CURRENT_TIMESTAMP)
                    ON CONFLICT(entity_id, keyword) DO UPDATE SET
                        keyword_type = excluded.keyword_type,
                        weight = excluded.weight,
                        is_active = 1,
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    (
                        entity_id,
                        keyword.strip(),
                        "canonical" if index == 0 else "alias",
                        100 if index == 0 else 80,
                    ),
                )
            connection.execute(
                """
                INSERT INTO entity_watchlists (
                    entity_id,
                    is_active,
                    priority,
                    refresh_interval_hours,
                    default_mode,
                    updated_at
                ) VALUES (?, 1, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(entity_id) DO UPDATE SET
                    is_active = 1,
                    priority = excluded.priority,
                    refresh_interval_hours = excluded.refresh_interval_hours,
                    default_mode = excluded.default_mode,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    entity_id,
                    int(item.get("priority") or 3),
                    int(item.get("refresh_interval_hours") or 24),
                    str(item.get("default_mode") or "general"),
                ),
            )
            for mode in ("general", "animal_law"):
                self._replace_question_suggestions(
                    connection,
                    entity_id,
                    mode,
                    [
                        (category, question_text, 82, "seed")
                        for category, question_text in question_templates_for(
                            str(item.get("entity_type") or "organization"),
                            mode,
                        )[:8]
                    ],
                )
        self._bootstrap_entity_page_profiles(connection)
        connection.commit()

    def _bootstrap_entity_page_profiles(self, connection: sqlite3.Connection) -> None:
        for item in ENTITY_PAGE_SEED:
            entity_id = self._upsert_entity(connection, str(item["canonical_name"]))
            connection.execute(
                """
                INSERT INTO entity_page_profiles (
                    entity_id,
                    headline,
                    introduction,
                    location,
                    cover_image_url,
                    cover_image_alt,
                    gallery_json,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(entity_id) DO UPDATE SET
                    headline = excluded.headline,
                    introduction = excluded.introduction,
                    location = excluded.location,
                    cover_image_url = excluded.cover_image_url,
                    cover_image_alt = excluded.cover_image_alt,
                    gallery_json = excluded.gallery_json,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    entity_id,
                    str(item.get("headline") or ""),
                    str(item.get("introduction") or ""),
                    str(item.get("location") or ""),
                    str(item.get("cover_image_url") or ""),
                    str(item.get("cover_image_alt") or ""),
                    json.dumps(item.get("gallery") or [], ensure_ascii=False),
                ),
            )

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
            "SELECT id, name, entity_type, alias_json FROM entities WHERE name = ?",
            (entity_name,),
        ).fetchone()
        if direct_match:
            return direct_match

        keyword_match = connection.execute(
            """
            SELECT e.id, e.name, e.entity_type, e.alias_json
            FROM entity_keywords ek
            JOIN entities e ON e.id = ek.entity_id
            WHERE ek.keyword = ? AND ek.is_active = 1
            LIMIT 1
            """,
            (entity_name,),
        ).fetchone()
        if keyword_match:
            return keyword_match

        rows = connection.execute(
            "SELECT id, name, entity_type, alias_json FROM entities",
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

    def _build_cached_source_terms(
        self,
        entity_name: str,
        question: str,
        expanded_queries: list[str],
    ) -> list[str]:
        candidates = [
            entity_name.strip(),
            *self._build_exact_entity_terms(entity_name),
            *self._extract_question_terms(question),
        ]
        for query in expanded_queries[:6]:
            pieces = str(query).replace("site:", " ").replace('"', " ").split()
            candidates.extend(piece.strip() for piece in pieces if len(piece.strip()) >= 2)

        ordered: list[str] = []
        seen: set[str] = set()
        for candidate in candidates:
            normalized = candidate.strip()
            if len(normalized) < 2 or normalized in seen:
                continue
            seen.add(normalized)
            ordered.append(normalized)
        return ordered[:12]

    def _build_exact_entity_terms(self, entity_name: str) -> list[str]:
        base = entity_name.strip()
        terms = [base]
        for suffix in ("狗園", "樂園", "園區", "協會", "流浪狗園", "流浪毛小孩生命照護協會"):
            if base.endswith(suffix):
                root = base.removesuffix(suffix).strip()
                if len(root) >= 2:
                    terms.append(root)
        return terms

    def _extract_question_terms(self, question: str) -> list[str]:
        markers = ("募資", "捐款", "善款", "財務", "透明", "爭議", "質疑", "道歉", "聲明", "報導", "新聞")
        return [marker for marker in markers if marker in question]

    def _insert_query(
        self,
        connection: sqlite3.Connection,
        entity_id: int,
        question: str,
        expanded_queries: list[str],
        mode: str,
        search_mode: str,
        animal_focus: bool,
    ) -> int:
        cursor = connection.execute(
            """
            INSERT INTO search_queries (
                entity_id,
                question,
                normalized_question,
                expanded_queries_json,
                mode,
                search_mode,
                animal_focus
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                entity_id,
                question,
                question.strip().lower(),
                json.dumps(expanded_queries, ensure_ascii=False),
                mode,
                search_mode,
                1 if animal_focus else 0,
            ),
        )
        return int(cursor.lastrowid)

    def _replace_question_suggestions(
        self,
        connection: sqlite3.Connection,
        entity_id: int,
        search_mode: str,
        suggestions: list[tuple[str, str, int, str]],
    ) -> None:
        connection.execute(
            "DELETE FROM entity_question_suggestions WHERE entity_id = ? AND mode = ?",
            (entity_id, search_mode),
        )
        for category, question_text, confidence_score, generated_from in suggestions:
            connection.execute(
                """
                INSERT INTO entity_question_suggestions (
                    entity_id,
                    mode,
                    category,
                    question_text,
                    confidence_score,
                    generated_from,
                    is_active,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 1, CURRENT_TIMESTAMP)
                """,
                (
                    entity_id,
                    search_mode,
                    category,
                    question_text,
                    confidence_score,
                    generated_from,
                ),
            )

    def _load_string_list(self, raw_value: str | None) -> list[str]:
        if not raw_value:
            return []
        try:
            parsed = json.loads(raw_value)
        except json.JSONDecodeError:
            return []
        return [str(item) for item in parsed if isinstance(item, str)]

    def _load_evidence_cards_for_query(
        self,
        connection: sqlite3.Connection,
        query_id: int,
    ) -> list[EvidenceCard]:
        rows = connection.execute(
            """
            SELECT
                ec.title,
                ec.snippet,
                ec.stance,
                ec.claim_type,
                ec.evidence_strength,
                ec.first_hand_score,
                ec.relevance_score,
                ec.credibility_score,
                ec.recency_label,
                ec.duplicate_risk,
                ec.notes,
                s.url,
                s.site_name,
                s.source_type,
                s.fetched_at,
                s.published_at
            FROM evidence_cards ec
            JOIN sources s ON s.id = ec.source_id
            WHERE ec.query_id = ?
            ORDER BY ec.relevance_score DESC, ec.id ASC
            """,
            (query_id,),
        ).fetchall()
        return [
            EvidenceCard(
                title=str(row["title"]),
                url=str(row["url"]),
                source=str(row["site_name"]),
                source_type=str(row["source_type"] or "other"),
                snippet=str(row["snippet"]),
                excerpt=None,
                ai_summary=None,
                extracted_at=str(row["fetched_at"]) if row["fetched_at"] else None,
                published_at=str(row["published_at"]) if row["published_at"] else None,
                stance=str(row["stance"]),
                claim_type=str(row["claim_type"]),
                evidence_strength=str(row["evidence_strength"]),
                first_hand_score=int(row["first_hand_score"] or 0),
                relevance_score=int(row["relevance_score"] or 0),
                credibility_score=int(row["credibility_score"] or 0),
                recency_label=str(row["recency_label"]),
                duplicate_risk=str(row["duplicate_risk"]),
                notes=str(row["notes"]),
            )
            for row in rows
        ]

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
            canonical_entity_name = self._resolve_entity_name(connection, entity_name)
            cursor = connection.execute(
                """
                INSERT INTO media_files (
                    entity_name, file_name, original_name, media_type,
                    mime_type, file_size, width, height, duration_seconds,
                    caption, uploader_ip
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    canonical_entity_name, file_name, original_name, media_type,
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
                normalized_entity_name = self._canonicalize_entity_name(connection, entity_name)
                conditions.append("entity_name = ?")
                params.append(normalized_entity_name)
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
            normalized_entity_name = self._canonicalize_entity_name(connection, entity_name) if entity_name else None
            where = "WHERE entity_name = ?" if normalized_entity_name else ""
            params: list[str] = [normalized_entity_name] if normalized_entity_name else []

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

    def _build_entity_page_content(
        self,
        entity_name: str,
        entity_type: str,
        page_row: sqlite3.Row | None,
    ) -> tuple[str, str, str, str, str, list[EntityPageImageItem]]:
        fallback = self._default_entity_page_content(entity_name, entity_type)
        if not page_row:
            return (
                str(fallback["headline"]),
                str(fallback["introduction"]),
                str(fallback["location"]),
                str(fallback["cover_image_url"]),
                str(fallback["cover_image_alt"]),
                fallback["gallery"],
            )

        gallery = self._load_page_gallery(page_row["gallery_json"])
        cover_image_url = str(page_row["cover_image_url"] or "").strip()
        cover_image_alt = str(page_row["cover_image_alt"] or "").strip()
        if not cover_image_url and gallery:
            cover_image_url = gallery[0].url
            cover_image_alt = gallery[0].alt_text
        # If gallery's sole entry is the same as the cover, drop it — frontend
        # already renders cover separately; showing it twice is noisy.
        if (
            cover_image_url
            and len(gallery) == 1
            and gallery[0].url.strip() == cover_image_url
        ):
            gallery = []

        return (
            str(page_row["headline"] or fallback["headline"]),
            str(page_row["introduction"] or fallback["introduction"]),
            str(page_row["location"] or fallback["location"]),
            cover_image_url,
            cover_image_alt,
            gallery,
        )

    def _default_entity_page_content(self, entity_name: str, entity_type: str) -> dict[str, object]:
        type_label = {
            "zoo": "動物園",
            "shelter": "動物之家／收容所",
            "rescue_org": "動保組織",
        }.get(entity_type, "實體")
        headline = f"{entity_name} 的專屬 {type_label} 資料頁"
        introduction = (
            f"{entity_name} 的專屬頁會持續累積基本介紹、資料庫摘要、附件與使用者評論，"
            "方便後續長期追蹤這個實體的公開資訊與動物福利議題。"
        )
        return {
            "headline": headline,
            "introduction": introduction,
            "location": "",
            "cover_image_url": "",
            "cover_image_alt": "",
            "gallery": [],
        }

    def _load_page_gallery(self, raw_gallery: str | None) -> list[EntityPageImageItem]:
        if not raw_gallery:
            return []
        try:
            parsed = json.loads(raw_gallery)
        except json.JSONDecodeError:
            return []
        if not isinstance(parsed, list):
            return []

        items: list[EntityPageImageItem] = []
        for item in parsed:
            if isinstance(item, str) and item.strip():
                items.append(EntityPageImageItem(url=item.strip()))
                continue
            if not isinstance(item, dict):
                continue
            url = str(item.get("url") or "").strip()
            if not url:
                continue
            items.append(
                EntityPageImageItem(
                    url=url,
                    alt_text=str(item.get("alt_text") or item.get("alt") or "").strip(),
                    caption=str(item.get("caption") or "").strip(),
                    source_page_url=str(item.get("source_page_url") or "").strip(),
                )
            )
        return items

    def _resolve_entity_name(self, connection: sqlite3.Connection, entity_name: str) -> str:
        entity_id = self._upsert_entity(connection, entity_name)
        row = connection.execute("SELECT name FROM entities WHERE id = ?", (entity_id,)).fetchone()
        return str(row["name"]) if row else entity_name

    def _canonicalize_entity_name(self, connection: sqlite3.Connection, entity_name: str) -> str:
        entity_row = self._find_entity_by_name_or_alias(connection, entity_name)
        if entity_row:
            return str(entity_row["name"])
        return entity_name

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
