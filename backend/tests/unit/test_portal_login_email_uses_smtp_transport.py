# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Portal sign-in links and invitations leave through the shared SMTP transport.

The portal has no mailer of its own: ``send_login_email`` hands its message to
``get_email_service()``, which resolves ``EMAIL_BACKEND=smtp`` to
``SmtpEmailBackend``. That keeps every guard of the transport on the portal
path too, the reserved-domain refusal added for production mail included. A
portal that grew a second mailer would bypass those guards silently, so this
pins the route end to end with only the socket replaced.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.config import Settings
from app.core.email import base as email_base
from app.core.email import service as email_service
from app.core.email.smtp import SmtpEmailBackend
from app.modules.portal import login_email


@pytest.fixture
def smtp_settings(monkeypatch):
    settings = Settings(  # type: ignore[call-arg]
        email_backend="smtp",
        smtp_host="127.0.0.1",
        smtp_port=587,
        smtp_user="",
        smtp_password="",
        smtp_from="info@datadrivenconstruction.io",
        smtp_tls=True,
    )
    import app.config as app_config

    monkeypatch.setattr(app_config, "get_settings", lambda: settings)
    monkeypatch.setattr(email_service, "get_settings", lambda: settings)

    async def _never_deactivated(_address: str, **_kw) -> bool:
        return False

    monkeypatch.setattr(email_service, "_address_belongs_to_deactivated_account", _never_deactivated)
    email_service.reset_email_service_cache()
    yield settings
    email_service.reset_email_service_cache()


@pytest.fixture
def relayed(monkeypatch):
    """Replace only the socket write of the SMTP backend and record what reached it."""
    calls: list[email_base.EmailMessage] = []

    def fake_send_sync(self, message):
        calls.append(message)
        return email_base.DeliveryResult.success(self.name)

    monkeypatch.setattr(SmtpEmailBackend, "_send_sync", fake_send_sync)
    return calls


async def _send(kind: str, to: str) -> str:
    now = datetime.now(UTC)
    return await login_email.send_login_email(
        kind=kind,  # type: ignore[arg-type]
        email=to,
        full_name="Dana Client",
        language="en",
        role="client",
        token="tok-123",
        expires_at=now + timedelta(hours=24),
        now=now,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["invite", "login"])
async def test_portal_mail_reaches_the_smtp_backend(smtp_settings, relayed, kind) -> None:
    assert isinstance(email_service.get_email_service()._backend, SmtpEmailBackend)

    status = await _send(kind, "dana@builtwell-client.com")

    assert status == "sent"
    assert len(relayed) == 1
    assert relayed[0].to == "dana@builtwell-client.com"
    assert "tok-123" in relayed[0].html_body


@pytest.mark.asyncio
async def test_portal_mail_to_a_reserved_domain_is_refused_by_the_transport(smtp_settings, relayed) -> None:
    status = await _send("invite", "dana@example.com")

    assert status == "failed"
    assert relayed == []
