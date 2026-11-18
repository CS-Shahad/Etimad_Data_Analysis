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
    stall_multiplier: float = 3.0,
    empty_page_retries: int = 2,
) -> tuple[list, Optional[int], bool, bool]:
    """Pages through fetch_page_fn(page_number, page_size) starting at
    start_page (so an interrupted run can resume mid-way) until a page
    comes back empty - confirmed empty, that is: a lone empty page is
    retried up to empty_page_retries times (confirmed 2026-11-18: trusting
    a single empty page outright had let the 2022-2025 partitions each get
    marked "done" at just 16-90% of their real totalCount, apparently from
    one transient empty response each rather than true completion) before
    being accepted as the end. Does not stop early based on the
    server-reported totalCount, since that count drifts on a live dataset
    and a resumed run's local "collected" tally would no longer reflect
    the true cumulative progress anyway — a confirmed-empty page is the
    only signal trusted as "done". totalCount is still returned (the
    latest value seen) purely for progress reporting.

    Does not assume the server honors the requested page_size either — it
    only trusts the actual length of each page's "data" list, since
    Etimad's endpoint echoes back whatever PageSize was requested without
    necessarily returning that many rows.

    deadline (in now_fn() units, e.g. time.monotonic()) stops the loop
    before starting a new page once reached, instead of mid-request - a
    scheduled job bounded well under GitHub's 6-hour cap can exit cleanly
    and resume next run via its checkpoint rather than getting killed.

    stall_multiplier guards against a page number that never runs out of
    non-empty data to return - confirmed 2026-11-18: the 2021 date
    partition reached page 11,451 (checkpoint carried across a week of
    resumed runs) while only 42,242 of its ~50,001 tenders were actually
    distinct, meaning most of those pages were re-serving data already
    seen rather than making progress - with no empty page ever coming
    back to signal "done", every run spent its entire shared time budget
    here without ever finishing. Once the server has reported a
    totalCount, expected_pages is estimated from it and the size of the
    first page actually seen (not the requested page_size, since the
    server doesn't honor that) - if page_number passes
    expected_pages * stall_multiplier, the loop stops as stalled rather
    than continuing indefinitely, even though more (very likely
    duplicate) data is still coming back.

    Returns (records_collected_this_call, latest_total_count_seen,
    reached_end, stalled). reached_end is only True if the loop actually
    stopped because of an empty page (true completion), not the deadline,
    max_pages safety cap, or a stall, so the caller knows whether it's
    safe to clear its checkpoint. stalled is only True if the
    stall_multiplier guard is what stopped the loop, so the caller can
    flag the partition as needing investigation instead of silently
    retrying the same trap next run.
    """
    collected: list = []
    total_count: Optional[int] = None
    reached_end = False
    stalled = False
    first_page_len: Optional[int] = None

    for page_number in range(start_page, start_page + max_pages):
        if deadline is not None and now_fn() >= deadline:
            break

        payload = fetch_page_fn(page_number, page_size)
        data = payload.get("data", [])
        total_count = payload.get("totalCount", total_count)

        if not data:
            for _ in range(empty_page_retries):
                if delay_fn:
                    delay_fn()
                payload = fetch_page_fn(page_number, page_size)
                data = payload.get("data", [])
                total_count = payload.get("totalCount", total_count)
                if data:
                    break
            if not data:
                reached_end = True
                break

        if first_page_len is None:
            first_page_len = len(data)

        if total_count:
            expected_pages = -(-total_count // first_page_len)  # ceil
            if page_number > expected_pages * stall_multiplier:
                stalled = True
                break

        if on_page:
            on_page(page_number, data, total_count)
        collected.extend(data)

        if delay_fn:
            delay_fn()

    return collected, total_count, reached_end, stalled
