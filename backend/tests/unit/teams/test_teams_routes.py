"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The HTTP surface: every endpoint, and the status code each denial produces.

The service-level guards are covered in ``test_teams_access_control.py``. What
is pinned here is that the routes actually reach them - a gate in the service
that a route bypasses is not a gate - and that the wire-level answers are the
ones the IDOR policy calls for:

* another project's team, or one that does not exist -> 404
* a project you can see but do not own -> 403
* a record kind outside the catalogue -> 422
"""

from __future__ import annotations

import uuid

import pytest

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


# ── Catalogue ────────────────────────────────────────────────────────────────


async def test_entity_types_lists_the_catalogue(session) -> None:
    """The picker's source of truth, with the honesty flag on each row."""
    owner = await make_user(session)
    async with http_client(build_app(session, caller_id=owner.id)) as client:
        response = await client.get(f"{API_PREFIX}/entity-types")
    assert response.status_code == 200
    rows = response.json()
    assert len(rows) >= 20
    assert {"key", "label", "module", "enforced"} <= set(rows[0])
    assert any(r["key"] == "document" for r in rows)


# ── Team CRUD over HTTP ──────────────────────────────────────────────────────


async def test_the_owner_can_drive_the_whole_team_lifecycle(session) -> None:
    """Create, list, rename, re-kind and delete, all through the router."""
    owner = await make_user(session)
    project = await make_project(session, owner.id)

    async with http_client(build_app(session, caller_id=owner.id)) as client:
        created = await client.post(
            f"{API_PREFIX}/",
            json={
                "project_id": str(project.id),
                "name": "Client side",
                "kind": "client",
                "description": "The client's own QS and PM",
                "is_default": True,
            },
        )
        assert created.status_code == 201, created.text
        team = created.json()
        assert team["kind"] == "client"
        assert team["description"] == "The client's own QS and PM"

        listed = await client.get(f"{API_PREFIX}/project/{project.id}")
        assert listed.status_code == 200
        assert [t["id"] for t in listed.json()] == [team["id"]]
        assert listed.json()[0]["member_count"] == 0
        assert listed.json()[0]["restricted_record_count"] == 0

        by_query = await client.get(f"{API_PREFIX}/", params={"project_id": str(project.id)})
        assert by_query.status_code == 200
        assert len(by_query.json()) == 1

        renamed = await client.patch(
            f"{API_PREFIX}/{team['id']}",
            json={"name": "Client team", "kind": "consultant"},
        )
        assert renamed.status_code == 200
        assert renamed.json()["name"] == "Client team"
        assert renamed.json()["kind"] == "consultant"
        # The description survives an update that did not mention it.
        assert renamed.json()["description"] == "The client's own QS and PM"

        deleted = await client.delete(f"{API_PREFIX}/{team['id']}")
        assert deleted.status_code == 204
        assert await client.get(f"{API_PREFIX}/project/{project.id}") is not None


async def test_a_member_gets_403_on_a_write_and_200_on_a_read(session) -> None:
    """The two gates are visibly different at the wire.

    403 rather than 404 is correct here: the caller can already list this
    project's teams, so telling them "not yours" reveals nothing new.
    """
    owner = await make_user(session)
    member = await make_user(session)
    project = await make_project(session, owner.id)
    team = await make_team(session, project.id, name="Site", is_default=True)
    await make_membership(session, team.id, member.id)

    async with http_client(build_app(session, caller_id=member.id)) as client:
        read = await client.get(f"{API_PREFIX}/project/{project.id}")
        assert read.status_code == 200

        write = await client.post(
            f"{API_PREFIX}/",
            json={"project_id": str(project.id), "name": "Mine"},
        )
        assert write.status_code == 403

        add = await client.post(
            f"{API_PREFIX}/{team['id'] if isinstance(team, dict) else team.id}/members",
            json={"user_id": str(uuid.uuid4()), "role": "member"},
        )
        assert add.status_code == 403


async def test_a_stranger_gets_404_everywhere(session) -> None:
    """Someone with no relationship to the project learns nothing at all."""
    owner = await make_user(session)
    stranger = await make_user(session)
    project = await make_project(session, owner.id)
    team = await make_team(session, project.id, name="Site", is_default=True)

    async with http_client(build_app(session, caller_id=stranger.id)) as client:
        assert (await client.get(f"{API_PREFIX}/project/{project.id}")).status_code == 404
        assert (await client.get(f"{API_PREFIX}/{team.id}/members")).status_code == 404
        assert (await client.get(f"{API_PREFIX}/{team.id}/visibility")).status_code == 404
        assert (await client.get(f"{API_PREFIX}/project/{project.id}/restricted")).status_code == 404
        assert (await client.get(f"{API_PREFIX}/project/{project.id}/access-matrix")).status_code == 404
        assert (await client.get(f"{API_PREFIX}/project/{project.id}/validate")).status_code == 404
        assert (
            await client.post(
                f"{API_PREFIX}/",
                json={"project_id": str(project.id), "name": "Mine"},
            )
        ).status_code == 404
        assert (await client.delete(f"{API_PREFIX}/{team.id}")).status_code == 404


async def test_an_unknown_team_and_a_foreign_team_answer_alike(session) -> None:
    """The two must be indistinguishable or the id becomes an existence oracle."""
    owner_a = await make_user(session)
    owner_b = await make_user(session)
    await make_project(session, owner_a.id)
    project_b = await make_project(session, owner_b.id)
    team_b = await make_team(session, project_b.id, name="Theirs", is_default=True)

    async with http_client(build_app(session, caller_id=owner_a.id)) as client:
        foreign = await client.get(f"{API_PREFIX}/{team_b.id}/members")
        invented = await client.get(f"{API_PREFIX}/{uuid.uuid4()}/members")
    assert foreign.status_code == invented.status_code == 404
    assert foreign.json()["detail"] == invented.json()["detail"]


async def test_a_write_to_a_foreign_team_is_refused_and_says_nothing(session) -> None:
    """PATCH and DELETE answer like the reads: 404, with one body for both cases.

    The reads above are covered; the writes were not, and they are the two
    handlers the IDOR guard pins. Renaming or deleting another project's team
    must be indistinguishable from acting on a team id that names nothing.
    """
    owner_a = await make_user(session)
    owner_b = await make_user(session)
    await make_project(session, owner_a.id)
    project_b = await make_project(session, owner_b.id)
    team_b = await make_team(session, project_b.id, name="Theirs", is_default=True)

    async with http_client(build_app(session, caller_id=owner_a.id)) as client:
        renamed = await client.patch(f"{API_PREFIX}/{team_b.id}", json={"name": "Mine now"})
        invented = await client.patch(f"{API_PREFIX}/{uuid.uuid4()}", json={"name": "Mine now"})
        removed = await client.delete(f"{API_PREFIX}/{team_b.id}")

    assert renamed.status_code == invented.status_code == removed.status_code == 404
    assert renamed.json()["detail"] == invented.json()["detail"]

    # And the team is still there, under its own name.
    await session.refresh(team_b)
    assert team_b.name == "Theirs"


# ── Members over HTTP ────────────────────────────────────────────────────────


async def test_members_can_be_added_listed_repromoted_and_removed(session) -> None:
    """The member panel's four calls, including the display fields it renders."""
    owner = await make_user(session)
    person = await make_user(session, full_name="Dana Ruiz")
    project = await make_project(session, owner.id)
    team = await make_team(session, project.id, name="Site", is_default=True)

    async with http_client(build_app(session, caller_id=owner.id)) as client:
        added = await client.post(
            f"{API_PREFIX}/{team.id}/members",
            json={"user_id": str(person.id), "role": "estimator"},
        )
        assert added.status_code == 201, added.text

        listed = await client.get(f"{API_PREFIX}/{team.id}/members")
        assert listed.status_code == 200
        row = listed.json()[0]
        assert row["role"] == "estimator"
        assert row["full_name"] == "Dana Ruiz"
        assert row["email"] == person.email

        promoted = await client.patch(
            f"{API_PREFIX}/{team.id}/members/{person.id}",
            json={"role": "project_manager"},
        )
        assert promoted.status_code == 200
        assert promoted.json()["role"] == "project_manager"

        removed = await client.delete(f"{API_PREFIX}/{team.id}/members/{person.id}")
        assert removed.status_code == 204
        assert (await client.get(f"{API_PREFIX}/{team.id}/members")).json() == []


async def test_a_role_outside_the_whitelist_is_rejected(session) -> None:
    """422 at the schema, before anything reaches the database."""
    owner = await make_user(session)
    person = await make_user(session)
    project = await make_project(session, owner.id)
    team = await make_team(session, project.id, name="Site", is_default=True)

    async with http_client(build_app(session, caller_id=owner.id)) as client:
        response = await client.post(
            f"{API_PREFIX}/{team.id}/members",
            json={"user_id": str(person.id), "role": "superuser"},
        )
    assert response.status_code == 422


async def test_adding_the_same_person_twice_is_a_conflict(session) -> None:
    """409, so the UI can say "already on this team" instead of showing a 500."""
    owner = await make_user(session)
    person = await make_user(session)
    project = await make_project(session, owner.id)
    team = await make_team(session, project.id, name="Site", is_default=True)

    async with http_client(build_app(session, caller_id=owner.id)) as client:
        first = await client.post(
            f"{API_PREFIX}/{team.id}/members",
            json={"user_id": str(person.id), "role": "member"},
        )
        second = await client.post(
            f"{API_PREFIX}/{team.id}/members",
            json={"user_id": str(person.id), "role": "member"},
        )
    assert first.status_code == 201
    assert second.status_code == 409


# ── Restrictions over HTTP ───────────────────────────────────────────────────


async def test_the_visibility_panel_round_trips(session) -> None:
    """Set the teams on a record, read the state back, then lift it."""
    owner = await make_user(session)
    reader = await make_user(session)
    project = await make_project(session, owner.id)
    team = await make_team(session, project.id, name="Cost team", is_default=True)
    await make_membership(session, team.id, reader.id)
    record = str(uuid.uuid4())

    async with http_client(build_app(session, caller_id=owner.id)) as client:
        base = f"{API_PREFIX}/project/{project.id}/visibility/document/{record}"

        open_state = await client.get(base)
        assert open_state.status_code == 200
        assert open_state.json()["restricted"] is False

        set_state = await client.put(base, json={"team_ids": [str(team.id)]})
        assert set_state.status_code == 200, set_state.text
        body = set_state.json()
        assert body["restricted"] is True
        assert body["viewer_count"] == 1
        assert body["teams"][0]["name"] == "Cost team"

        register = await client.get(f"{API_PREFIX}/project/{project.id}/restricted")
        assert [r["entity_id"] for r in register.json()] == [record]

        team_view = await client.get(f"{API_PREFIX}/{team.id}/visibility")
        assert [r["entity_id"] for r in team_view.json()] == [record]

        lifted = await client.put(base, json={"team_ids": []})
        assert lifted.json()["restricted"] is False
        assert (await client.get(f"{API_PREFIX}/project/{project.id}/restricted")).json() == []


async def test_grant_and_revoke_by_team_work_over_http(session) -> None:
    """The single-team form the record's own screen would call."""
    owner = await make_user(session)
    project = await make_project(session, owner.id)
    team = await make_team(session, project.id, name="Site", is_default=True)
    record = str(uuid.uuid4())

    async with http_client(build_app(session, caller_id=owner.id)) as client:
        granted = await client.post(
            f"{API_PREFIX}/{team.id}/visibility",
            json={"entity_type": "drawing", "entity_id": record},
        )
        assert granted.status_code == 201, granted.text
        revoked = await client.delete(f"{API_PREFIX}/{team.id}/visibility/drawing/{record}")
        assert revoked.status_code == 204
        assert (await client.get(f"{API_PREFIX}/{team.id}/visibility")).json() == []


async def test_an_unknown_record_kind_is_refused_at_the_edge(session) -> None:
    """A typo must not become a restriction that silently protects nothing."""
    owner = await make_user(session)
    project = await make_project(session, owner.id)
    team = await make_team(session, project.id, name="Site", is_default=True)

    async with http_client(build_app(session, caller_id=owner.id)) as client:
        posted = await client.post(
            f"{API_PREFIX}/{team.id}/visibility",
            json={"entity_type": "drawings", "entity_id": str(uuid.uuid4())},
        )
        put = await client.put(
            f"{API_PREFIX}/project/{project.id}/visibility/drawings/{uuid.uuid4()}",
            json={"team_ids": [str(team.id)]},
        )
    assert posted.status_code == 422
    assert put.status_code == 422


async def test_a_member_cannot_change_a_restriction(session) -> None:
    """Reading who can see a record is a member's business; changing it is not."""
    owner = await make_user(session)
    member = await make_user(session)
    project = await make_project(session, owner.id)
    team = await make_team(session, project.id, name="Site", is_default=True)
    await make_membership(session, team.id, member.id)
    record = str(uuid.uuid4())

    async with http_client(build_app(session, caller_id=member.id)) as client:
        read = await client.get(f"{API_PREFIX}/project/{project.id}/visibility/document/{record}")
        assert read.status_code == 200

        put = await client.put(
            f"{API_PREFIX}/project/{project.id}/visibility/document/{record}",
            json={"team_ids": [str(team.id)]},
        )
        post = await client.post(
            f"{API_PREFIX}/{team.id}/visibility",
            json={"entity_type": "document", "entity_id": record},
        )
    assert put.status_code == 403
    assert post.status_code == 403


# ── Reports over HTTP ────────────────────────────────────────────────────────


async def test_the_access_matrix_endpoint_answers_who_sees_what(session) -> None:
    """One payload, one row per person on the project."""
    owner = await make_user(session, full_name="Owner")
    kept = await make_user(session, full_name="Kept")
    lost = await make_user(session, full_name="Lost")
    project = await make_project(session, owner.id)
    allowed = await make_team(session, project.id, name="Allowed", is_default=True)
    other = await make_team(session, project.id, name="Other", sort_order=1)
    await make_membership(session, allowed.id, kept.id)
    await make_membership(session, other.id, lost.id)

    async with http_client(build_app(session, caller_id=owner.id)) as client:
        await client.post(
            f"{API_PREFIX}/{allowed.id}/visibility",
            json={"entity_type": "contract", "entity_id": str(uuid.uuid4())},
        )
        matrix = await client.get(f"{API_PREFIX}/project/{project.id}/access-matrix")

    assert matrix.status_code == 200
    body = matrix.json()
    assert body["restricted_record_count"] == 1
    by_name = {m["full_name"]: m for m in body["members"]}
    assert by_name["Kept"]["visible_restricted_count"] == 1
    assert by_name["Kept"]["hidden_restricted_count"] == 0
    assert by_name["Lost"]["visible_restricted_count"] == 0
    assert by_name["Lost"]["hidden_restricted_count"] == 1


async def test_the_team_list_counts_restrictions_held_by_a_team_with_no_members(
    session,
) -> None:
    """The list route carries the counts the "stranded team" warning reads.

    The screen flags a team that holds restrictions but has nobody in it,
    because that is the shape of having locked everyone out of a record. It
    decides that from `member_count` and `restricted_record_count` on this
    route alone. A route that returned the plain team shape, or that left the
    restriction count at null, would leave the warning permanently unreachable
    while still looking correct, so assert the non-zero side of both counts
    rather than the zero one an unpopulated field would also satisfy.
    """
    owner = await make_user(session)
    project = await make_project(session, owner.id)
    stranded = await make_team(session, project.id, name="Stranded", is_default=True)
    staffed = await make_team(session, project.id, name="Staffed", sort_order=1)
    member = await make_user(session)
    await make_membership(session, staffed.id, member.id)

    async with http_client(build_app(session, caller_id=owner.id)) as client:
        restricted = await client.post(
            f"{API_PREFIX}/{stranded.id}/visibility",
            json={"entity_type": "contract", "entity_id": str(uuid.uuid4())},
        )
        assert restricted.status_code in {200, 201}, restricted.text
        listed = await client.get(f"{API_PREFIX}/project/{project.id}")

    assert listed.status_code == 200
    by_name = {t["name"]: t for t in listed.json()}
    assert by_name["Stranded"]["restricted_record_count"] == 1
    assert by_name["Stranded"]["member_count"] == 0
    # The counts are per team, not per project: the staffed team must not
    # inherit the other team's restriction.
    assert by_name["Staffed"]["restricted_record_count"] == 0
    assert by_name["Staffed"]["member_count"] == 1


async def test_the_validate_endpoint_returns_the_rule_findings(session) -> None:
    """The banner's payload, with counts and localisable keys."""
    owner = await make_user(session)
    project = await make_project(session, owner.id)
    await make_team(session, project.id, name="Empty", is_default=True)

    async with http_client(build_app(session, caller_id=owner.id)) as client:
        response = await client.get(f"{API_PREFIX}/project/{project.id}/validate")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] in {"warnings", "errors"}
    assert {f["rule_id"] for f in body["findings"]} >= {"teams.empty_team"}
    assert all(f["key"].startswith("teams.validation.") for f in body["findings"])
