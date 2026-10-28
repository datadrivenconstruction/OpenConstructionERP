# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠A console transport nobody chose must not report a successful delivery.

``test_email_configuration_diagnosis.py`` next door pins the case where an
operator filled in every ``SMTP_*`` variable and left ``EMAIL_BACKEND`` alone.
This file pins the quieter one underneath it: an operator who set *nothing*
about email at all.

That deployment gets ``email_backend='console'`` because that is the field
default, and the console transport answers every send with
``DeliveryResult.success``. There is no failed-delivery log line, no error
returned to the caller, and no counter that moves, so the population who never
received their password reset cannot be named even afterwards. A measured
install ran that way for ten days.

The distinction the whole file rests on is between an operator who *wrote*
``EMAIL_BACKEND=console`` - a supported choice, see ``console.py`` on
air-gapped installs and compliance freezes - and one who wrote nothing.
``model_fields_set`` is the only thing that separates them: both produce the
same ``email_backend`` value, so any check reading the value alone answers
identically for the two and settles nothing.

Every ``Settings`` here passes ``_env_file=None`` for the reason the
neighbouring file gives, and the unchosen cases additionally assert that
``email_backend`` really is absent from ``model_fields_set``. Without that
assertion a stray ``EMAIL_BACKEND`` in the runner's environment would quietly
turn the two controls into the same test, which is exactly the failure this
file exists to prevent.
"""

from __future__ import annotations

import logging

import pytest

from app.config import Settings
from app.core.email.base import EmailMessage
from app.core.email.console import ConsoleEmailBackend
from app.core.email.service import (
    _resolve_backend,
    diagnose_email_config,
    report_email_config_at_startup,
)

#: Long enough and unremarkable enough to clear the non-development JWT guard,
#: which raises before a production ``Settings`` can be built at all.
_JWT = "x" * 48


def _settings(**overrides) -> Settings:
    base = {"_env_file": None}
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


def _production(**overrides) -> Settings:
    return _settings(app_env="production", jwt_secret=_JWT, **overrides)


def _message() -> EmailMessage:
    return EmailMessage(
        to="recipient@example.invalid",
        subject="Reset your password",
        html_body="<p>x</p>",
    )


@pytest.fixture(autouse=True)
def _no_inherited_email_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    """Drop both spellings of the variable from the runner's environment.

    ``_env_file=None`` only silences the ``.env`` file; environment variables
    are a separate source and bind under the bare name and the ``OE_`` prefix
    alike. A value inherited from the shell would land in ``model_fields_set``
    and make the "nobody chose" cases untestable.
    """
    for name in ("EMAIL_BACKEND", "OE_EMAIL_BACKEND"):
        monkeypatch.delenv(name, raising=False)


class TestTheTransportItself:
    """What ``send`` answers, which is what every caller ultimately reads."""

    @pytest.mark.asyncio
    async def test_console_nobody_chose_reports_failure_in_production(self) -> None:
        settings = _production()
        assert "email_backend" not in settings.model_fields_set, (
            "precondition broken: something set EMAIL_BACKEND, so this case is no "
            "longer the unchosen one it claims to test"
        )
        assert settings.email_backend == "console"

        backend = _resolve_backend(settings)
        result = await backend.send(_message())

        assert result.ok is False, "a transport nobody chose reported the send as successful"
        assert "log" in result.reason.lower()

    @pytest.mark.asyncio
    async def test_console_the_operator_chose_still_reports_success(self) -> None:
        """The air-gapped install ``console.py`` documents must keep working.

        This differs from the case above in exactly one input, the presence of
        ``email_backend``. If it ever fails together with that one, the change
        under test stopped discriminating and started refusing.
        """
        settings = _production(email_backend="console")
        assert "email_backend" in settings.model_fields_set

        backend = _resolve_backend(settings)
        result = await backend.send(_message())

        assert result.ok is True
        assert result.reason == "logged"

    @pytest.mark.asyncio
    async def test_smtp_without_a_host_falls_back_and_reports_failure(self) -> None:
        """The operator asked for delivery in the loudest way the settings allow.

        ``_resolve_backend`` hands them console anyway when ``SMTP_HOST`` is
        empty. Reporting that as a success is the same lie arriving through a
        different door, and this one is told to someone who explicitly asked
        for mail to leave.
        """
        settings = _production(email_backend="smtp", smtp_host="")

        backend = _resolve_backend(settings)
        result = await backend.send(_message())

        assert isinstance(backend, ConsoleEmailBackend)
        assert result.ok is False

    @pytest.mark.asyncio
    async def test_development_keeps_the_zero_config_success(self) -> None:
        """The stated non-goal: a fresh checkout must behave exactly as before.

        ``app.cli`` defaults ``APP_ENV`` to ``development``, so this is the
        shape every ``make quickstart`` and every desktop build runs.
        """
        settings = _settings()
        assert settings.app_env == "development"
        assert "email_backend" not in settings.model_fields_set

        backend = _resolve_backend(settings)
        result = await backend.send(_message())

        assert result.ok is True
        assert result.reason == "logged"


class TestTheBootTimeReport:
    """The second observer: what the operator can read before anyone sends.

    The transport only speaks when a send is attempted, and by then the person
    waiting for the mail has already been told nothing is wrong. The boot line
    is the one an operator can act on in advance.
    """

    def test_unchosen_console_is_diagnosed_in_production(self) -> None:
        settings = _production()
        assert "email_backend" not in settings.model_fields_set

        problem = diagnose_email_config(settings)

        assert problem is not None, "the deployment shape that shipped silently is still silent"
        # Naming the setting is not enough; the line has to carry the
        # consequence and the value that fixes it, or it reads as noise and
        # gets filtered out along with everything else at this level.
        assert "EMAIL_BACKEND" in problem
        assert "EMAIL_BACKEND=smtp" in problem

    def test_chosen_console_is_not_diagnosed(self) -> None:
        """One input apart from the test above, and it must answer the opposite."""
        settings = _production(email_backend="console")

        assert diagnose_email_config(settings) is None

    def test_development_is_not_diagnosed(self) -> None:
        assert diagnose_email_config(_settings()) is None

    def test_startup_logs_the_unchosen_case_at_error(
        self,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        with caplog.at_level(logging.DEBUG, logger="app.core.email.service"):
            report_email_config_at_startup(_production())

        errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
        assert errors, "the boot log said nothing about a deployment that cannot send mail"
        assert "EMAIL_BACKEND" in errors[0].getMessage()

    def test_startup_says_nothing_when_the_operator_chose_console(
        self,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        with caplog.at_level(logging.DEBUG, logger="app.core.email.service"):
            report_email_config_at_startup(_production(email_backend="console"))

        assert caplog.records == []

    def test_startup_says_nothing_in_development(
        self,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        with caplog.at_level(logging.DEBUG, logger="app.core.email.service"):
            report_email_config_at_startup(_settings())

        assert caplog.records == []
