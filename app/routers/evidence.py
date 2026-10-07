from fastapi import APIRouter, Depends, File, Form, UploadFile
from psycopg import AsyncConnection

from .. import storage
from ..config import settings
from ..schemas import EvidenceCreate
from ..security import INSTITUTION_WIDE, CurrentUser, current_user, forbid, get_conn, not_found

router = APIRouter(prefix="/evidence", tags=["بنك الشواهد"])

UPLOADERS = {"dept_coordinator", "faculty", "hod"}


def _can_see(user: CurrentUser, ev: dict) -> bool:
    if ev["institution_id"] != user.institution_id and not user.has_any("external_reviewer"):
        return False
    if ev["department_id"] is not None and not user.can_view_department(ev["department_id"]):
        if not user.has_any(*INSTITUTION_WIDE, "external_reviewer"):
            return False
    if ev["confidentiality"] == 3:   # سري: وكالة الجودة والمدققون ورئيس القسم المعني
        return user.has_any(*INSTITUTION_WIDE) or user.has("hod", department_id=ev["department_id"])
    if ev["confidentiality"] == 2:   # داخلي: منسوبو الكلية فقط
        return user.institution_id == ev["institution_id"]
    return True


async def _load(conn: AsyncConnection, user: CurrentUser, evidence_id: int) -> dict:
    cur = await conn.execute("SELECT * FROM evidence WHERE id = %s", (evidence_id,))
    ev = await cur.fetchone()
    if ev is None or not _can_see(user, ev):
        raise not_found("الشاهد غير موجود")
    return ev


def _can_upload(user: CurrentUser, department_id: int | None) -> bool:
    return user.has(*UPLOADERS, department_id=department_id) or user.has("quality_dean", "system_admin")


@router.post("", status_code=201)
async def create_evidence(body: EvidenceCreate, user: CurrentUser = Depends(current_user),
                          conn: AsyncConnection = Depends(get_conn)):
    if not _can_upload(user, body.department_id):
        raise forbid("لا تملك صلاحية إضافة شواهد لهذا القسم")
    cur = await conn.execute(
        """INSERT INTO evidence (institution_id, department_id, title_ar, description_ar, kind, url,
                                 confidentiality, created_by)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING *""",
        (user.institution_id, body.department_id, body.title_ar, body.description_ar, body.kind,
         str(body.url) if body.url else None, body.confidentiality, user.id))
    return await cur.fetchone()


@router.get("")
async def list_evidence(department_id: int | None = None, q: str | None = None,
                        user: CurrentUser = Depends(current_user), conn: AsyncConnection = Depends(get_conn)):
    cur = await conn.execute(
        """SELECT e.*, (SELECT count(*) FROM assessment_evidence ae WHERE ae.evidence_id = e.id) AS usage_count
             FROM evidence e
            WHERE e.institution_id = %(inst)s AND NOT e.is_archived
              AND (%(dept)s::bigint IS NULL OR e.department_id = %(dept)s)
              AND (%(q)s::text IS NULL OR e.title_ar ILIKE '%%' || %(q)s || '%%')
            ORDER BY e.updated_at DESC LIMIT 500""",
        {"inst": user.institution_id, "dept": department_id, "q": q})
    return [ev for ev in await cur.fetchall() if _can_see(user, ev)]


@router.post("/{evidence_id}/versions", status_code=201)
async def upload_version(evidence_id: int, file: UploadFile = File(...), change_note: str | None = Form(None),
                         user: CurrentUser = Depends(current_user), conn: AsyncConnection = Depends(get_conn)):
    ev = await _load(conn, user, evidence_id)
    if not _can_upload(user, ev["department_id"]):
        raise forbid("لا تملك صلاحية رفع نسخ لهذا الشاهد")
    if ev["kind"] == "link":
        raise forbid("الشاهد من نوع رابط لا يقبل ملفات")

    sha256, size, ext = await storage.hash_and_validate(file)
    key = storage.build_key(ev["institution_id"], ev["department_id"], evidence_id, ext)
    await storage.put_upload(key, file, size)
    try:
        cur = await conn.execute(
            """INSERT INTO evidence_version (evidence_id, version_no, storage_key, file_name, mime_type,
                                             size_bytes, sha256, change_note, uploaded_by)
               VALUES (%s, 0, %s, %s, %s, %s, %s, %s, %s)
               RETURNING id, evidence_id, version_no, file_name, mime_type, size_bytes, sha256, uploaded_at""",
            (evidence_id, key, file.filename, file.content_type, size, sha256, change_note, user.id))
        return await cur.fetchone()
    except Exception:
        await storage.remove(key)   # لا نترك ملفاً يتيماً إذا فشل التسجيل
        raise


@router.get("/{evidence_id}/versions")
async def list_versions(evidence_id: int, user: CurrentUser = Depends(current_user),
                        conn: AsyncConnection = Depends(get_conn)):
    await _load(conn, user, evidence_id)
    cur = await conn.execute(
        """SELECT v.id, v.version_no, v.file_name, v.mime_type, v.size_bytes, v.sha256, v.change_note,
                  v.uploaded_at, u.full_name_ar AS uploaded_by
             FROM evidence_version v LEFT JOIN app_user u ON u.id = v.uploaded_by
            WHERE v.evidence_id = %s ORDER BY v.version_no DESC""", (evidence_id,))
    return await cur.fetchall()


@router.get("/{evidence_id}/download")
async def download(evidence_id: int, version: int | None = None, user: CurrentUser = Depends(current_user),
                   conn: AsyncConnection = Depends(get_conn)):
    ev = await _load(conn, user, evidence_id)
    if ev["kind"] == "link":
        return {"url": ev["url"], "expires_in": None}
    cur = await conn.execute(
        "SELECT storage_key, file_name FROM evidence_version WHERE evidence_id = %s AND version_no = %s",
        (evidence_id, version or ev["current_version_no"]))
    v = await cur.fetchone()
    if v is None:
        raise not_found("النسخة غير موجودة")
    await conn.execute(
        "INSERT INTO audit_log (table_name, row_key, action, actor_id) VALUES ('evidence_version', %s, 'DOWNLOAD', %s)",
        (f"{evidence_id}:{version or ev['current_version_no']}", user.id))
    url = await storage.download_url(v["storage_key"], v["file_name"] or "evidence")
    return {"url": url, "expires_in": settings.download_url_ttl_seconds}
