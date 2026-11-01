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
from .routers import auth, actions, admin, applicability, assessments, calendar, evidence_links, cycles, evidence, exports, forms, minutes, quality_works, reports, college, patterns, attendance, enrollment
from .security import CurrentUser, current_user, get_conn, issue_dev_token


@asynccontextmanager
async def lifespan(_: FastAPI):
    if settings.env == "prod" and (len(settings.jwt_secret) < 32 or settings.jwt_secret.startswith("change-me")):
        raise RuntimeError("AQAP_JWT_SECRET ضعيف أو افتراضي — عيّن قيمة عشوائية طويلة (32 خانة فأكثر) قبل التشغيل")
    await db.open_pool(settings.database_url)
    storage.init_storage()
    async with db.transaction() as conn:                 # قوالب النماذج من الكود (إصدار جديد عند التغيير فقط)
        await forms.sync_templates(conn)
    yield
    await db.close_pool()


_PROD = settings.env == "prod"
# في الإنتاج لا تُنشر صفحات توثيق الواجهة البرمجية (تكشف كل نقاط النهاية وتحمّل سكربتات من خارج المنصة)
app = FastAPI(title="AQAP API", version="0.1.0",
              description="واجهة برمجية لمنصة إدارة الجودة والاعتماد الأكاديمي", lifespan=lifespan,
              docs_url=None if _PROD else "/docs", redoc_url=None if _PROD else "/redoc",
              openapi_url=None if _PROD else "/openapi.json")

# ترويسات أمان المتصفح لكل الردود
_CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; "
        "font-src 'self' data:; connect-src 'self'; frame-src 'self' blob:; object-src 'self' blob:; "
        "base-uri 'self'; form-action 'self'; frame-ancestors 'none'")
_SECURITY_HEADERS = {
    "X-Frame-Options": "DENY",                       # لا تُضمَّن المنصة داخل مواقع أخرى
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
    "Cross-Origin-Opener-Policy": "same-origin",
}


@app.middleware("http")
async def security_headers(request, call_next):
    resp = await call_next(request)
    for k, v in _SECURITY_HEADERS.items():
        resp.headers.setdefault(k, v)
    if request.url.path not in ("/docs", "/redoc"):   # صفحتا التوثيق (خارج الإنتاج فقط) تحمّلان سكربتات خارجية
        resp.headers.setdefault("Content-Security-Policy", _CSP)
    if _PROD:   # فرض HTTPS في المتصفح لمدة سنة (للنطاق ونطاقاته الفرعية)
        resp.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    if request.url.path.startswith("/api/"):
        resp.headers.setdefault("Cache-Control", "no-store")   # بيانات المستخدمين لا تُحفظ في ذاكرة المتصفح أو الوسطاء
    return resp

register_error_handlers(app)
for r in (auth.router, cycles.router, assessments.router, evidence.router, actions.router, reports.router, exports.router, minutes.router, forms.router,
          applicability.router, calendar.router, evidence_links.router, admin.router, quality_works.router, college.router, patterns.router, attendance.router, enrollment.router):
    app.include_router(r, prefix="/api/v1")


@app.get("/api/v1/files/{token}", include_in_schema=False)
async def download_file(token: str):
    """تنزيل ملف من التخزين المحلي برابط موقّع قصير الأجل يُصدره الخادم بعد التحقق من الصلاحية."""
    import jwt
    from fastapi.responses import FileResponse
    from .storage import FILE_AUDIENCE, LocalStorage, storage as _st

    st = _st()
    if not isinstance(st, LocalStorage):
        raise HTTPException(404)
    try:
        claims = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"], audience=FILE_AUDIENCE,
                            options={"require": ["exp", "k"]})
        path = st.path_for(claims["k"])
    except (jwt.PyJWTError, ValueError):
        raise HTTPException(403, "رابط التنزيل غير صالح أو انتهت صلاحيته؛ أعد المحاولة من المنصة")
    if not path.is_file():
        raise HTTPException(404, "الملف غير موجود")
    # مرفق دائماً (لا يُعرض داخل المنصة) حتى لا يُنفَّذ محتوى ملف مرفوع في سياق المنصة
    return FileResponse(path, filename=claims.get("n") or path.name, content_disposition_type="attachment",
                        media_type="application/octet-stream")


@app.get("/health", tags=["النظام"])
async def health():
    return {"status": "ok"}


@app.get("/api/v1/me", tags=["النظام"])
async def me(user: CurrentUser = Depends(current_user), conn: AsyncConnection = Depends(get_conn, scope="function")):
    cur = await conn.execute("SELECT name_ar FROM institution WHERE id = %s", (user.institution_id,))
    inst = await cur.fetchone()
    return {**user.__dict__, "grants": [g.__dict__ for g in user.grants],
            "institution_name": inst["name_ar"] if inst else None, "env": settings.env}


@app.get("/api/v1/departments", tags=["النظام"])
async def departments(user: CurrentUser = Depends(current_user), conn: AsyncConnection = Depends(get_conn, scope="function")):
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
    @app.middleware("http")
    async def no_stale_frontend(request, call_next):
        # يتحقق المتصفح من الخادم في كل مرة (رد 304 خفيف إن لم يتغير) فتظهر التحديثات فور git pull
        resp = await call_next(request)
        if request.url.path.startswith("/app"):
            resp.headers["Cache-Control"] = "no-cache"
        return resp

    app.mount("/app", StaticFiles(directory=_FRONTEND, html=True), name="frontend")

    @app.get("/", include_in_schema=False)
    async def root():
        return RedirectResponse("/app/home.html")
