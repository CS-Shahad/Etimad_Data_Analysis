"""
سحب كامل لكل "المنافسات الحالية" المتاحة عبر AllSupplierTendersForVisitorAsync
وتخزينها كلقطة زمنية واحدة (scraped_at موحّد) بقاعدة SQLite.

مبني على نتائج الـ PoC والتشغيل الفعلي المؤكدة:
- جلسة httpx عادية (بدون متصفح) كافية لتجاوز كوكيز حماية F5.
- السيرفر يحدّ فعليًا عدد الصفوف بكل صفحة (~24) بصرف النظر عن PageSize
  المطلوب، لذلك التقدّم يعتمد على طول "data" الفعلي، والتوقف يعتمد فقط
  على استلام صفحة فارغة (وليس على totalCount، لأنه يتغيّر بيانات حيّة).
- بعد ~177 صفحة يبدأ السيرفر بإرجاع 429 (Rate Limiting)، فيتم التعامل
  معه بإعادة محاولة + انتظار (60 ثانية فأكثر) بدل تعطّل السكربت بالكامل.
- إذا تعطّل التشغيل (429 متكرر، انقطاع شبكة، Ctrl+C) يُستأنف السحب من
  آخر صفحة محفوظة بدل البدء من الصفحة الأولى، عبر ملف checkpoint.

الاستخدام:
    python scripts/collect_current_tenders_full.py
"""

import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from etimad_scraper.checkpoint import clear_checkpoint, load_checkpoint, save_checkpoint
from etimad_scraper.collect import collect_all_pages
from etimad_scraper.config import load_config
from etimad_scraper.db import get_connection, insert_tenders
from etimad_scraper.session import build_session, fetch_tenders_page, warm_up


def main() -> None:
    cfg = load_config()
    client = build_session(cfg)
    conn = get_connection(cfg["storage"]["sqlite_path"])
    checkpoint_path = cfg["storage"]["checkpoint_path"]
    page_size = cfg["current_tenders"]["collect_page_size"]

    checkpoint = load_checkpoint(checkpoint_path)
    if checkpoint:
        scraped_at = checkpoint["scraped_at"]
        start_page = checkpoint["last_completed_page"] + 1
        print(
            f"وُجد checkpoint سابق: استئناف اللقطة {scraped_at} "
            f"من الصفحة {start_page} (بدل البدء من جديد)."
        )
    else:
        scraped_at = datetime.now(timezone.utc).isoformat()
        start_page = 1
        print(f"لا يوجد checkpoint، بدء لقطة جديدة: {scraped_at}")

    print("تسخين الجلسة...")
    warm_up(client, cfg, page_number=1)

    def fetch_page_fn(page_number: int, size: int) -> dict:
        # fetch_tenders_page already retries on 429 (60s+ backoff) and
        # raises for other error statuses before returning.
        resp = fetch_tenders_page(client, cfg, page_number=page_number, page_size=size)
        return resp.json()

    def polite_delay() -> None:
        time.sleep(
            random.uniform(
                cfg["request"]["min_delay_seconds"], cfg["request"]["max_delay_seconds"]
            )
        )

    def on_page(page_number: int, data: list, total_count) -> None:
        inserted = insert_tenders(conn, data, scraped_at)
        save_checkpoint(
            checkpoint_path,
            {
                "scraped_at": scraped_at,
                "last_completed_page": page_number,
                "total_count_last_seen": total_count,
            },
        )
        print(f"  صفحة {page_number}: +{inserted} صف (المجموع المُعلَن={total_count})")

    print("بدء السحب...")
    records, total_count = collect_all_pages(
        fetch_page_fn,
        page_size=page_size,
        start_page=start_page,
        delay_fn=polite_delay,
        on_page=on_page,
    )

    # collect_all_pages only returns normally once it has actually reached
    # an empty page, i.e. the full listing is done - safe to drop the
    # checkpoint so the next run starts a fresh snapshot from page 1.
    clear_checkpoint(checkpoint_path)
    conn.close()

    print(f"انتهى. تم جمع {len(records)} منافسة بهذا التشغيل (آخر totalCount مُعلَن={total_count})")
    print(f"محفوظة في: {cfg['storage']['sqlite_path']} (scraped_at={scraped_at})")


if __name__ == "__main__":
    main()
