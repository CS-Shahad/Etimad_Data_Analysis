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
    max_pages: int = 5000,
    delay_fn: Optional[Callable[[], None]] = None,
    on_page: Optional[Callable[[int, list, Optional[int]], None]] = None,
) -> tuple[list, Optional[int]]:
    """Pages through fetch_page_fn(page_number, page_size) until either a
    page comes back empty or the running total reaches the server-reported
    totalCount (read from the first response). Does not assume the server
    honors the requested page_size — it only trusts the actual length of
    each page's "data" list, since Etimad's endpoint echoes back whatever
    PageSize was requested without necessarily returning that many rows.

    Returns (all_records, total_count_reported_by_server).
    """
    collected: list = []
    total_count: Optional[int] = None

    for page_number in range(1, max_pages + 1):
        payload = fetch_page_fn(page_number, page_size)
        data = payload.get("data", [])

        if total_count is None:
            total_count = payload.get("totalCount")

        if not data:
            break

        if on_page:
            on_page(page_number, data, total_count)
        collected.extend(data)

        if total_count is not None and len(collected) >= total_count:
            break

        if delay_fn:
            delay_fn()

    return collected, total_count
