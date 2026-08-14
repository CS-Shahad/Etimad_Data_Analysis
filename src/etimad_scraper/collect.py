"""Pagination logic for fully collecting a listing endpoint.

Kept independent of httpx/network I/O (fetch_page_fn is injected) so the
termination logic — the part actually worth getting right, since a bug
here means either an infinite loop against a government server or a
silently incomplete dataset — can be unit tested without a live connection.
"""

from typing import Callable, Optional


def collect_all_pages(
    fetch_page_fn: Callable[[int, int], dict],
    page_size: int,
    start_page: int = 1,
    max_pages: int = 5000,
    delay_fn: Optional[Callable[[], None]] = None,
    on_page: Optional[Callable[[int, list, Optional[int]], None]] = None,
) -> tuple[list, Optional[int]]:
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

    Returns (records_collected_this_call, latest_total_count_seen).
    """
    collected: list = []
    total_count: Optional[int] = None

    for page_number in range(start_page, start_page + max_pages):
        payload = fetch_page_fn(page_number, page_size)
        data = payload.get("data", [])
        total_count = payload.get("totalCount", total_count)

        if not data:
            break

        if on_page:
            on_page(page_number, data, total_count)
        collected.extend(data)

        if delay_fn:
            delay_fn()

    return collected, total_count
