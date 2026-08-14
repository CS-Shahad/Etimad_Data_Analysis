"""Retry-with-backoff for rate-limited HTTP calls.

Kept independent of httpx (get_fn/sleep_fn are injected) so the backoff
decision logic can be unit tested without real network calls or real
sleeps — the thing worth verifying here is that a 429 pauses and retries
instead of crashing a multi-minute collection run, and that it eventually
gives up rather than looping forever against a server stuck at 429.
"""

import time
from typing import Callable, Protocol


class RetryableResponse(Protocol):
    status_code: int
    headers: dict

    def raise_for_status(self) -> None: ...


def get_with_retry(
    get_fn: Callable[[], RetryableResponse],
    max_retries: int = 6,
    default_backoff_seconds: float = 5.0,
    max_backoff_seconds: float = 90.0,
    sleep_fn: Callable[[float], None] = time.sleep,
    on_retry: Callable[[int, float], None] = None,
) -> RetryableResponse:
    """Calls get_fn() and, on HTTP 429, waits (honoring a Retry-After
    header when present, otherwise exponential backoff) and retries, up to
    max_retries times. Any other status is handled by the caller via
    raise_for_status() as usual.
    """
    for attempt in range(max_retries):
        resp = get_fn()

        if resp.status_code != 429:
            resp.raise_for_status()
            return resp

        retry_after = resp.headers.get("Retry-After")
        if retry_after is not None:
            wait_seconds = float(retry_after)
        else:
            wait_seconds = min(max_backoff_seconds, default_backoff_seconds * (2**attempt))

        if on_retry:
            on_retry(attempt + 1, wait_seconds)
        sleep_fn(wait_seconds)

    raise RuntimeError(f"Gave up after {max_retries} retries due to repeated 429 responses")
