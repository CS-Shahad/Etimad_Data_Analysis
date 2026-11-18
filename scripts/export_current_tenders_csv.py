"""
Exports the latest known snapshot of each tender in current_tenders
(SQLite) to a single CSV file under data/processed/ - the one project
data path deliberately committed to git, unlike etimad.db (gitignored,
fully regenerable by rerunning the collection scripts). The per-direction
checkpoint files (data/raw/checkpoint_current_tenders_*.json) are
committed too, but separately by the GitHub Actions workflow - not
exported here.

Exports one row per tender_id (its most recent scraped_at), not the full
append-only history - confirmed 2026-11-18 that exporting every snapshot
ever collected let the file grow past GitHub's hard 100MB push limit
(101.64MB, rejected outright - "pre-receive hook declined"), including
snapshots that were pure dead weight: repeated re-scrapes of the same
~7,000-36,000 "current" tenders from before the PublishDateId fix (the
rolling-3-month-window bug), now fully superseded by the full-archive
collection. Nothing in the project actually reads the full snapshot
history - get_ended_tenders() and the rest only ever care about each
tender's latest known state - so this costs no functionality.

Compressed as .csv.gz rather than plain .csv: even after deduplication,
the full ~291,000-tender archive would still land close to GitHub's
100MB limit once collection is complete, so a plain CSV would just hit
the same wall again later. pandas reads/writes the .gz transparently
(both here and in rebuild_db_from_csv.py) from the file extension alone,
so nothing downstream needs to know the file is compressed.

Usage:
    python scripts/export_current_tenders_csv.py
    git add data/processed/current_tenders.csv.gz
    git commit -m "..."
    git push
"""

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pandas as pd

from etimad_scraper.config import load_config

# Mirrors db._ENDED_TENDERS_SQL's latest-snapshot-per-tender join.
_LATEST_SNAPSHOT_SQL = """
SELECT t.*
FROM current_tenders t
INNER JOIN (
    SELECT tender_id, MAX(scraped_at) AS latest_scraped_at
    FROM current_tenders
    GROUP BY tender_id
) latest
    ON t.tender_id = latest.tender_id
   AND t.scraped_at = latest.latest_scraped_at
ORDER BY t.tender_id
"""


def main() -> None:
    cfg = load_config()
    sqlite_path = cfg["storage"]["sqlite_path"]
    csv_path = Path(cfg["storage"]["csv_export_path"])

    conn = sqlite3.connect(sqlite_path)
    df = pd.read_sql_query(_LATEST_SNAPSHOT_SQL, conn)
    conn.close()

    csv_path.parent.mkdir(parents=True, exist_ok=True)
    # utf-8-sig (BOM) so the Arabic columns display correctly when opened
    # directly in Excel on Windows, not just in pandas/a text editor.
    df.to_csv(csv_path, index=False, encoding="utf-8-sig")

    print(f"Exported {len(df)} tenders (latest snapshot each) to {csv_path}")


if __name__ == "__main__":
    main()
