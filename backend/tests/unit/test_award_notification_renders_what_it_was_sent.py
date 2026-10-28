# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The award notification renders the values its publisher actually sent.

A subscriber that reads a key its publisher does not emit says nothing about
it. ``str(data.get("award_amount") or "")`` yields an empty string, the
notification is delivered anyway, and the only place the fault is visible is
the sentence a person eventually reads: an award notice with a blank where the
money should be. No exception, no log line, nothing red.

This pins the pairing rather than either side of it, because each side is
correct alone. The publisher's half is asserted in
``test_bid_management.test_the_award_payload_carries_what_its_notification_subscriber_reads``;
the payload used here is that same published contract, written out so the two
tests fail for different reasons when they fail.

Note what is deliberately NOT here: ``winner_user_id``. A ``Bidder`` is an
external company with no user id in the schema, so the winning bidder is not
reachable through in-app notifications and the handler resolves two recipients
rather than three. See the note on ``_on_bid_awarded``.
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import patch

import pytest

# The payload ``bid_management`` publishes for an award, with the two people it
# can name. The awarding user and the package owner are different on purpose:
# a single id would let a handler that only ever reads one of them pass.
_PACKAGE_ID = str(uuid.uuid4())
_AWARD_EVENT = {
    "package_id": _PACKAGE_ID,
    "project_id": str(uuid.uuid4()),
    "awarded_bidder_id": str(uuid.uuid4()),
    "awarded_amount": "9000.00",
    "currency": "EUR",
    "buyer_user_id": "owner-1",
    "actor_id": "awarder-7",
    "package_name": "Groundworks and piling",
}


async def _run_award_subscriber(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Run ``_on_bid_awarded`` against *data*, returning the notifications sent."""
    from app.core.events import Event
    from app.modules.notifications import _wave23_subscribers as subs

    sent: list[dict[str, Any]] = []

    async def _capture(**kwargs: Any) -> None:
        sent.append(kwargs)

    with patch.object(subs, "_notify", _capture):
        await subs._on_bid_awarded(Event(name="bid_management.package.awarded", data=data))
    return sent


@pytest.mark.asyncio
async def test_the_award_notification_names_the_package_and_the_amount() -> None:
    sent = await _run_award_subscriber(dict(_AWARD_EVENT))

    # Both resolvable recipients, in the order the handler reads them:
    # buyer_user_id (the package owner) before actor_id (whoever awarded it).
    assert [n["user_id"] for n in sent] == ["owner-1", "awarder-7"]

    for notification in sent:
        context = notification["body_context"]
        assert context["amount"] == "9000.00", "the amount read a key the publisher does not send"
        assert context["package"] == "Groundworks and piling"


@pytest.mark.asyncio
async def test_an_award_with_no_recipient_notifies_nobody_rather_than_failing() -> None:
    """The failure mode this whole area exists for, pinned as behaviour.

    Stripping the recipients leaves a payload that is still valid and still
    describes a real award. The handler resolves nobody and returns. That it
    stays quiet is correct - it is why the defect survived every test - so what
    is worth asserting is that quiet means zero notifications and not one
    addressed to nobody.
    """
    starved = {k: v for k, v in _AWARD_EVENT.items() if k not in {"buyer_user_id", "actor_id"}}

    sent = await _run_award_subscriber(starved)

    assert sent == []
