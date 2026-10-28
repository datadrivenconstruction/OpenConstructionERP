"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The public demo is genuinely read-only, and only when it is switched on.

The claim under test is not "the guard answers 403". It is that with the flag
on, nothing a visitor can reach writes to the database, which is a different
and much stronger claim, so the evidence is a row census of every table in the
schema taken before and after the write attempts rather than the status codes
the API returned.

Stated that way on purpose, because the wider claim - that with the flag on
nothing in the database moves at all - is false on a running deployment, and a
guarantee stated too strongly is worse than a narrower one stated exactly: the
day it breaks nobody believes the test. Background housekeeping keeps running.
The known example is the collaboration-lock sweeper, which deletes expired
rows every thirty seconds outside any request, so no request-scoped guard sees
it. It is stopped for the duration of this suite, in ``app_client``, which
says why. What is guaranteed here is about the surface a visitor can reach.

Three phases, all in one run, on one application instance:

* Phase A, flag ON  - every non-safe method on every mounted route is refused
  with the exact contract, and the census is unchanged afterwards.
* Phase B, flag OFF - the same writes all succeed and the census grows. Without
  this control, phase A would also pass against a harness that never manages to
  write anything, and a guard that is on for everybody would look correct.
* Phase C, flag ON  - reads still work, including the ones that post a body,
  and a visitor can still sign in.

The flag is flipped between phases on a single app built once, which is also
the point: it proves the value is read per request rather than baked in at
construction, so nobody can later flip the default and have this suite stay
green.

Run: pytest tests/integration/test_demo_read_only.py -v
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Iterator
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.config import get_settings
from app.core.demo_read_only import (
    _ALWAYS_WRITABLE,
    _AUTHENTICATION_WRITABLE,
    ALLOWED_ENDPOINTS,
    DEMO_READ_ONLY_ERROR,
    SAFE_METHODS,
    demo_read_only_guard,
    endpoint_key,
)
from app.database import async_session_factory
from app.main import create_app

#: Tables the guard deliberately lets a permitted request write. Taken from the
#: module rather than restated here: a second copy of the decision would let
#: someone widen the exemption without this test noticing. They are the trace
#: of a visit rather than demo content, and they are reported separately below
#: instead of being quietly dropped from the comparison.
EXEMPT_TABLES = set(_ALWAYS_WRITABLE) | set(_AUTHENTICATION_WRITABLE)

#: A stand-in for every path parameter. The guard refuses before validation, so
#: the value only has to be well-formed enough not to 404 on the router.
_ANY_ID = "00000000-0000-0000-0000-000000000001"


@pytest.fixture(autouse=True)
def _leave_the_flag_off_afterwards():
    """No test in this file may leave a read-only deployment behind it.

    ``get_settings`` is an ``lru_cache``, so restoring the environment is not
    enough on its own: the cached Settings object built while the flag was on
    would still be handed to whatever runs next. Clear it explicitly rather
    than relying on the order fixture finalizers happen to run in.
    """
    yield
    import os

    os.environ.pop("OE_DEMO_READ_ONLY", None)
    get_settings.cache_clear()
    assert get_settings().demo_read_only is False


def _set_flag(monkeypatch: pytest.MonkeyPatch, *, on: bool) -> None:
    """Flip the read-only demo flag for subsequent requests."""
    monkeypatch.setenv("OE_DEMO_READ_ONLY", "true" if on else "false")
    get_settings.cache_clear()
    assert get_settings().demo_read_only is on


async def _census() -> dict[str, tuple[int, str]]:
    """Row count *and* a content digest for every table in the public schema.

    Generated from the catalog, not from a hand-picked list: a guard that
    refuses the endpoints someone thought of while a different one writes is
    the failure mode this test exists to catch, and a hand-written table list
    would share the same blind spot as the hand-written endpoint list.

    The digest is here because a row count alone is blind to the write that
    matters most on a demo: an UPDATE. Editing every project's name leaves
    every count identical. Hashing the ordered text of each row catches it.

    ``row::text`` renders timestamps through ``DateStyle`` and ``TimeZone`` and
    floats through ``extra_float_digits``, all of them per-session settings.
    Two snapshots taken on different pooled connections could therefore differ
    with nothing written at all, which would read as a guard failure. Pinning
    the three of them makes the digest a function of the data alone.
    """
    async with async_session_factory() as session:
        await session.execute(text("SET LOCAL TimeZone = 'UTC'"))
        await session.execute(text("SET LOCAL DateStyle = 'ISO, YMD'"))
        await session.execute(text("SET LOCAL extra_float_digits = 0"))
        names = [
            row[0]
            for row in (
                await session.execute(
                    text(
                        "SELECT c.relname FROM pg_class c "
                        "JOIN pg_namespace n ON n.oid = c.relnamespace "
                        "WHERE c.relkind = 'r' AND n.nspname = 'public' "
                        "ORDER BY c.relname"
                    )
                )
            ).all()
        ]
        if not names:
            return {}
        union = " UNION ALL ".join(
            f"SELECT '{n}' AS t, count(*) AS c, "
            f"coalesce(md5(string_agg(x::text, '|' ORDER BY x::text)), '-') AS d "
            f'FROM "{n}" x'
            for n in names
        )
        rows = (await session.execute(text(union))).all()
    return {row[0]: (int(row[1]), str(row[2])) for row in rows}


def _diff(
    before: dict[str, tuple[int, str]], after: dict[str, tuple[int, str]]
) -> dict[str, tuple[tuple[int, str], tuple[int, str]]]:
    """Tables whose contents changed, as ``{table: (before, after)}``."""
    moved: dict[str, tuple[tuple[int, str], tuple[int, str]]] = {}
    for table in sorted(set(before) | set(after)):
        was, now = before.get(table, (0, "-")), after.get(table, (0, "-"))
        if was != now:
            moved[table] = (was, now)
    return moved


def _rows(census: dict[str, tuple[int, str]]) -> int:
    """Total rows across the whole schema."""
    return sum(count for count, _digest in census.values())


def _assert_contract(response: Any, where: str) -> None:
    """The refusal is exactly the shape the screen was built against."""
    assert response.status_code == 403, f"{where}: expected 403, got {response.status_code} {response.text[:200]}"
    body = response.json()
    assert set(body) == {"detail"}, f"{where}: unexpected top-level keys {sorted(body)}"
    detail = body["detail"]
    assert isinstance(detail, dict), f"{where}: detail is {type(detail).__name__}, not an object"
    assert set(detail) == {"error", "message"}, f"{where}: unexpected detail keys {sorted(detail)}"
    assert detail["error"] == DEMO_READ_ONLY_ERROR
    assert isinstance(detail["message"], str) and detail["message"].strip()


#: The curated writes. Each one has to succeed with the flag off, which is what
#: makes its refusal with the flag on mean something.
def _writes(marker: str) -> list[tuple[str, str, dict[str, Any] | None]]:
    return [
        (
            "POST",
            "/api/v1/projects/",
            {"name": f"Demo guard {marker}", "currency": "EUR", "region": "DACH"},
        ),
        (
            "POST",
            "/api/v1/costs/",
            {
                "code": f"DGC-{marker}",
                "description": f"Demo guard item {marker}",
                "unit": "m3",
                "rate": "123.45",
                "currency": "EUR",
            },
        ),
        (
            "POST",
            "/api/v1/users/auth/register",
            {
                "email": f"guard-{marker}@demo-guard.io",
                "password": f"GuardPass{marker}9!",
                "full_name": "Guard Probe",
            },
        ),
        ("PATCH", "/api/v1/users/me/", {"full_name": f"Renamed {marker}"}),
        ("PUT", "/api/v1/users/me/sidebar-preferences/", {"hidden_modules": [f"/{marker}"]}),
        ("POST", "/api/v1/users/me/api-keys/", {"name": f"guard-{marker}"}),
    ]


@pytest_asyncio.fixture(scope="module")
async def app_client():
    """One application, one lifespan, for every phase below.

    The collaboration-lock sweeper is stopped for the duration, and which of
    the two available fixes that is matters. The sweeper deletes expired lock
    rows on a timer with no request scope, so layer 2 ignores it by design and
    a census that straddles a sweep sees ``oe_collab_lock`` fall on its own.
    It is reproducible rather than theoretical: run this file in one pytest
    process with ``test_collab_locks_ws.py``, which leaves lock rows behind,
    and phase C goes red with that table going one row to zero. Each file is
    green alone, which is what makes it nasty.

    The other fix was to add the table to the exempt set, and it was rejected.
    The exempt set is what this suite uses to say "a write here is allowed",
    and widening it to silence a true observation would spend the instrument
    that has to catch the untrue one later - a request-scoped write to that
    same table would then pass unremarked forever. Stopping the writer keeps
    the observation about request-scoped writes, which is the claim under test,
    and leaves the table fully watched.

    Stopped rather than skipped over, so what is excluded is one background
    task named here, not a whole table for every reason.
    """
    from app.modules.collaboration_locks.sweeper import stop_sweeper

    app = create_app()
    async with app.router.lifespan_context(app):
        # After startup, because startup is what spawns it.
        stop_sweeper()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test", timeout=60.0) as ac:
            yield app, ac


@pytest_asyncio.fixture(scope="module")
async def auth_headers(app_client):
    """Register, promote and sign in while the flag is still off."""
    from sqlalchemy import update as sa_update

    from app.modules.users.models import User

    _app, client = app_client
    get_settings.cache_clear()
    unique = uuid.uuid4().hex[:8]
    email = f"dro-{unique}@demo-guard.io"
    password = f"DroPass{unique}9!"

    registered = await client.post(
        "/api/v1/users/auth/register",
        json={"email": email, "password": password, "full_name": "Read-only Probe"},
    )
    assert registered.status_code == 201, registered.text

    async with async_session_factory() as session:
        await session.execute(sa_update(User).where(User.email == email.lower()).values(role="admin", is_active=True))
        await session.commit()

    signed_in = await client.post("/api/v1/users/auth/login", json={"email": email, "password": password})
    assert signed_in.status_code == 200, signed_in.text
    return {
        "headers": {"Authorization": f"Bearer {signed_in.json()['access_token']}"},
        "email": email,
        "password": password,
    }


#: Smallest believable size for the mutating surface. The product mounts
#: thousands; this is a floor that only a broken census can fall through, set
#: far below the real number so a genuine reorganisation of the API does not
#: trip it. See :func:`walk_routes` for what fell through before it existed.
_MUTATING_ROUTE_FLOOR = 1000

#: Every WebSocket the application mounts, spelled out rather than counted.
#:
#: The HTTP sweep gets a floor because its population is in the thousands and
#: moves with every feature. The socket population is five, so it gets the
#: stronger thing: the exact set. A floor would only catch the sweep going to
#: nothing, and the failure worth catching here is the sweep coming back with
#: SOME of them - three out of five still satisfies "every socket I found
#: carries the guard" while saying nothing about the two that went missing.
#:
#: Five entries for three declarations because the module loader mounts each
#: module twice when its directory name is not already kebab-case, once at the
#: canonical prefix and once at the legacy underscore mirror. ``notifications``
#: is spelled the same either way and so appears once; ``collaboration_locks``
#: becomes ``collaboration-locks`` and ``global_presence`` becomes
#: ``global-presence``, so each appears twice. Adding a socket is
#: meant to fail here: it is a line in this set, and a moment's thought about
#: whether it belongs in the demo allowlist.
_EXPECTED_SOCKET_PATHS = frozenset(
    {
        "/api/v1/notifications/ws/",
        "/api/v1/collaboration-locks/presence/",
        "/api/v1/collaboration_locks/presence/",
        "/api/v1/global-presence/ws/",
        "/api/v1/global_presence/ws/",
    }
)


def walk_routes(routes: Any, prefix: str = "", inherited: tuple = ()) -> Iterator[tuple[str, Any, tuple]]:
    """Every route the application answers on, as ``(full_path, route, inherited)``.

    ``inherited`` is the dependencies the route picks up from the routers it is
    mounted through, which on current FastAPI is where they live rather than on
    the route itself. See the note on effective dependencies at the end.

    Reading ``app.routes`` directly is wrong on current FastAPI and this is not
    a theoretical concern: it is how this file came to verify the read-only
    guarantee against five endpoints out of roughly five thousand, in the only
    lane that gates, while passing locally for a completely different reason.

    Up to 0.140, ``include_router`` copied the sub-router's routes into the
    application's own table, already carrying their full prefix, so iterating
    ``app.routes`` was the whole answer. From 0.141 an include appends ONE
    opaque ``_IncludedRouter`` wrapper that holds the router and resolves paths
    when a request arrives. Measured on 0.141.1: the wrapper has no ``methods``
    and no ``path``, so a loop that skips entries without them drops every
    router-mounted route in the product in silence, leaving only the handful
    declared directly on the app object with ``@app.post``. ``pyproject.toml``
    pins ``fastapi>=0.116,<1`` and CI installs fresh, so CI runs the second
    shape while the local virtualenvs still run the first. Both must work.

    So: recurse through ``original_router`` and accumulate ``include_context``
    prefixes; nested includes wrap again, so it has to recurse rather than
    descend one level. On the older shape neither attribute exists, the prefix
    stays empty and the route's own already-prefixed path is yielded, which is
    why one traversal serves both. Verified to return identical results on
    0.136.3 and 0.141.1 for a nested app with a mirrored include.

    Both attributes are private and have moved once already, which is the whole
    reason this comment exists. Two defences: callers cross-check the count
    against ``app.openapi()``, which is public and needs no private attribute,
    and the sweep asserts a floor. FastAPI's own ``iter_route_contexts`` was
    tried instead and rejected: on 0.141.1 it yields ``path=''`` for every
    WebSocket route, so it cannot enumerate sockets at all, and sockets are the
    half no OpenAPI cross-check can cover.

    On effective dependencies, which is the other half of the same change.
    Up to 0.140 an application-level dependency was COPIED onto every route as
    it was included, so ``route.dependencies`` was the whole answer. On 0.141 it
    is not copied: a router-mounted route reads ``route.dependencies == []`` and
    the dependency is applied from the router chain when the request arrives.
    Measured both ways on 0.141.1: the real sockets report no dependencies and
    the guard demonstrably still runs on them. So a test that asserts on
    ``route.dependencies`` alone is asserting a storage detail that has already
    changed once, and it fails on the version CI installs while the behaviour it
    cares about is fine. Callers must union the route's own dependencies with
    what is yielded here.

    What accumulates is ``include_context.dependencies``, not the included
    router's own ``dependencies``, and the difference is a real gap rather than
    a preference. A router's own dependencies are copied onto its routes when
    the route is declared, so they already arrive in ``route.dependencies``.
    The include context is where the two that are NOT copied end up: the
    application-level ones and any passed to ``include_router(dependencies=)``.
    Accumulating the router's own instead reconstructs the application level
    and re-adds what the route already had, and silently drops every
    include-level dependency. Measured on a four-level case - application,
    include of A, include of B, router B's own, plus one on the route - the
    context accumulator reproduces all five on 0.141.1, and the resulting set
    is identical to what 0.136.3 merges flat onto the route. That equality
    across versions is the property worth having; passing today is not, because
    nothing in the product currently passes ``dependencies=`` to an include and
    a check that missed them would look just as green.

    Nested includes do not double count. A wrapper's ``include_context`` holds
    only what its own include declared; FastAPI combines it with the parent's
    when resolving a request, so accumulating down the recursion here is the
    same sum reached once rather than twice.
    """
    for entry in routes:
        original_router = getattr(entry, "original_router", None)
        if original_router is not None:
            context = getattr(entry, "include_context", None)
            yield from walk_routes(
                original_router.routes,
                prefix + (getattr(context, "prefix", "") or ""),
                inherited + tuple(getattr(context, "dependencies", ()) or ()),
            )
            continue
        path = getattr(entry, "path", None)
        if isinstance(path, str):
            yield prefix + path, entry, inherited


def _openapi_mutating_count(app) -> int:
    """How many non-safe operations the published schema describes.

    The independent second opinion on :func:`walk_routes`. Built from public
    API only, so a future rename of the private attributes cannot take both
    readings down together. It cannot see WebSocket routes, which is why it is
    a cross-check on the HTTP sweep rather than the sweep itself.
    """
    paths = app.openapi().get("paths", {})
    return sum(1 for item in paths.values() for method in item if method.upper() not in SAFE_METHODS)


def _mutating_routes(app) -> list[tuple[str, str, str, bool]]:
    """Every mounted (method, path) that is not a safe method.

    Returns ``(method, template, concrete_path, allowlisted)``. Built by
    walking the live route table, so nothing can be missed by being spelled
    differently in a test than it is in the router.
    """
    out: list[tuple[str, str, str, bool]] = []
    for template, route, _inherited in walk_routes(app.routes):
        methods = getattr(route, "methods", None) or set()
        endpoint = getattr(route, "endpoint", None)
        if not methods or not template:
            continue
        allowlisted = endpoint_key(endpoint) in ALLOWED_ENDPOINTS
        concrete = template
        while "{" in concrete:
            head, _, rest = concrete.partition("{")
            _param, _, tail = rest.partition("}")
            concrete = f"{head}{_ANY_ID}{tail}"
        for method in sorted(methods):
            if method in SAFE_METHODS:
                continue
            out.append((method, template, concrete, allowlisted))
    return out


@pytest.mark.asyncio
@pytest.mark.integration
async def test_demo_read_only_refuses_every_write_and_moves_no_rows(app_client, auth_headers, monkeypatch):
    """Phase A: the whole mutating surface is refused, and the database is still."""
    app, client = app_client
    headers = auth_headers["headers"]
    routes = _mutating_routes(app)

    # The census has to be shown to be a census before anything it reports is
    # worth reading. A sweep that silently collapses to a handful answers 403
    # for every one of them and passes, which is exactly what happened here on
    # the lane that gates while this file was green everywhere else.
    assert len(routes) >= _MUTATING_ROUTE_FLOOR, (
        f"route sweep collapsed to {len(routes)} entries, below the floor of "
        f"{_MUTATING_ROUTE_FLOOR}. The application mounts thousands of mutating "
        f"routes, so this is a broken traversal rather than a smaller product: "
        f"see walk_routes(). What it found was {sorted({t for _m, t, _c, _a in routes})[:10]}"
    )

    # Second opinion, from public API that shares no code path with the walker
    # above. They will not agree exactly - the schema hides the mirror mounts
    # that carry include_in_schema=False, and it cannot see WebSocket routes -
    # so this checks the order of magnitude rather than equality. The failure
    # it exists to catch is one reading collapsing while the other does not.
    from_schema = _openapi_mutating_count(app)
    assert from_schema >= _MUTATING_ROUTE_FLOOR, (
        f"the published schema describes only {from_schema} mutating operations, "
        f"below the floor of {_MUTATING_ROUTE_FLOOR} - the application under test is not the product"
    )
    assert len(routes) >= from_schema, (
        f"the walker found {len(routes)} mutating routes but the schema describes "
        f"{from_schema}. The walker is meant to see at least everything the schema "
        f"does, plus the mirror mounts the schema hides, so it is missing routes"
    )
    print(f"\n[phase A] mutating routes: walker {len(routes)}, openapi {from_schema}")

    _set_flag(monkeypatch, on=True)
    before = await _census()
    assert before, "row census came back empty - the harness is measuring nothing"

    # 1. The curated writes, which phase B proves really do write.
    for method, path, payload in _writes("phase-a"):
        response = await client.request(method, path, headers=headers, json=payload)
        _assert_contract(response, f"{method} {path}")

    # 2. The whole surface, so this cannot be "the endpoints I thought of".
    unexpected: list[str] = []
    swept = 0
    for method, template, concrete, allowlisted in routes:
        if allowlisted:
            continue
        response = await client.request(method, concrete, headers=headers, json={})
        swept += 1
        if response.status_code != 403 or response.json().get("detail", {}).get("error") != DEMO_READ_ONLY_ERROR:
            unexpected.append(f"{method} {template} -> {response.status_code}")

    after = await _census()
    moved = _diff(before, after)
    non_exempt = {t: v for t, v in moved.items() if t not in EXEMPT_TABLES}
    exempt_moved = {t: v for t, v in moved.items() if t in EXEMPT_TABLES}

    print(f"\n[phase A] flag ON, mutating routes swept: {swept} (allowlisted skipped: {len(routes) - swept})")
    print(f"[phase A] tables counted: {len(before)}; total rows before: {_rows(before)}, after: {_rows(after)}")
    print(f"[phase A] declared-exempt tables that moved: {exempt_moved or 'none'}")
    print(f"[phase A] every other table that moved: {non_exempt or 'none'}")

    assert not unexpected, f"{len(unexpected)} routes did not answer the contract: {unexpected[:20]}"
    assert not non_exempt, f"the database moved while the demo was read-only: {non_exempt}"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_writes_still_work_with_the_flag_off(app_client, auth_headers, monkeypatch):
    """Phase B, the negative control: off means off, for everybody."""
    _app, client = app_client
    headers = auth_headers["headers"]

    _set_flag(monkeypatch, on=False)
    before = await _census()

    statuses: list[str] = []
    for method, path, payload in _writes(uuid.uuid4().hex[:6]):
        response = await client.request(method, path, headers=headers, json=payload)
        statuses.append(f"{method} {path} -> {response.status_code}")
        assert 200 <= response.status_code < 300, f"{method} {path} failed with the flag OFF: {response.text[:300]}"

    after = await _census()
    moved = _diff(before, after)
    non_exempt = {t: v for t, v in moved.items() if t not in EXEMPT_TABLES}

    print("\n[phase B] flag OFF, writes attempted:")
    for line in statuses:
        print(f"           {line}")
    print(f"[phase B] total rows before: {_rows(before)}, after: {_rows(after)}")
    print(f"[phase B] tables that moved: {moved}")

    assert non_exempt, (
        "the flag-off control moved nothing outside the exempt tables, so the "
        "flag-on result proves nothing: the harness is not writing"
    )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_reads_and_sign_in_still_work_with_the_flag_on(app_client, auth_headers, monkeypatch):
    """Phase C: the whole point is that a visitor sees everything."""
    _app, client = app_client
    headers = auth_headers["headers"]

    # Sign-in throttles its own ``last_login_at`` UPDATE to once a minute, so a
    # login that follows another one closely never issues it - and the write
    # carve-out that makes sign-in possible would go untested. Age the row so
    # the UPDATE really fires. Done here, with no request in scope and the flag
    # still off, which is the state the seeders and migrations run in.
    from sqlalchemy import update as sa_update

    from app.modules.users.models import User

    async with async_session_factory() as session:
        await session.execute(
            sa_update(User).where(User.email == auth_headers["email"].lower()).values(last_login_at=None)
        )
        await session.commit()

    _set_flag(monkeypatch, on=True)
    before = await _census()

    reads = [
        ("GET", "/api/health", None),
        ("GET", "/api/system/status", None),
        ("GET", "/api/v1/projects/", None),
        ("GET", "/api/v1/users/me/", None),
        ("GET", "/api/v1/costs/", None),
        ("GET", "/api/v1/notifications/", None),
    ]
    for method, path, payload in reads:
        response = await client.request(method, path, headers=headers, json=payload)
        assert response.status_code == 200, f"{method} {path} -> {response.status_code} {response.text[:200]}"

    # Reads that post a body because the query does not fit in a URL. These are
    # the ones a method-only guard would have broken.
    body_reads = [
        ("/api/v1/costs/match/", {"query": "concrete C25/30", "top_k": 5}),
        ("/api/v1/boq/boqs/search-cost-items/", {"query": "concrete", "limit": 5}),
        (
            "/api/v1/boq/boqs/suggest-rate/",
            {"description": "concrete slab 200mm", "unit": "m2"},
        ),
    ]
    for path, payload in body_reads:
        response = await client.post(path, headers=headers, json=payload)
        assert response.status_code != 403, f"POST {path} was refused, but it only reads: {response.text[:200]}"
        assert response.status_code < 500, f"POST {path} -> {response.status_code} {response.text[:200]}"

    # Signing in has to keep working, or the demo is a login page.
    signed_in = await client.post(
        "/api/v1/users/auth/login",
        json={"email": auth_headers["email"], "password": auth_headers["password"]},
    )
    assert signed_in.status_code == 200, f"sign-in refused on the read-only demo: {signed_in.text[:300]}"
    assert signed_in.json().get("access_token")

    # ...and it really did take the write carve-out rather than skipping it.
    async with async_session_factory() as session:
        stamped = (
            await session.execute(
                text("SELECT last_login_at FROM oe_users_user WHERE email = :e"),
                {"e": auth_headers["email"].lower()},
            )
        ).scalar_one()
    assert stamped is not None, "sign-in did not stamp last_login_at, so the carve-out went untested"

    after = await _census()
    moved = _diff(before, after)
    non_exempt = {t: v for t, v in moved.items() if t not in EXEMPT_TABLES}

    exempt_moved = {t: v for t, v in moved.items() if t in EXEMPT_TABLES}
    print("\n[phase C] flag ON, reads + sign-in: all served")
    print(f"[phase C] declared-exempt tables that moved: {exempt_moved or 'none'}")
    print(f"[phase C] every other table that moved: {non_exempt or 'none'}")

    assert not non_exempt, f"a read moved the database while the demo was read-only: {non_exempt}"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_an_edit_to_existing_data_leaves_the_row_byte_for_byte(app_client, auth_headers, monkeypatch):
    """Phase D: the case a row count cannot see.

    The sweep in phase A posts empty bodies, so every request there is refused
    before it could have edited anything, and counts alone would have proved
    the same thing. This is the other shape of a demo write: a real, valid
    edit of a row that already exists. Nothing is created and nothing is
    deleted, so the count is identical either way, and only the digest can
    tell a refusal from a successful rename.
    """
    _app, client = app_client
    headers = auth_headers["headers"]

    _set_flag(monkeypatch, on=False)
    created = await client.post(
        "/api/v1/projects/",
        headers=headers,
        json={"name": f"Demo guard subject {uuid.uuid4().hex[:6]}", "currency": "EUR", "region": "DE"},
    )
    assert created.status_code == 201, created.text[:300]
    project_id = created.json()["id"]

    before = await _census()
    _set_flag(monkeypatch, on=True)

    response = await client.patch(
        f"/api/v1/projects/{project_id}",
        headers=headers,
        json={"name": "Renamed by a visitor", "description": "and described by one too"},
    )
    after = await _census()

    assert response.status_code == 403, f"a rename was not refused: {response.status_code} {response.text[:300]}"
    assert response.json()["detail"]["error"] == DEMO_READ_ONLY_ERROR

    reread = await client.get(f"/api/v1/projects/{project_id}", headers=headers)
    assert reread.status_code == 200
    assert reread.json()["name"] != "Renamed by a visitor"

    moved = {t: v for t, v in _diff(before, after).items() if t not in EXEMPT_TABLES}
    projects = "oe_projects_project"
    print(f"\n[phase D] PATCH /api/v1/projects/{{id}} -> {response.status_code}")
    print(f"[phase D] {projects} before: {before.get(projects)}")
    print(f"[phase D] {projects} after:  {after.get(projects)}")
    print(f"[phase D] tables that moved: {moved or 'none'}")

    assert before.get(projects) == after.get(projects), "the project row changed under a refused edit"
    assert not moved, f"the database moved under a refused edit: {moved}"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_the_guard_cannot_be_talked_out_of_it(app_client, auth_headers, monkeypatch):
    """No header, verb or spelling gets a write through."""
    _app, client = app_client
    headers = dict(auth_headers["headers"])

    _set_flag(monkeypatch, on=True)

    # An anonymous caller gets the refusal, not a 401: the demo says why.
    anonymous = await client.post("/api/v1/projects/", json={"name": "x"})
    _assert_contract(anonymous, "anonymous POST /api/v1/projects/")

    # A method override header is not a way round it.
    overridden = await client.post(
        "/api/v1/projects/",
        headers={**headers, "X-HTTP-Method-Override": "GET"},
        json={"name": "x"},
    )
    _assert_contract(overridden, "method-override POST /api/v1/projects/")

    # The underscore mirror mount of a module is the same endpoint, so one
    # allowlist entry covers both spellings and neither is a back door.
    mirrored = await client.post("/api/v1/bid_management/bidders/", headers=headers, json={})
    _assert_contract(mirrored, "underscore mirror POST /api/v1/bid_management/bidders/")

    # The deployment's own control surface is refused too, not exempted.
    upgrade = await client.post("/api/system/upgrade", headers=headers, json={})
    _assert_contract(upgrade, "POST /api/system/upgrade")


async def _drive_socket(
    app: Any,
    path: str,
    query: str = "",
    frames: tuple[dict[str, Any], ...] = (),
) -> list[dict[str, Any]]:
    """Run one WebSocket connection straight against the ASGI application.

    Deliberately not ``TestClient``: that drives its own event loop on another
    thread, while the asyncpg pool these handlers read through is bound to this
    one. Speaking ASGI directly keeps the connection on the test's loop, needs
    no new dependency, and exercises the real middleware stack, the real
    routing and the real application-level dependencies.

    Nothing is caught here. An exception escaping the application is the
    finding, not something to fold into the returned frames.
    """
    inbox: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
    await inbox.put({"type": "websocket.connect"})
    for frame in frames:
        await inbox.put(frame)
    await inbox.put({"type": "websocket.disconnect", "code": 1000})

    sent: list[dict[str, Any]] = []

    async def receive() -> dict[str, Any]:
        return await inbox.get()

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    scope = {
        "type": "websocket",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "scheme": "ws",
        "server": ("testserver", 80),
        "client": ("testclient", 50000),
        "root_path": "",
        "path": path,
        "raw_path": path.encode(),
        "query_string": query.encode(),
        "headers": [
            (b"host", b"testserver"),
            (b"connection", b"upgrade"),
            (b"upgrade", b"websocket"),
            (b"sec-websocket-version", b"13"),
            (b"sec-websocket-key", b"dGhlIHNhbXBsZSBub25jZQ=="),
        ],
        "subprotocols": [],
        "state": {},
    }
    # A handler that never returns is a failure, not a reason to hang the suite.
    await asyncio.wait_for(app(scope, receive, send), timeout=30.0)
    return sent


@pytest.mark.asyncio
@pytest.mark.integration
async def test_every_mounted_socket_is_wired_to_the_guard(app_client, auth_headers, monkeypatch):
    """Every socket the application mounts is wired to the guard.

    A wiring claim, not a behaviour one, and the split is deliberate. What a
    socket does once it is connected - a stranger refused at the handshake, the
    two real sockets still opening, an allowlisted socket still refused at the
    write - is asserted in ``test_demo_read_only_sockets.py``, against real and
    allowlisted sockets. What is left here is the half that belongs with the
    census above: that the sweep can see every socket at all, and that what it
    sees carries the guard.

    Sockets are the sharper case for the census. They carry no method, so the
    HTTP sweep in phase A skips them by construction, and they are absent from
    the OpenAPI schema, so the cross-check cannot see them either. Whatever is
    asserted about sockets has to be asserted here or nowhere.

    FastAPI fills a ``Request`` parameter only for an HTTP route, so a guard
    annotated ``Request`` is called with the argument missing on a WebSocket
    handshake and every socket in the application dies with a ``TypeError`` -
    with the flag off as much as on, because the failure is in solving the
    dependency rather than in anything the guard decides. ``HTTPConnection`` is
    the common base of both and is filled for either. That is check 1, and it
    is cheap insurance against a one-word annotation change.

    Three checks:

    1. the guard's parameter really binds as a connection rather than a request;
    2. every socket route the real application mounts really does carry the
       guard, on the EFFECTIVE dependency set rather than on what the route
       object happens to store, which is a storage detail that has already
       moved once - see :func:`walk_routes`;
    3. a real socket on the real application still serves with the flag on,
       driven rather than inferred. This one is the negative control for check
       2: a set assembled from private attributes could be complete, correct
       and still describe something that never runs, and a census that cannot
       be wrong about that is not worth having.

    The database tripwire has one documented blind spot that a socket would be
    alone with if it reached it: ``_pg_bulk_insert_cost_rows`` in
    ``app.modules.costs.router`` writes through a raw DBAPI cursor that never
    reaches the listener. Neither socket goes near it today. Worth knowing
    before adding a third.
    """
    from fastapi.dependencies.utils import get_dependant
    from fastapi.routing import APIWebSocketRoute

    # 1. The parameter binds as a connection.
    dependant = get_dependant(path="/", call=demo_read_only_guard)
    assert dependant.http_connection_param_name == "connection"
    assert dependant.request_param_name is None

    app, _client = app_client

    # 2. Every mounted socket carries the guard.
    #
    # Walked rather than read off ``app.routes``, and sockets are the sharper
    # case of that. From FastAPI 0.141 an included router is one opaque wrapper,
    # so ``[r for r in app.routes if isinstance(r, APIWebSocketRoute)]`` returns
    # ZERO on the version CI installs - measured, not inferred. The self-check
    # below would then have fired, which is the honest outcome, but the loop it
    # guards would never have run. FastAPI's own flattening is no help here
    # either: on 0.141.1 it reports every socket route with an empty path.
    #
    # An application-level dependency reaches these three different ways on
    # different releases, so the check is on the EFFECTIVE set: what the route
    # holds itself, plus what it inherits from the routers it is mounted
    # through, plus the application's own. Asserting on route.dependencies
    # alone reports "does not carry the guard" for every real socket on 0.141
    # while the guard is in fact running on all of them, which is a false
    # alarm on the exact claim this file exists to defend.
    app_level = tuple(app.router.dependencies)
    socket_routes = [
        (path, r, tuple(r.dependencies) + inherited + app_level)
        for path, r, inherited in walk_routes(app.routes)
        if isinstance(r, APIWebSocketRoute)
    ]
    assert socket_routes, "no socket routes found, so this test would prove nothing"
    paths = sorted(path for path, _r, _d in socket_routes)
    # The set, not a floor and not a sample. "Every socket I found carries the
    # guard" is a claim about the sweep as much as about the guard, and it
    # passes just as well on a sweep that found two of three as on one that
    # found all of them. Comparing against the declared set is what makes a
    # shrinking census a failure rather than a quieter pass. Both directions
    # are reported because they mean opposite things: a socket that vanished
    # from the sweep is a census defect, and one that appeared is a socket
    # nobody has decided about yet.
    found = set(paths)
    assert found == set(_EXPECTED_SOCKET_PATHS), (
        f"the socket census does not match what this file declares. "
        f"missing from the sweep: {sorted(set(_EXPECTED_SOCKET_PATHS) - found)}; "
        f"not declared here: {sorted(found - set(_EXPECTED_SOCKET_PATHS))}"
    )
    for path, _route, effective in socket_routes:
        names = [d.dependency for d in effective]
        assert demo_read_only_guard in names, f"{path} does not carry the guard"

    token = auth_headers["headers"]["Authorization"].split()[1]

    _set_flag(monkeypatch, on=True)

    # 3. A real socket still serves with the flag on.
    served = await _drive_socket(
        app,
        next(p for p in paths if p.endswith("/notifications/ws/")),
        f"token={token}",
        ({"type": "websocket.receive", "text": "ping"},),
    )
    kinds = [m["type"] for m in served]
    assert "websocket.accept" in kinds, f"the notifications socket was not accepted: {served}"
    payloads = [m.get("text", "") for m in served if m["type"] == "websocket.send"]
    assert any("notifications.hello" in p for p in payloads), f"no hello frame: {payloads}"
    assert any("pong" in p for p in payloads), f"the socket did not answer a ping: {payloads}"

    print(f"\n[sockets] guard attached to {len(socket_routes)} socket routes: {paths}")
    print("[sockets] a real socket still serves with the flag on, so the wiring above is not just a set")


@pytest.mark.asyncio
@pytest.mark.integration
async def test_the_database_tripwire_refuses_a_write_layer_one_let_through(monkeypatch):
    """Layer 2 on its own: a write from an allowlisted route is still refused."""
    from app.core import demo_read_only as dro

    _set_flag(monkeypatch, on=True)
    token = dro._set_write_scope(dro.WriteScope.NONE)
    try:
        async with async_session_factory() as session:
            with pytest.raises(Exception) as caught:  # noqa: PT011 - driver may wrap it
                await session.execute(
                    text("INSERT INTO oe_projects_project (id, name) VALUES (:i, 'x')"),
                    {"i": str(uuid.uuid4())},
                )
            chain: list[Any] = []
            exc: BaseException | None = caught.value
            while exc is not None and len(chain) < 10:
                chain.append(exc)
                exc = exc.__cause__ or exc.__context__
            assert any(isinstance(e, dro.DemoReadOnlyError) for e in chain), (
                f"the tripwire did not fire; got {caught.value!r}"
            )
            await session.rollback()

        # A read on the same scope is untouched.
        async with async_session_factory() as session:
            assert (await session.execute(text("SELECT 1"))).scalar_one() == 1
    finally:
        dro._reset_write_scope(token)
        _set_flag(monkeypatch, on=False)


@pytest.mark.parametrize(
    ("statement", "expected"),
    [
        ("SELECT 1", None),
        ("  \n-- a comment\nSELECT * FROM oe_projects_project", None),
        ("SELECT * FROM t FOR UPDATE", None),
        ("SET LOCAL app.current_tenant = 'x'", None),
        ("BEGIN", None),
        ("SAVEPOINT sa_1", None),
        ("COPY (SELECT 1) TO STDOUT", None),
        ("CREATE TEMP TABLE scratch (a int)", None),
        ('INSERT INTO "oe_activity_log" (a) VALUES (1)', ("INSERT", "oe_activity_log")),
        ("update oe_users_user set last_login_at = now()", ("UPDATE", "oe_users_user")),
        ("DELETE FROM public.oe_projects_project WHERE id = 1", ("DELETE", "oe_projects_project")),
        ("TRUNCATE TABLE oe_projects_project", ("TRUNCATE", "oe_projects_project")),
        ("COPY oe_projects_project FROM STDIN", ("COPY", None)),
        ("ALTER TABLE oe_projects_project ADD COLUMN x int", ("ALTER", None)),
    ],
)
def test_statement_classifier(statement, expected):
    """The tripwire's own reading of a statement, both polarities."""
    from app.core.demo_read_only import classify_statement

    assert classify_statement(statement) == expected


@pytest.mark.parametrize(
    ("scope_name", "kind", "table", "permitted"),
    [
        # Sign-in mints a session row alongside the tokens that name it, and
        # refreshing pushes that row's horizon out. Both have to be writable
        # or signing in is refused outright: the mint raises rather than
        # falling back to a session nobody could revoke.
        ("AUTHENTICATION", "INSERT", "oe_users_session", True),
        ("AUTHENTICATION", "UPDATE", "oe_users_session", True),
        # And no further. Removing a session is pruning, which is a background
        # job with no request in scope, so it never asks this question and
        # does not need an answer of yes.
        ("AUTHENTICATION", "DELETE", "oe_users_session", False),
        # The account row keeps the narrower permission it was given: a
        # sign-in stamps last_login_at, and an INSERT here is account
        # creation, which is the thing a read-only demo exists to refuse.
        ("AUTHENTICATION", "UPDATE", "oe_users_user", True),
        ("AUTHENTICATION", "INSERT", "oe_users_user", False),
        # Scope still decides. Every route that is not sign-in holds NONE, and
        # none of the above is writable from there.
        ("NONE", "INSERT", "oe_users_session", False),
        ("NONE", "UPDATE", "oe_users_user", False),
        # The audit trail is writable from either scope, being the trace of a
        # visit rather than anything a visitor chose to change.
        ("NONE", "INSERT", "oe_activity_log", True),
        # Demo content, from the scope that gets closest to writing it.
        ("AUTHENTICATION", "INSERT", "oe_projects_project", False),
    ],
)
def test_what_a_signed_in_visitor_may_write(scope_name, kind, table, permitted):
    """The permission matrix layer 2 enforces, stated per table and per kind.

    Worth pinning separately from the end to end proof above, because the two
    fail differently. The end to end test says sign-in was refused; this one
    says which statement on which table was the reason, which is the thing a
    reader needs when a later feature adds a write to the sign-in path.
    """
    from app.core.demo_read_only import WriteScope, _permitted

    assert _permitted(WriteScope[scope_name], kind, table) is permitted
