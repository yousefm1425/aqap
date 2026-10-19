"""فحص شامل للمنصة قبل الإطلاق (للقراءة فقط — لا يعدّل أي بيانات).

يفحص:
  1) كل واجهات القراءة (GET) في الـ API لكل دور: لا أخطاء خادم (5xx)، والصلاحيات تُرجع 403 لا خطأ.
  2) كل التنزيلات والتصديرات: ملف Excel الرسمي، تقارير الكلية (xlsx)، PDF المحاضر والنماذج، تنزيل الشواهد.
  3) كل صفحات الواجهة لكل دور في متصفح حقيقي (Playwright): لا أخطاء JavaScript، لا رسالة خطأ في الصفحة، لا طلبات فاشلة.
  4) روابط الصفحة الرئيسية وملفات PDF المنشورة (دليل الاستخدام، الدليل الرسمي).

التشغيل (والمنصة تعمل على المنفذ 8000 في وضع التطوير):
    python scripts/smoke_test.py
    python scripts/smoke_test.py --base http://localhost:8000 --no-ui      # الواجهات البرمجية فقط
النتيجة: جدول في الطرفية + تقرير HTML في smoke-report.html، ورمز خروج 1 عند وجود إخفاق.
"""
import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.request
from collections import defaultdict

ROUTES = {"workspace": "التقديرات والشواهد", "minutes": "المحاضر", "forms": "الخطط والتقارير", "plans": "خطط التحسين",
          "quality": "أعمال الجودة", "calendar": "التقويم", "folders": "مجلدات الشواهد", "dashboard": "لوحة المؤشرات",
          "training": "سير العملية التدريبية", "report": "التقرير النهائي", "college": "تقارير الكلية",
          "scope": "نطاق المتطلبات", "guides": "الأدلة", "users": "المستخدمون"}
ROLE_LABEL = {"quality_dean": "وكيل الجودة", "system_admin": "مدير النظام", "quality_auditor": "مدقق الجودة",
              "hod": "رئيس قسم", "dept_coordinator": "منسق قسم", "faculty": "مدرب", "external_reviewer": "مراجع خارجي"}
SIGNATURES = {"xlsx": b"PK", "pdf": b"%PDF"}


class Smoke:
    def __init__(self, base: str):
        self.base = base.rstrip("/")
        self.results: list[dict] = []          # {area, role, item, status, ok, note}

    # ------------------------------------------------------------------ أدوات
    def req(self, path, token=None, method="GET", body=None, raw=False):
        url = path if path.startswith("http") else f"{self.base}{path}"
        data = json.dumps(body).encode() if body is not None else None
        headers = {"Content-Type": "application/json"} if data else {}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        r = urllib.request.Request(url, data=data, method=method, headers=headers)
        t0 = time.time()
        try:
            with urllib.request.urlopen(r, timeout=60) as resp:
                content = resp.read()
                return resp.status, content if raw else _json(content), resp.headers.get("Content-Type", ""), time.time() - t0
        except urllib.error.HTTPError as e:
            return e.code, _json(e.read()), "", time.time() - t0
        except Exception as e:                                   # noqa: BLE001
            return 0, str(e), "", time.time() - t0

    def add(self, area, role, item, status, ok, note=""):
        self.results.append({"area": area, "role": role, "item": item, "status": status, "ok": ok, "note": note})
        mark = "✓" if ok is True else ("!" if ok == "warn" else "✗")
        print(f"  {mark} [{area}] {role:<14} {item} → {status} {note}")

    def token(self, email):
        s, d, *_ = self.req("/api/v1/auth/dev-token", method="POST", body={"email": email})
        if s != 200:
            raise SystemExit(f"تعذّر الدخول بـ {email} ({s}): {d}. هل المنصة تعمل في وضع التطوير؟")
        return d["access_token"]

    # ------------------------------------------------------------------ 1) الحسابات والأدوار
    def accounts(self):
        dean = self.token(self.dean)
        s, users, *_ = self.req("/api/v1/users", dean)
        users = users.get("users", []) if isinstance(users, dict) else users
        if s != 200:
            raise SystemExit(f"تعذّر قراءة المستخدمين بحساب {self.dean} ({s})")
        picked: dict[str, dict] = {}
        for u in users:
            if not u.get("is_active", True):
                continue
            for r in u.get("roles") or []:
                role = r.get("role") if isinstance(r, dict) else r
                picked.setdefault(role, {"email": u["email"], "name": u["full_name_ar"]})
        print(f"الأدوار المختبرة: {', '.join(f'{ROLE_LABEL.get(k, k)} ({v['email']})' for k, v in picked.items())}")
        return {role: {**v, "token": self.token(v["email"])} for role, v in picked.items()}

    # ------------------------------------------------------------------ 2) الواجهات البرمجية
    def discover(self, tok):
        ids = defaultdict(list)
        _, cycles, *_ = self.req("/api/v1/cycles", tok)
        cycles = cycles if isinstance(cycles, list) else []
        ids["cycle_id"] = [c["id"] for c in cycles if c.get("framework_code") != "TVTC-PATTERNS"][:1] or [c["id"] for c in cycles][:1]
        _, depts, *_ = self.req("/api/v1/departments", tok)
        ids["department_id"] = [d["id"] for d in depts] if isinstance(depts, list) else []
        if not ids["cycle_id"]:
            return ids
        c = ids["cycle_id"][0]
        _, a, *_ = self.req(f"/api/v1/cycles/{c}/assessments", tok)
        ids["assessment_id"] = [x["id"] for x in a][:3] if isinstance(a, list) else []
        _, a, *_ = self.req(f"/api/v1/cycles/{c}/actions", tok)
        ids["action_id"] = [x["id"] for x in a][:3] if isinstance(a, list) else []
        _, m, *_ = self.req(f"/api/v1/cycles/{c}/minutes", tok)
        ids["minutes_id"] = [x["minutes_id"] for x in m][:3] if isinstance(m, list) else []
        forms = []
        for d in ids["department_id"]:
            _, t, *_ = self.req(f"/api/v1/cycles/{c}/forms/templates?department_id={d}", tok)
            for tpl in t if isinstance(t, list) else []:
                forms += [r["id"] for r in tpl.get("records") or [] if isinstance(r, dict) and "id" in r]
        ids["form_id"] = forms[:4]
        _, ev, *_ = self.req("/api/v1/evidence", tok)
        ids["evidence_id"] = [x["id"] for x in ev if x.get("kind") != "link"][:2] + [x["id"] for x in ev if x.get("kind") == "link"][:1] \
            if isinstance(ev, list) else []
        _, cr, *_ = self.req(f"/api/v1/cycles/{c}/college-reports", tok)
        ids["key"] = [x["key"] for x in cr] if isinstance(cr, list) else []
        self.college_keys = ids["key"]
        return ids

    def api(self, roles):
        print("\n— 1) الواجهات البرمجية لكل دور")
        _, spec, *_ = self.req("/openapi.json")
        paths = [p for p, ops in spec["paths"].items() if "get" in ops and p.startswith("/api/v1") and "dev-token" not in p]
        dean_ids = self.discover(roles[self.dean_role]["token"])
        for role, info in roles.items():
            tok = info["token"]
            for p in paths:
                params = re.findall(r"{(\w+)}", p)
                values = [dean_ids.get(x) or [] for x in params]
                if any(not v for v in values):
                    continue
                combos = [dict(zip(params, [v[0] for v in values]))]
                if params and len(values[-1]) > 1 and params[-1] in ("key", "form_id", "minutes_id"):   # كل تقارير الكلية وأكثر من نموذج
                    combos = [dict(zip(params, [v[0] for v in values[:-1]] + [last])) for last in values[-1]]
                for combo in combos:
                    url = p.format(**combo)
                    raw = url.endswith(("/pdf", "/xlsx", "/official", "/download"))
                    s, body, ctype, dt = self.req(url, tok, raw=raw)
                    ok, note = self.judge(url, s, body, ctype, raw, role)
                    if ok is not True or role == self.dean_role or raw:
                        self.add("API", ROLE_LABEL.get(role, role), url.replace("/api/v1", ""), s, ok, note + (f" ({dt:.1f}ث)" if dt > 3 else ""))
                    else:
                        self.results.append({"area": "API", "role": ROLE_LABEL.get(role, role), "item": url, "status": s, "ok": True, "note": ""})

    def judge(self, url, s, body, ctype, raw, role):
        if s == 0:
            return False, f"لا استجابة: {body}"
        if s >= 500:
            return False, "خطأ خادم"
        if s in (401, 403):
            return (False, "رُفض لوكيل الجودة") if role == self.dean_role else (True, "ممنوع حسب الصلاحية")
        if s == 404 and role != self.dean_role:
            return True, "خارج نطاق قسمه"
        if s == 404 and "/download" in url:
            return "warn", "الملف غير موجود في التخزين"
        if s >= 400:
            msg = body.get("detail") if isinstance(body, dict) else body
            return "warn", str(msg)[:120]
        if raw:
            if url.endswith("/download") and "json" in ctype:
                return True, "رابط خارجي/موقّع"
            kind = "pdf" if url.endswith("/pdf") else "xlsx" if url.endswith(("/xlsx", "/official")) else None
            if kind and not (isinstance(body, bytes) and body.startswith(SIGNATURES[kind])):
                return False, f"الملف ليس {kind} صالحاً"
            return True, f"{len(body) / 1024:.0f}KB" if isinstance(body, bytes) else ""
        return True, ""

    # ------------------------------------------------------------------ 3) الصفحة الرئيسية والملفات المنشورة
    def static(self):
        print("\n— 2) الصفحة الرئيسية والملفات المنشورة")
        s, html, *_ = self.req("/app/home.html", raw=True)
        self.add("رئيسية", "زائر", "/app/home.html", s, s == 200)
        links = set(re.findall(rb'(?:href|src)="([^"#][^"]*)"', html or b""))
        for l in sorted(x.decode() for x in links):
            if l.startswith(("http", "mailto")):
                continue
            url = "/app/" + l.lstrip("./") if not l.startswith("/") else l
            s, body, ctype, _ = self.req(url, raw=True)
            ok = s == 200 and (not url.endswith(".pdf") or (body or b"").startswith(b"%PDF"))
            self.add("رئيسية", "زائر", url, s, ok, f"{len(body or b'') / 1024:.0f}KB" if ok else "")

    # ------------------------------------------------------------------ 4) صفحات الواجهة في متصفح
    def ui(self, roles, shots=None):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            print("\n(تخطّي فحص الواجهة: Playwright غير مثبت — pip install playwright)")
            return
        print("\n— 3) صفحات الواجهة لكل دور (متصفح حقيقي)")
        with sync_playwright() as p:
            browser = p.chromium.launch()
            for role, info in roles.items():
                ctx = browser.new_context(viewport={"width": 1366, "height": 900}, accept_downloads=True)
                page = ctx.new_page()
                errors, failed = [], []
                page.on("pageerror", lambda e: errors.append(str(e)))
                page.on("console", lambda m: m.type == "error" and "Failed to load resource" not in m.text and errors.append(m.text))
                page.on("response", lambda r: r.status >= 500 and failed.append(f"{r.status} {r.url}"))
                page.goto(f"{self.base}/app/#token={info['token']}")
                page.wait_for_timeout(1200)
                for path, label in ROUTES.items():
                    errors.clear(); failed.clear()
                    page.goto(f"{self.base}/app/#/{path}")
                    try:
                        page.wait_for_load_state("networkidle", timeout=15000)
                    except Exception:                            # noqa: BLE001
                        pass
                    page.wait_for_timeout(600)
                    landed = page.evaluate("location.hash.split('?')[0].replace('#/', '')")
                    box = page.query_selector("main .error-box")
                    msg = box.inner_text() if box else ""
                    text = page.inner_text("main") if page.query_selector("main") else ""
                    if landed != path:
                        ok, note = True, f"غير متاحة لهذا الدور (حُوّل إلى {ROUTES.get(landed, landed)})"
                    elif msg or errors or failed:
                        ok, note = False, (msg or "; ".join(errors + failed))[:200]
                    elif len(text.strip()) < 20:
                        ok, note = False, "الصفحة فارغة"
                    else:
                        ok, note = True, ""
                    self.add("واجهة", ROLE_LABEL.get(role, role), f"{label} (#/{path})", "", ok, note)
                    if shots:
                        page.screenshot(path=f"{shots}/{role}-{path}.png", full_page=False)
                if role == self.dean_role:
                    self.ui_actions(page)
                ctx.close()
            browser.close()

    def ui_actions(self, page):
        """أزرار التنزيل والتصدير الفعلية في الواجهة (بحساب وكيل الجودة، دون تعديل بيانات)."""
        def download(route, button, kind):
            page.goto(f"{self.base}/app/#/{route}")
            page.wait_for_timeout(1500)
            btn = page.get_by_role("button", name=button)
            if not btn.count():
                self.add("زر", "وكيل الجودة", f"{button} (#/{route})", "", "warn", "الزر غير ظاهر")
                return
            try:
                with page.expect_download(timeout=150000) as d:
                    btn.first.click()
                path = d.value.path()
                head = open(path, "rb").read(4)
                ok = head.startswith(SIGNATURES[kind])
                self.add("زر", "وكيل الجودة", f"{button} (#/{route})", "تنزيل", ok, d.value.suggested_filename if ok else "ملف غير صالح")
            except Exception as e:                               # noqa: BLE001
                box = page.query_selector(".toast.error")
                self.add("زر", "وكيل الجودة", f"{button} (#/{route})", "", False, (box.inner_text() if box else str(e))[:200])

        def popup(route, button):
            page.goto(f"{self.base}/app/#/{route}")
            page.wait_for_timeout(1500)
            btn = page.get_by_role("button", name=button)
            if not btn.count():
                self.add("زر", "وكيل الجودة", f"{button} (#/{route})", "", "warn", "الزر غير ظاهر (لا بيانات بعد؟)")
                return
            try:
                with page.context.expect_page(timeout=20000) as pp:
                    btn.first.click()
                w = pp.value
                w.wait_for_load_state()
                title = w.title()
                self.add("زر", "وكيل الجودة", f"{button} (#/{route})", "نافذة", bool(title), title)
                w.close()
            except Exception as e:                               # noqa: BLE001
                self.add("زر", "وكيل الجودة", f"{button} (#/{route})", "", False, str(e)[:200])

        print("\n— 4) أزرار التصدير والتنزيل في الواجهة")
        download("dashboard", "تصدير النموذج الرسمي (Excel)", "xlsx")
        for key in self.college_keys[:3]:
            download(f"college?r={key}", "تصدير Excel", "xlsx")
        popup("training", "التقرير التنفيذي (طباعة / PDF)")

    # ------------------------------------------------------------------ التقرير
    def report(self, out):
        fails = [r for r in self.results if r["ok"] is False]
        warns = [r for r in self.results if r["ok"] == "warn"]
        print(f"\nالنتيجة: {len(self.results)} فحص — {len(fails)} إخفاق، {len(warns)} تنبيه")
        rows = "".join(
            f"<tr class='{'f' if r['ok'] is False else 'w' if r['ok'] == 'warn' else ''}'><td>{r['area']}</td><td>{r['role']}</td>"
            f"<td dir='ltr'>{r['item']}</td><td>{r['status']}</td><td>{'✗' if r['ok'] is False else '!' if r['ok'] == 'warn' else '✓'}</td>"
            f"<td>{r['note']}</td></tr>" for r in sorted(self.results, key=lambda r: (r['ok'] is True, r['ok'] == 'warn', r['area'])))
        with open(out, "w", encoding="utf-8") as f:
            f.write(f"""<!doctype html><html lang="ar" dir="rtl"><meta charset="utf-8"><title>تقرير فحص المنصة</title>
<style>body{{font-family:system-ui,Tahoma;margin:24px;color:#1f2d2c}} h1{{color:#126C66}} table{{border-collapse:collapse;width:100%;font-size:13px}}
td,th{{border-bottom:1px solid #e3ecea;padding:5px 8px;text-align:right}} th{{background:#126C66;color:#fff}} tr.f td{{background:#fdecea}} tr.w td{{background:#fff8e6}}
.s{{display:flex;gap:16px}} .s div{{border:1px solid #d6e6e3;border-radius:8px;padding:10px 16px}} .s b{{font-size:22px;display:block}}</style>
<h1>تقرير فحص المنصة قبل الإطلاق</h1><p>{time.strftime('%Y-%m-%d %H:%M')} · {self.base}</p>
<div class="s"><div><b>{len(self.results)}</b>فحص</div><div><b style="color:#C2463D">{len(fails)}</b>إخفاق</div><div><b style="color:#B7791F">{len(warns)}</b>تنبيه</div></div>
<table><tr><th>المجال</th><th>الدور</th><th>العنصر</th><th>الحالة</th><th></th><th>ملاحظة</th></tr>{rows}</table></html>""")
        print(f"التقرير: {out}")
        return 1 if fails else 0


def _json(b):
    try:
        return json.loads(b)
    except Exception:                                            # noqa: BLE001
        return b


def main():
    ap = argparse.ArgumentParser(description="فحص شامل للمنصة قبل الإطلاق (قراءة فقط)")
    ap.add_argument("--base", default="http://localhost:8000")
    ap.add_argument("--dean", default="dean@ynb", help="بريد حساب وكيل الجودة")
    ap.add_argument("--no-ui", action="store_true", help="تخطّي فحص صفحات الواجهة في المتصفح")
    ap.add_argument("--shots", help="مجلد لحفظ لقطة شاشة لكل صفحة ولكل دور")
    ap.add_argument("--out", default="smoke-report.html")
    a = ap.parse_args()
    s = Smoke(a.base)
    s.dean = a.dean
    roles = s.accounts()
    s.dean_role = next(r for r, v in roles.items() if v["email"] == a.dean)
    s.api(roles)
    s.static()
    if not a.no_ui:
        s.ui(roles, a.shots)
    sys.exit(s.report(a.out))


if __name__ == "__main__":
    main()
