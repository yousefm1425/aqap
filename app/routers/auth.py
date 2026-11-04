"""الدخول بالبريد وكلمة المرور، واستعادة كلمة المرور وتعيينها برابط يصل إلى البريد.

- كلمات المرور في جدول user_credential (خارج سجل التدقيق) بتجزئة scrypt.
- بعد عدد من المحاولات الخاطئة يُوقف الدخول مؤقتاً للحساب.
- روابط الاستعادة/الدعوة لمرة واحدة ولمدة محدودة، ولا يُحفظ في القاعدة إلا بصمتها.
- طلب الاستعادة يرد بالرسالة نفسها دائماً، فلا يكشف هل البريد مسجّل أم لا.
"""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from psycopg import AsyncConnection
from pydantic import BaseModel, Field

from .. import db
from ..config import settings
from ..mailer import link_email, mail_configured, send_mail
from ..passwords import hash_password, new_link_token, password_problem, token_digest, verify_password
from ..ratelimit import limit
from ..security import CurrentUser, current_user, issue_token, password_version

router = APIRouter(prefix="/auth", tags=["الدخول"])

BAD_LOGIN = "البريد الإلكتروني أو كلمة المرور غير صحيحة"
FORGOT_REPLY = "إن كان البريد مسجلاً في المنصة فسيصلك خلال دقائق رابط لتعيين كلمة مرور جديدة."
BAD_LINK = "الرابط غير صالح أو انتهت صلاحيته. اطلب رابطاً جديداً من «نسيت كلمة المرور»."


class LoginIn(BaseModel):
    email: str = Field(min_length=3, max_length=200)
    password: str = Field(min_length=1, max_length=200)


class ForgotIn(BaseModel):
    email: str = Field(min_length=3, max_length=200)


class ResetIn(BaseModel):
    token: str = Field(min_length=20, max_length=200)
    password: str = Field(max_length=200)


class ChangeIn(BaseModel):
    current_password: str = Field(max_length=200)
    new_password: str = Field(max_length=200)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def link_url(raw: str) -> str:
    return f"{settings.public_url.rstrip('/')}/app/#setpw={raw}"


async def create_link_token(conn: AsyncConnection, user_id: int, purpose: str) -> str:
    raw, digest = new_link_token()
    ttl = timedelta(hours=settings.invite_token_hours) if purpose == "invite" else timedelta(minutes=settings.reset_token_minutes)
    await conn.execute("INSERT INTO auth_token (user_id, purpose, token_hash, expires_at) VALUES (%s, %s, %s, %s)",
                       (user_id, purpose, digest, _now() + ttl))
    return raw


async def send_link(user: dict, raw: str, purpose: str) -> bool:
    url = link_url(raw)
    if purpose == "invite":
        subject = "تفعيل حسابك في منصة الجودة والاعتماد"
        intro = "أُنشئ لك حساب في منصة الجودة والاعتماد. اضغط الزر لتعيين كلمة المرور ثم ادخل ببريدك."
        note = f"الرابط صالح لمدة {settings.invite_token_hours} ساعة ولمرة واحدة."
        button = "تعيين كلمة المرور"
    else:
        subject = "استعادة كلمة المرور — منصة الجودة والاعتماد"
        intro = "وصلنا طلب لاستعادة كلمة المرور لحسابك. اضغط الزر لتعيين كلمة مرور جديدة."
        note = (f"الرابط صالح لمدة {settings.reset_token_minutes} دقيقة ولمرة واحدة. "
                "إن لم تطلب الاستعادة فتجاهل هذه الرسالة، وكلمة مرورك الحالية تبقى كما هي.")
        button = "تعيين كلمة مرور جديدة"
    text, html = link_email(user["full_name_ar"], intro, button, url, note)
    return await send_mail(user["email"], subject, text, html)


@router.get("/config")
async def auth_config():
    """ما تحتاجه شاشة الدخول: هل الدخول التجريبي متاح (خارج الإنتاج فقط)، وهل البريد مهيأ."""
    return {"dev_login": settings.env != "prod", "mail": mail_configured()}


@router.post("/login", dependencies=[Depends(limit("login", 20, 300))])
async def login(body: LoginIn):
    email = body.email.strip().lower()
    async with db.transaction() as conn:
        cur = await conn.execute(
            """SELECT u.id, u.email, c.password_hash, c.failed_count, c.locked_until, c.changed_at, c.must_change
                 FROM app_user u LEFT JOIN user_credential c ON c.user_id = u.id
                WHERE u.is_active AND lower(u.email) = %s""", (email,))
        row = await cur.fetchone()
        locked = row is not None and row["locked_until"] is not None and row["locked_until"] > _now()
        ok = verify_password(body.password, row["password_hash"] if row and not locked else None)
        if row is not None and row["password_hash"] and not locked:
            if ok:
                await conn.execute("""UPDATE user_credential SET failed_count = 0, locked_until = NULL, last_login_at = now()
                                       WHERE user_id = %s""", (row["id"],))
            else:
                fails = row["failed_count"] + 1
                lock = fails >= settings.login_max_failures
                await conn.execute(
                    "UPDATE user_credential SET failed_count = %s, locked_until = %s WHERE user_id = %s",
                    (0 if lock else fails, _now() + timedelta(minutes=settings.login_lock_minutes) if lock else None, row["id"]))
                locked = lock
    # تُرفع الأخطاء بعد انتهاء المعاملة حتى يُحفظ عدّاد المحاولات
    if locked:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS,
                            f"أُوقف الدخول مؤقتاً بسبب محاولات خاطئة متكررة. حاول بعد {settings.login_lock_minutes} دقيقة، "
                            "أو عيّن كلمة مرور جديدة من «نسيت كلمة المرور».")
    if not ok:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, BAD_LOGIN)
    return {"access_token": issue_token(row["email"], pv=password_version(row["changed_at"])), "token_type": "bearer",
            "must_change": row["must_change"]}


@router.post("/forgot", dependencies=[Depends(limit("forgot", 5, 300))])
async def forgot(body: ForgotIn):
    email = body.email.strip().lower()
    async with db.transaction() as conn:
        cur = await conn.execute("SELECT id, email, full_name_ar FROM app_user WHERE is_active AND lower(email) = %s", (email,))
        user = await cur.fetchone()
        raw = None
        if user is not None:
            # رابط واحد كل دقيقة على الأكثر للحساب، منعاً لإغراق البريد
            cur = await conn.execute("""SELECT 1 FROM auth_token WHERE user_id = %s AND purpose = 'reset'
                                         AND created_at > now() - interval '1 minute'""", (user["id"],))
            if await cur.fetchone() is None:
                raw = await create_link_token(conn, user["id"], "reset")
    if raw is not None:
        await send_link(user, raw, "reset")
    out = {"message": FORGOT_REPLY}
    if raw is not None and settings.env != "prod" and not mail_configured():
        out["dev_link"] = link_url(raw)        # للتطوير والاختبار فقط
    return out


async def _token_row(conn: AsyncConnection, raw: str) -> dict:
    cur = await conn.execute(
        """SELECT t.id, t.user_id, t.purpose, u.email, u.full_name_ar FROM auth_token t JOIN app_user u ON u.id = t.user_id
            WHERE t.token_hash = %s AND t.used_at IS NULL AND t.expires_at > now() AND u.is_active""",
        (token_digest(raw),))
    row = await cur.fetchone()
    if row is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, BAD_LINK)
    return row


@router.get("/link", dependencies=[Depends(limit("link", 30, 300))])
async def check_link(token: str):
    """تتحقق شاشة تعيين كلمة المرور من الرابط قبل عرض النموذج."""
    async with db.transaction() as conn:
        row = await _token_row(conn, token)
    return {"purpose": row["purpose"], "email": row["email"], "full_name_ar": row["full_name_ar"]}


async def set_password(conn: AsyncConnection, user_id: int, password: str, must_change: bool = False) -> datetime:
    """يعيّن كلمة المرور ويفك القفل وينهي الجلسات السابقة. must_change للكلمة المؤقتة التي يعيّنها مدير النظام."""
    problem = password_problem(password)
    if problem:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, problem)
    cur = await conn.execute(
        """INSERT INTO user_credential (user_id, password_hash, changed_at, must_change) VALUES (%s, %s, clock_timestamp(), %s)
           ON CONFLICT (user_id) DO UPDATE SET password_hash = EXCLUDED.password_hash, changed_at = EXCLUDED.changed_at,
                                               failed_count = 0, locked_until = NULL, must_change = EXCLUDED.must_change
           RETURNING changed_at""", (user_id, hash_password(password), must_change))
    return (await cur.fetchone())["changed_at"]


_set_password = set_password


@router.post("/reset", dependencies=[Depends(limit("reset", 15, 300))])
async def reset(body: ResetIn):
    async with db.transaction() as conn:
        row = await _token_row(conn, body.token)
        changed_at = await _set_password(conn, row["user_id"], body.password)
        # الرابط لمرة واحدة؛ وتُبطل معه بقية الروابط المفتوحة للحساب
        await conn.execute("UPDATE auth_token SET used_at = now() WHERE user_id = %s AND used_at IS NULL", (row["user_id"],))
    return {"access_token": issue_token(row["email"], pv=password_version(changed_at)), "token_type": "bearer"}


@router.post("/change-password", dependencies=[Depends(limit("change", 10, 300))])
async def change_password(body: ChangeIn, user: CurrentUser = Depends(current_user)):
    async with db.transaction(user.id) as conn:
        cur = await conn.execute("SELECT password_hash FROM user_credential WHERE user_id = %s", (user.id,))
        cred = await cur.fetchone()
        if not verify_password(body.current_password, cred["password_hash"] if cred else None):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "كلمة المرور الحالية غير صحيحة")
        if body.new_password == body.current_password:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "اختر كلمة مرور مختلفة عن الحالية")
        changed_at = await _set_password(conn, user.id, body.new_password)
    # الجلسات الأخرى تبطل؛ هذه الجلسة تأخذ رمزاً جديداً
    return {"access_token": issue_token(user.email, pv=password_version(changed_at)), "token_type": "bearer"}
