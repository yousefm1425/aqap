"""تجهيز منصة جديدة ببيانات الكلية الأساسية: المعايير الرسمية، الأقسام، ودورة التقييم — دون أي بيانات تجريبية.

يُشغَّل مرة واحدة بعد أول نشر (وبعد create_admin.py)، من طرفية حاوية المنصة:
    python scripts/setup_college.py

ما ينشئه (آمن للتكرار؛ لا يكرر ما هو موجود):
  1) إطار «نموذج العمل الشامل – المستوى الثاني»: 6 معايير، 18 معياراً فرعياً، 48 متطلباً،
     بالنصوص والعناوين الرسمية (من ترحيلات 017 و018) وقاعدة «لا ينطبق» (* و**).
  2) أقسام الكلية: تقنية الحاسب، التقنية الكهربائية، التقنية الميكانيكية، تقنية الاتصالات،
     التقنية الإلكترونية، الدراسات العامة.
  3) دورة «التقييم الذاتي 1447هـ» مفتوحة، تشمل كل الأقسام، مع توليد تقديرات كل قسم.
ثم يعيد تطبيق ترحيلات القاعدة (آمنة للتكرار) لربط النصوص الرسمية ومهام أعمال الجودة بالمتطلبات.
لا ينشئ مستخدمين ولا تقديرات أو شواهد تجريبية.
"""
import argparse
import os
import sys
from pathlib import Path

import psycopg

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from seed_demo import DEPTS, STANDARDS, STARRED, SUB_TITLES  # noqa: E402  (بنية النموذج الرسمي)

FRAMEWORK = "TVTC-TQ-L2"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dsn", default=os.environ.get("AQAP_DATABASE_URL"))
    ap.add_argument("--year", default="1447", help="العام التدريبي (هجري)")
    ap.add_argument("--starts", default="2026-09-01")
    ap.add_argument("--ends", default="2027-05-31")
    a = ap.parse_args()
    if not a.dsn:
        sys.exit("AQAP_DATABASE_URL غير محدد")

    with psycopg.connect(a.dsn, autocommit=True) as conn:
        conn.execute("SET search_path = aqap, public")

        # المنشأة (تُنشأ مع حساب المدير عادة)
        row = conn.execute("SELECT id FROM institution ORDER BY id LIMIT 1").fetchone()
        inst = row[0] if row else conn.execute(
            "INSERT INTO institution(code, name_ar) VALUES ('YNB', 'الكلية التقنية التطبيقية بينبع') RETURNING id").fetchone()[0]

        # (1) الإطار والمتطلبات
        fw = conn.execute("SELECT id FROM framework WHERE code = %s", (FRAMEWORK,)).fetchone()
        if fw is None:
            sys.exit(f"الإطار {FRAMEWORK} غير موجود في المخطط")
        fw = fw[0]
        n_req = conn.execute("""SELECT count(*) FROM requirement r JOIN sub_standard ss ON ss.id = r.sub_standard_id
                                  JOIN standard s ON s.id = ss.standard_id WHERE s.framework_id = %s""", (fw,)).fetchone()[0]
        if n_req == 0:
            rows, order = [], 0
            for si, (scode, stitle, subs) in enumerate(STANDARDS, 1):
                for j, n in enumerate(subs, 1):
                    sub = f"{scode}-{j}"
                    for k in range(1, n + 1):
                        order += 1
                        code = f"{sub}-{k}"
                        # «نص تجريبي» يُستبدل بالنص الرسمي في ترحيل 017 أدناه
                        rows.append((scode, stitle, si, sub, SUB_TITLES.get(sub, f"معيار فرعي {sub}"), j, code,
                                     f"نص تجريبي للمتطلب {code}", order, "department", True, STARRED.get(code, 0)))
            with conn.transaction():
                conn.execute("TRUNCATE import_requirement_staging")
                with conn.cursor() as cur:
                    cur.executemany("INSERT INTO import_requirement_staging VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)", rows)
                conn.execute("SELECT import_framework_from_staging(%s)", (FRAMEWORK,))
                conn.execute("TRUNCATE import_requirement_staging")
            print(f"✓ المعايير: {len(STANDARDS)} معايير و{sum(len(s[2]) for s in STANDARDS)} معياراً فرعياً و{len(rows)} متطلباً")
        else:
            print(f"• المعايير موجودة مسبقاً ({n_req} متطلباً)")

        # (2) الأقسام
        added = 0
        for code, name in DEPTS + [("GS", "الدراسات العامة")]:
            exists = conn.execute("SELECT 1 FROM department WHERE institution_id = %s AND (code = %s OR name_ar = %s)",
                                  (inst, code, name)).fetchone()
            if not exists:
                conn.execute("INSERT INTO department(institution_id, code, name_ar, is_general_studies) VALUES (%s, %s, %s, %s)",
                             (inst, code, name, code == "GS"))
                added += 1
        n_dept = conn.execute("SELECT count(*) FROM department WHERE institution_id = %s AND is_active", (inst,)).fetchone()[0]
        print(f"✓ الأقسام: {n_dept} (أُضيف {added})")

        # (3) دورة التقييم
        cyc = conn.execute("SELECT id FROM assessment_cycle WHERE institution_id = %s AND framework_id = %s AND academic_year = %s",
                           (inst, fw, a.year)).fetchone()
        if cyc is None:
            with conn.transaction():
                cyc_id = conn.execute(
                    """INSERT INTO assessment_cycle(institution_id, framework_id, title_ar, academic_year, starts_on, ends_on, status)
                       VALUES (%s, %s, %s, %s, %s, %s, 'open') RETURNING id""",
                    (inst, fw, f"التقييم الذاتي {a.year}هـ", a.year, a.starts, a.ends)).fetchone()[0]
                conn.execute("""INSERT INTO cycle_department (cycle_id, department_id)
                                SELECT %s, id FROM department WHERE institution_id = %s AND is_active""", (cyc_id, inst))
                conn.execute("SELECT generate_cycle_assessments(%s)", (cyc_id,))
            print(f"✓ دورة «التقييم الذاتي {a.year}هـ» مفتوحة")
        else:
            cyc_id = cyc[0]
            conn.execute("""INSERT INTO cycle_department (cycle_id, department_id)
                            SELECT %s, id FROM department WHERE institution_id = %s AND is_active ON CONFLICT DO NOTHING""",
                         (cyc_id, inst))
            conn.execute("SELECT generate_cycle_assessments(%s)", (cyc_id,))
            print(f"• الدورة {a.year} موجودة مسبقاً")

        # النصوص والعناوين الرسمية وربط مهام الجودة: الترحيلات آمنة للتكرار
        for f in sorted((ROOT / "db" / "migrations").glob("*.sql")):
            conn.execute(f.read_text(encoding="utf-8"))
        n_assess = conn.execute("SELECT count(*) FROM assessment WHERE cycle_id = %s", (cyc_id,)).fetchone()[0]
        n_demo = conn.execute("SELECT count(*) FROM requirement WHERE text_ar LIKE 'نص تجريبي%%'").fetchone()[0]
        print(f"✓ التقديرات المولّدة: {n_assess}")
        print("✓ النصوص الرسمية مطبّقة" if n_demo == 0 else f"⚠ بقي {n_demo} متطلباً بنص تجريبي")
    print("\nجاهزة: افتح المنصة ← نطاق المتطلبات. أضف المستخدمين من صفحة «المستخدمون».")


if __name__ == "__main__":
    main()
