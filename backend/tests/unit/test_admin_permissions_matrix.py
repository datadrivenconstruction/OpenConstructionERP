"""Tests for ``GET /api/v1/admin/permissions/matrix`` and friends.

The endpoint snapshots the live ``PermissionRegistry`` for the admin
UI. We exercise the pure builder directly (no ASGI) so the unit suite
stays fast, plus one focused round-trip through the registry so the
gate (``audit.view``) and the response shape can't drift apart.

The edit surface (``PATCH /permissions/{key}`` and
``POST /permissions/preset/{name}``) is exercised via FastAPI's
``TestClient`` with dependency overrides for the admin role and the DB
session — that's the smallest setup that lets us assert the lockout
guard, the audit-log write, the 404 paths, and the non-admin 403.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.audit import AuditEntry
from app.core.permissions import (
    PermissionRegistry,
    Role,
    permission_registry,
    register_core_permissions,
)
from app.dependencies import (
    get_current_user_payload,
    get_session,
)
from app.modules.admin.permissions_router import _build_matrix_payload, router
from tests._pg import isolated_engine


@pytest.fixture
def fresh_registry(monkeypatch):
    """Swap the global registry for a clean instance for this test only."""
    clean = PermissionRegistry()
    monkeypatch.setattr("app.modules.admin.permissions_router.permission_registry", clean)
    return clean


class TestPermissionsMatrixPayload:
    def test_empty_registry_returns_canonical_roles_only(self, fresh_registry):
        payload = _build_matrix_payload()
        # ``roles`` is the matrix *column* set: the four permission-bearing
        # roles the UI renders cells for. The three field-worker personas
        # (field_worker / site_foreman / site_inspector) carry no
        # permissions yet (register_field_role_permissions is a design-stage
        # stub), so they are intentionally omitted from the column set even
        # though they exist in the canonical role hierarchy below.
        assert payload["roles"] == ["viewer", "editor", "manager", "admin"]
        assert payload["modules"] == []
        # Role hierarchy is rendered as {role_value: int_level} so the
        # UI can label / sort columns without re-implementing the
        # canonical order on its side. This mirrors the full canonical
        # ROLE_HIERARCHY, including the field-worker personas whose ranks
        # are NEGATIVE (below viewer=0) so a legacy default-`-1` lookup
        # can never promote a field worker above a viewer.
        assert payload["role_hierarchy"] == {
            "field_worker": -2,
            "site_foreman": -1,
            "site_inspector": 0,
            "viewer": 0,
            "editor": 1,
            "manager": 2,
            "admin": 3,
        }
        # Presets are surfaced so the UI can offer them in a dropdown
        # without hard-coding the list on its side.
        assert "viewer-default" in payload["presets"]
        assert "editor-default" in payload["presets"]
        assert "manager-default" in payload["presets"]

    def test_includes_registered_modules(self, fresh_registry):
        fresh_registry.register_module_permissions(
            "projects",
            {
                "projects.create": Role.EDITOR,
                "projects.delete": Role.MANAGER,
                "projects.read": Role.VIEWER,
            },
        )
        fresh_registry.register_module_permissions(
            "system",
            {"system.settings.write": Role.ADMIN},
        )

        payload = _build_matrix_payload()

        # Modules must be alphabetically sorted — the UI relies on a
        # stable order to keep the column rendering deterministic.
        names = [m["name"] for m in payload["modules"]]
        assert names == ["projects", "system"]

        projects = payload["modules"][0]
        # Permissions inside a module are also sorted alphabetically.
        keys = [p["key"] for p in projects["permissions"]]
        assert keys == ["projects.create", "projects.delete", "projects.read"]

        # Each permission carries the canonical role string for that
        # min_role. This is what the UI cell rendering hangs on.
        min_roles = {p["key"]: p["min_role"] for p in projects["permissions"]}
        assert min_roles == {
            "projects.create": "editor",
            "projects.delete": "manager",
            "projects.read": "viewer",
        }

    def test_core_permissions_round_trip(self):
        """Smoke: registering core perms surfaces the audit.view gate."""
        # Use the real global registry — we only inspect, we don't
        # mutate (register_core_permissions is idempotent).
        register_core_permissions()
        all_perms = permission_registry.list_all()
        assert all_perms.get("audit.view") == "manager"


# ── Edit-surface tests (PATCH + POST preset) ─────────────────────────────


@pytest_asyncio.fixture
async def edit_app(fresh_registry):
    """Mount the permissions router with a throwaway PostgreSQL DB + admin user.

    The app under test opens its own sessions via the ``get_session`` override,
    and the tests assert on the audit-log rows through a SEPARATE session, so the
    two run on different connections that must see each other's commits - hence a
    real throwaway database rather than a savepoint-rolled-back shared session.
    """
    # Seed the clean registry with a couple of perms to mutate.
    fresh_registry.register_module_permissions(
        "projects",
        {
            "projects.create": Role.EDITOR,
            "projects.delete": Role.MANAGER,
            "projects.read": Role.VIEWER,
        },
    )
    fresh_registry.register("permissions.admin", Role.ADMIN)

    async with isolated_engine() as engine:
        sessionmaker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        async def _override_session() -> AsyncIterator[AsyncSession]:
            async with sessionmaker() as session:
                yield session
                await session.commit()

        app = FastAPI()
        app.include_router(router, prefix="/v1/admin")
        app.dependency_overrides[get_session] = _override_session

        yield app, sessionmaker


def _set_admin(app: FastAPI, role: str = "admin", user_id: str | None = None) -> None:
    """Inject a fake JWT payload so the role / lockout gates see the caller."""
    uid = user_id or str(uuid.uuid4())

    async def _payload() -> dict[str, str]:
        return {
            "sub": uid,
            "role": role,
            "permissions": ["audit.view"],
        }

    app.dependency_overrides[get_current_user_payload] = _payload


@pytest.mark.asyncio
class TestPermissionsMatrixEdit:
    async def test_patch_toggles_min_role_and_writes_audit(self, edit_app):
        app, sessionmaker = edit_app
        _set_admin(app)

        # Drive the app with an in-process AsyncClient on THIS event loop. The
        # sync TestClient runs the handler on a separate anyio portal loop,
        # which would hand the request a DB connection bound to a different
        # loop than the engine - the source of "attached to a different loop".
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            # Flip projects.create from editor → manager.
            resp = await client.patch(
                "/v1/admin/permissions/projects.create",
                json={"min_role": "manager"},
            )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["previous_min_role"] == "editor"
        assert body["new_min_role"] == "manager"

        # Audit log carries the before/after.
        async with sessionmaker() as session:
            entries = (await session.execute(__import__("sqlalchemy").select(AuditEntry))).scalars().all()
        keys = [e.entity_id for e in entries]
        assert "projects.create" in keys
        update = next(e for e in entries if e.entity_id == "projects.create")
        assert update.action == "update"
        assert update.details["previous_min_role"] == "editor"
        assert update.details["new_min_role"] == "manager"

    async def test_patch_blocks_admin_lockout(self, edit_app):
        """Refuse to drop ``permissions.admin`` below admin role."""
        app, _ = edit_app
        _set_admin(app)
        client = TestClient(app)

        resp = client.patch(
            "/v1/admin/permissions/permissions.admin",
            json={"min_role": "viewer"},
        )
        assert resp.status_code == 400
        assert resp.json()["detail"]["code"] == "admin_lockout_blocked"

    async def test_patch_unknown_permission_returns_404(self, edit_app):
        app, _ = edit_app
        _set_admin(app)
        client = TestClient(app)

        resp = client.patch(
            "/v1/admin/permissions/nonexistent.thing",
            json={"min_role": "viewer"},
        )
        assert resp.status_code == 404
        assert resp.json()["detail"]["code"] == "permission_not_found"

    async def test_patch_non_admin_caller_is_forbidden(self, edit_app):
        app, _ = edit_app
        # A manager has audit.view but is below the admin role gate.
        _set_admin(app, role="manager")
        client = TestClient(app)

        resp = client.patch(
            "/v1/admin/permissions/projects.create",
            json={"min_role": "viewer"},
        )
        assert resp.status_code == 403

    async def test_preset_apply_rewrites_matrix(self, edit_app):
        """``viewer-default`` flips read-style keys to viewer."""
        app, sessionmaker = edit_app
        _set_admin(app)

        # In-process AsyncClient on THIS loop (see the patch test above for
        # why the sync TestClient cannot be used with a loop-bound engine).
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            # projects.read is already viewer — flip it to editor first so
            # the preset has something to undo.
            await client.patch(
                "/v1/admin/permissions/projects.read",
                json={"min_role": "editor"},
            )

            resp = await client.post("/v1/admin/permissions/preset/viewer-default")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["preset"] == "viewer-default"
        # At least projects.read should have moved back to viewer.
        keys_changed = {c["permission"] for c in body["changes"]}
        assert "projects.read" in keys_changed

        # Audit log carries one preset_applied row with the full diff.
        async with sessionmaker() as session:
            preset_entries = (
                (
                    await session.execute(
                        __import__("sqlalchemy").select(AuditEntry).where(AuditEntry.action == "preset_applied")
                    )
                )
                .scalars()
                .all()
            )
        assert len(preset_entries) == 1
        assert preset_entries[0].entity_id == "viewer-default"
        assert preset_entries[0].details["preset"] == "viewer-default"

    async def test_preset_unknown_returns_404(self, edit_app):
        app, _ = edit_app
        _set_admin(app)
        client = TestClient(app)

        resp = client.post("/v1/admin/permissions/preset/does-not-exist")
        assert resp.status_code == 404
        assert resp.json()["detail"]["code"] == "preset_not_found"
