# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The transport refuses the seeded demo logins.

These three addresses are logins on a domain we own where exactly one
mailbox exists, so every message addressed to them is refused by the
receiving server and returns as a hard bounce against our own sending
reputation. In September 2026 a background sweeper nudged the same
permanently overdue demo items twice a day, every nudge bounced, and the
mail host disabled outbound sending for the entire account.

The test is written against ``EmailService.send`` rather than against the
notification dispatcher on purpose: six modules reach the transport
directly, so a guard proven on one of seven paths proves nothing about the
other six.
"""

from __future__ import annotations

import pytest

from app.core.demo_accounts import DEMO_ACCOUNT_EMAILS, is_demo_account
from app.core.email.base import EmailMessage
from app.core.email.memory import MemoryEmailBackend
from app.core.email.service import EmailService


def _message(to: str) -> EmailMessage:
    return EmailMessage(to=to, subject="Overdue item", html_body="<p>nudge</p>")


@pytest.mark.parametrize("address", sorted(DEMO_ACCOUNT_EMAILS))
@pytest.mark.asyncio
async def test_a_demo_login_is_refused_and_nothing_is_handed_to_the_backend(address: str) -> None:
    backend = MemoryEmailBackend()
    service = EmailService(backend)

    result = await service.send(_message(address))

    assert result.ok is False
    assert "demo login" in result.reason
    assert backend.sent == [], "the message must not reach the transport at all"


@pytest.mark.asyncio
async def test_case_and_padding_do_not_get_a_message_past_the_guard() -> None:
    """The address that slips through a hand-written comparison is this one."""
    backend = MemoryEmailBackend()
    service = EmailService(backend)

    result = await service.send(_message("  Demo@OpenConstructionERP.com  "))

    assert result.ok is False
    assert backend.sent == []


@pytest.mark.asyncio
async def test_an_ordinary_recipient_still_goes_out() -> None:
    """The guard must be narrow: a real address is untouched.

    Without this half the test would pass just as well against a transport
    that refuses everything, which is the failure a one-sided guard test
    cannot tell apart from success.
    """
    backend = MemoryEmailBackend()
    service = EmailService(backend)

    result = await service.send(_message("site.manager@example-contractor.com"))

    assert result.ok is True
    assert len(backend.sent) == 1
    assert backend.sent[0].to == "site.manager@example-contractor.com"


def test_is_demo_account_says_no_to_a_lookalike() -> None:
    """A neighbouring address on the same domain is not a demo login."""
    assert is_demo_account("demo@openconstructionerp.com") is True
    assert is_demo_account("demo.user@openconstructionerp.com") is False
    assert is_demo_account("info@openconstructionerp.com") is False
    assert is_demo_account(None) is False
    assert is_demo_account("") is False
