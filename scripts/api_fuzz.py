"""اختبار شامل لواجهة المنصة بعد تسجيل الدخول (يفترض أن الدخول ناجح لكل دور):

1) كل مسار قراءة (GET) لكل دور بمعرّفات حقيقية → لا 5xx.
2) معرّفات غير صالحة (غير موجود، صفر، سالب، نص) → 4xx لا 5xx.
3) عزل الأقسام: منسوبو قسم آخر لا يصلون لوثائق قسم الاتصالات (404/403) قراءةً أو كتابة.
4) أجسام طلبات فاسدة لكل مسار كتابة (فارغ، أنواع خاطئة، نصوص ضخمة، null) → 4xx لا 5xx.

  python scripts/api_fuzz.py --base http://localhost:8012 --db postgresql://aqap:aqap@localhost/aqapfuzz
يُشغّل على نسخة قاعدة للتجربة فقط (المرحلة 4 تكتب في البيانات).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from collections import Counter

import psycopg

ROLES = ["dean@ynb", "auditor@ynb", "hod.tc@ynb", "coord.tc@ynb", "tc.t1@ynb", "coord.cs@ynb", "hod.cs@ynb"]
FAIL: list[str] = []
STATS = Counter()


class Api:
    def __init__(self, base):
        self.base, self.tok = base.rstrip("/"), {}

    def token(self, who):
        if who not in self.tok:
            self.tok[who] = self.req("POST", "/api/v1/auth/dev-token", {"email": who}, None)[1]["access_token"]
        return self.tok[who]

    def req(self, method, path, body=None, who="dean@ynb", raw=None):
        h = {"content-type": "application/json"}
        if who:
            h["authorization"] = "Bearer " + self.token(who)
        data = raw if raw is not None else (json.dumps(body, ensure_ascii=False).encode() if body is not None else None)
        r = urllib.request.Request(self.base + path, data=data, headers=h, method=method)
        try:
            with urllib.request.urlopen(r, timeout=120) as resp:
                b = resp.read()
                ct = resp.headers.get_content_type()
                return resp.status, (json.loads(b) if ct == "application/json" and b else None)
        except urllib.error.HTTPError as e:
            b = e.read()
            try:
                return e.code, json.loads(b)
            except Exception:
                return e.code, b[:300].decode("utf-8", "replace")


def check(label, status, body, expect=None):
    STATS["total"] += 1
    bad = status >= 500 or (expect is not None and status not in expect)
    if bad:
        FAIL.append(f"{label} → {status} {str(body)[:200]}")
        STATS["fail"] += 1


def sample_ids(db: str) -> dict:
    with psycopg.connect(db) as c:
        q = lambda s: [r[0] for r in c.execute(s).fetchall()]  # noqa: E731
        tc = q("SELECT id FROM aqap.department WHERE name_ar LIKE '%اتصالات%'")[0]
        cs = q("SELECT id FROM aqap.department WHERE name_ar = 'تقنية الحاسب'")[0]
        one = lambda s, *a: (c.execute(s, a).fetchone() or [None])[0]  # noqa: E731
        ids = {
            "cycle_id": one("SELECT id FROM aqap.assessment_cycle ORDER BY id"),
            "department_id": tc,
            "form_id": one("SELECT id FROM aqap.form_record WHERE department_id=%s ORDER BY id", tc),
            "minutes_id": one("SELECT id FROM aqap.minutes WHERE department_id=%s ORDER BY id", tc),
            "assessment_id": one("SELECT id FROM aqap.assessment WHERE department_id=%s ORDER BY id", tc),
            "action_id": one("SELECT id FROM aqap.improvement_action WHERE department_id=%s ORDER BY id", tc),
            "evidence_id": one("SELECT id FROM aqap.evidence WHERE department_id=%s AND kind='file' ORDER BY id", tc),
            "rec_id": one("""SELECT r.id FROM aqap.minutes_recommendation r JOIN aqap.minutes_agenda_item a ON a.id=r.agenda_item_id
                             JOIN aqap.minutes m ON m.id=a.minutes_id WHERE m.department_id=%s ORDER BY r.id""", tc),
            "user_id": one("SELECT id FROM aqap.app_user WHERE email='tc.t1@ynb'"),
            "requirement_id": one("SELECT id FROM aqap.requirement ORDER BY id"),
            "task_id": one("SELECT id FROM aqap.quality_task ORDER BY id"),
            "folder_id": one("SELECT id FROM aqap.evidence_folder ORDER BY id"),
            "guide_id": one("SELECT id FROM aqap.guide_document ORDER BY id"),
            "visit_id": one("SELECT id FROM aqap.external_visit ORDER BY id"),
            "deadline_id": one("SELECT id FROM aqap.cycle_deadline ORDER BY id"),
            "role_id": one("SELECT id FROM aqap.user_role ORDER BY id DESC"),
            "week_no": 1, "key": "exam_readiness",
        }
        ids["_cs"] = cs
        ids["_tc"] = tc
        return ids


def fill(path: str, ids: dict, override: dict | None = None) -> str | None:
    vals = {**ids, **(override or {})}
    out = path
    for p in re.findall(r"{(\w+)}", path):
        if vals.get(p) is None:
            return None
        out = out.replace("{" + p + "}", str(vals[p]))
    return out


GET_QUERY = {"/api/v1/cycles/{cycle_id}/assessments": "?department_id={department_id}"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8012")
    ap.add_argument("--db", required=True)
    ap.add_argument("--no-write", action="store_true")
    a = ap.parse_args()
    api = Api(a.base)
    ids = sample_ids(a.db)
    spec = api.req("GET", "/openapi.json", who=None)[1]
    paths = spec["paths"]

    # 1) قراءة لكل دور
    for path, ops in paths.items():
        if "get" not in ops:
            continue
        url = fill(path, ids)
        if url is None:
            continue
        for who in ROLES:
            s, b = api.req("GET", url, who=who)
            check(f"GET {url} [{who}]", s, b)
    print(f"① القراءة لكل دور: {STATS['total']} طلب، إخفاقات {STATS['fail']}")

    # 2) معرّفات غير صالحة
    n0 = STATS["total"]
    for path, ops in paths.items():
        params = re.findall(r"{(\w+)}", path)
        if not params or "get" not in ops:
            continue
        for bad in (99999999, 0, -1, "abc", "1%3BDROP%20TABLE%20x"):
            url = fill(path, ids, {params[-1]: bad})
            s, b = api.req("GET", url)
            check(f"GET {url} (معرّف غير صالح)", s, b, expect=range(400, 500))
    print(f"② المعرّفات غير الصالحة: {STATS['total'] - n0} طلب")

    # 3) عزل الأقسام: منسق الحاسب ومدرب… على وثائق الاتصالات
    n0 = STATS["total"]
    for who in ("coord.cs@ynb", "hod.cs@ynb"):
        for path in ("/api/v1/forms/{form_id}", "/api/v1/minutes/{minutes_id}", "/api/v1/assessments/{assessment_id}",
                     "/api/v1/actions/{action_id}", "/api/v1/forms/{form_id}/pdf", "/api/v1/forms/{form_id}/xlsx",
                     "/api/v1/minutes/{minutes_id}/pdf", "/api/v1/assessments/{assessment_id}/pdf",
                     "/api/v1/evidence/{evidence_id}/download", "/api/v1/evidence/{evidence_id}/versions"):
            url = fill(path, ids)
            if url:
                s, b = api.req("GET", url, who=who)
                check(f"IDOR GET {url} [{who}]", s, b, expect=(403, 404))
        writes = [("PUT", "/api/v1/forms/{form_id}", {"plan_data": {}}),
                  ("POST", "/api/v1/forms/{form_id}/transition", {"to_status": "returned", "comment": "x"}),
                  ("PUT", "/api/v1/minutes/{minutes_id}", {"title_ar": "اختبار", "agenda": [], "attendees": []}),
                  ("POST", "/api/v1/minutes/{minutes_id}/transition", {"to_status": "returned", "comment": "x"}),
                  ("PATCH", "/api/v1/assessments/{assessment_id}/self", {"self_rating": "met"}),
                  ("POST", "/api/v1/assessments/{assessment_id}/transition", {"to_status": "returned", "comment": "x"}),
                  ("PATCH", "/api/v1/actions/{action_id}", {"progress_pct": 10}),
                  ("PATCH", "/api/v1/minutes/recommendations/{rec_id}/follow-up", {"fu_status": "done"}),
                  ("POST", "/api/v1/cycles/{cycle_id}/forms", {"template_id": 1, "department_id": ids["_tc"]}),
                  ("POST", "/api/v1/evidence", {"title_ar": "شاهد دخيل", "kind": "link", "url": "https://mttvtcedu-my.sharepoint.com/x",
                                                 "department_id": ids["_tc"]})]
        for m, path, body in writes:
            url = fill(path, ids)
            s, b = api.req(m, url, body, who=who)
            check(f"IDOR {m} {url} [{who}]", s, b, expect=(403, 404, 409, 422))
    # مدرب القسم لا يعتمد ولا يحكم
    for m, path, body in [("POST", "/api/v1/assessments/{assessment_id}/transition", {"to_status": "final"}),
                          ("PATCH", "/api/v1/assessments/{assessment_id}/external", {"ext_verdict": "conforms"}),
                          ("POST", "/api/v1/users", {"email": "x@y", "full_name_ar": "دخيل"}),
                          ("PUT", "/api/v1/settings/evidence", {"attachment_mode": "both", "allowed_link_domains": ["evil.com"]})]:
        s, b = api.req(m, fill(path, ids), body, who="tc.t1@ynb")
        check(f"PRIV {m} {path} [مدرب]", s, b, expect=(403, 404, 409))
    print(f"③ عزل الأقسام والصلاحيات: {STATS['total'] - n0} طلب")

    if a.no_write:
        return report()
    # 4) أجسام فاسدة لكل مسار كتابة
    n0 = STATS["total"]
    junk = [None, {}, [], "x", 123, {"x": None}, {"title_ar": "ا" * 100000}, {"to_status": "approved' OR 1=1 --"},
            {"plan_data": "x", "follow_data": [1, 2]}, {"department_id": "abc", "template_id": -5}]
    for path, ops in paths.items():
        for m in ("post", "put", "patch"):
            if m not in ops or "dev-token" in path:
                continue
            url = fill(path, ids)
            if url is None:
                continue
            for body in junk:
                for who in ("coord.tc@ynb", "dean@ynb"):
                    raw = b"{not json" if body == "x" else None
                    s, b = api.req(m.upper(), url, body, who=who, raw=raw)
                    check(f"{m.upper()} {url} body={str(body)[:40]} [{who}]", s, b)
    print(f"④ الأجسام الفاسدة: {STATS['total'] - n0} طلب")
    report()


def report():
    print(f"\nالإجمالي: {STATS['total']} طلب — إخفاقات: {len(FAIL)}")
    for f in FAIL[:80]:
        print("  ✗", f)
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
