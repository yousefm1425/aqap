"""النماذج الإلكترونية (الخطط والتقارير): محرّك موحّد لكل متطلب نموذجه «خطة» أو «تقرير».

مسودة ← مرفوع ← (معتمد | معاد). بيانات التخطيط تُقفل بالاعتماد، وبيانات المتابعة تبقى مفتوحة طوال الدورة.
عند الاعتماد يُؤرشف PDF شاهداً في بنك القسم ويُربط بالمتطلب مع الشواهد الداعمة؛ و«أرشفة نسخة المتابعة» تضيف نسخة جديدة.
"""
import hashlib
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from psycopg import AsyncConnection
from psycopg.types.json import Jsonb
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from .. import storage
from ..form_templates import FRAMEWORK, TEMPLATES
from ..forms_engine import FormError, clean_follow, clean_plan, compute, empty_plan, missing_for_submit, summary_record
from ..forms_pdf import render_pdf
from ..linking import ACTIVE_CYCLE, link_to_requirement
from ..schemas import MinutesAttachIn, MinutesTransitionIn
from .evidence_links import assert_link_ok, assert_uploads_allowed
from ..security import CurrentUser, current_user, forbid, get_conn, load_cycle, not_found

router = APIRouter(tags=["النماذج"])

DEPT_ROLES = ("hod", "dept_coordinator", "faculty")
QUALITY = ("quality_dean", "quality_auditor", "system_admin")


class FormCreate(BaseModel):
    template_id: int
    department_id: int


class FormSave(BaseModel):
    plan_data: dict | None = None
    follow_data: dict | None = None


async def sync_templates(conn: AsyncConnection) -> int:
    """يزامن قوالب الكود مع قاعدة البيانات عند التشغيل؛ يرفع الإصدار فقط عند تغيّر القالب."""
    n = 0
    for t in TEMPLATES:
        cur = await conn.execute(
            """INSERT INTO form_template (framework_code, requirement_code, kind, title_ar, schema, guidance_ar,
                                          is_provisional, sort_order)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (framework_code, requirement_code) DO UPDATE
                  SET kind = EXCLUDED.kind, title_ar = EXCLUDED.title_ar, schema = EXCLUDED.schema,
                      guidance_ar = EXCLUDED.guidance_ar, is_provisional = EXCLUDED.is_provisional,
                      sort_order = EXCLUDED.sort_order, version = form_template.version + 1, updated_at = now()
                WHERE (form_template.kind, form_template.title_ar, form_template.schema, form_template.guidance_ar,
                       form_template.is_provisional, form_template.sort_order)
                      IS DISTINCT FROM (EXCLUDED.kind, EXCLUDED.title_ar, EXCLUDED.schema, EXCLUDED.guidance_ar,
                                        EXCLUDED.is_provisional, EXCLUDED.sort_order)
               RETURNING id""",
            (FRAMEWORK, t["requirement_code"], t["kind"], t["title_ar"], Jsonb(t["schema"]),
             t.get("guidance_ar"), t.get("is_provisional", False), t["sort_order"]))
        n += len(await cur.fetchall())
    return n


async def _templates(conn: AsyncConnection, cycle: dict) -> list[dict]:
    cur = await conn.execute(
        """SELECT t.id, t.requirement_code, t.kind, t.title_ar, t.guidance_ar, t.is_provisional, t.sort_order, t.version,
                  r.id AS requirement_id, r.text_ar AS requirement_text,
                  ss.code AS sub_standard_code, ss.title_ar AS sub_standard_title,
                  s.code AS standard_code, s.title_ar AS standard_title
             FROM form_template t
             JOIN framework f ON f.code = t.framework_code
             LEFT JOIN requirement r ON r.code = t.requirement_code AND r.sub_standard_id IN (
                  SELECT ss2.id FROM sub_standard ss2 JOIN standard s2 ON s2.id = ss2.standard_id WHERE s2.framework_id = f.id)
             LEFT JOIN sub_standard ss ON ss.id = r.sub_standard_id
             LEFT JOIN standard s ON s.id = ss.standard_id
            WHERE f.id = %s ORDER BY t.sort_order""", (cycle["framework_id"],))
    return await cur.fetchall()


async def _load(conn: AsyncConnection, user: CurrentUser, form_id: int, lock: bool = False) -> dict:
    cur = await conn.execute("SELECT * FROM form_record WHERE id = %s" + (" FOR UPDATE" if lock else ""), (form_id,))
    f = await cur.fetchone()
    if f is None or not user.can_view_department(f["department_id"], f["cycle_id"]):
        raise not_found("النموذج غير موجود")
    await load_cycle(conn, user, f["cycle_id"])
    return f


def _is_dept(user: CurrentUser, f: dict) -> bool:
    return user.has(*DEPT_ROLES, department_id=f["department_id"], cycle_id=f["cycle_id"])


async def _full(conn: AsyncConnection, form_id: int) -> dict:
    cur = await conn.execute(
        """SELECT f.*, t.requirement_code, t.kind, t.title_ar, t.schema, t.guidance_ar, t.is_provisional, t.version,
                  r.text_ar AS requirement_text, d.name_ar AS department_name, i.name_ar AS institution_name,
                  c.academic_year, c.status AS cycle_status,
                  ua.full_name_ar AS approved_by_name, us.full_name_ar AS submitted_by_name
             FROM form_record f
             JOIN form_template t ON t.id = f.template_id
             JOIN assessment_cycle c ON c.id = f.cycle_id
             JOIN institution i ON i.id = c.institution_id
             JOIN department d ON d.id = f.department_id
             LEFT JOIN requirement r ON r.code = t.requirement_code AND r.sub_standard_id IN (
                  SELECT ss.id FROM sub_standard ss JOIN standard s ON s.id = ss.standard_id WHERE s.framework_id = c.framework_id)
             LEFT JOIN app_user ua ON ua.id = f.approved_by
             LEFT JOIN app_user us ON us.id = f.submitted_by
            WHERE f.id = %s""", (form_id,))
    doc = await cur.fetchone()
    cur = await conn.execute(
        """SELECT h.from_status, h.to_status, h.comment, h.at, u.full_name_ar AS actor
             FROM form_transition h JOIN app_user u ON u.id = h.actor_id WHERE h.form_id = %s ORDER BY h.at""", (form_id,))
    history = await cur.fetchall()
    cur = await conn.execute(
        """SELECT fa.id, fa.evidence_id, fa.note, fa.added_at, u.full_name_ar AS added_by_name,
                  e.title_ar, e.kind::text AS kind, e.url, e.current_version_no, v.file_name, v.size_bytes,
                  EXISTS (SELECT 1 FROM assessment_evidence ae JOIN assessment a ON a.id = ae.assessment_id
                            JOIN requirement r ON r.id = a.requirement_id
                           WHERE ae.evidence_id = fa.evidence_id AND a.cycle_id = %(c)s
                             AND a.department_id = %(d)s AND r.code = %(code)s) AS linked
             FROM form_attachment fa JOIN evidence e ON e.id = fa.evidence_id
             LEFT JOIN evidence_version v ON v.evidence_id = e.id AND v.version_no = e.current_version_no
             LEFT JOIN app_user u ON u.id = fa.added_by
            WHERE fa.form_id = %(f)s ORDER BY fa.added_at, fa.id""",
        {"f": form_id, "c": doc["cycle_id"], "d": doc["department_id"], "code": doc["requirement_code"]})
    attachments = await cur.fetchall()
    calc = compute(doc["schema"], doc["plan_data"], doc["follow_data"])
    return {**doc, "history": history, "attachments": attachments, "computed": calc,
            "missing": missing_for_submit(doc["schema"], doc["plan_data"], doc["follow_data"])}


def _bad(ex: FormError) -> HTTPException:
    return HTTPException(422, str(ex))


# ---------------------------------------------------------------------------
@router.get("/cycles/{cycle_id}/forms/templates")
async def templates(cycle_id: int, department_id: int | None = None, user: CurrentUser = Depends(current_user),
                    conn: AsyncConnection = Depends(get_conn)):
    """قوالب النماذج لإطار الدورة مع حالة نموذج القسم (إن وُجد) ضمن نطاق المستخدم."""
    cycle = await load_cycle(conn, user, cycle_id)
    rows = await _templates(conn, cycle)
    all_depts, depts = user.scope(cycle_id)
    cur = await conn.execute(
        """SELECT id AS form_id, template_id, department_id, status, summary, updated_at FROM form_record
            WHERE cycle_id = %(c)s AND (%(all)s OR department_id = ANY(%(d)s))
              AND (%(dept)s::bigint IS NULL OR department_id = %(dept)s)""",
        {"c": cycle_id, "all": all_depts, "d": depts, "dept": department_id})
    recs = await cur.fetchall()
    # الأقسام التي استُبعد منها متطلب النموذج (لا يظهر لها النموذج)
    cur = await conn.execute(
        """SELECT e.requirement_id, array_agg(e.department_id) AS depts FROM requirement_exclusion e
            WHERE e.revoked_at IS NULL GROUP BY e.requirement_id""")
    excl = {r["requirement_id"]: r["depts"] for r in await cur.fetchall()}
    return [{**t, "excluded_for": excl.get(t["requirement_id"], []),
             "records": [r for r in recs if r["template_id"] == t["id"]]} for t in rows]


@router.post("/cycles/{cycle_id}/forms", status_code=201)
async def create_form(cycle_id: int, body: FormCreate, user: CurrentUser = Depends(current_user),
                      conn: AsyncConnection = Depends(get_conn)):
    cycle = await load_cycle(conn, user, cycle_id)
    if cycle["status"] not in ACTIVE_CYCLE:
        raise forbid("الدورة ليست مفتوحة")
    if not user.has(*DEPT_ROLES, department_id=body.department_id, cycle_id=cycle_id):
        raise forbid("إنشاء النماذج من صلاحية منسوبي القسم")
    cur = await conn.execute("SELECT t.id, t.schema FROM form_template t JOIN framework f ON f.code = t.framework_code "
                             "WHERE t.id = %s AND f.id = %s", (body.template_id, cycle["framework_id"]))
    tpl = await cur.fetchone()
    if tpl is None:
        raise not_found("النموذج غير موجود في إطار هذه الدورة")
    cur = await conn.execute(
        """INSERT INTO form_record (cycle_id, department_id, template_id, plan_data, created_by)
           VALUES (%s, %s, %s, %s, %s) ON CONFLICT (cycle_id, department_id, template_id) DO NOTHING RETURNING id""",
        (cycle_id, body.department_id, tpl["id"], Jsonb(empty_plan(tpl["schema"])), user.id))
    row = await cur.fetchone()
    if row is None:
        raise forbid("للقسم نموذج من هذا النوع في الدورة مسبقاً")
    await _refresh_summary(conn, row["id"])
    return await _full(conn, row["id"])


@router.get("/forms/{form_id}")
async def get_form(form_id: int, user: CurrentUser = Depends(current_user), conn: AsyncConnection = Depends(get_conn)):
    await _load(conn, user, form_id)
    return await _full(conn, form_id)


async def _refresh_summary(conn: AsyncConnection, form_id: int) -> None:
    cur = await conn.execute("SELECT f.plan_data, f.follow_data, t.schema FROM form_record f "
                             "JOIN form_template t ON t.id = f.template_id WHERE f.id = %s", (form_id,))
    r = await cur.fetchone()
    s = summary_record(compute(r["schema"], r["plan_data"], r["follow_data"]))
    await conn.execute("UPDATE form_record SET summary = %s WHERE id = %s", (Jsonb(s), form_id))


def _urls(schema: dict, data) -> set[str]:
    keys = {c["key"] for sec in schema.get("sections", []) for c in sec.get("columns", []) if c.get("type") == "url"}
    out: set[str] = set()

    def walk(x):
        if isinstance(x, dict):
            for k, v in x.items():
                if k in keys and isinstance(v, str) and v.strip():
                    out.add(v.strip())
                else:
                    walk(v)
        elif isinstance(x, (list, tuple)):
            for v in x:
                walk(v)
    walk(data)
    return out


@router.put("/forms/{form_id}")
async def save_form(form_id: int, body: FormSave, user: CurrentUser = Depends(current_user),
                    conn: AsyncConnection = Depends(get_conn)):
    """حفظ التخطيط (المسودة/بعد الإعادة) و/أو المتابعة (في أي وقت عدا انتظار الاعتماد) — القواعد مفروضة في القاعدة."""
    f = await _load(conn, user, form_id, lock=True)
    if not _is_dept(user, f):
        raise forbid("تحرير النموذج من صلاحية منسوبي القسم")
    if f["status"] == "submitted":
        raise HTTPException(409, "النموذج بانتظار قرار رئيس القسم؛ يُعدّل بعد الاعتماد أو الإعادة")
    cur = await conn.execute("SELECT schema FROM form_template WHERE id = %s", (f["template_id"],))
    schema = (await cur.fetchone())["schema"]
    try:
        plan = clean_plan(schema, body.plan_data) if body.plan_data is not None else f["plan_data"]
        follow = clean_follow(schema, plan, body.follow_data if body.follow_data is not None else f["follow_data"])
    except FormError as ex:
        raise _bad(ex)
    for u in _urls(schema, (plan, follow)) - _urls(schema, (f["plan_data"], f["follow_data"])):
        await assert_link_ok(conn, user.institution_id, u)          # روابط الشواهد داخل النموذج تخضع لسياسة المنشأة
    sets, args = [], []
    if body.plan_data is not None and plan != f["plan_data"]:
        sets.append("plan_data = %s"); args.append(Jsonb(plan))
    if follow != f["follow_data"]:
        sets.append("follow_data = %s"); args.append(Jsonb(follow))
    if sets:
        await conn.execute(f"UPDATE form_record SET {', '.join(sets)} WHERE id = %s", (*args, form_id))
        await _refresh_summary(conn, form_id)
    return await _full(conn, form_id)


@router.delete("/forms/{form_id}", status_code=204)
async def delete_form(form_id: int, user: CurrentUser = Depends(current_user), conn: AsyncConnection = Depends(get_conn)):
    f = await _load(conn, user, form_id, lock=True)
    if not _is_dept(user, f):
        raise forbid()
    await conn.execute("DELETE FROM form_record WHERE id = %s", (form_id,))      # المسودة فقط (قاعدة البيانات)


async def _archive(conn: AsyncConnection, user: CurrentUser, form_id: int) -> dict:
    doc = await _full(conn, form_id)
    pdf = await run_in_threadpool(render_pdf, doc)
    await conn.execute("SELECT set_config('aqap.system_op', 'on', true)")
    try:
        ev_id = doc["evidence_id"]
        first = ev_id is None
        if first:
            cur = await conn.execute(
                """INSERT INTO evidence (institution_id, department_id, title_ar, description_ar, kind, created_by)
                   SELECT c.institution_id, %s, %s, %s, 'file', %s FROM assessment_cycle c WHERE c.id = %s RETURNING id""",
                (doc["department_id"], f"{doc['requirement_code']} {doc['title_ar']}",
                 f"مولّد من منصة AQAP للمتطلب {doc['requirement_code']} (المرجع AQAP-F-{form_id})", user.id, doc["cycle_id"]))
            ev_id = (await cur.fetchone())["id"]
            await conn.execute("UPDATE form_record SET evidence_id = %s WHERE id = %s", (ev_id, form_id))
        key = storage.build_key(user.institution_id, doc["department_id"], ev_id, ".pdf")
        await storage.put_bytes(key, pdf, "application/pdf")
        cur = await conn.execute(
            """INSERT INTO evidence_version (evidence_id, version_no, storage_key, file_name, mime_type, size_bytes, sha256,
                                             change_note, uploaded_by)
               VALUES (%s, 0, %s, %s, 'application/pdf', %s, %s, %s, %s) RETURNING version_no""",
            (ev_id, key, f"{doc['requirement_code']}-{doc['kind'] == 'plan' and 'خطة' or 'تقرير'}.pdf", len(pdf),
             hashlib.sha256(pdf).hexdigest(),
             "اعتماد النموذج" if first else "تحديث المتابعة", user.id))
        version = (await cur.fetchone())["version_no"]
    finally:
        await conn.execute("SELECT set_config('aqap.system_op', 'off', true)")
    args = (doc["cycle_id"], doc["department_id"], doc["requirement_code"], doc["cycle_status"])
    linked = await link_to_requirement(conn, user, *args, ev_id, f"نموذج AQAP-F-{form_id}")
    attached = 0
    for att in doc["attachments"]:
        if await link_to_requirement(conn, user, *args, att["evidence_id"], f"شاهد داعم لنموذج AQAP-F-{form_id}"):
            attached += 1
    return {"evidence_id": ev_id, "version_no": version, "linked_to_requirement": linked, "attachments_linked": attached}


@router.post("/forms/{form_id}/transition")
async def transition(form_id: int, body: MinutesTransitionIn, user: CurrentUser = Depends(current_user),
                     conn: AsyncConnection = Depends(get_conn)):
    f = await _load(conn, user, form_id)
    if body.to_status == "submitted" and f["status"] in ("draft", "returned"):
        doc = await _full(conn, form_id)
        if doc["missing"]:
            raise forbid("أكمل النموذج قبل الرفع: " + " · ".join(doc["missing"][:4]))
    cur = await conn.execute("SELECT transition_form(%s, %s, %s, %s) AS s", (form_id, body.to_status, user.id, body.comment))
    result = {"form_id": form_id, "status": (await cur.fetchone())["s"]}
    if body.to_status == "approved":
        result["archive"] = await _archive(conn, user, form_id)
    return result


@router.post("/forms/{form_id}/archive")
async def archive_follow_up(form_id: int, user: CurrentUser = Depends(current_user), conn: AsyncConnection = Depends(get_conn)):
    """نسخة مؤرشفة جديدة من النموذج المعتمد تتضمن آخر المتابعة."""
    f = await _load(conn, user, form_id)
    if f["status"] != "approved":
        raise forbid("الأرشفة للنموذج المعتمد فقط")
    if not (_is_dept(user, f) or user.has(*QUALITY, cycle_id=f["cycle_id"])):
        raise forbid()
    return await _archive(conn, user, form_id)


@router.get("/forms/{form_id}/pdf")
async def form_pdf(form_id: int, user: CurrentUser = Depends(current_user), conn: AsyncConnection = Depends(get_conn)):
    await _load(conn, user, form_id)
    doc = await _full(conn, form_id)
    pdf = await run_in_threadpool(render_pdf, doc)
    name = f"{doc['requirement_code']}-{doc['department_name']}.pdf"
    return Response(pdf, media_type="application/pdf", headers={"Content-Disposition": f"inline; filename*=UTF-8''{quote(name)}"})


# ---------------------------------------------------------------------------
# الشواهد الداعمة
# ---------------------------------------------------------------------------
async def _attach_target(conn: AsyncConnection, user: CurrentUser, form_id: int) -> dict:
    f = await _load(conn, user, form_id, lock=True)
    if not _is_dept(user, f):
        raise forbid("إرفاق الشواهد من صلاحية منسوبي القسم")
    cur = await conn.execute("SELECT status FROM assessment_cycle WHERE id = %s", (f["cycle_id"],))
    if (await cur.fetchone())["status"] not in ACTIVE_CYCLE:
        raise forbid("الدورة ليست مفتوحة")
    return f


async def _attach(conn: AsyncConnection, user: CurrentUser, f: dict, evidence_id: int, note: str | None) -> dict:
    cur = await conn.execute(
        """INSERT INTO form_attachment (form_id, evidence_id, note, added_by) VALUES (%s, %s, %s, %s)
           ON CONFLICT (form_id, evidence_id) DO NOTHING RETURNING id""", (f["id"], evidence_id, note, user.id))
    if await cur.fetchone() is None:
        raise forbid("الشاهد مرفق بهذا النموذج مسبقاً")
    linked = None
    full = await _full(conn, f["id"])
    if f["status"] == "approved":
        linked = await link_to_requirement(conn, user, full["cycle_id"], full["department_id"], full["requirement_code"],
                                           full["cycle_status"], evidence_id, f"شاهد داعم لنموذج AQAP-F-{f['id']}")
        full = await _full(conn, f["id"])
    return {"attachments": full["attachments"], "evidence_id": evidence_id, "linked_to_requirement": linked}


@router.post("/forms/{form_id}/attachments", status_code=201)
async def attach(form_id: int, body: MinutesAttachIn, user: CurrentUser = Depends(current_user),
                 conn: AsyncConnection = Depends(get_conn)):
    f = await _attach_target(conn, user, form_id)
    if body.evidence_id is not None:
        cur = await conn.execute("SELECT id FROM evidence WHERE id = %s AND institution_id = %s AND NOT is_archived",
                                 (body.evidence_id, user.institution_id))
        if await cur.fetchone() is None:
            raise not_found("الشاهد غير موجود")
        ev_id = body.evidence_id
    else:
        cur = await conn.execute(
            """INSERT INTO evidence (institution_id, department_id, title_ar, description_ar, kind, url, created_by)
               VALUES (%s, %s, %s, %s, 'link', %s, %s) RETURNING id""",
            (user.institution_id, f["department_id"], body.title_ar, f"شاهد داعم لنموذج AQAP-F-{form_id}",
             str(body.url), user.id))
        ev_id = (await cur.fetchone())["id"]
    return await _attach(conn, user, f, ev_id, body.note)


@router.post("/forms/{form_id}/attachments/upload", status_code=201)
async def attach_upload(form_id: int, file: UploadFile = File(...), title_ar: str | None = Form(None),
                        note: str | None = Form(None), user: CurrentUser = Depends(current_user),
                        conn: AsyncConnection = Depends(get_conn)):
    f = await _attach_target(conn, user, form_id)
    if f["status"] == "submitted":
        raise forbid("النموذج بانتظار قرار رئيس القسم؛ أضف الشواهد بعد الاعتماد أو الإعادة")
    await assert_uploads_allowed(conn, user.institution_id)
    title = (title_ar or "").strip() or (file.filename or "شاهد داعم").rsplit(".", 1)[0]
    if len(title) < 3:
        title = f"شاهد داعم — {title}"
    cur = await conn.execute(
        """INSERT INTO evidence (institution_id, department_id, title_ar, description_ar, kind, created_by)
           VALUES (%s, %s, %s, %s, 'file', %s) RETURNING id""",
        (user.institution_id, f["department_id"], title[:300], f"شاهد داعم لنموذج AQAP-F-{form_id}", user.id))
    ev_id = (await cur.fetchone())["id"]
    sha256, size, ext = await storage.hash_and_validate(file)
    key = storage.build_key(user.institution_id, f["department_id"], ev_id, ext)
    await storage.put_upload(key, file, size)
    try:
        await conn.execute(
            """INSERT INTO evidence_version (evidence_id, version_no, storage_key, file_name, mime_type,
                                             size_bytes, sha256, change_note, uploaded_by)
               VALUES (%s, 0, %s, %s, %s, %s, %s, %s, %s)""",
            (ev_id, key, file.filename, file.content_type, size, sha256, "شاهد داعم للنموذج", user.id))
        return await _attach(conn, user, f, ev_id, note)
    except Exception:
        await storage.remove(key)
        raise


@router.delete("/forms/{form_id}/attachments/{evidence_id}", status_code=204)
async def detach(form_id: int, evidence_id: int, user: CurrentUser = Depends(current_user),
                 conn: AsyncConnection = Depends(get_conn)):
    f = await _attach_target(conn, user, form_id)
    cur = await conn.execute("DELETE FROM form_attachment WHERE form_id = %s AND evidence_id = %s RETURNING id",
                             (f["id"], evidence_id))
    if await cur.fetchone() is None:
        raise not_found("الشاهد غير مرفق بهذا النموذج")
