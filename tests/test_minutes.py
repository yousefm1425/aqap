"""وحدة المحاضر: إنشاء من النموذج، تحرير، رفع، إعادة، اعتماد وأرشفة PDF مربوط بالمتطلب، متابعة التوصيات، الحضور."""
import os
import tempfile
from pathlib import Path

import psycopg
import pytest

ADMIN_URL = os.environ.get("AQAP_TEST_ADMIN_URL", "postgresql://aqap:aqap@localhost:5432/postgres")
DB = "aqap_minutes_test"
API = "/api/v1"

SEED = """
SET search_path = aqap;
INSERT INTO import_requirement_staging VALUES
 ('1','القيادة الإدارية',1,'1-1','التوجه التشغيلي',1,'1-1-1','محاضر اجتماعات أعضاء القسم لمناقشة المبادرات التنفيذية للقسم',1,'department',true,0),
 ('1','القيادة الإدارية',1,'1-1','التوجه التشغيلي',1,'1-1-2','خطة المبادرات التنفيذية للقسم',2,'department',true,0);
SELECT import_framework_from_staging('TVTC-TQ-L2');
INSERT INTO institution(code, name_ar) VALUES ('YNB', 'الكلية التقنية التطبيقية بينبع');
INSERT INTO department(institution_id, code, name_ar) VALUES (1,'CS','تقنية الحاسب'), (1,'EE','التقنية الكهربائية');
INSERT INTO app_user(institution_id, email, full_name_ar) VALUES
 (1,'coord@ynb','منسق الحاسب'), (1,'hod@ynb','رئيس قسم الحاسب'), (1,'fac@ynb','مدرب الحاسب'),
 (1,'dean@ynb','وكيل الجودة'), (1,'coord.ee@ynb','منسق الكهرباء');
INSERT INTO user_role(user_id, role, department_id) VALUES
 (1,'dept_coordinator',1), (2,'hod',1), (3,'faculty',1), (4,'quality_dean',NULL), (5,'dept_coordinator',2);
INSERT INTO assessment_cycle(institution_id, framework_id, title_ar, academic_year, starts_on, ends_on, status)
 VALUES (1,1,'دورة 1447','1447','2026-09-01','2027-05-31','open');
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
                       "AQAP_LOCAL_STORAGE_DIR": tempfile.mkdtemp(prefix="aqap-min-"), "AQAP_JWT_SECRET": "test-secret"})
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


def test_minutes_lifecycle(client):
    coord, hod, fac, dean, ee = (h(client, e) for e in ("coord@ynb", "hod@ynb", "fac@ynb", "dean@ynb", "coord.ee@ynb"))

    tpls = client.get(f"{API}/cycles/1/minutes/templates", headers=coord).json()
    assert len(tpls) == 13
    t111 = next(t for t in tpls if t["requirement_code"] == "1-1-1")
    assert t111["requirement_id"] and len(t111["suggested_agenda"]) == 3

    assert client.post(f"{API}/cycles/1/minutes", headers=ee, json={"template_id": t111["id"], "department_id": 1}).status_code == 403
    r = client.post(f"{API}/cycles/1/minutes", headers=coord, json={"template_id": t111["id"], "department_id": 1})
    assert r.status_code == 201, r.text
    m = r.json()
    mid = m["id"]
    assert m["meeting_no"] == 1 and m["status"] == "draft" and len(m["agenda"]) == 3
    assert [a["role_ar"] for a in m["attendees"]][0] == "رئيس القسم" and len(m["attendees"]) == 3
    assert client.get(f"{API}/minutes/{mid}", headers=ee).status_code == 404

    tr = lambda who, to, **kw: client.post(f"{API}/minutes/{mid}/transition", headers=who, json={"to_status": to, **kw})
    r = tr(coord, "submitted")
    assert r.status_code == 409 and "تاريخ الاجتماع" in r.json()["detail"]

    doc = {"title_ar": m["title_ar"], "semester": "الأول", "meeting_date": "2026-09-23", "start_time": "10:00 ص",
           "location_ar": "قاعة القسم", "follow_up_owner": "رئيس القسم",
           "agenda": [{"title_ar": "مراجعة المبادرات", "recommendations": [
                          {"text_ar": "حصر المبادرات المعتمدة", "responsible_ar": "رئيس القسم", "period_ar": "الأسبوع الأول"},
                          {"text_ar": "إعداد خطة التنفيذ", "responsible_ar": "منسق الجودة", "period_ar": "الأسبوع الثالث"}]},
                      {"title_ar": "توزيع المسؤوليات", "recommendations": []}],
           "attendees": [{"name_ar": a["name_ar"], "role_ar": a["role_ar"], "user_id": a["user_id"]} for a in m["attendees"]]}
    assert client.put(f"{API}/minutes/{mid}", headers=coord, json=doc).status_code == 200
    r = tr(coord, "submitted")
    assert r.status_code == 409 and "توصية واحدة" in r.json()["detail"]
    doc["agenda"][1]["recommendations"] = [{"text_ar": "تكليف مسؤول لكل مبادرة", "responsible_ar": "", "period_ar": ""}]
    client.put(f"{API}/minutes/{mid}", headers=coord, json=doc)
    assert "مسؤول التنفيذ" in tr(coord, "submitted").json()["detail"]
    doc["agenda"][1]["recommendations"][0]["responsible_ar"] = "رئيس القسم"
    assert client.put(f"{API}/minutes/{mid}", headers=coord, json=doc).status_code == 200
    assert tr(coord, "submitted").status_code == 200

    assert client.put(f"{API}/minutes/{mid}", headers=coord, json=doc).status_code == 409          # مقفل بعد الرفع
    rec_id = client.get(f"{API}/minutes/{mid}", headers=coord).json()["agenda"][0]["recommendations"][0]["id"]
    assert client.patch(f"{API}/minutes/recommendations/{rec_id}/follow-up", headers=coord,
                        json={"fu_status": "done"}).status_code == 409                                  # المتابعة بعد الاعتماد
    assert tr(coord, "approved").status_code == 409                                                       # ليس رئيس القسم
    assert tr(hod, "returned").status_code == 409                                                         # بلا سبب
    assert tr(hod, "returned", comment="أضف مكان الاجتماع الفعلي").status_code == 200
    assert client.get(f"{API}/minutes/{mid}", headers=coord).json()["return_reason"] == "أضف مكان الاجتماع الفعلي"
    doc["location_ar"] = "قاعة 12 مبنى الحاسب"
    assert client.put(f"{API}/minutes/{mid}", headers=coord, json=doc).status_code == 200
    assert tr(coord, "submitted").status_code == 200

    r = tr(hod, "approved")
    assert r.status_code == 200, r.text
    arch = r.json()["archive"]
    assert arch["version_no"] == 1 and arch["linked_to_requirement"] is True
    cs = client.get(f"{API}/cycles/1/assessments", headers=coord).json()
    a111 = next(a for a in cs if a["requirement_code"] == "1-1-1")
    assert a111["evidence_count"] == 1
    d = client.get(f"{API}/evidence/{arch['evidence_id']}/download", headers=hod).json()
    assert Path(d["url"].removeprefix("file://")).read_bytes().startswith(b"%PDF")

    full = client.get(f"{API}/minutes/{mid}", headers=coord).json()
    recs = [r for a in full["agenda"] for r in a["recommendations"]]
    fu = lambda rid, **kw: client.patch(f"{API}/minutes/recommendations/{rid}/follow-up", headers=coord, json=kw)
    assert fu(recs[0]["id"], fu_status="partial").status_code == 403                                     # بلا معوقات
    assert fu(recs[0]["id"], fu_status="partial", fu_obstacles="تأخر الاعتماد", fu_solutions="رفعها للمجلس").status_code == 200
    s = fu(recs[1]["id"], fu_status="done").json()
    assert s["rec_total"] == 3 and s["rec_done"] == 1 and s["rec_partial"] == 1 and float(s["completion_pct"]) == 50.0

    assert client.post(f"{API}/minutes/{mid}/attendees/confirm", headers=fac).json()["confirmed"] is True
    assert client.post(f"{API}/minutes/{mid}/attendees/confirm", headers=dean).status_code == 404
    assert client.post(f"{API}/minutes/{mid}/archive", headers=coord).json()["version_no"] == 2

    pdf = client.get(f"{API}/minutes/{mid}/pdf", headers=hod)
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")

    r2 = client.post(f"{API}/cycles/1/minutes", headers=coord, json={"template_id": t111["id"], "department_id": 1}).json()
    assert r2["meeting_no"] == 2
    assert client.delete(f"{API}/minutes/{mid}", headers=coord).status_code == 409                      # معتمد
    assert client.delete(f"{API}/minutes/{r2['id']}", headers=coord).status_code == 204

    assert tr(hod, "returned", comment="x").status_code == 409                                            # إعادة فتح للوكيل فقط
    assert tr(dean, "returned", comment="تصحيح اسم المسؤول").status_code == 200
    again = client.get(f"{API}/minutes/{mid}", headers=coord).json()
    assert again["status"] == "returned" and again["summary"]["rec_pending"] == 3
    lst = client.get(f"{API}/cycles/1/minutes", headers=coord).json()
    assert [x["minutes_id"] for x in lst] == [mid]
