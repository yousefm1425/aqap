"""تحديد عدد المحاولات لكل عنوان IP على نقاط الدخول والاستعادة (في الذاكرة؛ خادم واحد).

يكمّل إيقاف الحساب بعد المحاولات الخاطئة: ذاك يحمي حساباً بعينه، وهذا يمنع جهازاً واحداً من تجربة حسابات كثيرة
أو إغراق البريد بطلبات الاستعادة.
"""
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request, status

_hits: dict[tuple[str, str], deque] = defaultdict(deque)


def client_ip(request: Request) -> str:
    # خلف وكيل Coolify (Traefik): آخر عنوان في X-Forwarded-For هو ما رآه الوكيل فعلاً؛
    # ما قبله يرسله العميل ويمكن تزويره.
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[-1].strip()
    return request.client.host if request.client else "unknown"


def limit(bucket: str, max_hits: int, window_seconds: int):
    """اعتمادية FastAPI: ترفض بـ 429 إذا تجاوز العنوان max_hits خلال window_seconds."""
    def dep(request: Request) -> None:
        now = time.monotonic()
        q = _hits[(bucket, client_ip(request))]
        while q and now - q[0] > window_seconds:
            q.popleft()
        if len(q) >= max_hits:
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS,
                                "محاولات كثيرة من هذا الجهاز. انتظر بضع دقائق ثم حاول مرة أخرى.")
        q.append(now)
        if len(_hits) > 50_000:        # حماية الذاكرة من عناوين كثيرة
            _hits.clear()
    return dep


def reset() -> None:
    """للاختبارات."""
    _hits.clear()
