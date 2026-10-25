"""اختبار الواجهة بعد تسجيل الدخول: كل صفحة لكل دور، ثم كل وثيقة لقسم الاتصالات (كل نموذج، كل محضر، كل متطلب، كل خطة)
مع رصد أخطاء JavaScript، وأخطاء الطلبات (4xx/5xx)، والصفحات الفارغة، والطلبات المعلقة.

  python scripts/ui_deep_test.py --base http://localhost:8012 --db postgresql://aqap:aqap@localhost/aqaprender
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request

import psycopg
from playwright.sync_api import sync_playwright

ROUTES = ["scope", "dashboard", "workspace", "minutes", "forms", "plans", "quality", "calendar", "folders", "training", "report",
          "college", "guides", "users"]
ROLES = ["dean@ynb", "auditor@ynb", "hod.tc@ynb", "coord.tc@ynb", "tc.t1@ynb", "coord.cs@ynb"]
ISSUES: list[str] = []


def token(base, who):
    r = urllib.request.Request(base + "/api/v1/auth/dev-token", data=json.dumps({"email": who}).encode(),
                               headers={"content-type": "application/json"})
    return json.load(urllib.request.urlopen(r))["access_token"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8012")
    ap.add_argument("--db", required=True)
    a = ap.parse_args()
    with psycopg.connect(a.db) as c:
        tc = c.execute("SELECT id FROM aqap.department WHERE name_ar LIKE '%اتصالات%'").fetchone()[0]
        forms = [r[0] for r in c.execute("SELECT template_id FROM aqap.form_record WHERE department_id=%s ORDER BY 1", (tc,))]
        mins = [r[0] for r in c.execute("SELECT id FROM aqap.minutes WHERE department_id=%s ORDER BY 1", (tc,))]
        asses = [r[0] for r in c.execute("SELECT id FROM aqap.assessment WHERE department_id=%s ORDER BY 1", (tc,))]
        acts = [r[0] for r in c.execute("SELECT id FROM aqap.improvement_action WHERE department_id=%s ORDER BY 1", (tc,))]
    pages = 0
    with sync_playwright() as p:
        b = p.chromium.launch()
        for who in ROLES:
            ctx = b.new_context(viewport={"width": 1366, "height": 900}, locale="ar-SA")
            pg = ctx.new_page()
            cur = {"url": ""}
            pg.on("console", lambda m: m.type == "error" and ISSUES.append(f"[{who}] console {cur['url']}: {m.text[:200]}"))
            pg.on("pageerror", lambda e: ISSUES.append(f"[{who}] JS {cur['url']}: {str(e)[:200]}"))
            pg.on("response", lambda r: r.status >= 400 and "/api/" in r.url and ISSUES.append(
                f"[{who}] HTTP {r.status} {r.request.method} {r.url.split('/api/v1')[-1][:90]} @ {cur['url']}"))
            pg.on("requestfailed", lambda r: ISSUES.append(f"[{who}] failed {r.url[:90]} @ {cur['url']}"))
            pg.goto(f"{a.base}/app/#token={token(a.base, who)}")
            pg.wait_for_load_state("networkidle")
            targets = [f"#/{r}" for r in ROUTES]
            if who in ("dean@ynb", "coord.tc@ynb"):
                targets += [f"#/forms?dept={tc}&t={t}" for t in forms] + [f"#/minutes?dept={tc}&m={m}" for m in mins] + \
                           [f"#/workspace?dept={tc}&a={x}" for x in asses] + [f"#/plans?dept={tc}&a={x}" for x in acts]
            for t in targets:
                cur["url"] = t
                pg.goto(f"{a.base}/app/{t}")
                try:
                    pg.wait_for_load_state("networkidle", timeout=20000)
                except Exception:
                    ISSUES.append(f"[{who}] timeout {t}")
                pg.wait_for_timeout(150)
                txt = pg.evaluate("document.querySelector('main, #app, body').innerText.trim().length")
                err = pg.evaluate("[...document.querySelectorAll('.error, .alert-error, .toast.error')].map(e=>e.innerText).join(' | ')")
                if txt < 30:
                    ISSUES.append(f"[{who}] صفحة فارغة {t}")
                if err.strip():
                    ISSUES.append(f"[{who}] رسالة خطأ ظاهرة {t}: {err[:160]}")
                pages += 1
            ctx.close()
        b.close()
    # الطلبات 403/404 المتوقعة لدور لا يملك الصفحة ليست أخطاء إن وجّهت الواجهة المستخدم؛ نعرضها منفصلة
    hard = [i for i in ISSUES if " HTTP 403 " not in i and " HTTP 404 " not in i]
    soft = [i for i in ISSUES if i not in hard]
    print(f"الصفحات: {pages} — مشكلات: {len(hard)} — طلبات 403/404 من الواجهة: {len(soft)}")
    for i in hard[:60]:
        print("  ✗", i)
    for i in sorted(set(soft))[:40]:
        print("  ~", i)
    sys.exit(1 if hard else 0)


if __name__ == "__main__":
    main()
