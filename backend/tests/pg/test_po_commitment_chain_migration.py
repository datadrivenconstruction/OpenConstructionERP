# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""``vpo01`` and ``vpo02`` add what the models declare, and take it away again, on PostgreSQL.

Each revision runs on a throwaway database cloned from the schema-loaded
template: its columns are dropped first, so ``upgrade()`` exercises the add
path rather than the guarded no-op, then ``downgrade()`` and ``upgrade()``
run once more. The result is compared with what the ORM metadata declares.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from tests._pg import isolated_engine

pytestmark = pytest.mark.asyncio

#: revision -> {table: (columns, indexes)}
EXPECTED = {
    "vpo01_invoice_commitment_chain": {
        "oe_finance_invoice": (
            {
                "subcontract_agreement_id",
                "scheduled_payment_date",
                "submitted_by",
                "submitted_at",
                "approved_by",
                "approved_at",
            },
            {"ix_invoice_subcontract_agreement"},
        ),
    },
    "vpo02_po_lines_allocations_release": {
        "oe_finance_invoice_item": ({"po_line_id"}, {"ix_finance_invoice_item_po_line"}),
        "oe_finance_invoice": ({"released_at", "released_by", "released_export_id"}, set()),
        "oe_changeorders_order": ({"commitment_allocations"}, set()),
    },
}


def _load(name: str):
    path = Path(__file__).resolve().parents[2] / "alembic" / "versions" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run(sync_conn, direction) -> None:
    with Operations.context(MigrationContext.configure(sync_conn)):
        direction()


def _shape(sync_conn, tables) -> dict[str, tuple[set[str], set[str]]]:
    inspector = sa.inspect(sync_conn)
    return {
        t: (
            {c["name"] for c in inspector.get_columns(t)},
            {i["name"] for i in inspector.get_indexes(t) if i.get("name")},
        )
        for t in tables
    }


@pytest.mark.parametrize("revision", sorted(EXPECTED))
async def test_revision_adds_and_removes_its_columns(revision: str) -> None:
    from app.database import Base

    module = _load(revision)
    expected = EXPECTED[revision]
    for table, (columns, indexes) in expected.items():
        declared = Base.metadata.tables[table]
        assert columns <= set(declared.columns.keys()), table
        assert indexes <= {ix.name for ix in declared.indexes}, table

    async with isolated_engine() as engine:
        async with engine.begin() as conn:
            for table, (columns, indexes) in expected.items():
                for index in indexes:
                    await conn.execute(sa.text(f"DROP INDEX IF EXISTS {index}"))
                for column in columns:
                    await conn.execute(sa.text(f"ALTER TABLE {table} DROP COLUMN IF EXISTS {column}"))

            await conn.run_sync(_run, module.upgrade)
            after = await conn.run_sync(_shape, list(expected))
            for table, (columns, indexes) in expected.items():
                assert columns <= after[table][0], (table, columns - after[table][0])
                assert indexes <= after[table][1], (table, indexes - after[table][1])

            await conn.run_sync(_run, module.downgrade)
            gone = await conn.run_sync(_shape, list(expected))
            for table, (columns, indexes) in expected.items():
                assert not columns & gone[table][0], table
                assert not indexes & gone[table][1], table

            await conn.run_sync(_run, module.upgrade)
            again = await conn.run_sync(_shape, list(expected))
            for table, (columns, _indexes) in expected.items():
                assert columns <= again[table][0], table
