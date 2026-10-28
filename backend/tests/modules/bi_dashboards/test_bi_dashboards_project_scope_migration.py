# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Executes ``v3293_bi_dashboards_project_scope`` against real PostgreSQL.

Reading a migration proves nothing about it, and this one carries a claim that
only a populated database can settle: adding the project dimension must leave
the rows that were already there readable, and leave them company-wide rather
than orphaning them into a project nobody named.

Three claims are checked here:

* ``upgrade()`` is a no-op against a database that already carries the columns.
  That is the ordinary case, because a fresh install materialises the schema
  with ``create_all`` and then stamps; the first thing this revision meets in
  production is a database that does not need it. It also pins that the index
  name the revision writes is the name ``create_all`` writes, which is the
  quiet way two install routes drift apart.
* Down then up restores the columns and their indexes, and neither direction
  trips over a second run.
* Rows written before the column existed survive the upgrade and come out with
  ``project_id`` NULL, which is what "company-wide" is stored as.

The revision is driven through an Alembic ``MigrationContext`` rather than
``alembic upgrade head`` so that what is under test is this revision's own SQL
and not the state of the 300-odd revisions around it. Whether it is reachable
is ``tests/unit/test_alembic_single_head.py``'s job.

Everything runs against a throwaway database from ``isolated_engine()``, cloned
per test and dropped afterwards. The shared unit database is off limits:
dropping columns in it would take down every other test in the session.

Run:
    cd backend
    python -m pytest tests/modules/bi_dashboards/test_bi_dashboards_project_scope_migration.py -v
"""

from __future__ import annotations

import importlib.util
import sys
import uuid
from collections.abc import Callable
from pathlib import Path
from types import ModuleType

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.engine import Connection

from tests._pg import isolated_engine

#: backend/tests/modules/bi_dashboards/<this file> -> backend/alembic/versions/<revision>
MIGRATION_PATH = Path(__file__).resolve().parents[3] / "alembic" / "versions" / "v3293_bi_dashboards_project_scope.py"

COLUMN = "project_id"

TABLES: tuple[str, ...] = (
    "oe_bi_dashboards_kpi_definition",
    "oe_bi_dashboards_report_definition",
    "oe_bi_dashboards_report_schedule",
    "oe_bi_dashboards_saved_filter",
)

#: The composite ``(project_id, created_at)`` index that
#: ``app.core.pg_optimizations`` hangs off ``create_all``'s ``after_create``
#: event. No revision in the repository creates these and this one follows that
#: convention, so a down/up round trip legitimately does not bring it back -
#: the hook does, on the next ``create_all``. Named here so the difference
#: stays a known one instead of quietly widening.
HOOK_INDEXES: frozenset[str] = frozenset(f"ix_{table}_{COLUMN}_created_at" for table in TABLES)

#: Minimal NOT NULL payload per table, so the "rows survive" check inserts
#: something a populated database would actually hold.
_SEED_COLUMNS: dict[str, dict[str, object]] = {
    "oe_bi_dashboards_kpi_definition": {"code": "legacy_kpi", "name": "Legacy KPI", "formula_ref": "noop"},
    "oe_bi_dashboards_report_definition": {"code": "legacy_report", "name": "Legacy report"},
    "oe_bi_dashboards_report_schedule": {"report_definition_id": None},
    "oe_bi_dashboards_saved_filter": {"name": "Legacy filter", "module": "boq"},
}


def _load_migration() -> ModuleType:
    """Import the revision file by path - ``alembic/versions`` is not a package."""
    spec = importlib.util.spec_from_file_location("bi_dashboards_project_scope_migration", MIGRATION_PATH)
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        pytest.fail(f"Cannot load the migration at {MIGRATION_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _apply(sync_conn: Connection, step: Callable[[], None]) -> None:
    """Run one migration function with ``op`` bound to this connection."""
    context = MigrationContext.configure(sync_conn)
    with Operations.context(context):
        step()


def _columns(sync_conn: Connection, table: str) -> set[str]:
    return {c["name"] for c in sa.inspect(sync_conn).get_columns(table)}


def _indexes(sync_conn: Connection, table: str) -> set[str]:
    return {i["name"] for i in sa.inspect(sync_conn).get_indexes(table) if i["name"]}


def test_migration_identifies_itself_and_chains_off_an_existing_revision() -> None:
    module = _load_migration()

    assert module.revision == "v3293_bi_dashboards_project_scope"
    assert module.down_revision == "v3292_finance_einvoice_seller_contact"
    parent = MIGRATION_PATH.parent / f"{module.down_revision}.py"
    assert parent.is_file(), "down_revision must name a revision file that exists"


@pytest.mark.asyncio
async def test_upgrade_is_a_no_op_on_a_database_create_all_already_built() -> None:
    """The production path is create_all then stamp, so this is the usual case.

    It also pins that the revision and ``create_all`` agree on the index name.
    If they did not, this would add a second index under the revision's own
    name and the two install routes would drift apart silently.
    """
    module = _load_migration()

    async with isolated_engine() as engine, engine.begin() as conn:
        before = {}
        for table in TABLES:
            columns = await conn.run_sync(_columns, table)
            assert COLUMN in columns, f"{table} should already carry {COLUMN} from the ORM metadata"
            before[table] = (columns, await conn.run_sync(_indexes, table))
            assert f"ix_{table}_{COLUMN}" in before[table][1], (
                f"{table}: create_all names the index differently from the revision"
            )

        await conn.run_sync(_apply, module.upgrade)

        for table in TABLES:
            assert (await conn.run_sync(_columns, table), await conn.run_sync(_indexes, table)) == before[table]


@pytest.mark.asyncio
async def test_down_then_up_restores_the_columns_and_both_directions_repeat() -> None:
    module = _load_migration()

    async with isolated_engine() as engine, engine.begin() as conn:
        before = {t: await conn.run_sync(_indexes, t) for t in TABLES}

        await conn.run_sync(_apply, module.downgrade)
        for table in TABLES:
            assert COLUMN not in await conn.run_sync(_columns, table)
        # A second downgrade must not trip over the column it already dropped.
        await conn.run_sync(_apply, module.downgrade)

        await conn.run_sync(_apply, module.upgrade)
        # And a second upgrade must not trip over the column it just added.
        await conn.run_sync(_apply, module.upgrade)

        for table in TABLES:
            assert COLUMN in await conn.run_sync(_columns, table)
            rebuilt = await conn.run_sync(_indexes, table)
            assert f"ix_{table}_{COLUMN}" in rebuilt
            lost = before[table] - rebuilt
            assert lost <= HOOK_INDEXES, f"{table} lost {sorted(lost - HOOK_INDEXES)}, which no hook will put back"


@pytest.mark.asyncio
async def test_rows_written_before_the_column_existed_survive_and_read_company_wide() -> None:
    """The claim that makes this safe on a populated database.

    Drop the column to reproduce the pre-migration shape, write a row into each
    table the way an existing deployment already has, then upgrade. Every row
    has to still be there, and has to come back with ``project_id`` NULL - the
    stored form of "company-wide", which is what keeps it listed on every
    project view instead of orphaned into one nobody named.
    """
    module = _load_migration()

    async with isolated_engine() as engine, engine.begin() as conn:
        await conn.run_sync(_apply, module.downgrade)

        report_id = str(uuid.uuid4())
        seeded: dict[str, str] = {}
        for table in TABLES:
            row_id = report_id if table == "oe_bi_dashboards_report_definition" else str(uuid.uuid4())
            seeded[table] = row_id
            values: dict[str, object] = {"id": row_id, **_SEED_COLUMNS[table]}
            if table == "oe_bi_dashboards_report_schedule":
                values["report_definition_id"] = report_id
            columns = ", ".join(values)
            binds = ", ".join(f":{name}" for name in values)
            await conn.execute(sa.text(f"INSERT INTO {table} ({columns}) VALUES ({binds})"), values)

        await conn.run_sync(_apply, module.upgrade)

        for table, row_id in seeded.items():
            row = (
                await conn.execute(
                    sa.text(f"SELECT id, {COLUMN} FROM {table} WHERE id = :id"),
                    {"id": row_id},
                )
            ).first()
            assert row is not None, f"{table} lost the row it held before the upgrade"
            assert row[1] is None, f"{table} did not leave the pre-existing row company-wide"
