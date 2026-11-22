# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Who may decide that another company participates in a project, over HTTP, against PostgreSQL.

ADR 006, stage 2. The table and its revision are pinned by
``test_the_participant_grant_table_is_the_same_however_it_was_built.py``; this
file pins the four routes on top of it and the one rule behind all of them.

The identity is the variable under test, and the world is built so that every
interesting answer is a different person rather than a different flag:

* a manager of the company that owns the project - the only caller who may
  decide;
* an editor of that same company - right company, not enough authority;
* a manager of that company whose membership is suspended - was entitled, is not;
* a manager of the invited company - holds a live grant, and a grant is not
  authority (this is what makes sub-granting impossible rather than forbidden);
* a manager of a third company, and the same person holding the ``admin`` role -
  an instance administrator is trusted with the instance, not with handing one
  company's project to another;
* a manager of a fourth company, used to hold a grant id that belongs to a
  different project.

Every request goes through the real router, the real dependencies and the real
service against a real database. Nothing here calls the service directly except
the ownership-change test, which has no route: no product path moves a project
between companies today, and the last test in this file says so out loud rather
than pretending to exercise an endpoint that does not exist.

The role recorded beside every observation is the connecting superuser, because
these are application writes and not migration DDL: ``oe_app`` is what a request
transaction runs as once row-level security is enforced, and the grant table
carries no ``tenant_id``, so no policy binds it either way. The test asserts what
it observes instead of assuming it.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.projects.grants import GRANT_ENTITY_TYPE, suspend_grants_on_ownership_change
from app.modules.projects.models import Project, ProjectParticipantGrant
from app.modules.projects.permissions import register_project_permissions
from app.modules.projects.router import router
from app.modules.users.models import Membership, Organization, User
from tests._pg import isolated_engine

pytestmark = [pytest.mark.asyncio, pytest.mark.tenant_isolation]

BASE = "/api/v1/projects"

#: Tables whose row counts are compared before and after a revocation. The point
#: of the list is that it contains everything a revocation might have been
#: implemented as an update over, and the assertion is that none of them moved.
_UNTOUCHED_TABLES = (
    "oe_projects_project",
    "oe_projects_participant_grant",
    "oe_users_organization",
    "oe_users_membership",
    "oe_users_user",
    "oe_teams_team",
    # The person layer: team membership and the site roster behind it. Listed
    # because "revocation is not retroactive" is a claim about people as much as
    # about rows - a revocation that quietly removed the grantee's staff from the
    # project's team would close access by destroying the evidence of who was on it.
    "oe_teams_membership",
    "oe_teams_roster_member",
    "oe_activity_log",
)


@pytest_asyncio.fixture
async def world():
    """A throwaway database holding two companies, a project and six identities."""
    register_project_permissions()
    async with isolated_engine() as engine:
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with factory() as session:
            w = await _build(session)
            await session.commit()
        w.factory = factory
        w.engine = engine
        yield w


class _World:
    """The identities, the two companies and the project they fight over."""

    def __init__(self) -> None:
        self.factory: async_sessionmaker[AsyncSession] | None = None
        self.engine = None
        self.owner_org: uuid.UUID = uuid.uuid4()
        self.grantee_org: uuid.UUID = uuid.uuid4()
        self.third_org: uuid.UUID = uuid.uuid4()
        self.fourth_org: uuid.UUID = uuid.uuid4()
        self.project_id: uuid.UUID = uuid.uuid4()
        self.other_project_id: uuid.UUID = uuid.uuid4()
        self.boss: uuid.UUID = uuid.uuid4()
        self.editor: uuid.UUID = uuid.uuid4()
        self.leaver: uuid.UUID = uuid.uuid4()
        self.grantee_boss: uuid.UUID = uuid.uuid4()
        self.stranger: uuid.UUID = uuid.uuid4()
        self.admin: uuid.UUID = uuid.uuid4()
        self.fourth_boss: uuid.UUID = uuid.uuid4()
        #: caller -> the organization a token minted for them names.
        self.tenants: dict[uuid.UUID, uuid.UUID] = {}


async def _organization(session: AsyncSession, organization_id: uuid.UUID, name: str) -> None:
    session.add(Organization(id=organization_id, name=name, slug=f"{name.lower().replace(' ', '-')}", status="active"))
    await session.flush()


async def _person(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    role: str,
    organization_id: uuid.UUID,
    membership_status: str = "active",
) -> None:
    """A user and their membership in ``organization_id``."""
    session.add(
        User(
            id=user_id,
            email=f"{role}-{user_id.hex[:8]}@grants.test",
            hashed_password="x",
            full_name=f"Grants {role}",
            role=role,
            locale="en",
            is_active=True,
            metadata_={},
        )
    )
    await session.flush()
    session.add(
        Membership(
            user_id=user_id,
            organization_id=organization_id,
            role=role,
            status=membership_status,
            is_default=True,
        )
    )
    await session.flush()


async def _project(
    session: AsyncSession, project_id: uuid.UUID, owner: uuid.UUID, organization_id: uuid.UUID | None
) -> None:
    session.add(
        Project(
            id=project_id,
            name=f"Grants {project_id.hex[:6]}",
            currency="EUR",
            status="active",
            owner_id=owner,
            organization_id=organization_id,
            metadata_={},
        )
    )
    await session.flush()


async def _build(session: AsyncSession) -> _World:
    w = _World()
    await _organization(session, w.owner_org, "Owner Company")
    await _organization(session, w.grantee_org, "Grantee Company")
    await _organization(session, w.third_org, "Third Company")
    await _organization(session, w.fourth_org, "Fourth Company")

    await _person(session, w.boss, role="manager", organization_id=w.owner_org)
    await _person(session, w.editor, role="editor", organization_id=w.owner_org)
    await _person(session, w.leaver, role="manager", organization_id=w.owner_org, membership_status="suspended")
    await _person(session, w.grantee_boss, role="manager", organization_id=w.grantee_org)
    await _person(session, w.stranger, role="manager", organization_id=w.third_org)
    await _person(session, w.admin, role="admin", organization_id=w.third_org)
    await _person(session, w.fourth_boss, role="manager", organization_id=w.fourth_org)

    await _project(session, w.project_id, w.boss, w.owner_org)
    # A second project in a fourth company, so a grant id can be presented to the
    # wrong project and the answer has to be the same 404 as an id that does not
    # exist at all.
    await _project(session, w.other_project_id, w.fourth_boss, w.fourth_org)

    w.tenants = {
        w.boss: w.owner_org,
        w.editor: w.owner_org,
        w.leaver: w.owner_org,
        w.grantee_boss: w.grantee_org,
        w.stranger: w.third_org,
        w.admin: w.third_org,
        w.fourth_boss: w.fourth_org,
    }
    return w


@asynccontextmanager
async def client_as(w: _World, user_id: uuid.UUID, role: str):
    """The projects router, with only the caller's identity substituted.

    Both payload dependencies are overridden with the same claim, so
    ``get_current_tenant_id`` runs for real: the tenant the routes see is the one
    ``resolve_tenant_id`` reads out of a ``tenant_id`` claim, which is the path a
    production request takes and the one ADR 005 says is an organization id and
    never a person's.
    """
    from app.dependencies import (
        get_current_user_payload,
        get_optional_user_payload,
        get_session,
    )

    app = FastAPI()
    app.include_router(router, prefix=BASE)
    payload = {
        "sub": str(user_id),
        "role": role,
        "permissions": [],
        "tenant_id": str(w.tenants[user_id]),
    }

    async def _session():
        async with w.factory() as s:
            yield s
            await s.commit()

    app.dependency_overrides[get_session] = _session
    app.dependency_overrides[get_current_user_payload] = lambda: dict(payload)
    app.dependency_overrides[get_optional_user_payload] = lambda: dict(payload)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://grants-test") as c:
        yield c


def _grants(w: _World, tail: str = "") -> str:
    return f"{BASE}/{w.project_id}/participant-grants{tail}"


def _body(w: _World, **overrides) -> dict:
    payload = {"grantee_organization_id": str(w.grantee_org), "scope": "view"}
    payload.update(overrides)
    return payload


async def _grants_in(w: _World, project_id: uuid.UUID | None = None) -> list[ProjectParticipantGrant]:
    """The grant rows, read straight from the database rather than from a response."""
    async with w.factory() as session:
        stmt = select(ProjectParticipantGrant).order_by(ProjectParticipantGrant.created_at, ProjectParticipantGrant.id)
        if project_id is not None:
            stmt = stmt.where(ProjectParticipantGrant.project_id == project_id)
        return list((await session.execute(stmt)).scalars().all())


async def _audit_rows(w: _World, *, grant_id: uuid.UUID | None = None, action: str | None = None) -> list[dict]:
    """The audit rows this module wrote, oldest first."""
    sql = (
        "SELECT action, entity_type, entity_id, actor_id, tenant_id, from_status, to_status, reason, metadata "
        "FROM oe_activity_log WHERE entity_type = :entity"
    )
    params: dict[str, object] = {"entity": GRANT_ENTITY_TYPE}
    if grant_id is not None:
        sql += " AND entity_id = :grant"
        params["grant"] = str(grant_id)
    if action is not None:
        sql += " AND action = :action"
        params["action"] = action
    sql += " ORDER BY created_at, id"
    async with w.factory() as session:
        rows = (await session.execute(text(sql), params)).mappings().all()
    return [dict(row) for row in rows]


async def _counts(w: _World) -> dict[str, int]:
    """Row counts for :data:`_UNTOUCHED_TABLES`."""
    async with w.factory() as session:
        return {table: int(await session.scalar(text(f"SELECT count(*) FROM {table}"))) for table in _UNTOUCHED_TABLES}


async def _role_facts(w: _World) -> dict[str, object]:
    """Who the connection is, recorded rather than assumed."""
    async with w.factory() as session:
        row = (
            await session.execute(
                text("SELECT current_user, session_user, (SELECT rolsuper FROM pg_roles WHERE rolname = current_user)")
            )
        ).one()
    return {"current_user": row[0], "session_user": row[1], "rolsuper": bool(row[2])}


async def _create(w: _World, user_id: uuid.UUID, role: str, **overrides):
    """POST one grant and return the response."""
    async with client_as(w, user_id, role) as client:
        return await client.post(_grants(w), json=_body(w, **overrides))


# ── the one caller who may decide ─────────────────────────────────────────


async def test_the_owning_companys_manager_creates_a_grant_and_the_audit_row_lands_with_it(world):
    w = world
    response = await _create(w, w.boss, "manager", scope="contribute", reason="Tender lot 3")

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["project_id"] == str(w.project_id)
    assert body["grantee_organization_id"] == str(w.grantee_org)
    assert body["granted_on_behalf_of_organization_id"] == str(w.owner_org)
    assert body["granted_by_user_id"] == str(w.boss)
    assert body["scope"] == "contribute"
    assert body["status"] == "active"
    # ``is_live`` comes off the model's own property, so the response and the
    # read predicate cannot disagree about whether the grant is in force.
    assert body["is_live"] is True

    grants = await _grants_in(w)
    assert len(grants) == 1
    facts = await _role_facts(w)
    # These are application writes on the connecting role, not migration DDL and
    # not a request transaction under enforcement: the grant table carries no
    # ``tenant_id``, so no policy binds it whichever role reads it. Recorded
    # rather than assumed, and asserted so that a future change to the harness -
    # provisioning RLS on a throwaway database, or downgrading the role - shows
    # up here as a fact that stopped being true instead of silently changing what
    # every other assertion in this file means.
    assert facts["rolsuper"] is True, facts
    assert facts["current_user"] == facts["session_user"], facts

    rows = await _audit_rows(w, grant_id=uuid.UUID(body["id"]), action="granted")
    assert len(rows) == 1, rows
    row = rows[0]
    assert row["entity_type"] == GRANT_ENTITY_TYPE
    # The audit row belongs to the company that DECIDED, not the one that
    # received access: putting it under the grantee's tenant would file the
    # record of the decision in the ledger of the company that made none.
    assert str(row["tenant_id"]) == str(w.owner_org)
    assert str(row["actor_id"]) == str(w.boss)
    assert row["reason"] == "Tender lot 3"
    assert row["to_status"] == "active"
    metadata = row["metadata"]
    assert metadata["grantee_organization_id"] == str(w.grantee_org)
    assert metadata["scope"] == "contribute"
    assert metadata["project_id"] == str(w.project_id)


async def test_the_scope_vocabulary_is_refused_at_the_edge_as_well_as_in_the_table(world):
    """``read`` is the ADR's superseded word for ``view``, and both layers refuse it.

    The ``Literal`` in the schema makes it a 422 that names the three accepted
    values in the OpenAPI document; the check constraint on the table makes it
    unreachable however the row is written. This is the edge half, and the
    table half is asserted in the catalog test beside this one.
    """
    w = world
    response = await _create(w, w.boss, "manager", scope="read")

    assert response.status_code == 422, response.text
    assert await _grants_in(w) == []
    assert await _audit_rows(w) == []


# ── everybody who may not ─────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("identity", "role"),
    [("grantee_boss", "manager"), ("stranger", "manager"), ("admin", "admin")],
)
async def test_a_company_that_does_not_own_the_project_cannot_grant_on_it(world, identity, role):
    """404 for every caller whose company is not the owner, whatever their role.

    404 and not 403, so that "not yours" and "no such project" stay the same
    answer to somebody holding a list of identifiers - the policy
    ``verify_project_access`` already sets. The ``admin`` case is in the list
    because an instance administrator is trusted with the instance and handing
    one company's project to another is not an instance decision; the routes have
    no admin bypass and this is the test that says so.
    """
    w = world
    user_id = getattr(w, identity)
    response = await _create(w, user_id, role)

    assert response.status_code == 404, response.text
    assert response.json()["detail"] == "Project not found"
    assert await _grants_in(w) == []
    assert await _audit_rows(w) == []


async def test_a_grantee_holding_a_live_grant_cannot_grant_anybody_else_in(world):
    """No sub-grants, and the refusal is structural rather than a check.

    The grantee's manager holds a live ``manage``-scoped grant, which is as much
    authority over the project as the table can express, and is still refused:
    authority resolution asks whether the caller's company is the project's
    ``organization_id`` and never asks where the caller's access came from, so
    there is no branch to get wrong. The test asserts the refusal rather than the
    absence of the branch, because the refusal is the contract.
    """
    w = world
    granted = await _create(w, w.boss, "manager", scope="manage")
    assert granted.status_code == 201, granted.text

    async with client_as(w, w.grantee_boss, "manager") as client:
        response = await client.post(
            _grants(w), json=_body(w, grantee_organization_id=str(w.third_org), scope="manage")
        )

    assert response.status_code == 404, response.text
    grants = await _grants_in(w)
    assert len(grants) == 1, "the third company must not have been granted anything"
    assert str(grants[0].grantee_organization_id) == str(w.grantee_org)


async def test_an_editor_of_the_owning_company_cannot_grant(world):
    """Right company, not enough authority: ``projects.grant`` sits at MANAGER."""
    w = world
    response = await _create(w, w.editor, "editor")

    assert response.status_code == 403, response.text
    assert response.json()["detail"] == "Missing permission: projects.grant"
    assert await _grants_in(w) == []


async def test_a_manager_who_left_the_owning_company_cannot_decide_for_it(world):
    """The membership is read from the database, not taken from the token.

    A token outlives the membership that minted it, so a person whose membership
    was suspended still holds a credential naming the company until it expires.
    Checking the row is what stops that credential from inviting a third company
    into a project its holder no longer works on.
    """
    w = world
    response = await _create(w, w.leaver, "manager")

    assert response.status_code == 403, response.text
    assert "active membership" in response.json()["detail"]
    assert await _grants_in(w) == []


async def test_the_owner_cannot_grant_the_project_to_itself(world):
    """A self-grant is a row that says the company participates in its own project.

    The predicate already answers that from the ownership arm, so the row would
    mean nothing - and could not be revoked without pretending something had been
    taken away.
    """
    w = world
    response = await _create(w, w.boss, "manager", grantee_organization_id=str(w.owner_org))

    assert response.status_code == 422, response.text
    assert "its own project" in response.json()["detail"]
    assert await _grants_in(w) == []


async def test_a_grantee_that_does_not_exist_is_refused_before_anything_is_written(world):
    w = world
    response = await _create(w, w.boss, "manager", grantee_organization_id=str(uuid.uuid4()))

    assert response.status_code == 422, response.text
    assert await _grants_in(w) == []
    assert await _audit_rows(w) == []


async def test_a_window_that_ends_before_it_starts_is_refused_by_the_api_not_by_a_500(world):
    """The table has a check constraint for this; the API answers 422 first.

    An ``IntegrityError`` from a constraint reaches a client as a 500 unless
    something translates it, and the caller here did something wrong rather than
    something unfortunate.
    """
    w = world
    now = datetime.now(UTC)
    response = await _create(
        w,
        w.boss,
        "manager",
        valid_from=now.isoformat(),
        valid_until=(now - timedelta(days=1)).isoformat(),
    )

    assert response.status_code == 422, response.text
    assert "later than valid_from" in response.json()["detail"]
    assert await _grants_in(w) == []
    assert await _audit_rows(w) == []


async def test_a_second_live_grant_to_the_same_company_is_refused_and_names_what_is_there(world):
    """409 rather than a silent widening, and the refusal says which grant is live.

    Quietly turning a suspended grant into an active one would revive access that
    was withdrawn pending review, which is why the answer is a refusal that names
    the status and scope already there rather than an update nobody asked for.
    """
    w = world
    first = await _create(w, w.boss, "manager", scope="view")
    assert first.status_code == 201, first.text

    second = await _create(w, w.boss, "manager", scope="manage")

    assert second.status_code == 409, second.text
    detail = second.json()["detail"]
    assert "active" in detail and "'view'" in detail
    grants = await _grants_in(w)
    assert len(grants) == 1
    assert grants[0].scope == "view", "the refused request must not have widened the grant"
    assert len(await _audit_rows(w, action="granted")) == 1


# ── listing ───────────────────────────────────────────────────────────────


async def test_listing_hides_withdrawn_grants_unless_asked_and_only_the_owner_may_list(world):
    w = world
    first = await _create(w, w.boss, "manager", grantee_organization_id=str(w.grantee_org))
    second = await _create(w, w.boss, "manager", grantee_organization_id=str(w.third_org))
    assert first.status_code == 201 and second.status_code == 201
    async with client_as(w, w.boss, "manager") as client:
        revoked = await client.post(
            _grants(w, f"/{second.json()['id']}/revoke"), json={"reason": "Lot awarded elsewhere"}
        )
        assert revoked.status_code == 200, revoked.text

        live = await client.get(_grants(w))
        assert live.status_code == 200
        body = live.json()
        assert body["total"] == 1 and body["include_revoked"] is False
        assert [item["status"] for item in body["items"]] == ["active"]

        everything = await client.get(_grants(w), params={"include_revoked": "true"})
        assert everything.status_code == 200
        full = everything.json()
        assert full["total"] == 2 and full["include_revoked"] is True
        # Oldest first, and the revoked row is still there: revocation keeps the
        # record rather than deleting it.
        assert [item["status"] for item in full["items"]] == ["active", "revoked"]
        assert full["items"][1]["revocation_reason"] == "Lot awarded elsewhere"

    # Who else is in the room is the owner's information, not a consequence of
    # having been invited.
    async with client_as(w, w.grantee_boss, "manager") as client:
        refused = await client.get(_grants(w))
    assert refused.status_code == 404, refused.text


async def test_a_grant_id_belonging_to_another_project_is_not_found_here(world):
    """Scoped by project as well as by id.

    Otherwise these routes become a way to change a grant on a project the
    caller's company cannot see, using an id it obtained somewhere else.
    """
    w = world
    created = await _create(w, w.fourth_boss, "manager", grantee_organization_id=str(w.grantee_org))
    # The fourth company's own manager cannot grant on the owner's project either;
    # build the foreign grant through its own project instead.
    assert created.status_code == 404, created.text

    async with w.factory() as session:
        session.add(
            ProjectParticipantGrant(
                project_id=w.other_project_id,
                grantee_organization_id=w.grantee_org,
                granted_by_user_id=w.fourth_boss,
                granted_on_behalf_of_organization_id=w.fourth_org,
                scope="view",
                status="active",
                metadata_={},
            )
        )
        await session.commit()
    foreign = (await _grants_in(w, project_id=w.other_project_id))[0]

    async with client_as(w, w.boss, "manager") as client:
        # Each request carries a body its own schema accepts, so a 404 here is the
        # handler refusing a grant that belongs to another project and not body
        # validation refusing the request before the handler ran.
        for method, tail, body in (
            ("patch", "/scope", {"scope": "manage"}),
            ("post", "/revoke", {"reason": "not yours"}),
        ):
            response = await client.request(method, _grants(w, f"/{foreign.id}{tail}"), json=body)
            assert response.status_code == 404, (method, response.text)
        listed = await client.get(_grants(w), params={"include_revoked": "true"})
        assert listed.json()["total"] == 0

    assert (await _grants_in(w, project_id=w.other_project_id))[0].scope == "view"


async def test_a_project_with_no_owning_company_has_nobody_who_can_grant_on_it(world):
    """The one refusal that is not about the caller, so it says what is missing.

    A project whose ``organization_id`` is NULL is what ADR 005's readiness
    report counts; folding it into the same 404 as "not yours" would leave an
    operator unable to tell that the fix is to resolve the owner to a company.
    """
    w = world
    async with w.factory() as session:
        orphan_id = uuid.uuid4()
        session.add(
            Project(
                id=orphan_id,
                name=f"Orphan {orphan_id.hex[:6]}",
                currency="EUR",
                status="active",
                owner_id=w.boss,
                organization_id=None,
                metadata_={},
            )
        )
        await session.commit()

    async with client_as(w, w.boss, "manager") as client:
        response = await client.post(f"{BASE}/{orphan_id}/participant-grants", json=_body(w))

    assert response.status_code == 409, response.text
    assert "no owning organization" in response.json()["detail"]


# ── scope changes and revocation ─────────────────────────────────────────


async def test_changing_the_scope_keeps_the_grants_identity_and_records_both_ends(world):
    w = world
    created = await _create(w, w.boss, "manager", scope="view")
    grant_id = created.json()["id"]

    async with client_as(w, w.boss, "manager") as client:
        changed = await client.patch(
            _grants(w, f"/{grant_id}/scope"),
            json={"scope": "manage", "reason": "Awarded the site package"},
        )
        assert changed.status_code == 200, changed.text
        assert changed.json()["id"] == grant_id
        assert changed.json()["scope"] == "manage"
        assert changed.json()["status"] == "active"

        # Asking for the scope that is already there is not an error and writes
        # nothing: an audit row saying the scope changed to what it already was
        # is noise in the one log an operator reads to reconstruct a decision.
        again = await client.patch(_grants(w, f"/{grant_id}/scope"), json={"scope": "manage"})
        assert again.status_code == 200

    rows = await _audit_rows(w, grant_id=uuid.UUID(grant_id), action="scope_changed")
    assert len(rows) == 1, rows
    assert rows[0]["from_status"] == "view"
    assert rows[0]["to_status"] == "manage"
    assert rows[0]["reason"] == "Awarded the site package"
    assert rows[0]["metadata"]["previous_rank"] < rows[0]["metadata"]["rank"]


async def test_a_revoked_grant_is_history_and_cannot_be_scoped(world):
    w = world
    created = await _create(w, w.boss, "manager")
    grant_id = created.json()["id"]
    async with client_as(w, w.boss, "manager") as client:
        assert (await client.post(_grants(w, f"/{grant_id}/revoke"), json={})).status_code == 200
        refused = await client.patch(_grants(w, f"/{grant_id}/scope"), json={"scope": "manage"})

    assert refused.status_code == 409, refused.text
    assert "history" in refused.json()["detail"]
    assert (await _grants_in(w))[0].scope == "view"


async def test_revoking_closes_access_keeps_the_row_and_rewrites_nothing_else(world):
    """Owner decision 3, measured rather than asserted from the code's shape.

    A revocation could have been implemented as a delete, as a rewrite of the
    rows the grantee produced, or as a re-stamp of their tenant. It is none of
    those: the grant row survives with its author and reason, and every table
    that a retroactive implementation would have had to touch has the same row
    count afterwards. The audit log grows by exactly one row, which is the one
    write that is supposed to happen.
    """
    w = world
    created = await _create(w, w.boss, "manager", scope="contribute")
    grant_id = created.json()["id"]

    # Something the grantee owns: a project in the grantee's own company, which a
    # retroactive revocation would have had to hide, re-stamp or delete.
    async with w.factory() as session:
        grantee_project = uuid.uuid4()
        session.add(
            Project(
                id=grantee_project,
                name=f"Grantee own {grantee_project.hex[:6]}",
                currency="EUR",
                status="active",
                owner_id=w.grantee_boss,
                organization_id=w.grantee_org,
                metadata_={},
            )
        )
        await session.commit()

    before = await _counts(w)
    async with client_as(w, w.boss, "manager") as client:
        response = await client.post(_grants(w, f"/{grant_id}/revoke"), json={"reason": "Handover complete"})
    after = await _counts(w)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "revoked"
    assert body["revoked_at"] is not None
    assert body["revoked_by_user_id"] == str(w.boss)
    assert body["revocation_reason"] == "Handover complete"
    # The scope at revocation is what the grantee could do while it had access,
    # and revoking does not quietly narrow it on the way out.
    assert body["scope"] == "contribute"
    assert body["is_live"] is False

    grants = await _grants_in(w)
    assert len(grants) == 1, "revocation keeps the row"
    assert grants[0].status == "revoked"

    grew = {table: after[table] - before[table] for table in _UNTOUCHED_TABLES if after[table] != before[table]}
    assert grew == {"oe_activity_log": 1}, grew

    async with w.factory() as session:
        still_the_grantees = await session.get(Project, grantee_project)
    assert still_the_grantees is not None
    assert str(still_the_grantees.organization_id) == str(w.grantee_org)

    rows = await _audit_rows(w, grant_id=uuid.UUID(grant_id), action="revoked")
    assert len(rows) == 1
    assert rows[0]["from_status"] == "active"
    assert rows[0]["to_status"] == "revoked"
    assert rows[0]["metadata"]["scope_at_revocation"] == "contribute"
    assert str(rows[0]["tenant_id"]) == str(w.owner_org)


async def test_revoking_twice_is_refused_rather_than_rewriting_the_first_revocation(world):
    w = world
    created = await _create(w, w.boss, "manager")
    grant_id = created.json()["id"]
    async with client_as(w, w.boss, "manager") as client:
        assert (await client.post(_grants(w, f"/{grant_id}/revoke"), json={"reason": "First"})).status_code == 200
        again = await client.post(_grants(w, f"/{grant_id}/revoke"), json={"reason": "Second"})

    assert again.status_code == 409, again.text
    grant = (await _grants_in(w))[0]
    assert grant.revocation_reason == "First", "the second request must not have overwritten the first"
    assert len(await _audit_rows(w, grant_id=uuid.UUID(grant_id), action="revoked")) == 1


async def test_a_revoked_grant_does_not_block_the_regrant_that_replaces_it(world):
    """The partial unique index, exercised through the API rather than the catalog.

    Re-granting inserts a new row instead of resurrecting the old one, so the
    sequence of decisions survives in the table itself and not only in the log.
    """
    w = world
    first = await _create(w, w.boss, "manager", scope="view")
    grant_id = first.json()["id"]
    async with client_as(w, w.boss, "manager") as client:
        assert (await client.post(_grants(w, f"/{grant_id}/revoke"), json={})).status_code == 200
        second = await client.post(_grants(w), json=_body(w, scope="contribute"))

    assert second.status_code == 201, second.text
    assert second.json()["id"] != grant_id
    grants = await _grants_in(w)
    assert len(grants) == 2
    assert sorted(grant.status for grant in grants) == ["active", "revoked"]
    assert len(await _audit_rows(w, action="granted")) == 2


# ── suspension on an ownership change (owner decision 4) ──────────────────


async def test_an_ownership_change_suspends_the_grants_the_new_owner_did_not_make(world):
    """No route exercises this, and the reason is stated rather than hidden.

    Nothing in the product moves a project between companies: ``ProjectUpdate``
    has no ``organization_id`` field, and the only writer of that column is
    ``app.modules.users.repairs``, which fills a NULL and never replaces a
    company with a different one. So this test calls the service function
    directly, and ``test_every_writer_of_a_projects_owning_company_suspends_its_grants``
    in ``tests/unit`` is what fails the day a transfer path is added without it.

    The world here is the one a transfer would produce: the project used to
    belong to the grantee's company, which invited a fourth company in, and now
    belongs to the owner's company, which invited a third. After the change the
    incoming owner reviews a grant it did not make and keeps the one it did.
    """
    w = world
    async with w.factory() as session:
        inherited = ProjectParticipantGrant(
            project_id=w.project_id,
            grantee_organization_id=w.fourth_org,
            granted_by_user_id=w.grantee_boss,
            granted_on_behalf_of_organization_id=w.grantee_org,
            scope="contribute",
            status="active",
            metadata_={},
        )
        own = ProjectParticipantGrant(
            project_id=w.project_id,
            grantee_organization_id=w.third_org,
            granted_by_user_id=w.boss,
            granted_on_behalf_of_organization_id=w.owner_org,
            scope="view",
            status="active",
            metadata_={},
        )
        session.add_all([inherited, own])
        await session.commit()
        inherited_id, own_id = inherited.id, own.id

        project = await session.get(Project, w.project_id)
        project.organization_id = w.grantee_org
        await session.commit()

        suspended = await suspend_grants_on_ownership_change(
            session,
            w.project_id,
            new_organization_id=str(w.grantee_org),
            changed_by=str(w.boss),
            reason="Project transferred to Grantee Company",
        )
        await session.commit()

    assert [str(grant.id) for grant in suspended] == [str(own_id)], "only the grant the incoming owner did not make"

    grants = {str(grant.id): grant for grant in await _grants_in(w)}
    assert grants[str(own_id)].status == "suspended"
    assert grants[str(inherited_id)].status == "active"
    # Suspension is not revocation: the row keeps its scope and the revocation
    # columns stay empty, because nothing was withdrawn and the table is what has
    # to tell the two apart.
    assert grants[str(own_id)].scope == "view"
    assert grants[str(own_id)].revoked_at is None
    assert grants[str(own_id)].revoked_by_user_id is None

    rows = await _audit_rows(w, action="suspended")
    assert len(rows) == 1
    assert rows[0]["entity_id"] == str(own_id)
    assert rows[0]["from_status"] == "active"
    assert rows[0]["to_status"] == "suspended"
    assert rows[0]["reason"] == "Project transferred to Grantee Company"
    assert rows[0]["metadata"]["new_organization_id"] == str(w.grantee_org)
    assert str(rows[0]["tenant_id"]) == str(w.owner_org)

    # Running it again writes nothing: a grant already suspended is suspended,
    # and a second audit row would say a decision was made twice.
    async with w.factory() as session:
        again = await suspend_grants_on_ownership_change(
            session,
            w.project_id,
            new_organization_id=str(w.grantee_org),
            changed_by=str(w.boss),
            reason="Project transferred to Grantee Company",
        )
        await session.commit()
    assert again == []
    assert len(await _audit_rows(w, action="suspended")) == 1


async def test_a_project_left_belonging_to_nobody_suspends_every_live_grant(world):
    """``new_organization_id=None`` is a value, not an omission.

    A project with no owning company has nobody left who made its grants, so all
    of them are suspended and each suspension leaves its own audit row.
    """
    w = world
    async with w.factory() as session:
        for grantee in (w.grantee_org, w.third_org):
            session.add(
                ProjectParticipantGrant(
                    project_id=w.project_id,
                    grantee_organization_id=grantee,
                    granted_by_user_id=w.boss,
                    granted_on_behalf_of_organization_id=w.owner_org,
                    scope="view",
                    status="active",
                    metadata_={},
                )
            )
        await session.commit()

        suspended = await suspend_grants_on_ownership_change(
            session,
            w.project_id,
            new_organization_id=None,
            changed_by=None,
            reason="Owning company could not be resolved",
        )
        await session.commit()

    assert len(suspended) == 2
    assert all(grant.status == "suspended" for grant in await _grants_in(w))
    rows = await _audit_rows(w, action="suspended")
    assert len(rows) == 2
    # A boot repair has no actor, and the audit row says so rather than inventing one.
    assert all(row["actor_id"] is None for row in rows)


async def test_a_suspended_grant_still_occupies_the_slot_and_says_so_when_asked_again(world):
    """Suspension is reversible, so it is not a free slot.

    The refusal names the suspended status, which is the answer that tells the
    owner to review the grant rather than to make a new one.
    """
    w = world
    created = await _create(w, w.boss, "manager")
    async with w.factory() as session:
        grant = await session.get(ProjectParticipantGrant, uuid.UUID(created.json()["id"]))
        grant.status = "suspended"
        await session.commit()

    again = await _create(w, w.boss, "manager")

    assert again.status_code == 409, again.text
    assert "suspended" in again.json()["detail"]
    assert len(await _grants_in(w)) == 1


async def test_every_grant_event_leaves_exactly_one_audit_row_and_no_event_leaves_none(world):
    """The whole lifecycle counted, because "every event writes a row" is the claim.

    Four events - granted, scope_changed, suspended, revoked - and four rows, one
    per event, each naming the grant it describes. The count is taken from the
    database and not from the responses, so a handler that returned 200 without
    writing its row would fail here.
    """
    w = world
    created = await _create(w, w.boss, "manager", scope="view")
    grant_id = uuid.UUID(created.json()["id"])

    async with client_as(w, w.boss, "manager") as client:
        assert (await client.patch(_grants(w, f"/{grant_id}/scope"), json={"scope": "contribute"})).status_code == 200
        assert (await client.post(_grants(w, f"/{grant_id}/revoke"), json={"reason": "Done"})).status_code == 200

    async with w.factory() as session:
        second = ProjectParticipantGrant(
            project_id=w.project_id,
            grantee_organization_id=w.third_org,
            granted_by_user_id=w.boss,
            granted_on_behalf_of_organization_id=w.owner_org,
            scope="view",
            status="active",
            metadata_={},
        )
        session.add(second)
        await session.commit()
        suspended = await suspend_grants_on_ownership_change(
            session,
            w.project_id,
            new_organization_id=str(w.grantee_org),
            changed_by=str(w.boss),
            reason="Ownership moved",
        )
        await session.commit()
    assert len(suspended) == 1

    rows = await _audit_rows(w)
    assert [row["action"] for row in rows] == ["granted", "scope_changed", "revoked", "suspended"], rows
    assert all(row["entity_type"] == GRANT_ENTITY_TYPE for row in rows)
    assert all(row["entity_id"] for row in rows)
    assert {row["entity_id"] for row in rows} == {str(grant_id), str(second.id)}

    async with w.factory() as session:
        total = await session.scalar(text("SELECT count(*) FROM oe_activity_log"))
    assert int(total) == 4, "no other audit row was written by any of the four events"
