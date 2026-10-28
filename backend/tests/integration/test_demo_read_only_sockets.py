# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠A read-only demo refuses a WebSocket handshake it did not allowlist.

Separate from ``test_demo_read_only.py`` because it asserts a different thing.
That file proves the guarantee over the HTTP surface with a row census; this
one covers the half a census cannot see, where the refusal is a close code
rather than a status code and nothing is written either way.

Why the refusal exists at all. A socket carries no method, so layer 1 has
nothing to key a safe-versus-unsafe decision on, and before this it let every
handshake through and left sockets resting on the database tripwire alone. That
tripwire has one documented blind spot, the raw-cursor ``COPY`` in
``app.modules.costs.router``, and for an HTTP route layer 1 is what covers it.
Refusing an un-allowlisted handshake is the socket's layer 1, so a socket added
later is refused until somebody reads it and adds it deliberately.

Both polarities, on one application, because either half alone proves nothing:
an allowlisted socket must still open with the flag ON, or the guard has simply
broken the demo's realtime features, and an un-allowlisted one must be refused
with the flag ON and open with it OFF, or the refusal is not the guard.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import pytest
import pytest_asyncio
from fastapi import APIRouter, WebSocket

from app.config import get_settings
from app.core.demo_read_only import (
    _AUTHENTICATION_ENDPOINTS,
    _READ_ONLY_ENDPOINTS,
    _READ_ONLY_SOCKET_ENDPOINTS,
    ALLOWED_ENDPOINTS,
    DEMO_READ_ONLY_ERROR,
    WriteScope,
    endpoint_key,
)
from app.main import create_app

#: A socket nobody allowlisted, mounted the way the real ones are - through
#: ``include_router`` rather than ``@app.websocket`` - because that is the only
#: shape the product actually uses and the two are not equivalent.
_STRANGER_PREFIX = "/api/v1/demo_stranger_socket"


async def stranger_socket(websocket: WebSocket) -> None:
    """A socket that is not in the allowlist. Defined at module level so its
    annotation resolves: this file uses postponed annotations and FastAPI reads
    an endpoint's types out of its ``__globals__``."""
    await websocket.accept()
    await websocket.send_text("stranger opened")
    await websocket.close()


#: Where the writing socket below reports what happened to it.
_WROTE: dict[str, Any] = {}


async def writing_socket(websocket: WebSocket) -> None:
    """A socket that reaches the database, to show layer 2 under an allowed one."""
    from sqlalchemy import text

    from app.core import demo_read_only as dro
    from app.database import async_session_factory

    _WROTE.clear()
    _WROTE["scope"] = dro._write_scope.get()
    await websocket.accept()
    try:
        async with async_session_factory() as session:
            # A real row-moving UPDATE that damages nothing: PostgreSQL writes a
            # new tuple version and the value is unchanged.
            result = await session.execute(text("UPDATE alembic_version SET version_num = version_num"))
            await session.commit()
        _WROTE["outcome"] = "wrote"
        _WROTE["rowcount"] = result.rowcount
    except Exception as exc:  # noqa: BLE001 - the refusal is the measurement
        chain: list[str] = []
        current: BaseException | None = exc
        while current is not None and len(chain) < 10:
            chain.append(type(current).__name__)
            current = current.__cause__ or current.__context__
        _WROTE["outcome"] = "refused"
        _WROTE["chain"] = chain
    await websocket.close()


@pytest.fixture(autouse=True)
def _leave_the_flag_off_afterwards():
    """No test here may leave a read-only deployment behind it."""
    yield
    import os

    os.environ.pop("OE_DEMO_READ_ONLY", None)
    get_settings.cache_clear()
    assert get_settings().demo_read_only is False


def _set_flag(monkeypatch: pytest.MonkeyPatch, *, on: bool) -> None:
    monkeypatch.setenv("OE_DEMO_READ_ONLY", "true" if on else "false")
    get_settings.cache_clear()
    assert get_settings().demo_read_only is on


@pytest_asyncio.fixture(scope="module")
async def app_and_token():
    app = create_app()
    router = APIRouter()
    router.websocket("/ws/")(stranger_socket)
    router.websocket("/writes/")(writing_socket)
    app.include_router(router, prefix=_STRANGER_PREFIX)

    async with app.router.lifespan_context(app):
        from httpx import ASGITransport, AsyncClient
        from sqlalchemy import update as sa_update

        from app.database import async_session_factory
        from app.modules.users.models import User

        get_settings.cache_clear()
        unique = uuid.uuid4().hex[:8]
        email, password = f"dros-{unique}@demo-guard.io", f"DroSock{unique}9!"
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test", timeout=60.0) as client:
            registered = await client.post(
                "/api/v1/users/auth/register",
                json={"email": email, "password": password, "full_name": "Socket Probe"},
            )
            assert registered.status_code == 201, registered.text
            async with async_session_factory() as session:
                await session.execute(
                    sa_update(User).where(User.email == email.lower()).values(role="admin", is_active=True)
                )
                await session.commit()
            signed_in = await client.post("/api/v1/users/auth/login", json={"email": email, "password": password})
            assert signed_in.status_code == 200, signed_in.text
            yield app, signed_in.json()["access_token"]


async def _handshake(app, path: str, query: str = "") -> list[dict[str, Any]]:
    """Drive one handshake straight against the ASGI app and return its frames.

    Speaks ASGI rather than using ``TestClient`` so the connection stays on the
    test's own event loop, which is where the asyncpg pool these handlers read
    through is bound. Nothing is caught: an exception escaping the application
    is a finding, not a frame.
    """
    inbox: asyncio.Queue = asyncio.Queue()
    await inbox.put({"type": "websocket.connect"})
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
        "headers": [(b"host", b"testserver"), (b"sec-websocket-version", b"13")],
        "subprotocols": [],
        "state": {},
    }
    await asyncio.wait_for(app(scope, receive, send), timeout=30.0)
    return sent


def _closed_with(frames: list[dict[str, Any]]) -> tuple[int | None, str | None]:
    for frame in frames:
        if frame.get("type") == "websocket.close":
            return frame.get("code"), frame.get("reason")
    return None, None


@pytest.mark.asyncio
@pytest.mark.integration
async def test_the_allowlist_names_endpoints_that_exist(app_and_token):
    """An allowlist entry that matches nothing refuses the route it was written to keep open.

    The entries are strings, so a rename in any router leaves one pointing at
    nothing. The allowlist is default-deny, so an entry that resolves to
    nothing is not an entry that does nothing: the route it named goes back to
    being refused on the demo, and only on the demo.

    This is the one test in this file that is not about sockets, and that is
    deliberate. ``ALLOWED_ENDPOINTS`` is built from three lists, this check
    used to read one of them, and a check whose population is a third of the
    thing it is named after is the defect it exists to prevent. The population
    here is the merged dict, so a fourth list added later is covered the day it
    is merged rather than the day somebody remembers this file.

    The HTTP entries fail differently from the socket ones and both directions
    are bad. A stale socket entry is silent - a refused handshake reaches the
    browser as a close code our own clients do not render. A stale HTTP entry
    does produce a 403 with a body, but nothing in CI ever asks for those paths
    with the flag on, so it is just as unobserved and it lands on the demo,
    which is the one deployment strangers judge the product by.
    """
    from fastapi.routing import APIRoute, APIWebSocketRoute

    app, _token = app_and_token

    def walk(routes, prefix=""):
        for entry in routes:
            original_router = getattr(entry, "original_router", None)
            if original_router is not None:
                context = getattr(entry, "include_context", None)
                yield from walk(original_router.routes, prefix + (getattr(context, "prefix", "") or ""))
                continue
            path = getattr(entry, "path", None)
            if isinstance(path, str):
                yield prefix + path, entry

    mounted: dict[str, str] = {}
    sockets: set[str] = set()
    for path, route in walk(app.routes):
        if not isinstance(route, (APIRoute, APIWebSocketRoute)):
            continue
        key = endpoint_key(route.endpoint)
        if key is None:
            continue
        mounted.setdefault(key, path)
        if isinstance(route, APIWebSocketRoute):
            sockets.add(key)

    # Two vacuity guards rather than one, because the two halves are found by
    # different branches of the same walk and either can collapse alone.
    assert sockets, "no socket routes found, so the socket half of this test would prove nothing"
    assert len(mounted) - len(sockets) > 100, (
        f"the walk found {len(mounted) - len(sockets)} HTTP endpoints, which is far below what this "
        "product mounts. The traversal is broken, not the allowlist, and every assertion below it "
        "would pass by finding nothing."
    )

    unresolved = sorted(entry for entry in ALLOWED_ENDPOINTS if entry not in mounted)
    assert not unresolved, (
        f"{len(unresolved)} of {len(ALLOWED_ENDPOINTS)} allowlist entries name nothing that is "
        f"mounted: {unresolved}. Each one was written to keep a route usable on the read-only "
        "demo and now keeps nothing, so that route is refused there and answers normally "
        "everywhere else, which is why no other test sees it."
    )

    # The merge in demo_read_only.py is three dict.fromkeys calls into one
    # dict, so a key named in two lists takes the scope of the last list
    # silently. Login in both would come out as NONE and stop working on the
    # demo, which is the one route whose failure locks a visitor out entirely.
    named_twice = sorted(
        {e for e in _AUTHENTICATION_ENDPOINTS if e in set(_READ_ONLY_ENDPOINTS) | set(_READ_ONLY_SOCKET_ENDPOINTS)}
        | (set(_READ_ONLY_ENDPOINTS) & set(_READ_ONLY_SOCKET_ENDPOINTS))
    )
    assert not named_twice, (
        f"{named_twice} appear in more than one allowlist source, and the merge keeps only the "
        "scope of the last one. An authentication endpoint demoted to NONE this way is refused "
        "on the demo with no sign anywhere that a scope was overwritten."
    )
    for entry in _AUTHENTICATION_ENDPOINTS:
        assert ALLOWED_ENDPOINTS[entry] is WriteScope.AUTHENTICATION, (
            f"{entry} is listed as an authentication endpoint and merged as "
            f"{ALLOWED_ENDPOINTS[entry]}, so it cannot write the rows a sign-in needs."
        )

    for entry in _READ_ONLY_SOCKET_ENDPOINTS:
        assert entry in sockets, (
            f"allowlisted socket {entry} resolves to an HTTP route rather than a socket; "
            f"mounted sockets are {sorted(sockets)}"
        )
        assert ALLOWED_ENDPOINTS[entry] is WriteScope.NONE

    print(
        f"\n[allowlist] {len(ALLOWED_ENDPOINTS)} entries all resolve "
        f"({len(_AUTHENTICATION_ENDPOINTS)} authentication, {len(_READ_ONLY_ENDPOINTS)} read-only HTTP, "
        f"{len(_READ_ONLY_SOCKET_ENDPOINTS)} socket) against {len(mounted)} mounted endpoints, "
        f"{len(sockets)} of them sockets"
    )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_an_unlisted_socket_is_refused_only_while_the_demo_is_read_only(app_and_token, monkeypatch):
    """Both polarities on the same socket, which is what makes either mean anything."""
    app, _token = app_and_token
    path = f"{_STRANGER_PREFIX}/ws/"

    # Flag OFF: it opens. Without this the refusal below would also pass
    # against a socket that was broken, mis-mounted or 404.
    _set_flag(monkeypatch, on=False)
    opened = await _handshake(app, path)
    kinds = [f["type"] for f in opened]
    assert "websocket.accept" in kinds, f"the unlisted socket does not work with the flag OFF: {opened}"
    assert any(f.get("text") == "stranger opened" for f in opened), opened

    # Flag ON: refused at the handshake, before the handler runs.
    _set_flag(monkeypatch, on=True)
    refused = await _handshake(app, path)
    code, reason = _closed_with(refused)
    assert "websocket.accept" not in [f["type"] for f in refused], (
        f"an unlisted socket was accepted on a read-only demo: {refused}"
    )
    assert code == 1008, f"expected a 1008 policy close, got {code}: {refused}"
    assert reason == DEMO_READ_ONLY_ERROR, f"close reason was {reason!r}, not the contract key"
    assert not any(f.get("text") == "stranger opened" for f in refused), (
        "the handler ran despite the refusal, so the refusal is not before the handler"
    )

    print(f"\n[stranger] flag OFF -> accepted; flag ON -> close {code} {reason!r}")


@pytest.mark.asyncio
@pytest.mark.integration
async def test_the_two_real_sockets_still_open_on_a_read_only_demo(app_and_token, monkeypatch):
    """The point of the allowlist: reading is allowed, so these must still work.

    A guard that closed every handshake would pass the test above and quietly
    break both realtime features on the demo, and nothing else in this suite
    would notice, because a refused socket has no status code to assert on.
    """
    app, token = app_and_token

    _set_flag(monkeypatch, on=True)

    notifications = await _handshake(app, "/api/v1/notifications/ws/", f"token={token}")
    kinds = [f["type"] for f in notifications]
    assert "websocket.accept" in kinds, f"the notifications socket was refused on the demo: {notifications}"
    assert any("notifications.hello" in (f.get("text") or "") for f in notifications), notifications

    # Both spellings of the mirrored mount, because one allowlist entry is
    # meant to cover both and a path-keyed guard would only cover one.
    for path in ("/api/v1/collaboration-locks/presence/", "/api/v1/collaboration_locks/presence/"):
        frames = await _handshake(app, path, f"entity_type=project&entity_id={uuid.uuid4()}&token={token}")
        code, reason = _closed_with(frames)
        # A bad entity closes 1008 too, so assert on the REASON: the guard's
        # refusal carries the contract key and the router's does not.
        assert reason != DEMO_READ_ONLY_ERROR, f"{path} was refused by the demo guard: {frames}"

    print("\n[real sockets] notifications opened; both presence spellings passed the guard")


@pytest.mark.asyncio
@pytest.mark.integration
async def test_layer_two_still_refuses_a_write_from_an_ALLOWLISTED_socket(app_and_token, monkeypatch):
    """Allowlisting a socket is cheap, because layer 2 is still underneath it.

    This is the claim that makes the allowlist safe to extend. Getting past the
    handshake is not permission to write: the guard binds ``WriteScope.NONE``
    for the life of the connection, and the database tripwire refuses any
    row-moving statement issued under it.

    The socket is allowlisted here through ``monkeypatch.setitem`` rather than
    by adding a test-only entry to the shipped list, because that list is read
    by operators as the set of things a visitor can reach.

    Both polarities, and the flag-off half is the load-bearing one: an UPDATE
    that could never succeed would produce the same "refused" as a working
    guard. An earlier draft of exactly this check used an INSERT that failed on
    a missing NOT NULL column in both directions and looked perfect.
    """
    from app.core.demo_read_only import ALLOWED_ENDPOINTS as LIVE
    from app.core.demo_read_only import DemoReadOnlyError, WriteScope

    app, _token = app_and_token
    path = f"{_STRANGER_PREFIX}/writes/"
    monkeypatch.setitem(LIVE, endpoint_key(writing_socket), WriteScope.NONE)

    _set_flag(monkeypatch, on=True)
    frames = await _handshake(app, path)
    assert "websocket.accept" in [f["type"] for f in frames], (
        f"the allowlisted socket was refused at the handshake: {frames}"
    )
    assert _WROTE.get("scope") is WriteScope.NONE, (
        f"the guard did not arm layer 2 for the connection: scope was {_WROTE.get('scope')!r}"
    )
    assert _WROTE.get("outcome") == "refused", f"an allowlisted websocket wrote to the database: {_WROTE}"
    assert DemoReadOnlyError.__name__ in _WROTE.get("chain", []), (
        f"the write failed, but not because of the guard: {_WROTE}"
    )

    _set_flag(monkeypatch, on=False)
    await _handshake(app, path)
    assert _WROTE.get("outcome") == "wrote", (
        f"the same write failed with the flag OFF, so the refusal above proves nothing: {_WROTE}"
    )
    assert _WROTE.get("rowcount", 0) >= 1, f"the control wrote no rows: {_WROTE}"

    print("\n[layer 2] an allowlisted socket still cannot write: refused ON, wrote OFF")
