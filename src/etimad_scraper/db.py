import sqlite3
from pathlib import Path

from .config import PROJECT_ROOT

SCHEMA = """
CREATE TABLE IF NOT EXISTS current_tenders (
    tender_id INTEGER NOT NULL,
    scraped_at TEXT NOT NULL,
    tender_id_string TEXT,
    reference_number TEXT,
    tender_number TEXT,
    tender_name TEXT,
    agency_name TEXT,
    branch_name TEXT,
    tender_status_id INTEGER,
    tender_type_id INTEGER,
    tender_type_name TEXT,
    tender_activity_id INTEGER,
    tender_activity_name TEXT,
    condetional_booklet_price REAL,
    financial_fees REAL,
    invitation_cost REAL,
    buying_cost REAL,
    has_invitations INTEGER,
    last_enquiries_date TEXT,
    last_offer_presentation_date TEXT,
    offers_opening_date TEXT,
    submition_date TEXT,
    is_ugrp INTEGER,
    PRIMARY KEY (tender_id, scraped_at)
);

CREATE INDEX IF NOT EXISTS idx_current_tenders_tender_id
    ON current_tenders (tender_id);

CREATE INDEX IF NOT EXISTS idx_current_tenders_deadline
    ON current_tenders (last_offer_presentation_date);
"""

# Maps our SQLite columns to the raw field names returned by
# AllSupplierTendersForVisitorAsync. Kept explicit (rather than passing the
# API payload through as-is) so an upstream field rename or a noisy field we
# don't want (e.g. the live remainingDays/currentDateTime countdown values)
# doesn't silently change our schema.
FIELD_MAP = {
    "tender_id": "tenderId",
    "tender_id_string": "tenderIdString",
    "reference_number": "referenceNumber",
    "tender_number": "tenderNumber",
    "tender_name": "tenderName",
    "agency_name": "agencyName",
    "branch_name": "branchName",
    "tender_status_id": "tenderStatusId",
    "tender_type_id": "tenderTypeId",
    "tender_type_name": "tenderTypeName",
    "tender_activity_id": "tenderActivityId",
    "tender_activity_name": "tenderActivityName",
    "condetional_booklet_price": "condetionalBookletPrice",
    "financial_fees": "financialFees",
    "invitation_cost": "invitationCost",
    "buying_cost": "buyingCost",
    "has_invitations": "hasInvitations",
    "last_enquiries_date": "lastEnqueriesDate",
    "last_offer_presentation_date": "lastOfferPresentationDate",
    "offers_opening_date": "offersOpeningDate",
    "submition_date": "submitionDate",
    "is_ugrp": "isUGRP",
}


def get_connection(db_path: str | Path | None = None) -> sqlite3.Connection:
    path = Path(db_path) if db_path else PROJECT_ROOT / "data" / "raw" / "etimad.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    return conn


def insert_tenders(conn: sqlite3.Connection, records: list[dict], scraped_at: str) -> int:
    columns = list(FIELD_MAP.keys())
    placeholders = ", ".join(["?"] * (len(columns) + 1))
    sql = (
        f"INSERT OR REPLACE INTO current_tenders "
        f"(tender_id, scraped_at, {', '.join(columns[1:])}) VALUES ({placeholders})"
    )

    rows = []
    for record in records:
        row = [record.get(FIELD_MAP["tender_id"])]
        row.append(scraped_at)
        for col in columns[1:]:
            value = record.get(FIELD_MAP[col])
            if isinstance(value, bool):
                value = int(value)
            row.append(value)
        rows.append(row)

    conn.executemany(sql, rows)
    conn.commit()
    return len(rows)


# Same tender_id can appear under several scraped_at snapshots (the table is
# an append-only history), so "ended" needs the *latest* snapshot per tender,
# not just any row past its deadline.
_ENDED_TENDERS_SQL = """
SELECT t.*
FROM current_tenders t
INNER JOIN (
    SELECT tender_id, MAX(scraped_at) AS latest_scraped_at
    FROM current_tenders
    GROUP BY tender_id
) latest
    ON t.tender_id = latest.tender_id
   AND t.scraped_at = latest.latest_scraped_at
WHERE t.last_offer_presentation_date IS NOT NULL
  AND t.last_offer_presentation_date < ?
ORDER BY t.last_offer_presentation_date DESC
"""


def get_ended_tenders(conn: sqlite3.Connection, now_iso: str) -> list[dict]:
    """Latest-snapshot tenders whose submission deadline is before now_iso.

    now_iso is injected rather than read from the wall clock here so this
    stays testable with a fixed value. Note: Etimad's lastOfferPresentationDate
    strings carry no timezone (observed as Saudi local time, UTC+3) while
    scraped_at is UTC - a plain string comparison against a UTC "now" can
    misclassify tenders that ended within the last ~3 hours as still open.
    Fine for finding the bulk of already-closed tenders; not exact at the edge.
    """
    cur = conn.execute(_ENDED_TENDERS_SQL, (now_iso,))
    columns = [d[0] for d in cur.description]
    return [dict(zip(columns, row)) for row in cur.fetchall()]
