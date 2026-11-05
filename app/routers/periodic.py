"""التقارير الدورية: تقويم أعمال جودة التدريب 1448هـ أسبوعاً بأسبوع، مع حالة كل قسم.

البند المرتبط بنموذج قسم تُحسب حالته من صفوف نموذج القسم نفسه (لا يُرفع مرتين)، ويفتح منه وكيل الجودة التقرير المجمّع.
البنود الأخرى تُؤشَّر منجزة برابط الشاهد أو «لا ينطبق»: بند القسم يؤشّره القسم، وبند الكلية يؤشّره وكيل الجودة.
"""
from datetime import date, timedelta

from fastapi import APIRouter, Depends
from psycopg import AsyncConnection
from pydantic import BaseModel, Field

from .. import college_reports as cr
from ..periodic_catalog import BY_KEY, CATALOG_1448, HOLIDAYS_1448, INSTRUCTIONS, SHORT_WEEKS
from ..security import CurrentUser, current_user, forbid, get_conn, load_cycle, not_found
from .evidence_links import assert_link_ok
from .l2_timeline import CALENDAR_1448, locate, week_starts_for

router = APIRouter(tags=["التقارير الدورية"])
MANAGERS = ("quality_dean", "system_admin")
SUBMITTERS = ("dept_coordinator", "hod")
SEM_NAME = {1: "الأول", 2: "الثاني"}


class ProgressIn(BaseModel):
    department_id: int | None = None          # بلا قسم = بند على مستوى الكلية
    url: str | None = Field(default=None, max_length=2000)
    note_ar: str | None = Field(default=None, max_length=1000)
    not_applicable: bool = False


async def _departments(conn: AsyncConnection, user: CurrentUser, cycle_id: int) -> list[dict]:
    all_depts, depts = user.scope(cycle_id)
    cur = await conn.execute(
        """SELECT d.id, d.name_ar FROM cycle_department cd JOIN department d ON d.id = cd.department_id
            WHERE cd.cycle_id = %(c)s AND (%(all)s OR d.id = ANY(%(d)s)) ORDER BY d.code""",
        {"c": cycle_id, "all": all_depts, "d": depts})
    return await cur.fetchall()


async def _form_status(conn: AsyncConnection, cycle_id: int, items, dept_ids: list[int], cache: dict) -> dict:
    """حالة كل قسم في البنود المرتبطة بنموذج: filled (له صفوف تطابق البند) / started (النموذج منشأ) / none."""
    out: dict[str, dict] = {}
    codes = sorted({i.form for i in items if i.form})
    cur = await conn.execute(
        """SELECT t.requirement_code AS code, t.id AS template_id, f.department_id, f.id AS form_id, f.status
             FROM form_template t JOIN framework fw ON fw.code = t.framework_code
             JOIN assessment_cycle c ON c.framework_id = fw.id AND c.id = %s
             LEFT JOIN form_record f ON f.template_id = t.id AND f.cycle_id = c.id AND f.department_id = ANY(%s)
            WHERE t.requirement_code = ANY(%s)""", (cycle_id, dept_ids, codes))
    recs: dict[str, dict] = {}
    tpl_ids: dict[str, int] = {}
    for r in await cur.fetchall():
        tpl_ids[r["code"]] = r["template_id"]
        if r["department_id"]:
            recs.setdefault(r["code"], {})[r["department_id"]] = r
    for i in items:
        if not i.form:
            continue
        filled: dict[int, int] = {}
        if i.college:
            ck = (i.college, i.filter)
            if ck not in cache:
                cache[ck] = await cr.build_report(conn, cycle_id, i.college, i.filter, dept_ids)
            rep = cache[ck]
            names = {d["name"]: d["id"] for d in rep["departments"]}
            for row in rep["rows"]:
                if i.by_semester and row.get("semester") not in (None, "", SEM_NAME[i.semester]):
                    continue
                did = names.get(row.get("dept"))
                if did:
                    filled[did] = filled.get(did, 0) + 1
        per = {}
        for d in dept_ids:
            rec = recs.get(i.form, {}).get(d)
            st = "filled" if filled.get(d) or (not i.college and rec and rec["status"] in ("submitted", "approved")) \
                else "started" if rec else "none"
            per[str(d)] = {"state": st, "rows": filled.get(d, 0), "form_id": rec and rec["form_id"],
                           "form_status": rec and rec["status"]}
        out[i.key] = {"template_id": tpl_ids.get(i.form), "departments": per}
    return out


@router.get("/cycles/{cycle_id}/periodic")
async def periodic(cycle_id: int, user: CurrentUser = Depends(current_user),
                   conn: AsyncConnection = Depends(get_conn, scope="function")):
    await load_cycle(conn, user, cycle_id)
    departments = await _departments(conn, user, cycle_id)
    ids = [d["id"] for d in departments]
    weeks = []
    for sem, cal in CALENDAR_1448.items():
        for n, ws in enumerate(await week_starts_for(conn, cycle_id, cal["start"], 19), 1):
            a, b, days = SHORT_WEEKS.get((sem, n), (0, 4, None))
            weeks.append({"semester": sem, "week_no": n, "starts_on": ws + timedelta(days=a), "ends_on": ws + timedelta(days=b),
                          "days": days})
    ws = {(w["semester"], w["week_no"]): w["starts_on"] - timedelta(days=SHORT_WEEKS.get((w["semester"], w["week_no"]), (0,))[0])
          for w in weeks}
    forms = await _form_status(conn, cycle_id, CATALOG_1448, ids, {})
    cur = await conn.execute(
        """SELECT p.item_key, p.department_id, p.status, p.url, p.note_ar, p.done_at, u.full_name_ar AS done_by_name
             FROM periodic_progress p LEFT JOIN app_user u ON u.id = p.done_by
            WHERE p.cycle_id = %s AND (p.department_id IS NULL OR p.department_id = ANY(%s))""", (cycle_id, ids))
    marks: dict[str, dict] = {}
    for m in await cur.fetchall():
        marks.setdefault(m["item_key"], {})[str(m["department_id"] or 0)] = m
    # أعمال الجودة المرتبطة: نفس النموذج وموعدها في أسبوع البند أو الذي يليه
    cur = await conn.execute("SELECT id, week_no, title_ar, due_on, form_code FROM quality_task WHERE cycle_id = %s AND form_code IS NOT NULL",
                             (cycle_id,))
    qtasks = await cur.fetchall()
    items = []
    for i in CATALOG_1448:
        start = ws.get((i.semester, i.week)) if i.week else None
        related = [{"id": t["id"], "week_no": t["week_no"], "title_ar": t["title_ar"], "due_on": t["due_on"]}
                   for t in qtasks if i.form and t["form_code"] == i.form and start and t["due_on"]
                   and start - timedelta(days=7) <= t["due_on"] <= start + timedelta(days=13)]
        items.append({"key": i.key, "semester": i.semester, "week_no": i.week, "title_ar": i.title, "scope": i.scope,
                      "form_code": i.form, "college_key": i.college, "college_filter": i.filter, "note_ar": i.note,
                      "preset_done": i.preset_done, "starts_on": start,
                      "form": forms.get(i.key), "marks": marks.get(i.key, {}), "quality_tasks": related})
    today = date.today()
    return {"can_manage": user.has(*MANAGERS), "today": today,
            "now": locate([{**w, "starts_on": ws[(w["semester"], w["week_no"])]} for w in weeks], today) if weeks else None,
            "departments": departments, "weeks": weeks, "items": items,
            "holidays": [{"title_ar": t, "on": d, "hijri": hj} for t, d, hj in HOLIDAYS_1448], "instructions": INSTRUCTIONS,
            "source": "تقويم أعمال جودة التدريب للعام التدريبي 1448/1449هـ — الإدارة العامة لجودة التدريب"}


def _check(user: CurrentUser, item, dept: int | None, cycle_id: int) -> None:
    if item.scope == "college":
        if dept is not None:
            raise forbid("هذا البند على مستوى الكلية ولا يُؤشَّر لقسم")
        if not user.has(*MANAGERS):
            raise forbid("تأشير بنود الكلية من صلاحية وكيل الجودة")
        return
    if dept is None:
        raise forbid("حدد القسم")
    if item.form and item.college:
        raise forbid("حالة هذا البند تُحسب من نموذج القسم في «الخطط والتقارير»")
    if not (user.has(*SUBMITTERS, department_id=dept, cycle_id=cycle_id) or user.has(*MANAGERS)):
        raise forbid("تأشير البند من صلاحية منسق القسم أو رئيسه")


async def _in_cycle(conn: AsyncConnection, cycle_id: int, dept: int | None) -> None:
    if dept is None:
        return
    cur = await conn.execute("SELECT 1 FROM cycle_department WHERE cycle_id = %s AND department_id = %s", (cycle_id, dept))
    if await cur.fetchone() is None:
        raise not_found("القسم ليس ضمن الدورة")


@router.post("/cycles/{cycle_id}/periodic/{key}/progress")
async def mark(cycle_id: int, key: str, body: ProgressIn, user: CurrentUser = Depends(current_user),
               conn: AsyncConnection = Depends(get_conn, scope="function")):
    await load_cycle(conn, user, cycle_id)
    item = BY_KEY.get(key)
    if item is None:
        raise not_found("البند غير موجود")
    _check(user, item, body.department_id, cycle_id)
    await _in_cycle(conn, cycle_id, body.department_id)
    url = (body.url or "").strip() or None
    if body.not_applicable:
        if not (body.note_ar or "").strip():
            raise forbid("اكتب سبب عدم الانطباق في الملاحظة")
        status, url = "na", None
    else:
        status = "done"
        if url:
            await assert_link_ok(conn, user.institution_id, url)
    await conn.execute("SELECT set_config('aqap.user_id', %s, true)", (str(user.id),))
    await conn.execute(
        """INSERT INTO periodic_progress (cycle_id, item_key, department_id, status, url, note_ar, done_by)
           VALUES (%s, %s, %s, %s, %s, %s, %s)
           ON CONFLICT (cycle_id, item_key, (COALESCE(department_id, 0)))
           DO UPDATE SET status = EXCLUDED.status, url = EXCLUDED.url, note_ar = EXCLUDED.note_ar,
                         done_by = EXCLUDED.done_by, done_at = now()""",
        (cycle_id, key, body.department_id, status, url, (body.note_ar or "").strip() or None, user.id))
    return {"status": status}


@router.delete("/cycles/{cycle_id}/periodic/{key}/progress")
async def unmark(cycle_id: int, key: str, department_id: int | None = None, user: CurrentUser = Depends(current_user),
                 conn: AsyncConnection = Depends(get_conn, scope="function")):
    await load_cycle(conn, user, cycle_id)
    item = BY_KEY.get(key)
    if item is None:
        raise not_found("البند غير موجود")
    _check(user, item, department_id, cycle_id)
    await conn.execute("SELECT set_config('aqap.user_id', %s, true)", (str(user.id),))
    cur = await conn.execute(
        "DELETE FROM periodic_progress WHERE cycle_id = %s AND item_key = %s AND COALESCE(department_id, 0) = %s",
        (cycle_id, key, department_id or 0))
    if not cur.rowcount:
        raise not_found("لم يُؤشَّر هذا البند بعد")
    return {"deleted": True}
