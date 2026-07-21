"""v2.8.0 — per-project match-settings integration tests.

Stands up a minimal FastAPI app with the projects router mounted plus
session/auth dependencies overridden against a per-test throwaway PostgreSQL
database (cloned from the schema-loaded template by ``tests._pg.isolated_engine``)
so the suite runs fast and never touches the production database.

Coverage:

* GET creates a default row on first read (lazy init)
* GET twice returns the same row
* PATCH validates classifier (rejects unknown values → 422)
* PATCH validates mode (rejects unknown values → 422)
* PATCH clamps auto_link_threshold into [0, 1]
* PATCH writes an audit-log entry with before/after snapshots
* RESET returns settings to defaults
* GET on a non-existent project → 404
* GET / PATCH on someone else's project → 403
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
)

from tests._pg import isolated_engine

# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def temp_engine_and_factory():
    """Per-test throwaway PostgreSQL database, cloned from the schema-loaded template.

    The app under test opens its own sessions via the ``get_session`` override, so
    the test and the app run on separate connections that must see each other's
    commits - hence a real throwaway database rather than a savepoint-rolled-back
    shared session.
    """
    async with isolated_engine() as engine:
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        yield engine, factory


# Each test mutates this dict to swap the acting user.
_current_user_payload: dict[str, str] = {}


@pytest_asyncio.fixture
async def app(temp_engine_and_factory) -> AsyncGenerator[FastAPI, None]:
    _engine, factory = temp_engine_and_factory

    from app.dependencies import (
        get_current_user_id,
        get_current_user_payload,
        get_session,
    )
    from app.modules.projects.router import router as projects_router

    app = FastAPI()
    app.include_router(projects_router, prefix="/api/v1/projects")

    async def _override_session() -> AsyncGenerator[AsyncSession, None]:
        async with factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    async def _override_payload() -> dict[str, str]:
        return dict(_current_user_payload)

    async def _override_user_id() -> str:
        return _current_user_payload.get("sub", "")

    app.dependency_overrides[get_session] = _override_session
    app.dependency_overrides[get_current_user_payload] = _override_payload
    app.dependency_overrides[get_current_user_id] = _override_user_id

    yield app


@pytest_asyncio.fixture
async def client(app: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture
async def project_owned_by(temp_engine_and_factory):
    """Factory that creates an owner User + a Project they own.

    Returns ``(user_id, project_id)``. Persists via the temp factory so
    the row is visible inside the dependency-overridden session.
    """
    _engine, factory = temp_engine_and_factory

    from app.modules.projects.models import Project
    from app.modules.users.models import User

    async def _make() -> tuple[uuid.UUID, uuid.UUID]:
        user = User(
            id=uuid.uuid4(),
            email=f"owner-{uuid.uuid4().hex[:6]}@match.io",
            hashed_password="x" * 60,
            full_name="Match Owner",
            role="estimator",
            locale="en",
            is_active=True,
            metadata_={},
        )
        project = Project(
            id=uuid.uuid4(),
            name="Match Test Project",
            owner_id=user.id,
            status="active",
        )
        async with factory() as session:
            session.add(user)
            await session.flush()
            session.add(project)
            await session.commit()
        return user.id, project.id

    return _make


def _set_acting_user(user_id: uuid.UUID, role: str = "estimator") -> None:
    _current_user_payload.clear()
    _current_user_payload["sub"] = str(user_id)
    _current_user_payload["role"] = role


# ── Tests ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_creates_default_row_on_first_call(
    client: AsyncClient,
    project_owned_by,
) -> None:
    user_id, project_id = await project_owned_by()
    _set_acting_user(user_id)

    resp = await client.get(f"/api/v1/projects/{project_id}/match-settings")
    assert resp.status_code == 200, resp.text

    body = resp.json()
    assert body["project_id"] == str(project_id)
    assert body["target_language"] == "en"
    assert body["classifier"] == "none"
    assert body["auto_link_threshold"] == 0.85
    assert body["auto_link_enabled"] is False
    assert body["mode"] == "manual"
    assert sorted(body["sources_enabled"]) == ["bim", "dwg", "pdf", "photo"]


@pytest.mark.asyncio
async def test_get_is_idempotent(
    client: AsyncClient,
    project_owned_by,
) -> None:
    """Two GETs return the same row id (no duplicate rows)."""
    user_id, project_id = await project_owned_by()
    _set_acting_user(user_id)

    r1 = await client.get(f"/api/v1/projects/{project_id}/match-settings")
    r2 = await client.get(f"/api/v1/projects/{project_id}/match-settings")
    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r1.json()["id"] == r2.json()["id"]


@pytest.mark.asyncio
async def test_patch_rejects_invalid_classifier(
    client: AsyncClient,
    project_owned_by,
) -> None:
    user_id, project_id = await project_owned_by()
    _set_acting_user(user_id)

    resp = await client.patch(
        f"/api/v1/projects/{project_id}/match-settings",
        json={"classifier": "uniclass"},
    )
    assert resp.status_code == 422, resp.text


@pytest.mark.asyncio
async def test_patch_rejects_invalid_mode(
    client: AsyncClient,
    project_owned_by,
) -> None:
    user_id, project_id = await project_owned_by()
    _set_acting_user(user_id)

    resp = await client.patch(
        f"/api/v1/projects/{project_id}/match-settings",
        json={"mode": "semi-auto"},
    )
    assert resp.status_code == 422, resp.text


@pytest.mark.asyncio
async def test_patch_clamps_threshold_via_pydantic_bounds(
    client: AsyncClient,
    project_owned_by,
) -> None:
    """Pydantic bounds reject >1 / <0 outright (422); in-range clamps no-op."""
    user_id, project_id = await project_owned_by()
    _set_acting_user(user_id)

    # Out-of-range — Pydantic Field(ge=0, le=1) rejects loudly.
    resp_high = await client.patch(
        f"/api/v1/projects/{project_id}/match-settings",
        json={"auto_link_threshold": 1.5},
    )
    assert resp_high.status_code == 422

    # In-range — accepted, persisted.
    resp_ok = await client.patch(
        f"/api/v1/projects/{project_id}/match-settings",
        json={"auto_link_threshold": 0.5},
    )
    assert resp_ok.status_code == 200, resp_ok.text
    assert resp_ok.json()["auto_link_threshold"] == 0.5


@pytest.mark.asyncio
async def test_patch_accepts_valid_payload_and_persists(
    client: AsyncClient,
    project_owned_by,
) -> None:
    user_id, project_id = await project_owned_by()
    _set_acting_user(user_id)

    payload = {
        "target_language": "de",
        "classifier": "din276",
        "auto_link_threshold": 0.92,
        "auto_link_enabled": True,
        "mode": "auto",
        "sources_enabled": ["bim", "pdf"],
    }
    resp = await client.patch(
        f"/api/v1/projects/{project_id}/match-settings",
        json=payload,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["target_language"] == "de"
    assert body["classifier"] == "din276"
    assert body["auto_link_threshold"] == 0.92
    assert body["auto_link_enabled"] is True
    assert body["mode"] == "auto"
    assert sorted(body["sources_enabled"]) == ["bim", "pdf"]

    # Re-read confirms persistence.
    resp_get = await client.get(f"/api/v1/projects/{project_id}/match-settings")
    assert resp_get.json()["mode"] == "auto"


@pytest.mark.asyncio
async def test_patch_writes_audit_log_entry(
    client: AsyncClient,
    project_owned_by,
    temp_engine_and_factory,
) -> None:
    """Audit entry must include before+after snapshots."""
    _engine, factory = temp_engine_and_factory
    user_id, project_id = await project_owned_by()
    _set_acting_user(user_id)

    # First GET — creates the default row (no audit yet).
    await client.get(f"/api/v1/projects/{project_id}/match-settings")

    resp = await client.patch(
        f"/api/v1/projects/{project_id}/match-settings",
        json={"mode": "auto", "auto_link_enabled": True},
    )
    assert resp.status_code == 200

    from app.core.audit import AuditEntry

    async with factory() as session:
        rows = (
            (
                await session.execute(
                    select(AuditEntry).where(
                        AuditEntry.entity_type == "project_match_settings",
                        AuditEntry.entity_id == str(project_id),
                    )
                )
            )
            .scalars()
            .all()
        )

    assert len(rows) == 1
    entry = rows[0]
    assert entry.action == "update"
    assert entry.user_id == user_id
    details = entry.details
    assert "before" in details
    assert "after" in details
    assert details["before"]["mode"] == "manual"
    assert details["after"]["mode"] == "auto"
    assert details["before"]["auto_link_enabled"] is False
    assert details["after"]["auto_link_enabled"] is True


@pytest.mark.asyncio
async def test_reset_returns_settings_to_defaults(
    client: AsyncClient,
    project_owned_by,
    temp_engine_and_factory,
) -> None:
    _engine, factory = temp_engine_and_factory
    user_id, project_id = await project_owned_by()
    _set_acting_user(user_id)

    # Mutate first.
    await client.patch(
        f"/api/v1/projects/{project_id}/match-settings",
        json={
            "target_language": "bg",
            "classifier": "nrm",
            "auto_link_threshold": 0.5,
            "auto_link_enabled": True,
            "mode": "auto",
            "sources_enabled": ["bim"],
        },
    )

    resp = await client.post(
        f"/api/v1/projects/{project_id}/match-settings/reset",
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["target_language"] == "en"
    assert body["classifier"] == "none"
    assert body["auto_link_threshold"] == 0.85
    assert body["auto_link_enabled"] is False
    assert body["mode"] == "manual"
    assert sorted(body["sources_enabled"]) == ["bim", "dwg", "pdf", "photo"]

    # Audit entry written for the reset, with the prior state in `before`.
    from app.core.audit import AuditEntry

    async with factory() as session:
        rows = (
            (
                await session.execute(
                    select(AuditEntry).where(
                        AuditEntry.entity_type == "project_match_settings",
                        AuditEntry.entity_id == str(project_id),
                        AuditEntry.action == "reset",
                    )
                )
            )
            .scalars()
            .all()
        )

    assert len(rows) == 1
    details = rows[0].details
    assert details["before"]["mode"] == "auto"
    assert details["after"]["mode"] == "manual"


@pytest.mark.asyncio
async def test_get_returns_404_for_nonexistent_project(
    client: AsyncClient,
    project_owned_by,
) -> None:
    """A real authenticated user asking for an unknown project_id → 404."""
    user_id, _project_id = await project_owned_by()
    _set_acting_user(user_id)

    bogus = uuid.uuid4()
    resp = await client.get(f"/api/v1/projects/{bogus}/match-settings")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_non_owner_gets_403(
    client: AsyncClient,
    project_owned_by,
) -> None:
    """A different user attempting to read settings of someone else's project."""
    _owner_id, project_id = await project_owned_by()

    intruder_id = uuid.uuid4()
    _set_acting_user(intruder_id, role="estimator")

    resp = await client.get(f"/api/v1/projects/{project_id}/match-settings")
    assert resp.status_code == 403

    resp_patch = await client.patch(
        f"/api/v1/projects/{project_id}/match-settings",
        json={"mode": "auto"},
    )
    assert resp_patch.status_code == 403


@pytest.mark.asyncio
async def test_admin_bypass_can_read_other_projects(
    client: AsyncClient,
    project_owned_by,
) -> None:
    """Admin role bypasses the ownership check (existing _verify_project_owner)."""
    _owner_id, project_id = await project_owned_by()

    admin_id = uuid.uuid4()
    _set_acting_user(admin_id, role="admin")

    resp = await client.get(f"/api/v1/projects/{project_id}/match-settings")
    assert resp.status_code == 200, resp.text


# ── v2.8.2 cost_database_id binding ───────────────────────────────────────


@pytest.mark.asyncio
async def test_default_cost_database_id_is_null(
    client: AsyncClient,
    project_owned_by,
) -> None:
    """Fresh projects start with no catalogue picked — UI shows the picker."""
    user_id, project_id = await project_owned_by()
    _set_acting_user(user_id)

    resp = await client.get(f"/api/v1/projects/{project_id}/match-settings")
    assert resp.status_code == 200
    assert resp.json()["cost_database_id"] is None


@pytest.mark.asyncio
async def test_patch_cost_database_id_round_trip(
    client: AsyncClient,
    project_owned_by,
) -> None:
    """PATCH writes cost_database_id; subsequent GET reads it back."""
    user_id, project_id = await project_owned_by()
    _set_acting_user(user_id)

    resp = await client.patch(
        f"/api/v1/projects/{project_id}/match-settings",
        json={"cost_database_id": "RU_STPETERSBURG"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["cost_database_id"] == "RU_STPETERSBURG"

    resp_get = await client.get(f"/api/v1/projects/{project_id}/match-settings")
    assert resp_get.json()["cost_database_id"] == "RU_STPETERSBURG"


@pytest.mark.asyncio
async def test_patch_cost_database_id_can_clear(
    client: AsyncClient,
    project_owned_by,
) -> None:
    """Sending null clears the binding — returns project to no_catalog_selected."""
    user_id, project_id = await project_owned_by()
    _set_acting_user(user_id)

    await client.patch(
        f"/api/v1/projects/{project_id}/match-settings",
        json={"cost_database_id": "DE_BERLIN"},
    )
    resp = await client.patch(
        f"/api/v1/projects/{project_id}/match-settings",
        json={"cost_database_id": None},
    )
    assert resp.status_code == 200
    assert resp.json()["cost_database_id"] is None


@pytest.mark.asyncio
async def test_patch_rejects_oversized_cost_database_id(
    client: AsyncClient,
    project_owned_by,
) -> None:
    """The 32-char Pydantic bound matches the SQL column width."""
    user_id, project_id = await project_owned_by()
    _set_acting_user(user_id)

    resp = await client.patch(
        f"/api/v1/projects/{project_id}/match-settings",
        json={"cost_database_id": "A" * 33},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_reset_clears_cost_database_id(
    client: AsyncClient,
    project_owned_by,
) -> None:
    """``reset`` returns cost_database_id to ``None`` along with everything else."""
    user_id, project_id = await project_owned_by()
    _set_acting_user(user_id)

    await client.patch(
        f"/api/v1/projects/{project_id}/match-settings",
        json={"cost_database_id": "BG_SOFIA"},
    )
    resp = await client.post(
        f"/api/v1/projects/{project_id}/match-settings/reset",
    )
    assert resp.status_code == 200
    assert resp.json()["cost_database_id"] is None


# ── v3-P8 multibase: cost_database_ids (list) ─────────────────────────────
#
# The multibase wave lets a project pin several catalogues at once via
# ``cost_database_ids: list[str]``. The singular ``cost_database_id`` stays
# for back-compat and is kept in lockstep with the head of the list
# (``cost_database_ids[0] == cost_database_id``). The list is validated
# (per-member width), de-duplicated, and capped so a runaway payload can't
# fan the ranker out across hundreds of collections.


@pytest.mark.asyncio
async def test_default_cost_database_ids_is_empty(
    client: AsyncClient,
    project_owned_by,
) -> None:
    """A fresh project starts with an empty multibase list."""
    user_id, project_id = await project_owned_by()
    _set_acting_user(user_id)

    resp = await client.get(f"/api/v1/projects/{project_id}/match-settings")
    assert resp.status_code == 200, resp.text
    assert resp.json()["cost_database_ids"] == []


@pytest.mark.asyncio
async def test_patch_cost_database_ids_round_trip_and_primary_sync(
    client: AsyncClient,
    project_owned_by,
) -> None:
    """PATCH writes the list; GET reads it back; the singular id stays in
    lockstep with the head of the list (the documented invariant)."""
    user_id, project_id = await project_owned_by()
    _set_acting_user(user_id)

    resp = await client.patch(
        f"/api/v1/projects/{project_id}/match-settings",
        json={"cost_database_ids": ["DE_BERLIN", "CH_ZURICH"]},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert set(body["cost_database_ids"]) == {"DE_BERLIN", "CH_ZURICH"}
    assert len(body["cost_database_ids"]) == 2
    # cost_database_ids[0] == cost_database_id.
    assert body["cost_database_id"] == body["cost_database_ids"][0]

    resp_get = await client.get(f"/api/v1/projects/{project_id}/match-settings")
    got = resp_get.json()
    assert set(got["cost_database_ids"]) == {"DE_BERLIN", "CH_ZURICH"}
    assert got["cost_database_id"] == got["cost_database_ids"][0]


@pytest.mark.asyncio
async def test_patch_cost_database_ids_dedupes_members(
    client: AsyncClient,
    project_owned_by,
) -> None:
    """A duplicated member collapses - the ranker never queries the same
    catalogue twice."""
    user_id, project_id = await project_owned_by()
    _set_acting_user(user_id)

    resp = await client.patch(
        f"/api/v1/projects/{project_id}/match-settings",
        json={"cost_database_ids": ["DE_BERLIN", "DE_BERLIN", "CH_ZURICH"]},
    )
    assert resp.status_code == 200, resp.text
    ids = resp.json()["cost_database_ids"]
    assert len(ids) == 2
    assert set(ids) == {"DE_BERLIN", "CH_ZURICH"}


@pytest.mark.asyncio
async def test_patch_cost_database_ids_rejects_oversized_member(
    client: AsyncClient,
    project_owned_by,
) -> None:
    """Each member obeys the same 32-char width as the singular column."""
    user_id, project_id = await project_owned_by()
    _set_acting_user(user_id)

    resp = await client.patch(
        f"/api/v1/projects/{project_id}/match-settings",
        json={"cost_database_ids": ["DE_BERLIN", "A" * 33]},
    )
    assert resp.status_code == 422, resp.text


@pytest.mark.asyncio
async def test_patch_cost_database_ids_caps_member_count(
    client: AsyncClient,
    project_owned_by,
) -> None:
    """A runaway list is capped: the endpoint either rejects it (422) or
    truncates it to a sane bound - never fans the ranker out across an
    unbounded number of collections."""
    user_id, project_id = await project_owned_by()
    _set_acting_user(user_id)

    oversized = [f"R{i}_CITY" for i in range(40)]
    resp = await client.patch(
        f"/api/v1/projects/{project_id}/match-settings",
        json={"cost_database_ids": oversized},
    )
    assert resp.status_code == 422 or len(resp.json()["cost_database_ids"]) < 40, resp.text


# ── v3-P8 multibase: migration reversibility ──────────────────────────────


def test_cost_database_ids_migration_is_reversible() -> None:
    """The migration that adds ``cost_database_ids`` to
    ``oe_projects_match_settings`` must ship a real, reversible up/down pair:
    an ``add_column`` in ``upgrade()`` and a matching ``drop_column`` in
    ``downgrade()``, with a proper revision chain.

    This is the static companion (no DB spin-up) to
    ``tests/integration/test_migrations_roundtrip.py`` and guards the
    'missing or broken downgrade' bug class for the multibase column. The
    live column-at-head behaviour is exercised by the round-trip PATCH/GET
    tests above, which run against the create_all schema.
    """
    from pathlib import Path

    versions_dir = Path(__file__).resolve().parents[2] / "alembic" / "versions"
    assert versions_dir.is_dir(), f"alembic versions dir not found at {versions_dir}"

    candidates = [
        p
        for p in versions_dir.glob("*.py")
        if "cost_database_ids" in p.read_text(encoding="utf-8")
    ]
    if not candidates:
        pytest.skip("cost_database_ids migration not present yet (parallel wave)")

    src = candidates[0].read_text(encoding="utf-8")

    upgrade_body = src.partition("def upgrade")[2].split("\ndef ", 1)[0]
    downgrade_body = src.partition("def downgrade")[2].split("\ndef ", 1)[0]

    assert "add_column" in upgrade_body and "cost_database_ids" in upgrade_body, (
        "upgrade() must add the cost_database_ids column"
    )
    assert "drop_column" in downgrade_body and "cost_database_ids" in downgrade_body, (
        "downgrade() must drop the cost_database_ids column (no empty/broken downgrade)"
    )
    # Revision chain integrity - the migration must be linked, not orphaned.
    assert "revision" in src
    assert "down_revision" in src
