"""التقارير الدورية: تقويم 1448هـ، حالة بنود الأقسام من نماذجها، وتأشير البنود الأخرى وصلاحياتها."""
import os
import tempfile
from collections import Counter
from pathlib import Path

import psycopg
import pytest

from app.form_templates import TEMPLATES
from app.periodic_catalog import BY_KEY, CATALOG_1448

ADMIN_URL = os.environ.get("AQAP_TEST_ADMIN_URL", "postgresql://aqap:aqap@localhost:5432/postgres")
DB = "aqap_periodic_test"
API = "/api/v1"
URL = "https://tvtc-my.sharepoint.com/personal/q/Documents/culture.pdf"

SEED = """
SET search_path = aqap;
INSERT INTO import_requirement_staging VALUES
 ('1','القيادة الإدارية',1,'1-1','التوجيه التشغيلي',1,'1-1-1','متطلب 1-1-1',1,'department',true,0);
SELECT import_framework_from_staging('TVTC-TQ-L2');
INSERT INTO institution(code, name_ar) VALUES ('YNB', 'الكلية التقنية التطبيقية بينبع');
INSERT INTO department(institution_id, code, name_ar) VALUES (1,'CS','تقنية الحاسب'), (1,'EE','التقنية الكهربائية');
INSERT INTO app_user(institution_id, email, full_name_ar) VALUES
 (1,'coord@ynb','منسق الحاسب'), (1,'dean@ynb','وكيل الجودة'), (1,'coord.ee@ynb','منسق الكهرباء'), (1,'fac@ynb','مدرب');
INSERT INTO user_role(user_id, role, department_id) VALUES
 (1,'dept_coordinator',1), (2,'quality_dean',NULL), (3,'dept_coordinator',2), (4,'faculty',1);
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
                       "AQAP_LOCAL_STORAGE_DIR": tempfile.mkdtemp(prefix="aqap-pr-"), "AQAP_JWT_SECRET": "test-secret"})
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


def test_catalog_is_consistent():
    keys = [i.key for i in CATALOG_1448]
    assert len(keys) == len(set(keys)) and len(keys) > 100
    codes = {t["requirement_code"] for t in TEMPLATES}
    from app.college_reports import BY_KEY as REPORTS
    for i in CATALOG_1448:
        assert i.scope in ("dept", "college") and 0 <= i.week <= 19
        assert i.form is None or i.form in codes, i.key
        assert i.college is None or i.college in REPORTS, i.key
        if i.college and REPORTS[i.college]["filter"] and i.filter:
            assert i.filter in REPORTS[i.college]["filter"][1], i.key
    # الجاهزية في الأسبوع الخامس من الفصلين، والنهائية في الرابع عشر/الخامس عشر
    ready = [(i.semester, i.week, i.filter) for i in CATALOG_1448 if i.form == "3-1/جاهزية"]
    assert (1, 5, "الفصلي الأول") in ready and (2, 5, "الفصلي الأول") in ready and (1, 14, "النهائي") in ready
    assert Counter(i.semester for i in CATALOG_1448)[2] > 40


def test_week_dates_and_readiness_from_department_form(client):
    coord, dean = h(client, "coord@ynb"), h(client, "dean@ynb")
    d = client.get(f"{API}/cycles/1/periodic", headers=dean).json()
    assert d["can_manage"] and len(d["departments"]) == 2
    w = {(x["semester"], x["week_no"]): x for x in d["weeks"]}
    assert w[(1, 5)]["starts_on"] == "2026-09-20" and w[(1, 5)]["ends_on"] == "2026-09-22" and w[(1, 5)]["days"].startswith("الأحد")
    assert w[(2, 6)]["starts_on"] == "2027-02-23"
    assert w[(1, 14)]["starts_on"] == "2026-11-29" and w[(2, 1)]["starts_on"] == "2027-01-17"
    item = next(i for i in d["items"] if i["key"] == "1-05-a")
    assert item["scope"] == "dept" and item["college_key"] == "exam_readiness" and item["starts_on"] == "2026-09-20"
    assert item["form"]["departments"]["1"]["state"] == "none"

    # القسم يعبّئ صفه في نموذج الجاهزية → البند منجز له وحده، ويظهر في تقرير الكلية المجمّع
    tpl = item["form"]["template_id"]
    f = client.post(f"{API}/cycles/1/forms", headers=coord, json={"template_id": tpl, "department_id": 1}).json()
    started = client.get(f"{API}/cycles/1/periodic", headers=coord).json()
    assert len(started["departments"]) == 1
    assert next(i for i in started["items"] if i["key"] == "1-05-a")["form"]["departments"]["1"]["state"] == "started"
    row = {"semester": "الأول", "exam": "الفصلي الأول", "notify": "نعم", "courses": 12, "aligned": "نعم", "materials": "نعم", "halls": "نعم"}
    assert client.put(f"{API}/forms/{f['id']}", headers=coord, json={"follow_data": {"exams": [row]}}).status_code == 200
    d = client.get(f"{API}/cycles/1/periodic", headers=dean).json()
    by = {i["key"]: i for i in d["items"]}
    assert by["1-05-a"]["form"]["departments"]["1"]["state"] == "filled"
    assert by["1-05-a"]["form"]["departments"]["2"]["state"] == "none"
    assert by["2-05-c"]["form"]["departments"]["1"]["state"] == "started"     # صف الفصل الأول لا يُحسب للفصل الثاني
    assert by["1-11-a"]["form"]["departments"]["1"]["state"] == "started"     # الفترة الثانية لم تُعبّأ
    rep = client.get(f"{API}/cycles/1/college-reports/exam_readiness?f=الفصلي الأول", headers=dean).json()
    assert rep["rows"][0]["courses"] == 12

    # بند مرتبط بتقرير مجمّع لا يُؤشَّر يدوياً
    r = client.post(f"{API}/cycles/1/periodic/1-05-a/progress", headers=coord, json={"department_id": 1, "url": URL})
    assert r.status_code == 403


def test_marking_permissions(client):
    coord, dean, other, fac = (h(client, e) for e in ("coord@ynb", "dean@ynb", "coord.ee@ynb", "fac@ynb"))
    p = f"{API}/cycles/1/periodic"
    # بند الكلية: لوكيل الجودة فقط وبلا قسم
    assert client.post(f"{p}/1-08-a/progress", headers=coord, json={"url": URL}).status_code == 403
    assert client.post(f"{p}/1-08-a/progress", headers=dean, json={"department_id": 1, "url": URL}).status_code == 403
    r = client.post(f"{p}/1-08-a/progress", headers=dean, json={"url": URL, "note_ar": "نُشر"})
    assert r.status_code == 200 and r.json()["status"] == "done"
    # بند القسم بلا نموذج: منسق القسم لقسمه فقط، والمدرب لا يؤشّر
    assert client.post(f"{p}/1-05-b/progress", headers=other, json={"department_id": 1, "url": URL}).status_code == 403
    assert client.post(f"{p}/1-05-b/progress", headers=fac, json={"department_id": 1, "url": URL}).status_code == 403
    assert client.post(f"{p}/1-05-b/progress", headers=coord, json={"department_id": 1, "not_applicable": True}).status_code == 403
    assert client.post(f"{p}/1-05-b/progress", headers=coord, json={"department_id": 1, "url": URL}).status_code == 200
    assert client.post(f"{p}/1-05-b/progress", headers=coord,
                       json={"department_id": 1, "not_applicable": True, "note_ar": "لا مقررات محدثة"}).json()["status"] == "na"
    assert client.post(f"{p}/nope/progress", headers=dean, json={"url": URL}).status_code == 404
    d = client.get(p, headers=coord).json()
    by = {i["key"]: i for i in d["items"]}
    assert not d["can_manage"] and {i["scope"] for i in d["items"]} == {"dept"}     # القسم يرى بنوده فقط
    assert by["1-05-b"]["marks"]["1"]["status"] == "na" and "1-08-a" not in by
    dean_items = {i["key"]: i for i in client.get(p, headers=dean).json()["items"]}
    assert dean_items["1-08-a"]["marks"]["0"]["url"] == URL and dean_items["1-05-b"]["scope"] == "dept"
    assert "2" not in by["1-05-b"]["marks"]
    assert client.delete(f"{p}/1-05-b/progress?department_id=1", headers=coord).status_code == 200
    assert client.delete(f"{p}/1-05-b/progress?department_id=1", headers=coord).status_code == 404
    assert BY_KEY["1-00-a"].preset_done
