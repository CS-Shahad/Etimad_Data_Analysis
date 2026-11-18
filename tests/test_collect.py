import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from etimad_scraper.collect import collect_all_pages


def make_record(tender_id: int) -> dict:
    return {"tenderId": tender_id}


def test_stops_once_an_empty_page_is_confirmed_by_retries():
    # Mirrors the real endpoint: PageSize is requested as 100 but the
    # server only ever returns up to 24 rows per page. Page 3 stays empty
    # across the default retries too, so it's genuinely the end.
    pages = {
        1: [make_record(i) for i in range(1, 25)],   # 24 rows
        2: [make_record(i) for i in range(25, 49)],  # 24 rows
        3: [],                                       # confirmed done
    }
    calls = []

    def fake_fetch(page_number, page_size):
        calls.append((page_number, page_size))
        return {"data": pages.get(page_number, []), "totalCount": 48}

    records, reported_total, reached_end, stalled = collect_all_pages(fake_fetch, page_size=100)

    assert reported_total == 48
    assert len(records) == 48
    assert [r["tenderId"] for r in records] == list(range(1, 49))
    # page 3 is fetched 3 times total (the empty_page_retries=2 default)
    # before being trusted as the real end.
    assert calls == [(1, 100), (2, 100), (3, 100), (3, 100), (3, 100)]
    assert reached_end is True
    assert stalled is False


def test_a_single_transient_empty_page_does_not_end_the_run_early():
    # Confirmed 2026-11-18: the 2022-2025 date partitions each got marked
    # "done" at just 16-90% of their real totalCount after a single empty
    # page - almost certainly one transient hiccup, not true completion.
    # Page 2's real data only shows up from its second fetch onward,
    # simulating that one-off glitch; it must not be discarded.
    page_2_calls = {"n": 0}

    def fake_fetch(page_number, page_size):
        if page_number == 1:
            return {"data": [make_record(1)], "totalCount": 3}
        if page_number == 2:
            page_2_calls["n"] += 1
            if page_2_calls["n"] == 1:
                return {"data": [], "totalCount": 3}  # transient glitch
            return {"data": [make_record(2)], "totalCount": 3}
        if page_number == 3:
            return {"data": [make_record(3)], "totalCount": 3}
        return {"data": [], "totalCount": 3}  # page 4+: confirmed done

    records, _, reached_end, stalled = collect_all_pages(fake_fetch, page_size=100)

    assert [r["tenderId"] for r in records] == [1, 2, 3]
    assert reached_end is True
    assert stalled is False
    assert page_2_calls["n"] == 2


def test_empty_page_retries_is_configurable():
    calls = []

    def fake_fetch(page_number, page_size):
        calls.append(page_number)
        return {"data": [], "totalCount": None}

    collect_all_pages(fake_fetch, page_size=100, empty_page_retries=0)

    # no retries at all -> page 1 fetched exactly once before accepting "done"
    assert calls == [1]


def test_does_not_stop_early_just_because_running_total_reached_stale_total_count():
    # totalCount can drift on a live dataset (e.g. new tenders published
    # mid-run); it must never be used to cut the run short of an actual
    # empty page.
    def fake_fetch(page_number, page_size):
        if page_number <= 3:
            return {"data": [make_record(page_number)], "totalCount": 2}
        return {"data": [], "totalCount": 2}

    records, _, reached_end, _ = collect_all_pages(fake_fetch, page_size=100)

    assert len(records) == 3
    assert reached_end is True


def test_start_page_resumes_from_a_checkpoint_instead_of_page_one():
    calls = []

    def fake_fetch(page_number, page_size):
        calls.append(page_number)
        if page_number <= 5:
            return {"data": [make_record(page_number)], "totalCount": 5}
        return {"data": [], "totalCount": 5}

    records, _, _, _ = collect_all_pages(fake_fetch, page_size=100, start_page=4)

    # page 6 (empty) is retried twice (the default empty_page_retries)
    # before being trusted as the end.
    assert calls == [4, 5, 6, 6, 6]
    assert [r["tenderId"] for r in records] == [4, 5]


def test_respects_max_pages_safety_cap_relative_to_start_page():
    def fake_fetch(page_number, page_size):
        # never returns an empty page -> would loop forever without the cap
        # (totalCount is unknown here, so the stall guard never engages -
        # this is purely the max_pages cap)
        return {"data": [make_record(page_number)], "totalCount": None}

    records, _, reached_end, stalled = collect_all_pages(fake_fetch, page_size=100, start_page=10, max_pages=5)

    assert [r["tenderId"] for r in records] == [10, 11, 12, 13, 14]
    assert reached_end is False
    assert stalled is False


def test_stalls_once_pages_far_exceed_what_total_count_implies():
    # Mirrors the 2021 partition (confirmed 2026-11-18): totalCount settles
    # at 100, each page returns 10 rows (so ~10 pages should finish it),
    # but the server keeps returning non-empty data indefinitely - no
    # empty page ever comes back to end the loop on its own.
    def fake_fetch(page_number, page_size):
        return {"data": [make_record(page_number)] * 10, "totalCount": 100}

    records, total_count, reached_end, stalled = collect_all_pages(
        fake_fetch, page_size=100, max_pages=10_000
    )

    assert reached_end is False
    assert stalled is True
    assert total_count == 100
    # stopped after page 30 (expected_pages(10) * stall_multiplier(3)),
    # not after thousands of pages - 10 rows/page -> 300 records
    assert len(records) == 300


def test_does_not_stall_on_legitimate_progress_within_the_multiplier():
    # totalCount implies ~10 pages; finishing in 12 (within the 3x margin)
    # must not be flagged as stalled.
    def fake_fetch(page_number, page_size):
        if page_number <= 12:
            return {"data": [make_record(page_number)] * 10, "totalCount": 100}
        return {"data": [], "totalCount": 100}

    records, _, reached_end, stalled = collect_all_pages(fake_fetch, page_size=100)

    assert reached_end is True
    assert stalled is False
    assert len(records) == 120


def test_delay_fn_called_between_pages_but_not_after_the_last_one():
    def fake_fetch(page_number, page_size):
        data = [make_record(page_number)] if page_number <= 3 else []
        return {"data": data, "totalCount": 3}

    delay_calls = []
    # empty_page_retries=0 isolates this from the separate retry-delay
    # behavior (covered below) - here we only care that a successful page
    # is followed by a delay, and the empty page that ends the run isn't.
    collect_all_pages(
        fake_fetch, page_size=100, delay_fn=lambda: delay_calls.append(1), empty_page_retries=0
    )

    assert len(delay_calls) == 3


def test_delay_fn_also_called_before_each_empty_page_retry():
    def fake_fetch(page_number, page_size):
        return {"data": [], "totalCount": None}

    delay_calls = []
    collect_all_pages(
        fake_fetch, page_size=100, delay_fn=lambda: delay_calls.append(1), empty_page_retries=2
    )

    # a polite delay before each of the 2 retries, same as any other request
    assert len(delay_calls) == 2


def test_on_page_callback_receives_each_page_before_it_stops():
    def fake_fetch(page_number, page_size):
        data = [make_record(page_number)] if page_number <= 2 else []
        return {"data": data, "totalCount": 2}

    seen = []
    collect_all_pages(fake_fetch, page_size=100, on_page=lambda pn, data, tc: seen.append(pn))

    assert seen == [1, 2]


def test_stops_cleanly_once_deadline_reached_without_fetching_another_page():
    calls = []

    def fake_fetch(page_number, page_size):
        calls.append(page_number)
        return {"data": [make_record(page_number)], "totalCount": 10_000}

    # Fake clock: first call (the deadline check before page 1) is "before"
    # the deadline, every call after is "past" it.
    clock = iter([0.0, 10.0, 10.0, 10.0])

    records, _, reached_end, _ = collect_all_pages(
        fake_fetch, page_size=100, deadline=5.0, now_fn=lambda: next(clock)
    )

    assert calls == [1]
    assert len(records) == 1
    assert reached_end is False


def test_deadline_is_ignored_when_not_set():
    def fake_fetch(page_number, page_size):
        data = [make_record(page_number)] if page_number <= 2 else []
        return {"data": data, "totalCount": 2}

    records, _, reached_end, _ = collect_all_pages(fake_fetch, page_size=100, deadline=None)

    assert len(records) == 2
    assert reached_end is True
