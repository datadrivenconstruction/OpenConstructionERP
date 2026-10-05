# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""PG: the academy gates count project members exactly as project access does.

``app.core.academy_isolation`` answers "who is in this project" for a whole set
of ids at once instead of calling ``verify_project_access`` per id. These tests
hold the two answers together over every kind of person that guard knows (the
owner, a team member, an admin, an outsider, a malformed id) and over a project
that does not exist, so the set version cannot drift into a second definition.

Gated by ``OE_TEST_DB=pg`` (see conftest).
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException

from app.core.academy_isolation import (
    USER_NOT_IN_PROJECT,
    assert_users_can_access_project,
    filter_users_to_project,
)
from app.dependencies import verify_project_access
from tests.pg.academy_isolation.rows import add_member, make_project, make_user

pytestmark = pytest.mark.asyncio


async def _guard_lets_in(session, project_id: uuid.UUID, user_id: str) -> bool:
    try:
        await verify_project_access(project_id, user_id, session)
    except HTTPException as exc:
        assert exc.status_code == 404
        return False
    return True


async def _people(session):
    owner = await make_user(session, name="Owner")
    member = await make_user(session, name="Member")
    admin = await make_user(session, role="admin", name="Operator")
    outsider = await make_user(session, name="Outsider")
    project = await make_project(session, owner)
    await add_member(session, project, member)
    return project, {"owner": owner, "member": member, "admin": admin, "outsider": outsider}


@pytest.mark.tenant_isolation
async def test_membership_matches_verify_project_access_for_every_kind_of_person(pg_session, academy) -> None:
    academy(True)
    project, people = await _people(pg_session)
    missing_project = uuid.uuid4()

    for project_id in (project.id, missing_project):
        for label, user in people.items():
            expected = await _guard_lets_in(pg_session, project_id, str(user.id))
            got = await filter_users_to_project(pg_session, project_id, [user.id])
            assert (got == [user.id]) is expected, (
                f"{label} in {'missing' if project_id == missing_project else 'real'}"
            )

    # The guard answers 404 for a malformed id, and so does the gate.
    assert await _guard_lets_in(pg_session, project.id, "not-a-uuid") is False
    assert await filter_users_to_project(pg_session, project.id, ["not-a-uuid"]) == []
    # The sanity half: the parity loop above saw both answers.
    assert await _guard_lets_in(pg_session, project.id, str(people["member"].id)) is True
    assert await _guard_lets_in(pg_session, project.id, str(people["outsider"].id)) is False


@pytest.mark.tenant_isolation
async def test_filter_keeps_the_order_and_the_types_it_was_given(pg_session, academy) -> None:
    academy(True)
    project, people = await _people(pg_session)
    given = [str(people["outsider"].id), str(people["member"].id), None, people["owner"].id]

    assert await filter_users_to_project(pg_session, project.id, given) == [
        str(people["member"].id),
        people["owner"].id,
    ]


@pytest.mark.tenant_isolation
async def test_academy_on_naming_an_outsider_is_422(pg_session, academy) -> None:
    academy(True)
    project, people = await _people(pg_session)

    with pytest.raises(HTTPException) as caught:
        await assert_users_can_access_project(pg_session, project.id, [people["member"].id, people["outsider"].id])
    assert caught.value.status_code == 422
    assert caught.value.detail["error"] == USER_NOT_IN_PROJECT
    # The refusal does not tell an outsider apart from an id nobody has.
    with pytest.raises(HTTPException) as unknown:
        await assert_users_can_access_project(pg_session, project.id, [uuid.uuid4()])
    assert unknown.value.detail == caught.value.detail


@pytest.mark.tenant_isolation
async def test_academy_on_naming_insiders_and_nobody_passes(pg_session, academy) -> None:
    academy(True)
    project, people = await _people(pg_session)

    await assert_users_can_access_project(
        pg_session,
        project.id,
        [people["owner"].id, str(people["member"].id), people["admin"].id, None, ""],
    )
    await assert_users_can_access_project(pg_session, project.id, [])


@pytest.mark.tenant_isolation
async def test_academy_off_naming_an_outsider_is_unchanged(pg_session, academy) -> None:
    academy(False)
    project, people = await _people(pg_session)

    await assert_users_can_access_project(pg_session, project.id, [people["outsider"].id, "not-a-uuid"])
    given = [people["outsider"].id, "not-a-uuid", None]
    assert await filter_users_to_project(pg_session, project.id, given) == given
