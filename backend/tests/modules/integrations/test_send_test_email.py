"""The email settings' test button sends a real message and reports the transport's own reason.

The only test the Email card had read the settings and said "configured"
without opening a connection, so a wrong password or a blocked port looked
fine until the first sign-up confirmation silently went nowhere.
"""

from __future__ import annotations

import pytest

from app.core.email import DeliveryResult, EmailBackend, EmailMessage, MemoryEmailBackend, get_email_service
from app.modules.integrations import router as integrations_router
from app.modules.integrations.schemas import TestNotificationResponse


class _RefusingBackend(EmailBackend):
    name = "smtp"

    async def send(self, message: EmailMessage) -> DeliveryResult:
        return DeliveryResult.failure(self.name, reason="auth failed")


def _configured(monkeypatch: pytest.MonkeyPatch, backend: EmailBackend) -> None:
    monkeypatch.setattr(
        integrations_router,
        "_email_configuration_report",
        lambda: TestNotificationResponse(success=True, message="configured"),
    )
    monkeypatch.setattr("app.core.email.get_email_service", lambda: get_email_service(backend=backend))


@pytest.mark.asyncio
async def test_the_test_email_goes_to_the_caller(monkeypatch: pytest.MonkeyPatch) -> None:
    outbox = MemoryEmailBackend()
    _configured(monkeypatch, outbox)
    out = await integrations_router.send_server_test_email("estimator@builder.de", "Anna Estimator")
    assert out.success is True
    assert "estimator@builder.de" in out.message
    (mail,) = outbox.sent
    assert mail.to == "estimator@builder.de"
    assert "smtp_test" in mail.tags


@pytest.mark.asyncio
async def test_a_refused_login_is_named_in_the_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    _configured(monkeypatch, _RefusingBackend())
    out = await integrations_router.send_server_test_email("estimator@builder.de")
    assert out.success is False
    assert "auth failed" in out.message


@pytest.mark.asyncio
async def test_nothing_is_sent_when_the_server_has_no_mail_transport(monkeypatch: pytest.MonkeyPatch) -> None:
    outbox = MemoryEmailBackend()
    monkeypatch.setattr("app.core.email.get_email_service", lambda: get_email_service(backend=outbox))
    monkeypatch.setattr(
        integrations_router,
        "_email_configuration_report",
        lambda: TestNotificationResponse(success=False, message="Outbound email is not configured on this server."),
    )
    out = await integrations_router.send_server_test_email("estimator@builder.de")
    assert out.success is False
    assert "not configured" in out.message
    assert outbox.sent == []
