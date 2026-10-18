"""أعمال الجودة: جدول مهام متابعة الجودة الأسبوعي (تقارير الاختبارات، منصة المهارات العملية، ملف المقرر...).

كل مهمة تُربط بمعايير فرعية (توافق عام) أو بمتطلبات محددة. عندما يسلّم القسم المهمة برابط الشاهد
يُنشأ الشاهد مرة واحدة ويُربط تلقائياً بتقديرات القسم للمتطلبات المرتبطة، فلا يتكرر الرفع.
"""
from datetime import date, timedelta

from fastapi import APIRouter, Depends
from psycopg import AsyncConnection
from pydantic import BaseModel, Field

from ..security import CurrentUser, current_user, forbid, get_conn, load_cycle, not_found
from .evidence_links import assert_link_ok

router = APIRouter(tags=["أعمال الجودة"])
MANAGERS = ("quality_dean", "system_admin")
SUBMITTERS = ("dept_coordinator", "hod", "faculty")
EDITABLE = ("draft", "returned")

ORD = ["", "الأول", "الثاني", "الثالث", "الرابع", "الخامس", "السادس", "السابع", "الثامن", "التاسع", "العاشر",
       "الحادي عشر", "الثاني عشر", "الثالث عشر", "الرابع عشر", "الخامس عشر", "السادس عشر", "السابع عشر",
       "الثامن عشر", "التاسع عشر", "العشرون"]
DAY = {0: "بداية الأسبوع", 2: "الثلاثاء", 3: "الأربعاء", 4: None}   # إزاحة عن الأحد

PATTERNS_COND = "في حال تطبيق أنماط التدريب (عن بعد - ذاتي - مدمج) في القسم"
L2_COND = "في حال تطبيق نظام الجودة المستوى الثاني"
COURSE_FILE = ("متابعة تطبيق ورفع ملف المدرب وتوصيف المقرر على منصة التدريب الإلكتروني (البلاك بورد أو تقني) "
               "حسب النموذج المعتمد")
SKILLS = "تقرير تفعيل منصة المهارات العملية"
# (الأسبوع، المهمة، إزاحة اليوم، الشرط، ملاحظات، المعايير الفرعية المتوافقة)
DEFAULT_TASKS = [
    (3, "تقرير متابعة تنفيذ تحقيق منهجية قياس أنماط التدريب المختلفة", 4, PATTERNS_COND, "نماذج منهجية قياس أنماط التدريب", ["4-1"]),
    (3, "بدء أعمال التدقيق الذاتي لتطبيق نظام جودة التدريب (المستوى الثاني)", 4, L2_COND, None, ["6-1"]),
    (4, COURSE_FILE, 0, None, "متابعة تطبيق ملف المقرر على جميع المقررات وحسب الشعب", ["3-3", "4-3"]),
    (5, "تقرير جاهزية القسم لبدء الاختبار الفصلي الأول", 4, None, None, ["3-1"]),
    (6, "التقرير الشهري الأول لتفعيل منصة المهارات العملية (من بداية الأسبوع 2 إلى نهاية 5)", 2, None, None, ["4-1"]),
    (7, "تقرير تنفيذ الاختبار الفصلي الأول حسب اللوائح المنظمة (حسب الأسبوع المنفذ 6 أو 7)", 3, None, None, ["3-1"]),
    (7, "تقرير متابعة تنفيذ تحقيق منهجية قياس أنماط التدريب المختلفة", 4, PATTERNS_COND, "نماذج منهجية قياس أنماط التدريب", ["4-1"]),
    (8, "تقرير تحليل نتائج المتدربين للاختبار الفصلي الأول", 4, None, None, ["3-1", "2-2"]),
    (8, COURSE_FILE, 4, None, "متابعة تطبيق ملف المقرر على جميع المقررات وحسب الشعب", ["3-3", "4-3"]),
    (9, "تقرير الإجراءات التحسينية لتحليل نتائج الاختبار الفصلي الأول", 2, None, None, ["3-1"]),
    (10, "التقرير الشهري الثاني لتفعيل منصة المهارات العملية (من بداية الأسبوع 6 إلى نهاية 9)", 2, None, None, ["4-1"]),
    (11, "تقرير جاهزية القسم لبدء الاختبار الفصلي الثاني", 4, None, None, ["3-1"]),
    (11, "تقرير متابعة تنفيذ تحقيق نظام جودة التدريب (المستوى الثاني)", 4, L2_COND, None, ["6-1"]),
    (12, "تقرير متطلبات وتهيئة المتدربين لقياس جودة مخرجات التدريب", 2, None, None, ["2-2"]),
    (13, "تقرير تنفيذ الاختبار الفصلي الثاني حسب اللوائح المنظمة (حسب الأسبوع المنفذ 12 أو 13)", 3, None, None, ["3-1"]),
    (14, "التقرير الشهري الثالث لتفعيل منصة المهارات العملية (من بداية الأسبوع 10 إلى نهاية 13)", 2, None, None, ["4-1"]),
    (14, "تقرير تنفيذ قياس جودة مخرجات التدريب", 4, None,
     "قبل نهاية الأسبوع الرابع عشر أو بعد تنفيذ الاختبار حسب الموعد المحدد من الإدارة المعنية", ["2-2"]),
    (14, "تقرير الإجراءات التحسينية لتحليل نتائج الاختبار الفصلي الثاني", 4, None, None, ["3-1"]),
    (14, "تقرير جاهزية القسم لبدء الاختبارات النهائية", 4, None, None, ["3-1"]),
    (15, "متابعة تنفيذ الخطط التحسينية لملاحظات تحليل نتائج الاختبارين الفصليين الأول والثاني وتنفيذ التوصيات", 4, None, None, ["3-1", "6-4"]),
    (15, "تقرير تحليل نتائج المتدربين للاختبار الفصلي الثاني ومقارنتها بنتائج الاختبار الفصلي الأول", 2, None, None, ["3-1", "2-2"]),
    (15, "تقرير الإجراءات التحسينية لتحليل نتائج الاختبار (فصلي - نهائي)", 2, None,
     "متابعة تسليم الإجراءات التحسينية لتحليل نتائج الاختبارين الفصليين الأول والثاني", ["3-1"]),
    (15, "تقرير متابعة تنفيذ تحقيق نظام جودة التدريب (المستوى الثاني)", 4, L2_COND, None, ["6-1"]),
    (18, "تقرير خطط تحسين قياس جودة مخرجات التدريب", 4, None, None, ["2-2"]),
    (18, "تقرير التقييم النهائي لمنصة المهارات العملية", 4, None, None, ["4-1"]),
    (19, "تقرير تنفيذ الاختبارات النهائية", 4, None, None, ["3-1"]),
]


def hint_for(week: int, offset: int) -> str:
    w = ORD[week] if week < len(ORD) else str(week)
    if offset == 0:
        return f"بداية الأسبوع {w}"
    day = DAY.get(offset)
    return f"قبل نهاية الأسبوع {w}" + (f" (يوم {day})" if day else "")


class TaskIn(BaseModel):
    week_no: int = Field(ge=1, le=30)
    title_ar: str = Field(min_length=3, max_length=500)
    due_on: date | None = None
    due_hint_ar: str | None = Field(default=None, max_length=300)
    condition_ar: str | None = Field(default=None, max_length=300)
    notes_ar: str | None = Field(default=None, max_length=1000)


class SeedIn(BaseModel):
    semester_start: date            # أحد الأسبوع الأول من الفصل التدريبي


class LinksIn(BaseModel):
    sub_standard_codes: list[str] = Field(default_factory=list, max_length=30)
    requirement_codes: list[str] = Field(default_factory=list, max_length=100)


class SubmitIn(BaseModel):
    department_id: int
    url: str | None = Field(default=None, max_length=2000)
    note_ar: str | None = Field(default=None, max_length=1000)
    not_applicable: bool = False


class ReviewIn(BaseModel):
    department_id: int
    decision: str = Field(pattern="^(approved|returned)$")
    note_ar: str | None = Field(default=None, max_length=1000)


def _manager(user: CurrentUser) -> None:
    if not user.has(*MANAGERS):
        raise forbid("إدارة أعمال الجودة من صلاحية وكيل الجودة")


async def _task(conn: AsyncConnection, user: CurrentUser, task_id: int) -> dict:
    cur = await conn.execute("SELECT * FROM quality_task WHERE id = %s", (task_id,))
    t = await cur.fetchone()
    if t is None:
        raise not_found("المهمة غير موجودة")
    t["cycle"] = await load_cycle(conn, user, t["cycle_id"])
    return t


async def _actor(conn: AsyncConnection, user: CurrentUser) -> None:
    await conn.execute("SELECT set_config('aqap.user_id', %s, true)", (str(user.id),))


async def reflect(conn: AsyncConnection, task_id: int, department_id: int, evidence_id: int, user_id: int) -> tuple[int, int]:
    """يربط شاهد المهمة بتقديرات القسم للمتطلبات المرتبطة (المسودة أو المعادة فقط). يعيد (رُبط، تُخطّي)."""
    cur = await conn.execute(
        """SELECT a.id, a.status,
                  EXISTS (SELECT 1 FROM assessment_evidence ae WHERE ae.assessment_id = a.id AND ae.evidence_id = %(e)s) AS has
             FROM quality_task_link l JOIN quality_task t ON t.id = l.task_id
             JOIN assessment a ON a.cycle_id = t.cycle_id AND a.requirement_id = l.requirement_id AND a.department_id = %(d)s
            WHERE l.task_id = %(t)s AND NOT is_excluded(a.requirement_id, a.department_id, a.cycle_id)""",
        {"t": task_id, "d": department_id, "e": evidence_id})
    linked = skipped = 0
    for a in await cur.fetchall():
        if a["has"]:
            linked += 1
        elif a["status"] in EDITABLE:
            await conn.execute(
                "INSERT INTO assessment_evidence (assessment_id, evidence_id, note, linked_by) VALUES (%s, %s, %s, %s)",
                (a["id"], evidence_id, "من أعمال الجودة", user_id))
            linked += 1
        else:
            skipped += 1
    return linked, skipped


@router.get("/cycles/{cycle_id}/quality-tasks")
async def list_tasks(cycle_id: int, user: CurrentUser = Depends(current_user), conn: AsyncConnection = Depends(get_conn)):
    await load_cycle(conn, user, cycle_id)
    all_depts, depts = user.scope(cycle_id)
    cur = await conn.execute(
        """SELECT d.id, d.name_ar FROM cycle_department cd JOIN department d ON d.id = cd.department_id
            WHERE cd.cycle_id = %(c)s AND (%(all)s OR d.id = ANY(%(d)s)) ORDER BY d.code""",
        {"c": cycle_id, "all": all_depts, "d": depts})
    departments = await cur.fetchall()
    ids = [d["id"] for d in departments]
    cur = await conn.execute("SELECT * FROM quality_task WHERE cycle_id = %s ORDER BY week_no, sort_order, id", (cycle_id,))
    tasks = await cur.fetchall()
    tids = [t["id"] for t in tasks]
    cur = await conn.execute(
        """SELECT l.task_id, CASE WHEN l.requirement_id IS NULL THEN 'sub' ELSE 'req' END AS kind,
                  COALESCE(r.code, ss.code) AS code, COALESCE(r.text_ar, ss.title_ar) AS title,
                  COALESCE(ss.code, rss.code) AS sub_standard_code
             FROM quality_task_link l LEFT JOIN sub_standard ss ON ss.id = l.sub_standard_id
             LEFT JOIN requirement r ON r.id = l.requirement_id LEFT JOIN sub_standard rss ON rss.id = r.sub_standard_id
            WHERE l.task_id = ANY(%s) ORDER BY 2 DESC, 3""", (tids,))
    links = await cur.fetchall()
    cur = await conn.execute(
        """SELECT s.task_id, s.department_id, s.status, s.note_ar, s.review_note_ar, s.linked_count, s.submitted_at,
                  e.url, u.full_name_ar AS submitted_by_name
             FROM quality_task_submission s LEFT JOIN evidence e ON e.id = s.evidence_id
             LEFT JOIN app_user u ON u.id = s.submitted_by
            WHERE s.task_id = ANY(%s) AND s.department_id = ANY(%s)""", (tids, ids))
    subs = await cur.fetchall()
    for t in tasks:
        t["links"] = [x for x in links if x["task_id"] == t["id"]]
        t["submissions"] = {str(s["department_id"]): s for s in subs if s["task_id"] == t["id"]}
    return {"can_edit": user.has(*MANAGERS), "today": date.today(), "departments": departments, "tasks": tasks}


@router.get("/cycles/{cycle_id}/quality-tasks/catalog")
async def catalog(cycle_id: int, user: CurrentUser = Depends(current_user), conn: AsyncConnection = Depends(get_conn)):
    """المعايير الفرعية ومتطلباتها لاختيار الربط وعرض التوافق."""
    cycle = await load_cycle(conn, user, cycle_id)
    cur = await conn.execute(
        """SELECT s.code AS standard_code, s.title_ar AS standard_title, ss.code, ss.title_ar AS title,
                  COALESCE(json_agg(json_build_object('code', r.code, 'text', r.text_ar) ORDER BY r.sort_order)
                           FILTER (WHERE r.id IS NOT NULL), '[]') AS requirements
             FROM sub_standard ss JOIN standard s ON s.id = ss.standard_id
             LEFT JOIN requirement r ON r.sub_standard_id = ss.id AND r.is_active
            WHERE s.framework_id = %s GROUP BY s.code, s.title_ar, s.sort_order, ss.code, ss.title_ar, ss.sort_order
            ORDER BY s.sort_order, ss.sort_order""", (cycle["framework_id"],))
    return await cur.fetchall()


@router.post("/cycles/{cycle_id}/quality-tasks", status_code=201)
async def create_task(cycle_id: int, body: TaskIn, user: CurrentUser = Depends(current_user), conn: AsyncConnection = Depends(get_conn)):
    await load_cycle(conn, user, cycle_id)
    _manager(user)
    await _actor(conn, user)
    cur = await conn.execute(
        """INSERT INTO quality_task (cycle_id, week_no, title_ar, due_on, due_hint_ar, condition_ar, notes_ar, created_by)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
        (cycle_id, body.week_no, body.title_ar.strip(), body.due_on, body.due_hint_ar, body.condition_ar, body.notes_ar, user.id))
    return {"id": (await cur.fetchone())["id"]}


@router.post("/cycles/{cycle_id}/quality-tasks/seed", status_code=201)
async def seed_tasks(cycle_id: int, body: SeedIn, user: CurrentUser = Depends(current_user), conn: AsyncConnection = Depends(get_conn)):
    """يحمّل جدول أعمال الجودة المعتمد للفصل بتواريخ محسوبة من بداية الفصل، مع التوافق المقترح مع المعايير الفرعية."""
    cycle = await load_cycle(conn, user, cycle_id)
    _manager(user)
    cur = await conn.execute("SELECT count(*) AS n FROM quality_task WHERE cycle_id = %s", (cycle_id,))
    if (await cur.fetchone())["n"]:
        raise forbid("جدول أعمال الجودة محمّل مسبقاً لهذه الدورة")
    start = body.semester_start - timedelta(days=(body.semester_start.weekday() + 1) % 7)   # أحد ذلك الأسبوع
    await _actor(conn, user)
    for i, (week, title, off, cond, notes, subs) in enumerate(DEFAULT_TASKS):
        cur = await conn.execute(
            """INSERT INTO quality_task (cycle_id, week_no, title_ar, due_on, due_hint_ar, condition_ar, notes_ar, sort_order, created_by)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
            (cycle_id, week, title, start + timedelta(days=(week - 1) * 7 + off), hint_for(week, off), cond, notes, i, user.id))
        tid = (await cur.fetchone())["id"]
        await conn.execute(
            """INSERT INTO quality_task_link (task_id, sub_standard_id)
               SELECT %s, ss.id FROM sub_standard ss JOIN standard s ON s.id = ss.standard_id
                WHERE s.framework_id = %s AND ss.code = ANY(%s) ON CONFLICT DO NOTHING""",
            (tid, cycle["framework_id"], subs))
    return {"created": len(DEFAULT_TASKS)}


@router.patch("/quality-tasks/{task_id}")
async def update_task(task_id: int, body: TaskIn, user: CurrentUser = Depends(current_user), conn: AsyncConnection = Depends(get_conn)):
    await _task(conn, user, task_id)
    _manager(user)
    await _actor(conn, user)
    await conn.execute(
        """UPDATE quality_task SET week_no = %s, title_ar = %s, due_on = %s, due_hint_ar = %s, condition_ar = %s, notes_ar = %s
            WHERE id = %s""",
        (body.week_no, body.title_ar.strip(), body.due_on, body.due_hint_ar, body.condition_ar, body.notes_ar, task_id))
    return {"id": task_id}


@router.delete("/quality-tasks/{task_id}")
async def delete_task(task_id: int, user: CurrentUser = Depends(current_user), conn: AsyncConnection = Depends(get_conn)):
    await _task(conn, user, task_id)
    _manager(user)
    await _actor(conn, user)
    await conn.execute("DELETE FROM quality_task WHERE id = %s", (task_id,))
    return {"deleted": True}


@router.put("/quality-tasks/{task_id}/links")
async def set_links(task_id: int, body: LinksIn, user: CurrentUser = Depends(current_user), conn: AsyncConnection = Depends(get_conn)):
    """يحدد التوافق. ربط متطلب جديد ينعكس فوراً على الشواهد التي سلّمتها الأقسام سابقاً."""
    t = await _task(conn, user, task_id)
    _manager(user)
    fw = t["cycle"]["framework_id"]
    cur = await conn.execute(
        """SELECT ss.id, ss.code FROM sub_standard ss JOIN standard s ON s.id = ss.standard_id
            WHERE s.framework_id = %s AND ss.code = ANY(%s)""", (fw, body.sub_standard_codes))
    subs = await cur.fetchall()
    cur = await conn.execute(
        """SELECT r.id, r.code FROM requirement r JOIN sub_standard ss ON ss.id = r.sub_standard_id
             JOIN standard s ON s.id = ss.standard_id WHERE s.framework_id = %s AND r.code = ANY(%s)""",
        (fw, body.requirement_codes))
    reqs = await cur.fetchall()
    unknown = (set(body.sub_standard_codes) - {x["code"] for x in subs}) | (set(body.requirement_codes) - {x["code"] for x in reqs})
    if unknown:
        raise not_found(f"رموز غير موجودة في إطار الدورة: {'، '.join(sorted(unknown))}")
    await _actor(conn, user)
    await conn.execute("DELETE FROM quality_task_link WHERE task_id = %s", (task_id,))
    for s in subs:
        await conn.execute("INSERT INTO quality_task_link (task_id, sub_standard_id) VALUES (%s, %s)", (task_id, s["id"]))
    for r in reqs:
        await conn.execute("INSERT INTO quality_task_link (task_id, requirement_id) VALUES (%s, %s)", (task_id, r["id"]))
    cur = await conn.execute(
        """SELECT department_id, evidence_id FROM quality_task_submission
            WHERE task_id = %s AND evidence_id IS NOT NULL AND status IN ('submitted','approved')""", (task_id,))
    for s in await cur.fetchall():
        linked, _ = await reflect(conn, task_id, s["department_id"], s["evidence_id"], user.id)
        await conn.execute("UPDATE quality_task_submission SET linked_count = %s WHERE task_id = %s AND department_id = %s",
                           (linked, task_id, s["department_id"]))
    return {"sub_standards": len(subs), "requirements": len(reqs)}


@router.post("/quality-tasks/{task_id}/submit")
async def submit_task(task_id: int, body: SubmitIn, user: CurrentUser = Depends(current_user), conn: AsyncConnection = Depends(get_conn)):
    t = await _task(conn, user, task_id)
    dept = body.department_id
    if not (user.has(*SUBMITTERS, department_id=dept, cycle_id=t["cycle_id"]) or user.has(*MANAGERS)):
        raise forbid("تسليم أعمال الجودة من صلاحية منسق القسم أو رئيسه")
    cur = await conn.execute("SELECT 1 FROM cycle_department WHERE cycle_id = %s AND department_id = %s", (t["cycle_id"], dept))
    if await cur.fetchone() is None:
        raise not_found("القسم ليس ضمن الدورة")
    await _actor(conn, user)
    if body.not_applicable:
        if not (body.note_ar or "").strip():
            raise forbid("اكتب سبب عدم الانطباق في الملاحظة")
        evidence_id, linked, skipped, status = None, 0, 0, "na"
    else:
        url = (body.url or "").strip()
        if not url:
            raise forbid("أرفق رابط الشاهد من مجلد OneDrive/SharePoint")
        await assert_link_ok(conn, user.institution_id, url)
        cur = await conn.execute(
            """INSERT INTO evidence (institution_id, department_id, title_ar, description_ar, kind, url, created_by)
               VALUES (%s, %s, %s, %s, 'link', %s, %s) RETURNING id""",
            (user.institution_id, dept, f"أعمال الجودة (الأسبوع {t['week_no']}): {t['title_ar']}"[:300], body.note_ar, url, user.id))
        evidence_id = (await cur.fetchone())["id"]
        status = "submitted"
    await conn.execute(
        """INSERT INTO quality_task_submission (task_id, department_id, status, evidence_id, note_ar, submitted_by)
           VALUES (%s, %s, %s, %s, %s, %s)
           ON CONFLICT (task_id, department_id) DO UPDATE SET status = EXCLUDED.status, evidence_id = EXCLUDED.evidence_id,
                 note_ar = EXCLUDED.note_ar, submitted_by = EXCLUDED.submitted_by, submitted_at = now(),
                 review_note_ar = NULL, reviewed_by = NULL, reviewed_at = NULL""",
        (task_id, dept, status, evidence_id, body.note_ar, user.id))
    if evidence_id:
        linked, skipped = await reflect(conn, task_id, dept, evidence_id, user.id)
        await conn.execute("UPDATE quality_task_submission SET linked_count = %s WHERE task_id = %s AND department_id = %s",
                           (linked, task_id, dept))
    return {"status": status, "linked": linked, "skipped": skipped}


@router.post("/quality-tasks/{task_id}/review")
async def review_task(task_id: int, body: ReviewIn, user: CurrentUser = Depends(current_user), conn: AsyncConnection = Depends(get_conn)):
    await _task(conn, user, task_id)
    _manager(user)
    if body.decision == "returned" and not (body.note_ar or "").strip():
        raise forbid("اكتب سبب الإعادة للقسم")
    await _actor(conn, user)
    cur = await conn.execute(
        """UPDATE quality_task_submission SET status = %s, review_note_ar = %s, reviewed_by = %s, reviewed_at = now()
            WHERE task_id = %s AND department_id = %s AND status IN ('submitted','approved','returned','na')""",
        (body.decision, body.note_ar, user.id, task_id, body.department_id))
    if not cur.rowcount:
        raise not_found("لم يسلّم القسم هذه المهمة بعد")
    return {"status": body.decision}
