# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The SMTP transport refuses domains reserved by RFC 2606 / RFC 6761.

Nothing on ``.invalid``, ``.test``, ``.example``, ``.localhost`` or the
``example.com/net/org`` names can receive mail. Handing such a message to
the relay costs a bounce or a deferral on the account whose sending was
already revoked twice for bounces, and fixture data, demo installs and
placeholder form input are where these addresses come from.

The guard sits in ``SmtpEmailBackend`` and not in ``EmailService``: only
the real transport can earn a bounce, and the memory and console backends
must keep accepting the ``example.com`` addresses the test suite is built on.
"""

from __future__ import annotations

import smtplib
from unittest.mock import patch

import pytest

from app.config import Settings
from app.core.demo_accounts import is_reserved_mail_domain
from app.core.email.base import EmailMessage
from app.core.email.smtp import SmtpEmailBackend


def _backend() -> SmtpEmailBackend:
    settings = Settings(  # type: ignore[call-arg]
        smtp_host="127.0.0.1",
        smtp_port=587,
        smtp_user="",
        smtp_password="",
        smtp_from="info@datadrivenconstruction.io",
        smtp_tls=True,
    )
    return SmtpEmailBackend(settings)


def _message(to: str) -> EmailMessage:
    return EmailMessage(to=to, subject="Reset your password", html_body="<p>link</p>")


RESERVED = [
    "demo@openconstructionerp.invalid",
    "someone@site.test",
    "user@corp.example",
    "root@localhost",
    "dev@box.localhost",
    "admin@example.com",
    "admin@EXAMPLE.ORG",
    "x@mail.example.net",
    "  padded@example.com  ",
    "trailing@example.com.",
]

LOOKALIKES = [
    "site.manager@example-contractor.com",
    "a@myexample.com",
    "b@test.de",
    "c@invalid.com",
    "d@testing.io",
]


@pytest.mark.parametrize("address", RESERVED)
@pytest.mark.asyncio
async def test_a_reserved_domain_is_refused_before_a_socket_opens(address: str) -> None:
    with patch.object(smtplib, "SMTP", side_effect=AssertionError("must not connect")) as smtp:
        result = await _backend().send(_message(address))

    assert result.ok is False
    assert "reserved" in result.reason
    smtp.assert_not_called()


@pytest.mark.parametrize("address", RESERVED)
def test_every_reserved_example_is_recognised(address: str) -> None:
    assert is_reserved_mail_domain(address) is True


@pytest.mark.parametrize("address", LOOKALIKES)
def test_a_real_domain_that_only_resembles_a_reserved_one_is_not_caught(address: str) -> None:
    """Without this half, a guard that refuses everything would pass too."""
    assert is_reserved_mail_domain(address) is False


@pytest.mark.asyncio
async def test_a_lookalike_reaches_the_relay() -> None:
    with patch.object(smtplib, "SMTP", side_effect=ConnectionRefusedError("no relay in tests")) as smtp:
        result = await _backend().send(_message("site.manager@example-contractor.com"))

    smtp.assert_called_once()
    assert "reserved" not in (result.reason or "")


def test_is_reserved_mail_domain_handles_empty_and_malformed_input() -> None:
    assert is_reserved_mail_domain(None) is False
    assert is_reserved_mail_domain("") is False
    assert is_reserved_mail_domain("no-at-sign") is False
    assert is_reserved_mail_domain("x@invalid") is True
