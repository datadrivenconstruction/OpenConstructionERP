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

import re
from pathlib import Path

import pytest

from app.core.demo_accounts import (
    DEMO_ACCOUNT_EMAILS,
    NON_MAILBOX_LOGINS,
    is_demo_account,
    is_non_mailbox_login,
)
from app.core.email.base import EmailMessage
from app.core.email.memory import MemoryEmailBackend
from app.core.email.service import EmailService

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "app" / "scripts"


def _message(to: str) -> EmailMessage:
    return EmailMessage(to=to, subject="Overdue item", html_body="<p>nudge</p>")


@pytest.mark.parametrize("address", sorted(NON_MAILBOX_LOGINS))
@pytest.mark.asyncio
async def test_a_seeded_login_is_refused_and_nothing_is_handed_to_the_backend(address: str) -> None:
    backend = MemoryEmailBackend()
    service = EmailService(backend)

    result = await service.send(_message(address))

    assert result.ok is False
    assert "not a mailbox" in result.reason
    assert backend.sent == [], "the message must not reach the transport at all"


def test_every_address_a_seeder_registers_is_known_to_be_unmailable() -> None:
    """The guard's population must be the seeders, not a remembered list.

    A seeder creates its admin by POSTing a registration, so the account
    exists on any installation that ran one. Before this test the guard knew
    the three demo logins and not ``admin@openestimate.io``, which four
    seeders create, so that address was one overdue nudge away from the
    bounce that disabled outbound mail once already. Reading the constants
    out of the scripts means a new seeder cannot quietly add a fourth.
    """
    seeded = {}
    for script in sorted(SCRIPTS_DIR.glob("seed_*.py")):
        for m in re.finditer(r'^ADMIN_EMAIL\s*=\s*"([^"]+)"', script.read_text(encoding="utf-8"), re.M):
            seeded[m.group(1)] = script.name

    assert seeded, f"no seeder declared an ADMIN_EMAIL under {SCRIPTS_DIR}, so this test proves nothing"

    unguarded = {addr: name for addr, name in seeded.items() if not is_non_mailbox_login(addr)}
    assert not unguarded, f"a seeder registers an address the mail guard does not know: {unguarded}"


def test_the_seeder_admin_cannot_use_the_passwordless_demo_login() -> None:
    """The two sets are not interchangeable, and this pins that.

    ``DEMO_ACCOUNT_EMAILS`` is the whitelist of ``/auth/demo-login``, which
    hands out a session without a password. ``admin@openestimate.io`` has to
    be unmailable without becoming password-free, so it belongs in one set
    and not the other. Folding them back together would be a quiet
    privilege escalation, which is why this asserts in both directions.
    """
    assert is_non_mailbox_login("admin@openestimate.io")
    assert not is_demo_account("admin@openestimate.io")
    assert DEMO_ACCOUNT_EMAILS < NON_MAILBOX_LOGINS, "the demo logins must stay a strict subset"


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
