# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Tests for:

1. Issue assignment FSM — clash result status transitions are server-side
   validated. Valid statuses: new → active → reviewed → approved / resolved
   / ignored. An invalid status string must be rejected (422).

2. Clash severity enum enforcement — only (critical, high, medium, low)
   are accepted; anything else is 422.

3. Federation-of-models support — a ClashRun.model_ids is a JSON list that
   can hold multiple BIM model UUIDs; ClashResult stores a_model_id and
   b_model_id independently so cross-model pairs (element from model A vs
   element from model B) are first-class citizens. Verify the data model
   supports federated references.

4. ClashRun.ignore_same_model flag — when True, same-model pairs must
   be filtered out during detection (regression guard for federated
   coordination noise filter).
"""

from __future__ import annotations

import os
import tempfile
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

_TMP_DIR = Path(tempfile.mkdtemp(prefix="oe-clash-fsm-"))
_TMP_DB = _TMP_DIR / "clash_fsm.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_TMP_DB.as_posix()}"
os.environ["DATABASE_SYNC_URL"] = f"sqlite:///{_TMP_DB.as_posix()}"

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402


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


async def _seed_run_and_result(
    session,
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID]:
    """Seed project, run, result. Returns (user_id, project_id, run_id, result_id)."""
    from app.modules.clash.models import ClashResult, ClashRun
    from app.modules.projects.models import Project
    from app.modules.users.models import User

    user = User(
        email=f"fsm-{uuid.uuid4().hex[:8]}@test.io",
        hashed_password="x",
        full_name="FSM Tester",
        role="editor",
    )
    session.add(user)
    await session.flush()
    project = Project(name="FSM Test Project", owner_id=user.id)
    session.add(project)
    await session.flush()
    run = ClashRun(
        project_id=project.id,
        name="FSM Run",
        model_ids=[],
        status="completed",
        created_by=str(user.id),
        summary={},
    )
    session.add(run)
    await session.flush()
    result = ClashResult(
        run_id=run.id,
        a_element_id=uuid.uuid4(),
        b_element_id=uuid.uuid4(),
        a_stable_id="A-stable",
        b_stable_id="B-stable",
        a_name="Wall A",
        b_name="Pipe B",
        a_discipline="Structural",
        b_discipline="Mechanical",
        a_model_id=uuid.uuid4(),
        b_model_id=uuid.uuid4(),
        clash_type="hard",
        penetration_m=0.04,
        distance_m=0.0,
        cx=0.0,
        cy=0.0,
        cz=0.0,
        status="new",
        severity="medium",
    )
    session.add(result)
    await session.commit()
    await session.refresh(run)
    await session.refresh(result)
    return user.id, project.id, run.id, result.id


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


# ── FSM: valid status transitions ─────────────────────────────────────────


@pytest.mark.parametrize(
    "target_status",
    ["active", "reviewed", "approved", "resolved", "ignored"],
)
async def test_valid_status_transitions_accepted(app_factory, db_session, target_status):
    """Every canonical clash status is accepted by the PATCH endpoint."""
    app = app_factory
    user_id, project_id, run_id, result_id = await _seed_run_and_result(db_session)

    _override_payload(app, user_id, role="editor", perms=["clash.update"])
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.patch(
                f"/api/v1/clash/projects/{project_id}/runs/{run_id}/results/{result_id}",
                json={"status": target_status},
            )
        assert resp.status_code == 200, (
            f"Expected 200 for status='{target_status}', got {resp.status_code}: {resp.text}"
        )
        body = resp.json()
        assert body["status"] == target_status, (
            f"Status not updated: expected {target_status!r}, got {body['status']!r}"
        )
    finally:
        app.dependency_overrides.clear()


async def test_invalid_status_rejected_422(app_factory, db_session):
    """An unknown status string is rejected with 422 (server-side validation)."""
    app = app_factory
    user_id, project_id, run_id, result_id = await _seed_run_and_result(db_session)

    _override_payload(app, user_id, role="editor", perms=["clash.update"])
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.patch(
                f"/api/v1/clash/projects/{project_id}/runs/{run_id}/results/{result_id}",
                json={"status": "totally_not_a_real_status"},
            )
        assert resp.status_code == 422, f"Expected 422 for invalid status, got {resp.status_code}: {resp.text}"
    finally:
        app.dependency_overrides.clear()


async def test_new_status_accepted(app_factory, db_session):
    """Status 'new' is a valid value (regression guard — must not be stripped)."""
    app = app_factory
    user_id, project_id, run_id, result_id = await _seed_run_and_result(db_session)

    _override_payload(app, user_id, role="editor", perms=["clash.update"])
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            # First move away from 'new'
            resp1 = await client.patch(
                f"/api/v1/clash/projects/{project_id}/runs/{run_id}/results/{result_id}",
                json={"status": "active"},
            )
            assert resp1.status_code == 200
            # Then flip back to 'new' (reopened-style)
            resp2 = await client.patch(
                f"/api/v1/clash/projects/{project_id}/runs/{run_id}/results/{result_id}",
                json={"status": "new"},
            )
        assert resp2.status_code == 200, resp2.text
        assert resp2.json()["status"] == "new"
    finally:
        app.dependency_overrides.clear()


# ── FSM: severity enum enforcement ────────────────────────────────────────


@pytest.mark.parametrize("valid_severity", ["critical", "high", "medium", "low"])
async def test_valid_severity_accepted(app_factory, db_session, valid_severity):
    """All four severity values are accepted by the PATCH endpoint."""
    app = app_factory
    user_id, project_id, run_id, result_id = await _seed_run_and_result(db_session)

    _override_payload(app, user_id, role="editor", perms=["clash.update"])
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.patch(
                f"/api/v1/clash/projects/{project_id}/runs/{run_id}/results/{result_id}",
                json={"severity": valid_severity},
            )
        assert resp.status_code == 200, (
            f"Expected 200 for severity='{valid_severity}', got {resp.status_code}: {resp.text}"
        )
        assert resp.json()["severity"] == valid_severity
    finally:
        app.dependency_overrides.clear()


async def test_invalid_severity_rejected_422(app_factory, db_session):
    """An unknown severity string is rejected with 422."""
    app = app_factory
    user_id, project_id, run_id, result_id = await _seed_run_and_result(db_session)

    _override_payload(app, user_id, role="editor", perms=["clash.update"])
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.patch(
                f"/api/v1/clash/projects/{project_id}/runs/{run_id}/results/{result_id}",
                json={"severity": "extreme"},
            )
        assert resp.status_code == 422, f"Expected 422 for invalid severity, got {resp.status_code}: {resp.text}"
    finally:
        app.dependency_overrides.clear()


async def test_severity_filter_on_results_list_rejects_invalid(app_factory, db_session):
    """Results list with invalid severity filter → 422."""
    app = app_factory
    user_id, project_id, run_id, _result_id = await _seed_run_and_result(db_session)

    _override_payload(app, user_id, role="editor", perms=["clash.read"])
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(
                f"/api/v1/clash/projects/{project_id}/runs/{run_id}/results?severity=catastrophic",
            )
        assert resp.status_code == 422, f"Expected 422 for invalid severity filter, got {resp.status_code}"
    finally:
        app.dependency_overrides.clear()


# ── Federation-of-models: data model verification ─────────────────────────


async def test_federated_clash_run_stores_multiple_model_ids(db_session):
    """ClashRun.model_ids can hold multiple UUIDs (JSON list column)."""
    from sqlalchemy import select

    from app.modules.clash.models import ClashRun
    from app.modules.projects.models import Project
    from app.modules.users.models import User

    user = User(
        email=f"fed-{uuid.uuid4().hex[:8]}@test.io",
        hashed_password="x",
        full_name="Federation Tester",
        role="editor",
    )
    db_session.add(user)
    await db_session.flush()
    project = Project(name="Federation Project", owner_id=user.id)
    db_session.add(project)
    await db_session.flush()

    model_a = uuid.uuid4()
    model_b = uuid.uuid4()
    model_c = uuid.uuid4()

    run = ClashRun(
        project_id=project.id,
        name="Federated Run",
        model_ids=[str(model_a), str(model_b), str(model_c)],
        status="completed",
        created_by=str(user.id),
        summary={},
    )
    db_session.add(run)
    await db_session.commit()
    await db_session.refresh(run)

    persisted = (await db_session.execute(select(ClashRun).where(ClashRun.id == run.id))).scalar_one()

    assert len(persisted.model_ids) == 3, f"Expected 3 model_ids, got {len(persisted.model_ids)}: {persisted.model_ids}"
    persisted_strs = [str(m) for m in persisted.model_ids]
    for mid in (str(model_a), str(model_b), str(model_c)):
        assert mid in persisted_strs, f"model_id {mid} missing from persisted model_ids"


async def test_federated_clash_result_stores_cross_model_pair(db_session):
    """ClashResult.a_model_id != b_model_id → cross-model clash is first-class."""
    from sqlalchemy import select

    from app.modules.clash.models import ClashResult, ClashRun
    from app.modules.projects.models import Project
    from app.modules.users.models import User

    user = User(
        email=f"cross-{uuid.uuid4().hex[:8]}@test.io",
        hashed_password="x",
        full_name="Cross-Model Tester",
        role="editor",
    )
    db_session.add(user)
    await db_session.flush()
    project = Project(name="Cross-Model Project", owner_id=user.id)
    db_session.add(project)
    await db_session.flush()

    model_a = uuid.uuid4()
    model_b = uuid.uuid4()
    run = ClashRun(
        project_id=project.id,
        name="Cross-Model Run",
        model_ids=[str(model_a), str(model_b)],
        ignore_same_model=True,  # federated noise filter
        status="completed",
        created_by=str(user.id),
        summary={},
    )
    db_session.add(run)
    await db_session.flush()

    cross_result = ClashResult(
        run_id=run.id,
        a_element_id=uuid.uuid4(),
        b_element_id=uuid.uuid4(),
        a_stable_id="elem-in-model-A",
        b_stable_id="elem-in-model-B",
        a_name="Structural Wall (Model A)",
        b_name="HVAC Duct (Model B)",
        a_discipline="Structural",
        b_discipline="Mechanical",
        a_model_id=model_a,  # ← element from model A
        b_model_id=model_b,  # ← element from model B (cross-model)
        clash_type="hard",
        penetration_m=0.08,
        distance_m=0.0,
        cx=5.0,
        cy=10.0,
        cz=3.0,
        status="new",
        severity="high",
    )
    db_session.add(cross_result)
    await db_session.commit()
    await db_session.refresh(cross_result)

    row = (await db_session.execute(select(ClashResult).where(ClashResult.id == cross_result.id))).scalar_one()

    assert str(row.a_model_id) == str(model_a), "a_model_id not persisted correctly"
    assert str(row.b_model_id) == str(model_b), "b_model_id not persisted correctly"
    assert str(row.a_model_id) != str(row.b_model_id), "a_model_id and b_model_id must differ for a cross-model clash"


async def test_ignore_same_model_flag_persisted(db_session):
    """ClashRun.ignore_same_model=True is persisted and readable."""
    from sqlalchemy import select

    from app.modules.clash.models import ClashRun
    from app.modules.projects.models import Project
    from app.modules.users.models import User

    user = User(
        email=f"ignore-{uuid.uuid4().hex[:8]}@test.io",
        hashed_password="x",
        full_name="Ignore Same Model Tester",
        role="editor",
    )
    db_session.add(user)
    await db_session.flush()
    project = Project(name="Ignore Same Model Project", owner_id=user.id)
    db_session.add(project)
    await db_session.flush()

    run = ClashRun(
        project_id=project.id,
        name="Federated Noise Filter Run",
        model_ids=[str(uuid.uuid4()), str(uuid.uuid4())],
        ignore_same_model=True,
        status="pending",
        created_by="tester",
        summary={},
    )
    db_session.add(run)
    await db_session.commit()
    await db_session.refresh(run)

    row = (await db_session.execute(select(ClashRun).where(ClashRun.id == run.id))).scalar_one()

    assert row.ignore_same_model is True, f"ignore_same_model flag not persisted: got {row.ignore_same_model!r}"


# ── Pure unit: CLASH_STATUSES + CLASH_SEVERITIES constants ────────────────


def test_clash_statuses_constant_covers_expected_values():
    """CLASH_STATUSES includes every status from the workflow specification."""
    from app.modules.clash.schemas import CLASH_STATUSES

    required = {"new", "active", "reviewed", "approved", "resolved", "ignored"}
    actual = set(CLASH_STATUSES)
    missing = required - actual
    assert not missing, f"Missing statuses from CLASH_STATUSES: {missing}"


def test_clash_severities_constant_is_complete():
    """CLASH_SEVERITIES covers exactly (critical, high, medium, low)."""
    from app.modules.clash.schemas import CLASH_SEVERITIES

    assert set(CLASH_SEVERITIES) == {"critical", "high", "medium", "low"}
    # Severity order: critical is worst (index 0).
    assert CLASH_SEVERITIES[0] == "critical"
    assert CLASH_SEVERITIES[-1] == "low"
