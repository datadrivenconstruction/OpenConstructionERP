# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Every email the platform sends carries the OpenConstructionERP brand.

The brand shows in the same places in every mail: the ``From:`` display name,
the line beside the logo, and the closing line of the footer. It is never
translated or shortened, and the old internal name never reaches a recipient.
Each email the platform can send is rendered here and checked for both.
"""

from __future__ import annotations

import re
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.core.email import (
    BRAND_NAME,
    EmailAttachment,
    EmailMessage,
    EmailService,
    MemoryEmailBackend,
    SmtpEmailBackend,
    brand_header,
    template_invoice_approved,
    template_meeting_invitation,
    template_password_reset,
    template_safety_alert,
    template_task_assigned,
)
from app.core.email.smtp import sender_addresses
from app.modules.notifications import email_render
from app.modules.portal import login_email
from app.modules.reporting.service import progress_report_email
from app.modules.tendering import invitation_email

BRAND_FOOTER = f"{BRAND_NAME}</p></body></html>"
OLD_NAME = re.compile("open ?estimate", re.IGNORECASE)


def _assert_branded(subject: str, html_body: str, *, shell: bool = True) -> None:
    assert BRAND_NAME == "OpenConstructionERP"
    assert brand_header() in html_body, "the mail does not open with the brand line"
    if shell:
        assert html_body.endswith(BRAND_FOOTER), "the mail does not close with the brand line"
    assert not OLD_NAME.search(subject), subject
    assert not OLD_NAME.search(html_body)


def _notification_mails():
    for locale in email_render.SUPPORTED_LOCALES:
        yield (
            f"notification/{locale}",
            email_render.digest_subject(locale, 2),
            email_render.render_notification_email(
                locale=locale,
                recipient_name="Ann",
                subject="RFI assigned to you",
                body_text="RFI-7",
                action_url="/rfi?id=7",
                base_url="https://erp.example.com",
            ),
        )


def _portal_mails():
    for locale in login_email.SUPPORTED_LOCALES:
        for kind in ("invite", "login"):
            yield (
                f"portal-{kind}/{locale}",
                login_email.login_subject(kind, locale, ""),
                login_email.login_html(
                    kind=kind,
                    locale=locale,
                    full_name="Ann",
                    sender="",
                    action_url="https://erp.example.com/portal/home?token=t",
                    valid_hours=24,
                ),
            )


def _tender_mails():
    for locale in invitation_email.SUPPORTED_LOCALES:
        for link in ("https://erp.example.com/tendering/bid/t", ""):
            yield (
                f"bid-invite/{locale}/{'link' if link else 'no-link'}",
                invitation_email.invitation_subject(locale, "Concrete works"),
                invitation_email.invitation_html(
                    locale=locale,
                    company_name="Acme",
                    package_name="Concrete works",
                    project_name="Tower A",
                    description="",
                    deadline="2026-11-01",
                    custom_message=None,
                    action_url=link,
                ),
            )


def _core_templates():
    yield ("password-reset", *template_password_reset("Ann", "https://erp.example.com/auth/reset?token=t"))
    yield ("task-assigned", *template_task_assigned("Pour slab", "Ann", "Tower A"))
    yield ("invoice-approved", *template_invoice_approved("INV-1", "100 EUR", "Tower A"))
    yield ("safety-alert", *template_safety_alert("Open edge", "Bob", "Tower A"))
    yield ("meeting", *template_meeting_invitation("Site meeting", "2026-11-01", "Gate 2", "Tower A"))


ALL_MAILS = [*_notification_mails(), *_portal_mails(), *_tender_mails(), *_core_templates()]


@pytest.mark.parametrize(("name", "subject", "html_body"), ALL_MAILS, ids=[m[0] for m in ALL_MAILS])
def test_the_mail_carries_the_brand(name, subject, html_body):
    _assert_branded(subject, html_body)


def test_the_brand_is_never_translated():
    # The notification button names the product in every language.
    for locale in email_render.SUPPORTED_LOCALES:
        assert BRAND_NAME in email_render._TABLES[locale]["cta"], locale
        assert email_render.digest_subject(locale, 1).startswith(f"{BRAND_NAME}: "), locale


def test_mail_nobody_subscribed_to_does_not_blame_notification_settings():
    for name, _subject, html_body in [*_portal_mails(), *_tender_mails()]:
        assert "notification preferences" not in html_body, name
    _, reset = template_password_reset("Ann", "https://erp.example.com/auth/reset?token=t")
    assert "notification preferences" not in reset


@pytest.mark.asyncio
async def test_a_document_email_carries_the_brand():
    backend = MemoryEmailBackend()
    await EmailService(backend).send_document(
        "buyer@example.com",
        subject=f"Reservation receipt - {BRAND_NAME}",
        document_name="Reservation receipt",
        attachment=EmailAttachment(filename="r.pdf", content=b"%PDF-1.4"),
        recipient_name="Ann",
    )
    _assert_branded(backend.sent[0].subject, backend.sent[0].html_body)


def test_a_progress_report_email_carries_the_brand():
    report_html = "<!DOCTYPE html><html><head></head><body><h1>Week 40</h1><footer>x</footer></body></html>"
    subject, html_body = progress_report_email("Week 40", report_html)
    assert subject == f"Progress Report: Week 40 - {BRAND_NAME}"
    _assert_branded(subject, html_body, shell=False)
    assert html_body.startswith(f"<!DOCTYPE html><html><head></head><body>{brand_header()}")
    # A stub body without a document still opens with the brand line.
    assert progress_report_email("Week 40", "<p>Report</p>")[1].startswith(brand_header())


# ── The From: display name ────────────────────────────────────────────────


def test_a_bare_sender_address_shows_the_brand_name():
    assert sender_addresses("info@datadrivenconstruction.io") == (
        "OpenConstructionERP <info@datadrivenconstruction.io>",
        "info@datadrivenconstruction.io",
    )


def test_a_configured_display_name_is_kept():
    assert sender_addresses("Acme Builders <noreply@acme.example>") == (
        "Acme Builders <noreply@acme.example>",
        "noreply@acme.example",
    )


def test_the_smtp_backend_sends_under_the_brand_name():
    sent: dict = {}

    class FakeSMTP:
        def __init__(self, *args, **kwargs):
            pass

        def ehlo(self):
            pass

        def starttls(self):
            pass

        def login(self, *args):
            pass

        def sendmail(self, envelope_from, to, raw):
            sent.update(envelope_from=envelope_from, to=to, raw=raw)

        def quit(self):
            pass

    settings = SimpleNamespace(
        smtp_host="smtp.example.com",
        smtp_port=587,
        smtp_user="",
        smtp_password="",
        smtp_from="info@datadrivenconstruction.io",
        smtp_tls=True,
    )
    with patch("app.core.email.smtp.smtplib.SMTP", FakeSMTP):
        result = SmtpEmailBackend(settings)._send_sync(
            EmailMessage(to="ann@example.com", subject="Hello", html_body="<p>x</p>")
        )
    assert result.ok
    assert sent["envelope_from"] == "info@datadrivenconstruction.io"
    assert "From: OpenConstructionERP <info@datadrivenconstruction.io>" in sent["raw"]
    assert not OLD_NAME.search(sent["raw"])
