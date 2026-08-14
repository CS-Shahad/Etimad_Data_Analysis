import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from etimad_scraper.collect import collect_all_pages


def make_record(tender_id: int) -> dict:
    return {"tenderId": tender_id}


def test_stops_on_first_empty_page():
    # Mirrors the real endpoint: PageSize is requested as 100 but the
    # server only ever returns up to 24 rows per page.
    pages = {
        1: [make_record(i) for i in range(1, 25)],   # 24 rows
        2: [make_record(i) for i in range(25, 49)],  # 24 rows
        3: [],                                       # done
    }
    calls = []

    def fake_fetch(page_number, page_size):
        calls.append((page_number, page_size))
        return {"data": pages.get(page_number, []), "totalCount": 48}

    records, reported_total = collect_all_pages(fake_fetch, page_size=100)

    assert reported_total == 48
    assert len(records) == 48
    assert [r["tenderId"] for r in records] == list(range(1, 49))
    assert calls == [(1, 100), (2, 100), (3, 100)]


def test_does_not_stop_early_just_because_running_total_reached_stale_total_count():
    # totalCount can drift on a live dataset (e.g. new tenders published
    # mid-run); it must never be used to cut the run short of an actual
    # empty page.
    def fake_fetch(page_number, page_size):
        if page_number <= 3:
            return {"data": [make_record(page_number)], "totalCount": 2}
        return {"data": [], "totalCount": 2}

    records, _ = collect_all_pages(fake_fetch, page_size=100)

    assert len(records) == 3


def test_start_page_resumes_from_a_checkpoint_instead_of_page_one():
    calls = []

    def fake_fetch(page_number, page_size):
        calls.append(page_number)
        if page_number <= 5:
            return {"data": [make_record(page_number)], "totalCount": 5}
        return {"data": [], "totalCount": 5}

    records, _ = collect_all_pages(fake_fetch, page_size=100, start_page=4)

    assert calls == [4, 5, 6]
    assert [r["tenderId"] for r in records] == [4, 5]


def test_respects_max_pages_safety_cap_relative_to_start_page():
    def fake_fetch(page_number, page_size):
        # never returns an empty page -> would loop forever without the cap
        return {"data": [make_record(page_number)], "totalCount": 10_000}

    records, _ = collect_all_pages(fake_fetch, page_size=100, start_page=10, max_pages=5)

    assert [r["tenderId"] for r in records] == [10, 11, 12, 13, 14]


def test_delay_fn_called_between_pages_but_not_after_the_last_one():
    def fake_fetch(page_number, page_size):
        data = [make_record(page_number)] if page_number <= 3 else []
        return {"data": data, "totalCount": 3}

    delay_calls = []
    collect_all_pages(fake_fetch, page_size=100, delay_fn=lambda: delay_calls.append(1))

    assert len(delay_calls) == 3


def test_on_page_callback_receives_each_page_before_it_stops():
    def fake_fetch(page_number, page_size):
        data = [make_record(page_number)] if page_number <= 2 else []
        return {"data": data, "totalCount": 2}

    seen = []
    collect_all_pages(fake_fetch, page_size=100, on_page=lambda pn, data, tc: seen.append(pn))

    assert seen == [1, 2]
