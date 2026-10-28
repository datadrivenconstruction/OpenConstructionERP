# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Security regression tests for the Clash Detection export + comment paths.

Covers two output-/input-integrity gaps closed in the Wave-2 security pass:

* CSV formula injection (BUG-CSV-INJECTION): a source-controlled element
  name / discipline / assignee that begins with ``= + - @`` (or tab / CR)
  must be neutralised with a leading apostrophe by ``GET …/export-csv`` so
  a colleague opening the export in Excel / Sheets cannot be made to run a
  formula. Mirrors the boq / takeoff exporters' use of
  ``app.core.csv_safety.neutralise_formula``.
* Comment-author spoofing: ``PATCH …/results/{id}`` with a forged
  ``add_comment.author`` / ``author_id`` must NOT be trusted - authorship
  is server-authoritative (the authenticated caller), mirroring the bcf
  module. A client cannot post a triage note under another user's identity.

Driven end-to-end through the real ASGI app (same harness as
``test_clash_idor.py``) so the actual router wiring is exercised.
"""

from __future__ import annotations

import csv
import io
import uuid
from collections.abc import AsyncIterator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

# ── App + session fixtures (mirror test_clash_idor.py) ─────────────────────


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


# ── Helpers ────────────────────────────────────────────────────────────────


async def _seed_user_and_project(session) -> tuple[uuid.UUID, uuid.UUID]:
    from app.modules.projects.models import Project
    from app.modules.users.models import User

    user = User(
        email=f"clash-sec-{uuid.uuid4().hex[:8]}@test.io",
        hashed_password="x",
        full_name="Clash Security Tester",
        role="editor",
    )
    session.add(user)
    await session.flush()
    project = Project(name="Clash Security Project", owner_id=user.id)
    session.add(project)
    await session.commit()
    await session.refresh(project)
    return user.id, project.id


def _override_payload(
    app,
    user_id: uuid.UUID,
    *,
    role: str = "editor",
    perms: list[str] | None = None,
) -> None:
    from app.dependencies import get_current_user_payload

    async def _payload() -> dict:
        return {
            "sub": str(user_id),
            "role": role,
            "permissions": list(perms or []),
        }

    app.dependency_overrides[get_current_user_payload] = _payload


async def _seed_clash_run(session, project_id: uuid.UUID) -> uuid.UUID:
    from app.modules.clash.models import ClashRun

    run = ClashRun(
        project_id=project_id,
        name="Security Test Run",
        model_ids=[],
        status="completed",
        created_by="test",
        summary={},
    )
    session.add(run)
    await session.commit()
    await session.refresh(run)
    return run.id


async def _seed_clash_result(
    session,
    run_id: uuid.UUID,
    *,
    a_name: str = "Wall A",
    b_name: str = "Pipe B",
    a_discipline: str = "Structural",
    b_discipline: str = "Mechanical",
    assigned_to: str | None = None,
) -> uuid.UUID:
    from app.modules.clash.models import ClashResult

    result = ClashResult(
        run_id=run_id,
        a_element_id=uuid.uuid4(),
        b_element_id=uuid.uuid4(),
        a_stable_id="elem-A",
        b_stable_id="elem-B",
        a_name=a_name,
        b_name=b_name,
        a_discipline=a_discipline,
        b_discipline=b_discipline,
        a_model_id=uuid.uuid4(),
        b_model_id=uuid.uuid4(),
        clash_type="hard",
        penetration_m=0.05,
        distance_m=0.0,
        cx=1.0,
        cy=2.0,
        cz=3.0,
        status="new",
        severity="medium",
        assigned_to=assigned_to,
    )
    session.add(result)
    await session.commit()
    await session.refresh(result)
    return result.id


# ── CSV formula-injection neutralisation ───────────────────────────────────


async def test_export_csv_neutralises_formula_injection(app_factory, db_session):
    """Dangerous-prefixed names/disciplines/assignee are apostrophe-guarded.

    A malicious BIM element name like ``=cmd|'/c calc'!A0`` (or a discipline
    / assignee starting with ``+ - @``) must be written with a leading
    ``'`` so the spreadsheet treats it as literal text, never a formula.
    """
    app = app_factory
    owner_id, project_id = await _seed_user_and_project(db_session)
    run_id = await _seed_clash_run(db_session, project_id)
    await _seed_clash_result(
        db_session,
        run_id,
        a_name="=cmd|'/c calc'!A0",
        b_name='+HYPERLINK("http://evil")',
        a_discipline="-2+3",
        b_discipline="@SUM(A1)",
        assigned_to="=1+1",
    )

    _override_payload(app, owner_id, role="editor", perms=["clash.export"])
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(f"/api/v1/clash/projects/{project_id}/runs/{run_id}/export-csv")
        assert resp.status_code == 200, resp.text
        body = resp.text
        # Parse the CSV back and inspect the single data row's cells.
        rows = list(csv.reader(io.StringIO(body)))
        assert len(rows) >= 2, f"Expected header + 1 data row, got {rows!r}"
        data = rows[1]
        # Every originally-dangerous cell must now start with an apostrophe
        # and must NOT start with a raw formula trigger.
        dangerous = ("=", "+", "-", "@")
        guarded = [c for c in data if c.startswith("'")]
        assert any(c.lstrip("'").startswith("=cmd") for c in guarded), f"a_name formula was not neutralised: {data!r}"
        # No cell that carried injected content leaks a bare formula trigger.
        for cell in data:
            if any(t in cell for t in ("cmd|", "HYPERLINK", "SUM(")):
                assert cell[0] not in dangerous, f"cell still parses as a formula: {cell!r}"
    finally:
        app.dependency_overrides.clear()


async def test_export_csv_leaves_benign_names_unchanged(app_factory, db_session):
    """A normal element name is exported verbatim (no spurious apostrophe)."""
    app = app_factory
    owner_id, project_id = await _seed_user_and_project(db_session)
    run_id = await _seed_clash_run(db_session, project_id)
    await _seed_clash_result(db_session, run_id, a_name="Wall 12", b_name="Duct 7")

    _override_payload(app, owner_id, role="editor", perms=["clash.export"])
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(f"/api/v1/clash/projects/{project_id}/runs/{run_id}/export-csv")
        assert resp.status_code == 200, resp.text
        body = resp.text
        assert "Wall 12" in body and "Duct 7" in body
        assert "'Wall 12" not in body, "benign name must not gain a leading apostrophe"
    finally:
        app.dependency_overrides.clear()


# ── Comment-author spoofing (server-authoritative authorship) ──────────────


async def test_comment_author_is_server_authoritative(app_factory, db_session):
    """A forged ``author`` / ``author_id`` on a comment PATCH is ignored.

    The stored comment must be attributed to the authenticated caller, not
    to whatever identity the client supplied - closing comment-author
    spoofing (mirrors the bcf module's server-side authorship).
    """
    app = app_factory
    caller_id, project_id = await _seed_user_and_project(db_session)
    # A second real user whose identity the attacker tries to forge.
    victim_id, _ = await _seed_user_and_project(db_session)
    run_id = await _seed_clash_run(db_session, project_id)
    result_id = await _seed_clash_result(db_session, run_id)

    forged_author = "Totally Someone Else"
    _override_payload(app, caller_id, role="editor", perms=["clash.update"])
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.patch(
                f"/api/v1/clash/projects/{project_id}/runs/{run_id}/results/{result_id}",
                json={
                    "add_comment": {
                        "text": "spoof attempt",
                        "author": forged_author,
                        "author_id": str(victim_id),
                    }
                },
            )
        assert resp.status_code == 200, resp.text
        comments = resp.json().get("comments") or []
        assert comments, "comment was not appended"
        added = comments[-1]
        # author_id MUST be the caller, never the forged victim id.
        assert added.get("author_id") == str(caller_id), f"author_id was spoofable: {added!r}"
        assert added.get("author_id") != str(victim_id)
        # The free-text author label must not be the attacker-supplied string.
        assert added.get("author") != forged_author, f"author label was spoofable: {added!r}"
    finally:
        app.dependency_overrides.clear()
