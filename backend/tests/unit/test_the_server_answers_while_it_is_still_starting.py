"""The port opens at once; the API opens when startup has finished.

A fresh install spends minutes building the schema and loading the modules.
Until it is done the gate answers every API call except the health probe with a
503 that names the phase, static files pass, and health itself says
``starting``. Inline startup (the test suite, ``OE_BOOT_INLINE``) never gates.
"""

from __future__ import annotations

import asyncio

import pytest
from starlette.applications import Starlette
from starlette.responses import JSONResponse, PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from app.core.boot_state import (
    BOOT_PHASES,
    BootGateMiddleware,
    BootState,
    boot_in_background,
    is_gated_path,
    yield_to_requests,
)
from app.core.heavy_work import current_holder, heavy_slot


def _client(state: BootState) -> TestClient:
    async def api(_request):
        return JSONResponse({"ok": True})

    async def page(_request):
        return PlainTextResponse("<!doctype html>")

    app = Starlette(
        routes=[
            Route("/api/v1/projects/", api),
            Route("/api/health", api),
            Route("/", page),
            Route("/assets/app.js", page),
        ]
    )
    app.add_middleware(BootGateMiddleware, state=state)
    return TestClient(app)


def test_while_starting_the_api_answers_503_naming_the_phase() -> None:
    state = BootState()
    state.begin_background()
    state.set_phase("Modules")
    resp = _client(state).get("/api/v1/projects/")
    assert resp.status_code == 503
    assert resp.headers["retry-after"] == "3"
    body = resp.json()
    assert body["code"] == "server_starting"
    assert body["boot"]["phase"] == "Modules"
    assert body["boot"]["step"] == BOOT_PHASES.index("Modules") + 1
    assert body["boot"]["steps"] == len(BOOT_PHASES)
    assert body["boot"]["status"] == "starting"


def test_while_starting_health_and_static_files_pass() -> None:
    state = BootState()
    state.begin_background()
    client = _client(state)
    assert client.get("/api/health").status_code == 200
    assert client.get("/").status_code == 200
    assert client.get("/assets/app.js").status_code == 200


def test_once_ready_the_api_is_open() -> None:
    state = BootState()
    state.begin_background()
    state.mark_ready()
    assert _client(state).get("/api/v1/projects/").json() == {"ok": True}


def test_a_failed_start_keeps_the_api_closed_and_says_so() -> None:
    state = BootState()
    state.begin_background()
    state.mark_failed()
    body = _client(state).get("/api/v1/projects/").json()
    assert body["code"] == "server_start_failed"
    assert body["boot"]["status"] == "failed"


def test_inline_startup_never_gates() -> None:
    # A fresh state that never began a background boot: tests that skip the
    # lifespan entirely must reach the API as before.
    state = BootState()
    assert state.api_open
    assert _client(state).get("/api/v1/projects/").status_code == 200


def test_unknown_phase_reports_its_name_without_a_step() -> None:
    state = BootState()
    state.set_phase("Schema repair")
    snap = state.snapshot()
    assert snap["phase"] == "Schema repair"
    assert snap["step"] == 0


@pytest.mark.parametrize(
    ("path", "gated"),
    [
        ("/api/health", False),
        ("/api/v1/auth/login", True),
        ("/api", True),
        ("/apiary", False),
        ("/", False),
        ("/projects", False),
    ],
)
def test_gated_paths(path: str, gated: bool) -> None:
    assert is_gated_path(path) is gated


@pytest.mark.parametrize(
    ("env", "background"),
    [
        ({}, True),
        ({"OE_TEST_FAST_STARTUP": "1"}, False),
        ({"OE_BOOT_INLINE": "true"}, False),
        ({"OE_BOOT_INLINE": "0"}, True),
    ],
)
def test_boot_mode_follows_the_environment(env: dict[str, str], background: bool) -> None:
    assert boot_in_background(env) is background


def test_heavy_loads_run_one_at_a_time() -> None:
    order: list[str] = []

    async def load(name: str, hold: float) -> None:
        async with heavy_slot(name):
            order.append(f"{name}:start")
            assert current_holder() == name
            await asyncio.sleep(hold)
            order.append(f"{name}:end")

    async def main() -> None:
        await asyncio.gather(load("demo data seed", 0.05), load("cost database DE_BERLIN", 0.0))

    asyncio.run(main())
    assert order == [
        "demo data seed:start",
        "demo data seed:end",
        "cost database DE_BERLIN:start",
        "cost database DE_BERLIN:end",
    ]
    assert current_holder() is None


def test_the_real_health_probe_says_starting_until_the_api_opens() -> None:
    from app.core.boot_state import boot_state
    from app.main import create_app

    app = create_app()
    client = TestClient(app)  # no lifespan: the boot is driven by hand below
    try:
        boot_state.begin_background()
        boot_state.set_phase("Database")
        resp = client.get("/api/health")
        assert resp.status_code == 503
        body = resp.json()
        assert body["status"] == "starting"
        assert body["boot"]["phase"] == "Database"
        assert "version" in body
        assert client.get("/api/v1/projects/").json()["code"] == "server_starting"

        boot_state.mark_ready()
        assert client.get("/api/health").status_code == 200
    finally:
        boot_state.reset()


def test_blocking_import_steps_yield_only_behind_an_open_port(monkeypatch) -> None:
    slept: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        slept.append(seconds)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    inline = BootState()
    asyncio.run(yield_to_requests(inline))
    assert slept == []

    behind = BootState()
    behind.begin_background()
    asyncio.run(yield_to_requests(behind))
    assert len(slept) == 1
