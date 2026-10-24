"""تجربة تشغيل كاملة لقسم «تقنية الاتصالات» عبر واجهة المنصة نفسها (API) بحسابات الأدوار الفعلية:

  منسق الجودة بالقسم: يعبّئ كل الخطط والتقارير والمحاضر، يرفق الشواهد، يقيّم ذاتياً، ويرفع.
  رئيس القسم       : يعتمد (ويعيد نموذجاً واحداً لإظهار مسار الإعادة).
  وكيل الجودة       : يحيل للتدقيق، يعتمد نهائياً، ويعيد متطلباً ناقص الشواهد.
  المدقق (المقيّم الداخلي): يحكم على كل متطلب، ويعتمد خطط التحسين أو يعيدها.

  python scripts/demo_tc_run.py --base http://localhost:8000
  python scripts/demo_tc_run.py --base http://127.0.0.1:$PORT --auto   # مرة واحدة: يتوقف إن كان للقسم نماذج مسبقاً

البيانات افتراضية بالكامل (أسماء وأرقام) ومتسقة بين النماذج — تعمل فقط في وضع التطوير (دخول بالبريد).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from demo_tc_data import AUDIT_OVERRIDE, COORD, DEAN, HOD, NOT_MET, PARTIAL, TN, hdate  # noqa: E402
from demo_tc_forms import BUILDERS, DONE, NOT, PART  # noqa: E402
from demo_tc_minutes import MEETINGS  # noqa: E402

DOMAIN = "mttvtcedu-my.sharepoint.com"
ROOT_PATH = "/personal/yousefm_tvtc_gov_sa/Documents/Quality cat2027"
STD = {"1": "المعيار الاول القيادة الادارية", "2": "المعيار الثاني نواتج التدريب", "3": "المعيار الثالث المناهج وأدوات القياس والتقويم",
       "4": "المعيار الرابع التدريب والموارد المساندة", "5": "المعيار الخامس البيئة التدريبية", "6": "المعيار السادس الاستدامة"}
FACULTY = [("tc.t1@ynb", TN[2]), ("tc.t2@ynb", TN[3]), ("tc.t3@ynb", TN[6]), ("tc.t4@ynb", TN[8])]


class Api:
    def __init__(self, base: str):
        self.base = base.rstrip("/") + "/api/v1"
        self.tokens: dict[str, str] = {}

    def login(self, email: str) -> str:
        if email not in self.tokens:
            self.tokens[email] = self.call("POST", "/auth/dev-token", {"email": email}, None)["access_token"]
        return self.tokens[email]

    def call(self, method: str, path: str, body=None, who: str | None = "dean@ynb", ok404=False):
        headers = {"content-type": "application/json"}
        if who:
            headers["authorization"] = "Bearer " + self.login(who)
        data = json.dumps(body, ensure_ascii=False, default=str).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, headers=headers, method=method)
        for attempt in range(4):
            try:
                with urllib.request.urlopen(req, timeout=300) as r:
                    raw = r.read()
                    return json.loads(raw) if raw and r.headers.get_content_type() == "application/json" else None
            except urllib.error.HTTPError as e:
                msg = e.read().decode("utf-8", "replace")
                if e.code == 404 and ok404:
                    return None
                if e.code >= 500 and attempt < 3:
                    time.sleep(3)
                    continue
                raise RuntimeError(f"{method} {path} → {e.code}: {msg[:400]}") from None
            except urllib.error.URLError:
                if attempt == 3:
                    raise
                time.sleep(5)


def log(*a):
    print(*a, flush=True)


def wait_up(api: Api, seconds: int = 300) -> None:
    t0 = time.time()
    while time.time() - t0 < seconds:
        try:
            urllib.request.urlopen(api.base.rsplit("/api/v1", 1)[0] + "/health", timeout=5)
            return
        except Exception:
            time.sleep(3)
    raise SystemExit("المنصة لم تبدأ")


def folder_url(parts: list[str]) -> str:
    full = "/".join([ROOT_PATH, *parts])
    lib = "/".join(ROOT_PATH.split("/")[:4])
    return f"https://{DOMAIN}{urllib.parse.quote(lib)}/Forms/All.aspx?id={urllib.parse.quote(full, safe='')}"


def subst(x, url: str):
    if isinstance(x, dict):
        return {k: subst(v, url) for k, v in x.items()}
    if isinstance(x, list):
        return [subst(v, url) for v in x]
    return url if x == "@EV" else x


def split(schema: dict, data: dict) -> tuple[dict, dict]:
    """صفوف كاملة → بيانات التخطيط (صفوف بمعرّفات) + المتابعة (حسب المعرّف) وفق مرحلة كل عمود."""
    plan, follow = {}, {}
    for s in schema["sections"]:
        k, v = s["key"], data.get(s["key"])
        if v is None:
            continue
        if s["type"] == "table":
            cols = [c for c in s["columns"] if c["type"] != "computed"]
            if s.get("phase") == "follow":
                follow[k] = [{"id": r.get("id") or f"r{i}", **{c["key"]: r.get(c["key"]) for c in cols}} for i, r in enumerate(v, 1)]
                continue
            rows, fmap = [], {}
            for i, r in enumerate(v, 1):
                rid = r.get("id") or f"r{i}"
                rows.append({"id": rid, **{c["key"]: r.get(c["key"]) for c in cols if c["phase"] == "plan"}})
                fv = {c["key"]: r.get(c["key"]) for c in cols if c["phase"] == "follow"}
                if any(x is not None for x in fv.values()):
                    fmap[rid] = fv
            plan[k], follow[k] = rows, fmap
        elif s["type"] == "fields":
            plan[k] = {c["key"]: v.get(c["key"]) for c in s["fields"] if c["phase"] == "plan"}
            follow[k] = {c["key"]: v.get(c["key"]) for c in s["fields"] if c["phase"] == "follow"}
        elif s["type"] == "text":
            (follow if s.get("phase") == "follow" else plan)[k] = v
    return plan, follow


# ---------------------------------------------------------------------------
def setup(api: Api, cycle: dict, dept: dict) -> dict:
    users = {u["email"]: u for u in api.call("GET", "/users")["users"]}
    ids = {}

    def ensure(email, name, role):
        u = users.get(email)
        uid = u["id"] if u else api.call("POST", "/users", {"email": email, "full_name_ar": name})["id"]
        if u and u["full_name_ar"] != name:
            api.call("PATCH", f"/users/{uid}", {"full_name_ar": name})
        if not u or not any(r["role"] == role and r.get("department_id") in (dept["id"], None) for r in u["roles"]):
            api.call("POST", f"/users/{uid}/roles", {"role": role, "department_id": dept["id"] if role in ("hod", "dept_coordinator", "faculty") else None})
        ids[email] = uid
    ensure("coord.tc@ynb", COORD, "dept_coordinator")
    ensure("hod.tc@ynb", HOD, "hod")
    for email, name in FACULTY:
        ensure(email, name, "faculty")
    api.call("PATCH", f"/users/{users['dean@ynb']['id']}", {"full_name_ar": DEAN})
    ids["dean@ynb"] = users["dean@ynb"]["id"]
    s = api.call("GET", "/settings/evidence")
    if DOMAIN not in s.get("allowed_link_domains", []) or s.get("attachment_mode") == "files":
        api.call("PUT", "/settings/evidence", {"attachment_mode": "both" if s.get("attachment_mode") == "files" else s["attachment_mode"],
                                               "allowed_link_domains": sorted(set(s.get("allowed_link_domains", [])) | {DOMAIN})})
    return ids


class Ctx:
    def __init__(self, api, cycle, dept, folders, subs):
        self.api, self.cycle, self.dept, self.folders, self.subs = api, cycle, dept, folders, subs

    def url(self, req_code: str) -> str:
        sub = req_code.split("/")[0]
        sub = "-".join(sub.split("-")[:2])
        if sub in self.folders:
            return self.folders[sub]
        std = sub.split("-")[0]
        return folder_url([STD.get(std, f"المعيار {std}"), f"{sub} {self.subs.get(sub, '')}".strip(), self.dept["name_ar"]])


C = "coord.tc@ynb"
H = "hod.tc@ynb"
DEAN_E = "dean@ynb"
AUD = "auditor@ynb"


def fill_forms(ctx: Ctx) -> None:
    api, cy, dept = ctx.api, ctx.cycle["id"], ctx.dept["id"]
    tpls = api.call("GET", f"/cycles/{cy}/forms/templates?department_id={dept}", who=C)
    returned_once = False
    for t in tpls:
        code = t["requirement_code"]
        if dept in (t.get("excluded_for") or []) or code not in BUILDERS:
            log(f"  — تخطي {code}")
            continue
        rec = next(iter(t["records"]), None)
        f = api.call("GET", f"/forms/{rec['form_id']}", who=C) if rec else api.call("POST", f"/cycles/{cy}/forms", {"template_id": t["id"], "department_id": dept}, who=C)
        if f["status"] == "approved":
            continue
        if f["status"] == "submitted":            # تشغيل سابق توقف قبل الاعتماد
            api.call("POST", f"/forms/{f['id']}/transition", {"to_status": "approved", "comment": "معتمد"}, who=H)
            continue
        url = ctx.url(code)
        plan, follow = split(f["schema"], subst(BUILDERS[code](f["schema"]), url))
        f = api.call("PUT", f"/forms/{f['id']}", {"plan_data": plan, "follow_data": follow}, who=C)
        # خطط التحسين المولّدة تلقائياً من المهام غير المنفذة: يكمل المنسق الإجراء والمسؤول والموعد
        imps = f["follow_data"].get("improvements") or []
        changed = False
        for i, row in enumerate(imps):
            if row.get("_src") and not row.get("action"):
                row.update({"action": "معالجة سبب عدم التنفيذ ضمن خطة الفصل القادم ومتابعته في مجلس القسم",
                            "date": hdate(2, 6 + i % 6), "owner": "رئيس القسم" if i % 2 else "منسق الجودة بالقسم",
                            "evidence": url, "status": PART if i % 3 else DONE,
                            "obstacles": "ارتباط التنفيذ بجهات خارج القسم" if i % 3 else None,
                            "solutions": "التنسيق المبكر وتحديد بديل داخل القسم" if i % 3 else None})
                changed = True
        if changed:
            f = api.call("PUT", f"/forms/{f['id']}", {"follow_data": f["follow_data"]}, who=C)
        if f["missing"]:
            log(f"  ! {code} ناقص: {f['missing'][:3]}")
            continue
        api.call("POST", f"/forms/{f['id']}/attachments", {"title_ar": f"مجلد شواهد {code} — {ctx.dept['name_ar']}", "url": url,
                                                           "note": "الشواهد الأصلية الموقعة في مجلد القسم على OneDrive"}, who=C)
        api.call("POST", f"/forms/{f['id']}/transition", {"to_status": "submitted"}, who=C)
        if not returned_once:
            api.call("POST", f"/forms/{f['id']}/transition", {"to_status": "returned",
                     "comment": "يرجى توضيح أسباب المهام المنفذة جزئياً في عمود المعوقات قبل الاعتماد"}, who=H)
            api.call("POST", f"/forms/{f['id']}/transition", {"to_status": "submitted", "comment": "تم توضيح الأسباب"}, who=C)
            returned_once = True
        api.call("POST", f"/forms/{f['id']}/transition", {"to_status": "approved", "comment": "معتمد"}, who=H)
        log(f"  ✓ {code} {t['title_ar'][:50]}")


def fill_minutes(ctx: Ctx, ids: dict) -> None:
    api, cy, dept = ctx.api, ctx.cycle["id"], ctx.dept["id"]
    tpls = api.call("GET", f"/cycles/{cy}/minutes/templates?department_id={dept}", who=C)
    people = [(HOD, "رئيس القسم", ids["hod.tc@ynb"]), (COORD, "منسق الجودة بالقسم", ids["coord.tc@ynb"])] + \
             [(n, "عضو هيئة تدريب", ids[e]) for e, n in FACULTY] + [(n, "عضو هيئة تدريب", None) for n in TN[4:6] + TN[9:11]]
    for t in tpls:
        meets = MEETINGS.get(t["requirement_code"])
        if not meets or t["approved"] >= len(meets):
            continue
        for old in api.call("GET", f"/cycles/{cy}/minutes?department_id={dept}&template_id={t['id']}", who=C):
            if old["status"] in ("draft", "returned"):          # بقايا تشغيل سابق لم يكتمل
                api.call("DELETE", f"/minutes/{old.get('minutes_id') or old.get('id')}", who=C)
            elif old["status"] == "submitted":
                api.call("POST", f"/minutes/{old.get('minutes_id') or old.get('id')}/transition", {"to_status": "approved"}, who=H)
        done = len([1 for old in api.call("GET", f"/cycles/{cy}/minutes?department_id={dept}&template_id={t['id']}", who=C)
                    if old["status"] == "approved"])
        for sem, d, tm, place, agenda in meets[done:]:
            m = api.call("POST", f"/cycles/{cy}/minutes", {"template_id": t["id"], "department_id": dept}, who=C)
            body = {"title_ar": t["title_ar"], "semester": sem, "meeting_date": d.isoformat(), "start_time": tm, "location_ar": place,
                    "follow_up_owner": "رئيس القسم",
                    "agenda": [{"title_ar": a, "recommendations": [{k: v for k, v in r.items() if k != "_fu"} for r in recs]} for a, recs in agenda],
                    "attendees": [{"name_ar": n, "role_ar": role, "user_id": uid} for n, role, uid in people]}
            m = api.call("PUT", f"/minutes/{m['id']}", body, who=C)
            api.call("POST", f"/minutes/{m['id']}/attachments", {"title_ar": f"كشف حضور موقع — {t['title_ar'][:60]}", "url": ctx.url(t["requirement_code"]),
                                                                 "note": "النسخة الموقعة ورقياً"}, who=C)
            api.call("POST", f"/minutes/{m['id']}/transition", {"to_status": "submitted"}, who=C)
            api.call("POST", f"/minutes/{m['id']}/transition", {"to_status": "approved", "comment": "معتمد"}, who=H)
            for email in ["hod.tc@ynb", "coord.tc@ynb"] + [e for e, _ in FACULTY[:3]]:
                api.call("POST", f"/minutes/{m['id']}/attendees/confirm", who=email)
            full = api.call("GET", f"/minutes/{m['id']}", who=C)
            fus = [r["_fu"] for _, recs in agenda for r in recs]
            for rec, (st, ob, so) in zip([r for a in full["agenda"] for r in a["recommendations"]], fus):
                api.call("PATCH", f"/minutes/recommendations/{rec['id']}/follow-up", {"fu_status": st, "fu_obstacles": ob, "fu_solutions": so}, who=C)
            api.call("POST", f"/minutes/{m['id']}/archive", who=C)
            log(f"  ✓ محضر {t['requirement_code']} — {sem}")


def self_notes(code: str, rating: str, docs: int) -> str:
    base = f"أُعدّت وثائق المتطلب في المنصة ({docs} وثيقة معتمدة) وأُرفقت الشواهد الأصلية في مجلد القسم على OneDrive."
    if rating == "partial":
        return base + " نُفذ جزء من المهام وتم توثيق أسباب عدم الاستكمال وخطط التحسين داخل التقرير."
    if rating == "not_met":
        return base + " لم يتحقق المستهدف لأسباب خارجة عن القسم موثقة في التقرير، مع خطة تحسين معتمدة."
    return base + " نُفذت جميع المهام المخطط لها في موعدها."


def assess(ctx: Ctx) -> None:
    api, cy, dept = ctx.api, ctx.cycle["id"], ctx.dept["id"]
    rows = api.call("GET", f"/cycles/{cy}/assessments?department_id={dept}", who=C)
    redo = None
    for a in rows:
        code = a.get("requirement_code") or a.get("code")
        if a["status"] == "final":
            continue
        # تقدير بدأه القسم سابقاً: يُعاد إليه بمسار الإعادة النظامي ليُستكمل وفق التقارير المعتمدة
        back = "تحديث التقييم الذاتي وربطه بالتقارير والمحاضر المعتمدة في المنصة"
        if a["status"] == "hod_approved":
            api.call("POST", f"/assessments/{a['id']}/transition", {"to_status": "under_audit"}, who=DEAN_E)
            a["status"] = "under_audit"
        step = {"submitted": H, "under_audit": AUD, "audited": DEAN_E}.get(a["status"])
        if step:
            api.call("POST", f"/assessments/{a['id']}/transition", {"to_status": "returned", "comment": back}, who=step)
        rating = "partial" if code in PARTIAL else "not_met" if code in NOT_MET else "met"
        ev = api.call("POST", "/evidence", {"title_ar": f"شواهد المتطلب {code} — {ctx.dept['name_ar']}", "kind": "link", "url": ctx.url(code),
                                            "department_id": dept, "description_ar": "مجلد الشواهد الأصلية للمتطلب"}, who=C)
        api.call("POST", f"/assessments/{a['id']}/evidence", {"evidence_id": ev["id"], "note": "مجلد شواهد المتطلب"}, who=C)
        d = api.call("GET", f"/assessments/{a['id']}", who=C)
        docs = len([x for x in d.get("evidence", []) if x])
        api.call("PATCH", f"/assessments/{a['id']}/self", {"self_rating": rating, "self_adequacy": "suitable" if rating == "met" else "insufficient",
                                                          "self_notes": self_notes(code, rating, docs)}, who=C)
        api.call("POST", f"/assessments/{a['id']}/transition", {"to_status": "submitted"}, who=C)
        api.call("POST", f"/assessments/{a['id']}/transition", {"to_status": "hod_approved", "comment": "معتمد من رئيس القسم"}, who=H)
        api.call("POST", f"/assessments/{a['id']}/transition", {"to_status": "under_audit"}, who=DEAN_E)
        verdict, recm = AUDIT_OVERRIDE.get(code, ("conforms", None))
        if recm is None:
            recm = ("الشواهد كافية وتدعم التقييم الذاتي." if rating == "met"
                    else "نتفق مع التقييم الذاتي؛ تُتابع خطة التحسين حتى الإغلاق ويُرفق شاهد الإنجاز.")
        api.call("PATCH", f"/assessments/{a['id']}/external", {"ext_verdict": verdict, "ext_recommendation": recm}, who=AUD)
        api.call("POST", f"/assessments/{a['id']}/transition", {"to_status": "audited"}, who=AUD)
        if verdict == "insufficient":
            api.call("POST", f"/assessments/{a['id']}/transition", {"to_status": "returned", "comment": recm}, who=DEAN_E)
            redo = (a, code, rating)
            continue
        api.call("POST", f"/assessments/{a['id']}/transition", {"to_status": "final", "comment": "اعتماد نهائي"}, who=DEAN_E)
    log(f"  ✓ {len(rows)} متطلباً")
    if redo:                         # المتطلب المعاد: يستكمل القسم الشاهد ويُعاد الحكم
        a, code, rating = redo
        ev = api.call("POST", "/evidence", {"title_ar": f"محاضر اجتماعات مدربي المقررات المشتركة — الفصل الثاني ({code})", "kind": "link",
                                            "url": ctx.url(code), "department_id": dept}, who=C)
        api.call("POST", f"/assessments/{a['id']}/evidence", {"evidence_id": ev["id"], "note": "استكمال الشاهد بعد ملاحظة المدقق"}, who=C)
        api.call("POST", f"/assessments/{a['id']}/transition", {"to_status": "submitted", "comment": "أُرفقت محاضر الفصل الثاني"}, who=C)
        api.call("POST", f"/assessments/{a['id']}/transition", {"to_status": "hod_approved"}, who=H)
        api.call("POST", f"/assessments/{a['id']}/transition", {"to_status": "under_audit"}, who=DEAN_E)
        api.call("PATCH", f"/assessments/{a['id']}/external", {"ext_verdict": "conforms", "ext_recommendation": "استُكمل الشاهد المطلوب؛ الحكم منطبق."}, who=AUD)
        api.call("POST", f"/assessments/{a['id']}/transition", {"to_status": "audited"}, who=AUD)
        api.call("POST", f"/assessments/{a['id']}/transition", {"to_status": "final"}, who=DEAN_E)
        log(f"  ✓ {code}: أُعيد ثم اعتُمد بعد استكمال الشاهد")


ACTIONS = {
    "1-2-2": ("جدولة الزيارات الإشرافية للفصل الثاني في الأسابيع 3–12 بعيداً عن الاختبارات ولجان المناقشة", 100),
    "2-1-2": ("تحديث بيانات تواصل أولياء الأمور في أسبوع التسجيل وربط الإشعار بمنصة الإرشاد", 100),
    "2-2-1": ("خطة علاجية لمتدربي التدريب التعاوني دون المستوى في الصفات الشخصية بالتنسيق مع جهات التدريب", 60),
    "2-2-7": ("مخاطبة الجهات المستضيفة للزيارات الميدانية قبل الفصل بشهر وجدولة البرامج خارج أسابيع الاختبارات", 100),
    "4-1-3": ("استكمال تطبيق التقييم العملي على المحاكي في مقرر تقنيات الجيل الخامس", 50),
    "6-3-1": ("اعتماد خطة طوارئ القسم وتحديث سجل المخاطر فصلياً", 100),
    "4-2-2": ("متابعة طلبات التجهيزات المتأخرة (نقاط وصول Wi-Fi 6، ترخيص محاكي 5G) مع إدارة المشتريات", 40),
    "5-1-3": ("معالجة ملاحظات السلامة في المعامل وتوفير معدات الحماية الشخصية الناقصة", 70),
}


def improvement_plans(ctx: Ctx) -> None:
    api, cy, dept = ctx.api, ctx.cycle["id"], ctx.dept["id"]
    api.call("POST", f"/cycles/{cy}/actions/generate", who=DEAN_E)
    acts = api.call("GET", f"/cycles/{cy}/actions?department_id={dept}", who=C)
    revised = False
    for x in acts:
        if x["status"] != "draft":
            continue
        code = x.get("requirement_code") or ""
        text, pct = ACTIONS.get(code, ("معالجة أسباب عدم التحقق ومتابعة التنفيذ في مجلس القسم", 50))
        api.call("PATCH", f"/actions/{x['id']}", {"action_ar": text, "owner_label": "رئيس القسم",
                                                  "due_date": (date(2026, 5, 14) if pct == 100 else date(2026, 12, 17)).isoformat(),
                                                  "priority": 1 if code in NOT_MET else 2}, who=C)
        api.call("POST", f"/actions/{x['id']}/transition", {"to_status": "submitted"}, who=C)
        if not revised:
            api.call("POST", f"/actions/{x['id']}/transition", {"to_status": "revision", "adequacy": "insufficient",
                     "comment": "حدّد مؤشر قياس واضحاً للإنجاز وموعداً وسيطاً للمتابعة"}, who=AUD)
            api.call("PATCH", f"/actions/{x['id']}", {"action_ar": text + " — مؤشر الإنجاز: 100% من البنود، ومتابعة وسيطة في الأسبوع الثامن"}, who=C)
            api.call("POST", f"/actions/{x['id']}/transition", {"to_status": "submitted", "comment": "أُضيف مؤشر الإنجاز"}, who=C)
            revised = True
        api.call("POST", f"/actions/{x['id']}/transition", {"to_status": "approved", "comment": "الخطة مناسبة"}, who=AUD)
        if pct == 100:
            ev = api.call("POST", "/evidence", {"title_ar": f"شاهد إنجاز خطة التحسين — {code}", "kind": "link", "url": ctx.url(code), "department_id": dept}, who=C)
            api.call("PATCH", f"/actions/{x['id']}", {"progress_pct": 100, "completion_evidence_id": ev["id"], "completed_on": date(2026, 4, 30).isoformat()}, who=C)
            api.call("POST", f"/actions/{x['id']}/transition", {"to_status": "completed"}, who=C)
            api.call("POST", f"/actions/{x['id']}/transition", {"to_status": "verified", "comment": "تم التحقق من شاهد الإنجاز"}, who=DEAN_E)
        else:
            api.call("PATCH", f"/actions/{x['id']}", {"progress_pct": pct}, who=C)
        log(f"  ✓ خطة تحسين {code} ({pct}%)")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8000")
    ap.add_argument("--auto", action="store_true", help="مرة واحدة فقط: يتخطى إن كان لقسم الاتصالات نماذج")
    args = ap.parse_args()
    api = Api(args.base)
    wait_up(api)
    cycle = next(c for c in api.call("GET", "/cycles") if c["status"] in ("open", "external_review") and "أنماط" not in c["title_ar"])
    depts = api.call("GET", f"/cycles/{cycle['id']}/reports/departments")
    dept = next(d for d in depts if "اتصالات" in (d.get("department_name") or d.get("name_ar") or ""))
    dept = {"id": dept.get("department_id") or dept.get("id"), "name_ar": dept.get("department_name") or dept.get("name_ar")}
    if args.auto:
        rows = api.call("GET", f"/cycles/{cycle['id']}/assessments?department_id={dept['id']}")
        if rows and all(a["status"] == "final" for a in rows):
            log("تجربة قسم الاتصالات نُفذت مسبقاً — لا شيء")
            return
    log(f"الدورة: {cycle['title_ar']} — القسم: {dept['name_ar']}")
    ids = setup(api, cycle, dept)
    folders = {}
    for f in api.call("GET", f"/cycles/{cycle['id']}/folders?department_id={dept['id']}") or []:
        if f.get("department_id") == dept["id"] and f.get("sub_standard_code") and f.get("url"):
            folders[f["sub_standard_code"]] = f["url"]
    tree = api.call("GET", f"/cycles/{cycle['id']}/forms/templates", who=C)
    subs = {t["sub_standard_code"]: t["sub_standard_title"] for t in tree if t.get("sub_standard_code")}
    ctx = Ctx(api, cycle, dept, folders, subs)
    log("① الخطط والتقارير"); fill_forms(ctx)
    log("② المحاضر"); fill_minutes(ctx, ids)
    log("③ التقييم الذاتي والتدقيق والاعتماد النهائي"); assess(ctx)
    log("④ خطط التحسين"); improvement_plans(ctx)
    log("✓ اكتملت تجربة قسم الاتصالات")


if __name__ == "__main__":
    main()
