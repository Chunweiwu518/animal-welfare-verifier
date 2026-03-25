from __future__ import annotations

import argparse
import csv
from pathlib import Path

from app.config import Settings
from app.services.persistence_service import PersistenceService


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import entity aliases from a CSV file.")
    parser.add_argument("csv_path", type=Path, help="Path to a CSV file with canonical_name,alias columns.")
    parser.add_argument(
        "--database-path",
        type=str,
        default=None,
        help="Optional override for the SQLite database path.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    settings_kwargs = {"database_path": args.database_path} if args.database_path else {}
    settings = Settings(**settings_kwargs)
    service = PersistenceService(settings)
    service.initialize()

    inserted = 0
    with args.csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required_columns = {"canonical_name", "alias"}
        if reader.fieldnames is None or not required_columns.issubset(set(reader.fieldnames)):
            raise SystemExit("CSV must contain canonical_name and alias columns.")

        for row in reader:
            canonical_name = (row.get("canonical_name") or "").strip()
            alias = (row.get("alias") or "").strip()
            if not canonical_name or not alias:
                continue
            service.register_entity_alias(canonical_name=canonical_name, alias=alias)
            inserted += 1

    print(f"Imported {inserted} alias rows from {args.csv_path}")


if __name__ == "__main__":
    main()
