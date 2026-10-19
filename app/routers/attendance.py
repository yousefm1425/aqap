"""سير العملية التدريبية: تقرير التحضير الأسبوعي SO09 من رايات.

- يقرأ المتصفح ملف CSV ويرسل صفوفه الإحصائية (صف لكل شعبة) — لا بيانات شخصية للمتدربين.
- كل أسبوع تدريبي رفع واحد (إعادة الرفع تستبدله)، فتتكوّن سلسلة زمنية للفصل.
- الملف بلا عمود قسم: يُربط كل مدرب بقسمه مرة واحدة (اقتراح تلقائي من مقرراته ثم تأكيد وكيل الجودة).
- المؤشرات: نسبة رصد التحضير (عمود «نسبة التحضير» في رايات) ونسبة الحضور الفعلية = حاضر ÷ (حاضر + غائب).
- تعبئة صف الأسبوع في نموذج 4-3-1 «تقرير قياس سير العملية التدريبية» لكل قسم دون إدخال يدوي.
"""
import re
from datetime import date

from fastapi import APIRouter, Depends
from psycopg import AsyncConnection
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field

from ..forms_engine import clean_follow
from ..security import CurrentUser, current_user, forbid, get_conn, load_cycle, not_found

router = APIRouter(tags=["سير العملية التدريبية"])
MANAGERS = ("quality_dean", "system_admin")
WEEKS_AR = ["الأول", "الثاني", "الثالث", "الرابع", "الخامس", "السادس", "السابع", "الثامن", "التاسع", "العاشر", "الحادي عشر",
            "الثاني عشر", "الثالث عشر", "الرابع عشر", "الخامس عشر", "السادس عشر", "السابع عشر", "الثامن عشر", "التاسع عشر"]

# اقتراح قسم المدرب من أسماء مقرراته (المقررات المشتركة لا تُحتسب)
SHARED = re.compile(r"مقدمة تطبيقات الحاسب|تطبيقات الحاسب المتقدمة|^ريادة الأعمال|أساسيات ريادة|سلامة|^مشروع|التدريب التعاوني")
RULES = [
    ("الدراسات العامة", re.compile(r"إنجليز|انجليز|رياضيات|فيزياء|كيمياء|الثقافة الإسلامية|السلوك الوظيفي|الكتابة الفنية|العربية|بدنية|لياقة")),
    ("الحاسب", re.compile(r"حاسب|شبكات|برمج|الخوارزميات|قواعد البيانات|تشغيل|ويب|أمن|سيبران|البرمجيات|المعلومات|دعم فني|الدعم الفني|انترنت|إنترنت|تصميم|فيديو|الوسائط|الشهادات الاحترافية")),
    ("الكهربائية", re.compile(r"كهرب|دوائر|الكترون|إلكترون|التحكم|القدرة|محولات|آلات|ميكروويف|اتصالات|قياسات|رقمية|الأقمار")),
    ("الميكانيكية", re.compile(r"خراطة|تفريز|جلخ|لحام|تشكيل|ميكاني|نيوماتي|هيدرول|المواد|اختبار مواد|محركات|تبريد|تكييف|إنتاج|ورشة|رسم")),
    ("الإدارية", re.compile(r"محاسب|إدار|تسويق|موارد بشرية|مالية|اقتصاد|سكرتار|مكتب|تأمين|بنوك")),
]


class SectionIn(BaseModel):
    trainer_no: str = Field(min_length=1, max_length=30)
    trainer_name: str | None = Field(default=None, max_length=200)
    section_ref: str | None = Field(default=None, max_length=30)
    course_name: str | None = Field(default=None, max_length=200)
    schedule_type: str | None = Field(default=None, max_length=50)
    total: int = 0
    registered: int = 0
    deprived: int = 0
    withdrawn: int = 0
    slots: int = 0
    present: int = 0
    absent: int = 0
    unlisted_active: int = 0
    unlisted_inactive: int = 0
    recording_pct: float | None = None


class UploadIn(BaseModel):
    week_no: int = Field(ge=1, le=30)
    period_from: date | None = None
    period_to: date | None = None
    file_name: str | None = Field(default=None, max_length=300)
    rows: list[SectionIn] = Field(min_length=1, max_length=5000)


class MapIn(BaseModel):
    items: list[dict] = Field(max_length=500)     # [{trainer_no, department_id}]


def _manager(user: CurrentUser) -> None:
    if not user.has(*MANAGERS):
        raise forbid("رفع تقارير رايات وربط المدربين من صلاحية وكيل الجودة")


def suggest(courses: list[str], depts: dict[str, int]) -> int | None:
    score: dict[str, int] = {}
    for c in courses:
        c = (c or "").strip()
        if not c or SHARED.search(c):
            continue
        for key, rx in RULES:
            if rx.search(c):
                score[key] = score.get(key, 0) + 1
                break
    if not score:
        return None
    best = max(score, key=score.get)
    return next((i for name, i in depts.items() if best in name), None)


async def _actor(conn, user):
    await conn.execute("SELECT set_config('aqap.user_id', %s, true)", (str(user.id),))


@router.post("/cycles/{cycle_id}/attendance", status_code=201)
async def upload(cycle_id: int, body: UploadIn, user: CurrentUser = Depends(current_user), conn: AsyncConnection = Depends(get_conn)):
    cycle = await load_cycle(conn, user, cycle_id)
    _manager(user)
    await _actor(conn, user)
    await conn.execute("DELETE FROM attendance_upload WHERE cycle_id = %s AND week_no = %s", (cycle_id, body.week_no))
    cur = await conn.execute(
        """INSERT INTO attendance_upload (cycle_id, week_no, period_from, period_to, file_name, row_count, uploaded_by)
           VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id""",
        (cycle_id, body.week_no, body.period_from, body.period_to, body.file_name, len(body.rows), user.id))
    uid = (await cur.fetchone())["id"]
    async with conn.cursor() as c:
        await c.executemany(
            """INSERT INTO attendance_section (upload_id, trainer_no, trainer_name, section_ref, course_name, schedule_type, total,
                   registered, deprived, withdrawn, slots, present, absent, unlisted_active, unlisted_inactive, recording_pct)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            [(uid, r.trainer_no.strip(), r.trainer_name, r.section_ref, (r.course_name or "").strip(), r.schedule_type, r.total,
              r.registered, r.deprived, r.withdrawn, r.slots, r.present, r.absent, r.unlisted_active, r.unlisted_inactive,
              r.recording_pct) for r in body.rows])
    # ربط المدربين الجدد بأقسامهم (اقتراح غير مؤكد)
    cur = await conn.execute("SELECT id, name_ar FROM department WHERE institution_id = %s", (cycle["institution_id"],))
    depts = {d["name_ar"]: d["id"] for d in await cur.fetchall()}
    by_trainer: dict[str, dict] = {}
    for r in body.rows:
        t = by_trainer.setdefault(r.trainer_no.strip(), {"name": r.trainer_name, "courses": []})
        t["courses"].append(r.course_name or "")
    cur = await conn.execute("SELECT trainer_no FROM trainer_department WHERE institution_id = %s", (cycle["institution_id"],))
    known = {x["trainer_no"] for x in await cur.fetchall()}
    new = 0
    for no, t in by_trainer.items():
        if no in known:
            await conn.execute("UPDATE trainer_department SET trainer_name = %s WHERE institution_id = %s AND trainer_no = %s",
                               (t["name"], cycle["institution_id"], no))
            continue
        await conn.execute(
            "INSERT INTO trainer_department (institution_id, trainer_no, trainer_name, department_id) VALUES (%s, %s, %s, %s)",
            (cycle["institution_id"], no, t["name"], suggest(t["courses"], depts)))
        new += 1
    cur = await conn.execute("SELECT count(*) AS n FROM trainer_department WHERE institution_id = %s AND NOT confirmed",
                             (cycle["institution_id"],))
    return {"id": uid, "rows": len(body.rows), "new_trainers": new, "unconfirmed": (await cur.fetchone())["n"]}


@router.delete("/cycles/{cycle_id}/attendance/{week_no}")
async def delete_week(cycle_id: int, week_no: int, user: CurrentUser = Depends(current_user), conn: AsyncConnection = Depends(get_conn)):
    await load_cycle(conn, user, cycle_id)
    _manager(user)
    await _actor(conn, user)
    cur = await conn.execute("DELETE FROM attendance_upload WHERE cycle_id = %s AND week_no = %s", (cycle_id, week_no))
    if not cur.rowcount:
        raise not_found("لا يوجد رفع لهذا الأسبوع")
    return {"deleted": True}


@router.get("/attendance/trainers")
async def trainers(user: CurrentUser = Depends(current_user), conn: AsyncConnection = Depends(get_conn)):
    _manager(user)
    cur = await conn.execute(
        """SELECT t.trainer_no, t.trainer_name, t.department_id, t.confirmed,
                  (SELECT array_agg(DISTINCT s.course_name) FROM attendance_section s WHERE s.trainer_no = t.trainer_no) AS courses
             FROM trainer_department t WHERE t.institution_id = %s ORDER BY t.confirmed, t.trainer_name""", (user.institution_id,))
    return await cur.fetchall()


@router.put("/attendance/trainers")
async def map_trainers(body: MapIn, user: CurrentUser = Depends(current_user), conn: AsyncConnection = Depends(get_conn)):
    _manager(user)
    n = 0
    for it in body.items:
        cur = await conn.execute(
            """UPDATE trainer_department SET department_id = %s, confirmed = true, updated_at = now()
                WHERE institution_id = %s AND trainer_no = %s""",
            (it.get("department_id"), user.institution_id, str(it.get("trainer_no"))))
        n += cur.rowcount
    return {"updated": n}


def _agg(rows: list[dict]) -> dict:
    s = lambda k: sum((r[k] or 0) for r in rows)
    present, absent = s("present"), s("absent")
    slots_eff = s("slots") - s("unlisted_inactive")
    return {"sections": len(rows), "trainers": len({r["trainer_no"] for r in rows}), "total": s("total"),
            "registered": s("registered"), "deprived": s("deprived"), "withdrawn": s("withdrawn"),
            "present": present, "absent": absent, "unlisted_active": s("unlisted_active"),
            "attendance": present / (present + absent) if present + absent else None,
            "recording": (present + absent) / slots_eff if slots_eff else None,
            "incomplete": sum(1 for r in rows if (r["recording_pct"] or 0) < 100),
            "not_recorded": sum(1 for r in rows if (r["recording_pct"] or 0) == 0)}


@router.get("/cycles/{cycle_id}/attendance")
async def summary(cycle_id: int, week: int | None = None, user: CurrentUser = Depends(current_user),
                  conn: AsyncConnection = Depends(get_conn)):
    cycle = await load_cycle(conn, user, cycle_id)
    all_depts, depts = user.scope(cycle_id)
    cur = await conn.execute(
        "SELECT id, week_no, period_from, period_to, file_name, row_count, uploaded_at FROM attendance_upload "
        "WHERE cycle_id = %s ORDER BY week_no", (cycle_id,))
    uploads = await cur.fetchall()
    cur = await conn.execute("SELECT id, name_ar FROM department WHERE institution_id = %s ORDER BY code", (cycle["institution_id"],))
    dept_list = [d for d in await cur.fetchall() if all_depts or d["id"] in depts]
    names = {d["id"]: d["name_ar"] for d in dept_list}
    cur = await conn.execute("SELECT count(*) FILTER (WHERE NOT confirmed) AS u, count(*) AS n FROM trainer_department "
                             "WHERE institution_id = %s", (cycle["institution_id"],))
    tstat = await cur.fetchone()
    base = {"uploads": uploads, "departments": dept_list, "can_edit": user.has(*MANAGERS),
            "trainers_unconfirmed": tstat["u"], "trainers_total": tstat["n"], "week": None}
    if not uploads:
        return base
    up = next((u for u in uploads if u["week_no"] == week), uploads[-1])
    cur = await conn.execute(
        """SELECT u.week_no, s.*, td.department_id FROM attendance_section s JOIN attendance_upload u ON u.id = s.upload_id
             LEFT JOIN trainer_department td ON td.institution_id = %s AND td.trainer_no = s.trainer_no
            WHERE u.cycle_id = %s""", (cycle["institution_id"], cycle_id))
    rows = [r for r in await cur.fetchall() if all_depts or r["department_id"] in depts]
    cur_rows = [r for r in rows if r["week_no"] == up["week_no"]]
    by_dept = []
    for d in dept_list:
        rs = [r for r in cur_rows if r["department_id"] == d["id"]]
        if rs:
            by_dept.append({"department_id": d["id"], "name": d["name_ar"], **_agg(rs)})
    unmapped = [r for r in cur_rows if r["department_id"] is None]
    if unmapped and all_depts:
        by_dept.append({"department_id": None, "name": "غير مربوط بقسم", **_agg(unmapped)})
    types: dict[str, list] = {}
    for r in cur_rows:
        types.setdefault(r["schedule_type"] or "—", []).append(r)
    trend = []
    for u in uploads:
        rs = [r for r in rows if r["week_no"] == u["week_no"]]
        point = {"week_no": u["week_no"], **{k: v for k, v in _agg(rs).items() if k in ("attendance", "recording", "incomplete")}}
        point["by_dept"] = {str(d["id"]): _agg([r for r in rs if r["department_id"] == d["id"]])["attendance"] for d in dept_list}
        trend.append(point)
    follow = sorted((r for r in cur_rows if (r["recording_pct"] or 0) < 100),
                    key=lambda r: (float(r["recording_pct"] or 0), r["trainer_name"] or ""))
    courses: dict[str, list] = {}
    for r in cur_rows:
        courses.setdefault(r["course_name"] or "—", []).append(r)
    absence = []
    for c, rs in courses.items():
        a = _agg(rs)
        if a["present"] + a["absent"] >= 30 and a["attendance"] is not None:
            absence.append({"course": c, "sections": len(rs), "attendance": a["attendance"], "absent": a["absent"]})
    absence.sort(key=lambda x: x["attendance"])
    sec = lambda r: {"trainer": r["trainer_name"], "trainer_no": r["trainer_no"], "course": r["course_name"],
                     "section": r["section_ref"], "type": r["schedule_type"], "registered": r["registered"],
                     "recording": float(r["recording_pct"] or 0), "department": names.get(r["department_id"], "غير مربوط"),
                     "attendance": (r["present"] / (r["present"] + r["absent"])) if (r["present"] + r["absent"]) else None}
    buckets = {"100٪": 0, "90–99٪": 0, "50–89٪": 0, "أقل من 50٪": 0, "لم يُرصد": 0}
    for r in cur_rows:
        p = float(r["recording_pct"] or 0)
        buckets["100٪" if p >= 100 else "90–99٪" if p >= 90 else "50–89٪" if p >= 50 else "أقل من 50٪" if p > 0 else "لم يُرصد"] += 1
    return {**base, "week": up, "college": _agg(cur_rows), "by_department": by_dept,
            "by_type": [{"type": k, **_agg(v)} for k, v in sorted(types.items(), key=lambda x: -len(x[1]))],
            "trend": trend, "follow_up": [sec(r) for r in follow[:300]], "follow_up_total": len(follow),
            "low_courses": absence[:12], "recording_buckets": buckets}


@router.post("/cycles/{cycle_id}/attendance/{week_no}/fill-431")
async def fill_431(cycle_id: int, week_no: int, user: CurrentUser = Depends(current_user), conn: AsyncConnection = Depends(get_conn)):
    """يكتب صف الأسبوع (المدربون، المتدربون والحاضرون، الشعب والمنفذة) في نموذج 4-3-1 لكل قسم."""
    cycle = await load_cycle(conn, user, cycle_id)
    _manager(user)
    data = await summary(cycle_id, week_no, user, conn)
    if not data.get("week") or data["week"]["week_no"] != week_no:
        raise not_found("لا يوجد رفع لهذا الأسبوع")
    cur = await conn.execute(
        """SELECT t.id, t.schema FROM form_template t JOIN framework f ON f.code = t.framework_code
            WHERE f.id = %s AND t.requirement_code = '4-3-1'""", (cycle["framework_id"],))
    tpl = await cur.fetchone()
    if tpl is None:
        raise not_found("نموذج 4-3-1 غير متاح في إطار الدورة")
    from .forms import _refresh_summary
    await _actor(conn, user)
    semester = "الثاني" if (data["week"]["period_from"] and data["week"]["period_from"].month in (1, 2, 3, 4, 5, 6)) else "الأول"
    week_ar = WEEKS_AR[week_no - 1] if week_no <= len(WEEKS_AR) else None
    done, skipped = [], []
    cur_rows_by_dept = {d["department_id"]: d for d in data["by_department"] if d["department_id"]}
    cur = await conn.execute(
        """SELECT u.week_no, s.recording_pct, td.department_id FROM attendance_section s JOIN attendance_upload u ON u.id = s.upload_id
             JOIN trainer_department td ON td.institution_id = %s AND td.trainer_no = s.trainer_no
            WHERE u.cycle_id = %s AND u.week_no = %s""", (cycle["institution_id"], cycle_id, week_no))
    executed = {}
    for r in await cur.fetchall():
        executed[r["department_id"]] = executed.get(r["department_id"], 0) + (1 if (r["recording_pct"] or 0) > 0 else 0)
    for dept_id, a in cur_rows_by_dept.items():
        cur = await conn.execute(
            """INSERT INTO form_record (cycle_id, department_id, template_id, created_by) VALUES (%s, %s, %s, %s)
               ON CONFLICT (cycle_id, department_id, template_id) DO UPDATE SET cycle_id = EXCLUDED.cycle_id
               RETURNING id, status, plan_data, follow_data""", (cycle_id, dept_id, tpl["id"], user.id))
        f = await cur.fetchone()
        if f["status"] == "submitted":
            skipped.append(a["name"])
            continue
        weeks = [w for w in (f["follow_data"] or {}).get("weeks", []) if w.get("week") != week_ar]
        present = round(a["registered"] * a["attendance"]) if a["attendance"] is not None else None
        weeks.append({"semester": semester, "week": week_ar, "trainers": a["trainers"], "trainees": a["registered"],
                      "trainees_present": present, "sections": a["sections"], "sections_done": executed.get(dept_id, 0)})
        weeks.sort(key=lambda w: WEEKS_AR.index(w["week"]) if w.get("week") in WEEKS_AR else 99)
        follow = clean_follow(tpl["schema"], f["plan_data"] or {}, {**(f["follow_data"] or {}), "weeks": weeks})
        await conn.execute("UPDATE form_record SET follow_data = %s WHERE id = %s", (Jsonb(follow), f["id"]))
        await _refresh_summary(conn, f["id"])
        done.append(a["name"])
    return {"filled": done, "skipped": skipped}
