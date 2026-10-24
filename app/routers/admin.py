"""إدارة المستخدمين والصلاحيات، ومكتبة الأدلة.

- المستخدمون: وكيل الجودة ومدير النظام يضيفون الحسابات ويسندون الأدوار (لكل قسم أو للمنشأة) ويوقفون الحسابات.
  لا يمنح وكيل الجودة دور «مدير النظام»، ولا يوقف أحد حسابه بنفسه. كل تغيير في سجل التدقيق.
- الأدلة: روابط أدلة ومراجع يضيفها وكيل الجودة ويطّلع عليها الجميع.
"""
from datetime import date

from fastapi import APIRouter, Depends
from psycopg import AsyncConnection
from pydantic import BaseModel, Field

from ..security import CurrentUser, current_user, forbid, get_conn, not_found

router = APIRouter(tags=["الإدارة"])
MANAGERS = ("quality_dean", "system_admin")
ROLES = ("system_admin", "quality_dean", "quality_auditor", "hod", "dept_coordinator", "faculty", "external_reviewer")
DEPT_ROLES = ("hod", "dept_coordinator", "faculty")


class UserIn(BaseModel):
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+$", max_length=200)
    full_name_ar: str = Field(min_length=3, max_length=200)


class UserPatch(BaseModel):
    full_name_ar: str | None = Field(None, min_length=3, max_length=200)
    is_active: bool | None = None


class RoleIn(BaseModel):
    role: str = Field(pattern="^(" + "|".join(ROLES) + ")$")
    department_id: int | None = None
    cycle_id: int | None = None
    valid_to: date | None = None


class GuideIn(BaseModel):
    title_ar: str = Field(min_length=3, max_length=300)
    description_ar: str | None = Field(None, max_length=1000)
    category: str = Field("دليل إجرائي", max_length=100)
    url: str = Field(pattern=r"^https?://\S+$", max_length=2000)
    sort_order: int = 0


def _manager(user: CurrentUser) -> None:
    if not user.has(*MANAGERS):
        raise forbid("إدارة المستخدمين والأدلة من صلاحية وكيل الجودة")


async def _actor(conn, user):
    await conn.execute("SELECT set_config('aqap.user_id', %s, true)", (str(user.id),))


async def _own_user(conn, user: CurrentUser, user_id: int) -> dict:
    cur = await conn.execute("SELECT * FROM app_user WHERE id = %s AND (institution_id = %s OR institution_id IS NULL)",
                             (user_id, user.institution_id))
    u = await cur.fetchone()
    if u is None:
        raise not_found("المستخدم غير موجود")
    return u


# ---------------------------------------------------------------- المستخدمون
@router.get("/users")
async def list_users(user: CurrentUser = Depends(current_user), conn: AsyncConnection = Depends(get_conn, scope="function")):
    _manager(user)
    cur = await conn.execute(
        """SELECT u.id, u.email, u.full_name_ar, u.is_active, u.created_at,
                  COALESCE(json_agg(json_build_object('id', r.id, 'role', r.role, 'department_id', r.department_id,
                           'department_name', d.name_ar, 'cycle_id', r.cycle_id, 'valid_to', r.valid_to)
                           ORDER BY r.id) FILTER (WHERE r.id IS NOT NULL), '[]') AS roles
             FROM app_user u
             LEFT JOIN user_role r ON r.user_id = u.id
             LEFT JOIN department d ON d.id = r.department_id
            WHERE u.institution_id = %(i)s
               OR EXISTS (SELECT 1 FROM user_role x JOIN assessment_cycle c ON c.id = x.cycle_id
                           WHERE x.user_id = u.id AND c.institution_id = %(i)s)
            GROUP BY u.id ORDER BY u.is_active DESC, u.full_name_ar""", {"i": user.institution_id})
    return {"users": await cur.fetchall(), "can_grant_admin": user.has("system_admin")}


@router.post("/users", status_code=201)
async def create_user(body: UserIn, user: CurrentUser = Depends(current_user), conn: AsyncConnection = Depends(get_conn, scope="function")):
    _manager(user)
    await _actor(conn, user)
    cur = await conn.execute(
        "INSERT INTO app_user (institution_id, email, full_name_ar) VALUES (%s, lower(%s), %s) RETURNING id",
        (user.institution_id, body.email, body.full_name_ar.strip()))
    return {"id": (await cur.fetchone())["id"]}


@router.patch("/users/{user_id}")
async def patch_user(user_id: int, body: UserPatch, user: CurrentUser = Depends(current_user),
                     conn: AsyncConnection = Depends(get_conn, scope="function")):
    _manager(user)
    await _own_user(conn, user, user_id)
    if body.is_active is False and user_id == user.id:
        raise forbid("لا يمكنك إيقاف حسابك")
    await _actor(conn, user)
    if body.full_name_ar is not None:
        await conn.execute("UPDATE app_user SET full_name_ar = %s WHERE id = %s", (body.full_name_ar.strip(), user_id))
    if body.is_active is not None:
        await conn.execute("UPDATE app_user SET is_active = %s WHERE id = %s", (body.is_active, user_id))
    return {"updated": True}


@router.post("/users/{user_id}/roles", status_code=201)
async def add_role(user_id: int, body: RoleIn, user: CurrentUser = Depends(current_user),
                   conn: AsyncConnection = Depends(get_conn, scope="function")):
    _manager(user)
    await _own_user(conn, user, user_id)
    if body.role == "system_admin" and not user.has("system_admin"):
        raise forbid("منح دور «مدير النظام» من صلاحية مدير النظام فقط")
    if body.role in DEPT_ROLES and body.department_id is None:
        raise forbid("هذا الدور يتطلب تحديد القسم")
    if body.role == "external_reviewer" and (body.cycle_id is None or body.valid_to is None):
        raise forbid("المقيّم الخارجي يُسند لدورة محددة وبتاريخ انتهاء")
    if body.department_id is not None:
        cur = await conn.execute("SELECT 1 FROM department WHERE id = %s AND institution_id = %s",
                                 (body.department_id, user.institution_id))
        if await cur.fetchone() is None:
            raise not_found("القسم غير موجود")
    await _actor(conn, user)
    cur = await conn.execute(
        """INSERT INTO user_role (user_id, role, department_id, cycle_id, valid_to)
           VALUES (%s, %s, %s, %s, %s) RETURNING id""",
        (user_id, body.role, body.department_id if body.role in DEPT_ROLES else None, body.cycle_id, body.valid_to))
    return {"id": (await cur.fetchone())["id"]}


@router.delete("/roles/{role_id}")
async def remove_role(role_id: int, user: CurrentUser = Depends(current_user), conn: AsyncConnection = Depends(get_conn, scope="function")):
    _manager(user)
    cur = await conn.execute(
        """SELECT r.* FROM user_role r JOIN app_user u ON u.id = r.user_id
            WHERE r.id = %s AND (u.institution_id = %s OR u.institution_id IS NULL)""", (role_id, user.institution_id))
    r = await cur.fetchone()
    if r is None:
        raise not_found("الدور غير موجود")
    if r["role"] == "system_admin" and not user.has("system_admin"):
        raise forbid("سحب دور «مدير النظام» من صلاحية مدير النظام فقط")
    if r["user_id"] == user.id and r["role"] in MANAGERS:
        raise forbid("لا يمكنك سحب صلاحية الإدارة من حسابك")
    await _actor(conn, user)
    await conn.execute("DELETE FROM user_role WHERE id = %s", (role_id,))
    return {"deleted": True}


# ---------------------------------------------------------------- الأدلة
@router.get("/guides")
async def list_guides(user: CurrentUser = Depends(current_user), conn: AsyncConnection = Depends(get_conn, scope="function")):
    cur = await conn.execute(
        """SELECT g.id, g.title_ar, g.description_ar, g.category, g.url, g.sort_order, g.created_at, u.full_name_ar AS created_by_name
             FROM guide_document g LEFT JOIN app_user u ON u.id = g.created_by
            WHERE g.institution_id = %s ORDER BY g.category, g.sort_order, g.title_ar""", (user.institution_id,))
    return {"guides": await cur.fetchall(), "can_edit": user.has(*MANAGERS)}


@router.post("/guides", status_code=201)
async def add_guide(body: GuideIn, user: CurrentUser = Depends(current_user), conn: AsyncConnection = Depends(get_conn, scope="function")):
    _manager(user)
    await _actor(conn, user)
    cur = await conn.execute(
        """INSERT INTO guide_document (institution_id, title_ar, description_ar, category, url, sort_order, created_by)
           VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id""",
        (user.institution_id, body.title_ar.strip(), body.description_ar, body.category.strip() or "دليل إجرائي",
         body.url.strip(), body.sort_order, user.id))
    return {"id": (await cur.fetchone())["id"]}


@router.delete("/guides/{guide_id}")
async def delete_guide(guide_id: int, user: CurrentUser = Depends(current_user), conn: AsyncConnection = Depends(get_conn, scope="function")):
    _manager(user)
    await _actor(conn, user)
    cur = await conn.execute("DELETE FROM guide_document WHERE id = %s AND institution_id = %s", (guide_id, user.institution_id))
    if not cur.rowcount:
        raise not_found("الدليل غير موجود")
    return {"deleted": True}
