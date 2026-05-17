# app/services/notifications.py
import os
import asyncio
import smtplib
import ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional, List, Dict
import logging

logger = logging.getLogger(__name__)

BREVO_HOST = os.getenv("BREVO_SMTP_HOST", "smtp-relay.brevo.com")
BREVO_PORT = int(os.getenv("BREVO_SMTP_PORT", "587"))
# Accept either BREVO_SMTP_USER or BREVO_USER (and same for pass)
BREVO_USER = os.getenv("BREVO_SMTP_USER") or os.getenv("BREVO_USER", "")
BREVO_PASS = os.getenv("BREVO_SMTP_PASS") or os.getenv("BREVO_PASS", "")
FROM_EMAIL = os.getenv("FROM_EMAIL", "hello@lidle.com")
FROM_NAME = os.getenv("FROM_NAME", "Lidle-By-Lidle")

if BREVO_USER:
    logger.info(f"[EMAIL] Brevo configured: {BREVO_USER[:6]}*** → {FROM_EMAIL}")
else:
    logger.warning("[EMAIL] Brevo not configured — emails will be skipped. Set BREVO_SMTP_USER and BREVO_SMTP_PASS.")


# ── EMAIL TEMPLATES ──

def _base_layout(content: str, accent: str = "#F5C600") -> str:
    return f"""
    <!DOCTYPE html>
    <html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"></head>
    <body style="margin:0;padding:20px;background:#F0EDE8;font-family:sans-serif;">
      <div style="max-width:560px;margin:0 auto;background:#FAFAF8;border:2px solid #0D0D0D;">
        <div style="background:{accent};padding:28px 36px;border-bottom:2px solid #0D0D0D;">
          <h1 style="margin:0;font-size:30px;letter-spacing:4px;font-weight:900;color:#0D0D0D;">
            STRAPEE<span style="color:#E87CA0;">ZZY</span>
          </h1>
        </div>
        <div style="padding:36px;">{content}</div>
        <div style="padding:20px 36px;border-top:1px solid #E0D8CF;font-size:11px;color:#999;">
          © 2026 Lidle-By-Lidle · <a href="https://lidle.com" style="color:#999;">lidle.com</a>
        </div>
      </div>
    </body></html>"""


def template_waitlist_confirm(name: str, position: int) -> tuple[str, str]:
    subject = "You're on the Strapeezzy waitlist! 🎉"
    body = _base_layout(f"""
        <h2 style="margin:0 0 16px;font-size:24px;">You're in, {name or 'watch lover'}! 🙌</h2>
        <p style="color:#555;line-height:1.7;margin:0 0 12px;">
            You're <strong>#{position}</strong> on the Strapeezzy Pioneer waitlist.
        </p>
        <p style="color:#555;line-height:1.7;margin:0 0 28px;">
            We'll email you the moment our Pioneer case-straps for the AP × Swatch Royalpop are ready to ship.
            No spam — just one email when it's go time.
        </p>
        <div style="background:#0D0D0D;color:#F5C600;padding:16px 28px;display:inline-block;font-size:18px;font-weight:700;letter-spacing:2px;">
            8 COLORWAYS · COMING 2026
        </div>
    """)
    return subject, body


def template_order_confirm(order: dict) -> tuple[str, str]:
    subject = f"Order confirmed — {order['order_number']} 🎉"
    body = _base_layout(f"""
        <h2 style="margin:0 0 8px;font-size:22px;">Order Confirmed!</h2>
        <p style="color:#555;margin:0 0 24px;">Hi {order['customer_name']}, your order is confirmed. Here's a summary:</p>
        <table style="width:100%;border-collapse:collapse;">
            <tr style="border-bottom:1px solid #eee;"><td style="padding:10px 0;color:#888;font-size:13px;">Order</td><td style="padding:10px 0;font-weight:600;">{order['order_number']}</td></tr>
            <tr style="border-bottom:1px solid #eee;"><td style="padding:10px 0;color:#888;font-size:13px;">Product</td><td style="padding:10px 0;">{order['product_name']}</td></tr>
            <tr style="border-bottom:1px solid #eee;"><td style="padding:10px 0;color:#888;font-size:13px;">Variant</td><td style="padding:10px 0;">{order.get('product_variant') or '—'}</td></tr>
            <tr style="border-bottom:1px solid #eee;"><td style="padding:10px 0;color:#888;font-size:13px;">Qty</td><td style="padding:10px 0;">{order['quantity']}</td></tr>
            <tr><td style="padding:10px 0;color:#888;font-size:13px;">Total</td><td style="padding:10px 0;font-size:20px;font-weight:700;">${order['total_amount']/100:.2f}</td></tr>
        </table>
        <p style="color:#555;line-height:1.7;margin:24px 0 0;">We'll send a shipping confirmation with tracking once dispatched. Questions? Reply to this email.</p>
    """)
    return subject, body


def template_shipping_confirm(order: dict) -> tuple[str, str]:
    subject = f"Your Strapeezzy strap is on its way! 📦"
    tracking_block = ""
    if order.get("tracking_number"):
        tracking_block = f"""
        <div style="background:#0D0D0D;color:#F5C600;padding:20px 24px;margin:24px 0;">
            <div style="font-size:11px;letter-spacing:2px;text-transform:uppercase;color:#888;margin-bottom:6px;">Tracking Number</div>
            <div style="font-size:22px;font-weight:700;">{order['tracking_number']}</div>
            {f'<div style="font-size:13px;color:#aaa;margin-top:4px;">{order["tracking_carrier"]}</div>' if order.get("tracking_carrier") else ""}
            {f'<a href="{order["tracking_url"]}" style="display:inline-block;margin-top:12px;background:#F5C600;color:#0D0D0D;padding:10px 20px;font-weight:700;text-decoration:none;">Track Your Order →</a>' if order.get("tracking_url") else ""}
        </div>"""
    body = _base_layout(f"""
        <h2 style="margin:0 0 8px;font-size:22px;">It's shipped! 🚀</h2>
        <p style="color:#555;margin:0 0 4px;">Hi {order['customer_name']}, your {order['product_name']} is on its way.</p>
        {tracking_block}
        <p style="color:#999;font-size:13px;margin-top:16px;">Order: {order['order_number']}</p>
    """, accent="#4DCFC4")
    return subject, body


def template_waitlist_launch(name: str, shop_url: str) -> tuple[str, str]:
    subject = "🚨 Strapeezzy Pioneer Straps are LIVE — shop now"
    body = _base_layout(f"""
        <h2 style="font-size:28px;margin:0 0 16px;">We're LIVE, {name or 'watch lover'}! 🎉</h2>
        <p style="color:#555;line-height:1.7;margin:0 0 24px;">
            The Pioneer case-straps for the AP × Swatch Royalpop are now available.
            All 8 colorways. You're first in line as a waitlist member.
        </p>
        <a href="{shop_url}" style="display:inline-block;background:#0D0D0D;color:#F5C600;padding:18px 36px;font-size:20px;font-weight:700;letter-spacing:2px;text-decoration:none;">
            SHOP NOW →
        </a>
    """, accent="#E87CA0")
    return subject, body


def template_custom(subject: str, body_content: str) -> tuple[str, str]:
    body = _base_layout(f"<div>{body_content}</div>")
    return subject, body


# ── SEND EMAIL (sync via smtplib — run in thread pool) ──

def _send_email_sync(to_email: str, to_name: Optional[str], subject: str, html_body: str) -> bool:
    if not BREVO_USER or not BREVO_PASS:
        logger.warning(f"[EMAIL] Brevo not configured — skipping email to {to_email}")
        return False
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = f'"{FROM_NAME}" <{FROM_EMAIL}>'
        msg["To"] = f'"{to_name}" <{to_email}>' if to_name else to_email
        msg.attach(MIMEText(html_body, "html"))

        context = ssl.create_default_context()
        with smtplib.SMTP(BREVO_HOST, BREVO_PORT) as server:
            server.ehlo()
            server.starttls(context=context)
            server.login(BREVO_USER, BREVO_PASS)
            server.sendmail(FROM_EMAIL, to_email, msg.as_string())
        logger.info(f"[EMAIL] Sent '{subject}' to {to_email}")
        return True
    except Exception as e:
        logger.error(f"[EMAIL] Failed to {to_email}: {e}")
        return False


async def send_email(to_email: str, to_name: Optional[str], subject: str, html_body: str) -> bool:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _send_email_sync, to_email, to_name, subject, html_body)


async def send_bulk_email(
    recipients: List[Dict],
    template_fn,
    extra_kwargs: dict = {}
) -> Dict:
    results = {"sent": 0, "failed": 0, "errors": []}
    for r in recipients:
        try:
            subject, body = template_fn(r.get("name", ""), **extra_kwargs)
            ok = await send_email(r["email"], r.get("name"), subject, body)
            if ok:
                results["sent"] += 1
            else:
                results["failed"] += 1
        except Exception as e:
            results["failed"] += 1
            results["errors"].append({"email": r["email"], "error": str(e)})
        await asyncio.sleep(0.12)  # ~8/sec — Brevo free tier safe
    return results


# ── SEND SMS (Twilio) ──

async def send_sms(to_phone: str, message: str) -> bool:
    account_sid = os.getenv("TWILIO_ACCOUNT_SID", "")
    auth_token = os.getenv("TWILIO_AUTH_TOKEN", "")
    from_number = os.getenv("TWILIO_PHONE_NUMBER", "")

    if not account_sid or not auth_token or account_sid.startswith("AC_"):
        logger.warning(f"[SMS] Twilio not configured — skipping SMS to {to_phone}")
        return False
    try:
        from twilio.rest import Client
        loop = asyncio.get_running_loop()

        def _send():
            client = Client(account_sid, auth_token)
            return client.messages.create(body=message, from_=from_number, to=to_phone)

        msg = await loop.run_in_executor(None, _send)
        logger.info(f"[SMS] Sent to {to_phone}: {msg.sid}")
        return True
    except Exception as e:
        logger.error(f"[SMS] Failed to {to_phone}: {e}")
        return False
