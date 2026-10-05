# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""PG: in academy mode a submittal reviewer must be in the project (gate E3).

``reviewer_id``, ``approver_id`` and ``ball_in_court`` are user ids from the
request body. Submitting moves the ball to the reviewer and publishes
``submittal.submitted``, which notifies them, and every response resolved the
ball-in-court id to that user's name whoever they were. On an academy box one
learner could name another as reviewer, ping them, and read their name back.
In academy mode create and update refuse a person outside the project with 422
``user_not_in_project``, and the name lookup only names people in the project.

Gated by ``OE_TEST_DB=pg`` (see conftest).
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.core.academy_isolation import USER_NOT_IN_PROJECT
from app.modules.submittals.models import Submittal
from app.modules.submittals.router import get_submittal, submit_submittal
from app.modules.submittals.schemas import SubmittalCreate, SubmittalUpdate
from app.modules.submittals.service import SubmittalService
from tests.pg.academy_isolation.rows import add_member, make_project, make_user

pytestmark = [pytest.mark.asyncio, pytest.mark.tenant_isolation]

SUBMITTED = "submittal.submitted"


async def _setup(session):
    alice = await make_user(session, name="Alice Owner")
    bob = await make_user(session, name="Bob Outsider")
    carol = await make_user(session, name="Carol Member")
    project = await make_project(session, alice)
    await add_member(session, project, carol)
    return project, alice, bob, carol


def _create(project, **people) -> SubmittalCreate:
    return SubmittalCreate(project_id=project.id, title="Curtain wall", submittal_type="shop_drawing", **people)


async def _legacy_row(session, project, alice, bob) -> Submittal:
    """A submittal whose ball sits with an outsider, written past the service."""
    row = Submittal(
        project_id=project.id,
        submittal_number="SUB-900",
        title="Legacy",
        submittal_type="shop_drawing",
        status="submitted",
        ball_in_court=str(bob.id),
        created_by=str(alice.id),
    )
    session.add(row)
    await session.flush()
    return row


def _refused(caught) -> None:
    assert caught.value.status_code == 422
    assert caught.value.detail["error"] == USER_NOT_IN_PROJECT


async def test_reviewer_outside_is_422(pg_session, academy, events) -> None:
    academy(True)
    project, alice, bob, _carol = await _setup(pg_session)
    service = SubmittalService(pg_session)

    for field in ("reviewer_id", "approver_id", "ball_in_court"):
        with pytest.raises(HTTPException) as caught:
            await service.create_submittal(_create(project, **{field: str(bob.id)}), user_id=str(alice.id))
        _refused(caught)

    sub = await service.create_submittal(_create(project), user_id=str(alice.id))
    for field in ("reviewer_id", "approver_id", "ball_in_court"):
        with pytest.raises(HTTPException) as caught:
            await service.update_submittal(sub.id, SubmittalUpdate(**{field: str(bob.id)}))
        _refused(caught)

    await submit_submittal(sub.id, session=pg_session, user_id=str(alice.id), service=service)
    assert all(data["reviewer_id"] != str(bob.id) for name, data in events if name == SUBMITTED)


async def test_names_of_outsiders_not_resolved(pg_session, academy, events) -> None:
    academy(True)
    project, alice, bob, _carol = await _setup(pg_session)
    row = await _legacy_row(pg_session, project, alice, bob)

    resp = await get_submittal(row.id, session=pg_session, user_id=str(alice.id), service=SubmittalService(pg_session))
    assert resp.ball_in_court == str(bob.id)
    assert resp.ball_in_court_name is None


async def test_academy_on_a_project_member_can_review(pg_session, academy, events) -> None:
    academy(True)
    project, alice, _bob, carol = await _setup(pg_session)
    service = SubmittalService(pg_session)

    sub = await service.create_submittal(
        _create(project, reviewer_id=str(carol.id), approver_id=str(alice.id)), user_id=str(alice.id)
    )
    await service.update_submittal(sub.id, SubmittalUpdate(approver_id=str(carol.id)))
    resp = await submit_submittal(sub.id, session=pg_session, user_id=str(alice.id), service=service)
    assert resp.ball_in_court == str(carol.id)
    assert resp.ball_in_court_name == "Carol Member"
    assert [d["reviewer_id"] for n, d in events if n == SUBMITTED] == [str(carol.id)]


async def test_academy_off_unchanged(pg_session, academy, events) -> None:
    academy(False)
    project, alice, bob, _carol = await _setup(pg_session)
    service = SubmittalService(pg_session)

    sub = await service.create_submittal(
        _create(project, reviewer_id=str(bob.id), approver_id=str(bob.id)), user_id=str(alice.id)
    )
    await service.update_submittal(sub.id, SubmittalUpdate(ball_in_court=str(bob.id)))
    resp = await submit_submittal(sub.id, session=pg_session, user_id=str(alice.id), service=service)
    assert resp.ball_in_court_name == "Bob Outsider"
    assert [d["reviewer_id"] for n, d in events if n == SUBMITTED] == [str(bob.id)]

    row = await _legacy_row(pg_session, project, alice, bob)
    legacy = await get_submittal(row.id, session=pg_session, user_id=str(alice.id), service=service)
    assert legacy.ball_in_court_name == "Bob Outsider"
