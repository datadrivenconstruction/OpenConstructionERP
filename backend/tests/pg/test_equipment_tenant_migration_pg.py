# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A fleet that predates tenant scoping gets its owner's tenant, by migration or by boot repair.

``veq01_equipment_tenant`` (alembic) and ``equipment_tenant_backfill`` (boot
repair) must agree: a legacy unit goes to the oldest active administrator, or
to ``default`` on an install with no users, and the column ends NOT NULL with
the unit code unique per tenant. Each test works in a throwaway database cloned
from the schema template, so reshaping the table never reaches other tests.
"""

from __future__ import annotations

import importlib.util
import pathlib
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.equipment.models import Equipment
from app.modules.equipment.repairs import _run_tenant_backfill
from tests._pg import isolated_engine

pytestmark = pytest.mark.asyncio

_TABLE = "oe_equipment_equipment"
_MIGRATION = pathlib.Path(__file__).resolve().parents[2] / "alembic" / "versions" / "veq01_equipment_tenant.py"


def _migration():
    spec = importlib.util.spec_from_file_location("mig_veq01", _MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def _users(conn, *, with_admin: bool) -> dict[str, str]:
    """An old editor, an inactive old admin, and (optionally) the real owner: a newer active admin."""
    now = datetime.now(UTC)
    ids = {"editor": str(uuid.uuid4()), "inactive_admin": str(uuid.uuid4()), "admin": str(uuid.uuid4())}
    rows = [
        ("editor", "editor", True, now - timedelta(days=300)),
        ("inactive_admin", "admin", False, now - timedelta(days=200)),
    ]
    if with_admin:
        rows.append(("admin", "admin", True, now - timedelta(days=10)))
    for key, role, active, created in rows:
        await conn.execute(
            text(
                "INSERT INTO oe_users_user (id, email, hashed_password, full_name, locale, role, is_active, created_at, updated_at) "
                "VALUES (:id, :email, 'x', 'T', 'en', :role, :active, :created, :created)"
            ),
            {
                "id": ids[key],
                "email": f"{key}-{ids[key][:6]}@test.io",
                "role": role,
                "active": active,
                "created": created,
            },
        )
    return ids


async def _legacy_unit(conn, code: str) -> None:
    # Core insert so the model's own defaults fill every required column.
    await conn.execute(Equipment.__table__.insert().values(code=code, name="Legacy", tenant_id="tmp"))


async def _reshape_to_legacy(conn, *, drop_column: bool) -> None:
    """Back to the pre-tenant table: global unique code, no tenant (or a nullable one, as the boot heal leaves it)."""
    for index in ("uq_oe_equipment_equipment_tenant_code", "ix_oe_equipment_equipment_tenant_id"):
        await conn.execute(text(f"DROP INDEX IF EXISTS {index}"))
    if drop_column:
        await conn.execute(text(f"ALTER TABLE {_TABLE} DROP COLUMN tenant_id"))
        await conn.execute(text("DROP INDEX IF EXISTS ix_oe_equipment_equipment_code"))
        await conn.execute(text(f"CREATE UNIQUE INDEX ix_oe_equipment_equipment_code ON {_TABLE} (code)"))
    else:
        await conn.execute(text(f"ALTER TABLE {_TABLE} ALTER COLUMN tenant_id DROP NOT NULL"))
        await conn.execute(text(f"UPDATE {_TABLE} SET tenant_id = NULL"))  # noqa: S608


async def _schema(conn) -> dict:
    cols = {
        r[0]: r[1]
        for r in (
            await conn.execute(
                text(
                    "SELECT column_name, is_nullable FROM information_schema.columns "
                    "WHERE table_schema = current_schema() AND table_name = :t"
                ),
                {"t": _TABLE},
            )
        ).all()
    }
    indexes = {
        r[0]: r[1]
        for r in (
            await conn.execute(
                text(
                    "SELECT indexname, indexdef FROM pg_indexes WHERE schemaname = current_schema() AND tablename = :t"
                ),
                {"t": _TABLE},
            )
        ).all()
    }
    return {"columns": cols, "indexes": indexes}


async def _tenants(conn) -> list[str]:
    return [r[0] for r in (await conn.execute(text(f"SELECT tenant_id FROM {_TABLE} ORDER BY code"))).all()]  # noqa: S608


async def _run_migration(engine, step: str) -> None:
    module = _migration()

    def _apply(sync_conn) -> None:
        with Operations.context(MigrationContext.configure(sync_conn)):
            getattr(module, step)()

    async with engine.begin() as conn:
        await conn.run_sync(_apply)


async def test_the_repair_gives_legacy_units_the_oldest_active_admins_tenant() -> None:
    async with isolated_engine() as engine:
        async with engine.begin() as conn:
            ids = await _users(conn, with_admin=True)
            await _legacy_unit(conn, "L-1")
            await _legacy_unit(conn, "L-2")
            await _reshape_to_legacy(conn, drop_column=False)
        async with AsyncSession(engine) as session:
            assert await _run_tenant_backfill(session) == 2
            await session.commit()
        async with engine.connect() as conn:
            assert await _tenants(conn) == [ids["admin"], ids["admin"]]
            assert (await _schema(conn))["columns"]["tenant_id"] == "NO"
        async with AsyncSession(engine) as session:
            assert await _run_tenant_backfill(session) == 0  # a second boot changes nothing


async def test_the_repair_falls_back_to_default_on_an_install_without_users() -> None:
    async with isolated_engine() as engine:
        async with engine.begin() as conn:
            await _legacy_unit(conn, "L-1")
            await _reshape_to_legacy(conn, drop_column=False)
        async with AsyncSession(engine) as session:
            assert await _run_tenant_backfill(session) == 1
            await session.commit()
        async with engine.connect() as conn:
            assert await _tenants(conn) == ["default"]


async def test_the_repair_leaves_a_fleet_that_already_has_tenants_alone() -> None:
    async with isolated_engine() as engine:
        async with engine.begin() as conn:
            await _legacy_unit(conn, "L-1")  # tenant 'tmp', column already NOT NULL
        async with AsyncSession(engine) as session:
            assert await _run_tenant_backfill(session) == 0
        async with engine.connect() as conn:
            assert await _tenants(conn) == ["tmp"]


async def test_the_migration_goes_up_down_up_with_a_legacy_unit() -> None:
    async with isolated_engine() as engine:
        async with engine.begin() as conn:
            ids = await _users(conn, with_admin=True)
            await _legacy_unit(conn, "L-1")
            await _reshape_to_legacy(conn, drop_column=True)
            legacy = await _schema(conn)
        assert "tenant_id" not in legacy["columns"]
        assert "UNIQUE" in legacy["indexes"]["ix_oe_equipment_equipment_code"]

        await _run_migration(engine, "upgrade")
        async with engine.connect() as conn:
            up = await _schema(conn)
            assert up["columns"]["tenant_id"] == "NO"
            assert "UNIQUE" not in up["indexes"]["ix_oe_equipment_equipment_code"]
            assert "(tenant_id, code)" in up["indexes"]["uq_oe_equipment_equipment_tenant_code"]
            assert await _tenants(conn) == [ids["admin"]]

        await _run_migration(engine, "downgrade")
        async with engine.connect() as conn:
            down = await _schema(conn)
            assert "tenant_id" not in down["columns"]
            assert "UNIQUE" in down["indexes"]["ix_oe_equipment_equipment_code"]
            assert "uq_oe_equipment_equipment_tenant_code" not in down["indexes"]
            assert (await conn.execute(text(f"SELECT count(*) FROM {_TABLE}"))).scalar_one() == 1  # noqa: S608

        await _run_migration(engine, "upgrade")
        await _run_migration(engine, "upgrade")  # re-running is a no-op
        async with engine.connect() as conn:
            assert await _tenants(conn) == [ids["admin"]]
            assert (await _schema(conn))["columns"]["tenant_id"] == "NO"


async def test_the_migration_uses_default_when_no_user_exists() -> None:
    async with isolated_engine() as engine:
        async with engine.begin() as conn:
            await _legacy_unit(conn, "L-1")
            await _reshape_to_legacy(conn, drop_column=True)
        await _run_migration(engine, "upgrade")
        async with engine.connect() as conn:
            assert await _tenants(conn) == ["default"]
