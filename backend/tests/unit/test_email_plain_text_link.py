# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The plain-text alternative of an outgoing mail must carry its link targets.

Every mail is authored as HTML and the ``text/plain`` part of the
``multipart/alternative`` body is derived from it.  When that derivation
drops the ``href`` of an anchor, a recipient reading plain text sees the
label with nothing behind it - for the password-reset mail that means the
words "Reset password" and no way to reset a password at all.

The end-to-end test here goes through ``SmtpEmailBackend`` with the socket
replaced, reads the ``text/plain`` part back out of the serialized message,
and asserts the URL is in it.  Nothing is delivered anywhere.
"""

from __future__ import annotations

import email
from unittest.mock import patch

import pytest

from app.config import Settings
from app.core.email import (
    EmailMessage,
    SmtpEmailBackend,
    template_invoice_approved,
    template_meeting_invitation,
    template_password_reset,
    template_safety_alert,
    template_task_assigned,
    wrap,
)
from app.core.email.smtp import _html_to_text

RESET_URL = "https://app.openconstructionerp.com/reset-password?token=abc123&uid=42"
ACTION_URL = "https://app.openconstructionerp.com/go?id=7&ref=mail"


def _smtp_settings(**overrides) -> Settings:
    base = {
        "smtp_host": "mail.example.com",
        "smtp_port": 587,
        "smtp_user": "",
        "smtp_password": "",
        "smtp_from": "info@datadrivenconstruction.io",
        "smtp_tls": True,
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


def _plain_part(raw_message: str) -> str:
    """Return the ``text/plain`` alternative of a serialized MIME message."""
    for part in email.message_from_string(raw_message).walk():
        if part.get_content_type() == "text/plain":
            return part.get_payload(decode=True).decode("utf-8")
    raise AssertionError("outgoing message carries no text/plain part")


#: One rendered body per template that offers a call-to-action link.
LINKED_BODIES = [
    ("password_reset", template_password_reset("Ivan", ACTION_URL)[1]),
    ("task_assigned", template_task_assigned("Pour slab B2", "Ivan", "Tower A", ACTION_URL)[1]),
    ("invoice_approved", template_invoice_approved("INV-42", "1200.00 EUR", "Tower A", ACTION_URL)[1]),
    ("safety_alert", template_safety_alert("Unguarded edge on level 4", "Ivan", "Tower A", ACTION_URL)[1]),
    (
        "meeting_invitation",
        template_meeting_invitation("Kickoff", "2026-09-10 09:00", "Site office", "Tower A", ACTION_URL)[1],
    ),
]


class TestPasswordResetIsUsableInPlainText:
    """The mail whose entire purpose is the link."""

    def test_plain_text_carries_the_reset_url(self):
        _, html = template_password_reset(recipient_name="Ivan", reset_url=RESET_URL)
        text = _html_to_text(html)
        assert RESET_URL in text, (
            f"the plain-text reader was given no way to reset their password; the whole text part reads: {text!r}"
        )

    def test_the_url_follows_the_label_it_belongs_to(self):
        _, html = template_password_reset(recipient_name="Ivan", reset_url=RESET_URL)
        assert f"Reset password <{RESET_URL}>" in _html_to_text(html)

    @pytest.mark.asyncio
    async def test_delivered_text_part_carries_the_reset_url(self):
        """End to end through the backend that builds the MIME message."""
        _, html = template_password_reset(recipient_name="Ivan", reset_url=RESET_URL)
        backend = SmtpEmailBackend(_smtp_settings())
        with patch("app.core.email.smtp.smtplib.SMTP") as smtp_cls:
            server = smtp_cls.return_value
            result = await backend.send(
                EmailMessage(
                    to="ivan@example.com",
                    subject="Reset your password",
                    html_body=html,
                    tags=["password_reset"],
                ),
            )
        assert result.ok
        raw = server.sendmail.call_args[0][2]
        text = _plain_part(raw)
        assert RESET_URL in text, f"text/plain part of the sent message reads: {text!r}"

    @pytest.mark.parametrize(("name", "html"), LINKED_BODIES, ids=[n for n, _ in LINKED_BODIES])
    def test_every_template_with_a_call_to_action_keeps_its_target(self, name, html):
        assert ACTION_URL in _html_to_text(html), f"{name} lost its action URL"


class TestAnchorRendering:
    """How a link is written once it survives."""

    def test_anchor_text_that_is_already_the_target_is_not_printed_twice(self):
        text = _html_to_text('<a href="https://x.io/page">https://x.io/page</a>')
        assert text == "https://x.io/page"

    def test_an_address_shown_as_its_own_label_is_not_printed_twice(self):
        text = _html_to_text('<a href="mailto:info@datadrivenconstruction.io">info@datadrivenconstruction.io</a>')
        assert text == "info@datadrivenconstruction.io"

    def test_character_references_in_the_target_are_decoded(self):
        text = _html_to_text('<a href="https://x.io/r?a=1&amp;b=2">Go</a>')
        assert text == "Go <https://x.io/r?a=1&b=2>"

    def test_an_anchor_with_no_text_still_shows_its_target(self):
        text = _html_to_text('<a href="https://x.io/p"><img src="logo.png"/></a>')
        assert text == "<https://x.io/p>"

    @pytest.mark.parametrize("href", ["#top", "javascript:void(0)", ""])
    def test_targets_a_reader_cannot_use_are_left_out(self, href):
        text = _html_to_text(f'<a href="{href}">Click</a>')
        assert text == "Click"

    def test_a_closing_bracket_inside_an_attribute_does_not_truncate_the_tag(self):
        """The reason this is parsed rather than pattern-matched.

        ``<[^>]+>`` ends the tag at the first ``>``, which here sits inside a
        quoted attribute, so the rest of the attribute leaks into the body.
        """
        text = _html_to_text('<a href="https://x.io/q" title="a > b">Go</a>')
        assert text == "Go <https://x.io/q>"

    def test_stylesheet_and_script_content_stays_out_of_the_body(self):
        text = _html_to_text("<style>a{color:red}</style><p>Hi</p><script>var x=1;</script>")
        assert text == "Hi"

    def test_malformed_markup_degrades_instead_of_raising(self):
        text = _html_to_text('<p>Hi <a href="https://x.io/p">Go</a> &<b>bold')
        assert "https://x.io/p" in text


class TestBehaviourThatMustNotChange:
    """Controls - these hold with or without the link fix."""

    def test_a_mail_with_no_link_gains_nothing(self):
        """The document cover note carries a PDF, never a URL."""
        html = wrap(
            "Handover certificate",
            "<p>Hi Ivan,</p><p>Please find attached your <strong>Handover certificate</strong>.</p>",
        )
        text = _html_to_text(html)
        assert "Please find attached your Handover certificate" in text
        assert "<" not in text
        assert "http" not in text

    def test_tags_are_stripped_and_whitespace_collapsed(self):
        assert _html_to_text("<p>Hello <b>World</b></p>") == "Hello World"
        assert _html_to_text("<p>a</p>\n\n<p>b</p>") == "a b"
        assert _html_to_text("a &amp; b &lt;c&gt;") == "a & b <c>"
