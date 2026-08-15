"""
Fetches the extra "basic info" fields and "award results" only for ended
tenders (via get_ended_tenders), storing them in the tender_details and
tender_bids tables.

Incremental by construction: any tender_id already present in
tender_details is skipped, so rerunning the script after more tenders
close only fetches the delta - no separate checkpoint file needed like
the first collection script.

Usage:
    python scripts/fetch_tender_details.py
"""

import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from etimad_scraper.config import load_config
from etimad_scraper.db import (
    get_connection,
    get_ended_tenders,
    get_fetched_tender_detail_ids,
    insert_tender_bids,
    insert_tender_detail_failure,
    insert_tender_details,
)
from etimad_scraper.parse_html import parse_awarding_results, parse_basic_info_report
from etimad_scraper.session import build_session, fetch_awarding_results, fetch_basic_info_report, warm_up


def polite_delay(cfg: dict) -> None:
    time.sleep(
        random.uniform(cfg["request"]["min_delay_seconds"], cfg["request"]["max_delay_seconds"])
    )


def main() -> None:
    cfg = load_config()
    client = build_session(cfg)
    conn = get_connection(cfg["storage"]["sqlite_path"])

    now_iso = datetime.now(timezone.utc).isoformat()
    ended = get_ended_tenders(conn, now_iso)
    already_fetched = get_fetched_tender_detail_ids(conn)
    pending = [t for t in ended if t["tender_id"] not in already_fetched]

    print(f"Ended tenders: {len(ended)}, already fetched: {len(already_fetched)}, pending: {len(pending)}")
    if not pending:
        print("Nothing new.")
        return

    print("Warming up session...")
    warm_up(client, cfg, page_number=1)

    failures = 0
    for i, tender in enumerate(pending, start=1):
        tender_id = tender["tender_id"]
        tender_id_string = tender["tender_id_string"]
        fetched_at = datetime.now(timezone.utc).isoformat()

        try:
            report_resp = fetch_basic_info_report(client, cfg, tender_id_string)
            details = parse_basic_info_report(report_resp.text)
            insert_tender_details(conn, tender_id, details, fetched_at)
            polite_delay(cfg)

            award_resp = fetch_awarding_results(client, cfg, tender_id_string)
            award_data = parse_awarding_results(award_resp.text)
            n_bids = insert_tender_bids(
                conn, tender_id, award_data["bidders"], award_data["awarded"], fetched_at
            )
            polite_delay(cfg)
        except httpx.HTTPStatusError as e:
            # A handful of tender_id_strings contain characters (seen: *, @)
            # that make this endpoint 400 outright - not a rate-limit issue
            # (that's already retried inside fetch_*), a real problem with
            # this specific tender. Recorded, not fetched_at-stamped, so a
            # rerun retries it automatically instead of one bad id killing
            # progress on the other ~5700 tenders.
            failures += 1
            insert_tender_detail_failure(
                conn, tender_id, tender_id_string, str(e), fetched_at
            )
            print(f"  [{i}/{len(pending)}] tender_id={tender_id}: FAILED ({e}), skipping")
            polite_delay(cfg)
            continue

        print(
            f"  [{i}/{len(pending)}] tender_id={tender_id}: "
            f"{'awarded' if award_data['awarded'] else 'not yet awarded'} "
            f"({n_bids} bid(s) recorded)"
        )

    conn.close()
    print(f"Done. Fetched details for {len(pending) - failures} tender(s), {failures} failed (will retry next run).")


if __name__ == "__main__":
    main()
