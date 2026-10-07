from fastapi import APIRouter, Depends
from psycopg import AsyncConnection

from ..schemas import CycleCreate
from ..security import CurrentUser, current_user, forbid, get_conn, load_cycle

router = APIRouter(prefix="/cycles", tags=["دورات التقييم"])


@router.get("")
async def list_cycles(user: CurrentUser = Depends(current_user), conn: AsyncConnection = Depends(get_conn)):
    cur = await conn.execute(
        """SELECT c.* FROM assessment_cycle c
            WHERE c.institution_id = %(inst)s
               OR c.id = ANY(%(cycles)s)
            ORDER BY c.starts_on DESC""",
        {"inst": user.institution_id, "cycles": [g.cycle_id for g in user.grants if g.cycle_id]})
    return await cur.fetchall()


@router.post("", status_code=201)
async def create_cycle(body: CycleCreate, user: CurrentUser = Depends(current_user),
                       conn: AsyncConnection = Depends(get_conn)):
    if not user.has("quality_dean", "system_admin"):
        raise forbid("إنشاء الدورات من صلاحية وكيل الجودة")
    cur = await conn.execute(
        """INSERT INTO assessment_cycle (institution_id, framework_id, title_ar, academic_year, starts_on, ends_on)
           VALUES (%s, %s, %s, %s, %s, %s) RETURNING *""",
        (user.institution_id, body.framework_id, body.title_ar, body.academic_year, body.starts_on, body.ends_on))
    cycle = await cur.fetchone()
    async with conn.cursor() as c:
        await c.executemany(
            """INSERT INTO cycle_department (cycle_id, department_id)
               SELECT %s, id FROM department WHERE id = %s AND institution_id = %s""",
            [(cycle["id"], d, user.institution_id) for d in body.department_ids])
    return cycle


@router.post("/{cycle_id}/open")
async def open_cycle(cycle_id: int, user: CurrentUser = Depends(current_user),
                     conn: AsyncConnection = Depends(get_conn)):
    cycle = await load_cycle(conn, user, cycle_id)
    if not user.has("quality_dean", "system_admin", cycle_id=cycle_id):
        raise forbid("فتح الدورة من صلاحية وكيل الجودة")
    if cycle["status"] != "planning":
        raise forbid("يمكن فتح الدورة من حالة التخطيط فقط")
    cur = await conn.execute("SELECT generate_cycle_assessments(%s) AS n", (cycle_id,))
    generated = (await cur.fetchone())["n"]
    await conn.execute("UPDATE assessment_cycle SET status = 'open' WHERE id = %s", (cycle_id,))
    return {"cycle_id": cycle_id, "status": "open", "assessments_generated": generated}


@router.post("/{cycle_id}/external-review")
async def start_external_review(cycle_id: int, user: CurrentUser = Depends(current_user),
                                conn: AsyncConnection = Depends(get_conn)):
    cycle = await load_cycle(conn, user, cycle_id)
    if not user.has("quality_dean", "system_admin", cycle_id=cycle_id):
        raise forbid()
    if cycle["status"] != "open":
        raise forbid("الدورة ليست في حالة مفتوحة")
    await conn.execute("UPDATE assessment_cycle SET status = 'external_review' WHERE id = %s", (cycle_id,))
    return {"cycle_id": cycle_id, "status": "external_review"}


@router.post("/{cycle_id}/close")
async def close_cycle(cycle_id: int, user: CurrentUser = Depends(current_user),
                      conn: AsyncConnection = Depends(get_conn)):
    await load_cycle(conn, user, cycle_id)
    await conn.execute("SELECT close_cycle(%s, %s)", (cycle_id, user.id))  # الصلاحية والشروط داخل الدالة
    return {"cycle_id": cycle_id, "status": "closed"}
