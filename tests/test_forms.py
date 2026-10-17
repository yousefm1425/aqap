"""محرّك النماذج: القوالب، والتحقق، والصيغ (مطابقة لملفات Excel)، ومسار الاعتماد، وقفل التخطيط، والمتابعة، والشواهد."""
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import psycopg
import pytest

ADMIN_URL = os.environ.get("AQAP_TEST_ADMIN_URL", "postgresql://aqap:aqap@localhost:5432/postgres")
DB = "aqap_forms_test"
API = "/api/v1"
ROOT = Path(__file__).parents[1]

REQS = [("1-1", "التوجيه التشغيلي", ["1-1-1", "1-1-2"]), ("1-2", "إدارة وتطوير الموارد البشرية", ["1-2-1", "1-2-2", "1-2-3"]),
        ("1-3", "القبول والجداول التدريبية", ["1-3-1", "1-3-2", "1-3-3", "1-3-4"]), ("1-4", "التواصل والمشاركة", ["1-4-1", "1-4-2"])]
STAGING = ",\n".join(
    f"('1','القيادة الإدارية',1,'{ss}','{title}',{i},'{r}','متطلب {r}',{j},'department',true,0)"
    for i, (ss, title, rs) in enumerate(REQS, 1) for j, r in enumerate(rs, 1))
SEED = f"""
SET search_path = aqap;
INSERT INTO import_requirement_staging VALUES {STAGING};
SELECT import_framework_from_staging('TVTC-TQ-L2');
INSERT INTO institution(code, name_ar) VALUES ('YNB', 'الكلية التقنية التطبيقية بينبع');
INSERT INTO department(institution_id, code, name_ar) VALUES (1,'CS','تقنية الحاسب'), (1,'EE','التقنية الكهربائية');
INSERT INTO app_user(institution_id, email, full_name_ar) VALUES
 (1,'coord@ynb','منسق الحاسب'), (1,'hod@ynb','رئيس قسم الحاسب'), (1,'dean@ynb','وكيل الجودة'), (1,'coord.ee@ynb','منسق الكهرباء');
INSERT INTO user_role(user_id, role, department_id) VALUES (1,'dept_coordinator',1), (2,'hod',1), (3,'quality_dean',NULL), (4,'dept_coordinator',2);
INSERT INTO assessment_cycle(institution_id, framework_id, title_ar, academic_year, starts_on, ends_on, status)
 VALUES (1,1,'دورة 1448','1448','2026-08-01','2027-04-30','open');
INSERT INTO cycle_department VALUES (1,1),(1,2);
SELECT generate_cycle_assessments(1);
"""


@pytest.fixture(scope="module")
def client():
    with psycopg.connect(ADMIN_URL, autocommit=True) as c:
        c.execute(f"DROP DATABASE IF EXISTS {DB} WITH (FORCE)")
        c.execute(f"CREATE DATABASE {DB}")
    url = ADMIN_URL.rsplit("/", 1)[0] + f"/{DB}"
    with psycopg.connect(url, autocommit=True) as c:
        c.execute((ROOT / "db" / "schema.sql").read_text(encoding="utf-8"))
        c.execute(SEED)
    os.environ.update({"AQAP_DATABASE_URL": url, "AQAP_STORAGE_BACKEND": "local", "AQAP_ENV": "test",
                       "AQAP_LOCAL_STORAGE_DIR": tempfile.mkdtemp(prefix="aqap-forms-"), "AQAP_JWT_SECRET": "test-secret"})
    import importlib

    from app import config
    importlib.reload(config)
    from app import db, main, security, storage
    for mod in (security, storage):
        mod.settings = config.settings
    main.settings = config.settings
    from fastapi.testclient import TestClient
    with TestClient(main.app) as c:
        yield c
    db._pool = None


def h(client, email):
    t = client.post(f"{API}/auth/dev-token", json={"email": email}).json()["access_token"]
    return {"Authorization": f"Bearer {t}"}


def test_executive_plan_lifecycle(client):
    coord, hod, dean, ee = (h(client, e) for e in ("coord@ynb", "hod@ynb", "dean@ynb", "coord.ee@ynb"))
    tpls = client.get(f"{API}/cycles/1/forms/templates?department_id=1", headers=coord).json()
    assert [t["requirement_code"] for t in tpls] == ["1-1-2", "1-2-2", "1-2-3", "1-3-2", "1-3-3", "1-3-4", "1-4-1", "1-4-2",
                                                     "2-1-1", "2-1-3", "2-2-1", "2-2-2", "2-2-4", "2-2-5", "2-2-6", "2-2-7",
                                                     "2-2-9", "2-2-10", "3-1-2", "3-2-2", "3-2-5", "3-3-2", "4-1-2", "4-1-3",
                                                     "4-2-1", "4-2-2", "4-3-1"]
    t132 = next(t for t in tpls if t["requirement_code"] == "1-3-2")
    assert t132["sub_standard_code"] == "1-3" and t132["kind"] == "plan" and t132["records"] == []

    assert client.post(f"{API}/cycles/1/forms", headers=ee, json={"template_id": t132["id"], "department_id": 1}).status_code == 403
    r = client.post(f"{API}/cycles/1/forms", headers=coord, json={"template_id": t132["id"], "department_id": 1})
    assert r.status_code == 201, r.text
    f = r.json(); fid = f["id"]
    assert f["status"] == "draft" and f["plan_data"] == {"tasks": []}
    assert client.post(f"{API}/cycles/1/forms", headers=coord, json={"template_id": t132["id"], "department_id": 1}).status_code == 403
    assert client.get(f"{API}/forms/{fid}", headers=ee).status_code == 404

    save = lambda who, **body: client.put(f"{API}/forms/{fid}", headers=who, json=body)
    bad = save(coord, plan_data={"tasks": [{"semester": "الثالث", "task": "x", "target": 1, "owner": "y"}]})
    assert bad.status_code == 422 and "الفصل" in bad.json()["detail"]
    assert save(coord, plan_data={"tasks": [{"task": "x", "target": "عشرة"}]}).status_code == 422

    tr = lambda who, to, **kw: client.post(f"{API}/forms/{fid}/transition", headers=who, json={"to_status": to, **kw})
    r = tr(coord, "submitted")
    assert r.status_code == 403 and "صفاً واحداً" in r.json()["detail"]

    # القيم من ملف 1-3-2: المستهدف 0.6 والمتحقق 0.5 ← 83.3٪، و0.8/0.72 ← 90٪
    plan = {"tasks": [
        {"id": "t1", "semester": "الأول", "week": "الأول", "task": "الفرز الأولي للتسجيل المتوقع", "target": 0.6, "owner": "منسق الجداول"},
        {"id": "t2", "semester": "الأول", "week": "الأول", "task": "مقارنة النتائج بملف التسجيل المتوقع", "target": 0.8, "owner": "منسق الجداول"},
        {"id": "t3", "semester": "الأول", "week": "الثاني", "task": "استقبال طلبات إضافة المقررات", "target": 1}]}
    r = save(coord, plan_data=plan)
    assert r.status_code == 200, r.text
    assert "مسؤول التنفيذ" in tr(coord, "submitted").json()["detail"]
    plan["tasks"][2]["owner"] = "مسجلي القسم"
    follow = {"tasks": {"t1": {"status": "مُنفذ", "achieved": 0.5}, "t2": {"status": "مُنفذ جزئي", "achieved": 0.72}}}
    d = save(coord, plan_data=plan, follow_data=follow).json()
    rows = d["computed"]["tables"]["tasks"]
    assert round(rows[0]["ratio"], 4) == 0.8333 and round(rows[1]["ratio"], 2) == 0.9 and rows[2]["ratio"] is None
    assert d["computed"]["summaries"]["tasks"]["execution_pct"] == 0.75          # (1 + 0.5) ÷ 2 متابَعة
    assert d["summary"]["progress"] == 0.75 and d["missing"] == []

    assert tr(coord, "submitted").status_code == 200
    assert save(coord, follow_data=follow).status_code == 409                       # بانتظار الاعتماد
    assert tr(coord, "approved").status_code == 409
    assert tr(hod, "returned").status_code == 409
    r = tr(hod, "approved")
    assert r.status_code == 200, r.text
    assert r.json()["archive"]["linked_to_requirement"] is True and r.json()["archive"]["version_no"] == 1
    a = next(x for x in client.get(f"{API}/cycles/1/assessments", headers=coord).json() if x["requirement_code"] == "1-3-2")
    assert a["evidence_count"] == 1

    # بعد الاعتماد: التخطيط مقفل والمتابعة مفتوحة
    plan["tasks"][0]["target"] = 0.9
    assert save(coord, plan_data=plan).status_code == 409
    follow["tasks"]["t3"] = {"status": "لم يُنفذ", "obstacles": "تأخر اعتماد الجداول"}
    d = save(coord, follow_data=follow).json()
    assert round(d["computed"]["summaries"]["tasks"]["execution_pct"], 4) == 0.5   # (1 + 0.5 + 0) ÷ 3 = M32 في الملف
    d = save(coord, follow_data={**follow, "improvements": [
        {"recommendation": "ورش عمل لبناء الجداول", "action": "حضور الورش", "owner": "رئيس القسم", "status": "مُنفذ"},
        {"recommendation": "هاكثون تقني", "status": "مُنفذ جزئي"}, {"recommendation": "توصية ثالثة"}]}).json()
    assert round(d["computed"]["improvement_pct"], 4) == 0.5                        # (1 + 0.5 + 0) ÷ 3 = K14 في الملف
    assert save(coord, follow_data={"improvements": [{"status": "مُنفذ"}]}).status_code == 200   # المسودة تقبل النقص

    up = client.post(f"{API}/forms/{fid}/attachments/upload", headers=coord, data={"title_ar": "تقرير رايات"},
                     files={"file": ("rayat.pdf", b"%PDF-1.4 rayat", "application/pdf")})
    assert up.status_code == 201 and up.json()["linked_to_requirement"] is True
    assert client.post(f"{API}/forms/{fid}/archive", headers=coord).json()["version_no"] == 2
    pdf = client.get(f"{API}/forms/{fid}/pdf", headers=hod)
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    assert client.delete(f"{API}/forms/{fid}", headers=coord).status_code == 409

    assert tr(hod, "returned", comment="x").status_code == 409                         # إعادة الفتح للوكيل
    assert tr(dean, "returned", comment="تعديل المستهدف").status_code == 200
    assert save(coord, plan_data=plan).status_code == 200


def test_fixed_rows_and_pivot(client):
    coord = h(client, "coord@ynb")
    tpls = {t["requirement_code"]: t for t in client.get(f"{API}/cycles/1/forms/templates", headers=coord).json()}
    f = client.post(f"{API}/cycles/1/forms", headers=coord, json={"template_id": tpls["1-3-4"]["id"], "department_id": 1}).json()
    assert [r["id"] for r in f["plan_data"]["indicators"]] == ["i1", "i2", "i3", "i4"]
    r = client.put(f"{API}/forms/{f['id']}", headers=coord, json={
        "plan_data": {"indicators": [{"id": "x9"}], "limits": [{"id": "tm", "min": 12, "max": 35}], "source": {"semester": "الأول"}},
        "follow_data": {"ratio": {"am": {"avg": 19.7, "trainers": 30}, "pm": {"avg": 27}}}}).json()
    assert [x["id"] for x in r["plan_data"]["indicators"]] == ["i1", "i2", "i3", "i4"]      # الصفوف الثابتة لا تتغير
    ratio = r["computed"]["tables"]["ratio"]
    assert ratio[0]["rating"] == "متحقق" and ratio[0]["advice"] is None
    assert ratio[1]["rating"] == "غير متحقق" and ratio[1]["advice"].startswith("1. فتح")

    f = client.post(f"{API}/cycles/1/forms", headers=coord, json={"template_id": tpls["1-2-3"]["id"], "department_id": 1}).json()
    r = client.put(f"{API}/forms/{f['id']}", headers=coord, json={"plan_data": {
        "trainers": [{"name": "أ", "specialty": "تقنية الشبكات", "status1": "غير مفرغ وغير مجاز", "load1": 24},
                     {"name": "ب", "specialty": "تقنية الشبكات", "status1": "مفرغ جزئياً", "load1": 14, "assign1": "التدريب الإلكتروني"},
                     {"name": "ج", "specialty": "تقنية الشبكات", "status1": "مفرغ"}],
        "trainees": [{"specialty": "تقنية الشبكات", "n1": 80}]}}).json()
    g = r["computed"]["pivots"]["summary_by_specialty"][0]
    assert g["group"] == "تقنية الشبكات" and g["values"]["avg_load1"] == 19 and g["values"]["ratio1"] == "1 : 27"
    assert round(g["values"]["released1"], 4) == 0.3333 and g["values"]["avg_load2"] is None


def test_complaints_report_matches_official_formulas():
    """1-4-2 بعينة ملف القسم: نسبة الطلبات = (تظلم + شكوى) ÷ المتدربين، والإنجاز = المعالَج منها ÷ عددها."""
    from app.form_templates import TEMPLATES
    from app.forms_engine import clean_follow, clean_plan, compute
    t = next(x for x in TEMPLATES if x["requirement_code"] == "1-4-2")
    assert not t.get("is_provisional")
    p, f = SAMPLES["1-4-2"]
    plan = clean_plan(t["schema"], p)
    r = compute(t["schema"], plan, clean_follow(t["schema"], plan, f))
    piv = {g["group"]: g["values"] for g in r["pivots"]["stats_by_specialty"]}
    assert piv["شبكات"]["complaints1"] == 1 and piv["شبكات"]["suggestions1"] == 1 and piv["شبكات"]["rate1"] == 1 / 40
    assert piv["شبكات"]["done1"] == 1 and piv["شبكات"]["appeals2"] == 1 and piv["شبكات"]["done2"] == 0
    assert piv["الدعم الفني"]["rate1"] == 0 and piv["الدعم الفني"]["done1"] is None
    assert piv["برمجيات"]["rate1"] is None                                       # لا عدد متدربين مُدخل للتخصص
    sm = r["summaries"]["requests"]
    assert sm["appeals1"] == 1 and sm["complaints1"] == 1 and sm["suggestions1"] == 3
    assert sm["rate1"] == 2 / 60 and sm["done1"] == 1 and sm["done2"] == 0 and r["progress"] == 2 / 3


SAMPLES = {
    "1-1-2": ({"rows": [{"id": "a", "initiative": "م", "kpi": "ك", "t1": 0.2, "t2": 0.2, "owner": "ر"},
                        {"id": "b", "initiative": "م2", "kpi": "ك", "t1": 0.65, "owner": "ر"}]},
              {"rows": {"a": {"a1": 0.22, "status": "مُنفذ"}, "b": {"a1": 0.08, "a2": 0.3, "status": "مُنفذ جزئي"}}}),
    "1-2-2": ({"rows": [{"id": "a", "goal": "ه", "kpi": "ك", "t1": 100, "t2": 100, "owner": "ر"}],
               "evaluations": [{"id": "e", "name": "م"}, {"id": "f", "name": "ن"}]},
              {"rows": {"a": {"a1": 90, "a2": 80, "status": "مُنفذ"}},
               "evaluations": {"e": {"score1": 98, "v11": "نعم", "v12": "لا"}, "f": {"score1": 91, "score2": 95, "v11": "نعم"}}}),
    "1-3-3": ({"specialties": [{"id": "s", "specialty": "تقنية الشبكات", "prev": 70, "cap1": 60, "app1": 200, "adm1": 80},
                               {"id": "t", "specialty": "الدعم الفني", "prev": 30, "cap1": 20, "app1": 50, "adm1": 20}]},
              {"specialties": {"s": {"cap2": 60, "app2": 150, "adm2": 70}}}),
    "1-4-1": ({"tasks": [{"id": "a", "semester": "الأول", "task": "قناة تليجرام", "target": "المتدربين", "owner": "الفريق الإعلامي"}]},
              {"tasks": {"a": {"status": "مُنفذ", "achieved": "متحقق"}}}),
    "1-4-2": ({"trainees": [{"id": "n", "specialty": "شبكات", "n1": 40, "n2": 38}, {"id": "d", "specialty": "الدعم الفني", "n1": 20}]},
              {"requests": [
                  {"semester": "الأول", "trainee_name": "أ", "specialty": "شبكات", "type": "مقترح", "state": "لم يتم"},
                  {"semester": "الأول", "trainee_name": "ب", "specialty": "الدعم الفني", "type": "مقترح", "state": "لم يتم"},
                  {"semester": "الأول", "trainee_name": "ج", "specialty": "الدعم الفني", "type": "مقترح", "state": "تم"},
                  {"semester": "الأول", "trainee_name": "د", "specialty": "برمجيات", "type": "تظلم", "state": "تم"},
                  {"semester": "الأول", "trainee_name": "أ", "specialty": "شبكات", "type": "شكوى", "state": "تم"},
                  {"semester": "الثاني", "trainee_name": "هـ", "specialty": "شبكات", "type": "تظلم"}]}),
    "2-1-3": ({}, {"trainees": [
        {"specialty": "شبكات", "name": "أ", "advisor": "م1", "status": "منتظم", "cgpa": 3.2, "sgpa": 3.5, "units_required": 70, "units_earned": 40},
        {"specialty": "شبكات", "name": "ب", "advisor": "م1", "status": "منذر أكاديمياً", "cgpa": 1.8, "units_required": 70},
        {"specialty": "برمجة", "name": "ج", "advisor": "م2", "status": "متعثر", "cgpa": 2.1, "sgpa": 1.9}]}),
    "2-2-1": ({}, {"traits_test": [{"specialty": "شبكات", "target1": 15, "present1": 12, "traits1": 70, "gpa_pct1": 78, "spec1": 65}],
                   "specialty_test": [{"specialty": "شبكات", "target1": 15, "present1": 0, "target2": 20, "present2": 18}]}),
    "2-2-2": ({}, {"courses": [
        {"semester": "الأول", "exam": "الفصلي الأول", "specialty": "برمجة", "course": "برمجة الإنترنت", "registered": 22, "below60": 1, "absent": 0, "deprived": 2},
        {"semester": "الأول", "exam": "الفصلي الأول", "specialty": "شبكات", "course": "ربط الشبكات", "registered": 25, "below60": 9, "absent": 0, "deprived": 0}]}),
    "2-2-5": ({}, {"trainees": [{"name": "أ", "specialty": "برمجة", "committee": 60, "entity": 40},
                                {"name": "ب", "specialty": "برمجة", "committee": 55, "entity": 39},
                                {"name": "ج", "specialty": "شبكات", "p_committee": "ممتاز", "p_external": "لا"}]}),
    "2-2-6": ({}, {"trainees": [{"name": "أ", "specialty": "شبكات", "field": "في غير مجال التخصص", "support": "الدعم والتوجيه"}]}),
    "2-2-10": ({}, {"projects": [{"name": "أ", "specialty": "وسائط", "title": "حملة توعوية", "result": "ناجح", "external": "لا"},
                                 {"name": "ب", "specialty": "وسائط", "title": "التمور", "result": "ناجح", "external": "نعم"},
                                 {"name": "ج", "specialty": "برمجة", "title": "تطبيق", "result": "راسب"}]}),
    "3-2-5": ({}, {"courses": [{"specialty": "شبكات", "course": "م1", "meeting1": "تم", "aligned1": "نعم", "committed1": "نعم", "exam1": "لا",
                                "meeting2": "لم يتم"}]}),
    "4-1-3": ({}, {"trainers": [{"name": "أ", "file1": "مكتمل", "lms1": "جزئي", "att1": "مكتمل", "grades1": "مكتمل"},
                                {"name": "ب", "file1": "لا يوجد", "att1": "مكتمل", "grades1": "لم يتم"}]}),
    "4-2-2": ({}, {"requests": [{"semester": "الأول", "specialty": "ش", "type": "تجهيزات تدريبية", "item": "موجه", "status": "مُنفذ"},
                                {"semester": "الأول", "specialty": "ش", "type": "أخرى", "item": "كابلات", "status": "مُنفذ جزئي"}]}),
    "4-3-1": ({}, {"weeks": [{"semester": "الأول", "week": "الأول", "trainers": 20, "trainers_present": 19, "trainees": 400,
                              "trainees_present": 360, "sections": 50, "sections_done": 50},
                             {"semester": "الأول", "week": "الثاني", "trainers": 20, "trainers_present": 20, "trainees": 400,
                              "trainees_present": 380, "sections": 50, "sections_done": 48}]}),
}


def test_standard3_4_formulas():
    from app.form_templates import TEMPLATES
    from app.forms_engine import clean_follow, clean_plan, compute
    def run(code):
        t = next(x for x in TEMPLATES if x["requirement_code"] == code)
        p, f = SAMPLES[code]
        plan = clean_plan(t["schema"], p)
        return compute(t["schema"], plan, clean_follow(t["schema"], plan, f))
    sm = run("3-2-5")["summaries"]["courses"]
    assert sm["meetings"] == 0.5 and round(sm["integration"], 4) == 0.6667
    sm = run("4-1-3")["summaries"]["trainers"]
    assert sm["files"] == 0.5 and sm["lms"] == 0 and sm["rayat"] == 0.75
    r = run("4-2-2")
    assert r["summaries"]["requests"]["execution_pct"] == 0.75 and r["progress"] == 0.75
    r = run("4-3-1")
    assert r["tables"]["weeks"][0]["trainers_pct"] == 0.95 and r["summaries"]["weeks"]["trainees_pct"] == 740 / 800
    assert r["summaries"]["weeks"]["sections_pct"] == 0.98


def test_standard2_formulas_match_excel():
    """قيم من ملفات المعيار الثاني: 1 أقل من 60٪ من 22 مسجلاً، والنتيجة النهائية للتعاوني = اللجنة + جهة التدريب."""
    from app.form_templates import TEMPLATES
    from app.forms_engine import clean_follow, clean_plan, compute
    def run(code):
        t = next(x for x in TEMPLATES if x["requirement_code"] == code)
        p, f = SAMPLES[code]
        plan = clean_plan(t["schema"], p)
        return compute(t["schema"], plan, clean_follow(t["schema"], plan, f))
    r = run("2-2-2")
    c = r["tables"]["courses"]
    assert round(c[0]["below60_pct"], 3) == 0.045 and round(c[0]["deprived_pct"], 3) == 0.091 and round(c[1]["below60_pct"], 2) == 0.36
    assert r["summaries"]["courses"]["below60_pct"] == 10 / 47
    r = run("2-2-5")
    assert [x["final"] for x in r["tables"]["trainees"]] == [100, 94, None] and r["summaries"]["trainees"]["avg_final"] == 97
    r = run("2-1-3")
    assert r["tables"]["trainees"][0]["units_left"] == 30 and r["tables"]["trainees"][1]["units_left"] is None
    adv = {g["group"]: g["values"] for g in r["pivots"]["by_advisor"]}
    assert adv["م1"]["warned"] == 1 and round(adv["م1"]["avg_cgpa"], 2) == 2.5 and adv["م2"]["struggling"] == 1
    r = run("2-2-1")
    t = r["tables"]["traits_test"][0]
    assert t["attend1"] == 0.8 and t["gap1"] == 13 and r["tables"]["specialty_test"][0]["attend1"] == 0
    r = run("2-2-10")
    assert round(r["summaries"]["projects"]["pass"], 4) == 0.6667 and r["summaries"]["projects"]["external"] == 0.5


@pytest.mark.skipif(shutil.which("node") is None, reason="node غير متوفر")
def test_js_calculator_matches_python():
    """formcalc.js (الواجهة) وforms_engine.py (الخادم وPDF) يعطيان النتائج نفسها لكل القوالب."""
    from app.form_templates import TEMPLATES
    from app.forms_engine import clean_follow, clean_plan, compute

    cases = []
    for t in TEMPLATES:
        p, f = SAMPLES.get(t["requirement_code"], ({}, {}))
        plan = clean_plan(t["schema"], p)
        follow = clean_follow(t["schema"], plan, f)
        cases.append({"code": t["requirement_code"], "schema": t["schema"], "plan": plan, "follow": follow,
                      "py": compute(t["schema"], plan, follow)})
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "cases.json").write_text(json.dumps(cases, ensure_ascii=False), encoding="utf-8")
        script = Path(d) / "run.mjs"
        script.write_text(
            f"import {{ compute }} from {json.dumps((ROOT / 'frontend/js/formcalc.js').as_uri())};\n"
            "import {{ readFileSync }} from 'node:fs';\n".replace("{{", "{").replace("}}", "}")
            + f"const cases = JSON.parse(readFileSync({json.dumps(str(Path(d) / 'cases.json'))}, 'utf8'));\n"
            "console.log(JSON.stringify(cases.map(c => compute(c.schema, c.plan, c.follow))));\n", encoding="utf-8")
        out = subprocess.run(["node", str(script)], capture_output=True, text=True, check=True).stdout
    js = json.loads(out)

    def norm(v):
        if isinstance(v, float):
            return round(v, 9)
        if isinstance(v, dict):
            return {k: norm(x) for k, x in v.items()}
        if isinstance(v, list):
            return [norm(x) for x in v]
        return v
    for c, j in zip(cases, js):
        assert norm(j) == norm(c["py"]), c["code"]
