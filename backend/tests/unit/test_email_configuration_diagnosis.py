# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for outbound-email configuration diagnosis (``app.core.email``).

These pin the behaviour behind a support report where a user filled in every
``SMTP_*`` variable, saw no error anywhere, and never received a message. The
cause was ``EMAIL_BACKEND`` still holding its ``console`` default: the console
transport records a message and reports a *successful* delivery, so every
signal the user could reach said the send had worked.

The rule under test: whenever the settings contradict themselves, something
must say so in words that name the setting to change. Silence is the defect.

Every ``Settings`` here passes ``_env_file=None`` so a developer's real
``backend/.env`` cannot decide the outcome of a test.
"""

from __future__ import annotations

import logging

import pytest

from app.config import Settings
from app.core.email import diagnose_email_config, email_delivery_enabled
from app.core.email.console import ConsoleEmailBackend
from app.core.email.service import _resolve_backend
from app.core.email.smtp import SmtpEmailBackend


def _settings(**overrides) -> Settings:
    base = {"_env_file": None}
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


class TestEmailDeliveryEnabled:
    """The single definition of "mail will really leave the building"."""

    def test_requires_both_backend_and_host(self) -> None:
        assert email_delivery_enabled(_settings(email_backend="smtp", smtp_host="mail.example.invalid")) is True

    @pytest.mark.parametrize(
        ("backend", "host"),
        [
            ("console", "mail.example.invalid"),  # host set, transport records only
            ("smtp", ""),  # transport picked, nowhere to send
            ("noop", "mail.example.invalid"),
            ("memory", "mail.example.invalid"),
            ("console", ""),
        ],
    )
    def test_anything_less_is_not_delivery(self, backend: str, host: str) -> None:
        assert email_delivery_enabled(_settings(email_backend=backend, smtp_host=host)) is False


class TestDiagnoseEmailConfig:
    """Each contradiction gets a message that names the setting to change."""

    def test_smtp_settings_with_console_backend_is_reported(self) -> None:
        """The reported case: every SMTP_* filled in, EMAIL_BACKEND left alone."""
        problem = diagnose_email_config(
            _settings(
                email_backend="console",
                smtp_host="mail.example.invalid",
                smtp_user="user@example.invalid",
                smtp_password="example-not-a-real-password",
            ),
        )
        assert problem is not None
        assert "EMAIL_BACKEND" in problem
        # It must name the value that fixes it, not merely state that something is wrong.
        assert "EMAIL_BACKEND=smtp" in problem

    def test_coherent_smtp_configuration_is_silent(self) -> None:
        assert (
            diagnose_email_config(
                _settings(
                    email_backend="smtp",
                    smtp_host="mail.example.invalid",
                    smtp_port=587,
                    smtp_tls=True,
                    smtp_user="user@example.invalid",
                    smtp_password="example-not-a-real-password",
                ),
            )
            is None
        )

    def test_no_email_configuration_at_all_is_silent(self) -> None:
        """An install that never sends mail is supported and must not nag."""
        assert diagnose_email_config(_settings(email_backend="console", smtp_host="")) is None

    def test_smtp_backend_without_host_is_reported(self) -> None:
        problem = diagnose_email_config(_settings(email_backend="smtp", smtp_host=""))
        assert problem is not None
        assert "SMTP_HOST" in problem

    def test_port_465_is_reported_as_unsupported(self) -> None:
        problem = diagnose_email_config(
            _settings(email_backend="smtp", smtp_host="mail.example.invalid", smtp_port=465),
        )
        assert problem is not None
        assert "465" in problem
        assert "587" in problem

    def test_port_587_without_tls_is_reported(self) -> None:
        problem = diagnose_email_config(
            _settings(
                email_backend="smtp",
                smtp_host="mail.example.invalid",
                smtp_port=587,
                smtp_tls=False,
            ),
        )
        assert problem is not None
        assert "SMTP_TLS" in problem

    def test_user_without_password_names_the_right_variable(self) -> None:
        """``SMTP_PASS`` does not bind; the field is ``SMTP_PASSWORD``."""
        problem = diagnose_email_config(
            _settings(
                email_backend="smtp",
                smtp_host="mail.example.invalid",
                smtp_user="user@example.invalid",
                smtp_password="",
            ),
        )
        assert problem is not None
        assert "SMTP_PASSWORD" in problem


class TestResolveBackendWarns:
    """Resolution is the last place that can speak before mail disappears."""

    def test_console_default_with_smtp_settings_warns(self, caplog: pytest.LogCaptureFixture) -> None:
        settings = _settings(
            email_backend="console",
            smtp_host="mail.example.invalid",
            smtp_user="user@example.invalid",
            smtp_password="example-not-a-real-password",
        )
        with caplog.at_level(logging.WARNING, logger="app.core.email.service"):
            backend = _resolve_backend(settings)

        assert isinstance(backend, ConsoleEmailBackend)
        assert "EMAIL_BACKEND" in caplog.text

    def test_coherent_configuration_does_not_warn(self, caplog: pytest.LogCaptureFixture) -> None:
        settings = _settings(
            email_backend="smtp",
            smtp_host="mail.example.invalid",
            smtp_port=587,
            smtp_tls=True,
        )
        with caplog.at_level(logging.WARNING, logger="app.core.email.service"):
            backend = _resolve_backend(settings)

        assert isinstance(backend, SmtpEmailBackend)
        assert caplog.text == ""


class TestPort465FailsFastInsteadOfStalling:
    """465 wants implicit TLS; this transport only speaks STARTTLS."""

    @pytest.mark.asyncio
    async def test_send_refuses_before_opening_a_socket(self) -> None:
        from app.core.email.base import EmailMessage

        # 127.0.0.1 with nothing listening: if the guard regresses, this would
        # go to the network and stall on the socket timeout rather than return.
        backend = SmtpEmailBackend(
            _settings(email_backend="smtp", smtp_host="127.0.0.1", smtp_port=465, smtp_tls=True),
        )
        result = await backend.send(
            EmailMessage(to="recipient@example.invalid", subject="s", html_body="<p>x</p>"),
        )

        assert result.ok is False
        assert "465" in result.reason
        assert "587" in result.reason
