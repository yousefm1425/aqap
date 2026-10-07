from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import AsyncIterator

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from psycopg import AsyncConnection

from . import db
from .config import settings

INSTITUTION_WIDE = {"system_admin", "quality_dean", "quality_auditor"}
DEPT_EDITORS = {"dept_coordinator", "faculty"}

_bearer = HTTPBearer(auto_error=False)
_jwks_client = jwt.PyJWKClient(settings.jwks_url) if settings.jwks_url else None


@dataclass(frozen=True)
class Grant:
    role: str
    department_id: int | None
    cycle_id: int | None


@dataclass
class CurrentUser:
    id: int
    email: str
    full_name_ar: str
    institution_id: int | None
    grants: list[Grant] = field(default_factory=list)

    def has(self, *roles: str, department_id: int | None = None, cycle_id: int | None = None) -> bool:
        """نفس منطق aqap.has_role: المنحة بلا قسم تغطي كل الأقسام، والمنحة بلا دورة تغطي كل الدورات."""
        return any(
            g.role in roles
            and (g.department_id is None or g.department_id == department_id)
            and (g.cycle_id is None or g.cycle_id == cycle_id)
            for g in self.grants
        )

    def has_any(self, *roles: str) -> bool:
        return any(g.role in roles for g in self.grants)

    def scope(self, cycle_id: int | None = None) -> tuple[bool, list[int]]:
        """نطاق الاطلاع: (كل الأقسام؟, قائمة الأقسام المحددة)."""
        all_depts = any(
            g.department_id is None and (g.cycle_id is None or g.cycle_id == cycle_id)
            for g in self.grants
        )
        depts = sorted({g.department_id for g in self.grants
                        if g.department_id is not None and (g.cycle_id is None or g.cycle_id == cycle_id)})
        return all_depts, depts

    def can_view_department(self, department_id: int | None, cycle_id: int | None = None) -> bool:
        all_depts, depts = self.scope(cycle_id)
        return all_depts or (department_id is not None and department_id in depts)


def issue_dev_token(subject: str, hours: int = 8) -> str:
    now = datetime.now(timezone.utc)
    payload = {"sub": subject, "aud": settings.jwt_audience, "iat": now, "exp": now + timedelta(hours=hours)}
    if settings.jwt_issuer:
        payload["iss"] = settings.jwt_issuer
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def _decode(token: str) -> dict:
    options = {"require": ["sub", "exp"]}
    if _jwks_client is not None:
        key = _jwks_client.get_signing_key_from_jwt(token).key
        return jwt.decode(token, key, algorithms=["RS256"], audience=settings.jwt_audience,
                          issuer=settings.jwt_issuer, options=options)
    return jwt.decode(token, settings.jwt_secret, algorithms=["HS256"], audience=settings.jwt_audience,
                      issuer=settings.jwt_issuer, options=options)


async def current_user(creds: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> CurrentUser:
    unauthorized = HTTPException(status.HTTP_401_UNAUTHORIZED, "يلزم تسجيل الدخول",
                                 headers={"WWW-Authenticate": "Bearer"})
    if creds is None:
        raise unauthorized
    try:
        claims = _decode(creds.credentials)
    except jwt.PyJWTError:
        raise unauthorized

    async with db.transaction() as conn:
        cur = await conn.execute(
            """SELECT id, email, full_name_ar, institution_id FROM app_user
                WHERE is_active AND (sso_subject = %(s)s OR lower(email) = lower(%(s)s))""",
            {"s": claims["sub"]})
        row = await cur.fetchone()
        if row is None:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "الحساب غير مسجل أو غير مفعّل")
        cur = await conn.execute(
            """SELECT role::text, department_id, cycle_id FROM user_role
                WHERE user_id = %s AND current_date BETWEEN valid_from AND COALESCE(valid_to, 'infinity'::date)""",
            (row["id"],))
        grants = [Grant(r["role"], r["department_id"], r["cycle_id"]) for r in await cur.fetchall()]
    return CurrentUser(**row, grants=grants)


async def get_conn(user: CurrentUser = Depends(current_user)) -> AsyncIterator[AsyncConnection]:
    async with db.transaction(user.id) as conn:
        yield conn


def forbid(msg: str = "لا تملك صلاحية تنفيذ هذا الإجراء") -> HTTPException:
    return HTTPException(status.HTTP_403_FORBIDDEN, msg)


def not_found(msg: str = "غير موجود") -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, msg)


async def load_cycle(conn: AsyncConnection, user: CurrentUser, cycle_id: int) -> dict:
    """يعيد الدورة إن كانت ضمن مؤسسة المستخدم أو ضمن منحة مقيدة بها؛ وإلا 404."""
    cur = await conn.execute("SELECT * FROM assessment_cycle WHERE id = %s", (cycle_id,))
    cycle = await cur.fetchone()
    if cycle is None:
        raise not_found("الدورة غير موجودة")
    cycle_grant = any(g.cycle_id == cycle_id for g in user.grants)
    same_inst = user.institution_id == cycle["institution_id"] and any(g.cycle_id is None for g in user.grants)
    if not (cycle_grant or same_inst):
        raise not_found("الدورة غير موجودة")
    return cycle
