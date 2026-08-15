import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from etimad_scraper.db import (
    get_connection,
    get_ended_tenders,
    get_fetched_tender_detail_ids,
    insert_tender_bids,
    insert_tender_detail_failure,
    insert_tender_details,
    insert_tenders,
)

# Real record shape captured from AllSupplierTendersForVisitorAsync.
SAMPLE_RECORD = {
    "tenderId": 1091935,
    "referenceNumber": "260739009111",
    "tenderName": "تأمين وتوريد زيوت محرك ديزل للأليات الفنية والمعدات للإدارات الخارجية",
    "tenderNumber": "2026-027",
    "branchName": "ادارة الشؤون الفنية المركزية بمنطقة الرياض",
    "agencyName": "ادارة الشؤون الفنية المركزية بمنطقة الرياض",
    "tenderIdString": "JIIlkiSVr7 ex63lRmP8DQ==",
    "tenderStatusId": 4,
    "tenderTypeId": 2,
    "tenderTypeName": "شراء مباشر",
    "condetionalBookletPrice": 0.00,
    "lastEnqueriesDate": "2026-08-16T02:32:11.170565",
    "lastOfferPresentationDate": "2026-08-18T09:59:00",
    "offersOpeningDate": None,
    "tenderActivityName": "تجارة قطع الغيار الجديدة",
    "tenderActivityId": 111,
    "submitionDate": "2026-08-14T02:32:11.1706695",
    "financialFees": 0.00,
    "invitationCost": 200.00,
    "buyingCost": 0.00,
    "hasInvitations": False,
    "isUGRP": False,
}


def test_insert_tenders_maps_fields_and_round_trips(tmp_path):
    conn = get_connection(tmp_path / "test.db")

    inserted = insert_tenders(conn, [SAMPLE_RECORD], scraped_at="2026-08-14T00:00:00Z")
    assert inserted == 1

    row = conn.execute(
        "SELECT tender_id, tender_name, agency_name, tender_type_name, "
        "has_invitations, last_offer_presentation_date, scraped_at "
        "FROM current_tenders WHERE tender_id = ?",
        (1091935,),
    ).fetchone()

    assert row == (
        1091935,
        SAMPLE_RECORD["tenderName"],
        SAMPLE_RECORD["agencyName"],
        "شراء مباشر",
        0,
        "2026-08-18T09:59:00",
        "2026-08-14T00:00:00Z",
    )
    conn.close()


def test_insert_tenders_same_tender_two_scrapes_keeps_both_snapshots(tmp_path):
    conn = get_connection(tmp_path / "test.db")

    insert_tenders(conn, [SAMPLE_RECORD], scraped_at="2026-08-14T00:00:00Z")
    insert_tenders(conn, [SAMPLE_RECORD], scraped_at="2026-08-15T00:00:00Z")

    count = conn.execute(
        "SELECT COUNT(*) FROM current_tenders WHERE tender_id = ?", (1091935,)
    ).fetchone()[0]

    assert count == 2
    conn.close()


def _tender(tender_id: int, deadline: str) -> dict:
    record = dict(SAMPLE_RECORD)
    record["tenderId"] = tender_id
    record["lastOfferPresentationDate"] = deadline
    return record


def test_get_ended_tenders_returns_only_past_deadline():
    conn = get_connection(":memory:")
    insert_tenders(conn, [_tender(1, "2026-08-10T09:59:00")], scraped_at="2026-08-14T00:00:00Z")
    insert_tenders(conn, [_tender(2, "2026-08-20T09:59:00")], scraped_at="2026-08-14T00:00:00Z")

    ended = get_ended_tenders(conn, now_iso="2026-08-14T00:00:00")

    assert [t["tender_id"] for t in ended] == [1]
    conn.close()


def test_get_ended_tenders_uses_latest_snapshot_only():
    conn = get_connection(":memory:")
    # First snapshot: still open. Second (later) snapshot: deadline extended
    # is not what we're testing here - we're testing that an *earlier*
    # snapshot showing a since-passed deadline doesn't leak in if the
    # latest snapshot for that tender no longer qualifies, and vice versa.
    insert_tenders(conn, [_tender(1, "2026-08-10T09:59:00")], scraped_at="2026-08-05T00:00:00Z")
    insert_tenders(conn, [_tender(1, "2026-08-30T09:59:00")], scraped_at="2026-08-14T00:00:00Z")

    ended = get_ended_tenders(conn, now_iso="2026-08-20T00:00:00")

    # latest snapshot's deadline (08-30) is still in the future -> not ended,
    # even though the earlier snapshot's deadline (08-10) had already passed.
    assert ended == []
    conn.close()


def test_insert_tender_details_round_trips():
    conn = get_connection(":memory:")
    details = {
        "tender_value": "0.00",
        "tender_purpose": "توريد دهانات",
        "standstill_period": None,
        "expected_award_date_raw": "التاريخ: 16/04/1448\nالموافق: 28/09/2026",
        "expected_award_date": "28/09/2026",
        "work_start_date_raw": None,
        "work_start_date": None,
        "offer_submission_location": None,
        "offer_opening_location": "لا يوجد",
        "execution_location": "داخل المملكة",
        "classification": None,
    }

    insert_tender_details(conn, tender_id=1075680, details=details, fetched_at="2026-08-15T00:00:00Z")

    row = conn.execute(
        "SELECT tender_value, tender_purpose, expected_award_date, execution_location "
        "FROM tender_details WHERE tender_id = ?",
        (1075680,),
    ).fetchone()

    assert row == ("0.00", "توريد دهانات", "28/09/2026", "داخل المملكة")
    conn.close()


def test_get_fetched_tender_detail_ids_tracks_what_was_already_pulled():
    conn = get_connection(":memory:")
    assert get_fetched_tender_detail_ids(conn) == set()

    insert_tender_details(conn, tender_id=1, details={}, fetched_at="2026-08-15T00:00:00Z")
    insert_tender_details(conn, tender_id=2, details={}, fetched_at="2026-08-15T00:00:00Z")

    assert get_fetched_tender_detail_ids(conn) == {1, 2}
    conn.close()


def test_insert_tender_bids_marks_the_awarded_supplier():
    conn = get_connection(":memory:")
    bidders = [
        {"supplier_name": "مورد أ", "financial_offer": 100.0, "technical_result": "مطابق"},
        {"supplier_name": "مورد ب", "financial_offer": 90.0, "technical_result": "غير مطابق"},
    ]
    awarded = [{"supplier_name": "مورد أ", "financial_offer": 100.0, "award_value": 100.0}]

    inserted = insert_tender_bids(conn, tender_id=1075680, bidders=bidders, awarded=awarded, fetched_at="2026-08-15T00:00:00Z")
    assert inserted == 2

    rows = conn.execute(
        "SELECT supplier_name, is_awarded, award_value FROM tender_bids "
        "WHERE tender_id = ? ORDER BY supplier_name",
        (1075680,),
    ).fetchall()

    assert rows == [
        ("مورد أ", 1, 100.0),
        ("مورد ب", 0, None),
    ]
    conn.close()


def test_insert_tender_bids_handles_not_yet_awarded_tender():
    conn = get_connection(":memory:")

    inserted = insert_tender_bids(conn, tender_id=1, bidders=[], awarded=[], fetched_at="2026-08-15T00:00:00Z")

    assert inserted == 0
    conn.close()


def test_insert_tender_detail_failure_round_trips():
    conn = get_connection(":memory:")

    insert_tender_detail_failure(
        conn,
        tender_id=1094858,
        tender_id_string="AiWoj*@@**wElUruvO2kh2ftnQ==",
        error="400 Bad Request",
        failed_at="2026-08-15T00:00:00Z",
    )

    row = conn.execute(
        "SELECT tender_id, tender_id_string, error FROM tender_detail_failures WHERE tender_id = ?",
        (1094858,),
    ).fetchone()

    assert row == (1094858, "AiWoj*@@**wElUruvO2kh2ftnQ==", "400 Bad Request")
    conn.close()


def test_insert_tender_detail_failure_does_not_count_as_fetched():
    conn = get_connection(":memory:")

    insert_tender_detail_failure(
        conn, tender_id=1, tender_id_string="x", error="400", failed_at="2026-08-15T00:00:00Z"
    )

    assert get_fetched_tender_detail_ids(conn) == set()
    conn.close()
