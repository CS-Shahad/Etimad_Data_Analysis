"""
Full collection of all "current tenders" available via
AllSupplierTendersForVisitorAsync, stored as one timestamped snapshot per
year partition in SQLite.

Based on confirmed PoC and production results:
- A plain httpx session (no browser) is enough to get past the F5 WAF
  cookies.
- The server actually caps rows per page (~24) regardless of the
  requested PageSize, so progress tracks the real length of "data", and
  completion is only signaled by an empty page (not totalCount, since
  that drifts on a live dataset).
- The server retries 429 and network timeouts/dropped connections
  transparently (fetch_tenders_page) instead of aborting the script.
- PublishDateId=1 ("any time") returns ~291,000 tenders. Plain pagination
  hard-fails (400) past some depth regardless of sort - confirmed
  2026-11-04: ~185,000 for DESC/no-sort, but only ~4,500 for ASC (a much
  less efficient query plan in that direction). Collecting both sort
  directions to meet in the middle didn't work: ASC's wall is too shallow.
- Fix: date-partition the archive by calendar year (date_partitions.py),
  using the site's own last-offer-presentation-date range filter
  (FromLastOfferPresentationDateString/ToLastOfferPresentationDateString -
  confirmed 2026-11-05 via the site's own date-range search). One full
  year (2020) reported totalCount=15,653 - comfortably under the depth
  wall - so every single request's result set stays small enough to never
  approach it, collected with the cheap DESC sort.
- Each partition has its own checkpoint
  (data/raw/checkpoint_current_tenders_<year>.json). A completed
  partition's checkpoint gets a "status": "done" marker instead of being
  cleared, so a future run skips it outright - a missing checkpoint file
  would otherwise be ambiguous between "never started" and "already done".
  Any wall-clock time budget is split only across partitions not yet
  marked done, so completed years stop taking a share of it.
- If a run is interrupted (repeated failures after retrying, a network
  drop, Ctrl+C, a time budget), it resumes from the last saved page per
  partition instead of starting over.

Usage:
    python scripts/collect_current_tenders_full.py
"""

import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from etimad_scraper.checkpoint import (
    checkpoint_path_for_partition,
    load_checkpoint,
    save_checkpoint,
)
from etimad_scraper.collect import collect_all_pages
from etimad_scraper.config import load_config
from etimad_scraper.date_partitions import year_partitions
from etimad_scraper.db import get_connection, insert_tenders
from etimad_scraper.runtime_budget import resolve_max_runtime_seconds
from etimad_scraper.session import build_session, fetch_tenders_page, warm_up


def collect_one_partition(
    cfg: dict, client, conn, partition_key: str, from_date: str, to_date: str, deadline
) -> None:
    checkpoint_path = checkpoint_path_for_partition(cfg["storage"]["checkpoint_path"], partition_key)
    page_size = cfg["current_tenders"]["collect_page_size"]

    checkpoint = load_checkpoint(checkpoint_path)
    if checkpoint:
        scraped_at = checkpoint["scraped_at"]
        start_page = checkpoint["last_completed_page"] + 1
        print(
            f"[{partition_key}] Found existing checkpoint: resuming snapshot {scraped_at} "
            f"from page {start_page} (instead of starting over)."
        )
    else:
        scraped_at = datetime.now(timezone.utc).isoformat()
        start_page = 1
        print(f"[{partition_key}] No checkpoint found, starting a new snapshot: {scraped_at}")

    def fetch_page_fn(page_number: int, size: int) -> dict:
        resp = fetch_tenders_page(
            client, cfg, page_number=page_number, page_size=size,
            sort_direction="DESC", from_date=from_date, to_date=to_date,
        )
        return resp.json()

    def polite_delay() -> None:
        time.sleep(
            random.uniform(
                cfg["request"]["min_delay_seconds"], cfg["request"]["max_delay_seconds"]
            )
        )

    def on_page(page_number: int, data: list, total_count) -> None:
        inserted = insert_tenders(conn, data, scraped_at)
        save_checkpoint(
            checkpoint_path,
            {
                "scraped_at": scraped_at,
                "last_completed_page": page_number,
                "total_count_last_seen": total_count,
            },
        )
        print(f"  [{partition_key}] page {page_number}: +{inserted} rows (reported totalCount={total_count})")

    print(f"[{partition_key}] Starting collection ({from_date} - {to_date})...")
    records, total_count, reached_end = collect_all_pages(
        fetch_page_fn,
        page_size=page_size,
        start_page=start_page,
        delay_fn=polite_delay,
        on_page=on_page,
        deadline=deadline,
    )

    if reached_end:
        # on_page already wrote the correct last_completed_page for every
        # page actually fetched (including across resumed runs) - just add
        # the "done" marker to what's there instead of recomputing it from
        # start_page/len(records), which wouldn't necessarily agree (and
        # wouldn't exist at all yet for a partition with zero tenders -
        # load_checkpoint then returns None, so {} is the base).
        current = load_checkpoint(checkpoint_path) or {}
        current["status"] = "done"
        current["scraped_at"] = scraped_at
        current["total_count_last_seen"] = total_count
        save_checkpoint(checkpoint_path, current)
        print(f"[{partition_key}] Done. Collected {len(records)} tenders this run (last reported totalCount={total_count})")
    else:
        print(
            f"[{partition_key}] Time budget reached (or the depth wall / max_pages safety "
            f"cap) after collecting {len(records)} tenders this run. Checkpoint saved - "
            f"rerun to continue (last reported totalCount={total_count})."
        )


def main() -> None:
    cfg = load_config()
    client = build_session(cfg)
    conn = get_connection(cfg["storage"]["sqlite_path"])
    partitions = year_partitions(cfg["current_tenders"]["archive_start_year"])

    max_runtime_seconds = resolve_max_runtime_seconds(
        "COLLECT_MAX_MINUTES", cfg["current_tenders"].get("max_runtime_minutes")
    )

    print("Warming up session...")
    warm_up(client, cfg, page_number=1)

    pending = []
    for key, from_date, to_date in partitions:
        checkpoint = load_checkpoint(checkpoint_path_for_partition(cfg["storage"]["checkpoint_path"], key))
        if checkpoint and checkpoint.get("status") == "done":
            continue
        pending.append((key, from_date, to_date))

    print(f"{len(partitions)} year partition(s) total, {len(pending)} still pending: "
          f"{[p[0] for p in pending]}")
    per_partition_seconds = max_runtime_seconds / len(pending) if max_runtime_seconds and pending else None
    if max_runtime_seconds:
        print(f"Time budget: {max_runtime_seconds / 60:.0f} minutes total, "
              f"{(per_partition_seconds or 0) / 60:.0f} minutes per pending partition")

    for key, from_date, to_date in pending:
        deadline = time.monotonic() + per_partition_seconds if per_partition_seconds else None
        try:
            collect_one_partition(cfg, client, conn, key, from_date, to_date, deadline)
        except httpx.HTTPStatusError as e:
            # Shouldn't normally happen - year partitions are sized to stay
            # well under the depth wall - but don't let one bad partition
            # skip the rest if it somehow does.
            print(f"[{key}] Stopped by a non-retryable HTTP error: {e}")

    conn.close()
    print(f"Saved to: {cfg['storage']['sqlite_path']}")


if __name__ == "__main__":
    main()
