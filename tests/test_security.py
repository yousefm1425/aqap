"""ترويسات الأمان، روابط التنزيل الموقّعة، حدود المحاولات لكل عنوان، وحماية فاحص الروابط."""
import asyncio

import jwt
import pytest

from app.config import settings
from app.routers.evidence_links import _public_host
from app.storage import FILE_AUDIENCE

API = "/api/v1"


@pytest.fixture(scope="module")
def client(client):
    """سياق تطبيق خاص بهذه الوحدة: وحدات أخرى تفتح سياقها وتغلق مجمع الاتصالات عند انتهائها."""
    from fastapi.testclient import TestClient

    from app import main
    with TestClient(main.app) as c:
        yield c


def test_security_headers(client):
    for path in ("/app/", f"{API}/auth/config", "/health"):
        r = client.get(path)
        assert r.headers["x-frame-options"] == "DENY", path
        assert r.headers["x-content-type-options"] == "nosniff"
        assert "frame-ancestors 'none'" in r.headers["content-security-policy"]
        assert "script-src 'self';" in r.headers["content-security-policy"]
        assert r.headers["referrer-policy"] == "strict-origin-when-cross-origin"
    assert client.get(f"{API}/auth/config").headers["cache-control"] == "no-store"


def test_signed_download_links(client):
    bad = client.get(f"{API}/files/not-a-token")
    assert bad.status_code == 403
    forged = jwt.encode({"k": "x.pdf", "aud": FILE_AUDIENCE, "exp": 9999999999}, "wrong-secret", algorithm="HS256")
    assert client.get(f"{API}/files/{forged}").status_code == 403
    # مفتاح يحاول الخروج من مجلد التخزين
    trav = jwt.encode({"k": "../../etc/passwd", "aud": FILE_AUDIENCE, "exp": 9999999999}, settings.jwt_secret, algorithm="HS256")
    assert client.get(f"{API}/files/{trav}").status_code == 403
    # رمز دخول عادي لا يصلح رابط تنزيل (جمهور مختلف)
    login_like = jwt.encode({"k": "x", "aud": "aqap", "exp": 9999999999}, settings.jwt_secret, algorithm="HS256")
    assert client.get(f"{API}/files/{login_like}").status_code == 403
    expired = jwt.encode({"k": "x.pdf", "aud": FILE_AUDIENCE, "exp": 1}, settings.jwt_secret, algorithm="HS256")
    assert client.get(f"{API}/files/{expired}").status_code == 403


def test_login_rate_limit_per_ip(client):
    codes = [client.post(f"{API}/auth/login", json={"email": f"x{i}@ynb", "password": "Wrong1234"}).status_code
             for i in range(21)]
    assert codes[:20] == [401] * 20 and codes[20] == 429
    codes = [client.post(f"{API}/auth/forgot", json={"email": f"y{i}@ynb"}).status_code for i in range(6)]
    assert codes[:5] == [200] * 5 and codes[5] == 429


def test_link_checker_blocks_internal_addresses():
    run = asyncio.run
    for url in ("http://127.0.0.1/", "http://localhost:5432/", "http://10.0.0.5/", "http://169.254.169.254/latest/meta-data",
                "http://[::1]/", "file:///etc/passwd", "ftp://example.com/"):
        assert run(_public_host(url)) is False, url


def test_calendar_import_rejects_bombs(client):
    import io
    import zipfile
    t = client.post(f"{API}/auth/dev-token", json={"email": "dean@ynb"}).json()["access_token"]
    h = {"Authorization": f"Bearer {t}"}
    url = f"{API}/cycles/1/calendar/import"
    big = client.post(url, headers=h, files={"file": ("c.csv", b"a" * (5 * 1024 * 1024 + 10), "text/csv")})
    assert big.status_code == 413
    # «قنبلة zip»: جزء صغير مضغوطاً وضخم بعد الفك
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("xl/worksheets/sheet1.xml", b"<a>" + b" " * (40 * 1024 * 1024) + b"</a>")
    r = client.post(url, headers=h, files={"file": ("c.xlsx", buf.getvalue(), "application/octet-stream")})
    assert r.status_code == 413
    # كيانات XML (XXE / billion laughs) مرفوضة
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("xl/worksheets/sheet1.xml", '<?xml version="1.0"?><!DOCTYPE x [<!ENTITY e SYSTEM "file:///etc/passwd">]><x>&e;</x>')
    r = client.post(url, headers=h, files={"file": ("c.xlsx", buf.getvalue(), "application/octet-stream")})
    assert r.status_code == 422

