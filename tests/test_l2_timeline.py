"""الخط الزمني للمستوى الثاني: تحميل الخطة والتقويم، الصلاحيات، تأشير الإنجاز وربط الشاهد بالتقدير، المسؤول."""
import os
import tempfile
from datetime import date
from pathlib import Path

import psycopg
import pytest

from app.routers.l2_timeline import CALENDAR_1448, PLAN_1447, build_weeks, locate

ADMIN_URL = os.environ.get("AQAP_TEST_ADMIN_URL", "postgresql://aqap:aqap@localhost:5432/postgres")
DB = "aqap_l2_timeline_test"
API = "/api/v1"
URL = "https://tvtc-my.sharepoint.com/personal/q/Documents/minutes.pdf"

SEED = """
SET search_path = aqap;
INSERT INTO import_requirement_staging VALUES
 ('1','القيادة الإدارية',1,'1-1','التوجيه التشغيلي',1,'1-1-1','محاضر اجتماعات أعضاء القسم لمناقشة المبادرات التنفيذية',1,'department',true,0),
 ('1','القيادة الإدارية',1,'1-1','التوجيه التشغيلي',1,'1-1-2','خطة المبادرات التنفيذية للقسم',2,'department',true,0),
 ('4','التدريب والموارد المساندة',4,'4-3','إدارة العملية التدريبية',3,'4-3-1','تقرير قياس سير العملية التدريبية',1,'department',true,0),
 ('6','الاستدامة',6,'6-3','إدارة المخاطر',3,'6-3-1','تقرير تحليل المخاطر',1,'department',true,0);
SELECT import_framework_from_staging('TVTC-TQ-L2');
INSERT INTO institution(code, name_ar) VALUES ('YNB', 'الكلية التقنية التطبيقية بينبع');
INSERT INTO department(institution_id, code, name_ar) VALUES (1,'CS','تقنية الحاسب'), (1,'EE','التقنية الكهربائية');
INSERT INTO app_user(institution_id, email, full_name_ar) VALUES
 (1,'coord@ynb','منسق الحاسب'), (1,'dean@ynb','وكيل الجودة'), (1,'coord.ee@ynb','منسق الكهرباء'), (1,'aud@ynb','مدقق');
INSERT INTO user_role(user_id, role, department_id) VALUES
 (1,'dept_coordinator',1), (2,'quality_dean',NULL), (3,'dept_coordinator',2), (4,'quality_auditor',NULL);
INSERT INTO assessment_cycle(institution_id, framework_id, title_ar, academic_year, starts_on, ends_on, status)
 VALUES (1,1,'دورة 1448','1448','2026-08-23','2027-06-24','open');
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
        c.execute((Path(__file__).parents[1] / "db" / "schema.sql").read_text(encoding="utf-8"))
        c.execute(SEED)
    os.environ.update({"AQAP_DATABASE_URL": url, "AQAP_STORAGE_BACKEND": "local", "AQAP_ENV": "test",
                       "AQAP_LOCAL_STORAGE_DIR": tempfile.mkdtemp(prefix="aqap-l2-"), "AQAP_JWT_SECRET": "test-secret"})
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


def test_plan_and_calendar_constants():
    assert len(PLAN_1447) == 48
    s1 = build_weeks(CALENDAR_1448[1]["start"], CALENDAR_1448[1]["breaks"])
    assert s1[0] == date(2026, 8, 23) and s1[10] == date(2026, 11, 1)        # الأسبوع 11
    assert s1[13] == date(2026, 11, 29)                                       # الأسبوع 14 بعد إجازة الخريف
    assert s1[17] == date(2026, 12, 27)                                       # بداية الاختبارات (الأسبوع 18)
    s2 = build_weeks(CALENDAR_1448[2]["start"], CALENDAR_1448[2]["breaks"])
    assert s2[6] == date(2027, 3, 14) and s2[14] == date(2027, 5, 23) and s2[17] == date(2027, 6, 13)
    weeks = [{"semester": 1, "week_no": i + 1, "starts_on": d} for i, d in enumerate(s1)]
    assert locate(weeks, date(2026, 11, 4)) == {"semester": 1, "week_no": 11, "in_break": False}
    assert locate(weeks, date(2026, 11, 24)) == {"semester": 1, "week_no": 13, "in_break": True}


def test_timeline_flow(client):
    coord, dean, ee, aud = (h(client, e) for e in ("coord@ynb", "dean@ynb", "coord.ee@ynb", "aud@ynb"))

    # مهمة أعمال جودة محمّلة قبل التصحيح: الأسبوع 14 محسوب متتالياً (الخميس 26 نوفمبر) متجاهلاً إجازة الخريف
    url = ADMIN_URL.rsplit("/", 1)[0] + f"/{DB}"
    with psycopg.connect(url, autocommit=True) as c:
        c.execute("""INSERT INTO aqap.quality_task (cycle_id, week_no, title_ar, due_on, sort_order)
                     VALUES (1, 14, 'تقرير جاهزية القسم لبدء الاختبارات النهائية', '2026-11-26', 0),
                            (1, 6, 'التقرير الشهري الأول لتفعيل منصة المهارات العملية', '2026-09-29', 1)""")

    assert client.post(f"{API}/cycles/1/l2-timeline/seed", headers=coord, json={}).status_code == 403
    r = client.post(f"{API}/cycles/1/l2-timeline/seed", headers=dean, json={})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["quality_tasks_realigned"] == 1
    with psycopg.connect(url) as c:
        due = dict(c.execute("SELECT week_no, due_on FROM aqap.quality_task WHERE cycle_id = 1").fetchall())
    assert due == {14: date(2026, 12, 3), 6: date(2026, 9, 29)}     # الأسبوع 14 بعد الإجازة، والأسبوع 6 لم يتغير
    assert body["requirements"] == 4 and len(body["missing"]) == 44
    assert body["occurrences"] == 1 + 5 + 16 + 2          # 1-1-1، 1-1-2، 4-3-1 أسبوعي، 6-3-1 (مستمر + الفصل الثاني)
    assert client.post(f"{API}/cycles/1/l2-timeline/seed", headers=dean, json={}).status_code == 403

    data = client.get(f"{API}/cycles/1/l2-timeline", headers=coord).json()
    assert [d["name_ar"] for d in data["departments"]] == ["تقنية الحاسب"]
    assert len(data["weeks"]) == 38 and data["can_edit"] is False
    codes = [r["code"] for r in data["requirements"]]
    assert codes == ["1-1-1", "1-1-2", "4-3-1", "6-3-1"]
    r611 = next(r for r in data["requirements"] if r["code"] == "6-3-1")
    assert any(o["week_no"] is None and o["label_ar"] == "مستمر" for o in r611["occurrences"])
    occ = next(r for r in data["requirements"] if r["code"] == "1-1-1")["occurrences"][0]
    assert (occ["semester"], occ["week_no"]) == (1, 3)

    # منسق قسم آخر لا يؤشّر للحاسب، والمدقق لا يؤشّر
    assert client.post(f"{API}/l2-timeline/{occ['id']}/progress", headers=ee, json={"department_id": 1, "url": URL}).status_code == 403
    assert client.post(f"{API}/l2-timeline/{occ['id']}/progress", headers=aud, json={"department_id": 1, "url": URL}).status_code == 403
    assert client.post(f"{API}/l2-timeline/{occ['id']}/progress", headers=coord, json={"department_id": 1}).status_code == 403

    r = client.post(f"{API}/l2-timeline/{occ['id']}/progress", headers=coord, json={"department_id": 1, "url": URL, "note_ar": "محضر 1"})
    assert r.status_code == 200 and r.json() == {"status": "done", "linked": True}
    # الشاهد انعكس على تقدير القسم للمتطلب
    cs = client.get(f"{API}/cycles/1/assessments", headers=coord).json()
    a = next(x for x in cs if x["requirement_code"] == "1-1-1")
    ev = client.get(f"{API}/assessments/{a['id']}", headers=coord).json()
    assert any(e["url"] == URL for e in ev["evidence"])

    data = client.get(f"{API}/cycles/1/l2-timeline", headers=dean).json()
    o = next(r for r in data["requirements"] if r["code"] == "1-1-1")["occurrences"][0]
    assert o["progress"]["1"]["status"] == "done" and o["progress"]["1"]["url"] == URL and "2" not in o["progress"]

    # لا ينطبق يتطلب سبباً
    o2 = next(r for r in data["requirements"] if r["code"] == "1-1-2")["occurrences"][0]
    assert client.post(f"{API}/l2-timeline/{o2['id']}/progress", headers=ee, json={"department_id": 2, "not_applicable": True}).status_code == 403
    r = client.post(f"{API}/l2-timeline/{o2['id']}/progress", headers=ee, json={"department_id": 2, "not_applicable": True, "note_ar": "لا ينطبق"})
    assert r.json()["status"] == "na"

    # إلغاء التأشير
    assert client.delete(f"{API}/l2-timeline/{o2['id']}/progress?department_id=2", headers=ee).status_code == 200
    assert client.delete(f"{API}/l2-timeline/{o2['id']}/progress?department_id=2", headers=ee).status_code == 404

    # المسؤول
    assert client.put(f"{API}/cycles/1/l2-timeline/planner", headers=ee,
                      json={"requirement_code": "1-1-1", "department_id": 1, "owner_name_ar": "أ. خالد"}).status_code == 403
    r = client.put(f"{API}/cycles/1/l2-timeline/planner", headers=coord,
                   json={"requirement_code": "1-1-1", "department_id": 1, "owner_name_ar": " أ. خالد "})
    assert r.status_code == 200 and r.json()["owner_name_ar"] == "أ. خالد"
    data = client.get(f"{API}/cycles/1/l2-timeline", headers=coord).json()
    assert next(r for r in data["requirements"] if r["code"] == "1-1-1")["planners"] == {"1": "أ. خالد"}
    client.put(f"{API}/cycles/1/l2-timeline/planner", headers=coord, json={"requirement_code": "1-1-1", "department_id": 1, "owner_name_ar": ""})
    data = client.get(f"{API}/cycles/1/l2-timeline", headers=coord).json()
    assert next(r for r in data["requirements"] if r["code"] == "1-1-1")["planners"] == {}

    # إعادة التحميل بتاريخ مخصص تحذف المواعيد وما أُنجز
    r = client.post(f"{API}/cycles/1/l2-timeline/seed", headers=dean, json={"replace": True, "semester1_start": "2026-08-26"})
    assert r.status_code == 201
    data = client.get(f"{API}/cycles/1/l2-timeline", headers=dean).json()
    assert data["weeks"][0]["starts_on"] == "2026-08-23"
    assert all(not o["progress"] for r in data["requirements"] for o in r["occurrences"])


def test_quality_tasks_follow_training_weeks(client):
    dean = h(client, "dean@ynb")
    # بلا تقويم محمّل للدورة: تُستخدم أسابيع التقويم المعتمد 1448هـ
    with psycopg.connect(ADMIN_URL.rsplit("/", 1)[0] + f"/{DB}", autocommit=True) as c:
        c.execute("DELETE FROM aqap.quality_task WHERE cycle_id = 1; DELETE FROM aqap.training_week WHERE cycle_id = 1")
    r = client.post(f"{API}/cycles/1/quality-tasks/seed", headers=dean, json={"semester_start": "2026-08-23"})
    assert r.status_code == 201, r.text
    tasks = client.get(f"{API}/cycles/1/quality-tasks", headers=dean).json()
    tasks = tasks.get("tasks", tasks) if isinstance(tasks, dict) else tasks
    due = {}
    for t in tasks:
        due.setdefault(t["week_no"], set()).add(t["due_on"])
    assert due[13] == {"2026-11-18"}                                   # قبل إجازة الخريف: الأربعاء كما هو
    assert due[14] == {"2026-12-01", "2026-12-03"}                     # بعد الإجازة: الأسبوع 14 يبدأ 29 نوفمبر
    assert due[19] == {"2027-01-07"}                                   # آخر أيام الاختبارات النهائية


def test_calendar_shows_quality_tasks_and_timeline(client):
    dean, coord = h(client, "dean@ynb"), h(client, "coord@ynb")
    client.post(f"{API}/cycles/1/l2-timeline/seed", headers=dean, json={"replace": True})
    data = client.get(f"{API}/cycles/1/calendar", headers=dean).json()
    feeds = data["feeds"]
    q = [f for f in feeds if f["source"] == "quality"]
    l2 = [f for f in feeds if f["source"] == "l2"]
    assert q and l2 and data["deadlines"] == []
    assert not any("أنماط" in f["title"] for f in q)                   # أنماط التدريب غير معتمدة: لا تظهر
    wk3 = next(f for f in l2 if f["code"] == "1-1-1")
    assert wk3["due_on"] == "2026-09-10" and wk3["total"] == 2 and wk3["done"] == 0   # خميس الأسبوع 3
    assert all(f["code"] != "6-3-1" or f["week_no"] for f in l2)         # المواعيد بلا أسبوع لا تظهر في التقويم

    # تأشير القسم ينعكس على الإنجاز، والمنسق يرى قسمه فقط
    client.post(f"{API}/l2-timeline/{wk3['id']}/progress", headers=coord,
                json={"department_id": 1, "url": URL})
    mine = next(f for f in client.get(f"{API}/cycles/1/calendar", headers=coord).json()["feeds"]
                if f["source"] == "l2" and f["id"] == wk3["id"])
    assert (mine["done"], mine["total"], mine["status"]) == (1, 1, "done")
    alld = next(f for f in client.get(f"{API}/cycles/1/calendar", headers=dean).json()["feeds"]
                if f["source"] == "l2" and f["id"] == wk3["id"])
    assert (alld["done"], alld["total"], alld["status"]) == (1, 2, "overdue")
