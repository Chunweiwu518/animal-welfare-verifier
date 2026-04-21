"""Wipe the DB and re-import the watchlist from 動保列表.xlsx.

Reads two sheets:
- Sheet 1 (15 rows): 協會/狗園/公立收容所
- Sheet 2 (17 rows): 學生社團

Produces:
- 32 entities in DB
- Writes FACEBOOK_PAGE_IDS mapping to backend/.env
- Deletes data/media/* files

Cover images are intentionally NOT fetched here — run `refresh_all_covers.py` after.
"""
from __future__ import annotations

import logging
import re
import shutil
import sqlite3
import sys
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import Settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

NS = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
CELL_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"

XLSX_PATH = Path(__file__).resolve().parent.parent.parent / "動保列表.xlsx"

# Column letter -> meaning. Sheet1 and Sheet2 have different layouts.
SHEET1_COLS = {
    "A": "name",
    "G": "keywords",
    "K": "entity_type",
    "M": "region",
    "O": "registered",
    "Q": "leader",
    "S": "founded",
    "U": "capital",
    "W": "service_type",
    "Y": "fb_url",
    "AJ": "ig_url",
    "AR": "line",
    "AY": "yt_url",
    "BI": "website",
    "BM": "notes",
}

SHEET2_COLS = {
    "A": "name",
    "G": "entity_type",
    "I": "region",
    "K": "founded",
    "M": "service_type",
    "O": "fb_url",
    "Z": "ig_url",
    "AH": "line",
    "AO": "yt_url",
    "AW": "website",
    "BA": "notes",
}


def _col_letter(cell_ref: str) -> str:
    """Extract column letters from cell ref like 'AB12' → 'AB'."""
    m = re.match(r"([A-Z]+)\d+$", cell_ref)
    return m.group(1) if m else ""


def _read_xlsx_rows(xlsx_path: Path, sheet_name: str, col_map: dict[str, str]) -> list[dict]:
    """Return list of dicts, one per data row (header excluded)."""
    with zipfile.ZipFile(xlsx_path) as z:
        shared: list[str] = []
        if "xl/sharedStrings.xml" in z.namelist():
            tree = ET.fromstring(z.read("xl/sharedStrings.xml"))
            for si in tree.findall("x:si", NS):
                shared.append(
                    "".join(t.text or "" for t in si.iter(f"{CELL_NS}t"))
                )

        tree = ET.fromstring(z.read(sheet_name))
        rows = tree.findall(".//x:row", NS)

    result: list[dict] = []
    for row in rows:
        row_num = int(row.get("r", "0"))
        if row_num < 2:
            continue  # skip header
        record: dict[str, str] = {v: "" for v in col_map.values()}
        has_name = False
        for cell in row.findall("x:c", NS):
            letter = _col_letter(cell.get("r", ""))
            if letter not in col_map:
                continue
            t = cell.get("t")
            v_el = cell.find("x:v", NS)
            v_text = v_el.text if v_el is not None else ""
            if t == "s":
                idx = int(v_text) if v_text else 0
                val = shared[idx] if 0 <= idx < len(shared) else ""
            elif t == "inlineStr":
                is_el = cell.find("x:is", NS)
                val = (
                    "".join(t.text or "" for t in is_el.iter(f"{CELL_NS}t"))
                    if is_el is not None
                    else ""
                )
            else:
                val = v_text or ""
            val = val.strip()
            record[col_map[letter]] = val
            if col_map[letter] == "name" and val:
                has_name = True
        if has_name:
            result.append(record)
    return result


def _split_keywords(raw: str) -> list[str]:
    if not raw:
        return []
    parts = re.split(r"[/,、，]", raw)
    return [p.strip() for p in parts if p.strip()]


def _build_intro(record: dict) -> str:
    bits: list[str] = []
    if record.get("service_type"):
        bits.append(f"服務：{record['service_type']}")
    if record.get("entity_type"):
        bits.append(f"類型：{record['entity_type']}")
    if record.get("founded"):
        bits.append(f"成立：{record['founded']}")
    if record.get("leader"):
        bits.append(f"負責人：{record['leader']}")
    if record.get("website"):
        bits.append(f"官網：{record['website']}")
    if record.get("fb_url"):
        bits.append(f"Facebook：{record['fb_url']}")
    if record.get("ig_url"):
        bits.append(f"Instagram：{record['ig_url']}")
    if record.get("notes"):
        bits.append(f"備註：{record['notes']}")
    return "\n".join(bits)


def _wipe_db(conn: sqlite3.Connection) -> None:
    tables = [
        "query_summaries",
        "evidence_cards",
        "search_queries",
        "entity_summary_snapshots",
        "entity_question_suggestions",
        "reviews",
        "entity_comments",
        "media_files",
        "entity_page_profiles",
        "entity_keywords",
        "entity_watchlists",
        "pipeline_runs",
        "sources",
        "entities",
    ]
    for t in tables:
        try:
            conn.execute(f"DELETE FROM {t}")
            logger.info("  cleared %s", t)
        except sqlite3.OperationalError as exc:
            logger.debug("  skip %s: %s", t, exc)
    # Reset autoincrement counters so IDs start from 1
    try:
        conn.execute("DELETE FROM sqlite_sequence")
    except sqlite3.OperationalError:
        pass


def _wipe_media_files(media_dir: Path) -> int:
    if not media_dir.exists():
        return 0
    count = 0
    for p in media_dir.iterdir():
        if p.is_file():
            p.unlink()
            count += 1
    return count


def _update_env_fb_ids(env_path: Path, mappings: list[tuple[str, str]]) -> None:
    fb_value = ";".join(f"{name}|{url}" for name, url in mappings)
    content = env_path.read_text(encoding="utf-8")
    if "FACEBOOK_PAGE_IDS=" in content:
        content = re.sub(
            r"^FACEBOOK_PAGE_IDS=.*$",
            f"FACEBOOK_PAGE_IDS={fb_value}",
            content,
            flags=re.MULTILINE,
        )
    else:
        content = content.rstrip() + f"\nFACEBOOK_PAGE_IDS={fb_value}\n"
    env_path.write_text(content, encoding="utf-8")


def main() -> None:
    settings = Settings()
    db_path = Path(settings.database_path)

    # Read both sheets
    sheet1 = _read_xlsx_rows(XLSX_PATH, "xl/worksheets/sheet1.xml", SHEET1_COLS)
    sheet2 = _read_xlsx_rows(XLSX_PATH, "xl/worksheets/sheet2.xml", SHEET2_COLS)
    all_entities = sheet1 + sheet2
    logger.info("Loaded %d from sheet1 + %d from sheet2 = %d total", len(sheet1), len(sheet2), len(all_entities))

    # Backup and wipe
    backup = db_path.with_suffix(".db.bak-before-reimport")
    if db_path.exists():
        shutil.copy(db_path, backup)
        logger.info("Backed up DB to %s", backup)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = OFF")

    with conn:
        _wipe_db(conn)
    logger.info("DB wiped")

    media_deleted = _wipe_media_files(Path(settings.media_upload_dir))
    logger.info("Deleted %d media files", media_deleted)

    fb_mappings: list[tuple[str, str]] = []

    with conn:
        import json

        for rec in all_entities:
            name = rec["name"]
            aliases = _split_keywords(rec.get("keywords", "")) if "keywords" in rec else []
            entity_type = rec.get("entity_type") or "organization"
            intro = _build_intro(rec)
            location = rec.get("region", "")

            cur = conn.execute(
                "INSERT INTO entities (name, entity_type, alias_json) VALUES (?, ?, ?)",
                (name, entity_type, json.dumps(sorted(aliases), ensure_ascii=False)),
            )
            entity_id = int(cur.lastrowid)

            for alias in aliases:
                if alias == name:
                    continue
                conn.execute(
                    "INSERT OR IGNORE INTO entity_keywords (entity_id, keyword, keyword_type, weight, is_active) VALUES (?, ?, 'alias', 70, 1)",
                    (entity_id, alias),
                )

            conn.execute(
                """
                INSERT INTO entity_page_profiles (
                    entity_id, headline, introduction, location,
                    cover_image_url, cover_image_alt, gallery_json, updated_at
                ) VALUES (?, ?, ?, ?, '', '', '[]', CURRENT_TIMESTAMP)
                """,
                (entity_id, name, intro, location),
            )

            conn.execute(
                """
                INSERT INTO entity_watchlists (
                    entity_id, is_active, priority, refresh_interval_hours,
                    default_mode, next_crawl_at
                ) VALUES (?, 1, 3, 720, 'general', NULL)
                """,
                (entity_id,),
            )

            fb = rec.get("fb_url", "").strip()
            if fb.startswith(("http://", "https://")) and (
                "facebook.com" in fb.lower() or "fb.com" in fb.lower()
            ):
                fb_mappings.append((name, fb.rstrip("/").split("?")[0]))

            logger.info(
                "  [%s] type=%s aliases=%d fb=%s",
                name,
                entity_type,
                len(aliases),
                "Y" if fb else "-",
            )

    conn.close()

    env_path = Path(__file__).resolve().parent.parent / ".env"
    _update_env_fb_ids(env_path, fb_mappings)
    logger.info("Wrote %d FB mappings to %s", len(fb_mappings), env_path)

    logger.info("Done. Entities: %d | FB URLs: %d", len(all_entities), len(fb_mappings))


if __name__ == "__main__":
    main()
