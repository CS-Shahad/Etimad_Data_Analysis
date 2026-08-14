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
