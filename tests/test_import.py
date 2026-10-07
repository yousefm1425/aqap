"""اختبار المستورد على ملف النموذج الرسمي. يُتخطى إن لم يُحدد AQAP_TEST_XLSB."""
import os
import sys
from pathlib import Path

import psycopg
import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).parents[1]))
import import_xlsb as imp  # noqa: E402

XLSB = os.environ.get("AQAP_TEST_XLSB")
ADMIN_URL = os.environ.get("AQAP_TEST_ADMIN_URL", "postgresql://aqap:aqap@localhost:5432/postgres")
DB = "aqap_import_test"
pytestmark = pytest.mark.skipif(not XLSB or not Path(XLSB).exists(), reason="AQAP_TEST_XLSB غير محدد")


@pytest.fixture()
def conn():
    with psycopg.connect(ADMIN_URL, autocommit=True) as c:
        c.execute(f"DROP DATABASE IF EXISTS {DB} WITH (FORCE)")
        c.execute(f"CREATE DATABASE {DB}")
    url = ADMIN_URL.rsplit("/", 1)[0] + f"/{DB}"
    with psycopg.connect(url, autocommit=True) as c:
        c.execute((Path(__file__).parents[1] / "db" / "schema.sql").read_text(encoding="utf-8"))
        c.execute("""SET search_path = aqap;
            INSERT INTO institution(code, name_ar) VALUES ('YNB', 'الكلية التقنية التطبيقية بينبع');
            INSERT INTO app_user(institution_id, email, full_name_ar) VALUES (1, 'dean@ynb', 'وكيل الجودة');
            INSERT INTO user_role(user_id, role) VALUES (1, 'quality_dean');
            INSERT INTO assessment_cycle(institution_id, framework_id, title_ar, academic_year, starts_on, ends_on, status)
              VALUES (1, 1, 'دورة 1447', '1447', '2026-09-01', '2027-05-31', 'open');""")
    with psycopg.connect(url) as c:
        yield c


def test_parse_structure():
    data = imp.parse(XLSB)
    assert len(data.requirements) == 48
    assert len({q.sub_code for q in data.requirements}) == 18
    per_std = {n: sum(q.std_no == n for q in data.requirements) for n in range(1, 7)}
    assert per_std == {1: 11, 2: 13, 3: 9, 4: 7, 5: 4, 6: 4}
    q = next(q for q in data.requirements if q.code == "1-3-3")
    assert not q.text.endswith("*") and "الدراسات العامة" in q.note
    assert data.departments[0].name == "الدراسات العامة"


def test_import_framework_departments_and_ratings(conn):
    data = imp.parse(XLSB)
    # تقديرات اصطناعية: الملف المرفوع نموذج فارغ
    data.departments.append(imp.Department(2, "تقنية الحاسب", 12, 240))
    data.ratings += [
        imp.Rating(1, "الدراسات العامة", "1-1-1", "met", "insufficient", "توثيق المحاضر"),
        imp.Rating(1, "الدراسات العامة", "1-3-3", "na", "conforms", None),       # نجمة واحدة: مقبول للدراسات العامة
        imp.Rating(2, "تقنية الحاسب", "6-4-1", "partial", None, None),
    ]
    with conn.transaction():
        s = imp.apply(conn, data, institution_id=1, cycle_id=1, actor_id=1)
    assert s["requirements"] == 48 and s["departments_created"] == 2 and s["assessments_updated"] == 3
    assert s["moved_to_audited"] == 2
    conn.execute("SET search_path = aqap")
    assert conn.execute("SELECT count(*) FROM standard").fetchone()[0] == 6
    assert conn.execute("SELECT title_ar FROM standard WHERE code = '1'").fetchone()[0].strip() == "القيادة الإدارية"
    assert conn.execute("SELECT count(*) FROM assessment WHERE cycle_id = 1").fetchone()[0] == 96
    row = conn.execute("""SELECT a.status, a.self_rating, a.ext_verdict FROM assessment a
                            JOIN requirement r ON r.id = a.requirement_id WHERE r.code = '1-1-1' AND a.department_id = 1""").fetchone()
    assert row == ("audited", "met", "insufficient")
    assert conn.execute("SELECT na_scope FROM requirement WHERE code = '1-3-3'").fetchone()[0] == 1
    assert conn.execute("SELECT na_scope FROM requirement WHERE code = '2-2-1'").fetchone()[0] == 2
    gs = conn.execute("SELECT is_general_studies FROM department ORDER BY id").fetchall()
    assert [g[0] for g in gs] == [True, False]
    # «لا ينطبق» على متطلب النجمة الواحدة: مقبول للدراسات العامة فقط
    assert conn.execute("SELECT na_allowed(r.id, 1), na_allowed(r.id, 2) FROM requirement r WHERE r.code = '1-3-3'").fetchone() == (True, False)
    pct = conn.execute("SELECT self_pct, ext_pct FROM v_department_compliance WHERE department_id = 2").fetchone()
    assert float(pct[0]) == 0.0 and pct[1] is None          # «متحقق جزئي» لا يُحسب متحققاً في النموذج
    # الاستيراد المتكرر لا يكرر شيئاً
    with conn.transaction():
        s2 = imp.apply(conn, data, institution_id=1, cycle_id=1, actor_id=1)
    assert s2["departments_created"] == 0 and s2["moved_to_audited"] == 0
    assert conn.execute("SELECT count(*) FROM requirement").fetchone()[0] == 48


def test_verdict_roundtrip():
    """قيم الحكم الخارجي تُستورد وتُصدَّر بلا تحويل."""
    from app.export_official import VERDICT_LABEL
    for label, code in imp.VERDICT_MAP.items():
        if label != "غير كاف":
            assert VERDICT_LABEL[code] == label


@pytest.mark.skipif(not os.environ.get("AQAP_TEST_LIBREOFFICE"), reason="يتطلب LibreOffice (بطيء ~2 دقيقة)")
def test_export_official_template(conn, tmp_path):
    """تصدير كامل: قيم القالب الرسمي، وترتيب خطط التحسين مطابق لما تحسبه صيغ القالب نفسه."""
    import asyncio
    from psycopg import AsyncConnection
    from psycopg.rows import dict_row
    from app.export_official import build_payload, run_filler

    data = imp.parse(XLSB)
    with conn.transaction():
        imp.apply(conn, data, institution_id=1, cycle_id=1, actor_id=1)
        conn.execute("SELECT set_config('aqap.system_op', 'on', true)")
        conn.execute("""UPDATE aqap.assessment a SET self_rating = CASE WHEN r.sort_order % 6 = 0 THEN 'partial'
                          WHEN r.code = '1-3-3' THEN 'na' ELSE 'met' END::aqap.rating_t
                          FROM aqap.requirement r WHERE r.id = a.requirement_id""")
        conn.execute("UPDATE aqap.assessment SET ext_verdict = 'conforms'")
        conn.execute("UPDATE aqap.assessment SET status = 'final'")       # يولّد خطط التحسين
        conn.execute("UPDATE aqap.improvement_action SET action_ar = 'إجراء ' || id, owner_label = 'لجنة الجودة', due_date = '2027-01-31'")

    async def payload():
        async with await AsyncConnection.connect(conn.info.dsn, password="aqap", row_factory=dict_row,
                                                 options="-c search_path=aqap,public") as c:
            return await build_payload(c, 1)
    p = asyncio.run(payload())
    out = tmp_path / "export.xlsx"
    report = run_filler(p, XLSB, str(out), verify=True)
    assert report["verify"] == {"الدراسات العامة": True}
    assert report["plans_written"] == sum(1 for x in data.requirements if x.order % 6 == 0) and not report["warnings"]
    # نسب المنصة الذاتية = نسب القالب نفسه لكل قسم × معيار، بعد حسابها بصيغه
    ours = {(d, t.strip()): float(p) for d, t, p in conn.execute(
        """SELECT dp.name_ar, s.title_ar, round(v.self_pct, 1) FROM aqap.v_standard_compliance v
             JOIN aqap.department dp ON dp.id = v.department_id JOIN aqap.standard s ON s.id = v.standard_id""").fetchall()}
    theirs = {(d, t): p for d, t, p in report["verify_pct"]}
    assert theirs and all(abs(ours[k] - v) < 0.05 for k, v in theirs.items()), (ours, theirs)
