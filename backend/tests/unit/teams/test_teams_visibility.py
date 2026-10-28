"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Restriction semantics: what a visibility row does, and what it cannot do.

``EntityVisibility`` is subtractive. A record with no row is open to everyone
who can reach its project; a record with rows is open to the named teams, plus
the project owner and system admins. These cases pin both halves, and the
boundary between them.

The access-control negatives live in ``test_teams_access_control.py``. What is
here is the behaviour an operations lead configures: restrict, widen, lift,
and read back who is left.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException

from app.modules.teams.access import assert_entity_not_hidden, hidden_entity_ids
from app.modules.teams.service import TeamService
from tests.unit.teams.conftest import (
    make_membership,
    make_project,
    make_team,
    make_user,
)

pytestmark = pytest.mark.asyncio


async def _project_with_two_teams(session):
    """An owner, a project, two teams with one member each, and a stranger."""
    owner = await make_user(session)
    insider = await make_user(session)
    outsider = await make_user(session)
    project = await make_project(session, owner.id)
    team_a = await make_team(session, project.id, name="Cost team", is_default=True)
    team_b = await make_team(session, project.id, name="Client side", sort_order=1)
    await make_membership(session, team_a.id, insider.id)
    await make_membership(session, team_b.id, outsider.id)
    return owner, insider, outsider, project, team_a, team_b


# ── The two states of a record ───────────────────────────────────────────────


async def test_a_record_with_no_restriction_is_hidden_from_nobody(session) -> None:
    """The default state. Nothing is opt-out; restriction is opt-in per record."""
    _owner, insider, outsider, project, _a, _b = await _project_with_two_teams(session)
    record = str(uuid.uuid4())

    for user in (insider, outsider):
        assert (
            await hidden_entity_ids(
                session,
                project_id=project.id,
                entity_type="document",
                entity_ids=[record],
                user_id=user.id,
            )
            == set()
        )


async def test_restricting_a_record_hides_it_from_everyone_outside_the_team(session) -> None:
    """The first row flips a record from open to narrowed.

    This is the whole feature in one assertion: the member of the named team
    keeps it, the member of the other team loses it.
    """
    owner, insider, outsider, project, team_a, _b = await _project_with_two_teams(session)
    record = str(uuid.uuid4())
    service = TeamService(session)
    await service.grant_visibility("document", record, team_a.id, actor_id=owner.id)

    kept = await hidden_entity_ids(
        session,
        project_id=project.id,
        entity_type="document",
        entity_ids=[record],
        user_id=insider.id,
    )
    lost = await hidden_entity_ids(
        session,
        project_id=project.id,
        entity_type="document",
        entity_ids=[record],
        user_id=outsider.id,
    )
    assert kept == set()
    assert lost == {record}


async def test_the_owner_and_the_admin_are_never_locked_out(session) -> None:
    """A restriction controls who ELSE may look, not who is accountable.

    Without the bypass, an owner could restrict a record to a team they are not
    on and lose their own project's record with no way back.
    """
    owner, _insider, _outsider, project, team_a, _b = await _project_with_two_teams(session)
    admin = await make_user(session, role="admin")
    record = str(uuid.uuid4())
    service = TeamService(session)
    await service.grant_visibility("boq", record, team_a.id, actor_id=owner.id)

    assert (
        await hidden_entity_ids(
            session,
            project_id=project.id,
            entity_type="boq",
            entity_ids=[record],
            user_id=owner.id,
            is_project_owner=True,
        )
        == set()
    )
    assert (
        await hidden_entity_ids(
            session,
            project_id=project.id,
            entity_type="boq",
            entity_ids=[record],
            user_id=admin.id,
            is_system_admin=True,
        )
        == set()
    )


async def test_adding_a_second_team_widens_within_the_project_only(session) -> None:
    """Two teams on one record means both may see it - and nobody else."""
    owner, insider, outsider, project, team_a, team_b = await _project_with_two_teams(session)
    third = await make_user(session)
    team_c = await make_team(session, project.id, name="Nobody", sort_order=2)
    await make_membership(session, team_c.id, third.id)

    record = str(uuid.uuid4())
    service = TeamService(session)
    await service.grant_visibility("document", record, team_a.id, actor_id=owner.id)
    await service.grant_visibility("document", record, team_b.id, actor_id=owner.id)

    async def hidden_for(user_id):
        return await hidden_entity_ids(
            session,
            project_id=project.id,
            entity_type="document",
            entity_ids=[record],
            user_id=user_id,
        )

    assert await hidden_for(insider.id) == set()
    assert await hidden_for(outsider.id) == set()
    assert await hidden_for(third.id) == {record}


async def test_lifting_the_last_restriction_returns_the_record_to_the_project(session) -> None:
    """Removing the final row is what makes a record open again.

    Not a special case in the code: "no rows" is the open state, so the
    round trip has to land exactly back on it.
    """
    owner, _insider, outsider, project, team_a, _b = await _project_with_two_teams(session)
    record = str(uuid.uuid4())
    service = TeamService(session)
    await service.grant_visibility("document", record, team_a.id, actor_id=owner.id)
    assert record in await hidden_entity_ids(
        session,
        project_id=project.id,
        entity_type="document",
        entity_ids=[record],
        user_id=outsider.id,
    )

    await service.revoke_visibility("document", record, team_a.id, actor_id=owner.id)
    assert (
        await hidden_entity_ids(
            session,
            project_id=project.id,
            entity_type="document",
            entity_ids=[record],
            user_id=outsider.id,
        )
        == set()
    )


async def test_deleting_a_team_releases_the_records_it_held(session) -> None:
    """A record restricted only to a deleted team must not stay stranded.

    The FK cascade does the work; this pins that it actually fires, because the
    alternative - orphan rows naming a team that no longer exists - would hide
    the record from everyone permanently.
    """
    owner, _insider, outsider, project, team_a, _b = await _project_with_two_teams(session)
    record = str(uuid.uuid4())
    service = TeamService(session)
    await service.grant_visibility("document", record, team_a.id, actor_id=owner.id)

    await service.delete_team(team_a.id, actor_id=owner.id)

    assert (
        await hidden_entity_ids(
            session,
            project_id=project.id,
            entity_type="document",
            entity_ids=[record],
            user_id=outsider.id,
        )
        == set()
    )


# ── Set-at-once, the operation the UI performs ───────────────────────────────


async def test_set_entity_visibility_replaces_the_whole_list(session) -> None:
    """Ticking boxes and saving once is a replace, not a merge."""
    owner, insider, outsider, project, team_a, team_b = await _project_with_two_teams(session)
    record = str(uuid.uuid4())
    service = TeamService(session)

    state = await service.set_entity_visibility(project.id, "document", record, [team_a.id], actor_id=owner.id)
    assert state.restricted is True
    assert [t.team_id for t in state.teams] == [team_a.id]

    # Replacing with the other team must drop the first one, not add to it.
    state = await service.set_entity_visibility(project.id, "document", record, [team_b.id], actor_id=owner.id)
    assert [t.team_id for t in state.teams] == [team_b.id]
    assert record in await hidden_entity_ids(
        session,
        project_id=project.id,
        entity_type="document",
        entity_ids=[record],
        user_id=insider.id,
    )
    assert (
        await hidden_entity_ids(
            session,
            project_id=project.id,
            entity_type="document",
            entity_ids=[record],
            user_id=outsider.id,
        )
        == set()
    )


async def test_set_entity_visibility_with_an_empty_list_lifts_the_restriction(session) -> None:
    """The UI's "visible to everyone on the project" option."""
    owner, _insider, outsider, project, team_a, _b = await _project_with_two_teams(session)
    record = str(uuid.uuid4())
    service = TeamService(session)
    await service.set_entity_visibility(project.id, "document", record, [team_a.id], actor_id=owner.id)

    state = await service.set_entity_visibility(project.id, "document", record, [], actor_id=owner.id)
    assert state.restricted is False
    assert state.teams == []
    assert (
        await hidden_entity_ids(
            session,
            project_id=project.id,
            entity_type="document",
            entity_ids=[record],
            user_id=outsider.id,
        )
        == set()
    )


async def test_setting_the_same_list_again_is_a_no_op(session) -> None:
    """Saving an unchanged form must not churn rows or emit a spurious audit."""
    owner, _insider, _outsider, project, team_a, _b = await _project_with_two_teams(session)
    record = str(uuid.uuid4())
    service = TeamService(session)
    first = await service.set_entity_visibility(project.id, "document", record, [team_a.id], actor_id=owner.id)
    rows_before = await service.list_entity_visibility("document", record, project_id=project.id)
    second = await service.set_entity_visibility(project.id, "document", record, [team_a.id], actor_id=owner.id)
    rows_after = await service.list_entity_visibility("document", record, project_id=project.id)

    assert first.teams == second.teams
    assert [r.id for r in rows_before] == [r.id for r in rows_after]


# ── Reads built on the restriction table ─────────────────────────────────────


async def test_describe_reports_teams_viewers_and_whether_it_is_enforced(session) -> None:
    """The visibility panel's payload.

    ``viewer_count`` deliberately excludes the owner and admins, so a zero is
    the honest "nobody on a team can open this" signal rather than a
    reassuring one.
    """
    owner, _insider, _outsider, project, team_a, _b = await _project_with_two_teams(session)
    record = str(uuid.uuid4())
    service = TeamService(session)
    await service.grant_visibility("document", record, team_a.id, actor_id=owner.id)

    state = await service.describe_entity_visibility(project.id, "document", record, actor_id=owner.id)
    assert state.restricted is True
    assert state.viewer_count == 1
    assert state.teams[0].name == "Cost team"
    assert state.teams[0].member_count == 1
    # No consumer subtracts documents yet, and the payload says so rather than
    # implying a lock that is not wired.
    assert state.enforced is False


async def test_describe_warns_the_caller_who_is_about_to_lose_the_record(session) -> None:
    """ "You are restricting this to teams you are not on" - before the save.

    Read off the same membership the resolver uses, so the warning and the
    filter cannot disagree. The owner never sees the warning, because
    ownership bypasses restrictions.
    """
    owner, insider, outsider, project, team_a, _b = await _project_with_two_teams(session)
    record = str(uuid.uuid4())
    service = TeamService(session)
    await service.grant_visibility("document", record, team_a.id, actor_id=owner.id)

    for actor, expected in ((insider, True), (outsider, False), (owner, True)):
        state = await service.describe_entity_visibility(project.id, "document", record, actor_id=actor.id)
        assert state.caller_can_see is expected, actor.email


async def test_the_sql_and_the_python_resolver_agree(session) -> None:
    """Two implementations of one rule must not drift.

    ``hidden_entity_ids_subquery`` is the form a list endpoint uses so it does
    not round-trip candidate ids into Python. It is a second encoding of the
    same rule, which is exactly the kind of pair that quietly diverges.
    """
    from sqlalchemy import literal, select, union_all

    from app.modules.teams.access import hidden_entity_ids_subquery

    owner, insider, outsider, project, team_a, team_b = await _project_with_two_teams(session)
    service = TeamService(session)
    only_a = str(uuid.uuid4())
    both = str(uuid.uuid4())
    open_record = str(uuid.uuid4())
    await service.grant_visibility("document", only_a, team_a.id, actor_id=owner.id)
    await service.grant_visibility("document", both, team_a.id, actor_id=owner.id)
    await service.grant_visibility("document", both, team_b.id, actor_id=owner.id)

    candidates = [only_a, both, open_record]
    # Stand the candidate ids up as rows so the subquery can be used the way a
    # list endpoint uses it: as a filter over ids the endpoint already has.
    candidate_rows = union_all(*[select(literal(c).label("entity_id")) for c in candidates]).subquery()

    for user in (insider, outsider):
        via_python = await hidden_entity_ids(
            session,
            project_id=project.id,
            entity_type="document",
            entity_ids=candidates,
            user_id=user.id,
        )
        via_sql = {
            row
            for (row,) in (
                await session.execute(
                    select(candidate_rows.c.entity_id).where(
                        candidate_rows.c.entity_id.in_(hidden_entity_ids_subquery(project.id, "document", user.id))
                    )
                )
            ).all()
        }
        assert via_python == via_sql, user.email

    # And the answers are the ones the arrangement calls for.
    assert await hidden_entity_ids(
        session,
        project_id=project.id,
        entity_type="document",
        entity_ids=candidates,
        user_id=outsider.id,
    ) == {only_a}


async def test_describe_reports_an_unrestricted_record_as_open(session) -> None:
    """An untouched record reads as open, with no teams and no viewers."""
    owner, _insider, _outsider, project, _a, _b = await _project_with_two_teams(session)
    service = TeamService(session)
    state = await service.describe_entity_visibility(project.id, "document", str(uuid.uuid4()), actor_id=owner.id)
    assert state.restricted is False
    assert state.teams == []
    assert state.viewer_count == 0


async def test_the_restriction_register_groups_by_record(session) -> None:
    """One line per record, listing every team that may see it."""
    owner, _insider, _outsider, project, team_a, team_b = await _project_with_two_teams(session)
    service = TeamService(session)
    shared = str(uuid.uuid4())
    solo = str(uuid.uuid4())
    await service.grant_visibility("document", shared, team_a.id, actor_id=owner.id)
    await service.grant_visibility("document", shared, team_b.id, actor_id=owner.id)
    await service.grant_visibility("boq", solo, team_b.id, actor_id=owner.id)

    register = await service.list_restricted_entities(project.id, actor_id=owner.id)
    by_id = {row.entity_id: row for row in register}
    assert set(by_id) == {shared, solo}
    assert sorted(by_id[shared].team_names) == ["Client side", "Cost team"]
    assert by_id[shared].viewer_count == 2
    assert by_id[solo].entity_type == "boq"

    filtered = await service.list_restricted_entities(project.id, entity_type="boq", actor_id=owner.id)
    assert [row.entity_id for row in filtered] == [solo]


async def test_the_access_matrix_counts_what_each_person_can_still_open(session) -> None:
    """The "who sees what" screen.

    Two restricted records, one team on each. Each member keeps one and loses
    one; the owner keeps both.
    """
    owner, insider, outsider, project, team_a, team_b = await _project_with_two_teams(session)
    await make_membership(session, team_a.id, owner.id, role="owner")
    service = TeamService(session)
    await service.grant_visibility("document", str(uuid.uuid4()), team_a.id, actor_id=owner.id)
    await service.grant_visibility("document", str(uuid.uuid4()), team_b.id, actor_id=owner.id)

    matrix = await service.build_access_matrix(project.id, actor_id=owner.id)
    assert matrix.restricted_record_count == 2
    by_user = {m.user_id: m for m in matrix.members}

    assert by_user[insider.id].visible_restricted_count == 1
    assert by_user[insider.id].hidden_restricted_count == 1
    assert by_user[outsider.id].visible_restricted_count == 1
    assert by_user[outsider.id].hidden_restricted_count == 1
    # The owner is on team A but keeps both because ownership bypasses.
    assert by_user[owner.id].is_project_owner is True
    assert by_user[owner.id].visible_restricted_count == 2
    assert by_user[owner.id].hidden_restricted_count == 0


# ── Guard rails on the write path ────────────────────────────────────────────


async def test_an_unknown_record_kind_is_refused(session) -> None:
    """A typo would write a restriction nothing enforces - a fail-open row.

    Rejecting at the edge is the only point where it is still fixable by the
    person typing it.
    """
    owner, _insider, _outsider, project, team_a, _b = await _project_with_two_teams(session)
    service = TeamService(session)
    with pytest.raises(HTTPException) as exc:
        await service.grant_visibility("documnet", str(uuid.uuid4()), team_a.id, actor_id=owner.id)
    assert exc.value.status_code == 422


async def test_restricting_the_same_record_to_the_same_team_twice_is_a_conflict(session) -> None:
    """409, not a duplicate row and not a silent success."""
    owner, _insider, _outsider, project, team_a, _b = await _project_with_two_teams(session)
    record = str(uuid.uuid4())
    service = TeamService(session)
    await service.grant_visibility("document", record, team_a.id, actor_id=owner.id)
    with pytest.raises(HTTPException) as exc:
        await service.grant_visibility("document", record, team_a.id, actor_id=owner.id)
    assert exc.value.status_code == 409


async def test_revoking_a_restriction_that_is_not_there_is_a_404(session) -> None:
    """A no-op must not report success, or the UI shows a lift that never happened."""
    owner, _insider, _outsider, project, team_a, _b = await _project_with_two_teams(session)
    service = TeamService(session)
    with pytest.raises(HTTPException) as exc:
        await service.revoke_visibility("document", str(uuid.uuid4()), team_a.id, actor_id=owner.id)
    assert exc.value.status_code == 404


async def test_assert_entity_not_hidden_raises_404_for_a_restricted_record(session) -> None:
    """The detail-endpoint companion answers 404, never 403."""
    owner, insider, outsider, project, team_a, _b = await _project_with_two_teams(session)
    record = str(uuid.uuid4())
    service = TeamService(session)
    await service.grant_visibility("document", record, team_a.id, actor_id=owner.id)

    # Permitted reader: no exception.
    await assert_entity_not_hidden(
        session,
        project_id=project.id,
        entity_type="document",
        entity_id=record,
        user_id=insider.id,
    )
    with pytest.raises(HTTPException) as exc:
        await assert_entity_not_hidden(
            session,
            project_id=project.id,
            entity_type="document",
            entity_id=record,
            user_id=outsider.id,
        )
    assert exc.value.status_code == 404


async def test_the_resolver_fails_closed_when_the_lookup_breaks(session, monkeypatch) -> None:
    """A resolver that cannot reach its data must hide, not reveal.

    Flip the ``except`` branch in ``hidden_entity_ids`` to ``return set()`` and
    this fails - which is precisely the fail-open bug the branch exists to
    prevent.
    """
    _owner, _insider, outsider, project, _a, _b = await _project_with_two_teams(session)
    candidates = [str(uuid.uuid4()), str(uuid.uuid4())]

    async def _boom(*_args, **_kwargs):
        raise RuntimeError("connection lost")

    monkeypatch.setattr(
        "app.modules.teams.repository.VisibilityRepository.restricted_entity_ids",
        _boom,
    )
    hidden = await hidden_entity_ids(
        session,
        project_id=project.id,
        entity_type="document",
        entity_ids=candidates,
        user_id=outsider.id,
    )
    assert hidden == set(candidates)


async def test_an_unresolvable_caller_loses_every_restricted_record(session) -> None:
    """A caller id that parses as nobody is a member of nothing.

    The safe reading of a malformed id is "not on any team", so every
    restricted record is hidden - never "no restrictions apply".
    """
    owner, _insider, _outsider, project, team_a, _b = await _project_with_two_teams(session)
    record = str(uuid.uuid4())
    open_record = str(uuid.uuid4())
    service = TeamService(session)
    await service.grant_visibility("document", record, team_a.id, actor_id=owner.id)

    hidden = await hidden_entity_ids(
        session,
        project_id=project.id,
        entity_type="document",
        entity_ids=[record, open_record],
        user_id="not-a-uuid",
    )
    # The restricted one goes; the open one is still open, because an
    # unresolvable caller is not a reason to hide what nobody restricted.
    assert hidden == {record}
