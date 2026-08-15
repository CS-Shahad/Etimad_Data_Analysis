"""
يسحب "المعلومات الأساسية الإضافية" و"نتائج الترسية" فقط للمنافسات
المنتهية (اعتمادًا على get_ended_tenders)، ويخزّنها بجدولي
tender_details و tender_bids.

تراكمي تلقائيًا: أي tender_id موجود مسبقًا بجدول tender_details يُتجاهل،
فتشغيل السكربت مرة ثانية بعد ما تنتهي منافسات جديدة يجيب الفرق فقط -
بدون الحاجة لملف checkpoint منفصل زي سكربت السحب الأول.

الاستخدام:
    python scripts/fetch_tender_details.py
"""

import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from etimad_scraper.config import load_config
from etimad_scraper.db import (
    get_connection,
    get_ended_tenders,
    get_fetched_tender_detail_ids,
    insert_tender_bids,
    insert_tender_details,
)
from etimad_scraper.parse_html import parse_awarding_results, parse_basic_info_report
from etimad_scraper.session import build_session, fetch_awarding_results, fetch_basic_info_report, warm_up


def polite_delay(cfg: dict) -> None:
    time.sleep(
        random.uniform(cfg["request"]["min_delay_seconds"], cfg["request"]["max_delay_seconds"])
    )


def main() -> None:
    cfg = load_config()
    client = build_session(cfg)
    conn = get_connection(cfg["storage"]["sqlite_path"])

    now_iso = datetime.now(timezone.utc).isoformat()
    ended = get_ended_tenders(conn, now_iso)
    already_fetched = get_fetched_tender_detail_ids(conn)
    pending = [t for t in ended if t["tender_id"] not in already_fetched]

    print(f"منافسات منتهية: {len(ended)}، تم سحبها مسبقًا: {len(already_fetched)}، متبقي: {len(pending)}")
    if not pending:
        print("لا يوجد شي جديد.")
        return

    print("تسخين الجلسة...")
    warm_up(client, cfg, page_number=1)

    for i, tender in enumerate(pending, start=1):
        tender_id = tender["tender_id"]
        tender_id_string = tender["tender_id_string"]
        fetched_at = datetime.now(timezone.utc).isoformat()

        report_resp = fetch_basic_info_report(client, cfg, tender_id_string)
        details = parse_basic_info_report(report_resp.text)
        insert_tender_details(conn, tender_id, details, fetched_at)
        polite_delay(cfg)

        award_resp = fetch_awarding_results(client, cfg, tender_id_string)
        award_data = parse_awarding_results(award_resp.text)
        n_bids = insert_tender_bids(
            conn, tender_id, award_data["bidders"], award_data["awarded"], fetched_at
        )
        polite_delay(cfg)

        print(
            f"  [{i}/{len(pending)}] tender_id={tender_id}: "
            f"{'ترسية موجودة' if award_data['awarded'] else 'بدون ترسية بعد'} "
            f"({n_bids} عرض مسجّل)"
        )

    conn.close()
    print(f"انتهى. تم سحب تفاصيل {len(pending)} منافسة جديدة.")


if __name__ == "__main__":
    main()
