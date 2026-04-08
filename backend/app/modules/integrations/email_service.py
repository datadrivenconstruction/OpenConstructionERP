"""Email notification service using SMTP.

Sends HTML emails for important events: task assignments, invoice approvals,
safety alerts, meeting invitations.
"""

import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from functools import lru_cache

from app.config import get_settings

logger = logging.getLogger(__name__)


def _smtp_configured() -> bool:
    """Return True when SMTP host is set (non-empty)."""
    settings = get_settings()
    return bool(settings.smtp_host)


async def send_email(to: str, subject: str, html_body: str) -> bool:
    """Send an HTML email via SMTP. Returns True on success.

    Runs the blocking SMTP handshake in a thread so the event loop is not
    blocked.  If SMTP is not configured the call is silently skipped.
    """
    if not _smtp_configured():
        logger.debug("SMTP not configured — skipping email to %s", to)
        return False

    import asyncio

    return await asyncio.to_thread(_send_sync, to, subject, html_body)


def _send_sync(to: str, subject: str, html_body: str) -> bool:
    """Synchronous SMTP send (called inside a thread)."""
    settings = get_settings()
    msg = MIMEMultipart("alternative")
    msg["From"] = settings.smtp_from
    msg["To"] = to
    msg["Subject"] = subject
    msg.attach(MIMEText(html_body, "html"))

    try:
        if settings.smtp_tls:
            server = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15)
            server.ehlo()
            server.starttls()
            server.ehlo()
        else:
            server = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15)

        if settings.smtp_user and settings.smtp_password:
            server.login(settings.smtp_user, settings.smtp_password)

        server.sendmail(settings.smtp_from, [to], msg.as_string())
        server.quit()
        logger.info("Email sent to %s: %s", to, subject)
        return True
    except Exception:
        logger.exception("Failed to send email to %s", to)
        return False


# ---------------------------------------------------------------------------
# HTML email templates
# ---------------------------------------------------------------------------

_LOGO_URL = "https://openconstructionerp.com/logo-128.png"
_APP_NAME = "OpenConstructionERP"


@lru_cache(maxsize=1)
def _base_style() -> str:
    """Inline CSS shared by all templates."""
    return (
        "font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; "
        "line-height: 1.5; color: #1d1d1f; max-width: 560px; margin: 0 auto; padding: 24px;"
    )


def _wrap(title: str, body: str, action_url: str | None = None, action_label: str = "View") -> str:
    """Wrap *body* in the standard email template shell."""
    btn = ""
    if action_url:
        btn = (
            f'<p style="margin-top:20px;">'
            f'<a href="{action_url}" style="display:inline-block; padding:10px 24px; '
            f"background:#0071e3; color:#fff; border-radius:8px; text-decoration:none; "
            f'font-weight:600;">{action_label}</a></p>'
        )
    return (
        f"<!DOCTYPE html><html><head><meta charset='utf-8'></head>"
        f'<body style="{_base_style()}">'
        f'<img src="{_LOGO_URL}" alt="{_APP_NAME}" width="40" height="40" '
        f'style="margin-bottom:12px;"/>'
        f"<h2 style='margin:0 0 12px;'>{title}</h2>"
        f"{body}"
        f"{btn}"
        f"<hr style='border:none; border-top:1px solid #e5e5ea; margin:28px 0 12px;'/>"
        f"<p style='font-size:12px; color:#86868b;'>"
        f"Sent by {_APP_NAME}. You received this because of your notification preferences.</p>"
        f"</body></html>"
    )


def template_task_assigned(
    task_title: str,
    assignee_name: str,
    project_name: str,
    action_url: str | None = None,
) -> tuple[str, str]:
    """Return (subject, html_body) for a task-assigned notification."""
    subject = f"Task assigned: {task_title}"
    body = (
        f"<p>Hi {assignee_name},</p>"
        f"<p>You've been assigned a task in <strong>{project_name}</strong>:</p>"
        f"<blockquote style='border-left:3px solid #0071e3; padding-left:12px; margin:12px 0;'>"
        f"{task_title}</blockquote>"
    )
    return subject, _wrap("Task Assigned", body, action_url, "Open Task")


def template_invoice_approved(
    invoice_number: str,
    amount: str,
    project_name: str,
    action_url: str | None = None,
) -> tuple[str, str]:
    """Return (subject, html_body) for an invoice-approved notification."""
    subject = f"Invoice {invoice_number} approved"
    body = (
        f"<p>Invoice <strong>{invoice_number}</strong> for "
        f"<strong>{amount}</strong> in project <em>{project_name}</em> has been approved.</p>"
    )
    return subject, _wrap("Invoice Approved", body, action_url, "View Invoice")


def template_safety_alert(
    description: str,
    reporter_name: str,
    project_name: str,
    action_url: str | None = None,
) -> tuple[str, str]:
    """Return (subject, html_body) for a high-risk safety observation."""
    subject = f"Safety alert: {description[:60]}"
    body = (
        f"<p>A <strong style='color:#ff3b30;'>high-risk</strong> safety observation has "
        f"been reported in <em>{project_name}</em> by {reporter_name}:</p>"
        f"<blockquote style='border-left:3px solid #ff3b30; padding-left:12px; margin:12px 0;'>"
        f"{description}</blockquote>"
    )
    return subject, _wrap("Safety Alert", body, action_url, "View Observation")


def template_meeting_invitation(
    meeting_title: str,
    meeting_date: str,
    location: str | None,
    project_name: str,
    action_url: str | None = None,
) -> tuple[str, str]:
    """Return (subject, html_body) for a meeting invitation."""
    subject = f"Meeting: {meeting_title} on {meeting_date}"
    loc = f"<br/>Location: {location}" if location else ""
    body = (
        f"<p>A meeting has been scheduled in <em>{project_name}</em>:</p>"
        f"<p><strong>{meeting_title}</strong><br/>"
        f"Date: {meeting_date}{loc}</p>"
    )
    return subject, _wrap("Meeting Scheduled", body, action_url, "View Meeting")
