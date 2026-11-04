"""Retry-with-backoff for rate-limited and transiently-failing HTTP calls.

Kept independent of httpx (get_fn/sleep_fn are injected, and the caller
supplies which exception types count as "transient") so the backoff
decision logic can be unit tested without real network calls or real
sleeps — the thing worth verifying here is that a 429 or a dropped
connection pauses and retries instead of crashing a multi-hour collection
run, and that it eventually gives up rather than looping forever.
"""

import time
from typing import Callable, Optional, Protocol, Tuple, Type


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
    on_retry: Optional[Callable[[int, float, str], None]] = None,
    transient_exceptions: Tuple[Type[BaseException], ...] = (),
) -> RetryableResponse:
    """Calls get_fn() and retries, with backoff, on either:
    - HTTP 429 (honors a Retry-After header when present, otherwise
      exponential backoff), or
    - get_fn() raising one of transient_exceptions - e.g. httpx.TransportError
      for a real network timeout/dropped connection. Observed in production
      (2026-11-03/04): every single run of a multi-hour collection job
      crashed on an unhandled httpx.ReadTimeout around page 650-700,
      because nothing previously caught anything but a 429 response; a
      network-level exception isn't a response at all, so it skipped the
      status-code check entirely and propagated straight up.

    Any other status is handled by the caller via raise_for_status() as
    usual; any exception type not in transient_exceptions propagates
    immediately rather than being retried.
    """
    for attempt in range(max_retries):
        try:
            resp = get_fn()
        except transient_exceptions as e:
            wait_seconds = min(max_backoff_seconds, default_backoff_seconds * (2**attempt))
            if on_retry:
                on_retry(attempt + 1, wait_seconds, str(e))
            sleep_fn(wait_seconds)
            continue

        if resp.status_code != 429:
            resp.raise_for_status()
            return resp

        retry_after = resp.headers.get("Retry-After")
        if retry_after is not None:
            wait_seconds = float(retry_after)
        else:
            wait_seconds = min(max_backoff_seconds, default_backoff_seconds * (2**attempt))

        if on_retry:
            on_retry(attempt + 1, wait_seconds, "429")
        sleep_fn(wait_seconds)

    raise RuntimeError(
        f"Gave up after {max_retries} retries due to repeated 429 responses or transient errors"
    )
