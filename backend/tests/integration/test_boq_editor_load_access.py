# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The BOQ access guards answer in one statement, and refuse exactly as before.

Opening a bill in the editor fires one request per panel: the bill, its markups,
its cost breakdown, its classification, the structural limits and the project.
Every bill-scoped one stands behind ``_verify_boq_owner``, which read the bill's
project, then the project's owner, then (for anyone but the owner) the caller's
team membership: two statements per request for the owner and three for a team
member, before any work. Measured on a three-line bill, the page load cost the
owner 57 statements and a team member 62.

The guards now read the bill, the owner and the membership in one statement, and
``_verify_project_owner_for_boq`` reads the project's owner, status and the
membership in one statement instead of loading the whole project (which dragged
its milestones and WBS in through ``selectin``) and then the membership. These
cases pin that, and pin that nothing about who is refused changed:

* A differential oracle. The guards as they were are copied below verbatim, and
  over every caller (owner, team member, member of a different project,
  stranger, admin, a caller id that is not a UUID) and every target (a live
  bill, a bill on an archived project, a bill that does not exist, a live
  project, an archived project, a project that does not exist) the old and the
  new answer identically: the same status and the same detail, or both let the
  caller through.
* The same refusals over HTTP on the editor's own endpoints and on the
  comparison, which now guards both bills in one statement.
* Statement counts: the guard is one statement, the old guard run under the
  same counter shows two or three (so the counter is not blind), a team member's
  page load costs no more than the owner's, and the whole load stays under a
  ceiling.

Run:
    cd backend
    python -m pytest tests/integration/test_boq_editor_load_access.py -v
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from typing import Any

import pytest
import pytest_asyncio
from fastapi import HTTPException, status
from httpx import ASGITransport, AsyncClient

import app.modules.boq.models  # noqa: F401
import app.modules.projects.models  # noqa: F401
import app.modules.teams.models  # noqa: F401
import app.modules.users.models  # noqa: F401

pytestmark = pytest.mark.tenant_isolation

#: The editor's page-load ceiling for one bill, every request in
#: ``_editor_urls`` together, auth included. Measured at 57 for the owner and
#: 62 for a team member before the guards were folded, 53 and 54 after (the
#: member's one extra is the project read, guarded outside the BOQ module), and
#: 43 and 44 once the cost breakdown and the classification stopped loading the
#: bill twice (``tests/pg/test_editor_panels_read_the_bill_once.py``).
EDITOR_LOAD_CEILING = 43


# ── The guards as they were, verbatim ──────────────────────────────────────


async def _old_verify_boq_owner(session, boq_id, user_id, payload=None) -> None:
    from app.core.i18n import get_locale
    from app.core.validation.messages import translate

    if payload and payload.get("role") == "admin":
        return
    from sqlalchemy import select

    from app.modules.boq.models import BOQ
    from app.modules.projects.models import Project

    boq_row = (await session.execute(select(BOQ.project_id).where(BOQ.id == boq_id))).first()
    if boq_row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="BOQ not found")
    project_id = boq_row[0]
    owner_row = (await session.execute(select(Project.owner_id).where(Project.id == project_id))).first()
    if owner_row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=translate("errors.project_not_found", locale=get_locale())
        )
    if str(owner_row[0]) == user_id:
        return
    from app.modules.teams.access import is_project_member

    try:
        uid = uuid.UUID(str(user_id))
    except (ValueError, TypeError):
        uid = None
    if uid is not None and await is_project_member(session, project_id, uid):
        return
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="BOQ not found",
    )


async def _old_verify_project_owner_for_boq(session, project_id, user_id, payload=None) -> None:
    from app.core.i18n import get_locale
    from app.core.validation.messages import translate

    is_admin = bool(payload and payload.get("role") == "admin")
    from app.modules.projects.repository import ProjectRepository

    project_repo = ProjectRepository(session)
    project = await project_repo.get_by_id(project_id)
    if project is None or project.status == "archived":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=translate("errors.project_not_found", locale=get_locale())
        )
    if is_admin:
        return
    if str(project.owner_id) == user_id:
        return
    from app.modules.teams.access import is_project_member

    try:
        uid = uuid.UUID(str(user_id))
    except (ValueError, TypeError):
        uid = None
    if uid is not None and await is_project_member(session, project_id, uid):
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="You do not have access to this project",
    )


# ── Fixtures ───────────────────────────────────────────────────────────────


@pytest_asyncio.fixture(scope="module")
async def app_instance():
    """Boot the FastAPI app once per module and create all tables."""
    from app.config import get_settings

    get_settings.cache_clear()

    from app.main import create_app

    fastapi_app = create_app()

    async with fastapi_app.router.lifespan_context(fastapi_app):
        from app.database import Base, engine

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        yield fastapi_app


@pytest_asyncio.fixture(scope="module")
async def http_client(app_instance):
    transport = ASGITransport(app=app_instance)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def _register_login(client: AsyncClient, tag: str, *, role: str) -> tuple[str, dict[str, str]]:
    """Register, activate, set the role, then log in. Returns ``(user_id, headers)``."""
    from sqlalchemy import update

    from app.database import async_session_factory
    from app.modules.users.models import User

    email = f"{tag}-{uuid.uuid4().hex[:8]}@boq-editor-load.io"
    password = f"EditorLoad{uuid.uuid4().hex[:6]}9"
    reg = await client.post(
        "/api/v1/users/auth/register",
        json={"email": email, "password": password, "full_name": f"User {tag}"},
    )
    assert reg.status_code in (200, 201), f"register failed for {tag}: {reg.text}"
    # Every role is set explicitly: registration makes the first account in an
    # empty deployment an admin, and an admin passes every check vacuously.
    async with async_session_factory() as s:
        await s.execute(update(User).where(User.email == email.lower()).values(is_active=True, role=role))
        await s.commit()
    login = await client.post("/api/v1/users/auth/login", json={"email": email, "password": password})
    assert login.status_code == 200, f"login failed for {tag}: {login.text}"
    return reg.json()["id"], {"Authorization": f"Bearer {login.json()['access_token']}"}


async def _project(client: AsyncClient, headers: dict[str, str], name: str) -> str:
    resp = await client.post(
        "/api/v1/projects/",
        json={"name": f"{name} {uuid.uuid4().hex[:6]}", "currency": "EUR", "region": "DACH"},
        headers=headers,
    )
    assert resp.status_code == 201, f"create project failed: {resp.text}"
    return resp.json()["id"]


async def _bill(client: AsyncClient, headers: dict[str, str], project_id: str, name: str, lines: int) -> str:
    resp = await client.post(
        "/api/v1/boq/boqs/",
        json={"project_id": project_id, "name": name, "description": ""},
        headers=headers,
    )
    assert resp.status_code == 201, f"create BOQ failed: {resp.text}"
    boq_id = resp.json()["id"]
    for i in range(lines):
        pos = await client.post(
            f"/api/v1/boq/boqs/{boq_id}/positions/",
            json={
                "boq_id": boq_id,
                "ordinal": f"{(i + 1) * 10:04d}",
                "description": f"{name} line {i + 1}",
                "unit": "m3",
                "quantity": 2 + i,
                "unit_rate": 10 + i,
            },
            headers=headers,
        )
        assert pos.status_code == 201, f"add position failed: {pos.text}"
    return boq_id


async def _add_member(client: AsyncClient, owner: dict[str, str], project_id: str, user_id: str) -> None:
    resp = await client.post(
        f"/api/v1/projects/{project_id}/members/",
        json={"user_id": user_id, "role": "viewer"},
        headers=owner,
    )
    assert resp.status_code in (200, 201), f"add member failed: {resp.text}"


@pytest_asyncio.fixture(scope="module")
async def world(http_client):
    """One owner with a live project, a second live project and an archived one.

    ``member`` is a team member of ``live``. ``other_member`` is a team member
    of ``second`` only, which is the caller a membership test that forgot to
    correlate on the project would let into ``live``. ``stranger`` holds the
    same role as the owner and no tie to any project. The owner is an
    ``editor`` so the owner branch is the one under test, not the admin bypass.
    """
    owner_id, owner = await _register_login(http_client, "owner", role="editor")
    member_id, member = await _register_login(http_client, "member", role="viewer")
    other_member_id, other_member = await _register_login(http_client, "other", role="viewer")
    stranger_id, stranger = await _register_login(http_client, "stranger", role="editor")
    admin_id, admin = await _register_login(http_client, "admin", role="admin")

    live = await _project(http_client, owner, "Live")
    live_bill = await _bill(http_client, owner, live, "Live bill", 3)
    live_bill_2 = await _bill(http_client, owner, live, "Live bill two", 1)
    second = await _project(http_client, owner, "Second")
    second_bill = await _bill(http_client, owner, second, "Second bill", 1)
    archived = await _project(http_client, owner, "Archived")
    archived_bill = await _bill(http_client, owner, archived, "Archived bill", 1)

    await _add_member(http_client, owner, live, member_id)
    await _add_member(http_client, owner, second, other_member_id)

    from sqlalchemy import update

    from app.database import async_session_factory
    from app.modules.projects.models import Project

    async with async_session_factory() as s:
        await s.execute(update(Project).where(Project.id == uuid.UUID(archived)).values(status="archived"))
        await s.commit()

    return {
        "users": {
            "owner": (owner_id, owner, "editor"),
            "member": (member_id, member, "viewer"),
            "other_member": (other_member_id, other_member, "viewer"),
            "stranger": (stranger_id, stranger, "editor"),
            "admin": (admin_id, admin, "admin"),
        },
        "live": live,
        "live_bill": live_bill,
        "live_bill_2": live_bill_2,
        "second": second,
        "second_bill": second_bill,
        "archived": archived,
        "archived_bill": archived_bill,
    }


@contextmanager
def _statements() -> Iterator[list[str]]:
    """Collect every SQL statement the app's engine sends while the block runs."""
    from sqlalchemy import event

    from app.database import engine

    seen: list[str] = []

    def _on_execute(conn, cursor, statement, parameters, context, executemany):  # noqa: ARG001
        seen.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", _on_execute)
    try:
        yield seen
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", _on_execute)


Guard = Callable[..., Awaitable[None]]


async def _outcome(guard: Guard, target: uuid.UUID, user_id: str, payload: dict[str, Any]) -> tuple[Any, ...]:
    """Run one guard on a fresh session: ``("ok",)`` or ``(status, detail)``, plus its statement count."""
    from app.database import async_session_factory

    async with async_session_factory() as session:
        with _statements() as sent:
            try:
                await guard(session, target, user_id, payload)
                result: tuple[Any, ...] = ("ok",)
            except HTTPException as exc:
                result = (exc.status_code, exc.detail)
        await session.rollback()
    return result, len(sent)


def _callers(world: dict) -> dict[str, tuple[str, dict[str, Any]]]:
    """Every caller as the guards see one: ``(user_id, payload)``."""
    callers = {
        name: (user_id, {"sub": user_id, "role": role}) for name, (user_id, _headers, role) in world["users"].items()
    }
    # A caller id that is not a UUID: a member of nothing, never bound into SQL.
    callers["malformed"] = ("not-a-uuid", {"sub": "not-a-uuid", "role": "editor"})
    # A guard called without a payload, as the services that reuse it do.
    owner_id = world["users"]["owner"][0]
    callers["owner_no_payload"] = (owner_id, {})
    return callers


# ── Differential oracle: the new guards refuse exactly what the old ones did ─


@pytest.mark.asyncio
async def test_bill_guard_answers_exactly_what_the_old_one_did(world):
    from app.modules.boq.router import _verify_boq_owner

    bills = {
        "live": uuid.UUID(world["live_bill"]),
        "second": uuid.UUID(world["second_bill"]),
        "archived": uuid.UUID(world["archived_bill"]),
        "ghost": uuid.uuid4(),
    }
    expected_open = {
        ("owner", "live"),
        ("owner", "second"),
        ("owner", "archived"),
        ("owner_no_payload", "live"),
        ("owner_no_payload", "second"),
        ("owner_no_payload", "archived"),
        ("member", "live"),
        ("other_member", "second"),
        ("admin", "live"),
        ("admin", "second"),
        ("admin", "archived"),
        ("admin", "ghost"),
    }
    mismatches = []
    for caller, (user_id, payload) in _callers(world).items():
        for bill, boq_id in bills.items():
            old, old_count = await _outcome(_old_verify_boq_owner, boq_id, user_id, payload)
            new, new_count = await _outcome(_verify_boq_owner, boq_id, user_id, payload)
            if old != new:
                mismatches.append(f"{caller} on {bill}: old {old}, new {new}")
            assert (new == ("ok",)) == ((caller, bill) in expected_open), f"{caller} on {bill}: {new}"
            if payload.get("role") == "admin":
                assert new_count == 0, f"the admin bypass ran {new_count} statements"
            else:
                assert new_count == 1, f"{caller} on {bill}: the guard ran {new_count} statements"
                if bill != "ghost" and caller in ("owner", "member", "other_member", "stranger"):
                    # The counter sees the old shape: the bill, then the owner,
                    # then (for a non-owner) the membership.
                    assert old_count >= 2, f"{caller} on {bill}: the old guard ran only {old_count}"
    assert not mismatches, "the bill guard changed who is refused:\n" + "\n".join(mismatches)


@pytest.mark.asyncio
async def test_project_guard_answers_exactly_what_the_old_one_did(world):
    from app.modules.boq.router import _verify_project_owner_for_boq

    projects = {
        "live": uuid.UUID(world["live"]),
        "second": uuid.UUID(world["second"]),
        "archived": uuid.UUID(world["archived"]),
        "ghost": uuid.uuid4(),
    }
    expected_open = {
        ("owner", "live"),
        ("owner", "second"),
        ("owner_no_payload", "live"),
        ("owner_no_payload", "second"),
        ("member", "live"),
        ("other_member", "second"),
        ("admin", "live"),
        ("admin", "second"),
    }
    mismatches = []
    for caller, (user_id, payload) in _callers(world).items():
        for project, project_id in projects.items():
            old, _ = await _outcome(_old_verify_project_owner_for_boq, project_id, user_id, payload)
            new, new_count = await _outcome(_verify_project_owner_for_boq, project_id, user_id, payload)
            if old != new:
                mismatches.append(f"{caller} on {project}: old {old}, new {new}")
            assert (new == ("ok",)) == ((caller, project) in expected_open), f"{caller} on {project}: {new}"
            assert new_count == 1, f"{caller} on {project}: the guard ran {new_count} statements"
    assert not mismatches, "the project guard changed who is refused:\n" + "\n".join(mismatches)


@pytest.mark.asyncio
async def test_the_refusals_carry_their_status_and_detail(world):
    """Spelled out, so a change in both copies at once cannot pass the oracle unseen."""
    from app.modules.boq.router import _verify_boq_owner, _verify_project_owner_for_boq

    stranger_id = world["users"]["stranger"][0]
    stranger = {"sub": stranger_id, "role": "editor"}
    admin_id = world["users"]["admin"][0]
    admin = {"sub": admin_id, "role": "admin"}

    result, _ = await _outcome(_verify_boq_owner, uuid.UUID(world["live_bill"]), stranger_id, stranger)
    assert result == (404, "BOQ not found")
    result, _ = await _outcome(_verify_boq_owner, uuid.uuid4(), stranger_id, stranger)
    assert result == (404, "BOQ not found")
    result, _ = await _outcome(_verify_project_owner_for_boq, uuid.UUID(world["live"]), stranger_id, stranger)
    assert result == (403, "You do not have access to this project")
    # An archived project refuses an admin too, before the admin bypass.
    result, _ = await _outcome(_verify_project_owner_for_boq, uuid.UUID(world["archived"]), admin_id, admin)
    assert result[0] == 404
    result, _ = await _outcome(_verify_project_owner_for_boq, uuid.uuid4(), admin_id, admin)
    assert result[0] == 404


@pytest.mark.asyncio
async def test_two_bills_are_guarded_in_one_statement_and_in_order(world):
    from app.modules.boq.router import _verify_boqs_owner

    member_id = world["users"]["member"][0]
    member = {"sub": member_id, "role": "viewer"}
    live = uuid.UUID(world["live_bill"])
    live_2 = uuid.UUID(world["live_bill_2"])
    second = uuid.UUID(world["second_bill"])

    result, count = await _outcome(_verify_boqs_owner, [live, live_2], member_id, member)
    assert (result, count) == (("ok",), 1)
    # One bill the member may not read refuses the pair, whichever side it is on.
    for pair in ([live, second], [second, live]):
        result, count = await _outcome(_verify_boqs_owner, pair, member_id, member)
        assert (result, count) == ((404, "BOQ not found"), 1), pair
    # A string id finds its row like a UUID does.
    result, _ = await _outcome(_verify_boqs_owner, [str(live)], member_id, member)
    assert result == ("ok",)


# ── The same refusals over HTTP ────────────────────────────────────────────


def _editor_urls(world: dict, boq_key: str = "live_bill", project_key: str = "live") -> list[str]:
    """What the BOQ editor asks for when it opens a bill (BOQEditorPage and its default panels)."""
    boq_id = world[boq_key]
    return [
        f"/api/v1/boq/boqs/{boq_id}",
        f"/api/v1/projects/{world[project_key]}",
        f"/api/v1/boq/boqs/{boq_id}/markups/",
        f"/api/v1/boq/boqs/{boq_id}/cost-breakdown/",
        "/api/v1/boq/limits/",
        f"/api/v1/boq/boqs/{boq_id}/classification/",
    ]


def _bill_urls(world: dict, boq_key: str) -> list[str]:
    return [url for url in _editor_urls(world, boq_key) if "/boq/boqs/" in url]


@pytest.mark.asyncio
async def test_owner_member_and_admin_open_the_editor(http_client, world):
    for who in ("owner", "member", "admin"):
        headers = world["users"][who][1]
        for url in _editor_urls(world):
            resp = await http_client.get(url, headers=headers)
            assert resp.status_code == 200, f"{who} {url}: {resp.status_code} {resp.text[:200]}"


@pytest.mark.asyncio
@pytest.mark.parametrize("who", ["stranger", "other_member"])
async def test_a_caller_without_access_is_refused_on_every_editor_endpoint(http_client, world, who):
    headers = world["users"][who][1]
    for url in _bill_urls(world, "live_bill"):
        resp = await http_client.get(url, headers=headers)
        assert resp.status_code == 404, f"{who} {url}: {resp.status_code}"
        assert resp.json()["detail"] == "BOQ not found"
        assert "Live bill line" not in resp.text


@pytest.mark.asyncio
async def test_a_bill_that_does_not_exist_is_404_for_everyone_but_the_admin(http_client, world):
    ghost = str(uuid.uuid4())
    for who in ("owner", "member", "stranger"):
        resp = await http_client.get(f"/api/v1/boq/boqs/{ghost}", headers=world["users"][who][1])
        assert resp.status_code == 404, f"{who}: {resp.status_code}"
        assert resp.json()["detail"] == "BOQ not found"
    # The admin passes the guard and is refused by the read itself, as before.
    resp = await http_client.get(f"/api/v1/boq/boqs/{ghost}", headers=world["users"]["admin"][1])
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_the_project_bill_list_keeps_its_refusals(http_client, world):
    url = "/api/v1/boq/boqs/?project_id={}"
    owner = world["users"]["owner"][1]
    member = world["users"]["member"][1]
    stranger = world["users"]["stranger"][1]
    other_member = world["users"]["other_member"][1]
    admin = world["users"]["admin"][1]

    for headers in (owner, member, admin):
        resp = await http_client.get(url.format(world["live"]), headers=headers)
        assert resp.status_code == 200, resp.text
        assert {row["name"] for row in resp.json()} == {"Live bill", "Live bill two"}
    for headers in (stranger, other_member):
        resp = await http_client.get(url.format(world["live"]), headers=headers)
        assert resp.status_code == 403, resp.text
        assert resp.json()["detail"] == "You do not have access to this project"
    for headers in (owner, admin):
        resp = await http_client.get(url.format(world["archived"]), headers=headers)
        assert resp.status_code == 404, resp.text
        resp = await http_client.get(url.format(uuid.uuid4()), headers=headers)
        assert resp.status_code == 404, resp.text


@pytest.mark.asyncio
async def test_a_bill_cannot_be_created_on_a_project_the_caller_cannot_reach(http_client, world):
    body = {"project_id": world["live"], "name": "Intruder bill", "description": ""}
    resp = await http_client.post("/api/v1/boq/boqs/", json=body, headers=world["users"]["stranger"][1])
    assert resp.status_code == 403, resp.text
    archived = {"project_id": world["archived"], "name": "Late bill", "description": ""}
    resp = await http_client.post("/api/v1/boq/boqs/", json=archived, headers=world["users"]["owner"][1])
    assert resp.status_code == 404, resp.text


@pytest.mark.asyncio
async def test_comparison_guards_both_bills(http_client, world):
    url = "/api/v1/boq/boqs/{}/compare/{}"
    member = world["users"]["member"][1]
    resp = await http_client.get(url.format(world["live_bill"], world["live_bill_2"]), headers=member)
    assert resp.status_code == 200, resp.text
    # The member may read ``live`` but not ``second``: refused on either side.
    for pair in ((world["live_bill"], world["second_bill"]), (world["second_bill"], world["live_bill"])):
        resp = await http_client.get(url.format(*pair), headers=member)
        assert resp.status_code == 404, f"{pair}: {resp.status_code}"
        assert resp.json()["detail"] == "BOQ not found"


# ── Statement counts ───────────────────────────────────────────────────────


async def _load(http_client: AsyncClient, headers: dict[str, str], urls: list[str]) -> list[str]:
    for url in urls:  # warm, so a first-use lookup does not land in one count only
        await http_client.get(url, headers=headers)
    with _statements() as sent:
        for url in urls:
            resp = await http_client.get(url, headers=headers)
            assert resp.status_code == 200, f"{url}: {resp.status_code}"
    return sent


def _membership_reads(statements: list[str]) -> list[str]:
    return [s for s in statements if "oe_teams_membership" in s]


@pytest.mark.asyncio
async def test_editor_load_guards_each_request_in_one_statement(http_client, world):
    for who in ("owner", "member"):
        headers = world["users"][who][1]
        for url in _bill_urls(world, "live_bill"):
            with _statements() as sent:
                resp = await http_client.get(url, headers=headers)
            assert resp.status_code == 200, url
            guard = [s for s in sent if "oe_boq_boq" in s and "oe_teams_membership" in s]
            assert len(guard) == 1, f"{who} {url}: {len(guard)} guard statements"
            assert not [
                s for s in sent if " ".join(s.split()).startswith("SELECT oe_projects_project.owner_id FROM")
            ], f"{who} {url}: the project owner is still read on its own"
            assert len(_membership_reads(sent)) == 1, f"{who} {url}: membership read more than once"


@pytest.mark.asyncio
async def test_a_member_opens_the_editor_for_what_the_owner_pays(http_client, world):
    urls = _editor_urls(world)
    owner_load = await _load(http_client, world["users"]["owner"][1], urls)
    member_load = await _load(http_client, world["users"]["member"][1], urls)
    print(f"\n[statements] editor load: owner {len(owner_load)}, member {len(member_load)}")
    # The project read (``GET /projects/{id}``) is guarded outside the BOQ
    # module and still looks a member up on its own; that one is the only gap.
    assert len(member_load) <= len(owner_load) + 1, (
        f"a team member's page load cost {len(member_load)} statements against the owner's {len(owner_load)}"
    )
    assert len(owner_load) <= EDITOR_LOAD_CEILING, (
        f"opening a bill cost the owner {len(owner_load)} statements, ceiling {EDITOR_LOAD_CEILING}:\n"
        + "\n".join(" ".join(s.split())[:160] for s in owner_load)
    )
    assert len(member_load) <= EDITOR_LOAD_CEILING + 1
