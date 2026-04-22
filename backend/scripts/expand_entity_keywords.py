"""Expand entity_keywords with rule-based aliases for Taiwan animal welfare orgs.

For each entity we derive extra aliases by:
  - Stripping legal-form prefixes: 社團法人 / 財團法人 / 中華民國
  - Stripping leading county/city (臺南市, 高雄市, ...)
  - Stripping trailing org-form: 協會 / 基金會 / 推廣協會 / ...
  - Swapping 台 <-> 臺
  - Keeping the stripped core name as an alias
  - Adding core + 狗園 / 動保 hint if already implied

Usage:
    .venv/bin/python -m scripts.expand_entity_keywords                 # dry run
    .venv/bin/python -m scripts.expand_entity_keywords --apply         # actually write
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import Settings
from app.services.persistence_service import PersistenceService

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

LEGAL_PREFIXES = ["社團法人", "財團法人", "中華民國", "國立", "私立"]
CITY_PREFIXES = [
    "臺北市", "台北市", "新北市", "桃園市", "臺中市", "台中市",
    "臺南市", "台南市", "高雄市", "基隆市", "新竹市", "新竹縣",
    "苗栗縣", "彰化縣", "南投縣", "雲林縣", "嘉義市", "嘉義縣",
    "屏東縣", "宜蘭縣", "花蓮縣", "臺東縣", "台東縣", "澎湖縣",
    "金門縣", "連江縣",
]
TRAILING_FORMS = [
    "推廣協會", "研究協會", "關懷協會",
    "動物保護協會", "流浪動物協會", "護生協會", "愛護協會",
    "福利基金會", "生命基金會",
    "協會", "基金會", "志工隊", "志工團",
]

# Aliases matching any of these alone are too generic to search with.
GENERIC_BLOCKLIST = {
    "關懷", "保護", "動物", "流浪", "動保", "生命", "愛護", "護生",
    "基金會", "協會", "志工", "中心", "社團", "研究", "推廣", "照護",
    "臺灣", "台灣", "中華民國",
}
MIN_ALIAS_LENGTH = 4


def _variants(name: str) -> set[str]:
    core = name.strip()
    out: set[str] = {core}

    changed = True
    while changed:
        changed = False
        for p in LEGAL_PREFIXES:
            if core.startswith(p):
                core = core[len(p) :]
                changed = True
        for p in CITY_PREFIXES:
            if core.startswith(p):
                core = core[len(p) :]
                changed = True
    out.add(core)

    # trim trailing forms from the post-prefix core
    trimmed = core
    for t in TRAILING_FORMS:
        if trimmed.endswith(t) and len(trimmed) > len(t) + 1:
            trimmed = trimmed[: -len(t)]
            break
    out.add(trimmed)

    # 台 <-> 臺 swap on every variant so far
    swapped = set()
    for v in out:
        if "台" in v:
            swapped.add(v.replace("台", "臺"))
        if "臺" in v:
            swapped.add(v.replace("臺", "台"))
    out |= swapped

    # strip generic noise
    cleaned = set()
    for v in out:
        v = re.sub(r"\s+", " ", v).strip("·、， 。．.")
        if len(v) < MIN_ALIAS_LENGTH:
            continue
        if v in GENERIC_BLOCKLIST:
            continue
        cleaned.add(v)
    cleaned.discard("")
    return cleaned


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="Actually write (default: dry-run)")
    args = parser.parse_args()

    settings = Settings()
    persistence = PersistenceService(settings)
    persistence.initialize()

    conn = sqlite3.connect(settings.database_path)
    conn.row_factory = sqlite3.Row

    entities = conn.execute("SELECT id, name, alias_json FROM entities").fetchall()
    total_added = 0
    for e in entities:
        existing = {
            r["keyword"]
            for r in conn.execute(
                "SELECT keyword FROM entity_keywords WHERE entity_id=?", (e["id"],)
            )
        }
        try:
            current_aliases = [
                a for a in json.loads(e["alias_json"] or "[]") if isinstance(a, str)
            ]
        except json.JSONDecodeError:
            current_aliases = []
        all_variants = _variants(e["name"]) - {e["name"]}
        candidates = all_variants - existing
        desired_aliases = sorted({*current_aliases, *all_variants})
        needs_alias_sync = desired_aliases != sorted(current_aliases)
        if not candidates and not needs_alias_sync:
            continue
        logger.info("[%s]", e["name"])
        for c in sorted(candidates):
            logger.info("  + %s", c)
            if args.apply:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO entity_keywords
                        (entity_id, keyword, keyword_type, weight, is_active, updated_at)
                    VALUES (?, ?, 'alias', 70, 1, CURRENT_TIMESTAMP)
                    """,
                    (e["id"], c),
                )
        if args.apply and needs_alias_sync:
            conn.execute(
                "UPDATE entities SET alias_json=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (json.dumps(desired_aliases, ensure_ascii=False), e["id"]),
            )
        total_added += len(candidates)

    if args.apply:
        conn.commit()
        logger.info("Applied. Added %d aliases across %d entities.", total_added, len(entities))
    else:
        logger.info("DRY RUN. Would add %d aliases. Re-run with --apply.", total_added)


if __name__ == "__main__":
    main()
