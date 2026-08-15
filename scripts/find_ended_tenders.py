"""
Identifies which tenders in current_tenders (SQLite) are past their
submission deadline (last_offer_presentation_date), based on the latest
snapshot (scraped_at) per tender, and exports them to a separate CSV.

This is the list we'll use later as input for scraping the "basic info"
and "award results" tabs only for ended tenders (which may have award
data), instead of trying to fetch it for every open tender - those
definitely don't have award data yet.

Usage:
    python scripts/find_ended_tenders.py
"""

import csv
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from etimad_scraper.config import load_config
from etimad_scraper.db import get_connection, get_ended_tenders


def main() -> None:
    cfg = load_config()
    conn = get_connection(cfg["storage"]["sqlite_path"])
    now_iso = datetime.now(timezone.utc).isoformat()

    ended = get_ended_tenders(conn, now_iso)
    conn.close()

    print(f"Ended tenders (latest snapshot per tender, as of {now_iso}): {len(ended)}")

    out_path = Path(cfg["storage"]["ended_tenders_csv_path"])
    if not ended:
        print("Nothing to export.")
        return

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(ended[0].keys()))
        writer.writeheader()
        writer.writerows(ended)

    print(f"Saved to: {out_path}")


if __name__ == "__main__":
    main()
