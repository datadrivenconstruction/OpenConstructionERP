# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""PG: in academy mode a clash is assigned only inside the project.

A clash's ``assigned_to`` is a free string from the request body, from the bulk
triage toolbar and from an imported BCF topic. The notifications it triggers
already carry the project, so the backstop drops a stray one; but the stored
value travels on: the punch-list bridge copies it onto a punch item, where the
party-name resolver prints the person's name and the deadlines sweeper mails
them once the item is overdue. In academy mode an assignee id outside the
project is refused on the single and the bulk edit (422 ``user_not_in_project``)
and skipped on a BCF import. A typed-in name or an email, which is what BCF
tools write, is still accepted. A mention of someone outside the project was
already dropped by the notification backstop; that is pinned here too.

Gated by ``OE_TEST_DB=pg`` (see conftest).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.core.academy_isolation import USER_NOT_IN_PROJECT
from app.modules.bcf.bcf_xml import ParsedTopic, build_bcfzip
from app.modules.clash.models import ClashResult, ClashRun
from app.modules.clash.service import ClashService
from app.modules.notifications.models import Notification
from tests.pg.academy_isolation.rows import add_member, make_project, make_user

pytestmark = [pytest.mark.asyncio, pytest.mark.tenant_isolation]


async def _setup(session):
    alice = await make_user(session, name="Alice")
    bob = await make_user(session, name="Bob")
    carol = await make_user(session, name="Carol")
    project = await make_project(session, alice)
    await add_member(session, project, carol)
    run = ClashRun(
        project_id=project.id,
        name="Federated run",
        model_ids=[],
        clash_type="hard",
        tolerance_m=0.01,
        clearance_m=0.0,
        mode="cross_discipline",
        status="completed",
        element_count=0,
        total_clashes=2,
        summary={},
        rules=[],
        spatial_grid_mm=500,
        created_by=str(alice.id),
    )
    session.add(run)
    await session.flush()
    rows = []
    for tag in ("one", "two"):
        row = ClashResult(
            run_id=run.id,
            a_element_id=uuid.uuid4(),
            b_element_id=uuid.uuid4(),
            a_stable_id=f"A-{tag}",
            b_stable_id=f"B-{tag}",
            a_model_id=uuid.uuid4(),
            b_model_id=uuid.uuid4(),
            clash_type="hard",
            penetration_m=0.05,
            distance_m=0.0,
            cx=1.0,
            cy=2.0,
            cz=3.0,
            status="new",
            severity="medium",
            signature=uuid.uuid4().hex[:16],
            bcf_topic_guid=str(uuid.uuid4()),
        )
        session.add(row)
        rows.append(row)
    await session.flush()
    return project, run, rows, alice, bob, carol


def _refused(caught) -> None:
    assert caught.value.status_code == 422
    assert caught.value.detail["error"] == USER_NOT_IN_PROJECT


async def _update(session, project, run, row, actor, **fields):
    return await ClashService(session).update_result(
        project.id, run.id, row.id, new_status=None, actor=str(actor.id), **fields
    )


def _bcf(project, row, assignee: str) -> bytes:
    topic = ParsedTopic(
        guid=row.bcf_topic_guid,
        title="Clash",
        description="",
        topic_type="Clash",
        topic_status="Active",
        assigned_to=assignee,
        creation_date=datetime(2026, 10, 1, 9, 0, 0, tzinfo=UTC),
        creation_author="coordinator@example.test",
        comments=[],
    )
    return build_bcfzip(version="2.1", project_id=str(project.id), project_name="Course", topics=[topic])


async def test_academy_on_a_clash_cannot_be_assigned_outside_the_project(pg_session, academy, events) -> None:
    academy(True)
    project, run, rows, alice, bob, _carol = await _setup(pg_session)

    with pytest.raises(HTTPException) as single:
        await _update(pg_session, project, run, rows[0], alice, assigned_to=str(bob.id))
    _refused(single)
    with pytest.raises(HTTPException) as bulk:
        await ClashService(pg_session).bulk_update_results(
            project.id, run.id, [r.id for r in rows], assigned_to=str(bob.id), actor=str(alice.id)
        )
    _refused(bulk)
    for row in rows:
        await pg_session.refresh(row)
        assert row.assigned_to is None


async def test_academy_on_a_bcf_import_skips_an_outside_assignee(pg_session, academy, events) -> None:
    academy(True)
    project, run, rows, alice, bob, _carol = await _setup(pg_session)

    matched, _unmatched, _errors = await ClashService(pg_session).import_bcf(
        project.id, run.id, _bcf(project, rows[0], str(bob.id)), actor=str(alice.id)
    )

    assert matched == 1
    await pg_session.refresh(rows[0])
    assert rows[0].assigned_to is None


async def test_academy_on_members_names_and_emails_still_work(pg_session, academy, events) -> None:
    academy(True)
    project, run, rows, alice, _bob, carol = await _setup(pg_session)
    service = ClashService(pg_session)

    await _update(pg_session, project, run, rows[0], alice, assigned_to=str(carol.id))
    await service.bulk_update_results(project.id, run.id, [rows[1].id], assigned_to="MEP lead", actor=str(alice.id))
    await service.import_bcf(project.id, run.id, _bcf(project, rows[0], "mep@example.test"), actor=str(alice.id))
    await pg_session.refresh(rows[0])
    await pg_session.refresh(rows[1])
    assert rows[0].assigned_to == "mep@example.test"
    assert rows[1].assigned_to == "MEP lead"


async def test_academy_on_a_mention_outside_the_project_notifies_nobody(pg_session, academy, events) -> None:
    academy(True)
    project, run, rows, alice, bob, carol = await _setup(pg_session)

    await _update(
        pg_session,
        project,
        run,
        rows[0],
        alice,
        assigned_to=None,
        add_comment={"text": f"<at>{bob.id}</at> and <at>{carol.id}</at> please check", "author_id": str(alice.id)},
    )

    rows_for = {
        n.user_id
        for n in (
            await pg_session.execute(select(Notification).where(Notification.notification_type == "clash_mention"))
        )
        .scalars()
        .all()
    }
    assert rows_for == {carol.id}


async def test_academy_off_unchanged(pg_session, academy, events) -> None:
    academy(False)
    project, run, rows, alice, bob, _carol = await _setup(pg_session)
    service = ClashService(pg_session)

    await _update(pg_session, project, run, rows[0], alice, assigned_to=str(bob.id))
    await service.bulk_update_results(project.id, run.id, [rows[1].id], assigned_to=str(bob.id), actor=str(alice.id))
    await pg_session.refresh(rows[0])
    await pg_session.refresh(rows[1])
    assert rows[0].assigned_to == str(bob.id)
    assert rows[1].assigned_to == str(bob.id)

    other = str(uuid.uuid4())
    await service.import_bcf(project.id, run.id, _bcf(project, rows[0], other), actor=str(alice.id))
    await pg_session.refresh(rows[0])
    assert rows[0].assigned_to == other
