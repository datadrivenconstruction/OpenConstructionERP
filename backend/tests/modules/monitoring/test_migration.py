# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The monitoring revision upgrades the survey revision, runs twice, downgrades cleanly and matches the models.

Runs on the suite's PostgreSQL. The test database is built from the models, so each walk first takes the six
tables away with the revision's own downgrade: that is the database the previous release left behind.
"""

from __future__ import annotations

import importlib.util
import uuid
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError

from tests._pg import transactional_session

BACKEND = Path(__file__).resolve().parents[3]
_PATH = BACKEND / "alembic" / "versions" / "vmon01_monitoring.py"
SET, PROF, PT, EP, RD, AL = (
    "oe_monitoring_settings",
    "oe_monitoring_profile",
    "oe_monitoring_point",
    "oe_monitoring_epoch",
    "oe_monitoring_reading",
    "oe_monitoring_alert",
)
_TABLES = (SET, PROF, PT, EP, RD, AL)
PARENT = "vlpc01_land_parcels"


def _load():
    spec = importlib.util.spec_from_file_location("monitoring_migration", _PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _tables(connection) -> set[str]:
    return set(inspect(connection).get_table_names())


def _previous_release(migration, connection, monkeypatch) -> None:
    monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
    if set(_TABLES) <= _tables(connection):
        migration.downgrade()
    assert not set(_TABLES) & _tables(connection)


def _matches_the_models(connection) -> None:
    from app.modules.monitoring import models

    for cls in (
        models.MonitoringSettings,
        models.MonitoringProfile,
        models.MonitoringPoint,
        models.MonitoringEpoch,
        models.MonitoringReading,
        models.MonitoringAlert,
    ):
        table = cls.__table__
        migrated = {c["name"]: c for c in inspect(connection).get_columns(table.name)}
        assert set(migrated) == {c.name for c in table.columns}, table.name
        for column in table.columns:
            assert migrated[column.name]["nullable"] == column.nullable, (table.name, column.name)
            if type(column.type) is sa.Numeric:
                got = migrated[column.name]["type"]
                assert (got.precision, got.scale) == (column.type.precision, column.type.scale), (
                    table.name,
                    column.name,
                )
        # Declared indexes only: create_all's performance-index hook attaches more to the shared Table.
        model_indexes = {a.name for a in getattr(cls, "__table_args__", ()) if isinstance(a, sa.Index)}
        model_indexes |= {f"ix_{table.name}_{c.name}" for c in table.columns if c.index}
        assert model_indexes <= {i["name"] for i in inspect(connection).get_indexes(table.name)}, table.name


# -- the revision chain (no database) ----------------------------------------------------------------------------


def test_the_revision_hangs_off_the_survey_revision() -> None:
    script = ScriptDirectory.from_config(Config(str(BACKEND / "alembic.ini")))
    revision = script.get_revision("vmon01_monitoring")
    assert revision is not None
    assert revision.down_revision == PARENT
    assert script.get_revision(PARENT) is not None


def test_the_revision_declares_its_names() -> None:
    migration = _load()
    assert migration.revision == "vmon01_monitoring"
    assert migration.down_revision == PARENT
    assert len(migration.revision) <= 32  # alembic_version.version_num is VARCHAR(32)


# -- the walk ----------------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upgrade_creates_the_tables_the_models_expect(monkeypatch) -> None:
    migration = _load()

    def walk(connection) -> None:
        _previous_release(migration, connection, monkeypatch)
        migration.upgrade()
        assert set(_TABLES) <= _tables(connection)
        _matches_the_models(connection)
        uniques = {u["name"] for t in (SET, PT, EP, RD) for u in inspect(connection).get_unique_constraints(t)}
        assert {
            "uq_oe_monitoring_settings_project_id",
            "uq_oe_monitoring_point_project_code",
            "uq_oe_monitoring_epoch_project_at",
            "uq_oe_monitoring_reading_point_epoch",
        } <= uniques

    async with transactional_session(disable_fks=True) as session:
        await session.run_sync(lambda s: walk(s.connection()))


@pytest.mark.asyncio
async def test_a_second_upgrade_is_a_no_op_and_keeps_the_rows(monkeypatch) -> None:
    migration = _load()
    project = str(uuid.uuid4())

    def walk(connection) -> None:
        _previous_release(migration, connection, monkeypatch)
        migration.upgrade()
        connection.execute(
            sa.text(f"INSERT INTO {SET} (id, project_id, profile_key) VALUES (:i, :p, 'demo')"),
            {"i": str(uuid.uuid4()), "p": project},
        )
        migration.upgrade()
        rows = connection.execute(sa.text(f"SELECT profile_key FROM {SET} WHERE project_id = :p"), {"p": project})
        assert [r[0] for r in rows] == ["demo"]

    async with transactional_session(disable_fks=True) as session:
        await session.run_sync(lambda s: walk(s.connection()))


@pytest.mark.asyncio
async def test_downgrade_with_data_removes_every_table_and_up_again_is_empty(monkeypatch) -> None:
    migration = _load()
    project, point = str(uuid.uuid4()), str(uuid.uuid4())

    def walk(connection) -> None:
        _previous_release(migration, connection, monkeypatch)
        migration.upgrade()
        connection.execute(
            sa.text(f"INSERT INTO {PT} (id, project_id, code) VALUES (:i, :p, 'MP-01')"), {"i": point, "p": project}
        )
        migration.downgrade()
        assert not set(_TABLES) & _tables(connection)
        migration.upgrade()
        for table in _TABLES:
            assert connection.execute(sa.text(f"SELECT count(*) FROM {table}")).scalar() == 0

    async with transactional_session(disable_fks=True) as session:
        await session.run_sync(lambda s: walk(s.connection()))


@pytest.mark.asyncio
async def test_the_schema_holds_the_invariants_the_service_relies_on(monkeypatch) -> None:
    migration = _load()

    def walk(connection) -> None:
        _previous_release(migration, connection, monkeypatch)
        migration.upgrade()
        project, point, epoch = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
        connection.execute(
            sa.text(f"INSERT INTO {PT} (id, project_id, code) VALUES (:i, :p, 'MP-01')"), {"i": point, "p": project}
        )
        defaults = connection.execute(sa.text(f"SELECT point_type, axis FROM {PT}")).one()
        assert tuple(defaults) == ("settlement_pin", "z")
        with pytest.raises(IntegrityError), connection.begin_nested():
            connection.execute(
                sa.text(f"INSERT INTO {PT} (id, project_id, code) VALUES (:i, :p, 'MP-01')"),
                {"i": str(uuid.uuid4()), "p": project},
            )
        connection.execute(
            sa.text(f"INSERT INTO {EP} (id, project_id, observed_at) VALUES (:i, :p, '2026-10-09T00:00:00Z')"),
            {"i": epoch, "p": project},
        )
        reading = sa.text(f"INSERT INTO {RD} (id, project_id, point_id, epoch_id, z) VALUES (:i, :p, :pt, :e, 34.5120)")
        params = {"p": project, "pt": point, "e": epoch}
        connection.execute(reading, {"i": str(uuid.uuid4()), **params})
        # One reading per point and epoch; a second import of the same file cannot double it.
        with pytest.raises(IntegrityError), connection.begin_nested():
            connection.execute(reading, {"i": str(uuid.uuid4()), **params})
        # A tenth of a millimetre survives: Numeric, never float.
        assert connection.execute(sa.text(f"SELECT z::text FROM {RD}")).scalar() == "34.5120"

    async with transactional_session(disable_fks=True) as session:
        await session.run_sync(lambda s: walk(s.connection()))


@pytest.mark.asyncio
async def test_the_fk_cascades_are_declared(monkeypatch) -> None:
    migration = _load()

    def walk(connection) -> None:
        _previous_release(migration, connection, monkeypatch)
        migration.upgrade()
        for table in _TABLES:
            fks = inspect(connection).get_foreign_keys(table)
            assert any(
                fk["referred_table"] == "oe_projects_project" and fk["options"].get("ondelete") == "CASCADE"
                for fk in fks
            ), table
        for table, parent in ((RD, PT), (RD, EP), (AL, PT), (AL, RD)):
            fks = inspect(connection).get_foreign_keys(table)
            assert any(fk["referred_table"] == parent and fk["options"].get("ondelete") == "CASCADE" for fk in fks)

    async with transactional_session(disable_fks=True) as session:
        await session.run_sync(lambda s: walk(s.connection()))
