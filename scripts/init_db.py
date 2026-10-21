"""تهيئة قاعدة البيانات عند تشغيل الحاوية (Render وأي استضافة) — بلا psql، وآمنة للتكرار.

- قاعدة فارغة: يُطبَّق db/schema.sql ثم بيانات العرض التجريبية (أو لا شيء إن كان AQAP_SEED_DEMO=0).
- قاعدة قائمة: تُطبَّق ملفات db/migrations بالترتيب (كل ملف آمن للتكرار).
"""
import os
import sys
from pathlib import Path

import psycopg

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    dsn = os.environ.get("AQAP_DATABASE_URL") or (sys.argv[1] if len(sys.argv) > 1 else None)
    if not dsn:
        sys.exit("AQAP_DATABASE_URL غير محدد")
    with psycopg.connect(dsn, autocommit=True) as conn:
        exists = conn.execute("SELECT to_regclass('aqap.assessment') IS NOT NULL").fetchone()[0]
        if exists:
            for f in sorted((ROOT / "db" / "migrations").glob("*.sql")):
                conn.execute(f.read_text(encoding="utf-8"))
                print(f"✓ ترحيل: {f.name}")
            return
        print("⏳ إنشاء المخطط…")
        conn.execute((ROOT / "db" / "schema.sql").read_text(encoding="utf-8"))
    if os.environ.get("AQAP_SEED_DEMO", "1") != "0":
        sys.path.insert(0, str(ROOT / "scripts"))
        import seed_demo
        seed_demo.main(dsn)
    print("✓ قاعدة البيانات جاهزة")


if __name__ == "__main__":
    main()
