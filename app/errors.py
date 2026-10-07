from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from psycopg import errors as pg


def _msg(exc: pg.Error) -> str:
    return (exc.diag.message_primary or str(exc)).strip()


def register_error_handlers(app: FastAPI) -> None:
    # قواعد العمل المفروضة في قاعدة البيانات (RAISE EXCEPTION) ← 409 برسالتها العربية
    @app.exception_handler(pg.RaiseException)
    async def business_rule(_: Request, exc: pg.RaiseException):
        return JSONResponse(status_code=409, content={"detail": _msg(exc), "code": "business_rule"})

    @app.exception_handler(pg.UniqueViolation)
    async def unique(_: Request, exc: pg.UniqueViolation):
        return JSONResponse(status_code=409, content={"detail": "السجل موجود مسبقاً", "code": "duplicate"})

    @app.exception_handler(pg.ForeignKeyViolation)
    async def fk(_: Request, exc: pg.ForeignKeyViolation):
        return JSONResponse(status_code=422, content={"detail": "مرجع غير موجود", "code": "invalid_reference"})

    @app.exception_handler(pg.CheckViolation)
    async def check(_: Request, exc: pg.CheckViolation):
        return JSONResponse(status_code=422, content={"detail": "قيمة غير صالحة", "code": "check_violation",
                                                      "constraint": exc.diag.constraint_name})
