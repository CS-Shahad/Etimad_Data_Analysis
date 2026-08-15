"""
Rebuilds a fresh local SQLite db (data/raw/etimad.db) from the CSVs
committed under data/processed/. Meant to run first thing on a clean
checkout - a GitHub Actions runner, or a fresh Codespace - so scripts like
fetch_tender_details.py have the full history (which tenders are ended,
which already have details fetched) without ever needing the gitignored
etimad.db to be carried between environments.

Silently skips any CSV that doesn't exist yet (e.g. tender_bids.csv before
the first details backfill has run), rather than failing - a repo that
only has current_tenders.csv committed is a valid starting state.

Usage:
    python scripts/rebuild_db_from_csv.py
"""

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pandas as pd

from etimad_scraper.config import load_config
from etimad_scraper.db import get_connection

TABLES_AND_CONFIG_KEYS = [
    ("current_tenders", "csv_export_path"),
    ("tender_details", "tender_details_csv_path"),
    ("tender_bids", "tender_bids_csv_path"),
    ("tender_detail_failures", "tender_detail_failures_csv_path"),
]


def main() -> None:
    cfg = load_config()

    db_path = Path(cfg["storage"]["sqlite_path"])
    if db_path.exists():
        print(f"{db_path} already exists, not overwriting. Delete it first if you want a clean rebuild.")
        return

    conn = get_connection(db_path)

    for table, config_key in TABLES_AND_CONFIG_KEYS:
        csv_path = Path(cfg["storage"][config_key])
        if not csv_path.exists():
            print(f"{csv_path} not found, skipping {table}.")
            continue

        df = pd.read_csv(csv_path)
        if df.empty:
            print(f"{csv_path} is empty, skipping {table}.")
            continue

        df.to_sql(table, conn, if_exists="append", index=False)
        print(f"Loaded {len(df)} rows from {csv_path} into {table}")

    conn.close()


if __name__ == "__main__":
    main()
