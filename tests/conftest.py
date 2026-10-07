import os
import tempfile
from pathlib import Path

import psycopg
import pytest

ADMIN_URL = os.environ.get("AQAP_TEST_ADMIN_URL", "postgresql://aqap:aqap@localhost:5432/postgres")
TEST_DB = "aqap_test"
os.environ.update({
    "AQAP_ENV": "test",
    "AQAP_DATABASE_URL": ADMIN_URL.rsplit("/", 1)[0] + f"/{TEST_DB}",
    "AQAP_STORAGE_BACKEND": "local",
    "AQAP_LOCAL_STORAGE_DIR": tempfile.mkdtemp(prefix="aqap-store-"),
    "AQAP_JWT_SECRET": "test-secret",
})

SCHEMA = (Path(__file__).parents[1] / "db" / "schema.sql").read_text(encoding="utf-8")

SEED = """
SET search_path = aqap;
INSERT INTO import_requirement_staging VALUES
 ('S1','القيادة',1,'S1.1','الحوكمة',1,'R1','وجود هيكل تنظيمي معتمد',1,'department',true),
 ('S1','القيادة',1,'S1.1','الحوكمة',1,'R2','تفعيل لجان القسم',2,'department',true),
 ('S1','القيادة',1,'S1.2','التخطيط',2,'R3','خطة تشغيلية للقسم',1,'department',false),
 ('S2','مخرجات التدريب',2,'S2.1','التوظيف',1,'R4','متابعة توظيف الخريجين',1,'institution',true);
SELECT import_framework_from_staging('TVTC-TQ-L2');
INSERT INTO institution(code, name_ar) VALUES ('YNB', 'الكلية التقنية التطبيقية بينبع');
INSERT INTO department(institution_id, code, name_ar) VALUES (1,'CS','تقنية الحاسب'), (1,'EE','التقنية الكهربائية');
INSERT INTO app_user(institution_id, email, full_name_ar) VALUES
 (1,'coord.cs@ynb','منسق الحاسب'), (1,'hod.cs@ynb','رئيس قسم الحاسب'),
 (1,'auditor@ynb','مدقق الجودة'), (1,'dean@ynb','وكيل الجودة'), (1,'coord.ee@ynb','منسق الكهرباء'),
 (1,'auditor.cs@ynb','مدقق من قسم الحاسب');
INSERT INTO user_role(user_id, role, department_id) VALUES
 (1,'dept_coordinator',1), (2,'hod',1), (3,'quality_auditor',NULL), (4,'quality_dean',NULL), (5,'dept_coordinator',2),
 (6,'quality_auditor',NULL), (6,'faculty',1);
INSERT INTO assessment_cycle(institution_id, framework_id, title_ar, academic_year, starts_on, ends_on)
 VALUES (1,1,'دورة 1447','1447','2026-01-01','2026-12-31');
INSERT INTO cycle_department VALUES (1,1),(1,2);
"""


@pytest.fixture(scope="session")
def client():
    with psycopg.connect(ADMIN_URL, autocommit=True) as conn:
        conn.execute(f"DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE)")
        conn.execute(f"CREATE DATABASE {TEST_DB}")
    with psycopg.connect(os.environ["AQAP_DATABASE_URL"], autocommit=True) as conn:
        conn.execute(SCHEMA)
        conn.execute(SEED)

    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="session")
def auth(client):
    cache: dict[str, dict] = {}

    def headers(email: str) -> dict:
        if email not in cache:
            r = client.post("/api/v1/auth/dev-token", json={"email": email})
            assert r.status_code == 200, r.text
            cache[email] = {"Authorization": f"Bearer {r.json()['access_token']}"}
        return cache[email]

    return headers
