import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from etimad_scraper.date_partitions import year_partitions


def test_year_partitions_covers_each_year_inclusive():
    partitions = year_partitions(2019, 2021)

    assert partitions == [
        ("2019", "01/01/2019", "31/12/2019"),
        ("2020", "01/01/2020", "31/12/2020"),
        ("2021", "01/01/2021", "31/12/2021"),
    ]


def test_year_partitions_single_year():
    assert year_partitions(2026, 2026) == [("2026", "01/01/2026", "31/12/2026")]


def test_year_partitions_defaults_end_year_to_current_year(monkeypatch):
    import etimad_scraper.date_partitions as mod
    from datetime import datetime, timezone

    class FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 6, 15, tzinfo=timezone.utc)

    monkeypatch.setattr(mod, "datetime", FixedDatetime)

    partitions = year_partitions(2024)

    assert [p[0] for p in partitions] == ["2024", "2025", "2026"]
