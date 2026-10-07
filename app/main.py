from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from psycopg import AsyncConnection
from pydantic import BaseModel

from . import db, storage
from .config import settings
from .errors import register_error_handlers
from .routers import actions, assessments, cycles, evidence, exports, minutes, reports
from .security import CurrentUser, current_user, get_conn, issue_dev_token


@asynccontextmanager
async def lifespan(_: FastAPI):
    await db.open_pool(settings.database_url)
    storage.init_storage()
    yield
    await db.close_pool()


app = FastAPI(title="AQAP API", version="0.1.0",
              description="واجهة برمجية لمنصة إدارة الجودة والاعتماد الأكاديمي", lifespan=lifespan)
register_error_handlers(app)
for r in (cycles.router, assessments.router, evidence.router, actions.router, reports.router, exports.router, minutes.router):
    app.include_router(r, prefix="/api/v1")


@app.get("/health", tags=["النظام"])
async def health():
    return {"status": "ok"}


@app.get("/api/v1/me", tags=["النظام"])
async def me(user: CurrentUser = Depends(current_user), conn: AsyncConnection = Depends(get_conn)):
    cur = await conn.execute("SELECT name_ar FROM institution WHERE id = %s", (user.institution_id,))
    inst = await cur.fetchone()
    return {**user.__dict__, "grants": [g.__dict__ for g in user.grants],
            "institution_name": inst["name_ar"] if inst else None, "env": settings.env}


@app.get("/api/v1/departments", tags=["النظام"])
async def departments(user: CurrentUser = Depends(current_user), conn: AsyncConnection = Depends(get_conn)):
    cur = await conn.execute(
        "SELECT id, code, name_ar, name_en FROM department WHERE institution_id = %s AND is_active ORDER BY code",
        (user.institution_id,))
    return await cur.fetchall()


class DevTokenIn(BaseModel):
    email: str


@app.post("/api/v1/auth/dev-token", tags=["النظام"], include_in_schema=settings.env != "prod")
async def dev_token(body: DevTokenIn):
    """للتطوير والاختبار فقط؛ معطّل في الإنتاج حيث تأتي الرموز من مزوّد الدخول الموحّد."""
    if settings.env == "prod":
        raise HTTPException(404)
    return {"access_token": issue_dev_token(body.email), "token_type": "bearer"}


# الواجهة الأمامية (ملفات ثابتة بلا خطوة بناء)
_FRONTEND = Path(__file__).resolve().parents[1] / "frontend"
if _FRONTEND.is_dir():
    app.mount("/app", StaticFiles(directory=_FRONTEND, html=True), name="frontend")

    @app.get("/", include_in_schema=False)
    async def root():
        return RedirectResponse("/app/")
