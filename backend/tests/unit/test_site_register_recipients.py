# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Who a site register notification goes to, and who it does not.

Three rules, each a way a notification system loses the trust of the people it
is for: nobody is told about their own action, nobody is told twice because
they hold two roles, and nobody is invented, so a record that names its holder
is not also sprayed across the project's managers.

The database-backed halves (which ids are active accounts, who manages a
project) are replaced here; ``tests/pg`` runs them for real.
"""

from __future__ import annotations

import uuid

import pytest

from app.modules.deadlines import sweeper
from app.modules.notifications import _site_register_subscribers as sr
from app.modules.notifications import events as notification_events
from app.modules.notifications.service import KNOWN_EVENT_TYPES

_A, _B, _C = (uuid.uuid4() for _ in range(3))


def test_the_actor_is_never_a_recipient() -> None:
    assert sr.pick_recipients([_A, _B], actor=_A) == [_B]
    # The record holds ids as strings on some columns and as UUIDs on others.
    assert sr.pick_recipients([str(_A), _B], actor=str(_A).upper()) == [_B]
    assert sr.pick_recipients([_A], actor=_A) == []


def test_one_person_in_two_roles_is_told_once() -> None:
    assert sr.pick_recipients([_A, str(_A), _B, _A]) == [_A, _B]


def test_a_role_label_or_an_empty_column_is_nobody() -> None:
    assert sr.pick_recipients([None, "", "Engineer", "not-a-uuid", _C]) == [_C]
    assert sr.pick_recipients([]) == []
    # An actor that is not a user id excludes no one.
    assert sr.pick_recipients([_A], actor="system") == [_A]


@pytest.fixture
def project_with_managers(monkeypatch: pytest.MonkeyPatch) -> list[uuid.UUID]:
    """Every id is an active account; the project is managed by A and B."""
    managers = [_A, _B]

    async def existing(_session: object, user_ids: list[uuid.UUID]) -> list[uuid.UUID]:
        return list(user_ids)

    async def manager_ids(_session: object, _project_id: uuid.UUID) -> list[uuid.UUID]:
        return list(managers)

    monkeypatch.setattr(sr, "_existing", existing)
    monkeypatch.setattr(sweeper, "_project_manager_ids", manager_ids)
    return managers


@pytest.mark.asyncio
async def test_a_named_holder_is_told_and_the_managers_are_not(project_with_managers: list[uuid.UUID]) -> None:
    picked = await sr._holder_or_managers(None, [str(_C)], uuid.uuid4(), actor=_A)
    assert picked == [_C]


@pytest.mark.asyncio
async def test_a_record_naming_nobody_falls_back_to_the_managers_without_the_actor(
    project_with_managers: list[uuid.UUID],
) -> None:
    assert await sr._holder_or_managers(None, [None], uuid.uuid4(), actor=_A) == [_B]
    assert await sr._holder_or_managers(None, ["Engineer"], uuid.uuid4(), actor=None) == [_A, _B]


@pytest.mark.asyncio
async def test_a_holder_who_just_acted_tells_nobody(project_with_managers: list[uuid.UUID]) -> None:
    """The record did name someone, so the managers are not a substitute."""
    assert await sr._holder_or_managers(None, [_C], uuid.uuid4(), actor=_C) == []


@pytest.mark.asyncio
async def test_a_holder_whose_account_is_gone_falls_back_to_the_managers(monkeypatch: pytest.MonkeyPatch) -> None:
    async def nobody(_session: object, _user_ids: list[uuid.UUID]) -> list[uuid.UUID]:
        return []

    async def manager_ids(_session: object, _project_id: uuid.UUID) -> list[uuid.UUID]:
        return [_B]

    monkeypatch.setattr(sr, "_existing", nobody)
    monkeypatch.setattr(sweeper, "_project_manager_ids", manager_ids)
    assert await sr._holder_or_managers(None, [_C], uuid.uuid4(), actor=_A) == [_B]


def test_an_approver_is_asked_once_per_submission_and_step() -> None:
    first = {"submitted_at": "2026-10-10T09:00:00", "step": 1}
    assert sr.already_asked([first], submitted_at="2026-10-10T09:00:00", step=1)
    # The same person approving step 2 of the same chain is a new request.
    assert not sr.already_asked([first], submitted_at="2026-10-10T09:00:00", step=2)
    # Rejected, reworked, submitted again: a new submission is asked afresh.
    assert not sr.already_asked([first], submitted_at="2026-10-12T14:00:00", step=1)
    assert not sr.already_asked([], submitted_at="2026-10-10T09:00:00", step=1)


def test_a_manager_told_on_submission_is_not_told_again_as_first_approver() -> None:
    on_submit = {"submitted_at": "2026-10-10T09:00:00", "step": 0}
    assert sr.already_asked([on_submit], submitted_at="2026-10-10T09:00:00", step=1)
    assert not sr.already_asked([on_submit], submitted_at="2026-10-10T09:00:00", step=2)


def test_payload_ids_compare_by_value_not_by_type() -> None:
    assert notification_events._same_user(_A, str(_A))
    assert notification_events._same_user(str(_A).upper(), _A)
    assert not notification_events._same_user(_A, _B)
    # Two missing ids are not "the same person".
    assert not notification_events._same_user(None, None)
    assert not notification_events._same_user("", "")


def test_the_three_register_events_are_subscribed_and_can_be_muted() -> None:
    subscribed = {name for name, _ in sr._SITE_REGISTER_SUBSCRIPTIONS}
    assert subscribed == {
        "variations.notify.request",
        "changeorders.notify.awaiting_approval",
        "changeorders.notify.decided",
    }
    listed = {entry["event_type"] for entry in KNOWN_EVENT_TYPES}
    # A preference can only be set on an event type the catalogue offers.
    for event_type in (
        "variations.notify.submitted",
        "variations.notify.approved",
        "variations.notify.rejected",
        "changeorders.notify.awaiting_approval",
        "changeorders.notify.approved",
        "changeorders.notify.rejected",
        "deadlines.correspondence.approaching",
    ):
        assert event_type in listed, event_type
    assert ("submittal.reviewed", notification_events._on_submittal_reviewed) in notification_events._SUBSCRIPTIONS
