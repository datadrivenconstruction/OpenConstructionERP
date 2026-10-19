# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The zone-to-area and delivery-to-transport links are real foreign keys, on every install.

The two keys were once left out of the models because the boot heal issued them
before ``create_all`` had built the area and transport tables, and PostgreSQL
refused them on every upgrade. The heal now defers such a key until after
``create_all``. These tests check the three ways a database can come to have
the keys: built fresh from the models, upgraded by the boot (the previous
release's schema, healed and then ``create_all``), and walked by hand through
v98. They also check what the keys are for: deleting an area or a transport
straight in the database unlinks what pointed at it instead of leaving a
dangling id.
"""

from __future__ import annotations

import importlib.util
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from app.modules.site_logistics import models as m
from tests._pg import isolated_engine
from tests.pg.governance_fixtures import add_project, add_user

pytestmark = pytest.mark.asyncio

KEYS = {
    (m.LaydownZone.__tablename__, "fk_oe_site_zone_area", ("site_area_id",), m.SiteArea.__tablename__),
    (m.DeliveryBooking.__tablename__, "fk_oe_site_delivery_transport", ("transport_id",), m.Transport.__tablename__),
}
TABLES = sorted({table for table, *_ in KEYS})
NEW_TARGETS = [m.SiteArea.__tablename__, m.Transport.__tablename__]


def _load(name: str):
    path = Path(__file__).resolve().parents[2] / "alembic" / "versions" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_v98 = _load("v98_site_logistics_link_keys")


def _run(sync_conn, direction) -> None:
    with Operations.context(MigrationContext.configure(sync_conn)):
        direction()


def _keys(sync_conn) -> set[tuple]:
    inspector = sa.inspect(sync_conn)
    out = set()
    for table in TABLES:
        for fk in inspector.get_foreign_keys(table):
            if fk["name"] in {name for _t, name, _c, _r in KEYS}:
                out.add(
                    (
                        table,
                        fk["name"],
                        tuple(fk["constrained_columns"]),
                        fk["referred_table"],
                        (fk.get("options") or {}).get("ondelete"),
                    )
                )
    return out


EXPECTED = {(*key, "SET NULL") for key in KEYS}


async def test_a_fresh_schema_has_both_keys() -> None:
    async with isolated_engine() as engine:
        async with engine.connect() as conn:
            assert await conn.run_sync(_keys) == EXPECTED


async def test_v98_adds_the_keys_where_the_chain_is_walked_by_hand() -> None:
    async with isolated_engine() as engine:
        async with engine.begin() as conn:
            await conn.run_sync(_run, _v98.downgrade)
            assert await conn.run_sync(_keys) == set()
        async with engine.begin() as conn:
            await conn.run_sync(_run, _v98.upgrade)
            assert await conn.run_sync(_keys) == EXPECTED
        # Over a schema that already has them it changes nothing.
        async with engine.begin() as conn:
            await conn.run_sync(_run, _v98.upgrade)
            assert await conn.run_sync(_keys) == EXPECTED


async def test_the_upgrade_boot_adds_both_keys_without_a_refusal() -> None:
    """The previous release's schema: the two link columns without keys, no area or transport table."""
    from app.core.postgres_migrator import heal_deferred_foreign_keys, postgres_auto_migrate
    from app.database import Base

    async with isolated_engine() as engine:
        async with engine.begin() as conn:
            await conn.run_sync(_run, _v98.downgrade)
            for table in NEW_TARGETS:
                await conn.execute(sa.text(f'DROP TABLE "{table}" CASCADE'))

        skipped: list = []
        deferred: list[str] = []
        await postgres_auto_migrate(engine, Base, skipped=skipped, deferred_foreign_keys=deferred)
        refused = [(s.kind, s.table, s.name) for s in skipped if s.kind == "foreign_key" and s.table in TABLES]
        assert refused == []
        assert set(TABLES) <= set(deferred)

        # What the boot does next.
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        await heal_deferred_foreign_keys(engine, Base, deferred, skipped=skipped)

        assert [(s.kind, s.table, s.name) for s in skipped if s.table in TABLES] == []
        async with engine.connect() as conn:
            assert await conn.run_sync(_keys) == EXPECTED


async def test_deleting_the_target_row_unlinks_instead_of_dangling(pg_session) -> None:
    owner = await add_user(pg_session, "manager")
    pid = await add_project(pg_session, owner, [])
    area = m.SiteArea(project_id=pid, code="A1", area_kind="laydown")
    transport = m.Transport(project_id=pid, transport_kind="truck")
    pg_session.add_all([area, transport])
    await pg_session.flush()
    start = datetime(2026, 10, 19, 7, tzinfo=UTC)
    zone = m.LaydownZone(project_id=pid, name="Zone 1", site_area_id=area.id)
    delivery = m.DeliveryBooking(
        project_id=pid,
        supplier_name="Concrete supplier",
        window_start=start,
        window_end=start + timedelta(hours=1),
        transport_id=transport.id,
    )
    pg_session.add_all([zone, delivery])
    await pg_session.flush()

    # Straight in the database, past the service that unlinks by hand.
    await pg_session.execute(sa.text(f'DELETE FROM "{m.SiteArea.__tablename__}" WHERE id = :i'), {"i": str(area.id)})
    await pg_session.execute(
        sa.text(f'DELETE FROM "{m.Transport.__tablename__}" WHERE id = :i'), {"i": str(transport.id)}
    )

    row = (
        await pg_session.execute(
            sa.text(f'SELECT site_area_id FROM "{m.LaydownZone.__tablename__}" WHERE id = :i'), {"i": str(zone.id)}
        )
    ).one()
    assert row.site_area_id is None
    row = (
        await pg_session.execute(
            sa.text(f'SELECT transport_id FROM "{m.DeliveryBooking.__tablename__}" WHERE id = :i'),
            {"i": str(delivery.id)},
        )
    ).one()
    assert row.transport_id is None
