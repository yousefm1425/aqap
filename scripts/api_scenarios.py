"""سيناريوهات منطق العمل السلبية والتزامن (بعد تسجيل دخول ناجح لكل دور) — يجب أن تُرفض بـ 4xx واضحة، لا 5xx ولا قبول خاطئ.

  python scripts/api_scenarios.py --base http://localhost:8013 --db postgresql://aqap:aqap@localhost/aqapfuzz
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import sys

import psycopg

from api_fuzz import Api

RESULTS: list[tuple[bool, str]] = []


def expect(label, got, ok):
    s, b = got
    good = ok(s)
    RESULTS.append((good, f"{label} → {s} {str(b)[:160] if not good else ''}"))
    return got


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8013")
    ap.add_argument("--db", required=True)
    a = ap.parse_args()
    api = Api(a.base)
    is4 = lambda s: 400 <= s < 500  # noqa: E731
    with psycopg.connect(a.db) as c:
        one = lambda s, *p: (c.execute(s, p or None).fetchone() or [None])[0]  # noqa: E731
        tc = one("SELECT id FROM aqap.department WHERE name_ar LIKE '%اتصالات%'")
        cs = one("SELECT id FROM aqap.department WHERE name_ar='تقنية الحاسب'")
        cyc = one("SELECT id FROM aqap.assessment_cycle WHERE framework_id=(SELECT id FROM aqap.framework WHERE code='TVTC-TQ-L2')")
        f_ok = one("SELECT id FROM aqap.form_record WHERE department_id=%s AND status='approved' ORDER BY id", tc)
        m_ok = one("SELECT id FROM aqap.minutes WHERE department_id=%s AND status='approved' ORDER BY id", tc)
        a_fin = one("SELECT id FROM aqap.assessment WHERE department_id=%s AND status='final' ORDER BY id", tc)
        rec = one("""SELECT r.id FROM aqap.minutes_recommendation r JOIN aqap.minutes_agenda_item i ON i.id=r.agenda_item_id
                     WHERE i.minutes_id=%s ORDER BY r.id""", m_ok)
        tpl_free = one("""SELECT t.id FROM aqap.form_template t WHERE NOT EXISTS (SELECT 1 FROM aqap.form_record f
                          WHERE f.template_id=t.id AND f.department_id=%s AND f.cycle_id=%s) AND t.framework_code='TVTC-TQ-L2' ORDER BY t.id""", cs, cyc)
        mt = one("SELECT id FROM aqap.minutes_template WHERE framework_code='TVTC-TQ-L2' ORDER BY id")
    C, H, D, AU = "coord.tc@ynb", "hod.tc@ynb", "dean@ynb", "auditor@ynb"

    # الوثائق المعتمدة مقفلة
    expect("تعديل محضر معتمد", api.req("PUT", f"/api/v1/minutes/{m_ok}", {"title_ar": "تعديل بعد الاعتماد", "agenda": [], "attendees": []}, who=C), is4)
    expect("حذف محضر معتمد", api.req("DELETE", f"/api/v1/minutes/{m_ok}", who=C), is4)
    expect("حذف نموذج معتمد", api.req("DELETE", f"/api/v1/forms/{f_ok}", who=C), is4)
    expect("اعتماد نموذج معتمد مرة ثانية", api.req("POST", f"/api/v1/forms/{f_ok}/transition", {"to_status": "approved"}, who=H), is4)
    expect("تعديل تقييم ذاتي لمتطلب نهائي", api.req("PATCH", f"/api/v1/assessments/{a_fin}/self", {"self_rating": "not_met"}, who=C), is4)
    expect("المنسق يعتمد نهائياً", api.req("POST", f"/api/v1/assessments/{a_fin}/transition", {"to_status": "final"}, who=C), is4)
    expect("متابعة توصية جزئية بلا معوقات", api.req("PATCH", f"/api/v1/minutes/recommendations/{rec}/follow-up", {"fu_status": "partial"}, who=C), is4)
    expect("رابط شاهد من نطاق غير معتمد", api.req("POST", "/api/v1/evidence", {"title_ar": "رابط خارجي", "kind": "link",
                                                                           "url": "https://evil.example.com/a", "department_id": tc}, who=C), is4)
    expect("رابط بلا https", api.req("POST", "/api/v1/evidence", {"title_ar": "رابط", "kind": "link", "url": "javascript:alert(1)", "department_id": tc}, who=C), is4)

    # التحقق من قيم النموذج
    s, f = expect("إنشاء نموذج جديد لقسم الحاسب", api.req("POST", f"/api/v1/cycles/{cyc}/forms", {"template_id": tpl_free, "department_id": cs}, who="coord.cs@ynb"),
                  lambda s: s == 201)
    if s == 201:
        fid, sch = f["id"], f["schema"]
        tab = next(x for x in sch["sections"] if x["type"] == "table" and x.get("phase") != "follow" and not x.get("fixed_rows"))
        num = next((c for c in tab["columns"] if c["type"] == "number" and c.get("phase") == "plan"), None)
        sel = next((c for c in tab["columns"] if c["type"] == "select" and c.get("phase") == "plan"), None)
        if num:
            expect("رقم نصي في عمود رقمي", api.req("PUT", f"/api/v1/forms/{fid}", {"plan_data": {tab["key"]: [{num["key"]: "خمسة"}]}}, who="coord.cs@ynb"), lambda s: s == 422)
        if sel:
            expect("قيمة خارج قائمة الاختيار", api.req("PUT", f"/api/v1/forms/{fid}", {"plan_data": {tab["key"]: [{sel["key"]: "قيمة دخيلة"}]}}, who="coord.cs@ynb"), lambda s: s == 422)
        expect("تجاوز الحد الأعلى للصفوف", api.req("PUT", f"/api/v1/forms/{fid}", {"plan_data": {tab["key"]: [{} for _ in range(tab.get("max_rows", 100) + 1)]}},
                                                    who="coord.cs@ynb"), lambda s: s == 422)
        expect("رفع نموذج ناقص", api.req("POST", f"/api/v1/forms/{fid}/transition", {"to_status": "submitted"}, who="coord.cs@ynb"), is4)
        expect("اعتماد مسودة لم تُرفع", api.req("POST", f"/api/v1/forms/{fid}/transition", {"to_status": "approved"}, who="hod.cs@ynb"), is4)
        xss = "<img src=x onerror=alert(1)><script>alert(1)</script>"
        expect("نص فيه وسوم HTML يُحفظ كنص", api.req("PUT", f"/api/v1/forms/{fid}", {"plan_data": {tab["key"]: [{c["key"]: xss for c in tab["columns"]
                                                                                                  if c["type"] in ("text", "longtext") and c.get("phase") == "plan"}]}},
                                                         who="coord.cs@ynb"), lambda s: s == 200)
        s, pdf = api.req("GET", f"/api/v1/forms/{fid}/pdf", who="coord.cs@ynb")
        expect("PDF لنموذج فيه وسوم HTML", (s, ""), lambda s: s == 200)
        # التزامن: إنشاء النموذج نفسه مرتين معاً
        with cf.ThreadPoolExecutor(4) as ex:
            rs = list(ex.map(lambda _: api.req("DELETE", f"/api/v1/forms/{fid}", who="coord.cs@ynb"), range(3)))
        codes = sorted(r[0] for r in rs)
        RESULTS.append((codes.count(204) == 1 and all(c < 500 for c in codes), f"حذف متزامن لنفس المسودة → {codes}"))
        with cf.ThreadPoolExecutor(4) as ex:
            rs = list(ex.map(lambda _: api.req("POST", f"/api/v1/cycles/{cyc}/forms", {"template_id": tpl_free, "department_id": cs}, who="coord.cs@ynb"), range(4)))
        codes = sorted(r[0] for r in rs)
        RESULTS.append((codes.count(201) == 1 and all(c < 500 for c in codes), f"إنشاء متزامن لنفس النموذج → {codes}"))

    # محضر: رقم الاجتماع تسلسلي تحت التزامن
    with cf.ThreadPoolExecutor(4) as ex:
        rs = list(ex.map(lambda _: api.req("POST", f"/api/v1/cycles/{cyc}/minutes", {"template_id": mt, "department_id": cs}, who="coord.cs@ynb"), range(4)))
    codes = [r[0] for r in rs]
    nos = sorted(r[1]["meeting_no"] for r in rs if r[0] == 201)
    RESULTS.append((all(c in (201, 409) for c in codes) and len(set(nos)) == len(nos), f"إنشاء محاضر متزامنة → {codes} أرقام {nos}"))
    # اعتماد متزامن لمحضر مرفوع
    mid = next((r[1]["id"] for r in rs if r[0] == 201), None)
    if mid:
        api.req("PUT", f"/api/v1/minutes/{mid}", {"title_ar": "اجتماع اختبار التزامن", "meeting_date": "2026-01-10",
                                                  "agenda": [{"title_ar": "محور", "recommendations": [{"text_ar": "توصية", "responsible_ar": "رئيس القسم", "period_ar": "شهر"}]}],
                                                  "attendees": [{"name_ar": "عضو أول"}, {"name_ar": "عضو ثان"}]}, who="coord.cs@ynb")
        s, b = api.req("POST", f"/api/v1/minutes/{mid}/transition", {"to_status": "submitted"}, who="coord.cs@ynb")
        with cf.ThreadPoolExecutor(3) as ex:
            rs = list(ex.map(lambda _: api.req("POST", f"/api/v1/minutes/{mid}/transition", {"to_status": "approved"}, who="hod.cs@ynb"), range(3)))
        codes = sorted(r[0] for r in rs)
        RESULTS.append((codes.count(200) == 1 and all(c < 500 for c in codes), f"اعتماد متزامن لنفس المحضر → {codes} (الرفع {s})"))

    bad = [m for ok, m in RESULTS if not ok]
    for ok, m in RESULTS:
        print(("  ✓ " if ok else "  ✗ ") + m)
    print(f"\n{len(RESULTS)} سيناريو — إخفاقات {len(bad)}")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
