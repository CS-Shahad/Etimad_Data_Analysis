"""
Full collection of all "current tenders" available via
AllSupplierTendersForVisitorAsync, stored as one timestamped snapshot per
sort direction in SQLite.

Based on confirmed PoC and production results:
- A plain httpx session (no browser) is enough to get past the F5 WAF
  cookies.
- The server actually caps rows per page (~24) regardless of the
  requested PageSize, so progress tracks the real length of "data", and
  completion is only signaled by an empty page (not totalCount, since
  that drifts on a live dataset).
- The server retries 429 and network timeouts/dropped connections
  transparently (fetch_tenders_page) instead of aborting the script.
- PublishDateId=1 ("any time") returns ~291,000 tenders. Plain offset
  pagination hard-fails (400) once (pageNumber-1)*PageSize passes
  ~185,000 - confirmed 2026-11-04 a true depth limit (independent of
  PageSize), and the server's default order isn't reliably chronological
  either, so that depth wasn't simply "the newest 185,000".
- Fix: collect twice, once per sort direction in
  current_tenders.collect_directions (Sort=SubmitionDate&SortDirection=
  ASC|DESC, found via the site's own sort UI). ASC starts at the
  archive's true beginning (2019-12-05), DESC starts "now" - each walks
  until it hits its own depth wall, and since 185,000+185,000 exceeds the
  ~291,000 total, the two together cover the full archive with overlap
  to spare. Each direction gets its own checkpoint (independent
  pagination) and its own share of any time budget, so a bounded run
  still makes progress on both instead of one direction starving the
  other.
- If a run is interrupted (repeated failures after retrying, a network
  drop, Ctrl+C, a time budget), it resumes from the last saved page per
  direction instead of starting over.

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
    checkpoint_path_for_direction,
    clear_checkpoint,
    load_checkpoint,
    save_checkpoint,
)
from etimad_scraper.collect import collect_all_pages
from etimad_scraper.config import load_config
from etimad_scraper.db import get_connection, insert_tenders
from etimad_scraper.runtime_budget import resolve_max_runtime_seconds
from etimad_scraper.session import build_session, fetch_tenders_page, warm_up


def collect_one_direction(cfg: dict, client, conn, direction: str, deadline) -> None:
    checkpoint_path = checkpoint_path_for_direction(cfg["storage"]["checkpoint_path"], direction)
    page_size = cfg["current_tenders"]["collect_page_size"]

    checkpoint = load_checkpoint(checkpoint_path)
    if checkpoint:
        scraped_at = checkpoint["scraped_at"]
        start_page = checkpoint["last_completed_page"] + 1
        print(
            f"[{direction}] Found existing checkpoint: resuming snapshot {scraped_at} "
            f"from page {start_page} (instead of starting over)."
        )
    else:
        scraped_at = datetime.now(timezone.utc).isoformat()
        start_page = 1
        print(f"[{direction}] No checkpoint found, starting a new snapshot: {scraped_at}")

    def fetch_page_fn(page_number: int, size: int) -> dict:
        resp = fetch_tenders_page(
            client, cfg, page_number=page_number, page_size=size,
            sort_direction=direction.upper(),
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
        print(f"  [{direction}] page {page_number}: +{inserted} rows (reported totalCount={total_count})")

    print(f"[{direction}] Starting collection...")
    records, total_count, reached_end = collect_all_pages(
        fetch_page_fn,
        page_size=page_size,
        start_page=start_page,
        delay_fn=polite_delay,
        on_page=on_page,
        deadline=deadline,
    )

    if reached_end:
        # Actually reached an empty page - this direction is fully done.
        # Safe to drop its checkpoint so the next run starts a fresh
        # snapshot in this direction from page 1.
        clear_checkpoint(checkpoint_path)
        print(f"[{direction}] Done. Collected {len(records)} tenders this run (last reported totalCount={total_count})")
    else:
        print(
            f"[{direction}] Time budget reached (or the depth wall / max_pages safety "
            f"cap) after collecting {len(records)} tenders this run. Checkpoint saved - "
            f"rerun to continue (last reported totalCount={total_count})."
        )


def main() -> None:
    cfg = load_config()
    client = build_session(cfg)
    conn = get_connection(cfg["storage"]["sqlite_path"])
    directions = cfg["current_tenders"]["collect_directions"]

    max_runtime_seconds = resolve_max_runtime_seconds(
        "COLLECT_MAX_MINUTES", cfg["current_tenders"].get("max_runtime_minutes")
    )
    per_direction_seconds = max_runtime_seconds / len(directions) if max_runtime_seconds else None
    if max_runtime_seconds:
        print(f"Time budget: {max_runtime_seconds / 60:.0f} minutes total, "
              f"{per_direction_seconds / 60:.0f} minutes per direction ({directions})")

    print("Warming up session...")
    warm_up(client, cfg, page_number=1)

    for direction in directions:
        deadline = time.monotonic() + per_direction_seconds if per_direction_seconds else None
        try:
            collect_one_direction(cfg, client, conn, direction, deadline)
        except httpx.HTTPStatusError as e:
            # A non-429 error status (e.g. the ~185,000-offset depth wall,
            # confirmed 2026-11-04) isn't retryable - fetch_tenders_page
            # already handles 429s and network timeouts transparently, so
            # anything surfacing here is a real stop for this direction.
            # Don't let it skip the other direction's turn (or, run inside
            # a GitHub Action, make the whole job look like a crash every
            # single run from here on if this direction's wall never
            # moves - the checkpoint still points right at it, so a rerun
            # would hit the exact same failure immediately).
            print(f"[{direction}] Stopped by a non-retryable HTTP error (likely the pagination depth limit): {e}")

    conn.close()
    print(f"Saved to: {cfg['storage']['sqlite_path']}")


if __name__ == "__main__":
    main()
