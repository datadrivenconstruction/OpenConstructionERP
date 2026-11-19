# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The survey revision upgrades the release head, runs twice, downgrades cleanly and matches the models.

Runs on the suite's PostgreSQL. The test database is built from the models, so each walk first takes the three
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
_PATH = BACKEND / "alembic" / "versions" / "vsrv01_survey_core.py"
CRS, SETS, POINTS = "oe_survey_project_crs", "oe_survey_point_set", "oe_survey_point"
_TABLES = (CRS, SETS, POINTS)
RELEASE_HEAD = "vsub01_agreement_documents"  # head of the 19.8.0 release
PREVIOUS = "vdt04_po_delivery_address"  # the revision the survey chain follows in 19.9.0


def _load():
    spec = importlib.util.spec_from_file_location("survey_core_migration", _PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _tables(connection) -> set[str]:
    return set(inspect(connection).get_table_names())


def _bind(migration, connection, monkeypatch) -> None:
    monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))


def _previous_release(migration, connection, monkeypatch) -> None:
    """Leave the database as the 19.8.0 release does: none of the survey tables."""
    _bind(migration, connection, monkeypatch)
    if set(_TABLES) <= _tables(connection):
        # Later survey modules (surfaces, stockpiles, ...) hold FKs to these tables in the test schema.
        for table in _TABLES:
            connection.execute(sa.text(f"DROP TABLE {table} CASCADE"))
    assert not set(_TABLES) & _tables(connection)


# Columns a later revision (svc01_survey_calcs) adds to these tables.
_LATER = {POINTS: {"method", "inputs"}}


def _matches_the_models(connection) -> None:
    from app.modules.survey_core import models

    for table in (models.SurveyProjectCrs.__table__, models.SurveyPointSet.__table__, models.SurveyPoint.__table__):
        migrated = {c["name"]: c for c in inspect(connection).get_columns(table.name)}
        later = _LATER.get(table.name, set())
        assert set(migrated) == {c.name for c in table.columns} - later, table.name
        for column in table.columns:
            if column.name in later:
                continue
            assert migrated[column.name]["nullable"] == column.nullable, (table.name, column.name)
            if type(column.type) is sa.Numeric:
                got = migrated[column.name]["type"]
                assert (got.precision, got.scale) == (column.type.precision, column.type.scale), (
                    table.name,
                    column.name,
                )


# -- the revision chain (no database) ----------------------------------------------------------------------------


def test_there_is_one_head_and_the_survey_revision_follows_the_previous_revision() -> None:
    script = ScriptDirectory.from_config(Config(str(BACKEND / "alembic.ini")))
    assert len(script.get_heads()) == 1
    revision = script.get_revision("vsrv01_survey_core")
    assert revision is not None
    assert revision.down_revision == PREVIOUS
    assert script.get_revision(RELEASE_HEAD) is not None


def test_the_revision_is_reachable_from_the_head() -> None:
    script = ScriptDirectory.from_config(Config(str(BACKEND / "alembic.ini")))
    walked = {r.revision for r in script.walk_revisions()}
    assert {"vsrv01_survey_core", RELEASE_HEAD} <= walked


def test_the_revision_declares_its_names() -> None:
    migration = _load()
    assert migration.revision == "vsrv01_survey_core"
    assert migration.down_revision == PREVIOUS
    assert len(migration.revision) <= 32  # alembic_version.version_num is VARCHAR(32)


# -- the walk ----------------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upgrade_from_the_release_creates_the_tables_the_models_expect(monkeypatch) -> None:
    migration = _load()

    def walk(connection) -> None:
        _previous_release(migration, connection, monkeypatch)
        migration.upgrade()
        assert set(_TABLES) <= _tables(connection)
        _matches_the_models(connection)
        indexes = {i["name"] for t in (SETS, POINTS) for i in inspect(connection).get_indexes(t)}
        assert {"ix_oe_survey_point_set_project", "ix_oe_survey_point_project_pid", "ix_oe_survey_point_set"} <= indexes
        uniques = {u["name"] for u in inspect(connection).get_unique_constraints(CRS)}
        assert "uq_oe_survey_project_crs_project_id" in uniques

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
            sa.text(f"INSERT INTO {CRS} (id, project_id, horizontal_epsg) VALUES (:i, :p, 32633)"),
            {"i": str(uuid.uuid4()), "p": project},
        )
        migration.upgrade()
        rows = connection.execute(sa.text(f"SELECT horizontal_epsg FROM {CRS} WHERE project_id = :p"), {"p": project})
        assert [r[0] for r in rows] == [32633]

    async with transactional_session(disable_fks=True) as session:
        await session.run_sync(lambda s: walk(s.connection()))


@pytest.mark.asyncio
async def test_downgrade_with_data_removes_all_three_tables_and_up_again_is_empty(monkeypatch) -> None:
    migration = _load()
    project, point_set = str(uuid.uuid4()), str(uuid.uuid4())

    def walk(connection) -> None:
        _previous_release(migration, connection, monkeypatch)
        migration.upgrade()
        connection.execute(
            sa.text(f"INSERT INTO {SETS} (id, project_id, name) VALUES (:i, :p, 'control.csv')"),
            {"i": point_set, "p": project},
        )
        connection.execute(
            sa.text(
                f"INSERT INTO {POINTS} (id, project_id, point_set_id, point_id, e, n) VALUES (:i, :p, :s, 'CP1', 1, 2)"
            ),
            {"i": str(uuid.uuid4()), "p": project, "s": point_set},
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
        project = str(uuid.uuid4())
        insert = sa.text(f"INSERT INTO {CRS} (id, project_id) VALUES (:i, :p)")
        connection.execute(insert, {"i": str(uuid.uuid4()), "p": project})
        defaults = connection.execute(sa.text(f"SELECT vertical_mode, source, is_local_grid FROM {CRS}")).one()
        assert tuple(defaults) == ("same_as_source", "user", False)
        with pytest.raises(IntegrityError), connection.begin_nested():
            connection.execute(insert, {"i": str(uuid.uuid4()), "p": project})
        # A coordinate keeps a tenth of a millimetre exactly: Numeric, never float.
        set_id = str(uuid.uuid4())
        connection.execute(
            sa.text(f"INSERT INTO {SETS} (id, project_id, name) VALUES (:i, :p, 's')"), {"i": set_id, "p": project}
        )
        connection.execute(
            sa.text(
                f"INSERT INTO {POINTS} (id, project_id, point_set_id, point_id, e, n, z) "
                "VALUES (:i, :p, :s, 'A', 389000.1234, 5819000.0001, -0.0001)"
            ),
            {"i": str(uuid.uuid4()), "p": project, "s": set_id},
        )
        e, n, z = connection.execute(sa.text(f"SELECT e::text, n::text, z::text FROM {POINTS}")).one()
        assert (e, n, z) == ("389000.1234", "5819000.0001", "-0.0001")
        # Beyond the column is an error from the database, so the application has to stop it first.
        with pytest.raises(sa.exc.DBAPIError), connection.begin_nested():
            connection.execute(
                sa.text(
                    f"INSERT INTO {POINTS} (id, project_id, point_set_id, point_id, e, n) "
                    "VALUES (:i, :p, :s, 'B', 1e10, 0)"
                ),
                {"i": str(uuid.uuid4()), "p": project, "s": set_id},
            )

    async with transactional_session(disable_fks=True) as session:
        await session.run_sync(lambda s: walk(s.connection()))


@pytest.mark.asyncio
async def test_the_fk_cascades_remove_a_projects_survey_rows(monkeypatch) -> None:
    """Deleting a project takes its register with it: the ON DELETE CASCADE the migration declares."""
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
        point_fks = inspect(connection).get_foreign_keys(POINTS)
        assert any(fk["referred_table"] == SETS and fk["options"].get("ondelete") == "CASCADE" for fk in point_fks)

    async with transactional_session(disable_fks=True) as session:
        await session.run_sync(lambda s: walk(s.connection()))
