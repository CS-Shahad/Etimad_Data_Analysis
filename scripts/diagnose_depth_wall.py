"""
Diagnoses the NEW, much shallower 400 wall that hit every single year
partition on 2026-11-05 (run 42111306656, job 127539271833), each after
just 9-41 pages - far short of the ~1850-page (offset ~185,000) wall
previously confirmed for the unfiltered query. Year-partitioning the
archive by date did not avoid a depth wall after all; the date-filtered
query apparently has its own, much shallower one.

Read-only against the live site - does not touch the production
checkpoints or data/raw/etimad.db, so it's safe to run any time without
disturbing collection progress.

For each test partition, in order:
  A) Re-confirm the last page known to have succeeded there still works,
     with the same (already-used-for-other-partitions) session - a
     sanity check that the session itself isn't just globally broken.
  B) Reproduce the known failure twice, capturing the full response body
     (not just the status code) - to see whether it's a WAF block page
     or an application-level error, and whether it's deterministic.
  C) Retry the exact same failing page with a BRAND NEW session (fresh
     WAF cookies) - tests whether session "staleness" explains it, or a
     fresh session hits the identical wall.
  D) If C succeeds, probes a handful of further pages with that fresh
     session to find where its own wall falls.
Finally, a control: the original (by-then well-used) session re-requests
a known-deep page of the UNFILTERED query, to confirm the old, much
deeper wall is unaffected - isolating whether this is specific to the
date-filtered query shape or a general site-wide change.

Usage:
    python scripts/diagnose_depth_wall.py
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import httpx

from etimad_scraper.config import load_config
from etimad_scraper.session import build_session, fetch_tenders_page, warm_up

# (partition_key, from_date, to_date, first_page_that_failed, last_page_known_good)
# taken directly from run 42111306656's log.
TEST_CASES = [
    ("2021", "01/01/2021", "31/12/2021", 10, 9),
    ("2024", "01/01/2024", "31/12/2024", 42, 41),
    ("2022", "01/01/2022", "31/12/2022", 19, 18),
]

PAGE_SIZE = 100
# Last page confirmed (2026-11-04) to still succeed on the unfiltered
# DESC query, just under its ~185,000-offset wall.
UNFILTERED_CONTROL_PAGE = 1849
EXTRA_PROBE_PAGES = 15
DELAY_SECONDS = 3.0


def describe(resp: httpx.Response) -> str:
    body = resp.text[:500].replace("\n", " ")
    return f"status={resp.status_code} len={len(resp.content)} body[:500]={body!r}"


def try_fetch(client, cfg, page, from_date=None, to_date=None, sort_direction="DESC"):
    try:
        resp = fetch_tenders_page(
            client, cfg, page_number=page, page_size=PAGE_SIZE,
            sort_direction=sort_direction, from_date=from_date, to_date=to_date,
        )
        return True, describe(resp)
    except httpx.HTTPStatusError as e:
        return False, describe(e.response)
    except httpx.HTTPError as e:
        return False, f"network error: {e}"


def polite():
    time.sleep(DELAY_SECONDS)


def main():
    cfg = load_config()

    print("=== Building primary (shared, increasingly 'used') session ===")
    client = build_session(cfg)
    warm_up(client, cfg, page_number=1)

    for key, from_date, to_date, fail_page, good_page in TEST_CASES:
        print(f"\n=== [{key}] ===")

        print(f"[{key}] A: re-confirm last known-good page {good_page} with the shared session")
        ok, info = try_fetch(client, cfg, good_page, from_date, to_date)
        print(f"[{key}]    -> ok={ok} {info}")
        polite()

        print(f"[{key}] B: reproduce the failure at page {fail_page} with the shared session (x2)")
        for attempt in (1, 2):
            ok, info = try_fetch(client, cfg, fail_page, from_date, to_date)
            print(f"[{key}]    attempt {attempt} -> ok={ok} {info}")
            polite()

        print(f"[{key}] C: same page {fail_page}, but with a BRAND NEW session")
        fresh_client = build_session(cfg)
        warm_up(fresh_client, cfg, page_number=1)
        ok, info = try_fetch(fresh_client, cfg, fail_page, from_date, to_date)
        print(f"[{key}]    -> ok={ok} {info}")
        polite()

        if ok:
            print(f"[{key}] D: fresh session got past it - probing further pages")
            page = fail_page + 1
            limit = fail_page + EXTRA_PROBE_PAGES
            while page <= limit:
                ok, info = try_fetch(fresh_client, cfg, page, from_date, to_date)
                print(f"[{key}]    page {page} -> ok={ok} {info}")
                if not ok:
                    print(f"[{key}]    fresh session's own wall: page {page}")
                    break
                page += 1
                polite()
            else:
                print(f"[{key}]    no wall found within {EXTRA_PROBE_PAGES} extra pages")
        fresh_client.close()

    print("\n=== Control: unfiltered query, deep page, shared ('used') session ===")
    for page in (UNFILTERED_CONTROL_PAGE, UNFILTERED_CONTROL_PAGE + 1):
        ok, info = try_fetch(client, cfg, page, from_date=None, to_date=None)
        print(f"[control]    page {page} -> ok={ok} {info}")
        polite()

    client.close()


if __name__ == "__main__":
    main()
