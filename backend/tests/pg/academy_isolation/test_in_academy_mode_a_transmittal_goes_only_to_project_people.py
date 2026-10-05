# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""PG: in academy mode a transmittal goes only to project people.

A transmittal recipient may be a platform user, named by id in the request
body, and issuing the transmittal sends each of them an in-app "Transmittal
issued to you" with its number and subject. Only the transmittal's own project
was checked, so on an academy box a learner could push their transmittals into
another learner's inbox. In academy mode create, update and add-recipient
refuse a user outside the project (422 ``user_not_in_project``), issuing
notifies only recipients still in the project, and the notification carries
the project so the backstop drops one addressed outside it. A recipient named
only by name and email is stored as text and never notified, as before.

Gated by ``OE_TEST_DB=pg`` (see conftest).
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from app.core.academy_isolation import USER_NOT_IN_PROJECT
from app.core.events import Event
from app.modules.notifications import events as notification_events
from app.modules.notifications.models import Notification
from app.modules.transmittals.models import Transmittal
from app.modules.transmittals.schemas import ItemCreate, RecipientCreate, TransmittalCreate, TransmittalUpdate
from app.modules.transmittals.service import TransmittalService
from tests.pg.academy_isolation.rows import add_member, make_project, make_user
from tests.pg.tender_award_fixtures import _NonCommittingSession

pytestmark = [pytest.mark.asyncio, pytest.mark.tenant_isolation]

ISSUED = "transmittal.issued"


async def _setup(session):
    alice = await make_user(session, name="Alice")
    bob = await make_user(session, name="Bob")
    carol = await make_user(session, name="Carol")
    project = await make_project(session, alice)
    await add_member(session, project, carol)
    return project, alice, bob, carol


def _create(project, *people) -> TransmittalCreate:
    return TransmittalCreate(
        project_id=project.id,
        subject="Structural drawings rev C",
        purpose_code="for_review",
        recipients=[RecipientCreate(recipient_user_id=p.id) for p in people]
        + [RecipientCreate(recipient_name="Site office", recipient_email="site@example.test")],
        items=[ItemCreate(item_number=1, description="S-101")],
    )


def _issued_to(events) -> list[str]:
    return [data["recipient_user_id"] for name, data in events if name == ISSUED]


def _refused(caught) -> None:
    assert caught.value.status_code == 422
    assert caught.value.detail["error"] == USER_NOT_IN_PROJECT


async def _count(session, project) -> int:
    stmt = select(func.count(Transmittal.id)).where(Transmittal.project_id == project.id)
    return (await session.execute(stmt)).scalar_one()


async def test_academy_on_a_recipient_outside_the_project_is_422(pg_session, academy, events) -> None:
    academy(True)
    project, alice, bob, carol = await _setup(pg_session)
    service = TransmittalService(pg_session)

    with pytest.raises(HTTPException) as on_create:
        await service.create_transmittal(_create(project, carol, bob), user_id=str(alice.id))
    _refused(on_create)
    assert await _count(pg_session, project) == 0

    transmittal = await service.create_transmittal(_create(project, carol), user_id=str(alice.id))
    with pytest.raises(HTTPException) as on_add:
        await service.add_recipient(transmittal.id, RecipientCreate(recipient_user_id=bob.id))
    _refused(on_add)
    with pytest.raises(HTTPException) as on_update:
        await service.update_transmittal(
            transmittal.id,
            TransmittalUpdate(
                recipients=[RecipientCreate(recipient_user_id=carol.id), RecipientCreate(recipient_user_id=bob.id)]
            ),
        )
    _refused(on_update)

    await service.issue_transmittal(transmittal.id)
    assert _issued_to(events) == [str(carol.id)]


async def test_academy_on_issuing_skips_a_recipient_written_before_the_gate(pg_session, academy, events) -> None:
    academy(False)
    project, alice, bob, carol = await _setup(pg_session)
    service = TransmittalService(pg_session)
    transmittal = await service.create_transmittal(_create(project, carol, bob), user_id=str(alice.id))
    academy(True)

    await service.issue_transmittal(transmittal.id)

    assert _issued_to(events) == [str(carol.id)]


async def test_academy_on_the_issued_notification_names_its_project(pg_session, academy, monkeypatch) -> None:
    academy(True)
    project, _alice, bob, carol = await _setup(pg_session)
    monkeypatch.setattr(notification_events, "async_session_factory", lambda: _NonCommittingSession(pg_session))

    for person in (carol, bob):
        await notification_events._on_transmittal_issued(
            Event(
                name=ISSUED,
                data={
                    "transmittal_id": "6f1c1f9e-0000-4000-8000-000000000001",
                    "project_id": str(project.id),
                    "recipient_user_id": str(person.id),
                    "code": "TR-001",
                    "title": "Structural drawings rev C",
                },
            )
        )

    rows = (
        (await pg_session.execute(select(Notification).where(Notification.notification_type == "transmittal_issued")))
        .scalars()
        .all()
    )
    assert [r.user_id for r in rows] == [carol.id]
    assert rows[0].metadata_["project_id"] == str(project.id)


async def test_academy_off_unchanged(pg_session, academy, events) -> None:
    academy(False)
    project, alice, bob, carol = await _setup(pg_session)
    service = TransmittalService(pg_session)

    transmittal = await service.create_transmittal(_create(project, carol, bob), user_id=str(alice.id))
    other = await service.create_transmittal(_create(project, carol), user_id=str(alice.id))
    added = await service.add_recipient(other.id, RecipientCreate(recipient_user_id=bob.id))
    assert added.recipient_user_id == bob.id
    await service.issue_transmittal(transmittal.id)

    assert sorted(_issued_to(events)) == sorted([str(carol.id), str(bob.id)])
