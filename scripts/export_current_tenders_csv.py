"""
يصدّر كل الصفوف المجمّعة بجدول current_tenders (SQLite) إلى ملف CSV واحد
داخل data/processed/، وهو المسار الوحيد من بيانات المشروع المُتعمَّد رفعه
لـ git - عكس etimad.db وملف الـ checkpoint المستثنيين عمدًا (.gitignore)
لأنهما قابلين لإعادة التوليد بالكامل عبر إعادة تشغيل سكربتات السحب.

الاستخدام:
    python scripts/export_current_tenders_csv.py
    git add data/processed/current_tenders.csv
    git commit -m "..."
    git push
"""

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pandas as pd

from etimad_scraper.config import load_config


def main() -> None:
    cfg = load_config()
    sqlite_path = cfg["storage"]["sqlite_path"]
    csv_path = Path(cfg["storage"]["csv_export_path"])

    conn = sqlite3.connect(sqlite_path)
    df = pd.read_sql_query(
        "SELECT * FROM current_tenders ORDER BY scraped_at, tender_id", conn
    )
    conn.close()

    csv_path.parent.mkdir(parents=True, exist_ok=True)
    # utf-8-sig (BOM) so the Arabic columns display correctly when opened
    # directly in Excel on Windows, not just in pandas/a text editor.
    df.to_csv(csv_path, index=False, encoding="utf-8-sig")

    snapshots = df["scraped_at"].nunique() if not df.empty else 0
    print(f"تم تصدير {len(df)} صف ({snapshots} لقطة/لقطات زمنية) إلى {csv_path}")


if __name__ == "__main__":
    main()
