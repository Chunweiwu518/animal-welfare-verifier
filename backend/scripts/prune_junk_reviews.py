"""Mark clearly-junk existing reviews as content_type='unrelated'.

Targets rows with no user commentary — embed card titles, truncated URL
previews, numeric-only engagement strings, empty content — so the UI stops
surfacing them. Safe to re-run; idempotent.

Usage:
    .venv/bin/python -m scripts.prune_junk_reviews          # dry run
    .venv/bin/python -m scripts.prune_junk_reviews --apply
"""
from __future__ import annotations

import argparse
import logging
import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import Settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

EMBED_SUBSTRINGS = [
    "• Instagram", "Instagram 相片與影片", "• Threads",
    "• Facebook", "Facebook 貼文",
]
URL_PREVIEW_RE = re.compile(
    r"^(https?://|www\.)?"
    r"(instagram\.com|facebook\.com|youtube\.com|youtu\.be|fb\.com|threads\.net|t\.co)"
    r"[/\w@.\-]*[…\.]+$",
    re.IGNORECASE,
)
NUM_WITH_COMMA_RE = re.compile(r"^[\d,]+$")
ONLY_EMOJI_OR_PUNCT_RE = re.compile(
    r"^[\s\W\d]+$"
)  # no Chinese/alpha letters at all


def is_junk(content: str) -> bool:
    c = (content or "").strip()
    if not c:
        return True
    if len(c) < 6:
        return True
    if NUM_WITH_COMMA_RE.match(c):
        return True
    if URL_PREVIEW_RE.match(c):
        return True
    for sub in EMBED_SUBSTRINGS:
        if sub in c:
            return True
    if ONLY_EMOJI_OR_PUNCT_RE.match(c):
        return True
    return False


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    settings = Settings()
    conn = sqlite3.connect(settings.database_path)
    conn.row_factory = sqlite3.Row

    rows = conn.execute(
        "SELECT id, platform, content, content_type FROM reviews"
    ).fetchall()

    junk_ids: list[int] = []
    already_unrelated = 0
    per_platform: dict[str, int] = {}
    for r in rows:
        if not is_junk(r["content"] or ""):
            continue
        if r["content_type"] == "unrelated":
            already_unrelated += 1
            continue
        junk_ids.append(int(r["id"]))
        per_platform[r["platform"]] = per_platform.get(r["platform"], 0) + 1

    logger.info(
        "Found %d junk rows to re-label (already unrelated: %d). By platform: %s",
        len(junk_ids), already_unrelated, per_platform,
    )

    if not junk_ids:
        return

    if args.apply:
        # chunked update to keep the SQL parameter list safe
        for i in range(0, len(junk_ids), 500):
            chunk = junk_ids[i : i + 500]
            placeholders = ",".join("?" * len(chunk))
            conn.execute(
                f"UPDATE reviews SET content_type='unrelated', "
                f"relevance_score=0.0, stance='unclear', short_summary='' "
                f"WHERE id IN ({placeholders})",
                chunk,
            )
        conn.commit()
        logger.info("Applied. Re-labeled %d rows to unrelated.", len(junk_ids))
    else:
        logger.info("DRY RUN. Re-run with --apply to write.")


if __name__ == "__main__":
    main()
