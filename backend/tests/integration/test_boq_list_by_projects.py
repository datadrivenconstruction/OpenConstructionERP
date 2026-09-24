# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""``POST /boqs/by-projects/``: the bill register of many projects in one call.

The bill register page used to ask ``GET /boqs/?project_id=`` once per project.
Browsers run six requests to a host at a time over HTTP/1.1 and the desktop app
has nothing better, so the page spent most of its wait queueing. The batched
call has to be a drop-in for those N calls, which is what these cases pin:

* It answers, for every project, exactly what the single call answers, with
  ``offset`` and ``limit`` applied per project, never across the batch.
* It keeps the single call's access rules. A project the single call refuses
  because it is archived or not readable by the caller is left out of the
  answer, never answered, and the missing key is how the page tells it apart
  from a project with no bills and says which projects its totals exclude. The
  page asks for exactly the projects its project list showed, so such a
  project was archived or unshared while the page was open, and refusing the
  whole register for it left the reader with no estimates at all.
* An id that names no project at all still refuses the whole request, loudly,
  and names the id: the page cannot have been shown it.
* It reads nothing a caller could not read one project at a time: every user
  and project pair either answers the single call's rows or answers nothing
  for that project, and a batch holding one refused project answers exactly
  what the batch without it answers. The admin is in that table on purpose,
  because the admin bypass is the one branch where the two checks could drift
  apart unseen.
* Every project the project list shows a user can be batched, so the page's
  own request never fails for a reason the page cannot see.
* It stays a read on the read-only demo.
* Its statement count does not grow with the number of projects.

The main requester is an ``editor``, not an admin, because an admin skips the
ownership check and would make the foreign-project case pass vacuously.

Run:
    cd backend
    python -m pytest tests/integration/test_boq_list_by_projects.py -v
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

import app.modules.boq.models  # noqa: F401
import app.modules.projects.models  # noqa: F401
import app.modules.teams.models  # noqa: F401
import app.modules.users.models  # noqa: F401

pytestmark = pytest.mark.tenant_isolation

BATCH_URL = "/api/v1/boq/boqs/by-projects/"


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


async def _register_login(client: AsyncClient, tag: str, *, role: str | None) -> tuple[str, dict[str, str]]:
    """Register, activate, optionally promote, then log in. Returns ``(user_id, headers)``."""
    from sqlalchemy import update

    from app.database import async_session_factory
    from app.modules.users.models import User

    email = f"{tag}-{uuid.uuid4().hex[:8]}@boq-by-projects.io"
    password = f"BoqBatch{uuid.uuid4().hex[:6]}9"
    reg = await client.post(
        "/api/v1/users/auth/register",
        json={"email": email, "password": password, "full_name": f"User {tag}"},
    )
    assert reg.status_code in (200, 201), f"register failed for {tag}: {reg.text}"
    values: dict[str, object] = {"is_active": True}
    if role is not None:
        values["role"] = role
    async with async_session_factory() as s:
        await s.execute(update(User).where(User.email == email.lower()).values(**values))
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
                "quantity": 2.5 + i,
                "unit_rate": 110.0 + 7 * i,
            },
            headers=headers,
        )
        assert pos.status_code == 201, f"add position failed: {pos.text}"
    return boq_id


@pytest_asyncio.fixture(scope="module")
async def world(http_client):
    """Projects for one owner, one foreign project, one member, one admin, one archived project.

    ``busy`` has three bills so a page can be cut inside it, ``single`` one,
    ``empty`` none. ``extra_a`` and ``extra_b`` exist so the statement count
    can be compared between a batch of two projects and a batch of four, each
    project holding priced lines so every per-project lookup actually runs.
    """
    owner_id, owner = await _register_login(http_client, "owner", role="editor")
    _, stranger = await _register_login(http_client, "stranger", role="editor")
    # Every role is set explicitly. Registration makes an account admin
    # whenever no admin exists yet, and the roles set above leave none, so a
    # member left at the default would come out admin and pass every check.
    member_id, member = await _register_login(http_client, "member", role="viewer")
    _, admin = await _register_login(http_client, "admin", role="admin")

    busy = await _project(http_client, owner, "Busy")
    for n, lines in enumerate((2, 1, 3)):
        await _bill(http_client, owner, busy, f"Busy bill {n + 1}", lines)
    single = await _project(http_client, owner, "Single")
    await _bill(http_client, owner, single, "Single bill", 2)
    empty = await _project(http_client, owner, "Empty")
    extra_a = await _project(http_client, owner, "Extra A")
    await _bill(http_client, owner, extra_a, "Extra A bill", 1)
    extra_b = await _project(http_client, owner, "Extra B")
    await _bill(http_client, owner, extra_b, "Extra B bill", 1)

    archived = await _project(http_client, owner, "Archived")
    await _bill(http_client, owner, archived, "Archived bill", 1)
    from sqlalchemy import update

    from app.database import async_session_factory
    from app.modules.projects.models import Project

    async with async_session_factory() as s:
        await s.execute(update(Project).where(Project.id == uuid.UUID(archived)).values(status="archived"))
        await s.commit()

    foreign = await _project(http_client, stranger, "Foreign")
    await _bill(http_client, stranger, foreign, "Foreign bill", 1)

    add = await http_client.post(
        f"/api/v1/projects/{single}/members/",
        json={"user_id": member_id, "role": "viewer"},
        headers=owner,
    )
    assert add.status_code in (200, 201), f"add member failed: {add.text}"

    return {
        "owner": owner,
        "owner_id": owner_id,
        "member": member,
        "stranger": stranger,
        "admin": admin,
        "busy": busy,
        "single": single,
        "empty": empty,
        "extra_a": extra_a,
        "extra_b": extra_b,
        "archived": archived,
        "foreign": foreign,
    }


async def _single(client: AsyncClient, headers: dict[str, str], project_id: str, query: str = "") -> list[dict]:
    resp = await client.get(f"/api/v1/boq/boqs/?project_id={project_id}{query}", headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


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


# ── Same answer as the single call ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_batch_answers_what_one_call_per_project_answers(http_client, world):
    ids = [world["busy"], world["single"], world["empty"]]
    resp = await http_client.post(BATCH_URL, json={"project_ids": ids}, headers=world["owner"])
    assert resp.status_code == 200, resp.text
    register = resp.json()

    assert list(register) == ids, "every requested project is a key, in request order"
    for pid in ids:
        assert register[pid] == await _single(http_client, world["owner"], pid)
    assert [len(register[pid]) for pid in ids] == [3, 1, 0]
    # Priced lines reached the totals, so the equality above compared real money.
    assert all(float(b["grand_total"]) > 0 for b in register[world["busy"]])


@pytest.mark.asyncio
async def test_offset_and_limit_apply_per_project(http_client, world):
    ids = [world["busy"], world["single"]]
    resp = await http_client.post(f"{BATCH_URL}?offset=1&limit=1", json={"project_ids": ids}, headers=world["owner"])
    assert resp.status_code == 200, resp.text
    register = resp.json()

    for pid in ids:
        assert register[pid] == await _single(http_client, world["owner"], pid, "&offset=1&limit=1")
    # ``busy`` has three bills, so its page is its second bill alone. A limit
    # applied across the batch would have given ``single`` nothing to skip into
    # and ``busy`` a page shifted by it.
    assert len(register[world["busy"]]) == 1
    assert register[world["single"]] == []

    whole = await _single(http_client, world["owner"], world["busy"])
    assert register[world["busy"]][0]["id"] == whole[1]["id"]


@pytest.mark.asyncio
async def test_limit_bound_is_the_single_calls_bound(http_client, world):
    resp = await http_client.post(
        f"{BATCH_URL}?limit=101", json={"project_ids": [world["busy"]]}, headers=world["owner"]
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_empty_list_answers_an_empty_register(http_client, world):
    resp = await http_client.post(BATCH_URL, json={"project_ids": []}, headers=world["owner"])
    assert resp.status_code == 200, resp.text
    assert resp.json() == {}


@pytest.mark.asyncio
async def test_repeated_id_is_answered_once(http_client, world):
    ids = [world["single"], world["single"]]
    resp = await http_client.post(BATCH_URL, json={"project_ids": ids}, headers=world["owner"])
    assert resp.status_code == 200, resp.text
    assert list(resp.json()) == [world["single"]]


@pytest.mark.asyncio
async def test_more_than_the_projects_page_cap_is_refused(http_client, world):
    ids = [str(uuid.uuid4()) for _ in range(501)]
    resp = await http_client.post(BATCH_URL, json={"project_ids": ids}, headers=world["owner"])
    assert resp.status_code == 422


# ── An id that names no project fails the whole call, loudly ───────────────


@pytest.mark.asyncio
async def test_unknown_project_fails_the_whole_batch_and_is_named(http_client, world):
    ghost = str(uuid.uuid4())
    ids = [world["busy"], ghost, world["single"]]
    resp = await http_client.post(BATCH_URL, json={"project_ids": ids}, headers=world["owner"])

    assert resp.status_code == 404, resp.text
    detail = resp.json()["detail"]
    assert detail["error"] == "projects_not_found"
    assert detail["project_ids"] == [ghost]
    assert detail["not_found"] == [ghost]
    assert detail["forbidden"] == []
    assert ghost in detail["message"]
    # Nothing about the good projects travels with the refusal.
    assert "grand_total" not in resp.text
    assert world["busy"] not in resp.text


@pytest.mark.asyncio
async def test_an_unknown_id_is_refused_even_beside_a_skipped_one(http_client, world):
    ghost = str(uuid.uuid4())
    ids = [world["foreign"], world["busy"], world["archived"], ghost]
    resp = await http_client.post(BATCH_URL, json={"project_ids": ids}, headers=world["owner"])
    assert resp.status_code == 404, resp.text
    detail = resp.json()["detail"]
    assert detail["project_ids"] == [ghost], "only the id that names nothing is named"
    assert detail["not_found"] == [ghost]
    assert detail["forbidden"] == []
    assert "grand_total" not in resp.text


# ── A project archived or unshared since the page loaded is left out ───────


@pytest.mark.asyncio
async def test_archived_project_is_left_out_and_the_rest_answered(http_client, world):
    single = await http_client.get(f"/api/v1/boq/boqs/?project_id={world['archived']}", headers=world["owner"])
    assert single.status_code == 404, "the single call still refuses it"

    ids = [world["single"], world["archived"]]
    resp = await http_client.post(BATCH_URL, json={"project_ids": ids}, headers=world["owner"])
    assert resp.status_code == 200, resp.text
    assert list(resp.json()) == [world["single"]], "the archived project is not a key"
    assert resp.json()[world["single"]] == await _single(http_client, world["owner"], world["single"])
    assert "Archived bill" not in resp.text


@pytest.mark.asyncio
async def test_another_users_project_is_left_out_and_the_rest_answered(http_client, world):
    single = await http_client.get(f"/api/v1/boq/boqs/?project_id={world['foreign']}", headers=world["owner"])
    assert single.status_code == 403, "the single call still refuses it"

    ids = [world["busy"], world["foreign"]]
    resp = await http_client.post(BATCH_URL, json={"project_ids": ids}, headers=world["owner"])
    assert resp.status_code == 200, resp.text
    assert list(resp.json()) == [world["busy"]], "the unreadable project is not a key"
    assert "Foreign bill" not in resp.text


@pytest.mark.asyncio
async def test_a_batch_of_only_skipped_projects_answers_an_empty_register(http_client, world):
    ids = [world["foreign"], world["archived"]]
    resp = await http_client.post(BATCH_URL, json={"project_ids": ids}, headers=world["owner"])
    assert resp.status_code == 200, resp.text
    assert resp.json() == {}


# ── Team membership counts, as it does for the single call ─────────────────


@pytest.mark.asyncio
async def test_team_member_reads_the_project_shared_with_them(http_client, world):
    resp = await http_client.post(BATCH_URL, json={"project_ids": [world["single"]]}, headers=world["member"])
    assert resp.status_code == 200, resp.text
    assert resp.json()[world["single"]] == await _single(http_client, world["member"], world["single"])

    resp = await http_client.post(
        BATCH_URL, json={"project_ids": [world["single"], world["busy"]]}, headers=world["member"]
    )
    assert resp.status_code == 200, resp.text
    assert list(resp.json()) == [world["single"]], "a project not shared with the member is not a key"
    assert "Busy bill" not in resp.text


# ── Exactly the single call's access rule, for every user ──────────────────

_USERS = ("owner", "stranger", "member", "admin")
_PROJECTS = ("busy", "single", "empty", "archived", "foreign")


def _project_ids(world: dict) -> dict[str, str]:
    """Every project of the world by name, plus one id that names nothing."""
    return {**{key: world[key] for key in _PROJECTS}, "ghost": str(uuid.uuid4())}


@pytest.mark.asyncio
async def test_each_project_alone_answers_what_the_single_call_answers(http_client, world):
    """User by project, the batch of one gives the single call's rows, or nothing for a project it refuses.

    A project the single call refuses and that exists is left out (200, empty
    register); an id that names no project is 404 in both.
    """
    ids = _project_ids(world)
    table: dict[tuple[str, str], int] = {}
    for user in _USERS:
        for key, pid in ids.items():
            single = await http_client.get(f"/api/v1/boq/boqs/?project_id={pid}", headers=world[user])
            batch = await http_client.post(BATCH_URL, json={"project_ids": [pid]}, headers=world[user])
            table[(user, key)] = single.status_code
            if single.status_code == 200:
                assert batch.status_code == 200, f"{user} on {key}: {batch.text[:300]}"
                assert batch.json() == {pid: single.json()}
            elif key == "ghost":
                assert batch.status_code == 404, f"{user} on {key}: {batch.text[:300]}"
                assert "grand_total" not in batch.text
            else:
                assert batch.status_code == 200, f"{user} on {key}: {batch.text[:300]}"
                assert batch.json() == {}, f"{user} read {key} through the batch: {batch.text[:300]}"

    print("\n[access] " + ", ".join(f"{u}/{k}={s}" for (u, k), s in table.items()))
    # The comparison proves something only if the table holds every answer.
    assert set(table.values()) == {200, 403, 404}
    # The cells the checks could most easily disagree on.
    assert table[("admin", "foreign")] == 200, "an admin reads every live project"
    assert table[("admin", "archived")] == 404, "an archived project is gone, for an admin too"
    assert table[("member", "single")] == 200, "a team member reads the project shared with them"
    assert table[("member", "busy")] == 403
    assert table[("stranger", "busy")] == 403


@pytest.mark.asyncio
async def test_a_batch_reads_nothing_its_projects_do_not_read_alone(http_client, world):
    """Adding one refused project to a batch that answers changes nothing in the answer."""
    ids = {key: pid for key, pid in _project_ids(world).items() if key != "ghost"}
    for user in _USERS:
        readable: list[str] = []
        refused: list[str] = []
        for pid in ids.values():
            single = await http_client.get(f"/api/v1/boq/boqs/?project_id={pid}", headers=world[user])
            (readable if single.status_code == 200 else refused).append(pid)
        assert readable, f"{user} reads no project, so the case below would be vacuous"
        assert refused, f"{user} is refused no project, so the case below would be vacuous"

        whole = await http_client.post(BATCH_URL, json={"project_ids": readable}, headers=world[user])
        assert whole.status_code == 200, f"{user}: {whole.text[:300]}"
        assert list(whole.json()) == readable

        for pid in refused:
            resp = await http_client.post(BATCH_URL, json={"project_ids": [*readable, pid]}, headers=world[user])
            assert resp.status_code == 200, f"{user} with {pid}: {resp.text[:300]}"
            assert resp.json() == whole.json(), f"{user} read {pid} through the batch: {resp.text[:300]}"


@pytest.mark.asyncio
async def test_every_project_the_project_list_shows_can_be_batched(http_client, world):
    """The page asks for the bills of exactly the projects it was listed, so those must never be refused."""
    for user in _USERS:
        listed = await http_client.get("/api/v1/projects/?limit=500", headers=world[user])
        assert listed.status_code == 200, listed.text
        project_ids = [p["id"] for p in listed.json()]
        assert project_ids, f"{user} is listed no project"

        resp = await http_client.post(BATCH_URL, json={"project_ids": project_ids}, headers=world[user])
        assert resp.status_code == 200, f"{user} was listed a project the batch refuses: {resp.text[:500]}"
        assert list(resp.json()) == project_ids


# ── A read on the read-only demo ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_the_read_only_demo_still_answers_the_batch(http_client, world, monkeypatch):
    """The batch posts a body but only reads, so the demo serves it, and serves the same answer.

    The demo refuses every POST it has not been told is a read, before the
    handler runs, and a database guard refuses any write a read lets through.
    A 200 here therefore also says the batch wrote nothing.
    """
    from app.config import get_settings

    ids = [world["busy"], world["single"], world["empty"]]
    before = await http_client.post(BATCH_URL, json={"project_ids": ids}, headers=world["owner"])
    assert before.status_code == 200, before.text

    # The flag is flipped on the live settings object, never by rebuilding it.
    # The app patched that object at startup (in development it carries the
    # persisted signing secret), so a rebuilt one would reject every token this
    # module has issued, and would do so for every test that runs after this.
    settings = get_settings()
    with monkeypatch.context() as patch:
        patch.setattr(settings, "demo_read_only", True)
        assert get_settings().demo_read_only is True

        # The flag is really on: a write beside the read is refused.
        write = await http_client.post(
            "/api/v1/boq/boqs/",
            json={"project_id": world["single"], "name": "Refused on the demo", "description": ""},
            headers=world["owner"],
        )
        assert write.status_code == 403, write.text
        assert write.json()["detail"]["error"] == "demo_read_only"

        during = await http_client.post(BATCH_URL, json={"project_ids": ids}, headers=world["owner"])
    # The app and its settings outlive this test, so the flag must not.
    assert get_settings().demo_read_only is False

    assert during.status_code == 200, during.text
    assert during.json() == before.json()


# ── Cost does not grow with the number of projects ─────────────────────────


@pytest.mark.asyncio
async def test_statement_count_does_not_grow_with_projects(http_client, world):
    two = [world["busy"], world["single"]]
    four = [*two, world["extra_a"], world["extra_b"]]

    # Warm both paths once so a first-use lookup does not land in one count only.
    for ids in (two, four):
        warm = await http_client.post(BATCH_URL, json={"project_ids": ids}, headers=world["owner"])
        assert warm.status_code == 200, warm.text

    with _statements() as batch_two:
        await http_client.post(BATCH_URL, json={"project_ids": two}, headers=world["owner"])
    with _statements() as batch_four:
        await http_client.post(BATCH_URL, json={"project_ids": four}, headers=world["owner"])
    with _statements() as singles_four:
        for pid in four:
            await _single(http_client, world["owner"], pid)

    print(
        f"\n[statements] batch of 2: {len(batch_two)}, batch of 4: {len(batch_four)}, "
        f"4 single calls: {len(singles_four)}"
    )
    assert len(batch_four) == len(batch_two), (
        "the batched register issued more statements for four projects than for two, so something "
        f"in it still runs once per project:\n{batch_four}"
    )
    assert len(batch_four) < len(singles_four)
