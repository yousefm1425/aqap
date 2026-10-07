from fastapi import APIRouter, Depends, Query
from psycopg import AsyncConnection, sql

from ..schemas import AssessmentStatus, EvidenceLink, ExternalAssessmentPatch, SelfAssessmentPatch, TransitionIn
from ..security import DEPT_EDITORS, CurrentUser, current_user, forbid, get_conn, load_cycle, not_found

router = APIRouter(tags=["التقديرات"])

_LIST_SQL = """
SELECT a.id, a.cycle_id, a.department_id, a.status, a.due_date, a.assigned_to,
       a.self_rating, a.ext_verdict,
       effective_rating(a.self_rating, a.ext_verdict, na_allowed(a.requirement_id, a.department_id)) AS eff_rating,
       na_allowed(a.requirement_id, a.department_id) AS na_ok,
       s.code AS standard_code, ss.code AS sub_standard_code, ss.title_ar AS sub_standard_title,
       r.id AS requirement_id, r.code AS requirement_code, r.text_ar AS requirement_text, r.evidence_required,
       (SELECT count(*) FROM assessment_evidence ae WHERE ae.assessment_id = a.id) AS evidence_count
  FROM assessment a
  JOIN requirement r   ON r.id = a.requirement_id
  JOIN sub_standard ss ON ss.id = r.sub_standard_id
  JOIN standard s      ON s.id = ss.standard_id
 WHERE a.cycle_id = %(cycle)s
   AND (%(all)s OR a.department_id = ANY(%(depts)s))
   AND (%(dept)s::bigint IS NULL OR a.department_id = %(dept)s)
   AND (%(status)s::aqap.assessment_status_t IS NULL OR a.status = %(status)s)
 ORDER BY a.department_id NULLS FIRST, s.sort_order, ss.sort_order, r.sort_order
"""


async def _load(conn: AsyncConnection, user: CurrentUser, assessment_id: int, lock: bool = False) -> dict:
    q = "SELECT * FROM assessment WHERE id = %s" + (" FOR UPDATE" if lock else "")
    cur = await conn.execute(q, (assessment_id,))
    a = await cur.fetchone()
    if a is None or not user.can_view_department(a["department_id"], a["cycle_id"]):
        raise not_found("التقدير غير موجود")
    await load_cycle(conn, user, a["cycle_id"])
    return a


async def _patch(conn: AsyncConnection, assessment_id: int, fields: dict) -> dict:
    if not fields:
        cur = await conn.execute("SELECT * FROM assessment WHERE id = %s", (assessment_id,))
        return await cur.fetchone()
    q = sql.SQL("UPDATE assessment SET {} WHERE id = %(id)s RETURNING *").format(
        sql.SQL(", ").join(sql.SQL("{} = {}").format(sql.Identifier(k), sql.Placeholder(k)) for k in fields))
    cur = await conn.execute(q, {**fields, "id": assessment_id})
    return await cur.fetchone()


@router.get("/cycles/{cycle_id}/assessments")
async def list_assessments(cycle_id: int, department_id: int | None = None,
                           status: AssessmentStatus | None = Query(default=None),
                           user: CurrentUser = Depends(current_user), conn: AsyncConnection = Depends(get_conn)):
    await load_cycle(conn, user, cycle_id)
    all_depts, depts = user.scope(cycle_id)
    cur = await conn.execute(_LIST_SQL, {"cycle": cycle_id, "all": all_depts, "depts": depts,
                                         "dept": department_id, "status": status})
    return await cur.fetchall()


@router.get("/assessments/{assessment_id}")
async def get_assessment(assessment_id: int, user: CurrentUser = Depends(current_user),
                         conn: AsyncConnection = Depends(get_conn)):
    a = await _load(conn, user, assessment_id)
    cur = await conn.execute(
        """SELECT r.code, r.text_ar, r.guidance_ar, r.expected_evidence_ar, r.evidence_required,
                  na_allowed(r.id, %s) AS na_ok,
                  ss.code AS sub_standard_code, ss.title_ar AS sub_standard_title,
                  s.code AS standard_code, s.title_ar AS standard_title
             FROM requirement r JOIN sub_standard ss ON ss.id = r.sub_standard_id
             JOIN standard s ON s.id = ss.standard_id WHERE r.id = %s""", (a["department_id"], a["requirement_id"]))
    requirement = await cur.fetchone()
    cur = await conn.execute(
        """SELECT e.id, e.title_ar, e.kind, e.url, e.current_version_no, ae.pinned_version_no, ae.note, ae.linked_at
             FROM assessment_evidence ae JOIN evidence e ON e.id = ae.evidence_id
            WHERE ae.assessment_id = %s ORDER BY ae.linked_at""", (assessment_id,))
    evidence = await cur.fetchall()
    cur = await conn.execute(
        """SELECT t.from_status, t.to_status, t.comment, t.at, u.full_name_ar AS actor
             FROM assessment_transition t JOIN app_user u ON u.id = t.actor_id
            WHERE t.assessment_id = %s ORDER BY t.at""", (assessment_id,))
    history = await cur.fetchall()
    eff = await conn.execute("SELECT effective_rating(%s, %s, %s) AS r", (a["self_rating"], a["ext_verdict"], requirement["na_ok"]))
    return {**a, "eff_rating": (await eff.fetchone())["r"], "requirement": requirement, "evidence": evidence, "history": history}


@router.patch("/assessments/{assessment_id}/self")
async def patch_self(assessment_id: int, body: SelfAssessmentPatch, user: CurrentUser = Depends(current_user),
                     conn: AsyncConnection = Depends(get_conn)):
    a = await _load(conn, user, assessment_id, lock=True)
    if not user.has(*DEPT_EDITORS, department_id=a["department_id"], cycle_id=a["cycle_id"]):
        raise forbid("التقييم الذاتي من صلاحية منسق القسم أو أعضائه")
    return await _patch(conn, assessment_id, body.model_dump(exclude_unset=True))


@router.patch("/assessments/{assessment_id}/external")
async def patch_external(assessment_id: int, body: ExternalAssessmentPatch,
                         user: CurrentUser = Depends(current_user), conn: AsyncConnection = Depends(get_conn)):
    a = await _load(conn, user, assessment_id, lock=True)
    if not user.has("quality_auditor", "external_reviewer", department_id=a["department_id"], cycle_id=a["cycle_id"]):
        raise forbid("التقييم الخارجي من صلاحية المدقق أو المقيّم الخارجي")
    return await _patch(conn, assessment_id, body.model_dump(exclude_unset=True))


@router.post("/assessments/{assessment_id}/transition")
async def transition(assessment_id: int, body: TransitionIn, user: CurrentUser = Depends(current_user),
                     conn: AsyncConnection = Depends(get_conn)):
    await _load(conn, user, assessment_id)
    # الصلاحية وشروط الاكتمال تُفحص داخل aqap.transition_assessment
    cur = await conn.execute("SELECT transition_assessment(%s, %s, %s, %s) AS status",
                             (assessment_id, body.to_status, user.id, body.comment))
    return {"assessment_id": assessment_id, "status": (await cur.fetchone())["status"]}


@router.post("/assessments/{assessment_id}/evidence", status_code=201)
async def link_evidence(assessment_id: int, body: EvidenceLink, user: CurrentUser = Depends(current_user),
                        conn: AsyncConnection = Depends(get_conn)):
    a = await _load(conn, user, assessment_id)
    if not user.has(*DEPT_EDITORS, department_id=a["department_id"], cycle_id=a["cycle_id"]):
        raise forbid("ربط الشواهد من صلاحية منسق القسم أو أعضائه")
    cur = await conn.execute("SELECT institution_id, department_id, is_archived FROM evidence WHERE id = %s",
                             (body.evidence_id,))
    ev = await cur.fetchone()
    if (ev is None or ev["is_archived"] or ev["institution_id"] != user.institution_id
            or (ev["department_id"] is not None and not user.can_view_department(ev["department_id"], a["cycle_id"]))):
        raise not_found("الشاهد غير موجود")
    if ev["department_id"] not in (None, a["department_id"]):
        raise forbid("لا يمكن ربط شاهد قسم آخر")
    await conn.execute(
        "INSERT INTO assessment_evidence (assessment_id, evidence_id, note, linked_by) VALUES (%s, %s, %s, %s)",
        (assessment_id, body.evidence_id, body.note, user.id))
    return {"assessment_id": assessment_id, "evidence_id": body.evidence_id}


@router.delete("/assessments/{assessment_id}/evidence/{evidence_id}", status_code=204)
async def unlink_evidence(assessment_id: int, evidence_id: int, user: CurrentUser = Depends(current_user),
                          conn: AsyncConnection = Depends(get_conn)):
    a = await _load(conn, user, assessment_id)
    if not user.has(*DEPT_EDITORS, department_id=a["department_id"], cycle_id=a["cycle_id"]):
        raise forbid()
    cur = await conn.execute("DELETE FROM assessment_evidence WHERE assessment_id = %s AND evidence_id = %s",
                             (assessment_id, evidence_id))
    if cur.rowcount == 0:
        raise not_found("الربط غير موجود")
