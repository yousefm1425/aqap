"""الخط الزمني لتنفيذ متطلبات نظام الجودة (المستوى الثاني).

وكيل الجودة يحمّل الخطة المعتمدة (أسابيع تنفيذ كل متطلب في الفصلين) مع أسابيع التقويم التدريبي.
كل قسم يحدد المسؤول (Planner) عن كل متطلب، ويؤشّر كل موعد منجزاً برابط الشاهد أو «لا ينطبق».
الشاهد يُنشأ مرة واحدة ويُربط تلقائياً بتقدير القسم للمتطلب نفسه، فلا يُرفع مرتين.
"""
from datetime import date, timedelta

from fastapi import APIRouter, Depends
from psycopg import AsyncConnection
from pydantic import BaseModel, Field

from ..security import CurrentUser, current_user, forbid, get_conn, load_cycle, not_found
from .evidence_links import assert_link_ok

router = APIRouter(tags=["الخط الزمني للمستوى الثاني"])
MANAGERS = ("quality_dean", "system_admin")
SUBMITTERS = ("dept_coordinator", "hod", "faculty")
PLANNERS = ("dept_coordinator", "hod")
EDITABLE = ("draft", "returned")

WEEKLY = tuple(range(1, 17))
# الخطة المعتمدة 1447هـ: رمز المتطلب → (أسابيع الفصل الأول، أسابيع الفصل الثاني، موعد بلا أسبوع)
PLAN_1447: dict[str, tuple[tuple[int, ...], tuple[int, ...], str | None]] = {
    "1-1-1": ((3,), (), None),
    "1-1-2": ((4, 10, 17), (2, 3), None),
    "1-2-1": ((4, 11, 16), (3,), None),
    "1-2-2": ((4, 9, 17), (), None),
    "1-2-3": ((2,), (2,), None),
    "1-3-1": ((9,), (), None),
    "1-3-2": ((9,), (), None),
    "1-3-3": ((4,), (3,), None),
    "1-3-4": ((3,), (3,), None),
    "1-4-1": ((2, 7, 15), (3,), None),
    "1-4-2": ((2, 7, 13), (3,), None),
    "2-1-1": ((4, 7, 13), (3,), None),
    "2-1-2": ((4, 13), (), None),
    "2-1-3": ((1, 17), (), None),
    "2-2-1": ((14,), (), None),
    "2-2-2": ((8, 14), (), None),
    "2-2-3": ((14,), (), None),
    "2-2-4": ((2,), (2,), None),
    "2-2-5": ((16,), (), None),
    "2-2-6": ((7, 14), (), None),
    "2-2-7": ((5, 10, 15), (), None),
    "2-2-8": ((14,), (), None),
    "2-2-9": ((2, 8, 14), (), None),
    "2-2-10": ((15,), (), None),
    "3-1-1": ((8, 14), (), None),
    "3-1-2": ((5, 11, 15), (), None),
    "3-2-1": ((8,), (), None),
    "3-2-2": ((9,), (), None),
    "3-2-3": ((3, 8, 15), (), None),
    "3-2-4": ((3, 8, 15), (), None),
    "3-2-5": ((4, 9, 15), (), None),
    "3-3-1": ((4,), (), None),
    "3-3-2": ((5,), (), None),
    "4-1-1": ((4,), (), None),
    "4-1-2": ((6,), (), None),
    "4-1-3": ((3, 10), (3,), None),
    "4-2-1": ((2,), (), None),
    "4-2-2": ((2, 9, 15), (), None),
    "4-3-1": (WEEKLY, (), None),
    "4-3-2": ((4, 11, 16), (), None),
    "5-1-1": ((1, 7, 16), (), None),
    "5-1-2": (WEEKLY, (), None),
    "5-1-3": ((2, 10, 15), (), None),
    "5-2-1": ((2, 10, 15), (), None),
    "6-1-1": ((), (), "ملف موحد (متابعة وكالة الجودة)"),
    "6-2-1": ((4, 10, 17), (2, 3), None),
    "6-3-1": ((), (2,), "مستمر"),
    "6-4-1": ((15, 19), (2,), None),
}

# التقويم التدريبي 1448هـ (2026/2027م) المعتمد من المؤسسة: بداية كل فصل، والأسابيع التي تقع فيها إجازة كاملة
CALENDAR_1448 = {
    1: {"start": date(2026, 8, 23), "breaks": {date(2026, 11, 22)}},                       # إجازة الخريف
    2: {"start": date(2027, 1, 17), "breaks": {date(2027, 2, 28), date(2027, 3, 7),         # عيد الفطر
                                               date(2027, 5, 9), date(2027, 5, 16)}},        # عيد الأضحى
}
WEEKS_PER_SEMESTER = 19          # 17 أسبوع تدريب + أسبوعا الاختبارات النهائية
EXAM_FROM = 18


def sunday(d: date) -> date:
    return d - timedelta(days=(d.weekday() + 1) % 7)


def build_weeks(start: date, breaks: set[date], n: int = WEEKS_PER_SEMESTER) -> list[date]:
    out, k, s = [], 0, sunday(start)
    while len(out) < n:
        wk = s + timedelta(days=7 * k)
        k += 1
        if wk not in breaks:
            out.append(wk)
    return out


async def week_starts_for(conn: AsyncConnection, cycle_id: int, semester_start: date, n: int = 20) -> list[date]:
    """بدايات أسابيع التدريب للفصل الذي يبدأ في semester_start: من تقويم الدورة المحمّل إن وُجد، ثم التقويم المعتمد،
    وإلا فأسابيع متتالية. الإجازات لا تُحسب أسابيع."""
    first = sunday(semester_start)
    cur = await conn.execute(
        """SELECT semester, starts_on FROM training_week WHERE cycle_id = %s AND week_no = 1""", (cycle_id,))
    sem = next((r["semester"] for r in await cur.fetchall() if r["starts_on"] == first), None)
    if sem is not None:
        cur = await conn.execute("SELECT starts_on FROM training_week WHERE cycle_id = %s AND semester = %s ORDER BY week_no",
                                 (cycle_id, sem))
        out = [r["starts_on"] for r in await cur.fetchall()]
    else:
        cal = next((c for c in CALENDAR_1448.values() if sunday(c["start"]) == first), None)
        out = build_weeks(first, cal["breaks"] if cal else set(), n)
    while len(out) < n:
        out.append(out[-1] + timedelta(days=7))
    return out


async def realign_quality_tasks(conn: AsyncConnection, cycle_id: int) -> int:
    """يعيد حساب مواعيد «أعمال الجودة» المحمّلة على أسابيع التقويم التدريبي، محافظاً على يوم التسليم داخل الأسبوع."""
    cur = await conn.execute("SELECT id, week_no, due_on FROM quality_task WHERE cycle_id = %s AND due_on IS NOT NULL", (cycle_id,))
    tasks = await cur.fetchall()
    cur = await conn.execute("SELECT semester, week_no, starts_on FROM training_week WHERE cycle_id = %s", (cycle_id,))
    tw = {(r["semester"], r["week_no"]): r["starts_on"] for r in await cur.fetchall()}
    starts = {s: tw[(s, 1)] for s in (1, 2) if (s, 1) in tw}
    n = 0
    for t in tasks:
        off = (t["due_on"].weekday() + 1) % 7
        assumed = sunday(t["due_on"]) - timedelta(days=7 * (t["week_no"] - 1))   # بداية الفصل التي حُسب منها الموعد
        sem = min(starts, key=lambda s: abs((starts[s] - assumed).days), default=None)
        ws = tw.get((sem, t["week_no"])) if sem else None
        if ws and ws + timedelta(days=off) != t["due_on"]:
            await conn.execute("UPDATE quality_task SET due_on = %s WHERE id = %s", (ws + timedelta(days=off), t["id"]))
            n += 1
    return n


def locate(weeks: list[dict], today: date) -> dict:
    """موقع اليوم في التقويم: الفصل والأسبوع، أو آخر أسبوع مرّ إن كان اليوم في إجازة."""
    last = None
    for w in sorted(weeks, key=lambda x: x["starts_on"]):
        if w["starts_on"] <= today < w["starts_on"] + timedelta(days=7):
            return {"semester": w["semester"], "week_no": w["week_no"], "in_break": False}
        if w["starts_on"] <= today:
            last = w
    if last is None:
        return {"semester": 1, "week_no": 0, "in_break": False}
    return {"semester": last["semester"], "week_no": last["week_no"], "in_break": True}


class SeedIn(BaseModel):
    semester1_start: date | None = None     # الافتراضي: التقويم التدريبي 1448هـ
    semester2_start: date | None = None
    replace: bool = False                   # إعادة التحميل تحذف المواعيد وما أُنجز عليها


class ProgressIn(BaseModel):
    department_id: int
    url: str | None = Field(default=None, max_length=2000)
    note_ar: str | None = Field(default=None, max_length=1000)
    not_applicable: bool = False


class PlannerIn(BaseModel):
    requirement_code: str = Field(min_length=3, max_length=20)
    department_id: int
    owner_name_ar: str = Field(default="", max_length=200)


def _manager(user: CurrentUser) -> None:
    if not user.has(*MANAGERS):
        raise forbid("إدارة الخط الزمني من صلاحية وكيل الجودة")


async def _actor(conn: AsyncConnection, user: CurrentUser) -> None:
    await conn.execute("SELECT set_config('aqap.user_id', %s, true)", (str(user.id),))


async def _in_cycle(conn: AsyncConnection, cycle_id: int, dept: int) -> None:
    cur = await conn.execute("SELECT 1 FROM cycle_department WHERE cycle_id = %s AND department_id = %s", (cycle_id, dept))
    if await cur.fetchone() is None:
        raise not_found("القسم ليس ضمن الدورة")


@router.get("/cycles/{cycle_id}/l2-timeline")
async def timeline(cycle_id: int, user: CurrentUser = Depends(current_user), conn: AsyncConnection = Depends(get_conn, scope="function")):
    cycle = await load_cycle(conn, user, cycle_id)
    all_depts, depts = user.scope(cycle_id)
    cur = await conn.execute(
        """SELECT d.id, d.name_ar FROM cycle_department cd JOIN department d ON d.id = cd.department_id
            WHERE cd.cycle_id = %(c)s AND (%(all)s OR d.id = ANY(%(d)s)) ORDER BY d.code""",
        {"c": cycle_id, "all": all_depts, "d": depts})
    departments = await cur.fetchall()
    ids = [d["id"] for d in departments]
    cur = await conn.execute("SELECT semester, week_no, starts_on, is_exam FROM training_week WHERE cycle_id = %s ORDER BY 1, 2",
                             (cycle_id,))
    weeks = await cur.fetchall()
    cur = await conn.execute(
        """SELECT r.id, r.code, r.text_ar, ss.code AS sub_standard_code, ss.title_ar AS sub_standard_title,
                  s.code AS standard_code, s.title_ar AS standard_title
             FROM requirement r JOIN sub_standard ss ON ss.id = r.sub_standard_id JOIN standard s ON s.id = ss.standard_id
            WHERE s.framework_id = %s AND r.id IN (SELECT requirement_id FROM l2_schedule WHERE cycle_id = %s)
            ORDER BY s.sort_order, ss.sort_order, r.sort_order""", (cycle["framework_id"], cycle_id))
    reqs = await cur.fetchall()
    cur = await conn.execute(
        """SELECT id, requirement_id, semester, week_no, label_ar FROM l2_schedule WHERE cycle_id = %s
            ORDER BY semester, week_no NULLS FIRST""", (cycle_id,))
    sched = await cur.fetchall()
    cur = await conn.execute(
        """SELECT p.schedule_id, p.department_id, p.status, p.note_ar, p.linked, p.done_at, e.url, u.full_name_ar AS done_by_name
             FROM l2_progress p JOIN l2_schedule s ON s.id = p.schedule_id LEFT JOIN evidence e ON e.id = p.evidence_id
             LEFT JOIN app_user u ON u.id = p.done_by
            WHERE s.cycle_id = %s AND p.department_id = ANY(%s)""", (cycle_id, ids))
    prog = {}
    for p in await cur.fetchall():
        prog.setdefault(p["schedule_id"], {})[str(p["department_id"])] = p
    cur = await conn.execute(
        "SELECT requirement_id, department_id, owner_name_ar FROM l2_planner WHERE cycle_id = %s AND department_id = ANY(%s)",
        (cycle_id, ids))
    planners = {}
    for p in await cur.fetchall():
        planners.setdefault(p["requirement_id"], {})[str(p["department_id"])] = p["owner_name_ar"]
    for r in reqs:
        r["occurrences"] = [{**s, "progress": prog.get(s["id"], {})} for s in sched if s["requirement_id"] == r["id"]]
        r["planners"] = planners.get(r["id"], {})
        r.pop("id")
    today = date.today()
    return {"can_edit": user.has(*MANAGERS), "today": today, "now": locate(weeks, today) if weeks else None,
            "departments": departments, "weeks": weeks, "requirements": reqs}


@router.post("/cycles/{cycle_id}/l2-timeline/seed", status_code=201)
async def seed(cycle_id: int, body: SeedIn, user: CurrentUser = Depends(current_user), conn: AsyncConnection = Depends(get_conn, scope="function")):
    """يحمّل خطة المستوى الثاني المعتمدة 1447هـ وأسابيع التقويم التدريبي للدورة."""
    cycle = await load_cycle(conn, user, cycle_id)
    _manager(user)
    cur = await conn.execute("SELECT count(*) AS n FROM l2_schedule WHERE cycle_id = %s", (cycle_id,))
    if (await cur.fetchone())["n"] and not body.replace:
        raise forbid("الخط الزمني محمّل مسبقاً لهذه الدورة")
    await _actor(conn, user)
    if body.replace:
        await conn.execute("DELETE FROM l2_schedule WHERE cycle_id = %s", (cycle_id,))
    await conn.execute("DELETE FROM training_week WHERE cycle_id = %s", (cycle_id,))
    starts = {1: body.semester1_start, 2: body.semester2_start}
    for sem, cal in CALENDAR_1448.items():
        custom = starts[sem]
        weeks = build_weeks(custom, set()) if custom else build_weeks(cal["start"], cal["breaks"])
        for i, wk in enumerate(weeks, 1):
            await conn.execute("INSERT INTO training_week VALUES (%s, %s, %s, %s, %s)", (cycle_id, sem, i, wk, i >= EXAM_FROM))
    realigned = await realign_quality_tasks(conn, cycle_id)
    cur = await conn.execute(
        """SELECT r.id, r.code FROM requirement r JOIN sub_standard ss ON ss.id = r.sub_standard_id
             JOIN standard s ON s.id = ss.standard_id WHERE s.framework_id = %s AND r.code = ANY(%s)""",
        (cycle["framework_id"], list(PLAN_1447)))
    found = {r["code"]: r["id"] for r in await cur.fetchall()}
    rows = 0
    for code, (s1, s2, label) in PLAN_1447.items():
        rid = found.get(code)
        if rid is None:
            continue
        slots = [(1, w, None) for w in s1] + [(2, w, None) for w in s2]
        if label:
            slots.append((1, None, label))
        for sem, wk, lab in slots:
            await conn.execute(
                """INSERT INTO l2_schedule (cycle_id, requirement_id, semester, week_no, label_ar, created_by)
                   VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING""", (cycle_id, rid, sem, wk, lab, user.id))
            rows += 1
    return {"requirements": len(found), "occurrences": rows, "missing": sorted(set(PLAN_1447) - set(found)),
            "quality_tasks_realigned": realigned}


async def _link(conn: AsyncConnection, cycle_id: int, requirement_id: int, dept: int, evidence_id: int, user_id: int) -> bool:
    """يربط الشاهد بتقدير القسم للمتطلب إن كان قابلاً للتعديل. يعيد هل الشاهد مربوط."""
    cur = await conn.execute(
        """SELECT a.id, a.status,
                  EXISTS (SELECT 1 FROM assessment_evidence ae WHERE ae.assessment_id = a.id AND ae.evidence_id = %(e)s) AS has
             FROM assessment a WHERE a.cycle_id = %(c)s AND a.requirement_id = %(r)s AND a.department_id = %(d)s
              AND NOT is_excluded(a.requirement_id, a.department_id, a.cycle_id)""",
        {"c": cycle_id, "r": requirement_id, "d": dept, "e": evidence_id})
    a = await cur.fetchone()
    if a is None:
        return False
    if a["has"]:
        return True
    if a["status"] not in EDITABLE:
        return False
    await conn.execute(
        "INSERT INTO assessment_evidence (assessment_id, evidence_id, note, linked_by) VALUES (%s, %s, %s, %s)",
        (a["id"], evidence_id, "من الخط الزمني للمستوى الثاني", user_id))
    return True


async def _slot(conn: AsyncConnection, user: CurrentUser, schedule_id: int) -> dict:
    cur = await conn.execute(
        """SELECT s.*, r.code FROM l2_schedule s JOIN requirement r ON r.id = s.requirement_id WHERE s.id = %s""", (schedule_id,))
    s = await cur.fetchone()
    if s is None:
        raise not_found("الموعد غير موجود")
    await load_cycle(conn, user, s["cycle_id"])
    return s


@router.post("/l2-timeline/{schedule_id}/progress")
async def mark(schedule_id: int, body: ProgressIn, user: CurrentUser = Depends(current_user),
               conn: AsyncConnection = Depends(get_conn, scope="function")):
    s = await _slot(conn, user, schedule_id)
    dept = body.department_id
    if not (user.has(*SUBMITTERS, department_id=dept, cycle_id=s["cycle_id"]) or user.has(*MANAGERS)):
        raise forbid("تأشير الإنجاز من صلاحية منسق القسم أو رئيسه")
    await _in_cycle(conn, s["cycle_id"], dept)
    await _actor(conn, user)
    evidence_id, linked = None, False
    if body.not_applicable:
        if not (body.note_ar or "").strip():
            raise forbid("اكتب سبب عدم الانطباق في الملاحظة")
        status = "na"
    else:
        status = "done"
        url = (body.url or "").strip()
        if not url:
            raise forbid("أرفق رابط الشاهد من مجلد OneDrive/SharePoint")
        await assert_link_ok(conn, user.institution_id, url)
        when = f"الأسبوع {s['week_no']} من الفصل {'الأول' if s['semester'] == 1 else 'الثاني'}" if s["week_no"] else (s["label_ar"] or "")
        cur = await conn.execute(
            """INSERT INTO evidence (institution_id, department_id, title_ar, description_ar, kind, url, created_by)
               VALUES (%s, %s, %s, %s, 'link', %s, %s) RETURNING id""",
            (user.institution_id, dept, f"المتطلب {s['code']} — {when}"[:300], body.note_ar, url, user.id))
        evidence_id = (await cur.fetchone())["id"]
        linked = await _link(conn, s["cycle_id"], s["requirement_id"], dept, evidence_id, user.id)
    await conn.execute(
        """INSERT INTO l2_progress (schedule_id, department_id, status, evidence_id, note_ar, linked, done_by)
           VALUES (%s, %s, %s, %s, %s, %s, %s)
           ON CONFLICT (schedule_id, department_id) DO UPDATE SET status = EXCLUDED.status, evidence_id = EXCLUDED.evidence_id,
                 note_ar = EXCLUDED.note_ar, linked = EXCLUDED.linked, done_by = EXCLUDED.done_by, done_at = now()""",
        (schedule_id, dept, status, evidence_id, body.note_ar, linked, user.id))
    return {"status": status, "linked": linked}


@router.delete("/l2-timeline/{schedule_id}/progress")
async def unmark(schedule_id: int, department_id: int, user: CurrentUser = Depends(current_user),
                 conn: AsyncConnection = Depends(get_conn, scope="function")):
    """يلغي تأشير الإنجاز. الشاهد يبقى في سجل الشواهد وفي تقدير المتطلب."""
    s = await _slot(conn, user, schedule_id)
    if not (user.has(*SUBMITTERS, department_id=department_id, cycle_id=s["cycle_id"]) or user.has(*MANAGERS)):
        raise forbid("تعديل الإنجاز من صلاحية منسق القسم أو رئيسه")
    await _actor(conn, user)
    cur = await conn.execute("DELETE FROM l2_progress WHERE schedule_id = %s AND department_id = %s", (schedule_id, department_id))
    if not cur.rowcount:
        raise not_found("لم يُؤشَّر هذا الموعد بعد")
    return {"deleted": True}


@router.put("/cycles/{cycle_id}/l2-timeline/planner")
async def set_planner(cycle_id: int, body: PlannerIn, user: CurrentUser = Depends(current_user),
                      conn: AsyncConnection = Depends(get_conn, scope="function")):
    cycle = await load_cycle(conn, user, cycle_id)
    dept = body.department_id
    if not (user.has(*PLANNERS, department_id=dept, cycle_id=cycle_id) or user.has(*MANAGERS)):
        raise forbid("تحديد المسؤول من صلاحية منسق القسم أو رئيسه")
    await _in_cycle(conn, cycle_id, dept)
    cur = await conn.execute(
        """SELECT r.id FROM requirement r JOIN sub_standard ss ON ss.id = r.sub_standard_id
             JOIN standard s ON s.id = ss.standard_id WHERE s.framework_id = %s AND r.code = %s""",
        (cycle["framework_id"], body.requirement_code))
    r = await cur.fetchone()
    if r is None:
        raise not_found(f"المتطلب {body.requirement_code} غير موجود في إطار الدورة")
    await _actor(conn, user)
    name = body.owner_name_ar.strip()
    if not name:
        await conn.execute("DELETE FROM l2_planner WHERE cycle_id = %s AND requirement_id = %s AND department_id = %s",
                           (cycle_id, r["id"], dept))
    else:
        await conn.execute(
            """INSERT INTO l2_planner (cycle_id, requirement_id, department_id, owner_name_ar, updated_by) VALUES (%s, %s, %s, %s, %s)
               ON CONFLICT (cycle_id, requirement_id, department_id)
               DO UPDATE SET owner_name_ar = EXCLUDED.owner_name_ar, updated_by = EXCLUDED.updated_by, updated_at = now()""",
            (cycle_id, r["id"], dept, name, user.id))
    return {"owner_name_ar": name}
