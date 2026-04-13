"""Weekly background crawl using agent-browser.

Reads all active watchlist entities and crawls platform sources
(PTT, Dcard, etc.) via headless browser automation.  Results are
written into the ``sources`` table so that the DB-first search path
picks them up without needing live API calls.

Usage:
    cd backend && python -m scripts.weekly_browser_crawl
    cd backend && python -m scripts.weekly_browser_crawl --entity-name 壽山動物園
    cd backend && python -m scripts.weekly_browser_crawl --limit 3 --max-results 10
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from datetime import datetime, timezone

from app.config import Settings
from app.services.duckduckgo_service import DuckDuckGoService
from app.services.persistence_service import PersistenceService
from app.services.scrapers.dcard_scraper import search_dcard
from app.services.scrapers.google_maps_scraper import search_google_maps
from app.services.scrapers.ptt_browser_crawler import crawl_ptt_for_entity

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("weekly_browser_crawl")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Weekly background crawl via agent-browser",
    )
    parser.add_argument(
        "--database-path",
        type=str,
        default=None,
        help="Override SQLite database path.",
    )
    parser.add_argument(
        "--entity-name",
        action="append",
        dest="entity_names",
        default=None,
        help="Crawl only the specified entity (repeatable).  Bypasses watchlist filtering.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="Max number of watchlist entities to process (default: 20).",
    )
    parser.add_argument(
        "--max-results",
        type=int,
        default=30,
        help="Max articles to collect per entity per platform (default: 30).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Crawl but do not write to the database.",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Crawl ALL active watchlist entities, ignoring due-date.",
    )
    return parser.parse_args()


def _dedup_merge(all_results: list[dict], new_items: list[dict]) -> None:
    """Append *new_items* into *all_results*, skipping duplicate URLs."""
    seen = {r["url"] for r in all_results}
    for item in new_items:
        url = str(item.get("url") or "").strip()
        if url and url not in seen:
            all_results.append(item)
            seen.add(url)


async def _crawl_entity(
    entity_name: str,
    aliases: list[str],
    max_results: int,
    settings: Settings,
) -> list[dict]:
    """Run all platform crawlers for a single entity.

    Uses agent-browser for PTT, and existing HTTP scrapers for
    Dcard (API) and Google Maps (SerpApi).
    """
    all_results: list[dict] = []

    # --- Level 1: PTT via agent-browser ---
    logger.info("[PTT] crawling %s ...", entity_name)
    try:
        ptt_results = await crawl_ptt_for_entity(entity_name, max_results=max_results)
        _dedup_merge(all_results, ptt_results)
        logger.info("[PTT] entity=%s results=%d", entity_name, len(ptt_results))
    except Exception as exc:
        logger.warning("[PTT] entity=%s failed: %s", entity_name, exc)

    # PTT aliases
    for alias in aliases[:2]:
        if alias == entity_name:
            continue
        try:
            extra = await crawl_ptt_for_entity(alias, max_results=max(5, max_results // 3))
            _dedup_merge(all_results, extra)
        except Exception as exc:
            logger.warning("[PTT] alias=%s failed: %s", alias, exc)

    # --- Level 1: Dcard via API ---
    logger.info("[Dcard] crawling %s ...", entity_name)
    try:
        dcard_results = await search_dcard(entity_name, max_results=max_results)
        _dedup_merge(all_results, dcard_results)
        logger.info("[Dcard] entity=%s results=%d", entity_name, len(dcard_results))
    except Exception as exc:
        logger.warning("[Dcard] entity=%s failed: %s", entity_name, exc)

    for alias in aliases[:2]:
        if alias == entity_name:
            continue
        try:
            extra = await search_dcard(alias, max_results=max(5, max_results // 3))
            _dedup_merge(all_results, extra)
        except Exception as exc:
            logger.warning("[Dcard] alias=%s failed: %s", alias, exc)

    # --- Level 1: Google Maps via SerpApi ---
    if settings.serpapi_api_key:
        logger.info("[Google Maps] crawling %s ...", entity_name)
        try:
            maps_results = await search_google_maps(
                entity_name,
                serpapi_key=settings.serpapi_api_key,
                max_results=max_results,
            )
            _dedup_merge(all_results, maps_results)
            logger.info("[Google Maps] entity=%s results=%d", entity_name, len(maps_results))
        except Exception as exc:
            logger.warning("[Google Maps] entity=%s failed: %s", entity_name, exc)
    else:
        logger.info("[Google Maps] skipped — no SERPAPI_API_KEY")

    # --- Level 3: DuckDuckGo WebSearch (broad discovery) ---
    logger.info("[DuckDuckGo] crawling %s ...", entity_name)
    try:
        ddg = DuckDuckGoService(settings)
        ddg_queries = [
            f"{entity_name} 評價",
            f"{entity_name} 評論",
            f"{entity_name} 爭議",
            f"{entity_name} 動保",
            f"{entity_name} 心得",
            f"site:facebook.com {entity_name}",
            f"site:dcard.tw {entity_name}",
            f"site:ptt.cc {entity_name}",
        ]
        ddg_results = await ddg.search_reviews(ddg_queries)
        _dedup_merge(all_results, ddg_results)
        logger.info("[DuckDuckGo] entity=%s results=%d", entity_name, len(ddg_results))
    except Exception as exc:
        logger.warning("[DuckDuckGo] entity=%s failed: %s", entity_name, exc)

    return all_results


async def _run() -> int:
    args = parse_args()
    settings_kwargs: dict = {}
    if args.database_path:
        settings_kwargs["database_path"] = args.database_path
    settings = Settings(**settings_kwargs)
    persistence = PersistenceService(settings)

    start_time = datetime.now(timezone.utc)
    logger.info("weekly_browser_crawl started at %s", start_time.isoformat())

    # Determine which entities to crawl
    if args.entity_names:
        # Manual mode: crawl the specified entities regardless of watchlist status
        entities = [
            {"name": name, "aliases": [], "entity_type": "unknown"}
            for name in args.entity_names
        ]
    elif args.all:
        # All mode: crawl every active watchlist entity, ignoring due-date
        import sqlite3
        db_path = settings.database_path
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("""
            SELECT e.name, e.entity_type, e.alias_json
            FROM entity_watchlists ew
            JOIN entities e ON e.id = ew.entity_id
            WHERE ew.is_active = 1
            ORDER BY ew.priority ASC, e.name ASC
        """).fetchall()
        conn.close()
        import json as _json
        entities = []
        for r in rows:
            aliases = []
            try:
                aliases = _json.loads(r["alias_json"]) if r["alias_json"] else []
            except (TypeError, ValueError):
                pass
            entities.append({
                "name": str(r["name"]),
                "aliases": [str(a) for a in aliases],
                "entity_type": str(r["entity_type"] or "organization"),
            })
        entities = entities[:args.limit]
    else:
        # Watchlist mode: get due watchlist entities
        watchlist = persistence.list_due_watchlist_entities(limit=args.limit)
        if not watchlist:
            from app.seed_data import WATCHLIST_SEED
            entities = [
                {
                    "name": str(item["canonical_name"]),
                    "aliases": [str(a) for a in item.get("aliases", [])],
                    "entity_type": str(item.get("entity_type", "organization")),
                }
                for item in WATCHLIST_SEED[:args.limit]
            ]
        else:
            entities = [
                {"name": w.entity_name, "aliases": w.aliases, "entity_type": w.entity_type}
                for w in watchlist
            ]

    logger.info("will crawl %d entities: %s", len(entities), [e["name"] for e in entities])

    total_new = 0
    total_entities = 0

    for entity in entities:
        entity_name = entity["name"]
        aliases = entity.get("aliases", [])
        logger.info("--- crawling entity: %s (aliases: %s) ---", entity_name, aliases)

        try:
            results = await _crawl_entity(
                entity_name,
                aliases,
                max_results=args.max_results,
                settings=settings,
            )
            logger.info("entity=%s raw_results=%d", entity_name, len(results))

            if results and not args.dry_run:
                cached = persistence.cache_raw_sources(results)
                logger.info("entity=%s cached_to_db=%d", entity_name, cached)
                total_new += cached
            elif results and args.dry_run:
                logger.info("entity=%s dry_run=True would_cache=%d", entity_name, len(results))
                for r in results[:3]:
                    logger.info("  sample: %s | %s", r["url"], r["title"][:60])
                total_new += len(results)

            total_entities += 1

        except Exception as exc:
            logger.error("entity=%s crawl_failed: %s", entity_name, exc)
            continue

    elapsed = (datetime.now(timezone.utc) - start_time).total_seconds()
    logger.info(
        "weekly_browser_crawl finished entities=%d new_sources=%d elapsed=%.1fs dry_run=%s",
        total_entities, total_new, elapsed, args.dry_run,
    )
    return 0


def main() -> None:
    raise SystemExit(asyncio.run(_run()))


if __name__ == "__main__":
    main()
