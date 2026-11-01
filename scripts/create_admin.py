"""إنشاء حساب المدير الأول (مدير النظام + وكيل الجودة) وإرسال رابط تعيين كلمة المرور إلى بريده.

يُشغَّل مرة واحدة بعد أول نشر، من طرفية حاوية المنصة:
    python scripts/create_admin.py --email you@example.com --name "اسمك"

- ينشئ سجل الكلية إن كانت القاعدة فارغة.
- إن كان البريد مسجلاً يمنحه الدورين فقط (لا يكرر الحساب).
- يطبع رابط تعيين كلمة المرور (صالح 72 ساعة ولمرة واحدة) ويحاول إرساله بالبريد إن كان SMTP مهيأً.
  لا تُكتب كلمة مرور في الطرفية إطلاقاً.
"""
import argparse
import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import psycopg

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import settings  # noqa: E402
from app.passwords import new_link_token  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--email", required=True)
    ap.add_argument("--name", required=True, help="الاسم بالعربية كما يظهر في المنصة")
    ap.add_argument("--institution", default="الكلية التقنية التطبيقية بينبع")
    ap.add_argument("--institution-code", default="YNB")
    ap.add_argument("--dsn", default=os.environ.get("AQAP_DATABASE_URL"))
    a = ap.parse_args()
    if not a.dsn:
        sys.exit("AQAP_DATABASE_URL غير محدد")
    email = a.email.strip().lower()

    with psycopg.connect(a.dsn) as conn:
        conn.execute("SET search_path = aqap, public")
        row = conn.execute("SELECT id FROM institution ORDER BY id LIMIT 1").fetchone()
        inst = row[0] if row else conn.execute(
            "INSERT INTO institution(code, name_ar) VALUES (%s, %s) RETURNING id", (a.institution_code, a.institution)).fetchone()[0]
        row = conn.execute("SELECT id, full_name_ar FROM app_user WHERE lower(email) = %s", (email,)).fetchone()
        if row:
            uid, name = row
            conn.execute("UPDATE app_user SET is_active = true WHERE id = %s", (uid,))
            print(f"• الحساب موجود: {name} <{email}>")
        else:
            uid = conn.execute("INSERT INTO app_user(institution_id, email, full_name_ar) VALUES (%s, %s, %s) RETURNING id",
                               (inst, email, a.name.strip())).fetchone()[0]
            name = a.name.strip()
            print(f"✓ أُنشئ الحساب: {name} <{email}>")
        for role in ("system_admin", "quality_dean"):
            if not conn.execute("SELECT 1 FROM user_role WHERE user_id = %s AND role = %s AND department_id IS NULL",
                                (uid, role)).fetchone():
                conn.execute("INSERT INTO user_role(user_id, role) VALUES (%s, %s)", (uid, role))
                print(f"✓ مُنح دور: {role}")
        raw, digest = new_link_token()
        conn.execute("INSERT INTO auth_token (user_id, purpose, token_hash, expires_at) VALUES (%s, 'invite', %s, %s)",
                     (uid, digest, datetime.now(timezone.utc) + timedelta(hours=settings.invite_token_hours)))
        conn.commit()

    from app.routers.auth import link_url, send_link
    sent = asyncio.run(send_link({"email": email, "full_name_ar": name}, raw, "invite"))
    print("✓ أُرسل رابط تعيين كلمة المرور إلى البريد" if sent else "• البريد غير مهيأ أو تعذّر الإرسال — استخدم الرابط أدناه")
    print(f"\nرابط تعيين كلمة المرور (صالح {settings.invite_token_hours} ساعة ولمرة واحدة):\n{link_url(raw)}\n")


if __name__ == "__main__":
    main()
