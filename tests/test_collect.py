import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from etimad_scraper.collect import collect_all_pages


def make_record(tender_id: int) -> dict:
    return {"tenderId": tender_id}


def test_stops_when_running_total_reaches_reported_total_count():
    # Mirrors the real endpoint: PageSize is requested as 100 but the
    # server only ever returns up to 24 rows per page.
    total_count = 50
    pages = {
        1: [make_record(i) for i in range(1, 25)],   # 24 rows
        2: [make_record(i) for i in range(25, 49)],  # 24 rows -> 48 so far
        3: [make_record(i) for i in range(49, 51)],  # 2 rows -> 50, done
    }
    calls = []

    def fake_fetch(page_number, page_size):
        calls.append((page_number, page_size))
        return {"data": pages.get(page_number, []), "totalCount": total_count}

    records, reported_total = collect_all_pages(fake_fetch, page_size=100)

    assert reported_total == 50
    assert len(records) == 50
    assert [r["tenderId"] for r in records] == list(range(1, 51))
    # must not have requested a 4th page once the total was reached
    assert calls == [(1, 100), (2, 100), (3, 100)]


def test_stops_on_empty_page_even_if_below_reported_total_count():
    # totalCount can drift while paginating since the dataset is live; an
    # empty page must stop the loop rather than spin until max_pages.
    def fake_fetch(page_number, page_size):
        if page_number == 1:
            return {"data": [make_record(1)], "totalCount": 999}
        return {"data": [], "totalCount": 999}

    records, reported_total = collect_all_pages(fake_fetch, page_size=100)

    assert len(records) == 1
    assert reported_total == 999


def test_respects_max_pages_safety_cap():
    def fake_fetch(page_number, page_size):
        # never signals completion or an empty page -> would loop forever
        # without the safety cap
        return {"data": [make_record(page_number)], "totalCount": 10_000}

    records, _ = collect_all_pages(fake_fetch, page_size=100, max_pages=5)

    assert len(records) == 5


def test_delay_fn_called_between_pages_but_not_after_the_last_one():
    def fake_fetch(page_number, page_size):
        data = [make_record(page_number)] if page_number <= 3 else []
        return {"data": data, "totalCount": 3}

    delay_calls = []
    collect_all_pages(fake_fetch, page_size=100, delay_fn=lambda: delay_calls.append(1))

    assert len(delay_calls) == 2


def test_on_page_callback_receives_each_page_before_it_stops():
    def fake_fetch(page_number, page_size):
        data = [make_record(page_number)] if page_number <= 2 else []
        return {"data": data, "totalCount": 2}

    seen = []
    collect_all_pages(fake_fetch, page_size=100, on_page=lambda pn, data, tc: seen.append(pn))

    assert seen == [1, 2]
