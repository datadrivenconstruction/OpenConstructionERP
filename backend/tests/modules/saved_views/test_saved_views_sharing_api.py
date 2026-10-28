# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠End-to-end behaviour of the saved-views API against a real database.

Three things only show up once rows and identities exist:

* sharing a view with a team hands the DEFINITION to that team and to nobody
  else, and never widens what the reader is allowed to see;
* saving a second view under a name the owner already used is a 409 that names
  the collision, not the 500 an ``IntegrityError`` produces on its way out;
* a view whose entity has drifted is marked before anyone clicks it, and its
  validation report says which field moved.

Three users share one project: its owner, a member of the team the view is
shared with, and a member of a different team on the same project. The third
one is the whole point - team membership grants project access, so a project
member who is not in the named team is exactly the reader a team share has to
exclude.

The app is built once per module (booting it is the expensive part).
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient


@pytest_asyncio.fixture(scope="module")
async def app_instance():
    from app.config import get_settings

    get_settings.cache_clear()
    from app.main import create_app

    app = create_app()
    async with app.router.lifespan_context(app):
        from app.database import Base, engine

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        yield app


@pytest_asyncio.fixture(scope="module")
async def client(app_instance):
    transport = ASGITransport(app=app_instance)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def _register(client: AsyncClient, tag: str) -> tuple[dict[str, str], uuid.UUID]:
    """Register, activate and log in one editor; return its header and id."""
    email = f"saved-views-{tag}@test.io"
    password = f"SavedViews{tag}9"
    reg = await client.post(
        "/api/v1/users/auth/register",
        json={
            "email": email,
            "password": password,
            "full_name": f"Saved Views {tag}",
            "role": "editor",
        },
    )
    assert reg.status_code in (200, 201), reg.text

    from sqlalchemy import select, update

    from app.database import async_session_factory
    from app.modules.users.models import User

    async with async_session_factory() as session:
        await session.execute(
            update(User).where(User.email == email.lower()).values(role="editor", is_active=True),
        )
        await session.commit()
        user_id = (await session.execute(select(User.id).where(User.email == email.lower()))).scalar_one()

    login = await client.post(
        "/api/v1/users/auth/login",
        json={"email": email, "password": password},
    )
    token = login.json().get("access_token", "")
    assert token, login.text
    return {"Authorization": f"Bearer {token}"}, user_id


@pytest_asyncio.fixture(scope="module")
async def world(client: AsyncClient):
    """One project, two teams on it, three users, plus one unrelated stranger.

    Built through the ORM rather than the teams API: this file is about saved
    views, and the teams module owns its own tests.

    The stranger belongs to neither team and to neither project role, and owns a
    second project of their own. Sharing decisions are supposed to be resolved
    against the view's OWN project, so the stranger is the reader who must stay
    out however they address the request.
    """
    tag = uuid.uuid4().hex[:8]
    owner_header, owner_id = await _register(client, f"owner-{tag}")
    insider_header, insider_id = await _register(client, f"insider-{tag}")
    outsider_header, outsider_id = await _register(client, f"outsider-{tag}")
    stranger_header, stranger_id = await _register(client, f"stranger-{tag}")

    from app.database import async_session_factory
    from app.modules.projects.models import Project
    from app.modules.teams.models import Team, TeamMembership

    async with async_session_factory() as session:
        project = Project(name=f"Saved views sharing {tag}", owner_id=owner_id)
        elsewhere = Project(name=f"Saved views elsewhere {tag}", owner_id=stranger_id)
        session.add_all([project, elsewhere])
        await session.flush()

        shared_team = Team(project_id=project.id, name=f"Roof package {tag}")
        other_team = Team(project_id=project.id, name=f"Groundworks {tag}")
        session.add_all([shared_team, other_team])
        await session.flush()

        session.add_all(
            [
                TeamMembership(team_id=shared_team.id, user_id=owner_id, role="lead"),
                TeamMembership(team_id=shared_team.id, user_id=insider_id, role="member"),
                TeamMembership(team_id=other_team.id, user_id=outsider_id, role="member"),
            ]
        )
        await session.commit()

        return {
            "project_id": str(project.id),
            "elsewhere_project_id": str(elsewhere.id),
            "shared_team_id": str(shared_team.id),
            "other_team_id": str(other_team.id),
            "owner": owner_header,
            "insider": insider_header,
            "outsider": outsider_header,
            "stranger": stranger_header,
        }


def _payload(world: dict, **overrides: object) -> dict:
    """A create request for a project-entity view."""
    payload: dict[str, object] = {
        "entity_type": "project",
        "name": f"View {uuid.uuid4().hex[:8]}",
        "description": "Everything still open",
        "project_id": world["project_id"],
        "spec": {
            "sort": [{"field": "created_at", "direction": "desc"}],
            "columns": ["name", "status"],
            "page": 1,
            "page_size": 25,
        },
    }
    payload.update(overrides)
    return payload


async def _create(client: AsyncClient, world: dict, who: str = "owner", **overrides: object):
    return await client.post("/api/v1/saved-views/", json=_payload(world, **overrides), headers=world[who])


# ── Naming ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_creating_a_view_returns_it_marked_healthy(client: AsyncClient, world) -> None:
    """The happy path, and the staleness flags ride along with no extra call."""
    resp = await _create(client, world)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["share_scope"] == "private"
    assert body["shared_team_id"] is None
    assert body["is_stale"] is False
    assert body["stale_reasons"] == []


@pytest.mark.asyncio
async def test_a_duplicate_name_is_a_409_not_a_500(client: AsyncClient, world) -> None:
    """The unique index used to surface as an unhandled IntegrityError.

    A 500 also means the request's transaction has already been aborted, so
    the check has to happen before the insert, not after it fails.
    """
    name = f"Twice over {uuid.uuid4().hex[:6]}"
    first = await _create(client, world, name=name)
    assert first.status_code == 201, first.text

    second = await _create(client, world, name=name)
    assert second.status_code == 409, second.text
    assert name in second.json()["detail"]


@pytest.mark.asyncio
async def test_the_same_name_is_free_for_a_different_owner(client: AsyncClient, world) -> None:
    """The constraint is per owner, so one person's name does not block another's."""
    name = f"Shared wording {uuid.uuid4().hex[:6]}"
    assert (await _create(client, world, name=name)).status_code == 201
    assert (await _create(client, world, "insider", name=name)).status_code == 201


@pytest.mark.asyncio
async def test_renaming_a_view_onto_a_taken_name_is_refused(client: AsyncClient, world) -> None:
    """A rename is the same collision by another route."""
    taken = f"Occupied {uuid.uuid4().hex[:6]}"
    assert (await _create(client, world, name=taken)).status_code == 201
    mover = await _create(client, world)
    assert mover.status_code == 201

    resp = await client.patch(
        f"/api/v1/saved-views/{mover.json()['id']}",
        json={"name": taken},
        headers=world["owner"],
    )
    assert resp.status_code == 409, resp.text


@pytest.mark.asyncio
async def test_renaming_a_view_to_its_own_name_is_allowed(client: AsyncClient, world) -> None:
    """A no-op rename must not be reported as a clash with itself."""
    created = await _create(client, world)
    assert created.status_code == 201
    view = created.json()
    resp = await client.patch(
        f"/api/v1/saved-views/{view['id']}",
        json={"name": view["name"], "description": "reworded"},
        headers=world["owner"],
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["description"] == "reworded"


# ── Team sharing ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_team_share_reaches_the_team_and_stops_there(client: AsyncClient, world) -> None:
    """The never-widen rule, stated as a test.

    The outsider is a member of the same project through another team, so the
    project-access half of the check passes for them. Only the team half keeps
    them out, which is exactly the half that would disappear if a team share
    were resolved as "shared with the project".
    """
    created = await _create(
        client,
        world,
        share_scope="team",
        shared_team_id=world["shared_team_id"],
    )
    assert created.status_code == 201, created.text
    view = created.json()
    assert view["share_scope"] == "team"
    assert view["shared_team_id"] == world["shared_team_id"]

    seen = await client.get(f"/api/v1/saved-views/{view['id']}", headers=world["insider"])
    assert seen.status_code == 200, seen.text

    refused = await client.get(f"/api/v1/saved-views/{view['id']}", headers=world["outsider"])
    assert refused.status_code == 404, refused.text


@pytest.mark.asyncio
async def test_a_team_share_lists_only_for_the_team(client: AsyncClient, world) -> None:
    """The listing has to agree with the single-view read, or the UI leaks names."""
    created = await _create(
        client,
        world,
        share_scope="team",
        shared_team_id=world["shared_team_id"],
    )
    assert created.status_code == 201, created.text
    view_id = created.json()["id"]

    def _ids(resp) -> set[str]:
        return {row["id"] for row in resp.json()}

    insider_list = await client.get(
        "/api/v1/saved-views/",
        params={"project_id": world["project_id"]},
        headers=world["insider"],
    )
    assert view_id in _ids(insider_list)

    outsider_list = await client.get(
        "/api/v1/saved-views/",
        params={"project_id": world["project_id"]},
        headers=world["outsider"],
    )
    assert view_id not in _ids(outsider_list)


@pytest.mark.asyncio
async def test_a_project_share_reaches_every_project_member(client: AsyncClient, world) -> None:
    """The contrast case: a project share is meant to reach the outsider."""
    created = await _create(client, world, share_scope="project")
    assert created.status_code == 201, created.text
    seen = await client.get(
        f"/api/v1/saved-views/{created.json()['id']}",
        headers=world["outsider"],
    )
    assert seen.status_code == 200, seen.text


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_echoing_the_project_id_does_not_admit_a_stranger(client: AsyncClient, world) -> None:
    """Visibility is resolved against the view's project, not the caller's claim.

    ``project_id`` is a query parameter. Admitting a reader because the value
    they sent matches the view's project would hand every project-shared
    definition to anyone holding ``saved_views.read``, since the reader chooses
    what to send. The stranger here belongs to neither team and to neither role
    on that project, and sends its id anyway, on every path that reads a
    definition.
    """
    created = await _create(client, world, share_scope="project")
    assert created.status_code == 201, created.text
    view_id = created.json()["id"]
    params = {"project_id": world["project_id"]}

    for method, url in (
        ("get", f"/api/v1/saved-views/{view_id}"),
        ("get", f"/api/v1/saved-views/{view_id}/validation"),
        ("get", f"/api/v1/saved-views/{view_id}/runs"),
        ("post", f"/api/v1/saved-views/{view_id}/run"),
    ):
        resp = await getattr(client, method)(url, params=params, headers=world["stranger"])
        assert resp.status_code == 404, f"{method.upper()} {url} -> {resp.status_code}: {resp.text}"


@pytest.mark.asyncio
async def test_a_shared_view_cannot_be_run_against_a_project_its_reader_cannot_reach(
    client: AsyncClient,
    world,
) -> None:
    """Seeing a definition is not permission to point it anywhere.

    Sharing decides who reads the spec; the scoper still decides which rows come
    back, under the reader's own identity and against the project the run names.
    The outsider may read this project-shared view, so the refusal below can only
    come from the second half - the project they tried to run it against.
    """
    created = await _create(client, world, share_scope="project")
    assert created.status_code == 201, created.text
    view_id = created.json()["id"]

    allowed = await client.post(
        f"/api/v1/saved-views/{view_id}/run",
        params={"project_id": world["project_id"]},
        headers=world["outsider"],
    )
    assert allowed.status_code == 200, allowed.text

    retargeted = await client.post(
        f"/api/v1/saved-views/{view_id}/run",
        params={"project_id": world["elsewhere_project_id"]},
        headers=world["outsider"],
    )
    assert retargeted.status_code == 404, retargeted.text


@pytest.mark.asyncio
async def test_sharing_with_a_team_you_are_not_in_is_refused(client: AsyncClient, world) -> None:
    """You cannot hand a view to a group you do not belong to."""
    resp = await _create(
        client,
        world,
        "insider",
        share_scope="team",
        shared_team_id=world["other_team_id"],
    )
    assert resp.status_code == 422, resp.text


@pytest.mark.asyncio
async def test_a_team_share_without_a_team_is_rejected_by_the_schema(client: AsyncClient, world) -> None:
    """Scope and pin are decided together, so one without the other never lands."""
    resp = await _create(client, world, share_scope="team")
    assert resp.status_code == 422, resp.text


@pytest.mark.asyncio
async def test_a_team_pin_on_a_project_share_is_rejected(client: AsyncClient, world) -> None:
    """A team id on a project-wide share is a contradiction, not a hint."""
    resp = await _create(
        client,
        world,
        share_scope="project",
        shared_team_id=world["shared_team_id"],
    )
    assert resp.status_code == 422, resp.text


@pytest.mark.asyncio
async def test_widening_a_team_share_to_the_project_clears_the_team_pin(client: AsyncClient, world) -> None:
    """Patching the scope alone must not leave a stale team id behind it."""
    created = await _create(
        client,
        world,
        share_scope="team",
        shared_team_id=world["shared_team_id"],
    )
    assert created.status_code == 201, created.text
    resp = await client.patch(
        f"/api/v1/saved-views/{created.json()['id']}",
        json={"share_scope": "project"},
        headers=world["owner"],
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["share_scope"] == "project"
    assert resp.json()["shared_team_id"] is None


# ── Health and telemetry ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_drifted_view_is_marked_and_explained(client: AsyncClient, world) -> None:
    """A field leaving the whitelist has to be visible without running the view.

    The registered entity is narrowed for the duration of this test and put
    back afterwards, which is what a module upgrade does to a saved view that
    was written before it.
    """
    created = await _create(
        client,
        world,
        spec={
            "where": {
                "join": "and",
                "conditions": [{"field": "region", "op": "eq", "value": "DACH"}],
            },
            "page": 1,
            "page_size": 25,
        },
    )
    assert created.status_code == 201, created.text
    view_id = created.json()["id"]
    assert created.json()["is_stale"] is False

    from dataclasses import replace

    from app.modules.saved_views.registry import entity_registry

    original = entity_registry.get("project")
    assert original is not None
    narrowed_fields = {k: v for k, v in original.fields.items() if k != "region"}
    entity_registry._entities["project"] = replace(original, fields=narrowed_fields)  # noqa: SLF001
    try:
        fetched = await client.get(
            f"/api/v1/saved-views/{view_id}",
            params={"project_id": world["project_id"]},
            headers=world["owner"],
        )
        assert fetched.status_code == 200, fetched.text
        assert fetched.json()["is_stale"] is True
        assert any("region" in reason for reason in fetched.json()["stale_reasons"])

        report = await client.get(
            f"/api/v1/saved-views/{view_id}/validation",
            params={"project_id": world["project_id"]},
            headers=world["owner"],
        )
        assert report.status_code == 200, report.text
        body = report.json()
        assert body["error_count"] >= 1
        assert "saved_views.fields_whitelisted" in {f["rule_id"] for f in body["findings"]}

        # And the run itself refuses rather than answering a different question.
        run = await client.post(
            f"/api/v1/saved-views/{view_id}/run",
            params={"project_id": world["project_id"]},
            headers=world["owner"],
        )
        assert run.status_code == 422, run.text
    finally:
        entity_registry._entities["project"] = original  # noqa: SLF001


@pytest.mark.asyncio
async def test_run_telemetry_is_readable_after_a_run(client: AsyncClient, world) -> None:
    """The run table has been written since the module shipped; this reads it."""
    created = await _create(client, world)
    assert created.status_code == 201, created.text
    view_id = created.json()["id"]

    run = await client.post(
        f"/api/v1/saved-views/{view_id}/run",
        params={"project_id": world["project_id"]},
        headers=world["owner"],
    )
    assert run.status_code == 200, run.text

    stats = await client.get(
        f"/api/v1/saved-views/{view_id}/runs",
        params={"project_id": world["project_id"]},
        headers=world["owner"],
    )
    assert stats.status_code == 200, stats.text
    body = stats.json()
    assert body["total_runs"] == 1
    assert body["outcomes"] == {"ok": 1}
    assert body["last_outcome"] == "ok"
    assert body["last_run_at"] is not None
    assert body["max_elapsed_ms"] is not None


@pytest.mark.asyncio
async def test_telemetry_is_refused_to_a_reader_who_cannot_see_the_view(client: AsyncClient, world) -> None:
    """Run counts are about the view, so they answer to the same visibility check."""
    created = await _create(client, world)
    assert created.status_code == 201, created.text
    stats = await client.get(
        f"/api/v1/saved-views/{created.json()['id']}/runs",
        params={"project_id": world["project_id"]},
        headers=world["outsider"],
    )
    assert stats.status_code == 404, stats.text
