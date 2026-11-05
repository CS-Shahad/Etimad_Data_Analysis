"""Splits the full tender archive into yearly date-range windows.

Needed because plain pagination (any sort direction) hits a server-side
depth wall well short of the ~291,000-tender archive (confirmed
2026-11-04/05): DESC is cheap but still eventually limited, and ASC is
unexpectedly far more limited (walled out at ~4,500 records - an
inefficient query plan for that sort direction, going by the evidence).
A single year's totalCount (15,653 for 2020, confirmed 2026-11-05)
is comfortably under that wall, so collecting year by year - each
comfortably completing in one pass - replaces relying on either sort
direction reaching deep enough on its own.
"""

from datetime import datetime, timezone
from typing import List, Tuple


def year_partitions(start_year: int, end_year: int = None) -> List[Tuple[str, str, str]]:
    """Returns [(key, from_date, to_date), ...], one per calendar year from
    start_year through end_year (inclusive; defaults to the current UTC
    year). Dates are DD/MM/YYYY - confirmed 2026-11-05 as the format the
    site's own FromLastOfferPresentationDateString/
    ToLastOfferPresentationDateString filter expects.
    """
    if end_year is None:
        end_year = datetime.now(timezone.utc).year

    return [
        (str(year), f"01/01/{year}", f"31/12/{year}")
        for year in range(start_year, end_year + 1)
    ]
