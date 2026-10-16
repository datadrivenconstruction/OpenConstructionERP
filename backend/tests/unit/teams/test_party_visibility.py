"""Party visibility: the resolver every shared register reads through.

The cases are built to distinguish. Each negative names a record that plain
project access WOULD show (every user here is a member of the project), so a
pass means the party filter removed it, not that the user could not reach the
project in the first place. Each positive names a user the filter must leave
alone, so a filter that hides too much fails as loudly as one that hides too
little.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.core.audit_log import ActivityLog
from app.modules.rfi.models import RFI
from app.modules.teams.models import PartyRecordAccess, ProjectParty, ProjectPartyMember
from app.modules.teams.party_access import (
    party_hidden_ids,
    party_read_clause,
    resolve_party_scope,
    stamp_originator,
    verify_party_record_access,
)
from app.modules.teams.party_schemas import ProjectPartyCreate
from app.modules.teams.party_service import PartyService
from tests.unit.teams.conftest import make_membership, make_project, make_team, make_user

pytestmark = pytest.mark.asyncio


async def _rfi(session, project_id, raised_by, *, subject: str = "RFI") -> RFI:
    rfi = RFI(
        project_id=project_id,
        rfi_number=f"RFI-{uuid.uuid4().hex[:6]}",
        subject=subject,
        question="?",
        raised_by=raised_by,
    )
    session.add(rfi)
    await session.flush()
    return rfi


async def _visible_ids(session, project_id, user_id) -> set[uuid.UUID]:
    stmt = select(RFI.id).where(RFI.project_id == project_id)
    clause = await party_read_clause(
        session, user_id=user_id, entity_type="rfi", id_column=RFI.id, project_id_column=RFI.project_id
    )
    if clause is not None:
        stmt = stmt.where(clause)
    return set((await session.execute(stmt)).scalars().all())


async def _world(session):
    """Owner, an internal colleague, subcontractors A and B, and a host-party colleague.

    Every user is a team member of the project, so project access alone would
    show them every record.
    """
    owner = await make_user(session)
    internal = await make_user(session)
    host_colleague = await make_user(session)
    sub_a = await make_user(session)
    sub_b = await make_user(session)
    project = await make_project(session, owner.id)
    team = await make_team(session, project.id, is_default=True)
    for user in (internal, host_colleague, sub_a, sub_b):
        await make_membership(session, team.id, user.id)

    service = PartyService(session)
    host = await service.create_party(
        project.id, ProjectPartyCreate(name="Main contractor", role="contractor"), actor_id=owner.id
    )
    party_a = await service.create_party(project.id, ProjectPartyCreate(name="Sub A"), actor_id=owner.id)
    party_b = await service.create_party(project.id, ProjectPartyCreate(name="Sub B"), actor_id=owner.id)
    await service.bind_member(project.id, owner.id, host.id, actor_id=owner.id)
    await service.bind_member(project.id, host_colleague.id, host.id, actor_id=owner.id)
    await service.bind_member(project.id, sub_a.id, party_a.id, actor_id=owner.id)
    await service.bind_member(project.id, sub_b.id, party_b.id, actor_id=owner.id)
    return {
        "owner": owner,
        "internal": internal,
        "host_colleague": host_colleague,
        "sub_a": sub_a,
        "sub_b": sub_b,
        "project": project,
        "host": host,
        "party_a": party_a,
        "party_b": party_b,
    }


async def _created_by(session, w, user, subject: str) -> RFI:
    rfi = await _rfi(session, w["project"].id, user.id, subject=subject)
    await stamp_originator(session, entity_type="rfi", project_id=w["project"].id, entity_id=rfi.id, user_id=user.id)
    return rfi


# ── Backward compatibility ───────────────────────────────────────────────────


async def test_a_project_without_parties_is_not_filtered(session) -> None:
    owner = await make_user(session)
    member = await make_user(session)
    project = await make_project(session, owner.id)
    team = await make_team(session, project.id, is_default=True)
    await make_membership(session, team.id, member.id)
    rfi = await _rfi(session, project.id, owner.id)

    assert (
        await party_read_clause(
            session, user_id=member.id, entity_type="rfi", id_column=RFI.id, project_id_column=RFI.project_id
        )
        is None
    )
    assert await _visible_ids(session, project.id, member.id) == {rfi.id}
    await verify_party_record_access(
        session, entity_type="rfi", project_id=project.id, entity_id=rfi.id, user_id=member.id
    )
    # No parties means no stamps either: the project gains no rows.
    assert (
        await stamp_originator(session, entity_type="rfi", project_id=project.id, entity_id=rfi.id, user_id=member.id)
        is None
    )
    rows = (await session.execute(select(PartyRecordAccess).where(PartyRecordAccess.project_id == project.id))).all()
    assert rows == []


async def test_binding_on_another_project_does_not_filter_this_one(session) -> None:
    """A user external on project X is still internal on project Y without parties."""
    w = await _world(session)
    other_owner = await make_user(session)
    other = await make_project(session, other_owner.id)
    team = await make_team(session, other.id, is_default=True)
    await make_membership(session, team.id, w["sub_a"].id)
    rfi = await _rfi(session, other.id, other_owner.id)

    assert await _visible_ids(session, other.id, w["sub_a"].id) == {rfi.id}


# ── The distinguishing cases ─────────────────────────────────────────────────


async def test_subcontractor_a_does_not_see_b_in_the_list(session) -> None:
    w = await _world(session)
    rfi_a = await _created_by(session, w, w["sub_a"], "A's question")
    rfi_b = await _created_by(session, w, w["sub_b"], "B's question")

    assert await _visible_ids(session, w["project"].id, w["sub_a"].id) == {rfi_a.id}
    assert await _visible_ids(session, w["project"].id, w["sub_b"].id) == {rfi_b.id}


async def test_direct_id_of_a_hidden_record_is_404_not_403(session) -> None:
    w = await _world(session)
    rfi_b = await _created_by(session, w, w["sub_b"], "B's question")

    with pytest.raises(HTTPException) as exc:
        await verify_party_record_access(
            session, entity_type="rfi", project_id=w["project"].id, entity_id=rfi_b.id, user_id=w["sub_a"].id
        )
    assert exc.value.status_code == 404


async def test_internal_members_owner_and_host_party_see_everything(session) -> None:
    w = await _world(session)
    admin = await make_user(session, role="admin")
    rfi_a = await _created_by(session, w, w["sub_a"], "A")
    rfi_b = await _created_by(session, w, w["sub_b"], "B")
    legacy = await _rfi(session, w["project"].id, w["owner"].id, subject="no rows")
    everything = {rfi_a.id, rfi_b.id, legacy.id}

    for user in (w["owner"], w["internal"], w["host_colleague"], admin):
        assert await _visible_ids(session, w["project"].id, user.id) == everything, user
        scope = await resolve_party_scope(session, w["project"].id, user.id)
        assert scope.internal
    assert (await resolve_party_scope(session, w["project"].id, w["host_colleague"].id)).is_host


async def test_a_record_with_no_rows_is_hidden_from_external_parties(session) -> None:
    w = await _world(session)
    legacy = await _rfi(session, w["project"].id, w["owner"].id, subject="internal draft")

    for user in (w["sub_a"], w["sub_b"]):
        assert legacy.id not in await _visible_ids(session, w["project"].id, user.id)
        hidden = await party_hidden_ids(
            session, project_id=w["project"].id, entity_type="rfi", entity_ids=[legacy.id], user_id=user.id
        )
        assert hidden == {str(legacy.id)}


async def test_without_a_host_party_every_bound_member_is_external(session) -> None:
    """The owner bound to no party: binding alone makes someone external."""
    owner = await make_user(session)
    colleague = await make_user(session)
    project = await make_project(session, owner.id)
    team = await make_team(session, project.id, is_default=True)
    await make_membership(session, team.id, colleague.id)
    service = PartyService(session)
    party = await service.create_party(project.id, ProjectPartyCreate(name="Contractor"), actor_id=owner.id)
    await service.bind_member(project.id, colleague.id, party.id, actor_id=owner.id)
    rfi = await _rfi(session, project.id, owner.id)

    assert (await resolve_party_scope(session, project.id, colleague.id)).restricted
    assert await _visible_ids(session, project.id, colleague.id) == set()


# ── Sharing ──────────────────────────────────────────────────────────────────


async def test_sharing_for_view_grants_read_but_not_write(session) -> None:
    w = await _world(session)
    rfi_b = await _created_by(session, w, w["sub_b"], "B")
    service = PartyService(session)
    await service.share_record(w["project"].id, "rfi", rfi_b.id, w["party_a"].id, "view", actor_id=w["sub_b"].id)

    assert rfi_b.id in await _visible_ids(session, w["project"].id, w["sub_a"].id)
    await verify_party_record_access(
        session, entity_type="rfi", project_id=w["project"].id, entity_id=rfi_b.id, user_id=w["sub_a"].id
    )
    with pytest.raises(HTTPException) as exc:
        await verify_party_record_access(
            session,
            entity_type="rfi",
            project_id=w["project"].id,
            entity_id=rfi_b.id,
            user_id=w["sub_a"].id,
            write=True,
        )
    assert exc.value.status_code == 403
    # The originator keeps write access.
    await verify_party_record_access(
        session, entity_type="rfi", project_id=w["project"].id, entity_id=rfi_b.id, user_id=w["sub_b"].id, write=True
    )


async def test_contribute_share_grants_write(session) -> None:
    w = await _world(session)
    rfi_b = await _created_by(session, w, w["sub_b"], "B")
    await PartyService(session).share_record(
        w["project"].id, "rfi", rfi_b.id, w["party_a"].id, "contribute", actor_id=w["owner"].id
    )
    await verify_party_record_access(
        session, entity_type="rfi", project_id=w["project"].id, entity_id=rfi_b.id, user_id=w["sub_a"].id, write=True
    )


async def test_revoking_a_share_hides_the_record_again_and_is_audited(session) -> None:
    w = await _world(session)
    rfi_b = await _created_by(session, w, w["sub_b"], "B")
    service = PartyService(session)
    await service.share_record(w["project"].id, "rfi", rfi_b.id, w["party_a"].id, "view", actor_id=w["sub_b"].id)
    await service.revoke_share(w["project"].id, "rfi", rfi_b.id, w["party_a"].id, actor_id=w["sub_b"].id)

    assert rfi_b.id not in await _visible_ids(session, w["project"].id, w["sub_a"].id)
    audit = (
        (
            await session.execute(
                select(ActivityLog).where(
                    ActivityLog.entity_type == "party_record",
                    ActivityLog.entity_id == str(rfi_b.id),
                    ActivityLog.action == "party_share_revoked",
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(audit) == 1


async def test_a_party_cannot_pass_on_a_record_it_only_received(session) -> None:
    w = await _world(session)
    rfi_b = await _created_by(session, w, w["sub_b"], "B")
    service = PartyService(session)
    await service.share_record(w["project"].id, "rfi", rfi_b.id, w["party_a"].id, "contribute", actor_id=w["sub_b"].id)
    third = await service.create_party(w["project"].id, ProjectPartyCreate(name="Sub C"), actor_id=w["owner"].id)

    with pytest.raises(HTTPException) as exc:
        await service.share_record(w["project"].id, "rfi", rfi_b.id, third.id, "view", actor_id=w["sub_a"].id)
    assert exc.value.status_code == 403


async def test_a_party_cannot_share_a_record_it_cannot_see(session) -> None:
    w = await _world(session)
    rfi_b = await _created_by(session, w, w["sub_b"], "B")
    with pytest.raises(HTTPException) as exc:
        await PartyService(session).share_record(
            w["project"].id, "rfi", rfi_b.id, w["party_a"].id, "view", actor_id=w["sub_a"].id
        )
    assert exc.value.status_code == 404


async def test_cannot_share_with_a_party_outside_the_project(session) -> None:
    w = await _world(session)
    rfi_b = await _created_by(session, w, w["sub_b"], "B")
    other_owner = await make_user(session)
    other = await make_project(session, other_owner.id)
    foreign = await PartyService(session).create_party(
        other.id, ProjectPartyCreate(name="Elsewhere"), actor_id=other_owner.id
    )

    with pytest.raises(HTTPException) as exc:
        await PartyService(session).share_record(
            w["project"].id, "rfi", rfi_b.id, foreign.id, "view", actor_id=w["owner"].id
        )
    assert exc.value.status_code == 404
    rows = (await session.execute(select(PartyRecordAccess).where(PartyRecordAccess.party_id == foreign.id))).all()
    assert rows == []


async def test_a_record_of_another_project_cannot_be_shared_through_this_one(session) -> None:
    w = await _world(session)
    other_owner = await make_user(session)
    other = await make_project(session, other_owner.id)
    foreign_rfi = await _rfi(session, other.id, other_owner.id)

    with pytest.raises(HTTPException) as exc:
        await PartyService(session).share_record(
            w["project"].id, "rfi", foreign_rfi.id, w["party_a"].id, "view", actor_id=w["owner"].id
        )
    assert exc.value.status_code == 404


# ── Membership rules ─────────────────────────────────────────────────────────


async def test_a_member_has_at_most_one_party_per_project(session) -> None:
    w = await _world(session)
    with pytest.raises(HTTPException) as exc:
        await PartyService(session).bind_member(w["project"].id, w["sub_a"].id, w["party_b"].id, actor_id=w["owner"].id)
    assert exc.value.status_code == 409
    bindings = (
        await session.execute(
            select(ProjectPartyMember).where(
                ProjectPartyMember.project_id == w["project"].id, ProjectPartyMember.user_id == w["sub_a"].id
            )
        )
    ).all()
    assert len(bindings) == 1


async def test_only_a_project_member_can_be_bound(session) -> None:
    w = await _world(session)
    stranger = await make_user(session)
    with pytest.raises(HTTPException) as exc:
        await PartyService(session).bind_member(w["project"].id, stranger.id, w["party_a"].id, actor_id=w["owner"].id)
    assert exc.value.status_code == 422


async def test_a_member_cannot_configure_parties(session) -> None:
    w = await _world(session)
    with pytest.raises(HTTPException) as exc:
        await PartyService(session).create_party(
            w["project"].id, ProjectPartyCreate(name="Mine"), actor_id=w["internal"].id
        )
    assert exc.value.status_code == 403
    with pytest.raises(HTTPException) as exc:
        await PartyService(session).unbind_member(w["project"].id, w["sub_a"].id, actor_id=w["sub_a"].id)
    assert exc.value.status_code == 403


async def test_unbinding_makes_the_member_internal_again(session) -> None:
    w = await _world(session)
    rfi_b = await _created_by(session, w, w["sub_b"], "B")
    await PartyService(session).unbind_member(w["project"].id, w["sub_a"].id, actor_id=w["owner"].id)
    assert rfi_b.id in await _visible_ids(session, w["project"].id, w["sub_a"].id)


async def test_deleting_a_party_removes_its_rows(session) -> None:
    w = await _world(session)
    rfi_b = await _created_by(session, w, w["sub_b"], "B")
    await PartyService(session).delete_party(w["project"].id, w["party_b"].id, actor_id=w["owner"].id)
    assert await session.get(ProjectParty, w["party_b"].id) is None
    rows = (await session.execute(select(PartyRecordAccess).where(PartyRecordAccess.entity_id == rfi_b.id))).all()
    assert rows == []


async def test_originator_can_be_set_by_owner_only(session) -> None:
    w = await _world(session)
    legacy = await _rfi(session, w["project"].id, w["owner"].id)
    service = PartyService(session)
    with pytest.raises(HTTPException) as exc:
        await service.set_originator(w["project"].id, "rfi", legacy.id, w["party_a"].id, actor_id=w["internal"].id)
    assert exc.value.status_code == 403

    await service.set_originator(w["project"].id, "rfi", legacy.id, w["party_a"].id, actor_id=w["owner"].id)
    assert legacy.id in await _visible_ids(session, w["project"].id, w["sub_a"].id)
    assert legacy.id not in await _visible_ids(session, w["project"].id, w["sub_b"].id)


# ── Cross-project lists ──────────────────────────────────────────────────────


async def test_cross_project_clause_filters_only_where_the_user_is_external(session) -> None:
    w = await _world(session)
    rfi_b = await _created_by(session, w, w["sub_b"], "B")
    other_owner = await make_user(session)
    other = await make_project(session, other_owner.id)
    team = await make_team(session, other.id, is_default=True)
    await make_membership(session, team.id, w["sub_a"].id)
    open_rfi = await _rfi(session, other.id, other_owner.id)

    clause = await party_read_clause(
        session, user_id=w["sub_a"].id, entity_type="rfi", id_column=RFI.id, project_id_column=RFI.project_id
    )
    assert clause is not None
    ids = set(
        (await session.execute(select(RFI.id).where(RFI.project_id.in_([w["project"].id, other.id])).where(clause)))
        .scalars()
        .all()
    )
    assert open_rfi.id in ids
    assert rfi_b.id not in ids


# ── Validation rules ─────────────────────────────────────────────────────────


async def test_party_rules_flag_a_missing_host_and_a_stale_binding(session) -> None:
    from app.modules.teams.models import TeamMembership
    from app.modules.teams.validators import evaluate_project_teams

    owner = await make_user(session)
    colleague = await make_user(session)
    project = await make_project(session, owner.id)
    team = await make_team(session, project.id, is_default=True)
    membership = await make_membership(session, team.id, colleague.id)
    service = PartyService(session)
    party = await service.create_party(project.id, ProjectPartyCreate(name="Contractor"), actor_id=owner.id)
    await service.bind_member(project.id, colleague.id, party.id, actor_id=owner.id)

    report = await evaluate_project_teams(session, project.id)
    assert "teams.party_host_defined" in {f.rule_id for f in report.findings}
    assert "teams.party_member_has_access" not in {f.rule_id for f in report.findings}

    await session.delete(await session.get(TeamMembership, membership.id))
    await session.flush()
    report = await evaluate_project_teams(session, project.id)
    assert "teams.party_member_has_access" in {f.rule_id for f in report.findings}

    await service.bind_member(project.id, owner.id, party.id, actor_id=owner.id)
    report = await evaluate_project_teams(session, project.id)
    assert "teams.party_host_defined" not in {f.rule_id for f in report.findings}
