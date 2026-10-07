"""وحدة خطط التحسين: مطابقة لأوراق «تحسين قسم» في نموذج العمل الشامل.

المسار: مسودة ← مرفوعة ← (معتمدة | معادة) ← منجزة ← مغلقة بعد التحقق.
قواعد الانتقال والفصل بين المهام تُفرض في aqap.transition_action.
"""
from fastapi import APIRouter, Depends
from psycopg import AsyncConnection, sql

from ..schemas import ActionCreate, ActionPatch, ActionStatus, ActionTransitionIn
from ..security import CurrentUser, current_user, forbid, get_conn, load_cycle, not_found

router = APIRouter(tags=["خطط التحسين"])

MANAGERS = ("quality_dean", "quality_auditor", "system_admin")
DEPT_ROLES = ("hod", "dept_coordinator", "faculty")

_LIST = """
SELECT t.id, t.cycle_id, t.department_id, t.assessment_id, t.source, t.title_ar, t.action_ar, t.status,
       t.priority, t.due_date, t.progress_pct, t.adequacy, t.owner_id, t.owner_label,
       t.requirement_code, t.requirement_text, t.eff_rating, t.is_overdue, t.days_overdue,
       u.full_name_ar AS owner_name
  FROM v_improvement_tracker t LEFT JOIN app_user u ON u.id = t.owner_id
 WHERE t.cycle_id = %(cycle)s
   AND (%(all)s OR t.department_id = ANY(%(depts)s) OR t.owner_id = %(me)s)
   AND (%(dept)s::bigint IS NULL OR t.department_id = %(dept)s)
   AND (%(status)s::aqap.action_status_t IS NULL OR t.status = %(status)s)
   AND (%(overdue)s::boolean IS NULL OR t.is_overdue = %(overdue)s)
 ORDER BY t.is_overdue DESC, t.department_id NULLS FIRST, t.priority, t.requirement_code NULLS LAST, t.id
"""


def _can_view(user: CurrentUser, act: dict) -> bool:
    return act["owner_id"] == user.id or user.can_view_department(act["department_id"], act["cycle_id"])


async def _load(conn: AsyncConnection, user: CurrentUser, action_id: int, lock: bool = False) -> dict:
    cur = await conn.execute("SELECT * FROM improvement_action WHERE id = %s" + (" FOR UPDATE" if lock else ""),
                             (action_id,))
    act = await cur.fetchone()
    if act is None or not _can_view(user, act):
        raise not_found("الخطة غير موجودة")
    await load_cycle(conn, user, act["cycle_id"])
    return act


@router.get("/cycles/{cycle_id}/actions")
async def list_actions(cycle_id: int, department_id: int | None = None, status: ActionStatus | None = None,
                       overdue: bool | None = None, user: CurrentUser = Depends(current_user),
                       conn: AsyncConnection = Depends(get_conn)):
    await load_cycle(conn, user, cycle_id)
    all_depts, depts = user.scope(cycle_id)
    cur = await conn.execute(_LIST, {"cycle": cycle_id, "all": all_depts, "depts": depts, "me": user.id,
                                     "dept": department_id, "status": status, "overdue": overdue})
    return await cur.fetchall()


@router.post("/cycles/{cycle_id}/actions/generate")
async def generate(cycle_id: int, user: CurrentUser = Depends(current_user), conn: AsyncConnection = Depends(get_conn)):
    """يولّد خططاً للمتطلبات النهائية «جزئي/غير متحقق» التي لا خطة لها (يحدث تلقائياً عند الاعتماد النهائي)."""
    await load_cycle(conn, user, cycle_id)
    if not user.has(*MANAGERS, cycle_id=cycle_id):
        raise forbid("توليد الخطط من صلاحية وكالة الجودة")
    cur = await conn.execute("SELECT generate_improvement_actions(%s) AS n", (cycle_id,))
    return {"generated": (await cur.fetchone())["n"]}


@router.get("/actions/{action_id}")
async def get_action(action_id: int, user: CurrentUser = Depends(current_user),
                     conn: AsyncConnection = Depends(get_conn)):
    await _load(conn, user, action_id)
    cur = await conn.execute(
        """SELECT t.*, u.full_name_ar AS owner_name, ab.full_name_ar AS adequacy_by_name,
                  vb.full_name_ar AS verified_by_name, cb.full_name_ar AS completed_by_name,
                  a.self_rating, a.ext_verdict, a.status AS assessment_status,
                  e.title_ar AS completion_evidence_title, e.kind AS completion_evidence_kind
             FROM v_improvement_tracker t
             LEFT JOIN app_user u  ON u.id = t.owner_id
             LEFT JOIN app_user ab ON ab.id = t.adequacy_by
             LEFT JOIN app_user vb ON vb.id = t.verified_by
             LEFT JOIN app_user cb ON cb.id = t.completed_by
             LEFT JOIN assessment a ON a.id = t.assessment_id
             LEFT JOIN evidence e ON e.id = t.completion_evidence_id
            WHERE t.id = %s""", (action_id,))
    act = await cur.fetchone()
    cur = await conn.execute(
        """SELECT h.from_status, h.to_status, h.comment, h.at, u.full_name_ar AS actor
             FROM action_transition h JOIN app_user u ON u.id = h.actor_id
            WHERE h.action_id = %s ORDER BY h.at""", (action_id,))
    return {**act, "history": await cur.fetchall()}


async def _check_refs(conn: AsyncConnection, user: CurrentUser, dept: int | None, fields: dict) -> None:
    if fields.get("owner_id") is not None:
        cur = await conn.execute("SELECT 1 FROM app_user WHERE id = %s AND institution_id = %s AND is_active",
                                 (fields["owner_id"], user.institution_id))
        if await cur.fetchone() is None:
            raise not_found("المسؤول المحدد غير موجود في المنشأة")
    if fields.get("completion_evidence_id") is not None:
        cur = await conn.execute("SELECT department_id, institution_id FROM evidence WHERE id = %s AND NOT is_archived",
                                 (fields["completion_evidence_id"],))
        ev = await cur.fetchone()
        if ev is None or ev["institution_id"] != user.institution_id or ev["department_id"] not in (None, dept):
            raise not_found("شاهد التحسين غير موجود في بنك هذا القسم")


@router.post("/actions", status_code=201)
async def create_action(body: ActionCreate, user: CurrentUser = Depends(current_user),
                        conn: AsyncConnection = Depends(get_conn)):
    await load_cycle(conn, user, body.cycle_id)
    dept = body.department_id
    if body.assessment_id is not None:
        cur = await conn.execute("SELECT cycle_id, department_id FROM assessment WHERE id = %s", (body.assessment_id,))
        a = await cur.fetchone()
        if a is None or a["cycle_id"] != body.cycle_id:
            raise not_found("التقدير غير موجود في هذه الدورة")
        dept = a["department_id"]
    if not (user.has(*MANAGERS, cycle_id=body.cycle_id) or user.has("hod", department_id=dept, cycle_id=body.cycle_id)):
        raise forbid("إنشاء خطة تحسين يدوية من صلاحية الجودة أو رئيس القسم")
    data = body.model_dump() | {"department_id": dept}
    await _check_refs(conn, user, dept, data)
    q = sql.SQL("INSERT INTO improvement_action ({}) VALUES ({}) RETURNING *").format(
        sql.SQL(", ").join(map(sql.Identifier, data)), sql.SQL(", ").join(map(sql.Placeholder, data)))
    cur = await conn.execute(q, data)
    return await cur.fetchone()


@router.patch("/actions/{action_id}")
async def patch_action(action_id: int, body: ActionPatch, user: CurrentUser = Depends(current_user),
                       conn: AsyncConnection = Depends(get_conn)):
    act = await _load(conn, user, action_id, lock=True)
    fields = body.model_dump(exclude_unset=True)
    if not fields:
        return act
    allowed = (act["owner_id"] == user.id
               or user.has(*DEPT_ROLES, department_id=act["department_id"], cycle_id=act["cycle_id"])
               or user.has(*MANAGERS, cycle_id=act["cycle_id"]))
    if not allowed:
        raise forbid("تحديث الخطة من صلاحية القسم أو المسؤول عن التنفيذ أو الجودة")
    await _check_refs(conn, user, act["department_id"], fields)
    # نوافذ التعديل حسب المرحلة تُفرض في trg_action_guard
    q = sql.SQL("UPDATE improvement_action SET {} WHERE id = %(id)s RETURNING *").format(
        sql.SQL(", ").join(sql.SQL("{} = {}").format(sql.Identifier(k), sql.Placeholder(k)) for k in fields))
    cur = await conn.execute(q, fields | {"id": action_id})
    return await cur.fetchone()


@router.post("/actions/{action_id}/transition")
async def transition(action_id: int, body: ActionTransitionIn, user: CurrentUser = Depends(current_user),
                     conn: AsyncConnection = Depends(get_conn)):
    await _load(conn, user, action_id)
    cur = await conn.execute("SELECT transition_action(%s, %s, %s, %s, %s) AS status",
                             (action_id, body.to_status, user.id, body.comment, body.adequacy))
    return {"action_id": action_id, "status": (await cur.fetchone())["status"]}


@router.get("/departments/{department_id}/members")
async def department_members(department_id: int, user: CurrentUser = Depends(current_user),
                             conn: AsyncConnection = Depends(get_conn)):
    """مرشحو «المسؤول عن التنفيذ»: من لهم دور فعّال في القسم."""
    if not user.can_view_department(department_id):
        raise not_found("القسم غير موجود")
    cur = await conn.execute(
        """SELECT DISTINCT u.id, u.full_name_ar FROM app_user u JOIN user_role ur ON ur.user_id = u.id
            WHERE ur.department_id = %s AND u.is_active AND u.institution_id = %s
              AND current_date BETWEEN ur.valid_from AND COALESCE(ur.valid_to, 'infinity'::date)
            ORDER BY u.full_name_ar""", (department_id, user.institution_id))
    return await cur.fetchall()
