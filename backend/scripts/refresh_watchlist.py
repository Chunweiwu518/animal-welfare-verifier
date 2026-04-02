from __future__ import annotations

import argparse
import asyncio

from app.config import Settings
from app.services.watchlist_refresh_service import WatchlistRefreshService


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Refresh due watchlist entities into the local database.")
    parser.add_argument("--database-path", type=str, default=None, help="Optional override for the SQLite database path.")
    parser.add_argument("--limit", type=int, default=None, help="Maximum number of due entities to refresh.")
    parser.add_argument(
        "--entity-name",
        action="append",
        dest="entity_names",
        default=None,
        help="Refresh only the specified entity name (can be passed multiple times).",
    )
    parser.add_argument(
        "--mode",
        action="append",
        choices=["general", "animal_law"],
        dest="modes",
        default=None,
        help="Restrict refresh to one or more modes. Defaults to each watchlist entity's default mode.",
    )
    parser.add_argument(
        "--questions-per-mode",
        type=int,
        default=None,
        help="How many seed questions to refresh for each selected mode.",
    )
    return parser.parse_args()


async def _run() -> int:
    args = parse_args()
    settings_kwargs = {"database_path": args.database_path} if args.database_path else {}
    settings = Settings(**settings_kwargs)
    service = WatchlistRefreshService(settings)
    result = await service.refresh_due_entities(
        limit=args.limit,
        entity_names=args.entity_names,
        include_modes=args.modes,
        questions_per_mode=args.questions_per_mode,
    )
    print(
        "watchlist refresh finished "
        f"processed={result.processed} succeeded={result.succeeded} failed={result.failed} skipped={result.skipped}"
    )
    for detail in result.details:
        print(detail)
    return 0 if result.failed == 0 else 1


def main() -> None:
    raise SystemExit(asyncio.run(_run()))


if __name__ == "__main__":
    main()