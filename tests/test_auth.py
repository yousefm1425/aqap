"""الدخول بالبريد وكلمة المرور: الدعوة، تعيين كلمة المرور، الدخول، الإيقاف المؤقت، الاستعادة، التغيير، وإبطال الجلسات."""
from urllib.parse import unquote

from app.config import settings

API = "/api/v1"
DEAN = "dean@ynb"
GOOD = "Quality2026x"


def _token_from(link: str) -> str:
    assert "#setpw=" in link, link
    return unquote(link.split("#setpw=", 1)[1])


def _bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _new_user(client, auth, email: str, name: str) -> tuple[int, str]:
    r = client.post(f"{API}/users", json={"email": email, "full_name_ar": name}, headers=auth(DEAN))
    assert r.status_code == 201, r.text
    uid = r.json()["id"]
    r = client.post(f"{API}/users/{uid}/roles", json={"role": "faculty", "department_id": 1}, headers=auth(DEAN))
    assert r.status_code == 201, r.text
    r = client.post(f"{API}/users/{uid}/invite", headers=auth(DEAN))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["sent"] is False and body["mail_configured"] is False      # لا SMTP في الاختبار ← يُعاد الرابط
    return uid, _token_from(body["link"])


def test_config_and_login_without_password(client):
    assert client.get(f"{API}/auth/config").json() == {"dev_login": True, "mail": False}
    r = client.post(f"{API}/auth/login", json={"email": DEAN, "password": "whatever1"})
    assert r.status_code == 401
    r2 = client.post(f"{API}/auth/login", json={"email": "nobody@ynb", "password": "whatever1"})
    assert r2.status_code == 401 and r2.json()["detail"] == r.json()["detail"]     # لا يكشف وجود الحساب


def test_invite_set_password_and_login(client, auth):
    uid, token = _new_user(client, auth, "t.invite@ynb", "مدرب الدعوة")
    info = client.get(f"{API}/auth/link", params={"token": token}).json()
    assert info["purpose"] == "invite" and info["email"] == "t.invite@ynb"
    # سياسة كلمة المرور
    for weak in ("short1", "onlyletters", "12345678"):
        r = client.post(f"{API}/auth/reset", json={"token": token, "password": weak})
        assert r.status_code == 422, (weak, r.text)
    r = client.post(f"{API}/auth/reset", json={"token": token, "password": GOOD})
    assert r.status_code == 200, r.text
    assert client.get(f"{API}/me", headers=_bearer(r.json()["access_token"])).json()["email"] == "t.invite@ynb"
    # الرابط لمرة واحدة
    assert client.post(f"{API}/auth/reset", json={"token": token, "password": GOOD + "9"}).status_code == 400
    assert client.get(f"{API}/auth/link", params={"token": token}).status_code == 400
    # الدخول (البريد غير حساس لحالة الأحرف)
    r = client.post(f"{API}/auth/login", json={"email": "T.Invite@YNB", "password": GOOD})
    assert r.status_code == 200, r.text
    assert client.get(f"{API}/me", headers=_bearer(r.json()["access_token"])).status_code == 200
    assert client.post(f"{API}/auth/login", json={"email": "t.invite@ynb", "password": GOOD + "x"}).status_code == 401
    users = client.get(f"{API}/users", headers=auth(DEAN)).json()["users"]
    assert next(u for u in users if u["id"] == uid)["has_password"] is True


def test_lockout_after_failures(client, auth):
    _, token = _new_user(client, auth, "t.lock@ynb", "مدرب الإيقاف")
    assert client.post(f"{API}/auth/reset", json={"token": token, "password": GOOD}).status_code == 200
    codes = [client.post(f"{API}/auth/login", json={"email": "t.lock@ynb", "password": "Wrong1234"}).status_code
             for _ in range(settings.login_max_failures)]
    assert codes[:-1] == [401] * (settings.login_max_failures - 1) and codes[-1] == 429
    # أثناء الإيقاف ترفض حتى كلمة المرور الصحيحة
    assert client.post(f"{API}/auth/login", json={"email": "t.lock@ynb", "password": GOOD}).status_code == 429
    # تعيين كلمة مرور جديدة برابط الاستعادة يرفع الإيقاف
    r = client.post(f"{API}/auth/forgot", json={"email": "t.lock@ynb"})
    assert r.status_code == 200 and "dev_link" in r.json()
    assert client.post(f"{API}/auth/reset", json={"token": _token_from(r.json()["dev_link"]), "password": GOOD + "2"}).status_code == 200
    assert client.post(f"{API}/auth/login", json={"email": "t.lock@ynb", "password": GOOD + "2"}).status_code == 200


def test_forgot_reset_invalidates_old_sessions(client, auth):
    _, token = _new_user(client, auth, "t.reset@ynb", "مدرب الاستعادة")
    old = client.post(f"{API}/auth/reset", json={"token": token, "password": GOOD}).json()["access_token"]
    assert client.get(f"{API}/me", headers=_bearer(old)).status_code == 200
    # نفس الرد للبريد المسجل وغير المسجل
    unknown = client.post(f"{API}/auth/forgot", json={"email": "ghost@ynb"}).json()
    r = client.post(f"{API}/auth/forgot", json={"email": "t.reset@ynb"}).json()
    assert unknown["message"] == r["message"] and "dev_link" not in unknown
    # طلب ثانٍ خلال دقيقة لا يولّد رابطاً جديداً
    assert "dev_link" not in client.post(f"{API}/auth/forgot", json={"email": "t.reset@ynb"}).json()
    new = client.post(f"{API}/auth/reset", json={"token": _token_from(r["dev_link"]), "password": "NewPass2026"})
    assert new.status_code == 200
    assert client.get(f"{API}/me", headers=_bearer(old)).status_code == 401             # الجلسة القديمة أُبطلت
    assert client.get(f"{API}/me", headers=_bearer(new.json()["access_token"])).status_code == 200


def test_change_password(client, auth):
    _, token = _new_user(client, auth, "t.change@ynb", "مدرب التغيير")
    tok = client.post(f"{API}/auth/reset", json={"token": token, "password": GOOD}).json()["access_token"]
    r = client.post(f"{API}/auth/change-password", json={"current_password": "Wrong1234", "new_password": "Another2026"},
                    headers=_bearer(tok))
    assert r.status_code == 400
    r = client.post(f"{API}/auth/change-password", json={"current_password": GOOD, "new_password": "Another2026"},
                    headers=_bearer(tok))
    assert r.status_code == 200, r.text
    assert client.get(f"{API}/me", headers=_bearer(tok)).status_code == 401
    assert client.get(f"{API}/me", headers=_bearer(r.json()["access_token"])).status_code == 200
    assert client.post(f"{API}/auth/login", json={"email": "t.change@ynb", "password": "Another2026"}).status_code == 200


def test_inactive_user_cannot_login_or_reset(client, auth):
    uid, token = _new_user(client, auth, "t.off@ynb", "مدرب موقوف")
    assert client.post(f"{API}/auth/reset", json={"token": token, "password": GOOD}).status_code == 200
    assert client.patch(f"{API}/users/{uid}", json={"is_active": False}, headers=auth(DEAN)).status_code == 200
    assert client.post(f"{API}/auth/login", json={"email": "t.off@ynb", "password": GOOD}).status_code == 401
    assert "dev_link" not in client.post(f"{API}/auth/forgot", json={"email": "t.off@ynb"}).json()
    assert client.post(f"{API}/users/{uid}/invite", headers=auth(DEAN)).status_code == 403


def test_only_managers_invite(client, auth):
    assert client.post(f"{API}/users/1/invite", headers=auth("coord.cs@ynb")).status_code == 403


def test_prod_disables_dev_tokens(client, auth, monkeypatch):
    dev_headers = auth("coord.cs@ynb")
    monkeypatch.setattr(settings, "env", "prod")
    assert client.post(f"{API}/auth/dev-token", json={"email": DEAN}).status_code == 404
    assert client.get(f"{API}/me", headers=dev_headers).status_code == 401              # رمز بلا pv مرفوض في الإنتاج
    assert client.get(f"{API}/auth/config").json()["dev_login"] is False
    r = client.post(f"{API}/auth/login", json={"email": "t.change@ynb", "password": "Another2026"})
    assert r.status_code == 200 and client.get(f"{API}/me", headers=_bearer(r.json()["access_token"])).status_code == 200
    assert "dev_link" not in client.post(f"{API}/auth/forgot", json={"email": "t.invite@ynb"}).json()


def test_admin_changes_email(client, auth):
    uid, token = _new_user(client, auth, "t.mail@ynb", "مدرب البريد")
    tok = client.post(f"{API}/auth/reset", json={"token": token, "password": GOOD}).json()["access_token"]
    # البريد مأخوذ ← 409
    assert client.patch(f"{API}/users/{uid}", json={"email": "dean@ynb"}, headers=auth(DEAN)).status_code == 409
    assert client.patch(f"{API}/users/{uid}", json={"email": "bad-email"}, headers=auth(DEAN)).status_code == 422
    assert client.patch(f"{API}/users/{uid}", json={"email": "T.Mail2@YNB"}, headers=auth(DEAN)).status_code == 200
    assert client.get(f"{API}/me", headers=_bearer(tok)).status_code == 403            # الجلسة القديمة مرتبطة بالبريد القديم
    assert client.post(f"{API}/auth/login", json={"email": "t.mail@ynb", "password": GOOD}).status_code == 401
    r = client.post(f"{API}/auth/login", json={"email": "t.mail2@ynb", "password": GOOD})
    assert r.status_code == 200 and client.get(f"{API}/me", headers=_bearer(r.json()["access_token"])).json()["email"] == "t.mail2@ynb"
