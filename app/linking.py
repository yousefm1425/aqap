"""ربط شاهد بتقدير متطلبه في القسم، مع احترام مسار اعتماد التقدير (مشترك بين المحاضر والنماذج)."""
from psycopg import AsyncConnection

from .security import CurrentUser

ACTIVE_CYCLE = ("open", "external_review")


async def link_to_requirement(conn: AsyncConnection, user: CurrentUser, cycle_id: int, department_id: int,
                              requirement_code: str, cycle_status: str, evidence_id: int, note: str) -> bool | None:
    """True: مربوط (أو كان مربوطاً)، False: التقدير ليس لدى القسم الآن، None: لا تقدير لهذا المتطلب في القسم."""
    cur = await conn.execute(
        """SELECT a.id, a.status FROM assessment a JOIN requirement r ON r.id = a.requirement_id
             JOIN sub_standard ss ON ss.id = r.sub_standard_id JOIN standard s ON s.id = ss.standard_id
             JOIN assessment_cycle c ON c.id = a.cycle_id AND c.framework_id = s.framework_id
            WHERE a.cycle_id = %s AND a.department_id = %s AND r.code = %s""",
        (cycle_id, department_id, requirement_code))
    a = await cur.fetchone()
    if a is None:
        return None
    cur = await conn.execute("SELECT 1 FROM assessment_evidence WHERE assessment_id = %s AND evidence_id = %s",
                             (a["id"], evidence_id))
    if await cur.fetchone():
        return True
    if a["status"] in ("draft", "returned") and cycle_status in ACTIVE_CYCLE:
        await conn.execute("INSERT INTO assessment_evidence (assessment_id, evidence_id, linked_by, note) VALUES (%s, %s, %s, %s)",
                           (a["id"], evidence_id, user.id, note))
        return True
    return False
