"""تقارير الكلية المجمّعة من نماذج الأقسام، وتصديرها Excel بأعمدة ملفات الإدارة."""
import tempfile
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, BackgroundTasks, Depends
from fastapi.responses import FileResponse
from psycopg import AsyncConnection
from starlette.concurrency import run_in_threadpool

from .. import college_reports as cr
from ..security import CurrentUser, current_user, get_conn, load_cycle, not_found

router = APIRouter(tags=["تقارير الكلية"])


async def _depts(conn: AsyncConnection, user: CurrentUser, cycle_id: int) -> list[int]:
    all_depts, depts = user.scope(cycle_id)
    cur = await conn.execute("SELECT department_id FROM cycle_department WHERE cycle_id = %s", (cycle_id,))
    return [r["department_id"] for r in await cur.fetchall() if all_depts or r["department_id"] in depts]


@router.get("/cycles/{cycle_id}/college-reports")
async def list_reports(cycle_id: int, user: CurrentUser = Depends(current_user), conn: AsyncConnection = Depends(get_conn)):
    await load_cycle(conn, user, cycle_id)
    return cr.catalog()


@router.get("/cycles/{cycle_id}/college-reports/{key}")
async def get_report(cycle_id: int, key: str, f: str | None = None, user: CurrentUser = Depends(current_user),
                     conn: AsyncConnection = Depends(get_conn)):
    await load_cycle(conn, user, cycle_id)
    if key not in cr.BY_KEY:
        raise not_found("التقرير غير موجود")
    return await cr.build_report(conn, cycle_id, key, f, await _depts(conn, user, cycle_id))


@router.get("/cycles/{cycle_id}/college-reports/{key}/xlsx")
async def export_report(cycle_id: int, key: str, background: BackgroundTasks, f: str | None = None,
                        user: CurrentUser = Depends(current_user), conn: AsyncConnection = Depends(get_conn)):
    cycle = await load_cycle(conn, user, cycle_id)
    if key not in cr.BY_KEY:
        raise not_found("التقرير غير موجود")
    data = await cr.build_report(conn, cycle_id, key, f, await _depts(conn, user, cycle_id))
    cur = await conn.execute("SELECT name_ar, region_ar FROM institution WHERE id = %s", (cycle["institution_id"],))
    inst = await cur.fetchone()
    out = Path(tempfile.mkdtemp(prefix="aqap-college-")) / "report.xlsx"
    await run_in_threadpool(cr.to_xlsx, data, inst["name_ar"], cycle["academic_year"], str(out), inst["region_ar"])
    background.add_task(lambda: (out.unlink(missing_ok=True), out.parent.rmdir()))
    name = f"{data['title']}{' - ' + data['filter'] if data['filter'] else ''}.xlsx"
    return FileResponse(out, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}"})
