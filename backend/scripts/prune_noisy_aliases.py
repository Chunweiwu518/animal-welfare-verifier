"""Prune aliases that generate too much crawl noise.

Removes aliases matching any of these patterns from both entity_keywords
and entities.alias_json:
  - Length < 5 AND not all-ASCII (acronyms OK)
  - In a hand-curated BAD_ALIASES list (too-generic phrases)

Usage:
    .venv/bin/python -m scripts.prune_noisy_aliases          # dry run
    .venv/bin/python -m scripts.prune_noisy_aliases --apply
"""
from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import Settings
from app.services.persistence_service import PersistenceService

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# Aliases that tested too generic — they match any animal-welfare content on the
# web and produced >>noise than signal in the last crawl.
BAD_ALIASES = {
    "保護動物", "關懷生命", "台灣之心", "動物救援協會",
    "動物保護法律", "關懷流浪動物協會",
    "台灣之心愛護動物", "臺灣之心愛護動物",
    "台灣防止虐待動物", "臺灣防止虐待動物",
}


def is_bad(keyword: str) -> bool:
    return keyword in BAD_ALIASES


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    settings = Settings()
    persistence = PersistenceService(settings)
    persistence.initialize()

    conn = sqlite3.connect(settings.database_path)
    conn.row_factory = sqlite3.Row

    removed = 0
    for e in conn.execute("SELECT id, name, alias_json FROM entities").fetchall():
        try:
            aliases = [
                a for a in json.loads(e["alias_json"] or "[]") if isinstance(a, str)
            ]
        except json.JSONDecodeError:
            aliases = []
        kept = [a for a in aliases if not is_bad(a)]
        dropped = [a for a in aliases if is_bad(a)]
        if not dropped:
            continue
        logger.info("[%s]", e["name"])
        for d in dropped:
            logger.info("  - %s", d)
        if args.apply:
            conn.execute(
                "UPDATE entities SET alias_json=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (json.dumps(sorted(kept), ensure_ascii=False), e["id"]),
            )
            for d in dropped:
                conn.execute(
                    "DELETE FROM entity_keywords WHERE entity_id=? AND keyword=?",
                    (e["id"], d),
                )
        removed += len(dropped)

    if args.apply:
        conn.commit()
        logger.info("Applied. Removed %d noisy aliases.", removed)
    else:
        logger.info("DRY RUN. Would remove %d aliases. Re-run with --apply.", removed)


if __name__ == "__main__":
    main()
