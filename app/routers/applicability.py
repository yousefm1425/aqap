"""نطاق انطباق المتطلبات على القسم.

يقرر وكيل الجودة أن متطلباً ليس من اختصاص قسم (مثل الإرشاد أو المشروع لقسم الدراسات العامة) بمسوّغ موثّق،
فيُستبعد من تقديرات القسم ومؤشراته ونماذجه وخطط تحسينه. القرار يُسجّل في سجل التدقيق ويُلغى ولا يُحذف.
الاستبعاد خارج شرط النجمة في النموذج الرسمي يتطلب تأكيداً صريحاً ويظهر للمقيّم الخارجي.
"""
from fastapi import APIRouter, Depends
from psycopg import AsyncConnection
from pydantic import BaseModel, Field

from ..security import CurrentUser, current_user, forbid, get_conn, not_found

router = APIRouter(tags=["نطاق المتطلبات"])
MANAGERS = ("quality_dean", "system_admin")


class ExclusionIn(BaseModel):
    requirement_ids: list[int] = Field(min_length=1, max_length=500)
    reason_ar: str = Field(min_length=5, max_length=1000)
    outside_model_rule: bool = False          # تأكيد الاستبعاد خارج شرط النجمة


async def _dept(conn, user: CurrentUser, department_id: int) -> dict:
    cur = await conn.execute("SELECT id, name_ar, is_general_studies FROM department WHERE id = %s AND institution_id = %s",
                             (department_id, user.institution_id))
    d = await cur.fetchone()
    if d is None or not user.can_view_department(department_id):
        raise not_found("القسم غير موجود")
    return d


@router.get("/departments/{department_id}/applicability")
async def applicability(department_id: int, user: CurrentUser = Depends(current_user),
                        conn: AsyncConnection = Depends(get_conn, scope="function")):
    """شجرة متطلبات الإطار الفعّال مع حالة انطباق كل متطلب على القسم."""
    d = await _dept(conn, user, department_id)
    cur = await conn.execute(
        """SELECT s.code AS standard_code, s.title_ar AS standard_title, ss.code AS sub_standard_code,
                  ss.title_ar AS sub_standard_title, r.id AS requirement_id, r.code AS requirement_code, r.text_ar,
                  r.na_scope, na_allowed(r.id, %(d)s) AS model_allows,
                  e.id AS exclusion_id, e.reason_ar, e.within_model_rule, e.decided_at, u.full_name_ar AS decided_by_name
             FROM requirement r
             JOIN sub_standard ss ON ss.id = r.sub_standard_id
             JOIN standard s ON s.id = ss.standard_id
             JOIN framework f ON f.id = s.framework_id AND f.is_active
             LEFT JOIN requirement_exclusion e ON e.requirement_id = r.id AND e.department_id = %(d)s AND e.revoked_at IS NULL
             LEFT JOIN app_user u ON u.id = e.decided_by
            WHERE r.is_active AND r.scope = 'department'
            ORDER BY s.sort_order, ss.sort_order, r.sort_order""", {"d": department_id})
    rows = await cur.fetchall()
    return {"department": d, "can_edit": user.has(*MANAGERS), "requirements": rows,
            "excluded_count": sum(1 for r in rows if r["exclusion_id"])}


@router.post("/departments/{department_id}/applicability/exclusions", status_code=201)
async def exclude(department_id: int, body: ExclusionIn, user: CurrentUser = Depends(current_user),
                  conn: AsyncConnection = Depends(get_conn, scope="function")):
    if not user.has(*MANAGERS):
        raise forbid("تحديد نطاق المتطلبات من صلاحية وكيل الجودة")
    await _dept(conn, user, department_id)
    cur = await conn.execute(
        """SELECT r.id, r.code, na_allowed(r.id, %s) AS ok FROM requirement r
            WHERE r.id = ANY(%s) AND r.is_active AND r.scope = 'department'""", (department_id, body.requirement_ids))
    reqs = await cur.fetchall()
    if len(reqs) != len(set(body.requirement_ids)):
        raise not_found("بعض المتطلبات غير موجودة أو ليست على مستوى القسم")
    outside = [r["code"] for r in reqs if not r["ok"]]
    if outside and not body.outside_model_rule:
        raise forbid("النموذج الرسمي لا يقبل «لا ينطبق» لهذه المتطلبات في هذا القسم: " + "، ".join(outside)
                     + ". أكّد الاستبعاد خارج شرط النجمة إن كان لديك مسوّغ معتمد.")
    await conn.execute("SELECT set_config('aqap.user_id', %s, true)", (str(user.id),))
    n = 0
    for r in reqs:
        cur = await conn.execute(
            """INSERT INTO requirement_exclusion (department_id, requirement_id, reason_ar, within_model_rule, decided_by)
               VALUES (%s, %s, %s, %s, %s) ON CONFLICT (department_id, requirement_id) WHERE revoked_at IS NULL DO NOTHING""",
            (department_id, r["id"], body.reason_ar.strip(), r["ok"], user.id))
        n += cur.rowcount
    return {"excluded": n}


@router.delete("/departments/{department_id}/applicability/exclusions/{requirement_id}")
async def restore(department_id: int, requirement_id: int, user: CurrentUser = Depends(current_user),
                  conn: AsyncConnection = Depends(get_conn, scope="function")):
    """إعادة المتطلب لنطاق القسم (إلغاء القرار مع بقائه في السجل)."""
    if not user.has(*MANAGERS):
        raise forbid("تحديد نطاق المتطلبات من صلاحية وكيل الجودة")
    await _dept(conn, user, department_id)
    await conn.execute("SELECT set_config('aqap.user_id', %s, true)", (str(user.id),))
    cur = await conn.execute(
        """UPDATE requirement_exclusion SET revoked_at = clock_timestamp(), revoked_by = %s
            WHERE department_id = %s AND requirement_id = %s AND revoked_at IS NULL""",
        (user.id, department_id, requirement_id))
    if not cur.rowcount:
        raise not_found("المتطلب غير مستبعد من هذا القسم")
    # إعادة توليد تقدير المتطلب في الدورات المفتوحة التي استُبعد قبل فتحها
    cur = await conn.execute(
        """SELECT c.id FROM assessment_cycle c JOIN cycle_department cd ON cd.cycle_id = c.id
            WHERE cd.department_id = %s AND c.status = 'open'""", (department_id,))
    for c in await cur.fetchall():
        await conn.execute("SELECT generate_cycle_assessments(%s)", (c["id"],))
    return {"restored": True}
