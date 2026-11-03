"""
Full collection of all "current tenders" available via
AllSupplierTendersForVisitorAsync, stored as one timestamped snapshot
(a shared scraped_at) in SQLite.

Based on confirmed PoC and production results:
- A plain httpx session (no browser) is enough to get past the F5 WAF
  cookies.
- The server actually caps rows per page (~24) regardless of the
  requested PageSize, so progress tracks the real length of "data", and
  completion is only signaled by an empty page (not totalCount, since
  that drifts on a live dataset).
- The server starts returning 429 (rate limiting) after ~177 pages,
  handled with retry + backoff (60s+) instead of aborting the script.
- If a run is interrupted (repeated 429s, a network drop, Ctrl+C, a time
  budget), it resumes from the last saved page instead of starting over,
  via a checkpoint file.
- PublishDateId=1 ("any time") returns ~291,000 tenders (~12,100 pages at
  the ~24-row cap above) - confirmed 2026-11-03, far more than a single
  run (or a single GitHub Actions job, hard-capped at 6 hours) can finish,
  hence the time budget below.

Usage:
    python scripts/collect_current_tenders_full.py
"""

import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from etimad_scraper.checkpoint import clear_checkpoint, load_checkpoint, save_checkpoint
from etimad_scraper.collect import collect_all_pages
from etimad_scraper.config import load_config
from etimad_scraper.db import get_connection, insert_tenders
from etimad_scraper.runtime_budget import resolve_max_runtime_seconds
from etimad_scraper.session import build_session, fetch_tenders_page, warm_up


def main() -> None:
    cfg = load_config()
    client = build_session(cfg)
    conn = get_connection(cfg["storage"]["sqlite_path"])
    checkpoint_path = cfg["storage"]["checkpoint_path"]
    page_size = cfg["current_tenders"]["collect_page_size"]

    max_runtime_seconds = resolve_max_runtime_seconds(
        "COLLECT_MAX_MINUTES", cfg["current_tenders"].get("max_runtime_minutes")
    )
    deadline = time.monotonic() + max_runtime_seconds if max_runtime_seconds else None

    checkpoint = load_checkpoint(checkpoint_path)
    if checkpoint:
        scraped_at = checkpoint["scraped_at"]
        start_page = checkpoint["last_completed_page"] + 1
        print(
            f"Found existing checkpoint: resuming snapshot {scraped_at} "
            f"from page {start_page} (instead of starting over)."
        )
    else:
        scraped_at = datetime.now(timezone.utc).isoformat()
        start_page = 1
        print(f"No checkpoint found, starting a new snapshot: {scraped_at}")

    if max_runtime_seconds:
        print(f"Time budget: {max_runtime_seconds / 60:.0f} minutes")

    print("Warming up session...")
    warm_up(client, cfg, page_number=1)

    def fetch_page_fn(page_number: int, size: int) -> dict:
        # fetch_tenders_page already retries on 429 (60s+ backoff) and
        # raises for other error statuses before returning.
        resp = fetch_tenders_page(client, cfg, page_number=page_number, page_size=size)
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
        print(f"  page {page_number}: +{inserted} rows (reported totalCount={total_count})")

    print("Starting collection...")
    records, total_count, reached_end = collect_all_pages(
        fetch_page_fn,
        page_size=page_size,
        start_page=start_page,
        delay_fn=polite_delay,
        on_page=on_page,
        deadline=deadline,
    )

    if reached_end:
        # Actually reached an empty page, i.e. the full listing is done -
        # safe to drop the checkpoint so the next run starts a fresh
        # snapshot from page 1.
        clear_checkpoint(checkpoint_path)
        print(f"Done. Collected {len(records)} tenders this run (last reported totalCount={total_count})")
    else:
        print(
            f"Time budget reached (or max_pages safety cap) after collecting "
            f"{len(records)} tenders this run. Checkpoint saved - rerun to continue "
            f"this snapshot (last reported totalCount={total_count})."
        )

    conn.close()
    print(f"Saved to: {cfg['storage']['sqlite_path']} (scraped_at={scraped_at})")


if __name__ == "__main__":
    main()
