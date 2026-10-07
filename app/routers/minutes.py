"""وحدة المحاضر: نموذج رقمي موحّد لمحاضر الاجتماعات في متطلبات النموذج الرسمي.

مسودة ← مرفوع ← (معتمد | معاد). عند الاعتماد يُؤرشف PDF شاهداً في بنك القسم ويُربط بالمتطلب.
بعد الاعتماد تُتابع التوصيات (مُنفذ / مُنفذ جزئي / لم يُنفذ) ويؤكد الحضور حضورهم إلكترونياً.
"""
import hashlib
from urllib.parse import quote

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from psycopg import AsyncConnection
from starlette.concurrency import run_in_threadpool

from .. import storage
from ..minutes_pdf import render_pdf
from ..schemas import FollowUpIn, MinutesCreate, MinutesDoc, MinutesTransitionIn
from ..security import CurrentUser, current_user, forbid, get_conn, load_cycle, not_found

router = APIRouter(tags=["المحاضر"])

DEPT_ROLES = ("hod", "dept_coordinator", "faculty")
QUALITY = ("quality_dean", "quality_auditor", "system_admin")
ROLE_LABEL = {"hod": "رئيس القسم", "dept_coordinator": "منسق الجودة بالقسم", "faculty": "عضو هيئة تدريب"}


async def _template_rows(conn: AsyncConnection, cycle: dict) -> list[dict]:
    cur = await conn.execute(
        """SELECT t.id, t.requirement_code, t.title_ar, t.suggested_agenda, t.guidance_ar, t.sort_order,
                  r.id AS requirement_id, r.text_ar AS requirement_text
             FROM minutes_template t
             JOIN framework f ON f.code = t.framework_code
             LEFT JOIN requirement r ON r.code = t.requirement_code AND r.sub_standard_id IN (
                  SELECT ss.id FROM sub_standard ss JOIN standard s ON s.id = ss.standard_id WHERE s.framework_id = f.id)
            WHERE f.id = %s ORDER BY t.sort_order""", (cycle["framework_id"],))
    return await cur.fetchall()


async def _load(conn: AsyncConnection, user: CurrentUser, minutes_id: int, lock: bool = False) -> dict:
    cur = await conn.execute("SELECT * FROM minutes WHERE id = %s" + (" FOR UPDATE" if lock else ""), (minutes_id,))
    m = await cur.fetchone()
    if m is None or not user.can_view_department(m["department_id"], m["cycle_id"]):
        raise not_found("المحضر غير موجود")
    await load_cycle(conn, user, m["cycle_id"])
    return m


def _is_dept(user: CurrentUser, m: dict) -> bool:
    return user.has(*DEPT_ROLES, department_id=m["department_id"], cycle_id=m["cycle_id"])


async def _full(conn: AsyncConnection, minutes_id: int) -> dict:
    cur = await conn.execute(
        """SELECT m.*, t.requirement_code, t.guidance_ar, t.suggested_agenda, r.text_ar AS requirement_text,
                  d.name_ar AS department_name, i.name_ar AS institution_name, c.academic_year, c.status AS cycle_status,
                  ua.full_name_ar AS approved_by_name, us.full_name_ar AS submitted_by_name
             FROM minutes m
             JOIN minutes_template t ON t.id = m.template_id
             JOIN assessment_cycle c ON c.id = m.cycle_id
             JOIN institution i ON i.id = c.institution_id
             JOIN department d ON d.id = m.department_id
             LEFT JOIN requirement r ON r.code = t.requirement_code AND r.sub_standard_id IN (
                  SELECT ss.id FROM sub_standard ss JOIN standard s ON s.id = ss.standard_id WHERE s.framework_id = c.framework_id)
             LEFT JOIN app_user ua ON ua.id = m.approved_by
             LEFT JOIN app_user us ON us.id = m.submitted_by
            WHERE m.id = %s""", (minutes_id,))
    doc = await cur.fetchone()
    cur = await conn.execute("SELECT id, ord, title_ar FROM minutes_agenda_item WHERE minutes_id = %s ORDER BY ord",
                             (minutes_id,))
    agenda = await cur.fetchall()
    cur = await conn.execute(
        """SELECT r.id, r.agenda_item_id, r.ord, r.text_ar, r.responsible_ar, r.period_ar,
                  r.fu_status, r.fu_obstacles, r.fu_solutions, r.fu_at, u.full_name_ar AS fu_by_name
             FROM minutes_recommendation r JOIN minutes_agenda_item ai ON ai.id = r.agenda_item_id
             LEFT JOIN app_user u ON u.id = r.fu_by
            WHERE ai.minutes_id = %s ORDER BY ai.ord, r.ord""", (minutes_id,))
    recs = await cur.fetchall()
    for a in agenda:
        a["recommendations"] = [r for r in recs if r["agenda_item_id"] == a["id"]]
    cur = await conn.execute(
        "SELECT id, ord, name_ar, role_ar, user_id, confirmed_at FROM minutes_attendee WHERE minutes_id = %s ORDER BY ord",
        (minutes_id,))
    attendees = await cur.fetchall()
    cur = await conn.execute("SELECT * FROM v_minutes_summary WHERE minutes_id = %s", (minutes_id,))
    summary = await cur.fetchone()
    cur = await conn.execute(
        """SELECT h.from_status, h.to_status, h.comment, h.at, u.full_name_ar AS actor
             FROM minutes_transition h JOIN app_user u ON u.id = h.actor_id WHERE h.minutes_id = %s ORDER BY h.at""",
        (minutes_id,))
    history = await cur.fetchall()
    return {**doc, "agenda": agenda, "attendees": attendees, "summary": summary, "history": history}


@router.get("/cycles/{cycle_id}/minutes/templates")
async def templates(cycle_id: int, department_id: int | None = None, user: CurrentUser = Depends(current_user),
                    conn: AsyncConnection = Depends(get_conn)):
    """نماذج المحاضر لإطار الدورة، مع عدد المحاضر والمعتمد منها ضمن نطاق المستخدم."""
    cycle = await load_cycle(conn, user, cycle_id)
    rows = await _template_rows(conn, cycle)
    all_depts, depts = user.scope(cycle_id)
    cur = await conn.execute(
        """SELECT template_id, count(*) AS total, count(*) FILTER (WHERE status = 'approved') AS approved,
                  count(*) FILTER (WHERE status IN ('draft','returned')) AS open
             FROM minutes WHERE cycle_id = %(c)s AND (%(all)s OR department_id = ANY(%(d)s))
              AND (%(dept)s::bigint IS NULL OR department_id = %(dept)s)
            GROUP BY template_id""", {"c": cycle_id, "all": all_depts, "d": depts, "dept": department_id})
    counts = {r["template_id"]: r for r in await cur.fetchall()}
    return [{**t, "total": counts.get(t["id"], {}).get("total", 0), "approved": counts.get(t["id"], {}).get("approved", 0),
             "open": counts.get(t["id"], {}).get("open", 0)} for t in rows]


@router.get("/cycles/{cycle_id}/minutes")
async def list_minutes(cycle_id: int, department_id: int | None = None, template_id: int | None = None,
                       user: CurrentUser = Depends(current_user), conn: AsyncConnection = Depends(get_conn)):
    await load_cycle(conn, user, cycle_id)
    all_depts, depts = user.scope(cycle_id)
    cur = await conn.execute(
        """SELECT s.*, d.name_ar AS department_name FROM v_minutes_summary s JOIN department d ON d.id = s.department_id
            WHERE s.cycle_id = %(c)s AND (%(all)s OR s.department_id = ANY(%(d)s))
              AND (%(dept)s::bigint IS NULL OR s.department_id = %(dept)s)
              AND (%(t)s::bigint IS NULL OR s.template_id = %(t)s)
            ORDER BY s.requirement_code, s.department_id, s.meeting_no DESC""",
        {"c": cycle_id, "all": all_depts, "d": depts, "dept": department_id, "t": template_id})
    return await cur.fetchall()


@router.post("/cycles/{cycle_id}/minutes", status_code=201)
async def create_minutes(cycle_id: int, body: MinutesCreate, user: CurrentUser = Depends(current_user),
                         conn: AsyncConnection = Depends(get_conn)):
    """محضر جديد من النموذج: المحاور المقترحة، وأعضاء القسم المسجلون في المنصة كقائمة حضور أولية."""
    cycle = await load_cycle(conn, user, cycle_id)
    if cycle["status"] not in ("open", "external_review"):
        raise forbid("الدورة ليست مفتوحة")
    if not user.has(*DEPT_ROLES, department_id=body.department_id, cycle_id=cycle_id):
        raise forbid("إنشاء المحاضر من صلاحية منسوبي القسم")
    tpl = next((t for t in await _template_rows(conn, cycle) if t["id"] == body.template_id), None)
    if tpl is None:
        raise not_found("النموذج غير موجود في إطار هذه الدورة")
    cur = await conn.execute(
        """INSERT INTO minutes (cycle_id, department_id, template_id, meeting_no, title_ar, follow_up_owner, created_by)
           VALUES (%s, %s, %s, 0, %s, 'رئيس القسم', %s) RETURNING id""",
        (cycle_id, body.department_id, tpl["id"], tpl["title_ar"], user.id))
    mid = (await cur.fetchone())["id"]
    async with conn.cursor() as c:
        await c.executemany("INSERT INTO minutes_agenda_item (minutes_id, ord, title_ar) VALUES (%s, %s, %s)",
                            [(mid, i, title) for i, title in enumerate(tpl["suggested_agenda"], 1)])
    cur = await conn.execute(
        """SELECT DISTINCT ON (u.id) u.id, u.full_name_ar, ur.role::text AS role
             FROM user_role ur JOIN app_user u ON u.id = ur.user_id
            WHERE ur.department_id = %s AND u.is_active AND ur.role IN ('hod','dept_coordinator','faculty')
              AND current_date BETWEEN ur.valid_from AND COALESCE(ur.valid_to, 'infinity'::date)
            ORDER BY u.id, array_position(ARRAY['hod','dept_coordinator','faculty'], ur.role::text)""",
        (body.department_id,))
    members = sorted(await cur.fetchall(), key=lambda r: (["hod", "dept_coordinator", "faculty"].index(r["role"]), r["full_name_ar"]))
    async with conn.cursor() as c:
        await c.executemany(
            "INSERT INTO minutes_attendee (minutes_id, ord, name_ar, role_ar, user_id) VALUES (%s, %s, %s, %s, %s)",
            [(mid, i, u["full_name_ar"], ROLE_LABEL[u["role"]], u["id"]) for i, u in enumerate(members, 1)])
    return await _full(conn, mid)


@router.get("/minutes/{minutes_id}")
async def get_minutes(minutes_id: int, user: CurrentUser = Depends(current_user), conn: AsyncConnection = Depends(get_conn)):
    await _load(conn, user, minutes_id)
    return await _full(conn, minutes_id)


@router.put("/minutes/{minutes_id}")
async def save_minutes(minutes_id: int, body: MinutesDoc, user: CurrentUser = Depends(current_user),
                       conn: AsyncConnection = Depends(get_conn)):
    """حفظ المحضر كاملاً (المسودة أو بعد الإعادة فقط — مفروض في قاعدة البيانات)."""
    m = await _load(conn, user, minutes_id, lock=True)
    if not _is_dept(user, m):
        raise forbid("تحرير المحضر من صلاحية منسوبي القسم")
    ids = {a.user_id for a in body.attendees if a.user_id}
    if ids:
        cur = await conn.execute("SELECT count(*) AS n FROM app_user WHERE id = ANY(%s) AND institution_id = %s",
                                 (list(ids), user.institution_id))
        if (await cur.fetchone())["n"] != len(ids):
            raise not_found("أحد الحاضرين غير مسجل في المنشأة")
    await conn.execute(
        """UPDATE minutes SET title_ar = %s, semester = %s, meeting_date = %s, start_time = %s, location_ar = %s,
                              follow_up_owner = %s WHERE id = %s""",
        (body.title_ar, body.semester, body.meeting_date, body.start_time, body.location_ar, body.follow_up_owner, minutes_id))
    await conn.execute("DELETE FROM minutes_agenda_item WHERE minutes_id = %s", (minutes_id,))
    await conn.execute("DELETE FROM minutes_attendee WHERE minutes_id = %s", (minutes_id,))
    for i, a in enumerate(body.agenda, 1):
        cur = await conn.execute("INSERT INTO minutes_agenda_item (minutes_id, ord, title_ar) VALUES (%s, %s, %s) RETURNING id",
                                 (minutes_id, i, a.title_ar))
        aid = (await cur.fetchone())["id"]
        async with conn.cursor() as c:
            await c.executemany(
                """INSERT INTO minutes_recommendation (agenda_item_id, ord, text_ar, responsible_ar, period_ar)
                   VALUES (%s, %s, %s, %s, %s)""",
                [(aid, j, r.text_ar, r.responsible_ar, r.period_ar) for j, r in enumerate(a.recommendations, 1)])
    async with conn.cursor() as c:
        await c.executemany(
            "INSERT INTO minutes_attendee (minutes_id, ord, name_ar, role_ar, user_id) VALUES (%s, %s, %s, %s, %s)",
            [(minutes_id, k, a.name_ar, a.role_ar, a.user_id) for k, a in enumerate(body.attendees, 1)])
    return await _full(conn, minutes_id)


@router.delete("/minutes/{minutes_id}", status_code=204)
async def delete_minutes(minutes_id: int, user: CurrentUser = Depends(current_user), conn: AsyncConnection = Depends(get_conn)):
    m = await _load(conn, user, minutes_id, lock=True)
    if not _is_dept(user, m):
        raise forbid()
    await conn.execute("DELETE FROM minutes WHERE id = %s", (minutes_id,))       # المسودة فقط (قاعدة البيانات)


async def _archive(conn: AsyncConnection, user: CurrentUser, minutes_id: int) -> dict:
    """يولّد PDF ويحفظه نسخة في بنك شواهد القسم؛ أول مرة ينشئ الشاهد ويربطه بالمتطلب إن أمكن."""
    doc = await _full(conn, minutes_id)
    pdf = await run_in_threadpool(render_pdf, doc)
    linked = None
    await conn.execute("SELECT set_config('aqap.system_op', 'on', true)")
    try:
        ev_id = doc["evidence_id"]
        if ev_id is None:
            cur = await conn.execute(
                """INSERT INTO evidence (institution_id, department_id, title_ar, description_ar, kind, created_by)
                   SELECT c.institution_id, %s, %s, %s, 'file', %s FROM assessment_cycle c WHERE c.id = %s RETURNING id""",
                (doc["department_id"], f"محضر {doc['title_ar']} رقم {doc['meeting_no']} — الفصل {doc['semester']}",
                 f"مولّد من منصة AQAP للمتطلب {doc['requirement_code']} (المرجع AQAP-M-{minutes_id})", user.id, doc["cycle_id"]))
            ev_id = (await cur.fetchone())["id"]
            await conn.execute("UPDATE minutes SET evidence_id = %s WHERE id = %s", (ev_id, minutes_id))
        key = storage.build_key(user.institution_id, doc["department_id"], ev_id, ".pdf")
        await storage.put_bytes(key, pdf, "application/pdf")
        cur = await conn.execute(
            """INSERT INTO evidence_version (evidence_id, version_no, storage_key, file_name, mime_type, size_bytes, sha256,
                                             change_note, uploaded_by)
               VALUES (%s, 0, %s, %s, 'application/pdf', %s, %s, %s, %s) RETURNING version_no""",
            (ev_id, key, f"محضر-{doc['requirement_code']}-رقم-{doc['meeting_no']}.pdf", len(pdf),
             hashlib.sha256(pdf).hexdigest(),
             "اعتماد المحضر" if not any(r.get("fu_status") for a in doc["agenda"] for r in a["recommendations"])
             else "تحديث متابعة تنفيذ التوصيات", user.id))
        version = (await cur.fetchone())["version_no"]
    finally:
        await conn.execute("SELECT set_config('aqap.system_op', 'off', true)")
    # الربط بالمتطلب يحترم مسار الاعتماد: يُربط فقط إن كان التقدير لدى القسم
    cur = await conn.execute(
        """SELECT a.id, a.status FROM assessment a JOIN requirement r ON r.id = a.requirement_id
             JOIN sub_standard ss ON ss.id = r.sub_standard_id JOIN standard s ON s.id = ss.standard_id
             JOIN assessment_cycle c ON c.id = a.cycle_id AND c.framework_id = s.framework_id
            WHERE a.cycle_id = %s AND a.department_id = %s AND r.code = %s""",
        (doc["cycle_id"], doc["department_id"], doc["requirement_code"]))
    a = await cur.fetchone()
    if a is not None:
        cur = await conn.execute("SELECT 1 FROM assessment_evidence WHERE assessment_id = %s AND evidence_id = %s",
                                 (a["id"], ev_id))
        if await cur.fetchone():
            linked = True
        elif a["status"] in ("draft", "returned") and doc["cycle_status"] in ("open", "external_review"):
            await conn.execute("INSERT INTO assessment_evidence (assessment_id, evidence_id, linked_by, note) VALUES (%s, %s, %s, %s)",
                               (a["id"], ev_id, user.id, f"محضر AQAP-M-{minutes_id}"))
            linked = True
        else:
            linked = False
    return {"evidence_id": ev_id, "version_no": version, "linked_to_requirement": linked}


@router.post("/minutes/{minutes_id}/transition")
async def transition(minutes_id: int, body: MinutesTransitionIn, user: CurrentUser = Depends(current_user),
                     conn: AsyncConnection = Depends(get_conn)):
    await _load(conn, user, minutes_id)
    cur = await conn.execute("SELECT transition_minutes(%s, %s, %s, %s) AS s", (minutes_id, body.to_status, user.id, body.comment))
    result = {"minutes_id": minutes_id, "status": (await cur.fetchone())["s"]}
    if body.to_status == "approved":
        result["archive"] = await _archive(conn, user, minutes_id)
    return result


@router.patch("/minutes/recommendations/{rec_id}/follow-up")
async def follow_up(rec_id: int, body: FollowUpIn, user: CurrentUser = Depends(current_user),
                    conn: AsyncConnection = Depends(get_conn)):
    cur = await conn.execute(
        "SELECT ai.minutes_id FROM minutes_recommendation r JOIN minutes_agenda_item ai ON ai.id = r.agenda_item_id WHERE r.id = %s",
        (rec_id,))
    row = await cur.fetchone()
    if row is None:
        raise not_found("التوصية غير موجودة")
    m = await _load(conn, user, row["minutes_id"])
    if not (_is_dept(user, m) or user.has(*QUALITY, cycle_id=m["cycle_id"])):
        raise forbid("متابعة التوصيات من صلاحية القسم أو الجودة")
    if body.fu_status in ("partial", "not_done") and not (body.fu_obstacles or "").strip():
        raise forbid("اكتب المعوقات والتحديات للتوصية غير المنفذة كلياً")
    await conn.execute(
        "UPDATE minutes_recommendation SET fu_status = %s, fu_obstacles = %s, fu_solutions = %s WHERE id = %s",
        (body.fu_status, body.fu_obstacles, body.fu_solutions, rec_id))
    cur = await conn.execute("SELECT * FROM v_minutes_summary WHERE minutes_id = %s", (m["id"],))
    return await cur.fetchone()


@router.post("/minutes/{minutes_id}/attendees/confirm")
async def confirm_attendance(minutes_id: int, user: CurrentUser = Depends(current_user),
                             conn: AsyncConnection = Depends(get_conn)):
    """يؤكد المستخدم حضوره بنفسه (بديل التوقيع اليدوي)."""
    cur = await conn.execute("SELECT id, confirmed_at FROM minutes_attendee WHERE minutes_id = %s AND user_id = %s",
                             (minutes_id, user.id))
    att = await cur.fetchone()
    if att is None:
        raise not_found("لست ضمن قائمة الحضور في هذا المحضر")
    if att["confirmed_at"] is None:
        await conn.execute("UPDATE minutes_attendee SET confirmed_at = now() WHERE id = %s", (att["id"],))
    return {"confirmed": True}


@router.post("/minutes/{minutes_id}/archive")
async def archive_follow_up(minutes_id: int, user: CurrentUser = Depends(current_user),
                            conn: AsyncConnection = Depends(get_conn)):
    """نسخة مؤرشفة جديدة من المحضر المعتمد تتضمن متابعة التوصيات وتأكيدات الحضور."""
    m = await _load(conn, user, minutes_id)
    if m["status"] != "approved":
        raise forbid("الأرشفة للمحضر المعتمد فقط")
    if not (_is_dept(user, m) or user.has(*QUALITY, cycle_id=m["cycle_id"])):
        raise forbid()
    return await _archive(conn, user, minutes_id)


@router.get("/minutes/{minutes_id}/pdf")
async def minutes_pdf(minutes_id: int, user: CurrentUser = Depends(current_user), conn: AsyncConnection = Depends(get_conn)):
    """معاينة المحضر بحالته الحالية (المسودة تحمل علامة «غير معتمد»)."""
    await _load(conn, user, minutes_id)
    doc = await _full(conn, minutes_id)
    pdf = await run_in_threadpool(render_pdf, doc)
    name = f"محضر-{doc['requirement_code']}-رقم-{doc['meeting_no']}.pdf"
    return Response(pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f"inline; filename*=UTF-8''{quote(name)}"})
