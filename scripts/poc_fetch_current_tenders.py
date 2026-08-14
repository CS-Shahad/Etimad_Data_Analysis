"""
Proof-of-concept for the "current tenders" data source.

Validates two open questions before we build the full pagination loop:
1. Does a plain HTTP session (no browser engine) get past the F5 WAF
   cookies, or does the endpoint start returning 403s and force us onto
   the Playwright fallback?
2. What is the real upper bound the server accepts for PageSize? The UI
   default is 6, which would mean ~1180 requests for the full ~7080
   tenders currently listed.

Usage:
    python scripts/poc_fetch_current_tenders.py
"""

import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from etimad_scraper.config import load_config
from etimad_scraper.db import get_connection, insert_tenders
from etimad_scraper.session import build_session, fetch_tenders_page, warm_up


def polite_sleep(cfg: dict) -> None:
    delay = random.uniform(
        cfg["request"]["min_delay_seconds"], cfg["request"]["max_delay_seconds"]
    )
    time.sleep(delay)


def probe_page_size(client, cfg: dict) -> int:
    """Tries each candidate PageSize against page 1 and returns the largest
    one the server actually honors (judged by how many rows come back)."""
    working_size = cfg["current_tenders"]["page_size_candidates"][0]

    for candidate in cfg["current_tenders"]["page_size_candidates"]:
        resp = fetch_tenders_page(client, cfg, page_number=1, page_size=candidate)
        print(f"  PageSize={candidate} -> HTTP {resp.status_code}", end="")

        if resp.status_code != 200:
            print(" (stopping probe here)")
            break

        payload = resp.json()
        returned = len(payload.get("data", []))
        reported_page_size = payload.get("pageSize")
        print(f", rows returned={returned}, server-echoed pageSize={reported_page_size}")

        if returned >= min(candidate, 1):
            working_size = candidate
        polite_sleep(cfg)

    return working_size


def main() -> None:
    cfg = load_config()
    client = build_session(cfg)

    print("Step 1: warming up session on the human-facing listing page...")
    warm_up_resp = warm_up(client, cfg, page_number=1)
    print(f"  bootstrap GET -> HTTP {warm_up_resp.status_code}, "
          f"cookies received: {list(client.cookies.keys())}")
    polite_sleep(cfg)

    print("Step 2: probing accepted PageSize values...")
    page_size = probe_page_size(client, cfg)
    print(f"  -> using PageSize={page_size} for the rest of this PoC")
    polite_sleep(cfg)

    print("Step 3: fetching 2 pages of real data and storing them in SQLite...")
    conn = get_connection(cfg["storage"]["sqlite_path"])
    scraped_at = datetime.now(timezone.utc).isoformat()

    total_inserted = 0
    for page_number in (1, 2):
        resp = fetch_tenders_page(client, cfg, page_number=page_number, page_size=page_size)
        if resp.status_code != 200:
            print(f"  page {page_number}: HTTP {resp.status_code}, aborting")
            break

        payload = resp.json()
        records = payload.get("data", [])
        inserted = insert_tenders(conn, records, scraped_at)
        total_inserted += inserted
        print(f"  page {page_number}: {inserted} rows inserted "
              f"(reported totalCount={payload.get('totalCount')})")
        polite_sleep(cfg)

    conn.close()
    print(f"Done. {total_inserted} rows written to {cfg['storage']['sqlite_path']}")


if __name__ == "__main__":
    main()
