"""Unit tests for the pluggable email service (``app.core.email``).

Covers:
    - Per-backend behaviour (console, noop, memory, smtp-without-config)
    - EmailService facade + password-reset helper
    - Template rendering (wrap + password_reset)
    - Backend resolution via settings (fallback from smtp → console when
      SMTP_HOST is empty)
    - Back-compat shim at ``app.modules.integrations.email_service``
"""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, patch

import pytest

from app.config import Settings
from app.core.email import (
    ConsoleEmailBackend,
    DeliveryResult,
    EmailMessage,
    EmailService,
    MemoryEmailBackend,
    NoopEmailBackend,
    SmtpEmailBackend,
    get_email_service,
    reset_email_service_cache,
    template_password_reset,
    wrap,
)
from app.core.email.service import _resolve_backend
from app.core.email.smtp import _html_to_text

# ---------------------------------------------------------------------------
# Backends
# ---------------------------------------------------------------------------


class TestConsoleBackend:
    """Console backend logs at INFO; always succeeds."""

    @pytest.mark.asyncio
    async def test_success(self, caplog):
        backend = ConsoleEmailBackend()
        with caplog.at_level(logging.INFO, logger="app.core.email.console"):
            result = await backend.send(
                EmailMessage(to="alice@example.com", subject="Hi", html_body="<p>Hello</p>"),
            )
        assert result.ok is True
        assert result.backend == "console"
        assert any("alice@example.com" in rec.getMessage() for rec in caplog.records)
        assert any("Hi" in rec.getMessage() for rec in caplog.records)

    @pytest.mark.asyncio
    async def test_long_body_truncated(self, caplog):
        backend = ConsoleEmailBackend()
        big = "<p>" + ("X" * 10_000) + "</p>"
        with caplog.at_level(logging.INFO, logger="app.core.email.console"):
            await backend.send(EmailMessage(to="a@x", subject="s", html_body=big))
        messages = [rec.getMessage() for rec in caplog.records]
        # Preview in INFO line must be bounded.
        assert any("…" in m or "..." in m for m in messages)


class TestNoopBackend:
    """Noop drops silently with success."""

    @pytest.mark.asyncio
    async def test_success(self):
        backend = NoopEmailBackend()
        result = await backend.send(
            EmailMessage(to="a@x", subject="s", html_body="<p/>"),
        )
        assert result.ok is True
        assert result.backend == "noop"


class TestMemoryBackend:
    """Memory backend captures every send for assertions."""

    @pytest.mark.asyncio
    async def test_captures_message(self):
        backend = MemoryEmailBackend()
        msg = EmailMessage(to="a@x", subject="Hello", html_body="<p/>", tags=["welcome"])
        result = await backend.send(msg)
        assert result.ok
        assert backend.sent == [msg]
        assert backend.sent[0].tags == ["welcome"]

    @pytest.mark.asyncio
    async def test_clear(self):
        backend = MemoryEmailBackend()
        await backend.send(EmailMessage(to="a", subject="s", html_body="b"))
        backend.clear()
        assert backend.sent == []


class TestSmtpBackend:
    """SMTP backend behaviour without hitting a real server."""

    def _settings(self, **overrides) -> Settings:
        base = {
            "smtp_host": "",
            "smtp_port": 587,
            "smtp_user": "",
            "smtp_password": "",
            "smtp_from": "notifications@openconstructionerp.com",
            "smtp_tls": True,
        }
        base.update(overrides)
        return Settings(**base)  # type: ignore[arg-type]

    @pytest.mark.asyncio
    async def test_unconfigured_returns_structured_failure(self, caplog):
        backend = SmtpEmailBackend(self._settings())
        with caplog.at_level(logging.WARNING, logger="app.core.email.smtp"):
            result = await backend.send(EmailMessage(to="a@x", subject="s", html_body="b"))
        assert result.ok is False
        assert result.reason == "smtp not configured"
        # Loud warning so operators notice (v2.3.1 regression guard).
        assert any("not configured" in rec.getMessage() for rec in caplog.records)

    @pytest.mark.asyncio
    async def test_successful_send_mocked(self):
        backend = SmtpEmailBackend(self._settings(smtp_host="mail.example.com"))
        with patch("app.core.email.smtp.smtplib.SMTP") as smtp_cls:
            server = smtp_cls.return_value
            result = await backend.send(
                EmailMessage(to="a@x", subject="Hi", html_body="<p>Hello</p>"),
            )
        assert result.ok
        assert result.backend == "smtp"
        server.sendmail.assert_called_once()
        # Default settings have smtp_tls=True → STARTTLS is negotiated.
        server.starttls.assert_called_once()
        # No credentials configured → login skipped.
        server.login.assert_not_called()

    @pytest.mark.asyncio
    async def test_login_when_credentials_configured(self):
        backend = SmtpEmailBackend(
            self._settings(
                smtp_host="mail.example.com",
                smtp_user="bot",
                smtp_password="secret",
            ),
        )
        with patch("app.core.email.smtp.smtplib.SMTP") as smtp_cls:
            server = smtp_cls.return_value
            await backend.send(EmailMessage(to="a@x", subject="s", html_body="<p/>"))
        server.login.assert_called_once_with("bot", "secret")

    @pytest.mark.asyncio
    async def test_auth_failure_returned_not_raised(self):
        import smtplib as smtplib_mod

        backend = SmtpEmailBackend(
            self._settings(
                smtp_host="mail.example.com",
                smtp_user="bot",
                smtp_password="bad",
            ),
        )
        with patch("app.core.email.smtp.smtplib.SMTP") as smtp_cls:
            server = smtp_cls.return_value
            server.login.side_effect = smtplib_mod.SMTPAuthenticationError(535, b"bad creds")
            result = await backend.send(EmailMessage(to="a@x", subject="s", html_body="<p/>"))
        assert result.ok is False
        assert result.reason == "auth failed"

    @pytest.mark.asyncio
    async def test_recipient_refused(self):
        import smtplib as smtplib_mod

        backend = SmtpEmailBackend(self._settings(smtp_host="mail.example.com"))
        with patch("app.core.email.smtp.smtplib.SMTP") as smtp_cls:
            server = smtp_cls.return_value
            server.sendmail.side_effect = smtplib_mod.SMTPRecipientsRefused({"a@x": (550, b"no")})
            result = await backend.send(EmailMessage(to="a@x", subject="s", html_body="<p/>"))
        assert result.ok is False
        assert result.reason == "recipient refused"

    @pytest.mark.asyncio
    async def test_network_error_returned_not_raised(self):
        backend = SmtpEmailBackend(self._settings(smtp_host="unreachable.example"))
        with patch("app.core.email.smtp.smtplib.SMTP", side_effect=OSError("refused")):
            result = await backend.send(EmailMessage(to="a@x", subject="s", html_body="<p/>"))
        assert result.ok is False
        assert "network error" in result.reason


# ---------------------------------------------------------------------------
# EmailService facade
# ---------------------------------------------------------------------------


class TestEmailService:
    """High-level helpers layered on top of the backend."""

    @pytest.mark.asyncio
    async def test_send_password_reset_injects_token_in_link(self):
        mem = MemoryEmailBackend()
        service = EmailService(mem)
        result = await service.send_password_reset(
            to="alice@example.com",
            reset_url="https://app.example.com/auth/reset?token=ABC",
            recipient_name="Alice",
        )
        assert result.ok
        sent = mem.sent[0]
        assert sent.to == "alice@example.com"
        assert "password_reset" in sent.tags
        assert "Reset your password" in sent.html_body
        assert "ABC" in sent.html_body
        assert "Alice" in sent.html_body

    @pytest.mark.asyncio
    async def test_send_password_reset_anonymous_greeting(self):
        mem = MemoryEmailBackend()
        service = EmailService(mem)
        await service.send_password_reset(
            to="x@y", reset_url="https://x.y/r?token=T", recipient_name=None,
        )
        assert "Hello" in mem.sent[0].html_body

    @pytest.mark.asyncio
    async def test_failure_is_logged(self, caplog):
        class ExplodingBackend(NoopEmailBackend):
            async def send(self, message):
                return DeliveryResult.failure("noop", reason="simulated")

        service = EmailService(ExplodingBackend())
        with caplog.at_level(logging.WARNING, logger="app.core.email.service"):
            result = await service.send(
                EmailMessage(to="a@x", subject="s", html_body="<p/>"),
            )
        assert result.ok is False
        assert any("delivery failed" in rec.getMessage() for rec in caplog.records)


# ---------------------------------------------------------------------------
# Backend resolution from settings
# ---------------------------------------------------------------------------


class TestResolveBackend:
    """``_resolve_backend`` is the switch between the four backend names."""

    def test_console(self):
        s = Settings(email_backend="console")
        assert isinstance(_resolve_backend(s), ConsoleEmailBackend)

    def test_noop(self):
        s = Settings(email_backend="noop")
        assert isinstance(_resolve_backend(s), NoopEmailBackend)

    def test_memory(self):
        s = Settings(email_backend="memory")
        assert isinstance(_resolve_backend(s), MemoryEmailBackend)

    def test_smtp_configured(self):
        s = Settings(email_backend="smtp", smtp_host="mail.example.com")
        assert isinstance(_resolve_backend(s), SmtpEmailBackend)

    def test_smtp_unconfigured_falls_back_to_console(self, caplog):
        s = Settings(email_backend="smtp", smtp_host="")
        with caplog.at_level(logging.WARNING, logger="app.core.email.service"):
            backend = _resolve_backend(s)
        assert isinstance(backend, ConsoleEmailBackend)
        assert any("EMAIL_BACKEND=smtp" in rec.getMessage() for rec in caplog.records)


class TestGetEmailService:
    """``get_email_service`` wires backend injection + caching."""

    def test_explicit_backend_is_used(self):
        mem = MemoryEmailBackend()
        service = get_email_service(backend=mem)
        assert service.backend_name == "memory"

    def test_cache_reset(self):
        reset_email_service_cache()
        s1 = get_email_service()
        s2 = get_email_service()
        assert s1 is s2
        reset_email_service_cache()
        s3 = get_email_service()
        # After reset we MAY or may not get the same instance depending
        # on settings identity; important invariant is that cache_clear
        # doesn't raise.
        assert s3.backend_name == s1.backend_name


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------


class TestTemplates:
    def test_wrap_contains_boilerplate(self):
        html = wrap("Title", "<p>Body</p>")
        assert "<!DOCTYPE html>" in html
        assert "OpenConstructionERP" in html
        assert "Title" in html
        assert "<p>Body</p>" in html

    def test_wrap_with_action_button(self):
        html = wrap("Title", "<p/>", action_url="https://x.y/a", action_label="Go")
        assert "https://x.y/a" in html
        assert ">Go<" in html

    def test_password_reset_template(self):
        subject, html = template_password_reset(
            recipient_name="Alice",
            reset_url="https://x.y/r?token=T",
            token_lifetime_minutes=45,
        )
        assert "Reset your OpenConstructionERP password" in subject
        assert "Alice" in html
        assert "https://x.y/r?token=T" in html
        assert "45 minutes" in html
        assert "did not request" in html  # safety disclaimer

    def test_password_reset_no_name(self):
        _, html = template_password_reset(
            recipient_name=None, reset_url="https://x/r?token=T",
        )
        assert "Hello" in html


# ---------------------------------------------------------------------------
# HTML → plain text (SMTP fallback)
# ---------------------------------------------------------------------------


class TestHtmlToText:
    def test_strips_tags(self):
        assert _html_to_text("<p>Hello <b>World</b></p>") == "Hello World"

    def test_decodes_common_entities(self):
        assert _html_to_text("a &amp; b &lt;c&gt;") == "a & b <c>"

    def test_collapses_whitespace(self):
        assert _html_to_text("<p>a</p>\n\n<p>b</p>") == "a b"


# ---------------------------------------------------------------------------
# Back-compat shim
# ---------------------------------------------------------------------------


class TestLegacyShim:
    """``app.modules.integrations.email_service`` still works."""

    @pytest.mark.asyncio
    async def test_send_email_delegates_and_returns_bool(self):
        from app.modules.integrations import email_service as legacy

        mock_service = AsyncMock()
        mock_service.send.return_value = DeliveryResult.success("noop")
        with patch(
            "app.modules.integrations.email_service.get_email_service",
            return_value=mock_service,
        ):
            ok = await legacy.send_email("a@x", "Hi", "<p/>")
        assert ok is True
        mock_service.send.assert_awaited_once()

    def test_templates_still_importable(self):
        # Regression guard: tests/unit/test_integrations.py imports these.
        from app.modules.integrations.email_service import (
            template_invoice_approved,
            template_meeting_invitation,
            template_safety_alert,
            template_task_assigned,
        )

        subject, html = template_task_assigned("Do X", "Alice", "Project Y")
        assert "Do X" in subject
        assert "Alice" in html
        # Keep the other three referenced so ruff does not flag them.
        for fn in (template_invoice_approved, template_meeting_invitation, template_safety_alert):
            assert callable(fn)
