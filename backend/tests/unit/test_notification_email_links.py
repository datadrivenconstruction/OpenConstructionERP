# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The button in a notification email opens the app, in the reader's language.

Producers write ``action_url`` as an in-app path (``/boq/{id}``,
``/rfi?id=...``), which is what the router in the bell needs. The email put
that path into ``href`` as is, and a relative link in a mail client leads
nowhere, so the button in every notification email was dead. The mail was
also English whatever the reader's language.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.core.email import EmailService, MemoryEmailBackend
from app.core.events import Event
from app.modules.notifications import dispatcher, email_render

BASE = "https://erp.example.com"
SUB_BASE = "https://erp.example.com/erp"


# ── Link resolution ───────────────────────────────────────────────────────


def test_a_relative_path_gets_the_frontend_base():
    assert email_render.absolute_action_url("/boq/42", BASE) == "https://erp.example.com/boq/42"
    assert email_render.absolute_action_url("/rfi?id=7", BASE + "/") == "https://erp.example.com/rfi?id=7"


def test_a_sub_path_install_keeps_its_prefix():
    assert email_render.absolute_action_url("/rfi?id=7", SUB_BASE) == "https://erp.example.com/erp/rfi?id=7"
    assert email_render.absolute_action_url("/rfi?id=7", SUB_BASE + "/") == "https://erp.example.com/erp/rfi?id=7"


def test_an_absolute_link_to_our_own_frontend_stays():
    url = "https://erp.example.com/erp/boq/42?tab=lines"
    assert email_render.absolute_action_url(url, SUB_BASE) == url
    assert email_render.absolute_action_url("HTTPS://ERP.example.com/boq/1", BASE) == "HTTPS://ERP.example.com/boq/1"


@pytest.mark.parametrize(
    "url",
    [
        None,
        "",
        "   ",
        "boq/42",
        "javascript:alert(1)",
        "JavaScript:alert(1)",
        " javascript:alert(1)",
        "java\tscript:alert(1)",
        "data:text/html,<script>alert(1)</script>",
        "vbscript:msgbox(1)",
        "mailto:someone@example.com",
        "//evil.example.org/boq/1",
        "/\\evil.example.org/boq/1",
        "/boq/1\n",
        "/boq/\x00",
        "https://evil.example.org/boq/1",
        "https://erp.example.com.evil.example.org/boq/1",
        "https://erp.example.com@evil.example.org/boq/1",
        "https://user:pw@erp.example.com/boq/1",
        "https://erp.example.com:8443/boq/1",
        "https://erp.example.com:99999/boq/1",
        "https://[erp.example.com/boq/1",
        "http://erp.example.com/boq/1",
        "ftp://erp.example.com/boq/1",
    ],
)
def test_anything_else_is_dropped(url):
    assert email_render.absolute_action_url(url, BASE) is None


def test_our_host_outside_the_sub_path_is_dropped():
    assert email_render.absolute_action_url("https://erp.example.com/other/boq/1", SUB_BASE) is None
    assert email_render.absolute_action_url("https://erp.example.com/erpx/boq/1", SUB_BASE) is None


# ── Rendering ─────────────────────────────────────────────────────────────


def _render(**overrides):
    values = {
        "locale": "en",
        "recipient_name": "Ann",
        "subject": "RFI assigned to you",
        "body_text": "RFI-7 - Slab edge detail",
        "action_url": "/rfi?id=7&tab=answers",
        "base_url": SUB_BASE,
    }
    values.update(overrides)
    return email_render.render_notification_email(**values)


def test_the_button_carries_the_absolute_link_escaped():
    html = _render()
    assert 'href="https://erp.example.com/erp/rfi?id=7&amp;tab=answers"' in html
    assert "Open in OpenConstructionERP" in html


def test_a_dropped_link_renders_no_button():
    html = _render(action_url="javascript:alert(1)")
    assert "javascript" not in html
    assert "href=" not in html
    assert "Open in OpenConstructionERP" not in html


def test_every_interpolated_value_is_escaped():
    html = _render(
        recipient_name="<b>Ann</b>",
        subject="<script>x</script>",
        body_text='Line "one" & <i>two</i>\nsecond line',
    )
    assert "<script>" not in html
    assert "&lt;script&gt;x&lt;/script&gt;" in html
    assert "&lt;b&gt;Ann&lt;/b&gt;" in html
    assert "Line &quot;one&quot; &amp; &lt;i&gt;two&lt;/i&gt;<br>second line" in html


def test_the_reader_language_is_used():
    html = _render(locale="de")
    assert "Guten Tag Ann," in html
    assert "In OpenConstructionERP öffnen" in html
    assert "Benachrichtigungseinstellungen" in html
    for english in ("Hello", "Hi ", "Open in", "notification settings", "notification preferences"):
        assert english not in html


def test_a_regional_language_reads_its_base_catalogue():
    assert "Bonjour Ann," in _render(locale="fr-CA")
    assert "Здравствуйте, Ann!" in _render(locale="ru-RU")


def test_an_unknown_language_falls_back_to_english():
    html = _render(locale="xx")
    assert "Hello Ann," in html
    assert "notification settings" in html
    assert _render(locale=None) == _render(locale="en")


def test_no_name_greets_without_one():
    html = _render(recipient_name="  ", locale="de")
    assert "Guten Tag," in html


def test_every_language_carries_every_key_and_placeholder():
    en = email_render._TABLES["en"]
    for locale, table in email_render._TABLES.items():
        assert set(table) == set(en), locale
        for key, text in table.items():
            for placeholder in ("{name}", "{count}"):
                assert (placeholder in text) == (placeholder in en[key]), (locale, key)


def test_the_catalogue_covers_the_languages_the_other_emails_speak():
    from app.modules.portal import login_email
    from app.modules.tendering import invitation_email

    assert set(email_render.SUPPORTED_LOCALES) >= set(login_email.SUPPORTED_LOCALES)
    assert set(email_render.SUPPORTED_LOCALES) >= set(invitation_email.SUPPORTED_LOCALES)


def test_the_digest_subject_is_localised_with_its_count():
    assert email_render.digest_subject("en", 3) == "OpenConstructionERP: Notification digest (3)"
    assert email_render.digest_subject("de", 3) == "OpenConstructionERP: Benachrichtigungsübersicht (3)"
    assert email_render.digest_heading("ru") == "Последние уведомления:"


# ── The dispatcher sends what the renderer builds ─────────────────────────


async def _dispatch(payload: dict, *, locale: str = "de", event_type: str = "rfi_assigned"):
    backend = MemoryEmailBackend()
    service = EmailService(backend)
    settings = SimpleNamespace(resolved_frontend_url=SUB_BASE)
    with (
        patch.object(dispatcher, "_resolve_user_email", AsyncMock(return_value=("ann@example.com", "Ann", locale))),
        patch("app.core.email.get_email_service", return_value=service),
        patch("app.config.get_settings", return_value=settings),
    ):
        await dispatcher._on_dispatch_email(
            Event(
                name="notifications.dispatch.email",
                data={"user_id": "u1", "event_type": event_type, "payload": payload},
            )
        )
    return backend.sent


@pytest.mark.asyncio
async def test_the_sent_mail_links_into_the_app_in_the_reader_language():
    sent = await _dispatch(
        {
            "title_key": "notifications.rfi.assigned.title",
            "body_key": "notifications.rfi.assigned.body",
            "body_context": {"code": "RFI-7", "title": "Slab edge"},
            "action_url": "/rfi?id=7",
        }
    )
    assert len(sent) == 1
    html = sent[0].html_body
    assert 'href="https://erp.example.com/erp/rfi?id=7"' in html
    assert "In OpenConstructionERP öffnen" in html
    assert "RFI-7 - Slab edge" in html


@pytest.mark.asyncio
async def test_a_foreign_link_in_the_payload_is_never_sent():
    sent = await _dispatch({"title_key": "notifications.rfi.assigned.title", "action_url": "https://evil.example.org/"})
    assert len(sent) == 1
    assert "evil.example.org" not in sent[0].html_body
    assert "href=" not in sent[0].html_body


@pytest.mark.asyncio
async def test_the_digest_mail_is_localised():
    sent = await _dispatch(
        {
            "events": [
                {"event_type": "rfi_assigned", "payload": {"title_key": "notifications.rfi.assigned.title"}},
                {"event_type": "risk_assigned", "payload": {"title_key": "notifications.risk.assigned.title"}},
            ],
            "body_context": {"count": 2, "channel": "email"},
        },
        locale="ru",
        event_type="notifications.digest",
    )
    assert len(sent) == 1
    assert sent[0].subject == "OpenConstructionERP: Сводка уведомлений (2)"
    assert "Последние уведомления:" in sent[0].html_body
    assert "Recent notifications" not in sent[0].html_body
    assert "digest" not in sent[0].subject
