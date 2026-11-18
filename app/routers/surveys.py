"""الاستبيانات: استبيان المتدرب، واستبيان المدرب، واستبيان الخدمات المقدمة من الكلية للجميع (موظفين ومدربين ومتدربين).

التعبئة في Microsoft Forms المقيّد بحساب المؤسسة («يمكن فقط للأشخاص في مؤسستي الرد») فلا يفتح النموذج إلا ببريد المؤسسة،
ويرفع وكيل الجودة ملف الردود المصدَّر منه لتظهر الإحصاءات هنا. البريد والاسم في ملف الردود لا يُحفظان.
"""
from datetime import date
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, File, UploadFile
from psycopg import AsyncConnection
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field

from ..security import CurrentUser, current_user, forbid, get_conn, load_cycle, not_found
from ..survey_stats import SurveyFileError, compute, parse_responses

router = APIRouter(tags=["الاستبيانات"])
MANAGERS = ("quality_dean", "system_admin")
VIEWERS = ("quality_dean", "quality_auditor", "system_admin", "hod")
MAX_BYTES = 10 * 1024 * 1024

KINDS = {
    "trainee": {"title_ar": "استبيان رضا المتدربين", "audience_ar": "المتدربون",
                "hint_ar": "رضا المتدرب عن التدريب والمدربين والمقررات والبيئة التدريبية"},
    "trainer": {"title_ar": "استبيان رضا المدربين", "audience_ar": "المدربون",
                "hint_ar": "رضا المدرب عن بيئة العمل والموارد والدعم والتطوير المهني"},
    "services": {"title_ar": "استبيان رضا المستفيدين عن خدمات الكلية", "audience_ar": "الجميع: الموظفون والمدربون والمتدربون",
                 "hint_ar": "الخدمات المساندة: القبول والتسجيل، المكتبة، المعامل، الإرشاد، المرافق، الخدمات الإلكترونية وغيرها"},
}
FORM_HOSTS = ("forms.office.com", "forms.microsoft.com", "forms.cloud.microsoft")
RESULT_HOSTS = FORM_HOSTS + ("onedrive.live.com",)


def _host_ok(url: str, hosts: tuple[str, ...]) -> bool:
    u = urlparse(url)
    host = (u.hostname or "").lower()
    return u.scheme == "https" and (host in hosts or host.endswith(".sharepoint.com"))


class SurveyIn(BaseModel):
    title_ar: str = Field(min_length=3, max_length=200)
    form_url: str | None = Field(default=None, max_length=2000)
    results_url: str | None = Field(default=None, max_length=2000)
    opens_on: date | None = None
    closes_on: date | None = None


def _kind(kind: str) -> dict:
    if kind not in KINDS:
        raise not_found("نوع الاستبيان غير معروف")
    return KINDS[kind]


def _summary(kind: str, row: dict | None, count: int) -> dict:
    base = KINDS[kind]
    today = date.today()
    st = "draft"
    if row and row["form_url"]:
        st = "closed" if row["closes_on"] and row["closes_on"] < today else \
             "scheduled" if row["opens_on"] and row["opens_on"] > today else "open"
    return {"kind": kind, "id": row and row["id"], "title_ar": (row and row["title_ar"]) or base["title_ar"],
            "audience_ar": base["audience_ar"], "hint_ar": base["hint_ar"], "form_url": row and row["form_url"],
            "results_url": row and row["results_url"], "opens_on": row and row["opens_on"],
            "closes_on": row and row["closes_on"], "state": st, "responses": count,
            "questions": len(row["questions"]) if row else 0, "source_name": row and row["source_name"],
            "uploaded_at": row and row["uploaded_at"], "uploaded_by_name": row and row["uploaded_by_name"]}


async def _row(conn: AsyncConnection, cycle_id: int, kind: str) -> dict | None:
    cur = await conn.execute(
        """SELECT s.*, u.full_name_ar AS uploaded_by_name FROM survey s LEFT JOIN app_user u ON u.id = s.uploaded_by
            WHERE s.cycle_id = %s AND s.kind = %s""", (cycle_id, kind))
    return await cur.fetchone()


@router.get("/cycles/{cycle_id}/surveys")
async def list_surveys(cycle_id: int, user: CurrentUser = Depends(current_user),
                       conn: AsyncConnection = Depends(get_conn, scope="function")):
    await load_cycle(conn, user, cycle_id)
    cur = await conn.execute(
        """SELECT s.*, u.full_name_ar AS uploaded_by_name,
                  (SELECT count(*) FROM survey_response r WHERE r.survey_id = s.id) AS n
             FROM survey s LEFT JOIN app_user u ON u.id = s.uploaded_by WHERE s.cycle_id = %s""", (cycle_id,))
    rows = {r["kind"]: r for r in await cur.fetchall()}
    items = []
    can_stats = user.has_any(*VIEWERS)
    for k in KINDS:
        s = _summary(k, rows.get(k), rows[k]["n"] if k in rows else 0)
        if can_stats and s["responses"]:
            q = rows[k]
            cur = await conn.execute("SELECT answers FROM survey_response WHERE survey_id = %s", (q["id"],))
            st = compute(q["questions"], [r["answers"] for r in await cur.fetchall()])
            s["overall"] = st["overall"]
        if not can_stats:
            s["responses"] = None
        items.append(s)
    return {"can_manage": user.has_any(*MANAGERS), "can_view_stats": can_stats, "items": items}


@router.put("/cycles/{cycle_id}/surveys/{kind}")
async def save_survey(cycle_id: int, kind: str, body: SurveyIn, user: CurrentUser = Depends(current_user),
                      conn: AsyncConnection = Depends(get_conn, scope="function")):
    await load_cycle(conn, user, cycle_id)
    _kind(kind)
    if not user.has_any(*MANAGERS):
        raise forbid("إعداد الاستبيانات من صلاحية وكيل الجودة")
    form_url = (body.form_url or "").strip() or None
    results_url = (body.results_url or "").strip() or None
    if form_url and not _host_ok(form_url, FORM_HOSTS):
        raise forbid("رابط الاستبيان يجب أن يكون رابط Microsoft Forms (forms.office.com) يبدأ بـ https")
    if results_url and not _host_ok(results_url, RESULT_HOSTS):
        raise forbid("رابط الردود يجب أن يكون من Microsoft Forms أو OneDrive / SharePoint المؤسسة")
    if body.opens_on and body.closes_on and body.closes_on < body.opens_on:
        raise forbid("تاريخ الإغلاق قبل تاريخ الفتح")
    await conn.execute("SELECT set_config('aqap.user_id', %s, true)", (str(user.id),))
    await conn.execute(
        """INSERT INTO survey (cycle_id, kind, title_ar, form_url, results_url, opens_on, closes_on, updated_by)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
           ON CONFLICT (cycle_id, kind) DO UPDATE SET title_ar = EXCLUDED.title_ar, form_url = EXCLUDED.form_url,
               results_url = EXCLUDED.results_url, opens_on = EXCLUDED.opens_on, closes_on = EXCLUDED.closes_on,
               updated_by = EXCLUDED.updated_by, updated_at = now()""",
        (cycle_id, kind, body.title_ar.strip(), form_url, results_url, body.opens_on, body.closes_on, user.id))
    return _summary(kind, await _row(conn, cycle_id, kind), 0) | {"saved": True}


@router.post("/cycles/{cycle_id}/surveys/{kind}/responses")
async def upload_responses(cycle_id: int, kind: str, file: UploadFile = File(...), user: CurrentUser = Depends(current_user),
                           conn: AsyncConnection = Depends(get_conn, scope="function")):
    """يستبدل ردود الاستبيان بملف Microsoft Forms المصدَّر (الملف تراكمي يحوي كل الردود حتى لحظة التصدير)."""
    await load_cycle(conn, user, cycle_id)
    base = _kind(kind)
    if not user.has_any(*MANAGERS):
        raise forbid("رفع ردود الاستبيانات من صلاحية وكيل الجودة")
    data = await file.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise forbid("حجم الملف أكبر من 10 ميجابايت")
    try:
        questions, responses = parse_responses(file.filename or "", data)
    except SurveyFileError as ex:
        raise forbid(str(ex)) from ex
    await conn.execute("SELECT set_config('aqap.user_id', %s, true)", (str(user.id),))
    cur = await conn.execute(
        """INSERT INTO survey (cycle_id, kind, title_ar, questions, source_name, uploaded_by, uploaded_at, updated_by)
           VALUES (%s, %s, %s, %s, %s, %s, now(), %s)
           ON CONFLICT (cycle_id, kind) DO UPDATE SET questions = EXCLUDED.questions, source_name = EXCLUDED.source_name,
               uploaded_by = EXCLUDED.uploaded_by, uploaded_at = now()
           RETURNING id""",
        (cycle_id, kind, base["title_ar"], Jsonb(questions), (file.filename or "")[:200], user.id, user.id))
    sid = (await cur.fetchone())["id"]
    await conn.execute("DELETE FROM survey_response WHERE survey_id = %s", (sid,))
    async with conn.cursor() as c:
        await c.executemany(
            "INSERT INTO survey_response (survey_id, ext_id, submitted_at, answers) VALUES (%s, %s, %s, %s)",
            [(sid, r["ext_id"], r["submitted_at"], Jsonb(r["answers"])) for r in responses])
    st = compute(questions, [r["answers"] for r in responses])
    return {"responses": len(responses), "questions": len(questions), "overall": st["overall"],
            "types": {t: sum(1 for q in st["questions"] if q["type"] == t) for t in ("scale", "rating", "choice", "multi", "text")}}


@router.delete("/cycles/{cycle_id}/surveys/{kind}/responses")
async def clear_responses(cycle_id: int, kind: str, user: CurrentUser = Depends(current_user),
                          conn: AsyncConnection = Depends(get_conn, scope="function")):
    await load_cycle(conn, user, cycle_id)
    _kind(kind)
    if not user.has_any(*MANAGERS):
        raise forbid("حذف الردود من صلاحية وكيل الجودة")
    row = await _row(conn, cycle_id, kind)
    if not row:
        raise not_found("لا توجد ردود مرفوعة")
    await conn.execute("SELECT set_config('aqap.user_id', %s, true)", (str(user.id),))
    cur = await conn.execute("DELETE FROM survey_response WHERE survey_id = %s", (row["id"],))
    await conn.execute("UPDATE survey SET questions = '[]', source_name = NULL, uploaded_at = NULL, uploaded_by = NULL WHERE id = %s",
                       (row["id"],))
    return {"deleted": cur.rowcount}


@router.get("/cycles/{cycle_id}/surveys/{kind}/stats")
async def survey_stats(cycle_id: int, kind: str, q: int | None = None, v: str | None = None,
                       user: CurrentUser = Depends(current_user), conn: AsyncConnection = Depends(get_conn, scope="function")):
    await load_cycle(conn, user, cycle_id)
    _kind(kind)
    if not user.has_any(*VIEWERS):
        raise forbid("إحصاءات الاستبيانات متاحة لوكالة الجودة ورؤساء الأقسام")
    row = await _row(conn, cycle_id, kind)
    if not row:
        return _summary(kind, None, 0) | {"stats": None}
    cur = await conn.execute(
        "SELECT answers, submitted_at FROM survey_response WHERE survey_id = %s ORDER BY submitted_at NULLS LAST", (row["id"],))
    rows = await cur.fetchall()
    stats = compute(row["questions"], [r["answers"] for r in rows], q, v) if rows else None
    dates = [r["submitted_at"] for r in rows if r["submitted_at"]]
    return _summary(kind, row, len(rows)) | {
        "stats": stats, "filter": {"q": q, "v": v} if q is not None and v is not None else None,
        "first_at": min(dates) if dates else None, "last_at": max(dates) if dates else None}
