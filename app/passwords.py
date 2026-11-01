"""تجزئة كلمات المرور بخوارزمية scrypt من المكتبة القياسية (بلا اعتماديات إضافية)، ورموز الروابط لمرة واحدة."""
import base64
import hashlib
import hmac
import re
import secrets

_N, _R, _P, _LEN = 2 ** 15, 8, 1, 32
_MAXMEM = 64 * 1024 * 1024


def _b64(b: bytes) -> str:
    return base64.b64encode(b).decode()


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P, dklen=_LEN, maxmem=_MAXMEM)
    return f"scrypt${_N}${_R}${_P}${_b64(salt)}${_b64(dk)}"


def verify_password(password: str, stored: str | None) -> bool:
    if not stored:
        # تجزئة وهمية لتوحيد زمن الاستجابة حين لا يوجد حساب أو كلمة مرور
        hashlib.scrypt(password.encode(), salt=b"0" * 16, n=_N, r=_R, p=_P, dklen=_LEN, maxmem=_MAXMEM)
        return False
    try:
        algo, n, r, p, salt, dk = stored.split("$")
        if algo != "scrypt":
            return False
        calc = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt), n=int(n), r=int(r), p=int(p),
                              dklen=len(base64.b64decode(dk)), maxmem=_MAXMEM)
        return hmac.compare_digest(calc, base64.b64decode(dk))
    except (ValueError, TypeError):
        return False


def password_problem(password: str) -> str | None:
    """يعيد سبب رفض كلمة المرور، أو None إن كانت مقبولة."""
    if len(password) < 8:
        return "كلمة المرور يجب ألا تقل عن 8 خانات"
    if len(password) > 128:
        return "كلمة المرور طويلة جداً"
    if not re.search(r"[A-Za-z؀-ۿ]", password) or not re.search(r"\d", password):
        return "كلمة المرور يجب أن تحتوي على حروف وأرقام"
    return None


def new_link_token() -> tuple[str, str]:
    """رمز عشوائي للرابط، وبصمته التي تُحفظ في القاعدة (لا يُحفظ الرمز نفسه)."""
    raw = secrets.token_urlsafe(32)
    return raw, token_digest(raw)


def token_digest(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()
