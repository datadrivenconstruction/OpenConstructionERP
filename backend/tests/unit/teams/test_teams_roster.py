"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The project roster: who is on the job, where they come from, what expires.

Against a real PostgreSQL session, because the questions worth asking here are
about data: does a line survive its team being deleted, does a person the
platform already knows arrive with their name filled in, does an expired ticket
reach the validation report, and can somebody edit a roster line by guessing an
id from another project.

Placed under ``tests/unit`` with the rest of the module's suite, which is the
directory the sharded CI gate actually runs.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.modules.contacts.models import Contact
from app.modules.teams.models import RosterMember
from app.modules.teams.roster_schemas import RosterMemberCreate, RosterMemberUpdate
from app.modules.teams.roster_service import RosterService
from app.modules.teams.service import TeamService
from tests.unit.teams.conftest import (
    API_PREFIX,
    build_app,
    http_client,
    make_membership,
    make_project,
    make_team,
    make_user,
)

pytestmark = pytest.mark.asyncio


def _today() -> datetime:
    return datetime.now(UTC)


async def _make_contact(session, *, first: str, last: str, company: str) -> Contact:
    """An address-book contact, the kind a subcontractor foreman lives in."""
    contact = Contact(
        contact_type="subcontractor",
        first_name=first,
        last_name=last,
        company_name=company,
        primary_email=f"{first}.{last}@example.com".lower(),
        primary_phone="+49 170 0000000",
        is_active=True,
    )
    session.add(contact)
    await session.flush()
    return contact


# ── Where the people come from ───────────────────────────────────────────────


async def test_a_user_arrives_on_the_roster_with_their_name_already_filled_in(session):
    """Picking a colleague must not ask anybody to retype their name."""
    owner = await make_user(session, full_name="Owner One")
    project = await make_project(session, owner.id)
    engineer = await make_user(session, full_name="Marta Kowalska")

    service = RosterService(session)
    created = await service.add_members(
        project.id,
        [RosterMemberCreate(user_id=engineer.id, site_role="section_engineer", trade="concrete")],
        actor_id=owner.id,
    )

    assert len(created) == 1
    line = created[0]
    assert line.display_name == "Marta Kowalska"
    assert line.email == engineer.email
    assert line.source == "user"
    assert line.site_role_label == "Site engineer"
    assert line.trade_label == "Concrete"


async def test_a_contact_can_be_on_the_team_without_a_login(session):
    """The subcontractor's foreman has no account and still belongs on the roster."""
    owner = await make_user(session)
    project = await make_project(session, owner.id)
    contact = await _make_contact(session, first="Jens", last="Brandt", company="Brandt Rohbau GmbH")

    service = RosterService(session)
    created = await service.add_members(
        project.id,
        [RosterMemberCreate(contact_id=contact.id, site_role="foreman", trade="concrete")],
        actor_id=owner.id,
    )

    line = created[0]
    assert line.display_name == "Jens Brandt"
    assert line.company_name == "Brandt Rohbau GmbH"
    assert line.phone == "+49 170 0000000"
    assert line.source == "contact"
    # The whole point of the separation: a roster line hands out nothing.
    assert line.has_project_access is False


async def test_a_person_the_platform_does_not_know_can_still_be_listed(session):
    """The induction-list escape hatch: a name, and nothing else."""
    owner = await make_user(session)
    project = await make_project(session, owner.id)

    service = RosterService(session)
    created = await service.add_members(
        project.id,
        [RosterMemberCreate(display_name="Tomasz W.", company_name="Agency", site_role="operative")],
        actor_id=owner.id,
    )

    assert created[0].source == "manual"
    assert created[0].display_name == "Tomasz W."


async def test_candidates_offer_users_and_contacts_together_and_mark_who_is_already_there(session):
    """One list, both sources, and no invitation to create a duplicate."""
    owner = await make_user(session, full_name="Ada Owner")
    project = await make_project(session, owner.id)
    contact = await _make_contact(session, first="Jens", last="Brandt", company="Brandt Rohbau GmbH")

    service = RosterService(session)
    await service.add_members(project.id, [RosterMemberCreate(contact_id=contact.id)], actor_id=owner.id)

    candidates, total = await service.list_candidates(project.id, actor_id=owner.id)
    assert total == len(candidates)
    by_source = {c.source for c in candidates}
    assert by_source == {"user", "contact"}
    contact_row = next(c for c in candidates if c.source == "contact" and c.id == contact.id)
    assert contact_row.on_roster is True
    owner_row = next(c for c in candidates if c.source == "user" and c.id == owner.id)
    assert owner_row.on_roster is False


async def test_the_same_person_is_not_added_twice(session):
    """A double click is a repeat, not an error, and must not fail the batch."""
    owner = await make_user(session)
    project = await make_project(session, owner.id)
    engineer = await make_user(session, full_name="Marta Kowalska")

    service = RosterService(session)
    await service.add_members(project.id, [RosterMemberCreate(user_id=engineer.id)], actor_id=owner.id)
    second = await service.add_members(
        project.id,
        [
            RosterMemberCreate(user_id=engineer.id),
            RosterMemberCreate(display_name="New Person"),
        ],
        actor_id=owner.id,
    )

    assert [line.display_name for line in second] == ["New Person"]
    roster, _ = await service.list_roster(project.id, actor_id=owner.id)
    assert sum(1 for line in roster if line.user_id == engineer.id) == 1


# ── What the roster does NOT do ──────────────────────────────────────────────


async def test_a_roster_line_grants_no_project_access(session):
    """The property the whole design rests on, asserted rather than assumed."""
    owner = await make_user(session)
    project = await make_project(session, owner.id)
    outsider = await make_user(session, full_name="Outsider")

    await RosterService(session).add_members(
        project.id,
        [RosterMemberCreate(user_id=outsider.id)],
        actor_id=owner.id,
    )

    from app.modules.teams.access import is_project_member

    assert await is_project_member(session, project.id, outsider.id) is False


async def test_granting_access_alongside_the_roster_line_still_needs_the_admin_gate(session):
    """The one field that changes access keeps the gate that has always owned it."""
    owner = await make_user(session)
    project = await make_project(session, owner.id)
    team = await make_team(session, project.id, name="Default Team", is_default=True)
    plain_member = await make_user(session)
    await make_membership(session, team.id, plain_member.id)
    newcomer = await make_user(session, full_name="Newcomer")

    service = RosterService(session)
    with pytest.raises(Exception) as excinfo:
        await service.add_members(
            project.id,
            [RosterMemberCreate(user_id=newcomer.id, grant_project_access=True)],
            actor_id=plain_member.id,
        )
    assert getattr(excinfo.value, "status_code", None) == 403

    # Refused before anything was written: no roster line, no membership.
    rows = await service.repo.list_for_project(project.id)
    assert [r for r, _, _ in rows if r.user_id == newcomer.id] == []


async def test_the_owner_can_grant_access_from_the_same_screen(session):
    """Assembling a team includes letting the people in, in one step."""
    owner = await make_user(session)
    project = await make_project(session, owner.id)
    await make_team(session, project.id, name="Default Team", is_default=True)
    newcomer = await make_user(session, full_name="Newcomer")

    service = RosterService(session)
    created = await service.add_members(
        project.id,
        [RosterMemberCreate(user_id=newcomer.id, grant_project_access=True, access_role="member")],
        actor_id=owner.id,
    )

    assert created[0].has_project_access is True
    from app.modules.teams.access import is_project_member

    assert await is_project_member(session, project.id, newcomer.id) is True


# ── The line survives what happens around it ─────────────────────────────────


async def test_deleting_a_team_detaches_its_people_instead_of_deleting_them(session):
    """They are still on the project; they have only stopped being grouped."""
    owner = await make_user(session)
    project = await make_project(session, owner.id)
    team = await make_team(session, project.id, name="Concrete gang")

    roster = RosterService(session)
    created = await roster.add_members(
        project.id,
        [RosterMemberCreate(display_name="Tomasz W.", team_id=team.id)],
        actor_id=owner.id,
    )
    assert created[0].team_name == "Concrete gang"

    await TeamService(session).delete_team(team.id, actor_id=owner.id)

    remaining, _ = await roster.list_roster(project.id, actor_id=owner.id)
    assert [line.display_name for line in remaining] == ["Tomasz W."]
    assert remaining[0].team_id is None


async def test_a_roster_line_from_another_project_is_not_reachable(session):
    """Same answer for "not yours" and "does not exist"."""
    owner = await make_user(session)
    mine = await make_project(session, owner.id)
    theirs = await make_project(session, owner.id)

    service = RosterService(session)
    created = await service.add_members(theirs.id, [RosterMemberCreate(display_name="Theirs")], actor_id=owner.id)

    with pytest.raises(Exception) as excinfo:
        await service.update_member(
            mine.id,
            created[0].id,
            RosterMemberUpdate(site_role="foreman"),
            actor_id=owner.id,
        )
    assert getattr(excinfo.value, "status_code", None) == 404


async def test_a_team_from_another_project_cannot_be_assigned(session):
    """A roster line can only be grouped into a team of its own project."""
    owner = await make_user(session)
    mine = await make_project(session, owner.id)
    theirs = await make_project(session, owner.id)
    foreign_team = await make_team(session, theirs.id, name="Somebody else")

    service = RosterService(session)
    created = await service.add_members(mine.id, [RosterMemberCreate(display_name="Mine")], actor_id=owner.id)

    with pytest.raises(Exception) as excinfo:
        await service.update_member(
            mine.id,
            created[0].id,
            RosterMemberUpdate(team_id=foreign_team.id),
            actor_id=owner.id,
        )
    assert getattr(excinfo.value, "status_code", None) == 404


# ── Tickets, dates and what the summary says ─────────────────────────────────


async def test_an_expired_ticket_is_reported_on_the_line_and_in_the_summary(session):
    """The one roster fact with a legal edge to it."""
    owner = await make_user(session)
    project = await make_project(session, owner.id)
    expired = (_today() - timedelta(days=30)).date()
    valid = (_today() + timedelta(days=200)).date()

    service = RosterService(session)
    await service.add_members(
        project.id,
        [
            RosterMemberCreate(
                display_name="Jens Brandt",
                site_role="foreman",
                certifications=[
                    {"kind": "Site safety card", "valid_until": expired.isoformat()},
                    {"kind": "First aid", "valid_until": valid.isoformat()},
                ],
            )
        ],
        actor_id=owner.id,
    )

    roster, _ = await service.list_roster(project.id, actor_id=owner.id)
    line = roster[0]
    assert line.expired_certification_count == 1
    lapsed = next(c for c in line.certifications if c.expired)
    assert lapsed.kind == "Site safety card"
    assert lapsed.days_remaining is not None and lapsed.days_remaining < 0

    summary = await service.summary(project.id, actor_id=owner.id)
    assert summary.expired_certification_count == 1
    assert summary.active_headcount == 1


async def test_somebody_whose_last_day_has_passed_is_flagged(session):
    """A roster that answers "who is on site" with somebody who left is wrong."""
    owner = await make_user(session)
    project = await make_project(session, owner.id)
    left = (_today() - timedelta(days=5)).date()

    service = RosterService(session)
    await service.add_members(
        project.id,
        [RosterMemberCreate(display_name="Gone Already", starts_on=left - timedelta(days=90), ends_on=left)],
        actor_id=owner.id,
    )

    roster, _ = await service.list_roster(project.id, actor_id=owner.id)
    assert roster[0].off_window is True
    summary = await service.summary(project.id, actor_id=owner.id)
    assert summary.off_window_count == 1


async def test_the_summary_counts_the_people_with_access_who_are_on_no_line(session):
    """The number that explains a name on a snag with no firm behind it."""
    owner = await make_user(session)
    project = await make_project(session, owner.id)
    team = await make_team(session, project.id, name="Default Team", is_default=True)
    ghost = await make_user(session, full_name="Has Access Only")
    await make_membership(session, team.id, ghost.id)

    service = RosterService(session)
    await service.add_members(project.id, [RosterMemberCreate(display_name="On The Roster")], actor_id=owner.id)

    summary = await service.summary(project.id, actor_id=owner.id)
    assert summary.unrostered_member_count == 1
    assert summary.without_access_count == 1


async def test_the_validation_report_names_the_expired_ticket(session):
    """The rules registered by this module have to see the roster, not just teams."""
    owner = await make_user(session)
    project = await make_project(session, owner.id)
    await make_team(session, project.id, name="Default Team", is_default=True)
    expired = (_today() - timedelta(days=10)).date()

    await RosterService(session).add_members(
        project.id,
        [
            RosterMemberCreate(
                display_name="Jens Brandt",
                site_role="foreman",
                certifications=[{"kind": "Site safety card", "valid_until": expired.isoformat()}],
            )
        ],
        actor_id=owner.id,
    )

    report = await TeamService(session).validate_project(project.id, actor_id=owner.id)
    ids = {f.rule_id for f in report.findings}
    assert "teams.roster_ticket_valid" in ids
    # Somebody IS in a supervisory role, so that rule must stay quiet.
    assert "teams.roster_site_lead" not in ids


async def test_a_roster_with_nobody_in_charge_is_reported(session):
    """A roster that cannot say who runs the job is incomplete, not empty."""
    owner = await make_user(session)
    project = await make_project(session, owner.id)
    await make_team(session, project.id, name="Default Team", is_default=True)

    await RosterService(session).add_members(
        project.id,
        [RosterMemberCreate(display_name="Operative One", site_role="operative")],
        actor_id=owner.id,
    )

    report = await TeamService(session).validate_project(project.id, actor_id=owner.id)
    assert "teams.roster_site_lead" in {f.rule_id for f in report.findings}


# ── Over the wire ────────────────────────────────────────────────────────────


async def test_the_roster_endpoints_answer_and_gate(session):
    """The route surface, including what a stranger gets."""
    owner = await make_user(session, full_name="Ada Owner")
    project = await make_project(session, owner.id)
    stranger = await make_user(session)

    app = build_app(session, caller_id=owner.id)
    async with http_client(app) as client:
        vocab = await client.get(f"{API_PREFIX}/roster/vocabulary")
        assert vocab.status_code == 200
        assert any(t["key"] == "electrical" for t in vocab.json()["trades"])
        assert any(r["key"] == "site_manager" and r["supervisory"] for r in vocab.json()["site_roles"])

        created = await client.post(
            f"{API_PREFIX}/project/{project.id}/roster",
            json={"members": [{"display_name": "Jens Brandt", "site_role": "foreman", "trade": "concrete"}]},
        )
        assert created.status_code == 201, created.text
        member_id = created.json()[0]["id"]

        listed = await client.get(f"{API_PREFIX}/project/{project.id}/roster")
        assert listed.status_code == 200
        page = listed.json()
        assert [row["display_name"] for row in page["items"]] == ["Jens Brandt"]
        assert page["total"] == 1
        assert page["offset"] == 0

        patched = await client.patch(
            f"{API_PREFIX}/project/{project.id}/roster/{member_id}",
            json={"allocation_percent": 60, "company_name": "Brandt Rohbau GmbH"},
        )
        assert patched.status_code == 200
        assert patched.json()["allocation_percent"] == 60
        assert patched.json()["company_name"] == "Brandt Rohbau GmbH"

        summary = await client.get(f"{API_PREFIX}/project/{project.id}/roster/summary")
        assert summary.status_code == 200
        assert summary.json()["company_count"] == 1

        removed = await client.delete(f"{API_PREFIX}/project/{project.id}/roster/{member_id}")
        assert removed.status_code == 204

    stranger_app = build_app(session, caller_id=stranger.id)
    async with http_client(stranger_app) as client:
        denied = await client.get(f"{API_PREFIX}/project/{project.id}/roster")
        assert denied.status_code == 404


async def test_a_short_roster_page_says_how_many_people_it_left_out(session):
    """What the envelope is for: a page that cannot be mistaken for the roster.

    ``total`` is asserted against the number of people put on the project, not
    against ``len(items)``. Comparing the page to itself passes just as happily
    when ``total`` is the page length, which is the defect being guarded here,
    so a test written that way would prove nothing.
    """
    owner = await make_user(session, full_name="Ada Owner")
    project = await make_project(session, owner.id)

    service = RosterService(session)
    await service.add_members(
        project.id,
        [RosterMemberCreate(display_name=f"Person {index:02d}", site_role="operative") for index in range(7)],
        actor_id=owner.id,
    )

    app = build_app(session, caller_id=owner.id)
    async with http_client(app) as client:
        first = await client.get(f"{API_PREFIX}/project/{project.id}/roster", params={"limit": 3})
        assert first.status_code == 200, first.text
        page = first.json()
        assert len(page["items"]) == 3
        assert page["total"] == 7
        assert page["offset"] == 0
        assert page["limit"] == 3

        second = await client.get(
            f"{API_PREFIX}/project/{project.id}/roster",
            params={"limit": 3, "offset": 3},
        )
        assert second.status_code == 200, second.text
        rest = second.json()
        assert rest["total"] == 7
        assert rest["offset"] == 3

    # Page two continues page one instead of repeating it, which is what the
    # slice being taken after the reading-order sort buys. Sliced in SQL, both
    # pages would be ordered by the database and sorted only within themselves.
    assert [row["display_name"] for row in page["items"]] == ["Person 00", "Person 01", "Person 02"]
    assert [row["display_name"] for row in rest["items"]] == ["Person 03", "Person 04", "Person 05"]


async def test_the_candidate_picker_states_how_many_people_it_did_not_show(session):
    """The defect this route shipped with: fifty names and silence about the rest.

    Somebody whose colleague sorted fifty-first read that silence as "the
    platform does not know them" and typed a duplicate contact. The total has
    to come from a count, because both searches apply the limit in the database
    and the rows in hand are already cut short - so this asserts it against the
    number of people created rather than against what came back.
    """
    owner = await make_user(session, full_name="Ada Owner")
    project = await make_project(session, owner.id)
    for index in range(6):
        await _make_contact(session, first="Zwiebel", last=f"Kandidat{index}", company="Zwiebel Bau GmbH")

    service = RosterService(session)
    shown, total = await service.list_candidates(project.id, actor_id=owner.id, query="Zwiebel", limit=2)
    assert len(shown) == 2
    assert total == 6

    app = build_app(session, caller_id=owner.id)
    async with http_client(app) as client:
        response = await client.get(
            f"{API_PREFIX}/project/{project.id}/roster/candidates",
            params={"q": "Zwiebel", "limit": 2},
        )
    assert response.status_code == 200, response.text
    page = response.json()
    assert len(page["items"]) == 2
    assert page["total"] == 6
    assert page["limit"] == 2
    # No offset is offered, so the body states the one it served. See
    # RosterService.list_candidates for why a second page over two
    # independently ordered sources cannot be served honestly.
    assert page["offset"] == 0


async def test_an_unknown_trade_is_refused(session):
    """A closed vocabulary that accepts anything is not a vocabulary."""
    owner = await make_user(session)
    project = await make_project(session, owner.id)

    app = build_app(session, caller_id=owner.id)
    async with http_client(app) as client:
        response = await client.post(
            f"{API_PREFIX}/project/{project.id}/roster",
            json={"members": [{"display_name": "Somebody", "trade": "spaceframe"}]},
        )
    assert response.status_code == 422


async def test_a_line_with_no_name_and_no_link_is_refused(session):
    """Every roster line has to render as a person, never as an id."""
    owner = await make_user(session)
    project = await make_project(session, owner.id)

    app = build_app(session, caller_id=owner.id)
    async with http_client(app) as client:
        response = await client.post(
            f"{API_PREFIX}/project/{project.id}/roster",
            json={"members": [{"site_role": "operative"}]},
        )
    assert response.status_code == 422


async def test_the_stored_line_keeps_at_most_one_link(session):
    """The check constraint is the last line of defence behind the schema."""
    owner = await make_user(session)
    project = await make_project(session, owner.id)
    user = await make_user(session)
    contact = await _make_contact(session, first="Jens", last="Brandt", company="Brandt Rohbau GmbH")

    session.add(
        RosterMember(
            project_id=project.id,
            user_id=user.id,
            contact_id=contact.id,
            display_name="Both at once",
        )
    )
    with pytest.raises(Exception):
        await session.flush()
    await session.rollback()
    assert uuid.UUID(str(project.id))  # the rollback is the assertion's context, not its subject
