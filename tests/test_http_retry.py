import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from etimad_scraper.http_retry import get_with_retry


class FakeResponse:
    def __init__(self, status_code: int, headers: dict = None):
        self.status_code = status_code
        self.headers = headers or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def test_returns_immediately_on_success():
    calls = []

    def get_fn():
        calls.append(1)
        return FakeResponse(200)

    resp = get_with_retry(get_fn)

    assert resp.status_code == 200
    assert len(calls) == 1


def test_retries_on_429_then_succeeds():
    responses = [FakeResponse(429), FakeResponse(429), FakeResponse(200)]
    sleeps = []

    def get_fn():
        return responses.pop(0)

    resp = get_with_retry(get_fn, sleep_fn=lambda s: sleeps.append(s))

    assert resp.status_code == 200
    assert len(sleeps) == 2


def test_honors_retry_after_header_over_backoff():
    responses = [FakeResponse(429, headers={"Retry-After": "12"}), FakeResponse(200)]
    sleeps = []

    def get_fn():
        return responses.pop(0)

    get_with_retry(get_fn, sleep_fn=lambda s: sleeps.append(s))

    assert sleeps == [12.0]


def test_backoff_grows_and_is_capped_when_no_retry_after_header():
    # Always 429, no Retry-After -> exponential backoff capped at max_backoff_seconds.
    def get_fn():
        return FakeResponse(429)

    sleeps = []
    with pytest.raises(RuntimeError, match="Gave up after"):
        get_with_retry(
            get_fn,
            max_retries=5,
            default_backoff_seconds=1.0,
            max_backoff_seconds=4.0,
            sleep_fn=lambda s: sleeps.append(s),
        )

    assert sleeps == [1.0, 2.0, 4.0, 4.0, 4.0]


def test_non_429_error_status_raises_immediately_without_retry():
    calls = []

    def get_fn():
        calls.append(1)
        return FakeResponse(403)

    with pytest.raises(RuntimeError, match="HTTP 403"):
        get_with_retry(get_fn)

    assert len(calls) == 1
