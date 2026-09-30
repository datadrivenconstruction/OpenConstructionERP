# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Route-level tests for the rebar schedule API.

The module's other tests all exercise the ABS codec and the service, so a
router that never reached the database was invisible to them: every
project-scoped endpoint called ``verify_project_access(project_id, session,
user_id)`` while the helper's signature is ``(project_id, user_id, session)``.
The repository then received a string where it expects a session and raised
``AttributeError`` before any access decision was made, so all seven
project-scoped endpoints answered 500.

These tests drive the real ASGI app against the real database, which is the
only level at which the argument order is observable.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

_PREFIX = "/api/v1/rebar-schedule"


# ── App fixture ───────────────────────────────────────────────────────────


@pytest_asyncio.fixture(scope="module")
async def app_factory():
    from app.config import get_settings

    get_settings.cache_clear()
    from app.main import create_app

    app = create_app()
    async with app.router.lifespan_context(app):
        from app.database import Base, engine

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        yield app


@pytest_asyncio.fixture
async def db_session() -> AsyncIterator:
    from app.database import async_session_factory

    async with async_session_factory() as session:
        yield session


# ── Helpers ───────────────────────────────────────────────────────────────


async def _seed_user_and_project(session) -> tuple[uuid.UUID, uuid.UUID]:
    """Insert a minimal user plus a project they own."""
    from app.modules.projects.models import Project
    from app.modules.users.models import User

    user = User(
        email=f"rebar-routes-{uuid.uuid4().hex[:8]}@test.io",
        hashed_password="x",
        full_name="Rebar Route Tester",
        role="editor",
    )
    session.add(user)
    await session.flush()
    project = Project(name="Rebar Route Project", owner_id=user.id)
    session.add(project)
    await session.commit()
    await session.refresh(project)
    return user.id, project.id


async def _seed_import(session, project_id: uuid.UUID) -> uuid.UUID:
    """Persist one stored ABS import so the by-id routes have something to find."""
    from app.modules.rebar_schedule.models import RebarScheduleImport

    record = RebarScheduleImport(
        project_id=project_id,
        filename="schedule.abs",
        content_sha256=uuid.uuid4().hex + uuid.uuid4().hex,
        record_count=0,
        validation_status="passed",
    )
    session.add(record)
    await session.commit()
    await session.refresh(record)
    return record.id


def _override_payload(app, user_id: uuid.UUID, *, perms: list[str]) -> None:
    """Authenticate as a non-admin, so neither permission nor project access is bypassed."""
    from app.dependencies import get_current_user_payload

    async def _payload() -> dict:
        return {"sub": str(user_id), "role": "editor", "permissions": list(perms)}

    app.dependency_overrides[get_current_user_payload] = _payload


# ── Tests ─────────────────────────────────────────────────────────────────


async def test_the_router_is_mounted(app_factory) -> None:
    """Guard for the tests below: a 404 from an unmounted router proves nothing.

    Read off the OpenAPI document rather than ``app.routes``: the module
    loader adds each module through a lazy ``_IncludedRouter`` entry, so
    walking the route objects finds nothing even when the module is mounted.
    """
    paths = app_factory.openapi()["paths"]
    assert f"{_PREFIX}/imports/" in paths
    assert f"{_PREFIX}/imports/{{import_id}}/cutting" in paths


async def test_listing_a_projects_imports_reaches_the_project_access_check(
    app_factory,
    db_session,
) -> None:
    """``project_id`` comes off the query string here (router.py list_imports)."""
    user_id, project_id = await _seed_user_and_project(db_session)
    _override_payload(app_factory, user_id, perms=["rebar_schedule.read"])
    try:
        transport = ASGITransport(app=app_factory)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get(f"{_PREFIX}/imports/", params={"project_id": str(project_id)})
    finally:
        app_factory.dependency_overrides.clear()

    assert response.status_code == 200, response.text
    assert response.json()["items"] == []


async def test_a_foreign_project_is_refused_rather_than_erroring(
    app_factory,
    db_session,
) -> None:
    """The access decision has to be reached, not skipped: another owner's project is a 404."""
    user_id, _ = await _seed_user_and_project(db_session)
    _, other_project_id = await _seed_user_and_project(db_session)
    _override_payload(app_factory, user_id, perms=["rebar_schedule.read"])
    try:
        transport = ASGITransport(app=app_factory)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get(f"{_PREFIX}/imports/", params={"project_id": str(other_project_id)})
    finally:
        app_factory.dependency_overrides.clear()

    assert response.status_code == 404, response.text


async def test_fetching_one_import_reaches_the_project_access_check(
    app_factory,
    db_session,
) -> None:
    """``project_id`` comes off the loaded record here (router.py get_import)."""
    user_id, project_id = await _seed_user_and_project(db_session)
    import_id = await _seed_import(db_session, project_id)
    _override_payload(app_factory, user_id, perms=["rebar_schedule.read"])
    try:
        transport = ASGITransport(app=app_factory)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get(f"{_PREFIX}/imports/{import_id}")
    finally:
        app_factory.dependency_overrides.clear()

    assert response.status_code == 200, response.text
    assert response.json()["filename"] == "schedule.abs"


async def test_the_cutting_summary_reaches_the_project_access_check(
    app_factory,
    db_session,
) -> None:
    """A third call site (router.py cutting_summary), on an import with no shapes."""
    user_id, project_id = await _seed_user_and_project(db_session)
    import_id = await _seed_import(db_session, project_id)
    _override_payload(app_factory, user_id, perms=["rebar_schedule.read"])
    try:
        transport = ASGITransport(app=app_factory)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get(f"{_PREFIX}/imports/{import_id}/cutting")
    finally:
        app_factory.dependency_overrides.clear()

    assert response.status_code == 200, response.text
    assert response.json() == []


def test_every_call_site_passes_the_helpers_arguments_in_order() -> None:
    """The seven call sites are positional, so only the order keeps them correct.

    A route test can only cover the routes it drives; this reads the module's
    source so a new endpoint copying the old order is caught too.
    """
    import ast
    import inspect

    from app.dependencies import verify_project_access
    from app.modules.rebar_schedule import router as router_module

    expected = list(inspect.signature(verify_project_access).parameters)
    assert expected == ["project_id", "user_id", "session"]

    tree = ast.parse(inspect.getsource(router_module))
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "verify_project_access"
    ]
    assert len(calls) == 7, f"expected 7 call sites, found {len(calls)}"

    for call in calls:
        assert not call.keywords, f"line {call.lineno}: call is keyword-based, update this test"
        assert len(call.args) == 3, f"line {call.lineno}: expected 3 positional arguments"
        second, third = call.args[1], call.args[2]
        assert isinstance(second, ast.Name) and second.id == "user_id", (
            f"line {call.lineno}: second argument must be user_id, not {ast.unparse(second)}"
        )
        assert isinstance(third, ast.Name) and third.id == "session", (
            f"line {call.lineno}: third argument must be session, not {ast.unparse(third)}"
        )


async def test_the_upload_preview_decodes_like_an_import(app_factory, db_session) -> None:
    """``POST /preview/file/`` takes the import's multipart part and its decoder."""
    from app.modules.rebar_schedule.abs_format import compute_checksum
    from tests.modules.rebar_schedule import abs_fixtures

    base = abs_fixtures.RECORDS["bar-with-one-bend"]
    record = base.replace("@r312@", "@rBügel@")
    prefix = record[: record.rindex("@C") + 2]
    data = (prefix + str(compute_checksum(prefix)) + "@\r\n").encode("cp1252")

    user_id, _ = await _seed_user_and_project(db_session)
    _override_payload(app_factory, user_id, perms=["rebar_schedule.read"])
    try:
        transport = ASGITransport(app=app_factory)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                f"{_PREFIX}/preview/file/",
                files={"upload": ("buegel.abs", data, "application/octet-stream")},
            )
            empty = await client.post(
                f"{_PREFIX}/preview/file/",
                files={"upload": ("empty.abs", b"  \r\n", "application/octet-stream")},
            )
    finally:
        app_factory.dependency_overrides.clear()

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["encoding"] == "cp1252"
    assert body["shapes"][0]["checksum_ok"] is True
    assert body["shapes"][0]["drawing_ref"] == "Bügel"
    assert empty.status_code == 422
