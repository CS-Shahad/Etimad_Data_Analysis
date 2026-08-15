"""
Exports tender_details, tender_bids, and tender_detail_failures (SQLite)
to CSV files under data/processed/ - committed to git so a fresh
GitHub Actions runner (or a fresh Codespace) can reconstruct exactly what
has already been fetched without needing the gitignored etimad.db itself.
See rebuild_db_from_csv.py for the reverse direction.

Usage:
    python scripts/export_tender_details_csv.py
    git add data/processed/tender_details.csv data/processed/tender_bids.csv data/processed/tender_detail_failures.csv
    git commit -m "..."
    git push
"""

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pandas as pd

from etimad_scraper.config import load_config

TABLES_AND_CONFIG_KEYS = [
    ("tender_details", "tender_details_csv_path", "tender_id"),
    ("tender_bids", "tender_bids_csv_path", "tender_id, supplier_name"),
    ("tender_detail_failures", "tender_detail_failures_csv_path", "tender_id, failed_at"),
]


def main() -> None:
    cfg = load_config()
    conn = sqlite3.connect(cfg["storage"]["sqlite_path"])

    for table, config_key, order_by in TABLES_AND_CONFIG_KEYS:
        df = pd.read_sql_query(f"SELECT * FROM {table} ORDER BY {order_by}", conn)
        csv_path = Path(cfg["storage"][config_key])
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(csv_path, index=False, encoding="utf-8-sig")
        print(f"Exported {len(df)} rows from {table} to {csv_path}")

    conn.close()


if __name__ == "__main__":
    main()
