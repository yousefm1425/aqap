"""الاستبيانات: رابط Microsoft Forms، ورفع ملف الردود المصدَّر، والإحصاءات وصلاحياتها، وعدم حفظ البريد والاسم."""
import io
import os
import tempfile
from datetime import datetime
from pathlib import Path

import psycopg
import pytest
from openpyxl import Workbook

from app.survey_stats import classify, compute, parse_responses

ADMIN_URL = os.environ.get("AQAP_TEST_ADMIN_URL", "postgresql://aqap:aqap@localhost:5432/postgres")
DB = "aqap_surveys_test"
API = "/api/v1"
FORM = "https://forms.office.com/Pages/ResponsePage.aspx?id=abc123"

SEED = """
SET search_path = aqap;
INSERT INTO import_requirement_staging VALUES
 ('1','القيادة الإدارية',1,'1-1','التوجيه التشغيلي',1,'1-1-1','متطلب 1-1-1',1,'department',true,0);
SELECT import_framework_from_staging('TVTC-TQ-L2');
INSERT INTO institution(code, name_ar) VALUES ('YNB', 'الكلية التقنية التطبيقية بينبع');
INSERT INTO department(institution_id, code, name_ar) VALUES (1,'CS','تقنية الحاسب');
INSERT INTO app_user(institution_id, email, full_name_ar) VALUES
 (1,'dean@ynb','وكيل الجودة'), (1,'hod@ynb','رئيس القسم'), (1,'fac@ynb','مدرب');
INSERT INTO user_role(user_id, role, department_id) VALUES (1,'quality_dean',NULL), (2,'hod',1), (3,'faculty',1);
INSERT INTO assessment_cycle(institution_id, framework_id, title_ar, academic_year, starts_on, ends_on, status)
 VALUES (1,1,'دورة 1448','1448','2026-08-23','2027-06-24','open');
INSERT INTO cycle_department VALUES (1,1);
"""


def forms_export() -> bytes:
    """ملف مثل تصدير Microsoft Forms: أعمدة التعريف ثم الأسئلة."""
    wb = Workbook()
    ws = wb.active
    ws.append(["ID", "Start time", "Completion time", "Email", "Name", "الفئة", "رضاك عن خدمات المكتبة",
               "سرعة إنجاز معاملات القبول والتسجيل", "قيّم الخدمات الإلكترونية", "الخدمات التي استفدت منها", "ملاحظات ومقترحات"])
    rows = [
        ("متدرب", "موافق بشدة", "ممتاز", 5, "المكتبة;المعامل;", "شكراً"),
        ("متدرب", "موافق", "جيد جداً", 4, "المكتبة;", ""),
        ("مدرب", "محايد", "جيد", 3, "المعامل;", "تحسين الإنترنت"),
        ("موظف", "غير موافق", "مقبول", 2, "الإرشاد;", "زيادة ساعات المكتبة"),
        ("متدرب", "موافق بشدة", "ممتاز", 5, "المكتبة;الإرشاد;", ""),
    ]
    for i, r in enumerate(rows, 1):
        ws.append([i, datetime(2026, 11, i, 9), datetime(2026, 11, i, 9, 5), f"u{i}@tvtc.gov.sa", f"اسم {i}", *r])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_parse_and_compute():
    qs, rs = parse_responses("Survey.xlsx", forms_export())
    assert qs[0] == "الفئة" and len(qs) == 6 and len(rs) == 5
    assert all("tvtc.gov.sa" not in a and "اسم" not in a for r in rs for a in r["answers"])
    assert rs[0]["ext_id"] == "1" and rs[0]["submitted_at"].startswith("2026-11-01T09:05")
    st = compute(qs, [r["answers"] for r in rs])
    types = [q["type"] for q in st["questions"]]
    assert types == ["choice", "scale", "scale", "rating", "multi", "text"]
    lib = st["questions"][1]
    assert lib["satisfied_pct"] == 60.0 and lib["mean"] == 3.8 and lib["options"][0]["label"] == "موافق بشدة"
    assert st["questions"][4]["options"][0] == {"label": "المكتبة", "count": 3, "pct": 60.0}
    assert st["questions"][5]["samples"][0] == "زيادة ساعات المكتبة"
    assert st["overall"]["satisfied_pct"] == 60.0 and st["overall"]["scale_questions"] == 3
    trainees = compute(qs, [r["answers"] for r in rs], 0, "متدرب")
    assert trainees["responses"] == 3 and trainees["questions"][1]["satisfied_pct"] == 100.0
    assert trainees["filters"][0]["values"][0] == "متدرب"
    assert classify(["أ", "ب", "ج", "د", "هـ", "و", "ز"]) == "text"


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
                       "AQAP_LOCAL_STORAGE_DIR": tempfile.mkdtemp(prefix="aqap-sv-"), "AQAP_JWT_SECRET": "test-secret"})
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


def test_survey_flow_and_permissions(client):
    dean, hod, fac = h(client, "dean@ynb"), h(client, "hod@ynb"), h(client, "fac@ynb")
    p = f"{API}/cycles/1/surveys"
    d = client.get(p, headers=fac).json()
    assert [i["kind"] for i in d["items"]] == ["trainee", "trainer", "services"]
    assert not d["can_manage"] and not d["can_view_stats"] and d["items"][0]["state"] == "draft"

    body = {"title_ar": "استبيان الخدمات 1448", "form_url": FORM}
    assert client.put(f"{p}/services", headers=fac, json=body).status_code == 403
    bad = client.put(f"{p}/services", headers=dean, json={**body, "form_url": "https://evil.example.com/form"})
    assert bad.status_code == 403 and "Microsoft Forms" in bad.json()["detail"]
    assert client.put(f"{p}/services", headers=dean, json=body).status_code == 200
    assert client.put(f"{p}/nope", headers=dean, json=body).status_code == 404

    up = lambda who, data=None, name="responses.xlsx": client.post(  # noqa: E731
        f"{p}/services/responses", headers=who, files={"file": (name, data or forms_export())})
    assert up(fac).status_code == 403
    assert up(dean, b"not a sheet", "x.pdf").status_code == 403
    r = up(dean).json()
    assert r["responses"] == 5 and r["types"]["scale"] == 2 and r["overall"]["satisfied_pct"] == 60.0
    assert up(dean).json()["responses"] == 5          # إعادة الرفع تستبدل ولا تكرر

    lst = client.get(p, headers=fac).json()["items"][2]
    assert lst["form_url"] == FORM and lst["state"] == "open" and lst["responses"] is None   # المدرب يرى الرابط لا الإحصاءات
    assert client.get(f"{p}/services/stats", headers=fac).status_code == 403
    st = client.get(f"{p}/services/stats", headers=hod).json()
    assert st["responses"] == 5 and st["stats"]["overall"]["level"] == "مقبول" and st["last_at"].startswith("2026-11-05")
    f = client.get(f"{p}/services/stats", headers=hod, params={"q": 0, "v": "متدرب"}).json()
    assert f["stats"]["responses"] == 3 and f["filter"] == {"q": 0, "v": "متدرب"}
    with psycopg.connect(os.environ["AQAP_DATABASE_URL"]) as c:
        dump = c.execute("SELECT string_agg(answers::text, ' ') FROM aqap.survey_response").fetchone()[0]
    assert "tvtc.gov.sa" not in dump and "اسم 1" not in dump

    assert client.delete(f"{p}/services/responses", headers=dean).json()["deleted"] == 5
    assert client.get(f"{p}/services/stats", headers=dean).json()["stats"] is None
