"""لوحة تحكم مدير النظام بالحسابات: كلمة مرور مؤقتة يُلزم بتغييرها، فك القفل، إنهاء الجلسات — ولا يملكها غيره."""
from app.config import settings
from test_auth import API, DEAN, GOOD, _bearer, _new_user

ADMIN = "admin@ynb"


def _login(client, email, pw):
    return client.post(f"{API}/auth/login", json={"email": email, "password": pw})


def test_only_system_admin(client, auth):
    uid, _ = _new_user(client, auth, "p.only@ynb", "مدرب الصلاحيات")
    for path in ("password", "unlock", "end-sessions"):
        r = client.post(f"{API}/users/{uid}/{path}", json={}, headers=auth(DEAN))
        assert r.status_code == 403, path
    # تفاصيل الدخول لا تظهر لوكيل الجودة
    u = next(x for x in client.get(f"{API}/users", headers=auth(DEAN)).json()["users"] if x["id"] == uid)
    assert "last_login_at" not in u and "is_locked" not in u
    data = client.get(f"{API}/users", headers=auth(ADMIN)).json()
    assert data["is_sysadmin"] is True and "is_locked" in data["users"][0]


def test_temp_password_forces_change_and_ends_sessions(client, auth):
    uid, token = _new_user(client, auth, "p.temp@ynb", "مدرب المؤقتة")
    old = client.post(f"{API}/auth/reset", json={"token": token, "password": GOOD}).json()["access_token"]
    r = client.post(f"{API}/users/{uid}/password", json={}, headers=auth(ADMIN))
    assert r.status_code == 200
    temp = r.json()["password"]
    assert len(temp) == 12 and any(c.isdigit() for c in temp) and any(c.isalpha() for c in temp)
    assert client.get(f"{API}/me", headers=_bearer(old)).status_code == 401        # الجلسة القديمة انتهت
    assert _login(client, "p.temp@ynb", GOOD).status_code == 401                   # الكلمة القديمة لم تعد صالحة
    r = _login(client, "p.temp@ynb", temp)
    assert r.status_code == 200 and r.json()["must_change"] is True
    tok = r.json()["access_token"]
    assert client.get(f"{API}/me", headers=_bearer(tok)).json()["must_change"] is True
    r = client.post(f"{API}/auth/change-password", json={"current_password": temp, "new_password": "MyOwn2026pw"},
                    headers=_bearer(tok))
    assert r.status_code == 200
    assert client.get(f"{API}/me", headers=_bearer(r.json()["access_token"])).json()["must_change"] is False
    assert _login(client, "p.temp@ynb", "MyOwn2026pw").json()["must_change"] is False
    # يُسجَّل في سجل التدقيق دون الكلمة
    import psycopg
    with psycopg.connect(settings.database_url) as c:
        rows = c.execute("SELECT action, new_data::text FROM aqap.audit_log WHERE table_name = 'user_credential' AND row_key = %s",
                         (str(uid),)).fetchall()
    assert rows and rows[0][0] == "admin_set_password" and temp not in rows[0][1]


def test_manual_password_validated(client, auth):
    uid, _ = _new_user(client, auth, "p.manual@ynb", "مدرب اليدوية")
    assert client.post(f"{API}/users/{uid}/password", json={"password": "short"}, headers=auth(ADMIN)).status_code == 422
    r = client.post(f"{API}/users/{uid}/password", json={"password": "Manual2026x"}, headers=auth(ADMIN))
    assert r.status_code == 200 and r.json()["password"] is None
    assert _login(client, "p.manual@ynb", "Manual2026x").json()["must_change"] is True


def test_cannot_target_self_or_inactive(client, auth):
    me = client.get(f"{API}/me", headers=auth(ADMIN)).json()["id"]
    assert client.post(f"{API}/users/{me}/password", json={}, headers=auth(ADMIN)).status_code == 403
    assert client.post(f"{API}/users/{me}/end-sessions", headers=auth(ADMIN)).status_code == 403
    uid, _ = _new_user(client, auth, "p.off@ynb", "مدرب موقوف")
    client.patch(f"{API}/users/{uid}", json={"is_active": False}, headers=auth(DEAN))
    assert client.post(f"{API}/users/{uid}/password", json={}, headers=auth(ADMIN)).status_code == 403


def test_unlock_and_end_sessions(client, auth):
    uid, token = _new_user(client, auth, "p.lock@ynb", "مدرب القفل")
    tok = client.post(f"{API}/auth/reset", json={"token": token, "password": GOOD}).json()["access_token"]
    from app import ratelimit
    ratelimit.reset()
    for _ in range(settings.login_max_failures):
        _login(client, "p.lock@ynb", "wrong-pass1")
    assert _login(client, "p.lock@ynb", GOOD).status_code == 429
    u = next(x for x in client.get(f"{API}/users", headers=auth(ADMIN)).json()["users"] if x["id"] == uid)
    assert u["is_locked"] is True
    assert client.post(f"{API}/users/{uid}/unlock", headers=auth(ADMIN)).status_code == 200
    assert client.get(f"{API}/me", headers=_bearer(tok)).status_code == 200          # فك القفل لا ينهي الجلسة
    r = _login(client, "p.lock@ynb", GOOD)
    assert r.status_code == 200 and r.json()["must_change"] is False
    assert client.post(f"{API}/users/{uid}/end-sessions", headers=auth(ADMIN)).status_code == 200
    assert client.get(f"{API}/me", headers=_bearer(r.json()["access_token"])).status_code == 401
    assert _login(client, "p.lock@ynb", GOOD).status_code == 200                       # كلمة المرور نفسها باقية
