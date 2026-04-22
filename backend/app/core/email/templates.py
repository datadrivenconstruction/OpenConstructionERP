"""Shared HTML email templates.

Centralises the visual shell (logo, CSS, footer) and the per-event
templates (task-assigned, invoice-approved, safety-alert, meeting,
password-reset).  Each template returns ``(subject, html_body)`` so the
caller can decide whether to wrap it in an ``EmailMessage`` and push it
through the service, or inspect it directly in unit tests.

Kept template-only — no I/O, no settings, no side effects — so it can
be imported from tests without touching the rest of the stack.
"""

from __future__ import annotations

from functools import lru_cache

_LOGO_URL = "https://openconstructionerp.com/logo-128.png"
_APP_NAME = "OpenConstructionERP"


@lru_cache(maxsize=1)
def _base_style() -> str:
    return (
        "font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; "
        "line-height: 1.5; color: #1d1d1f; max-width: 560px; margin: 0 auto; padding: 24px;"
    )


def wrap(
    title: str,
    body: str,
    action_url: str | None = None,
    action_label: str = "View",
) -> str:
    """Wrap *body* in the standard email shell (logo, title, CTA, footer)."""
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
    subject = f"Task assigned: {task_title}"
    body = (
        f"<p>Hi {assignee_name},</p>"
        f"<p>You've been assigned a task in <strong>{project_name}</strong>:</p>"
        f"<blockquote style='border-left:3px solid #0071e3; padding-left:12px; margin:12px 0;'>"
        f"{task_title}</blockquote>"
    )
    return subject, wrap("Task Assigned", body, action_url, "Open Task")


def template_invoice_approved(
    invoice_number: str,
    amount: str,
    project_name: str,
    action_url: str | None = None,
) -> tuple[str, str]:
    subject = f"Invoice {invoice_number} approved"
    body = (
        f"<p>Invoice <strong>{invoice_number}</strong> for "
        f"<strong>{amount}</strong> in project <em>{project_name}</em> has been approved.</p>"
    )
    return subject, wrap("Invoice Approved", body, action_url, "View Invoice")


def template_safety_alert(
    description: str,
    reporter_name: str,
    project_name: str,
    action_url: str | None = None,
) -> tuple[str, str]:
    subject = f"Safety alert: {description[:60]}"
    body = (
        f"<p>A <strong style='color:#ff3b30;'>high-risk</strong> safety observation has "
        f"been reported in <em>{project_name}</em> by {reporter_name}:</p>"
        f"<blockquote style='border-left:3px solid #ff3b30; padding-left:12px; margin:12px 0;'>"
        f"{description}</blockquote>"
    )
    return subject, wrap("Safety Alert", body, action_url, "View Observation")


def template_meeting_invitation(
    meeting_title: str,
    meeting_date: str,
    location: str | None,
    project_name: str,
    action_url: str | None = None,
) -> tuple[str, str]:
    subject = f"Meeting: {meeting_title} on {meeting_date}"
    loc = f"<br/>Location: {location}" if location else ""
    body = (
        f"<p>A meeting has been scheduled in <em>{project_name}</em>:</p>"
        f"<p><strong>{meeting_title}</strong><br/>"
        f"Date: {meeting_date}{loc}</p>"
    )
    return subject, wrap("Meeting Scheduled", body, action_url, "View Meeting")


def template_password_reset(
    recipient_name: str | None,
    reset_url: str,
    token_lifetime_minutes: int = 60,
) -> tuple[str, str]:
    """Password-reset template.

    ``reset_url`` already carries the token as a query parameter — the
    template does not embed the raw token separately so we never leak it
    to copy-paste or forwarded-email attack paths.
    """
    greeting = f"Hi {recipient_name}," if recipient_name else "Hello,"
    subject = "Reset your OpenConstructionERP password"
    body = (
        f"<p>{greeting}</p>"
        f"<p>We received a request to reset the password on your "
        f"<strong>{_APP_NAME}</strong> account. Click the button below to choose a new one. "
        f"The link is valid for {token_lifetime_minutes} minutes.</p>"
        f"<p style='font-size:13px; color:#6e6e73;'>If you did not request a password reset, "
        f"you can safely ignore this email — your password will not change.</p>"
    )
    return subject, wrap("Reset your password", body, reset_url, "Reset password")
