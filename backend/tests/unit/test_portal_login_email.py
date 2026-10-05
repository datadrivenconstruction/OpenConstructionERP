# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The portal emails its own invitations and sign-in links.

Before this the invitation token was copied by hand and the self-service
``/auth/magic-link`` answered 202 while sending nothing, so a client whose
session ran out had no way back in without phoning the builder.
"""

from __future__ import annotations

import re
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.modules.portal import login_email
from app.modules.portal.service import MAGIC_LINK_REQUEST_INTERVAL, now_utc
from tests.unit.test_portal import _make_service, _patch_bus

_LANDING_TS = Path(__file__).resolve().parents[3] / "frontend" / "src" / "features" / "portal" / "portalLanding.ts"


# ── Template ──────────────────────────────────────────────────────────────


def test_the_emailed_link_opens_the_same_page_as_the_copied_link():
    source = _LANDING_TS.read_text(encoding="utf-8")
    block = re.search(r"PAYMENT_FIRST_ROLES[^=]*=\s*new Set<PortalRole>\(\[(.*?)\]\)", source, re.S)
    assert block, "portalLanding.ts no longer declares PAYMENT_FIRST_ROLES the way this test reads it"
    frontend_roles = set(re.findall(r"'([a-z_]+)'", block.group(1)))
    assert frontend_roles == set(login_email._PAYMENT_FIRST_ROLES)
    assert "PORTAL_HOME_PATH = '/portal/home'" in source
    assert "PORTAL_PAYMENTS_PATH = '/portal/payments'" in source
    assert login_email.landing_path("client") == "/portal/home"
    assert login_email.landing_path("subcontractor") == "/portal/payments"


def test_the_link_carries_the_token_on_the_configured_frontend():
    settings = SimpleNamespace(resolved_frontend_url="https://erp.example.com/")
    with patch("app.config.get_settings", return_value=settings):
        url = login_email.portal_link_url("abc123", "client")
    assert url == "https://erp.example.com/portal/home?token=abc123"


def test_a_regional_language_reads_its_own_catalogue():
    assert login_email.email_locale("de-AT") == "de"
    assert login_email.email_locale("pt-BR") == "pt"
    assert login_email.email_locale("xx") == "en"
    assert login_email.login_subject("login", "de-AT", "") == "Ihr Anmeldelink für das Kundenportal"


def test_every_language_carries_every_key():
    keys = set(login_email._TABLES["en"])
    for locale, table in login_email._TABLES.items():
        assert set(table) == keys, locale


def test_a_name_cannot_inject_markup():
    body = login_email.login_html(
        kind="invite",
        locale="en",
        full_name="<script>x</script>",
        sender="Acme & <b>Co</b>",
        action_url="https://erp.example.com/portal/home?token=t",
        valid_hours=24,
    )
    assert "<script>" not in body
    assert "&lt;script&gt;" in body
    assert "Acme &amp; &lt;b&gt;Co&lt;/b&gt;" in body
    assert "24 hours" in body


def test_an_invite_without_a_branded_company_names_the_project_team():
    assert login_email.login_subject("invite", "en", "") == "Your project team invited you to the client portal"
    assert login_email.login_subject("invite", "en", "Builder Ltd") == "Builder Ltd invited you to the client portal"


# ── Delivery ──────────────────────────────────────────────────────────────


async def _send(**overrides):
    args = {
        "kind": "login",
        "email": "client@example.com",
        "full_name": "Client",
        "language": "en",
        "role": "client",
        "token": "tok",
        "expires_at": now_utc() + timedelta(hours=24),
        "now": now_utc(),
    }
    args.update(overrides)
    return await login_email.send_login_email(**args)


@pytest.mark.asyncio
async def test_no_mail_server_means_the_staff_copy_the_link():
    with patch("app.core.email.email_delivery_enabled", return_value=False):
        assert await _send() == "not_configured"


@pytest.mark.asyncio
async def test_a_delivered_email_reports_sent_and_carries_the_link():
    service = SimpleNamespace(send=AsyncMock(return_value=SimpleNamespace(ok=True)))
    settings = SimpleNamespace(resolved_frontend_url="https://erp.example.com")
    with (
        patch("app.core.email.email_delivery_enabled", return_value=True),
        patch("app.core.email.get_email_service", return_value=service),
        patch("app.config.get_settings", return_value=settings),
        patch.object(login_email, "sender_name", return_value=""),
    ):
        assert await _send(kind="invite", language="fr", token="t0k") == "sent"
    message = service.send.await_args.args[0]
    assert message.to == "client@example.com"
    assert message.subject == "Votre équipe de projet vous a invité sur le portail client"
    assert "https://erp.example.com/portal/home?token=t0k" in message.html_body


@pytest.mark.asyncio
async def test_a_crashing_transport_degrades_to_failed():
    service = SimpleNamespace(send=AsyncMock(side_effect=OSError("smtp down")))
    with (
        patch("app.core.email.email_delivery_enabled", return_value=True),
        patch("app.core.email.get_email_service", return_value=service),
        patch.object(login_email, "sender_name", return_value=""),
    ):
        assert await _send() == "failed"


# ── Self-service request ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_an_unknown_address_mints_nothing():
    svc = _make_service()
    assert await svc.request_magic_link("nobody@example.com") is None
    assert svc.magic_repo.rows == {}


@pytest.mark.asyncio
async def test_a_second_request_inside_the_interval_mints_nothing():
    svc = _make_service()
    with _patch_bus():
        user, _, _ = await svc.invite_portal_user(email="c@example.com", role="client")
    # The invitation itself was a link a moment ago.
    assert await svc.request_magic_link("c@example.com") is None
    assert len(svc.magic_repo.rows) == 1

    for row in svc.magic_repo.rows.values():
        row.created_at = now_utc() - MAGIC_LINK_REQUEST_INTERVAL - timedelta(seconds=1)
    minted = await svc.request_magic_link("C@Example.com")
    assert minted is not None
    assert minted[0].id == user.id
    assert len(svc.magic_repo.rows) == 2

    # The new link replaces the old one: a user holds one live link, not one
    # per request.
    now = now_utc()
    live = [r for r in svc.magic_repo.rows.values() if r.expires_at > now]
    assert [r.expires_at for r in live] == [minted[2]]


@pytest.mark.asyncio
async def test_a_suspended_client_gets_no_link():
    svc = _make_service()
    with _patch_bus():
        user, _, _ = await svc.invite_portal_user(email="s@example.com", role="client")
    user.status = "suspended"
    for row in svc.magic_repo.rows.values():
        row.created_at = now_utc() - timedelta(hours=1)
    assert await svc.request_magic_link("s@example.com") is None


@pytest.mark.parametrize(
    ("branding", "expected"),
    [
        ({"mode": "text", "company_name": "Northgate Builders"}, "Northgate Builders"),
        ({"mode": "logo", "company_name": "Northgate Builders"}, "Northgate Builders"),
        # Switched back to the default brand: the stored name must not sign mail.
        ({"mode": "default", "company_name": "Northgate Builders"}, ""),
        ({"mode": "text", "company_name": "  "}, ""),
    ],
)
def test_the_sender_follows_the_brand_the_workspace_shows(branding, expected):
    with patch("app.core.app_branding.read_branding", return_value=branding):
        assert login_email.sender_name() == expected


def test_the_mail_carries_no_english_footer_about_notification_preferences():
    html_body = login_email.login_html(
        kind="invite",
        locale="de",
        full_name="Anna",
        sender="Northgate Builders",
        action_url="https://erp.example.com/portal/home?token=x",
        valid_hours=24,
    )
    assert "notification preferences" not in html_body
    assert "Sent by" not in html_body


def test_other_mail_keeps_its_footer():
    from app.core.email.templates import wrap

    assert "notification preferences" in wrap("Task Assigned", "<p>x</p>")
    assert "<hr" not in wrap("Hi", "<p>x</p>", footer="")
    assert "Sent on behalf of A &amp; B" in wrap("Hi", "<p>x</p>", footer="Sent on behalf of A &amp; B")
