"""Pagination logic for fully collecting a listing endpoint.

Kept independent of httpx/network I/O (fetch_page_fn is injected) so the
termination logic — the part actually worth getting right, since a bug
here means either an infinite loop against a government server or a
silently incomplete dataset — can be unit tested without a live connection.
"""

import time
from typing import Callable, Optional


def collect_all_pages(
    fetch_page_fn: Callable[[int, int], dict],
    page_size: int,
    start_page: int = 1,
    max_pages: int = 5000,
    delay_fn: Optional[Callable[[], None]] = None,
    on_page: Optional[Callable[[int, list, Optional[int]], None]] = None,
    deadline: Optional[float] = None,
    now_fn: Callable[[], float] = time.monotonic,
) -> tuple[list, Optional[int], bool]:
    """Pages through fetch_page_fn(page_number, page_size) starting at
    start_page (so an interrupted run can resume mid-way) until a page
    comes back empty. Does not stop early based on the server-reported
    totalCount, since that count drifts on a live dataset and a resumed
    run's local "collected" tally would no longer reflect the true
    cumulative progress anyway — an empty page is the only signal trusted
    as "done". totalCount is still returned (the latest value seen) purely
    for progress reporting.

    Does not assume the server honors the requested page_size either — it
    only trusts the actual length of each page's "data" list, since
    Etimad's endpoint echoes back whatever PageSize was requested without
    necessarily returning that many rows.

    deadline (in now_fn() units, e.g. time.monotonic()) stops the loop
    before starting a new page once reached, instead of mid-request - a
    scheduled job bounded well under GitHub's 6-hour cap can exit cleanly
    and resume next run via its checkpoint rather than getting killed.

    Returns (records_collected_this_call, latest_total_count_seen,
    reached_end) - reached_end is only True if the loop actually stopped
    because of an empty page (true completion), not the deadline or
    max_pages safety cap, so the caller knows whether it's safe to clear
    its checkpoint.
    """
    collected: list = []
    total_count: Optional[int] = None
    reached_end = False

    for page_number in range(start_page, start_page + max_pages):
        if deadline is not None and now_fn() >= deadline:
            break

        payload = fetch_page_fn(page_number, page_size)
        data = payload.get("data", [])
        total_count = payload.get("totalCount", total_count)

        if not data:
            reached_end = True
            break

        if on_page:
            on_page(page_number, data, total_count)
        collected.extend(data)

        if delay_fn:
            delay_fn()

    return collected, total_count, reached_end
