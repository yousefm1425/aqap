"""الشواهد بالروابط (OneDrive / SharePoint التابع للمؤسسة).

- إعدادات المنشأة: طريقة الإرفاق (روابط وملفات / روابط فقط / ملفات فقط) والنطاقات المسموحة.
  تُفرض على كل رابط في قاعدة البيانات (aqap.trg_evidence_link_policy) أياً كان مصدره.
- مجلدات الشواهد: يحدد وكيل الجودة رابط مجلد لكل قسم (عام أو لمعيار أو لمعيار فرعي) في كل دورة،
  فيظهر للقسم زر «فتح مجلد الشواهد» بجانب المتطلب.
- فحص الروابط: يكشف الروابط المحذوفة أو المعطلة قبل زيارة المقيّم الخارجي.
"""
import asyncio
from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Depends
from psycopg import AsyncConnection
from pydantic import BaseModel, Field

from ..security import CurrentUser, current_user, forbid, get_conn, load_cycle, not_found

router = APIRouter(tags=["الشواهد بالروابط"])
MANAGERS = ("quality_dean", "system_admin")
LOGIN_HOSTS = ("login.microsoftonline.com", "login.live.com", "accounts.google.com", "login.windows.net")


class SettingsIn(BaseModel):
    attachment_mode: str = Field(pattern="^(both|links|files)$")
    allowed_link_domains: list[str] = Field(default_factory=list, max_length=20)


class FolderIn(BaseModel):
    department_id: int
    target_code: str | None = None          # فارغ = المجلد العام للقسم، أو رمز معيار (2) أو معيار فرعي (2-1)
    url: str = Field(min_length=10, max_length=2000)


def _manager(user: CurrentUser) -> None:
    if not user.has(*MANAGERS):
        raise forbid("إعداد الشواهد من صلاحية وكيل الجودة")


async def get_settings(conn: AsyncConnection, institution_id: int) -> dict:
    cur = await conn.execute("SELECT attachment_mode, allowed_link_domains FROM institution_setting WHERE institution_id = %s",
                             (institution_id,))
    return await cur.fetchone() or {"attachment_mode": "both", "allowed_link_domains": []}


async def assert_uploads_allowed(conn: AsyncConnection, institution_id: int) -> None:
    """رفع الملفات من المستخدمين (لا يشمل أرشفة المحاضر والنماذج المولّدة من المنصة)."""
    if (await get_settings(conn, institution_id))["attachment_mode"] == "links":
        raise forbid("إعدادات المنشأة تعتمد الروابط فقط: ارفع الملف في مجلد الشواهد على OneDrive/SharePoint ثم أرفق رابطه")


async def assert_link_ok(conn: AsyncConnection, institution_id: int, url: str) -> None:
    s = await get_settings(conn, institution_id)
    if s["attachment_mode"] == "files":
        raise forbid("إعدادات المنشأة تسمح برفع الملفات فقط ولا تقبل الروابط")
    cur = await conn.execute("SELECT link_allowed(%s, %s) AS ok", (institution_id, url))
    if not (await cur.fetchone())["ok"]:
        raise forbid("الرابط ليس من النطاقات المعتمدة للمنشأة (مثل OneDrive أو SharePoint التابع للمؤسسة) أو لا يبدأ بـ https://")


@router.get("/settings/evidence")
async def read_settings(user: CurrentUser = Depends(current_user), conn: AsyncConnection = Depends(get_conn, scope="function")):
    return {**await get_settings(conn, user.institution_id), "can_edit": user.has(*MANAGERS)}


@router.put("/settings/evidence")
async def write_settings(body: SettingsIn, user: CurrentUser = Depends(current_user), conn: AsyncConnection = Depends(get_conn, scope="function")):
    _manager(user)
    domains = sorted({d.strip().lower().removeprefix("https://").removeprefix("http://").strip("/")
                      for d in body.allowed_link_domains if d.strip()})
    await conn.execute("SELECT set_config('aqap.user_id', %s, true)", (str(user.id),))
    await conn.execute(
        """INSERT INTO institution_setting (institution_id, attachment_mode, allowed_link_domains, updated_by)
           VALUES (%s, %s, %s, %s)
           ON CONFLICT (institution_id) DO UPDATE SET attachment_mode = EXCLUDED.attachment_mode,
                 allowed_link_domains = EXCLUDED.allowed_link_domains, updated_by = EXCLUDED.updated_by, updated_at = now()""",
        (user.institution_id, body.attachment_mode, domains, user.id))
    return await get_settings(conn, user.institution_id)


# ---------------------------------------------------------------- مجلدات الشواهد
@router.get("/cycles/{cycle_id}/folders")
async def list_folders(cycle_id: int, department_id: int | None = None, user: CurrentUser = Depends(current_user),
                       conn: AsyncConnection = Depends(get_conn, scope="function")):
    await load_cycle(conn, user, cycle_id)
    all_depts, depts = user.scope(cycle_id)
    cur = await conn.execute(
        """SELECT f.id, f.department_id, f.url, f.updated_at, s.code AS standard_code, ss.code AS sub_standard_code,
                  COALESCE(ss.title_ar, s.title_ar) AS target_title
             FROM evidence_folder f LEFT JOIN standard s ON s.id = f.standard_id
             LEFT JOIN sub_standard ss ON ss.id = f.sub_standard_id
            WHERE f.cycle_id = %(c)s AND (%(all)s OR f.department_id = ANY(%(d)s))
              AND (%(dept)s::bigint IS NULL OR f.department_id = %(dept)s)
            ORDER BY f.department_id, s.code NULLS FIRST, ss.code NULLS FIRST""",
        {"c": cycle_id, "all": all_depts, "d": depts, "dept": department_id})
    return await cur.fetchall()


@router.put("/cycles/{cycle_id}/folders")
async def set_folder(cycle_id: int, body: FolderIn, user: CurrentUser = Depends(current_user),
                     conn: AsyncConnection = Depends(get_conn, scope="function")):
    cycle = await load_cycle(conn, user, cycle_id)
    _manager(user)
    return await _save_folder(conn, user, cycle, body)


class FoldersBulkIn(BaseModel):
    items: list[FolderIn] = Field(min_length=1, max_length=500)


@router.put("/cycles/{cycle_id}/folders/bulk")
async def set_folders_bulk(cycle_id: int, body: FoldersBulkIn, user: CurrentUser = Depends(current_user),
                           conn: AsyncConnection = Depends(get_conn, scope="function")):
    """حفظ روابط مجلدات كثيرة دفعة واحدة (توليدها من مجلد OneDrive رئيسي: معيار ← معيار فرعي ← قسم)."""
    cycle = await load_cycle(conn, user, cycle_id)
    _manager(user)
    for it in body.items:
        await _save_folder(conn, user, cycle, it)
    return {"saved": len(body.items)}


async def _save_folder(conn, user, cycle, body: FolderIn) -> dict:
    cycle_id = cycle["id"]
    url = body.url.strip()
    await assert_link_ok(conn, user.institution_id, url)
    std_id = sub_id = None
    code = (body.target_code or "").strip()
    if code:
        cur = await conn.execute(
            """SELECT 'sub' AS k, ss.id FROM sub_standard ss JOIN standard s ON s.id = ss.standard_id
                WHERE s.framework_id = %(f)s AND ss.code = %(c)s
               UNION ALL SELECT 'std', s.id FROM standard s WHERE s.framework_id = %(f)s AND s.code = %(c)s""",
            {"f": cycle["framework_id"], "c": code})
        row = await cur.fetchone()
        if row is None:
            raise not_found(f"الرمز {code} ليس معياراً ولا معياراً فرعياً في إطار الدورة")
        std_id, sub_id = (row["id"], None) if row["k"] == "std" else (None, row["id"])
    await conn.execute("SELECT set_config('aqap.user_id', %s, true)", (str(user.id),))
    cur = await conn.execute(
        """INSERT INTO evidence_folder (cycle_id, department_id, standard_id, sub_standard_id, url, created_by)
           VALUES (%s, %s, %s, %s, %s, %s)
           ON CONFLICT (cycle_id, department_id, COALESCE(standard_id, 0), COALESCE(sub_standard_id, 0))
           DO UPDATE SET url = EXCLUDED.url, updated_at = now() RETURNING id""",
        (cycle_id, body.department_id, std_id, sub_id, url, user.id))
    return {"id": (await cur.fetchone())["id"]}


@router.delete("/folders/{folder_id}")
async def delete_folder(folder_id: int, user: CurrentUser = Depends(current_user), conn: AsyncConnection = Depends(get_conn, scope="function")):
    _manager(user)
    await conn.execute("SELECT set_config('aqap.user_id', %s, true)", (str(user.id),))
    cur = await conn.execute(
        """DELETE FROM evidence_folder f USING department d
            WHERE f.id = %s AND d.id = f.department_id AND d.institution_id = %s""", (folder_id, user.institution_id))
    if not cur.rowcount:
        raise not_found("المجلد غير موجود")
    return {"deleted": True}


# ---------------------------------------------------------------- فحص الروابط
async def classify(client: httpx.AsyncClient, url: str) -> tuple[str, int | None]:
    """ok: يفتح · restricted: يتطلب دخول المؤسسة (سليم) · broken: محذوف/غير موجود · unreachable: تعذّر الوصول."""
    try:
        current = url
        for _ in range(6):
            r = await client.get(current, follow_redirects=False)
            if r.is_redirect:
                nxt = str(r.next_request.url) if r.next_request else r.headers.get("location", "")
                if urlparse(nxt).hostname in LOGIN_HOSTS:
                    return "restricted", r.status_code
                current = nxt
                continue
            if r.status_code in (401, 403):
                return "restricted", r.status_code
            if r.status_code in (404, 410):
                return "broken", r.status_code
            return ("ok" if r.status_code < 400 else "unreachable"), r.status_code
        return "unreachable", None
    except httpx.HTTPError:
        return "unreachable", None


@router.post("/evidence/links/check")
async def check_links(department_id: int | None = None, limit: int = 300, user: CurrentUser = Depends(current_user),
                      conn: AsyncConnection = Depends(get_conn, scope="function")):
    _manager(user)
    cur = await conn.execute(
        """SELECT id, url FROM evidence WHERE institution_id = %s AND kind = 'link' AND NOT is_archived
              AND (%s::bigint IS NULL OR department_id = %s)
            ORDER BY link_checked_at NULLS FIRST LIMIT %s""", (user.institution_id, department_id, department_id, min(limit, 1000)))
    rows = await cur.fetchall()
    sem = asyncio.Semaphore(10)
    async with httpx.AsyncClient(timeout=8, headers={"User-Agent": "AQAP-LinkCheck/1.0"}) as client:
        async def one(r):
            async with sem:
                return r["id"], *await classify(client, r["url"])
        results = await asyncio.gather(*(one(r) for r in rows))
    now = datetime.now(timezone.utc)
    for ev_id, status, code in results:
        await conn.execute("UPDATE evidence SET link_status = %s, link_http = %s, link_checked_at = %s WHERE id = %s",
                           (status, code, now, ev_id))
    summary = {s: sum(1 for _, x, _ in results if x == s) for s in ("ok", "restricted", "broken", "unreachable")}
    return {"checked": len(results), **summary}


@router.get("/evidence/links/problems")
async def link_problems(department_id: int | None = None, user: CurrentUser = Depends(current_user),
                        conn: AsyncConnection = Depends(get_conn, scope="function")):
    all_depts, depts = user.scope()
    cur = await conn.execute(
        """SELECT e.id, e.title_ar, e.url, e.department_id, d.name_ar AS department_name, e.link_status, e.link_http, e.link_checked_at
             FROM evidence e LEFT JOIN department d ON d.id = e.department_id
            WHERE e.institution_id = %(i)s AND e.kind = 'link' AND NOT e.is_archived
              AND e.link_status IN ('broken','unreachable')
              AND (%(all)s OR e.department_id = ANY(%(d)s))
              AND (%(dept)s::bigint IS NULL OR e.department_id = %(dept)s)
            ORDER BY e.department_id, e.title_ar""",
        {"i": user.institution_id, "all": all_depts, "d": depts, "dept": department_id})
    return await cur.fetchall()
