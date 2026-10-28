"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The access-control negatives for the teams module.

The invariant under test, stated once so every case below can be read against
it: **no arrangement of teams, memberships or restrictions may show a user a
project or a record they could not already reach.** The team layer narrows. It
never widens.

Three ways that invariant could be broken, and the case that closes each:

1. A low-privilege caller writes a membership row. ``verify_project_access``
   reads any membership row as project access, so writing one is equivalent to
   handing out a project. Closed by
   :func:`test_plain_member_cannot_add_a_member` and its siblings, which are
   the headline cases.
2. A restriction row is read as a grant. Closed by
   :func:`test_a_restriction_never_grants_project_access` and
   :func:`test_hidden_entity_ids_returns_only_a_subset_of_its_input`.
3. An id is walked to discover what exists. Closed by the 404-not-403 cases.

Every case names the original behaviour it guards in its docstring, so the
"put the old behaviour back and watch it fail" check has a target.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException

from app.modules.teams.access import hidden_entity_ids, is_project_member
from app.modules.teams.schemas import AddMemberRequest, TeamCreate, TeamUpdate
from app.modules.teams.service import TeamService
from tests.unit.teams.conftest import (
    make_membership,
    make_project,
    make_team,
    make_user,
)

pytestmark = pytest.mark.asyncio


# ── 1. Writing a membership is writing project access ────────────────────────


async def test_plain_member_cannot_add_a_member(session) -> None:
    """A team member must not be able to put anyone else on the project.

    THE headline case. Before this change ``add_member`` gated on
    ``_assert_project_access``, which any membership row satisfies. So Mallory,
    holding one membership, could add Trudy - and Trudy's new row then made
    ``verify_project_access`` grant her the whole project. A user gained
    visibility of a project she could not see before, by way of a team.

    Put ``_assert_project_admin`` back to ``_assert_project_access`` in
    ``TeamService.add_member`` and this test fails: the call returns a
    membership instead of raising 403.
    """
    owner = await make_user(session)
    mallory = await make_user(session)
    trudy = await make_user(session)
    project = await make_project(session, owner.id)
    team = await make_team(session, project.id, name="Site", is_default=True)
    await make_membership(session, team.id, mallory.id)

    # Mallory really does have project access - that is the whole point.
    assert await is_project_member(session, project.id, mallory.id) is True

    service = TeamService(session)
    with pytest.raises(HTTPException) as exc:
        await service.add_member(
            team.id,
            AddMemberRequest(user_id=trudy.id, role="member"),
            actor_id=mallory.id,
        )
    assert exc.value.status_code == 403

    # And the escalation did not happen: Trudy still cannot reach the project.
    assert await is_project_member(session, project.id, trudy.id) is False


async def test_plain_member_cannot_create_a_team(session) -> None:
    """Creating a team is a write on the project's access model.

    A team is the container a membership lives in. Letting a member create one
    is the first half of the escalation in the case above, so it takes the same
    gate.
    """
    owner = await make_user(session)
    mallory = await make_user(session)
    project = await make_project(session, owner.id)
    team = await make_team(session, project.id, name="Site", is_default=True)
    await make_membership(session, team.id, mallory.id)

    service = TeamService(session)
    with pytest.raises(HTTPException) as exc:
        await service.create_team(
            TeamCreate(project_id=project.id, name="Mallory's team"),
            actor_id=mallory.id,
        )
    assert exc.value.status_code == 403


async def test_plain_member_cannot_change_a_role_or_remove_a_member(session) -> None:
    """Role changes and removals take the same gate as adds.

    A role change is how an in-place promotion into an ELEVATED role would be
    smuggled past the add-time check; a removal is how a member could evict the
    people who would notice.
    """
    owner = await make_user(session)
    mallory = await make_user(session)
    victim = await make_user(session)
    project = await make_project(session, owner.id)
    team = await make_team(session, project.id, name="Site", is_default=True)
    await make_membership(session, team.id, mallory.id)
    await make_membership(session, team.id, victim.id)

    service = TeamService(session)
    with pytest.raises(HTTPException) as promote:
        await service.update_member_role(team.id, mallory.id, "owner", actor_id=mallory.id)
    assert promote.value.status_code == 403

    with pytest.raises(HTTPException) as evict:
        await service.remove_member(team.id, victim.id, actor_id=mallory.id)
    assert evict.value.status_code == 403


async def test_owner_can_do_what_the_member_cannot(session) -> None:
    """The gate refuses the right people, not everyone.

    A refusal test on its own cannot tell "correctly denied" from "broken", so
    the positive path runs the same calls as the project owner.
    """
    owner = await make_user(session)
    newcomer = await make_user(session)
    project = await make_project(session, owner.id)

    service = TeamService(session)
    team = await service.create_team(
        TeamCreate(project_id=project.id, name="Client side", kind="client"),
        actor_id=owner.id,
    )
    membership = await service.add_member(
        team.id,
        AddMemberRequest(user_id=newcomer.id, role="viewer"),
        actor_id=owner.id,
    )
    assert membership.role == "viewer"

    promoted = await service.update_member_role(team.id, newcomer.id, "project_manager", actor_id=owner.id)
    assert promoted.role == "project_manager"

    await service.remove_member(team.id, newcomer.id, actor_id=owner.id)
    assert await service.list_members(team.id, actor_id=owner.id) == []


async def test_system_admin_passes_the_write_gate(session) -> None:
    """A persisted admin role bypasses ownership, as everywhere else."""
    owner = await make_user(session)
    admin = await make_user(session, role="admin")
    project = await make_project(session, owner.id)

    service = TeamService(session)
    team = await service.create_team(
        TeamCreate(project_id=project.id, name="Admin made this"),
        actor_id=admin.id,
    )
    assert team.project_id == project.id


async def test_a_deactivated_user_cannot_be_added(session) -> None:
    """A dangling membership row is project access nobody can audit.

    ``projects.member_service`` already refuses this; the teams door has to
    refuse it too or the rule is only enforced on one of the two paths into
    the same table.
    """
    owner = await make_user(session)
    ghost = await make_user(session, is_active=False)
    project = await make_project(session, owner.id)
    service = TeamService(session)
    team = await service.create_team(TeamCreate(project_id=project.id, name="Site"), actor_id=owner.id)

    with pytest.raises(HTTPException) as exc:
        await service.add_member(
            team.id,
            AddMemberRequest(user_id=ghost.id, role="member"),
            actor_id=owner.id,
        )
    assert exc.value.status_code == 400


async def test_an_unknown_user_cannot_be_added(session) -> None:
    """A membership for a user id that names nobody is a 404, not a 500."""
    owner = await make_user(session)
    project = await make_project(session, owner.id)
    service = TeamService(session)
    team = await service.create_team(TeamCreate(project_id=project.id, name="Site"), actor_id=owner.id)

    with pytest.raises(HTTPException) as exc:
        await service.add_member(
            team.id,
            AddMemberRequest(user_id=uuid.uuid4(), role="member"),
            actor_id=owner.id,
        )
    assert exc.value.status_code == 404


# ── 2. A restriction is not a grant ──────────────────────────────────────────


async def test_a_restriction_never_grants_project_access(session) -> None:
    """Being on a team that may see a record does not make the record reachable.

    An outsider is put on a team of project A and that team is given a
    restriction on a record. The restriction resolver reports the record as not
    hidden from them - which is correct and is exactly why the resolver alone is
    not a gate. Project access is the gate, and it is unchanged: the outsider
    is not a member of project B and cannot reach anything there.
    """
    owner_a = await make_user(session)
    owner_b = await make_user(session)
    outsider = await make_user(session)
    project_a = await make_project(session, owner_a.id)
    project_b = await make_project(session, owner_b.id)

    team_a = await make_team(session, project_a.id, name="A team")
    await make_membership(session, team_a.id, outsider.id)

    service = TeamService(session)
    record_id = str(uuid.uuid4())
    await service.grant_visibility("document", record_id, team_a.id, actor_id=owner_a.id)

    # Inside project A the outsider is one of the permitted readers.
    assert (
        await hidden_entity_ids(
            session,
            project_id=project_a.id,
            entity_type="document",
            entity_ids=[record_id],
            user_id=outsider.id,
        )
        == set()
    )

    # None of that reaches project B: not a member, and a restriction row
    # written against project A's team is inert against project B's reads.
    assert await is_project_member(session, project_b.id, outsider.id) is False
    with pytest.raises(HTTPException) as exc:
        await service.list_teams(project_b.id, actor_id=outsider.id)
    assert exc.value.status_code == 404


async def test_hidden_entity_ids_returns_only_a_subset_of_its_input(session) -> None:
    """The resolver is subtractive by signature and by behaviour.

    The structural half of the invariant: whatever the data looks like, the
    answer is a subset of the ids handed in, so a consumer that subtracts it
    cannot end up with more rows than it started with.
    """
    owner = await make_user(session)
    stranger = await make_user(session)
    project = await make_project(session, owner.id)
    team = await make_team(session, project.id, name="Restricted")

    service = TeamService(session)
    restricted = str(uuid.uuid4())
    open_record = str(uuid.uuid4())
    await service.grant_visibility("document", restricted, team.id, actor_id=owner.id)

    candidates = [restricted, open_record]
    hidden = await hidden_entity_ids(
        session,
        project_id=project.id,
        entity_type="document",
        entity_ids=candidates,
        user_id=stranger.id,
    )
    assert hidden <= set(candidates)
    # The restricted one is taken away; the unrestricted one is untouched.
    assert hidden == {restricted}

    # An id that was never offered is never returned, even though it is
    # restricted in the same project.
    other = str(uuid.uuid4())
    await service.grant_visibility("document", other, team.id, actor_id=owner.id)
    assert other not in await hidden_entity_ids(
        session,
        project_id=project.id,
        entity_type="document",
        entity_ids=[open_record],
        user_id=stranger.id,
    )


async def test_a_restriction_in_another_project_cannot_hide_this_project_s_record(session) -> None:
    """A row written against a foreign team is inert here.

    Without the ``Team.project_id`` join in the repository, an owner of any
    project could restrict a record id belonging to someone else's project and
    hide it from its own team - a cross-tenant denial of service. Drop the join
    from ``VisibilityRepository.restricted_entity_ids`` and this fails.
    """
    owner_a = await make_user(session)
    mallory = await make_user(session)
    reader = await make_user(session)
    project_a = await make_project(session, owner_a.id)
    project_m = await make_project(session, mallory.id)

    team_a = await make_team(session, project_a.id, name="A team")
    await make_membership(session, team_a.id, reader.id)
    team_m = await make_team(session, project_m.id, name="Mallory team")

    shared_id = str(uuid.uuid4())
    service = TeamService(session)
    # Mallory restricts the id inside her own project. She is allowed to: it
    # is her project. It must not reach project A.
    await service.grant_visibility("document", shared_id, team_m.id, actor_id=mallory.id)

    hidden = await hidden_entity_ids(
        session,
        project_id=project_a.id,
        entity_type="document",
        entity_ids=[shared_id],
        user_id=reader.id,
    )
    assert hidden == set()


# ── 3. Ids cannot be walked ──────────────────────────────────────────────────


async def test_a_team_in_another_project_answers_404_not_403(session) -> None:
    """Reading a team you may not see must not confirm it exists."""
    owner_a = await make_user(session)
    owner_b = await make_user(session)
    project_a = await make_project(session, owner_a.id)
    project_b = await make_project(session, owner_b.id)
    team_b = await make_team(session, project_b.id, name="Theirs")

    service = TeamService(session)
    with pytest.raises(HTTPException) as exc:
        await service.list_members(team_b.id, actor_id=owner_a.id)
    assert exc.value.status_code == 404

    # A team id that names nothing at all answers identically, which is what
    # makes the two indistinguishable.
    with pytest.raises(HTTPException) as missing:
        await service.list_members(uuid.uuid4(), actor_id=owner_a.id)
    assert missing.value.status_code == exc.value.status_code


async def test_writing_to_another_project_s_team_answers_404_not_403(session) -> None:
    """A write on a foreign team is 404 too: 403 would confirm it exists.

    403 is reserved for the case where the caller can already see the project,
    so telling them "not yours" leaks nothing they did not have.
    """
    owner_a = await make_user(session)
    owner_b = await make_user(session)
    project_a = await make_project(session, owner_a.id)
    project_b = await make_project(session, owner_b.id)
    team_b = await make_team(session, project_b.id, name="Theirs")
    _ = project_a

    service = TeamService(session)
    with pytest.raises(HTTPException) as exc:
        await service.update_team(team_b.id, TeamUpdate(name="Mine now"), actor_id=owner_a.id)
    assert exc.value.status_code == 404

    with pytest.raises(HTTPException) as delete_exc:
        await service.delete_team(team_b.id, actor_id=owner_a.id)
    assert delete_exc.value.status_code == 404


async def test_setting_visibility_to_a_foreign_team_answers_404(session) -> None:
    """A team id from another project cannot be smuggled into a set operation.

    Otherwise the endpoint doubles as an oracle: a 422 or a 500 on a real id
    and a 404 on a made-up one would tell the caller which team ids exist
    elsewhere.
    """
    owner_a = await make_user(session)
    owner_b = await make_user(session)
    project_a = await make_project(session, owner_a.id)
    project_b = await make_project(session, owner_b.id)
    team_b = await make_team(session, project_b.id, name="Theirs")

    service = TeamService(session)
    with pytest.raises(HTTPException) as exc:
        await service.set_entity_visibility(
            project_a.id,
            "document",
            str(uuid.uuid4()),
            [team_b.id],
            actor_id=owner_a.id,
        )
    assert exc.value.status_code == 404

    with pytest.raises(HTTPException) as invented:
        await service.set_entity_visibility(
            project_a.id,
            "document",
            str(uuid.uuid4()),
            [uuid.uuid4()],
            actor_id=owner_a.id,
        )
    assert invented.value.status_code == exc.value.status_code


async def test_reading_a_project_you_are_not_on_answers_404(session) -> None:
    """Every read entry point refuses a stranger the same way."""
    owner = await make_user(session)
    stranger = await make_user(session)
    project = await make_project(session, owner.id)

    service = TeamService(session)
    for call in (
        service.list_teams(project.id, actor_id=stranger.id),
        service.list_restricted_entities(project.id, actor_id=stranger.id),
        service.build_access_matrix(project.id, actor_id=stranger.id),
        service.describe_entity_visibility(project.id, "document", "x", actor_id=stranger.id),
        service.validate_project(project.id, actor_id=stranger.id),
    ):
        with pytest.raises(HTTPException) as exc:
            await call
        assert exc.value.status_code == 404
