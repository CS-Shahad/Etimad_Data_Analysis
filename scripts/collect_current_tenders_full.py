"""
سحب كامل لكل "المنافسات الحالية" المتاحة عبر AllSupplierTendersForVisitorAsync
وتخزينها كلقطة زمنية واحدة (scraped_at موحّد) بقاعدة SQLite.

مبني على نتائج الـ PoC المؤكدة:
- جلسة httpx عادية (بدون متصفح) كافية لتجاوز كوكيز حماية F5.
- السيرفر يحدّ فعليًا عدد الصفوف بكل صفحة (~24) بصرف النظر عن PageSize
  المطلوب، لذلك تتبّع التقدّم يعتمد على طول "data" الفعلي + totalCount
  المُعلَن، وليس على قيمة PageSize نفسها.

الاستخدام:
    python scripts/collect_current_tenders_full.py
"""

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from etimad_scraper.collect import collect_all_pages
from etimad_scraper.config import load_config
from etimad_scraper.db import get_connection, insert_tenders
from etimad_scraper.session import build_session, fetch_tenders_page, warm_up


def main() -> None:
    cfg = load_config()
    client = build_session(cfg)
    conn = get_connection(cfg["storage"]["sqlite_path"])
    scraped_at = datetime.now(timezone.utc).isoformat()
    page_size = cfg["current_tenders"]["collect_page_size"]

    print("تسخين الجلسة...")
    warm_up(client, cfg, page_number=1)

    def fetch_page_fn(page_number: int, size: int) -> dict:
        # fetch_tenders_page already retries on 429 and raises for other
        # error statuses before returning.
        resp = fetch_tenders_page(client, cfg, page_number=page_number, page_size=size)
        return resp.json()

    def polite_delay() -> None:
        import random
        import time

        time.sleep(
            random.uniform(
                cfg["request"]["min_delay_seconds"], cfg["request"]["max_delay_seconds"]
            )
        )

    def on_page(page_number: int, data: list, total_count) -> None:
        inserted = insert_tenders(conn, data, scraped_at)
        print(f"  صفحة {page_number}: +{inserted} صف (المجموع المُعلَن={total_count})")

    print("بدء السحب الكامل...")
    records, total_count = collect_all_pages(
        fetch_page_fn,
        page_size=page_size,
        delay_fn=polite_delay,
        on_page=on_page,
    )

    conn.close()
    print(f"انتهى. تم جمع {len(records)} منافسة من أصل totalCount المُعلَن={total_count}")
    print(f"محفوظة في: {cfg['storage']['sqlite_path']} (scraped_at={scraped_at})")


if __name__ == "__main__":
    main()
