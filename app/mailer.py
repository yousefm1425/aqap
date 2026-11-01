"""البريد الصادر عبر SMTP (مثل Brevo). في التطوير بلا SMTP تُكتب الرسالة في سجل الخادم بدل إرسالها."""
import asyncio
import logging
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr, make_msgid
from html import escape

from .config import settings

log = logging.getLogger("aqap.mail")


def mail_configured() -> bool:
    return bool(settings.smtp_host and settings.mail_from)


def _send_sync(to: str, subject: str, text: str, html: str) -> None:
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = formataddr((settings.mail_from_name, settings.mail_from))
    msg["To"] = to
    msg["Message-ID"] = make_msgid(domain=settings.mail_from.split("@")[-1])
    msg.set_content(text)
    msg.add_alternative(html, subtype="html")
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20) as s:
        if settings.smtp_starttls:
            s.starttls(context=ssl.create_default_context())
        if settings.smtp_user:
            s.login(settings.smtp_user, settings.smtp_password or "")
        s.send_message(msg)


async def send_mail(to: str, subject: str, text: str, html: str) -> bool:
    """يعيد True إن أُرسلت الرسالة. لا يرفع استثناءً: فشل البريد يُسجَّل ولا يكشف شيئاً للمستخدم."""
    if not mail_configured():
        if settings.env == "prod":      # لا تُكتب روابط الدخول في سجلات الإنتاج
            log.warning("SMTP غير مهيأ — لم تُرسل رسالة «%s» إلى %s", subject, to)
        else:
            log.warning("SMTP غير مهيأ — رسالة لم تُرسل إلى %s: %s\n%s", to, subject, text)
        return False
    try:
        await asyncio.to_thread(_send_sync, to, subject, text, html)
        return True
    except Exception:  # noqa: BLE001 — أي فشل في البريد يُسجَّل فقط
        log.exception("تعذّر إرسال البريد إلى %s", to)
        return False


def link_email(name: str, intro: str, button: str, url: str, note: str) -> tuple[str, str]:
    """نص ورسالة HTML (من اليمين لليسار) فيها زر رابط واحد."""
    text = f"مرحباً {name}،\n\n{intro}\n\n{url}\n\n{note}\n\n{settings.mail_from_name}"
    html = f"""<!doctype html><html lang="ar" dir="rtl"><body style="margin:0;background:#f4f6f5;font-family:Tahoma,Arial,sans-serif">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr><td align="center" style="padding:24px 12px">
<table role="presentation" width="100%" style="max-width:520px;background:#fff;border-radius:12px;border:1px solid #e3e8e6" cellpadding="0" cellspacing="0">
<tr><td style="background:#0E5A47;color:#fff;padding:16px 24px;border-radius:12px 12px 0 0;font-size:16px;font-weight:bold">{escape(settings.mail_from_name)}</td></tr>
<tr><td style="padding:24px;color:#1f2a27;font-size:15px;line-height:1.8;text-align:right">
<p style="margin:0 0 12px">مرحباً {escape(name)}،</p>
<p style="margin:0 0 20px">{escape(intro)}</p>
<p style="margin:0 0 20px;text-align:center"><a href="{escape(url, quote=True)}" style="display:inline-block;background:#0E5A47;color:#fff;text-decoration:none;padding:12px 28px;border-radius:8px;font-weight:bold">{escape(button)}</a></p>
<p style="margin:0 0 8px;color:#5b6b66;font-size:13px">{escape(note)}</p>
<p style="margin:0;color:#8a9893;font-size:12px;direction:ltr;text-align:left;word-break:break-all">{escape(url)}</p>
</td></tr></table></td></tr></table></body></html>"""
    return text, html
