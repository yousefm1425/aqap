"""أنماط التدريب (ذاتي / مدمج / عن بعد): وحدة اختيارية لا تُفعَّل إلا بقرار صاحب الصلاحية.

- دون قرار: لا يظهر شيء من منهجية الأنماط، ومهام أعمال الجودة المرتبطة بها «لا تنطبق» تلقائياً على كل الأقسام.
- بعد تسجيل القرار: تُنشأ دورة «منهجية قياس أنماط التدريب» (12 متطلباً على مستوى المنشأة) بنفس أدوات المنصة:
  التقييم الذاتي، روابط الشواهد، حكم المقيّم الخارجي، خطط التحسين، والتقرير النهائي.
- إلغاء القرار يوقف الأنماط دون حذف ما أُنجز.
"""
from datetime import date

from fastapi import APIRouter, Depends
from psycopg import AsyncConnection
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field

from ..security import CurrentUser, current_user, forbid, get_conn, load_cycle, not_found

router = APIRouter(tags=["أنماط التدريب"])
MANAGERS = ("quality_dean", "system_admin")
PATTERNS = ("ذاتي", "مدمج", "عن بعد")
PROGRAMS = ("بكالوريوس", "دبلوم", "بكالوريوس ودبلوم")


class SpecialtyIn(BaseModel):
    specialty: str = Field(min_length=2, max_length=200)
    courses: int | None = Field(default=None, ge=0)
    pattern: str | None = None
    trainees: int | None = Field(default=None, ge=0)


class ActivateIn(BaseModel):
    authority_ar: str = Field(min_length=3, max_length=200)
    decision_no: str | None = Field(default=None, max_length=100)
    decision_date: date | None = None
    patterns: list[str] = Field(min_length=1)
    specialties: list[SpecialtyIn] = Field(default_factory=list, max_length=60)
    notes_ar: str | None = Field(default=None, max_length=1000)


class RevokeIn(BaseModel):
    reason_ar: str = Field(min_length=3, max_length=500)


class VisitIn(BaseModel):
    visit_date: date
    program: str
    supervisor_name: str | None = Field(default=None, max_length=200)
    supervisor_phone: str | None = Field(default=None, max_length=30)
    college_name: str | None = Field(default=None, max_length=200)
    college_phone: str | None = Field(default=None, max_length=30)
    executed: bool | None = None
    notes_ar: str | None = Field(default=None, max_length=500)


async def activation(conn: AsyncConnection, cycle_id: int) -> dict | None:
    cur = await conn.execute(
        """SELECT a.*, pc.status AS patterns_status, pc.title_ar AS patterns_title
             FROM training_pattern_activation a LEFT JOIN assessment_cycle pc ON pc.id = a.patterns_cycle_id
            WHERE a.cycle_id = %s AND a.revoked_at IS NULL""", (cycle_id,))
    return await cur.fetchone()


async def _actor(conn, user):
    await conn.execute("SELECT set_config('aqap.user_id', %s, true)", (str(user.id),))


@router.get("/cycles/{cycle_id}/patterns")
async def get_patterns(cycle_id: int, user: CurrentUser = Depends(current_user), conn: AsyncConnection = Depends(get_conn, scope="function")):
    await load_cycle(conn, user, cycle_id)
    a = await activation(conn, cycle_id)
    progress = None
    if a and a["patterns_cycle_id"]:
        cur = await conn.execute(
            """SELECT count(*) AS total, count(*) FILTER (WHERE self_rating IS NOT NULL) AS rated,
                      count(*) FILTER (WHERE self_rating = 'met') AS met
                 FROM assessment WHERE cycle_id = %s""", (a["patterns_cycle_id"],))
        progress = await cur.fetchone()
    return {"active": a is not None, "activation": a, "progress": progress, "can_edit": user.has(*MANAGERS),
            "pattern_options": PATTERNS}


@router.post("/cycles/{cycle_id}/patterns/activate", status_code=201)
async def activate(cycle_id: int, body: ActivateIn, user: CurrentUser = Depends(current_user),
                   conn: AsyncConnection = Depends(get_conn, scope="function")):
    cycle = await load_cycle(conn, user, cycle_id)
    if not user.has(*MANAGERS):
        raise forbid("تسجيل قرار اعتماد أنماط التدريب من صلاحية وكيل الجودة")
    if any(p not in PATTERNS for p in body.patterns):
        raise forbid("الأنماط المعتمدة: ذاتي، مدمج، عن بعد")
    if await activation(conn, cycle_id):
        raise forbid("أنماط التدريب مفعّلة مسبقاً في هذه الدورة")
    cur = await conn.execute("SELECT id FROM framework WHERE code = 'TVTC-PATTERNS'")
    fw = await cur.fetchone()
    if fw is None:
        raise not_found("إطار منهجية الأنماط غير مستورد")
    await _actor(conn, user)
    # إعادة استخدام دورة الأنماط إن فُعّلت سابقاً ثم أُلغيت (لا يضيع ما أُنجز)
    cur = await conn.execute(
        """SELECT patterns_cycle_id FROM training_pattern_activation WHERE cycle_id = %s AND patterns_cycle_id IS NOT NULL
            ORDER BY id DESC LIMIT 1""", (cycle_id,))
    prev = await cur.fetchone()
    if prev:
        pc_id = prev["patterns_cycle_id"]
    else:
        cur = await conn.execute(
            """INSERT INTO assessment_cycle (institution_id, framework_id, title_ar, academic_year, starts_on, ends_on)
               VALUES (%s, %s, %s, %s, %s, %s) RETURNING id""",
            (cycle["institution_id"], fw["id"], f"منهجية قياس أنماط التدريب {cycle['academic_year']}هـ",
             cycle["academic_year"], cycle["starts_on"], cycle["ends_on"]))
        pc_id = (await cur.fetchone())["id"]
        await conn.execute("SELECT generate_cycle_assessments(%s)", (pc_id,))
        await conn.execute("UPDATE assessment_cycle SET status = 'open' WHERE id = %s", (pc_id,))
    cur = await conn.execute(
        """INSERT INTO training_pattern_activation (cycle_id, patterns_cycle_id, authority_ar, decision_no, decision_date,
                                                    patterns, specialties, notes_ar, created_by)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
        (cycle_id, pc_id, body.authority_ar, body.decision_no, body.decision_date, body.patterns,
         Jsonb([s.model_dump() for s in body.specialties]), body.notes_ar, user.id))
    return {"id": (await cur.fetchone())["id"], "patterns_cycle_id": pc_id}


@router.post("/cycles/{cycle_id}/patterns/revoke")
async def revoke(cycle_id: int, body: RevokeIn, user: CurrentUser = Depends(current_user), conn: AsyncConnection = Depends(get_conn, scope="function")):
    await load_cycle(conn, user, cycle_id)
    if not user.has(*MANAGERS):
        raise forbid("إيقاف أنماط التدريب من صلاحية وكيل الجودة")
    await _actor(conn, user)
    cur = await conn.execute(
        """UPDATE training_pattern_activation SET revoked_at = now(), revoke_reason_ar = %s
            WHERE cycle_id = %s AND revoked_at IS NULL""", (body.reason_ar, cycle_id))
    if not cur.rowcount:
        raise not_found("أنماط التدريب غير مفعّلة")
    return {"active": False}


# ---------------------------------------------------------------- زيارات التقييم الخارجي
@router.get("/cycles/{cycle_id}/external-visits")
async def list_visits(cycle_id: int, user: CurrentUser = Depends(current_user), conn: AsyncConnection = Depends(get_conn, scope="function")):
    await load_cycle(conn, user, cycle_id)
    cur = await conn.execute("SELECT * FROM external_visit WHERE cycle_id = %s ORDER BY visit_date, id", (cycle_id,))
    return await cur.fetchall()


@router.post("/cycles/{cycle_id}/external-visits", status_code=201)
async def add_visit(cycle_id: int, body: VisitIn, user: CurrentUser = Depends(current_user), conn: AsyncConnection = Depends(get_conn, scope="function")):
    await load_cycle(conn, user, cycle_id)
    if not user.has(*MANAGERS):
        raise forbid("جدول الزيارات من صلاحية وكيل الجودة")
    if body.program not in PROGRAMS:
        raise forbid("البرنامج: بكالوريوس أو دبلوم")
    await _actor(conn, user)
    cur = await conn.execute(
        """INSERT INTO external_visit (cycle_id, visit_date, program, supervisor_name, supervisor_phone, college_name,
                                       college_phone, executed, notes_ar, created_by)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
        (cycle_id, body.visit_date, body.program, body.supervisor_name, body.supervisor_phone, body.college_name,
         body.college_phone, body.executed, body.notes_ar, user.id))
    return {"id": (await cur.fetchone())["id"]}


@router.delete("/external-visits/{visit_id}")
async def delete_visit(visit_id: int, user: CurrentUser = Depends(current_user), conn: AsyncConnection = Depends(get_conn, scope="function")):
    if not user.has(*MANAGERS):
        raise forbid("جدول الزيارات من صلاحية وكيل الجودة")
    await _actor(conn, user)
    cur = await conn.execute(
        """DELETE FROM external_visit v USING assessment_cycle c
            WHERE v.id = %s AND c.id = v.cycle_id AND c.institution_id = %s""", (visit_id, user.institution_id))
    if not cur.rowcount:
        raise not_found("الزيارة غير موجودة")
    return {"deleted": True}
