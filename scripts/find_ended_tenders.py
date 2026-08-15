"""
يحدد أي المنافسات بجدول current_tenders (SQLite) تجاوزت موعدها النهائي
(last_offer_presentation_date) اعتمادًا على آخر لقطة (scraped_at) لكل
منافسة، ويصدّرها لملف CSV منفصل.

هذي هي القائمة اللي راح نستخدمها لاحقًا كمدخل لسحب تبويبي "المعلومات
الأساسية" و"نتائج الترسية" فقط للمنافسات المنتهية (تحتمل وجود بيانات
ترسية)، بدل محاولة سحبها لكل المنافسات المفتوحة اللي أكيد ما عندها ترسية
بعد.

الاستخدام:
    python scripts/find_ended_tenders.py
"""

import csv
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from etimad_scraper.config import load_config
from etimad_scraper.db import get_connection, get_ended_tenders


def main() -> None:
    cfg = load_config()
    conn = get_connection(cfg["storage"]["sqlite_path"])
    now_iso = datetime.now(timezone.utc).isoformat()

    ended = get_ended_tenders(conn, now_iso)
    conn.close()

    print(f"عدد المنافسات المنتهية (آخر لقطة لكل منافسة، حتى {now_iso}): {len(ended)}")

    out_path = Path(cfg["storage"]["ended_tenders_csv_path"])
    if not ended:
        print("لا يوجد شي يُصدَّر.")
        return

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(ended[0].keys()))
        writer.writeheader()
        writer.writerows(ended)

    print(f"محفوظة في: {out_path}")


if __name__ == "__main__":
    main()
