# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Shared HTML email templates.

Centralises the visual shell (logo, CSS, footer) and the per-event
templates (task-assigned, invoice-approved, safety-alert, meeting,
password-reset).  Each template returns ``(subject, html_body)`` so the
caller can decide whether to wrap it in an ``EmailMessage`` and push it
through the service, or inspect it directly in unit tests.

Kept template-only - no I/O, no settings, no side effects - so it can
be imported from tests without touching the rest of the stack.
"""

from __future__ import annotations

import html
from collections.abc import Mapping
from functools import lru_cache

_LOGO_URL = "https://openconstructionerp.com/logo-128.png"

#: The product name every outgoing email carries: the ``From:`` display name,
#: the line beside the logo and the closing line of the footer. It is a brand,
#: so it is never translated or shortened, in any language.
BRAND_NAME = "OpenConstructionERP"
_APP_NAME = BRAND_NAME

# The footer line of mail that a person receives because they subscribed to
# notifications. Other mail (a reset link, an invitation, a document) never
# says so; it closes with the brand line alone.
_PREFERENCES_FOOTER = f"Sent by {_APP_NAME}. You received this because of your notification preferences."


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
    *,
    footer: str | None = None,
    lang: str | None = None,
    rtl: bool = False,
) -> str:
    """Wrap *body* in the standard email shell (brand line, title, CTA, footer).

    Every mail opens with the logo and the brand name beside it, in text so it
    shows when a mail client blocks images, and closes with the brand name.
    ``footer`` is an extra line above that closing line, such as why the mail
    came; ``None`` or an empty string adds none. It is inserted as given, so
    escape it. ``lang`` sets the document language and ``rtl`` the reading
    direction for a right-to-left language (Arabic, Persian, Hebrew, Urdu).
    """
    btn = ""
    if action_url:
        btn = (
            f'<p style="margin-top:20px;">'
            f'<a href="{action_url}" style="display:inline-block; padding:10px 24px; '
            f"background:#0071e3; color:#fff; border-radius:8px; text-decoration:none; "
            f'font-weight:600;">{action_label}</a></p>'
        )
    html_attrs = (f' lang="{lang}"' if lang else "") + (' dir="rtl"' if rtl else "")
    return (
        f"<!DOCTYPE html><html{html_attrs}><head><meta charset='utf-8'></head>"
        f'<body style="{_base_style()}">'
        f"{brand_header()}"
        f"<h2 style='margin:0 0 12px;'>{title}</h2>"
        f"{body}"
        f"{btn}"
        f"{_footer_block(footer)}"
        f"</body></html>"
    )


#: Content-ID of the company logo; :class:`app.core.email.service.EmailService` attaches the image.
COMPANY_LOGO_CID = "company-logo"


def company_logo_png() -> bytes | None:
    """The company profile's document logo as PNG/JPEG bytes for a CID part, or ``None``."""
    from app.core.doc_templates.pdf import decode_png_data_url

    try:
        from app.core.company_profile import read_company_profile

        profile = read_company_profile()
    except Exception:  # noqa: BLE001 - an email never fails on a missing profile
        return None
    for key in ("document_logo_png_data_url", "document_logo_data_url"):
        raw = decode_png_data_url(profile.get(key))
        if raw:
            return raw
    return None


def email_brand() -> tuple[str, bool]:
    """``(name, has_logo)`` for the email shell: the company's own when its profile is filled in.

    An install that never filled the company profile in keeps the platform
    name and logo, so its emails do not change.
    """
    try:
        from app.core.company_profile import read_company_profile

        name = (read_company_profile().get("legal_name") or "").strip()
    except Exception:  # noqa: BLE001
        name = ""
    has_logo = company_logo_png() is not None
    if not name and not has_logo:
        return _APP_NAME, False
    return (html.escape(name) if name else ""), has_logo


def brand_header() -> str:
    """The logo and the brand name that open every email, as an HTML fragment."""
    name, has_logo = email_brand()
    if name == _APP_NAME and not has_logo:
        return (
            f"<p style='margin:0 0 12px;'>"
            f'<img src="{_LOGO_URL}" alt="{_APP_NAME}" width="40" height="40" '
            f'style="vertical-align:middle; margin-right:8px;"/>'
            f"<strong style='vertical-align:middle; font-size:15px;'>{_APP_NAME}</strong></p>"
        )
    logo = (
        f'<img src="cid:{COMPANY_LOGO_CID}" alt="{name}" height="40" style="vertical-align:middle; margin-right:8px;"/>'
        if has_logo
        else ""
    )
    label = f"<strong style='vertical-align:middle; font-size:15px;'>{name}</strong>" if name else ""
    return f"<p style='margin:0 0 12px;'>{logo}{label}</p>"


def _footer_block(footer: str | None) -> str:
    extra = f"<p style='font-size:12px; color:#86868b; margin:0 0 6px;'>{footer}</p>" if footer else ""
    name, _logo = email_brand()
    return (
        f"<hr style='border:none; border-top:1px solid #e5e5ea; margin:28px 0 12px;'/>"
        f"{extra}"
        f"<p style='font-size:12px; color:#86868b; margin:0;'>{name or _APP_NAME}</p>"
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
    return subject, wrap("Task Assigned", body, action_url, "Open Task", footer=_PREFERENCES_FOOTER)


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
    return subject, wrap("Invoice Approved", body, action_url, "View Invoice", footer=_PREFERENCES_FOOTER)


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
    return subject, wrap("Safety Alert", body, action_url, "View Observation", footer=_PREFERENCES_FOOTER)


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
    return subject, wrap("Meeting Scheduled", body, action_url, "View Meeting", footer=_PREFERENCES_FOOTER)


def template_password_reset(
    recipient_name: str | None,
    reset_url: str,
    token_lifetime_minutes: int = 60,
    wording: Mapping[str, str] | None = None,
) -> tuple[str, str]:
    """Password-reset template.

    ``reset_url`` already carries the token as a query parameter - the
    template does not embed the raw token separately so we never leak it
    to copy-paste or forwarded-email attack paths.
    """
    if wording:
        return _password_reset_from_wording(wording, recipient_name, reset_url, token_lifetime_minutes)
    greeting = f"Hi {recipient_name}," if recipient_name else "Hello,"
    subject = "Reset your OpenConstructionERP password"
    body = (
        f"<p>{greeting}</p>"
        f"<p>We received a request to reset the password on your "
        f"<strong>{_APP_NAME}</strong> account. Click the button below to choose a new one. "
        f"The link is valid for {token_lifetime_minutes} minutes.</p>"
        f"<p style='font-size:13px; color:#6e6e73;'>If you did not request a password reset, "
        f"you can safely ignore this email - your password will not change.</p>"
    )
    return subject, wrap("Reset your password", body, reset_url, "Reset password")


def _password_reset_from_wording(
    wording: Mapping[str, str], recipient_name: str | None, reset_url: str, minutes: int
) -> tuple[str, str]:
    """The reset email from a firm's published wording (``users.password_reset``)."""
    from app.core.doc_templates.markup import to_html, to_plain

    try:
        from app.core.company_profile import read_company_profile

        legal_name = read_company_profile().get("legal_name") or ""
    except Exception:  # noqa: BLE001
        legal_name = ""
    values = {
        "recipient.name": recipient_name or "",
        "app.name": _APP_NAME,
        "entity.legal_name": legal_name,
        "link.minutes": str(minutes),
    }
    subject = to_plain(wording.get("subject") or "", values) or "Reset your password"
    title = html.escape(to_plain(wording.get("preheader") or "", values) or subject)
    body = to_html(wording.get("body") or "", values)
    label = html.escape(to_plain(wording.get("cta_label") or "", values) or "Reset password")
    footer = to_html(wording.get("footer") or "", values) or None
    return subject, wrap(title, body, reset_url, label, footer=footer)


def template_email_verification(
    recipient_name: str | None,
    verify_url: str,
    token_lifetime_hours: int,
) -> tuple[str, str]:
    """Confirmation of a self-registered account; the link activates it."""
    from html import escape

    greeting = f"Hi {escape(recipient_name)}," if recipient_name else "Hello,"
    subject = "Confirm your OpenConstructionERP account"
    body = (
        f"<p>{greeting}</p>"
        f"<p>Confirm your email address to activate your <strong>{_APP_NAME}</strong> account. "
        f"The link is valid for {token_lifetime_hours} hours.</p>"
        f"<p style='font-size:13px; color:#6e6e73;'>If you did not sign up, you can ignore this email.</p>"
    )
    return subject, wrap("Confirm your account", body, verify_url, "Confirm account")


def template_test_email(sent_by: str | None) -> tuple[str, str]:
    """The message an administrator sends to check outbound mail."""
    from html import escape

    who = f" by {escape(sent_by)}" if sent_by else ""
    subject = "OpenConstructionERP test email"
    body = (
        f"<p>This test message was sent{who} from the email settings of {_APP_NAME}.</p>"
        f"<p>If you are reading it, outbound email works: password resets, sign-up confirmations "
        f"and notifications will be delivered.</p>"
    )
    return subject, wrap("Outbound email works", body)
