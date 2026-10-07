from fastapi import APIRouter, Depends
from psycopg import AsyncConnection

from ..security import CurrentUser, current_user, get_conn, load_cycle

router = APIRouter(prefix="/cycles/{cycle_id}/reports", tags=["التقارير ولوحات المؤشرات"])

_SCOPE = "(%(all)s OR department_id = ANY(%(depts)s))"


async def _rows(conn, user, cycle_id, query, **extra):
    await load_cycle(conn, user, cycle_id)
    all_depts, depts = user.scope(cycle_id)
    cur = await conn.execute(query, {"cycle": cycle_id, "all": all_depts, "depts": depts, **extra})
    return await cur.fetchall()


@router.get("/departments")
async def department_compliance(cycle_id: int, user: CurrentUser = Depends(current_user),
                                conn: AsyncConnection = Depends(get_conn)):
    """ملخص الأقسام: نسب الاستيفاء الذاتية والخارجية والفعلية + أعداد التقرير النهائي."""
    return await _rows(conn, user, cycle_id,
                       f"SELECT * FROM v_department_compliance WHERE cycle_id = %(cycle)s AND {_SCOPE} "
                       "ORDER BY department_id NULLS FIRST")


@router.get("/standards")
async def standard_compliance(cycle_id: int, department_id: int | None = None,
                              user: CurrentUser = Depends(current_user), conn: AsyncConnection = Depends(get_conn)):
    return await _rows(conn, user, cycle_id,
                       f"""SELECT v.cycle_id, v.department_id, v.standard_id, v.standard_code, s.title_ar AS standard_title,
                                  v.total_requirements, v.unrated_count,
                                  round(v.self_pct, 1) AS self_pct, round(v.ext_pct, 1) AS ext_pct,
                                  round(v.eff_pct, 1) AS eff_pct
                             FROM v_standard_compliance v JOIN standard s ON s.id = v.standard_id
                            WHERE v.cycle_id = %(cycle)s AND {_SCOPE.replace('department_id', 'v.department_id')}
                              AND (%(dept)s::bigint IS NULL OR v.department_id = %(dept)s)
                            ORDER BY v.department_id NULLS FIRST, s.sort_order""", dept=department_id)


@router.get("/sub-standards")
async def substandard_compliance(cycle_id: int, department_id: int | None = None,
                                 user: CurrentUser = Depends(current_user), conn: AsyncConnection = Depends(get_conn)):
    return await _rows(conn, user, cycle_id,
                       f"""SELECT cycle_id, department_id, standard_code, sub_standard_code, sub_standard_title,
                                  total_requirements, met_count, partial_count, not_met_count, na_count, unrated_count,
                                  round(self_pct, 1) AS self_pct, round(ext_pct, 1) AS ext_pct, round(eff_pct, 1) AS eff_pct
                             FROM v_substandard_compliance
                            WHERE cycle_id = %(cycle)s AND {_SCOPE}
                              AND (%(dept)s::bigint IS NULL OR department_id = %(dept)s)
                            ORDER BY department_id NULLS FIRST, sub_standard_code""", dept=department_id)


@router.get("/ranking")
async def ranking(cycle_id: int, limit: int = 3, user: CurrentUser = Depends(current_user),
                  conn: AsyncConnection = Depends(get_conn)):
    """أفضل وأضعف المعايير الفرعية على مستوى المنشأة (للتقرير النهائي)."""
    await load_cycle(conn, user, cycle_id)
    cur = await conn.execute(
        "SELECT * FROM v_substandard_ranking WHERE cycle_id = %s AND eff_pct IS NOT NULL", (cycle_id,))
    rows = await cur.fetchall()
    return {"best": sorted(rows, key=lambda r: r["best_rank"])[:limit],
            "worst": sorted(rows, key=lambda r: r["worst_rank"])[:limit]}


@router.get("/gaps")
async def self_external_gaps(cycle_id: int, user: CurrentUser = Depends(current_user),
                             conn: AsyncConnection = Depends(get_conn)):
    return await _rows(conn, user, cycle_id,
                       f"SELECT * FROM v_self_external_gap WHERE cycle_id = %(cycle)s AND {_SCOPE} ORDER BY department_id NULLS FIRST, requirement_code")


@router.get("/missing-evidence")
async def missing_evidence(cycle_id: int, user: CurrentUser = Depends(current_user),
                           conn: AsyncConnection = Depends(get_conn)):
    return await _rows(conn, user, cycle_id,
                       f"SELECT * FROM v_missing_evidence WHERE cycle_id = %(cycle)s AND {_SCOPE} "
                       "ORDER BY department_id NULLS FIRST, requirement_code")


@router.get("/improvement")
async def improvement_summary(cycle_id: int, user: CurrentUser = Depends(current_user),
                              conn: AsyncConnection = Depends(get_conn)):
    """ملخص خطط التحسين لكل قسم: في القسم، قيد المراجعة، قيد التنفيذ، بانتظار التحقق، مغلقة، متأخرة."""
    return await _rows(conn, user, cycle_id,
                       f"""SELECT s.*, COALESCE(d.name_ar, 'متطلبات المنشأة') AS department_name
                             FROM v_improvement_summary s LEFT JOIN department d ON d.id = s.department_id
                            WHERE s.cycle_id = %(cycle)s AND {_SCOPE.replace('department_id', 's.department_id')}
                            ORDER BY s.department_id NULLS FIRST""")


@router.get("/pass-level")
async def pass_level(cycle_id: int, user: CurrentUser = Depends(current_user), conn: AsyncConnection = Depends(get_conn)):
    """مستوى الاجتياز لكل معيار رئيسي وفق صيغة النموذج: لا يقل أي قسم عن 89.5% في التقييم الخارجي."""
    await load_cycle(conn, user, cycle_id)
    cur = await conn.execute(
        """SELECT p.*, s.title_ar AS standard_title FROM v_pass_level p JOIN standard s ON s.id = p.standard_id
            WHERE p.cycle_id = %s ORDER BY s.sort_order""", (cycle_id,))
    rows = await cur.fetchall()
    decided = [r["passed"] for r in rows]
    overall = None if (not rows or any(v is None for v in decided)) else all(decided)
    return {"passed": overall, "threshold_pct": 89.5, "standards": rows}


@router.get("/invalid-na")
async def invalid_na(cycle_id: int, user: CurrentUser = Depends(current_user), conn: AsyncConnection = Depends(get_conn)):
    """تقديرات «لا ينطبق» لا يقبلها شرط النجمة في النموذج (تُحسب «غير متحقق»)."""
    return await _rows(conn, user, cycle_id,
                       f"SELECT * FROM v_invalid_na WHERE cycle_id = %(cycle)s AND {_SCOPE} ORDER BY department_id, requirement_code")
