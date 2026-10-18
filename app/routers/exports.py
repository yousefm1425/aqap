import json
import tempfile
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import FileResponse
from psycopg import AsyncConnection
from starlette.concurrency import run_in_threadpool

from ..config import settings
from ..export_basic import build_basic
from ..export_official import ExportError, build_payload, run_filler
from ..security import CurrentUser, current_user, forbid, get_conn, load_cycle

router = APIRouter(tags=["التصدير"])


@router.get("/cycles/{cycle_id}/export/official")
async def export_official(cycle_id: int, background: BackgroundTasks, user: CurrentUser = Depends(current_user),
                          conn: AsyncConnection = Depends(get_conn)):
    """ملف «نموذج العمل الشامل» الرسمي معبأً بالأقسام والتقديرات وخطط التحسين (.xlsx)."""
    cycle = await load_cycle(conn, user, cycle_id)
    if not user.has("quality_dean", "quality_auditor", "system_admin", cycle_id=cycle_id):
        raise forbid("التصدير من صلاحية وكالة الجودة")
    workdir = Path(tempfile.mkdtemp(prefix="aqap-export-"))
    out = workdir / "export.xlsx"
    official = bool(settings.official_template) and Path(settings.official_template).is_file()
    try:
        if official:
            payload = await build_payload(conn, cycle_id)
            report = await run_in_threadpool(run_filler, payload, settings.official_template, str(out))
        else:   # لا يوجد ملف القالب الرسمي على الخادم: ملف Excel منسّق بديل بالبيانات نفسها
            report = await build_basic(conn, cycle_id, str(out))
    except ExportError as exc:
        raise HTTPException(422, str(exc))
    await conn.execute(
        "INSERT INTO audit_log (table_name, row_key, action, new_data, actor_id) VALUES ('assessment_cycle', %s, 'EXPORT', %s, %s)",
        (str(cycle_id), json.dumps(report, ensure_ascii=False), user.id))
    background.add_task(lambda: (out.unlink(missing_ok=True), workdir.rmdir()))
    name = f"{'نموذج_العمل_الشامل' if official else 'تقرير_التقييم'}_{cycle['academic_year']}.xlsx"
    return FileResponse(out, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}",
                                 "X-AQAP-Export-Report": quote(json.dumps(report, ensure_ascii=False))})
