# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The cost structure revision turns flat account lists into trees and can be undone."""

from __future__ import annotations

import importlib.util
import uuid
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import inspect, text

from app.modules.costmodel.models import ControlAccount
from tests._pg import transactional_session

_PATH = Path(__file__).resolve().parents[2] / "alembic/versions/v92_costmodel_cost_structure.py"


def _load():
    spec = importlib.util.spec_from_file_location("cost_structure_migration", _PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.mark.asyncio
async def test_backfill_nests_by_code_titles_from_names_and_lists_and_round_trips(monkeypatch) -> None:
    migration = _load()
    project = uuid.uuid4()
    other = uuid.uuid4()

    async with transactional_session(disable_fks=True) as session:
        flat = {
            code: ControlAccount(project_id=project, code=code, name=name, classification_standard=std)
            for code, name, std in [
                ("300", "300", "din276"),
                ("330", "330", "din276"),
                ("331", "Load-bearing walls", "din276"),
                ("3399", "3399", "din276"),
                ("A1", "A1", "company"),
                ("A1.1", "A1.1", "company"),
            ]
        }
        # Same codes in another project must not become parents across projects.
        foreign = ControlAccount(project_id=other, code="300", name="300", classification_standard="din276")
        session.add_all([*flat.values(), foreign])
        await session.flush()
        ids = {code: str(a.id) for code, a in flat.items()}

        def check(sync_session) -> None:
            connection = sync_session.connection()
            monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
            migration.upgrade()
            migration.upgrade()

            def row(code: str, project_id: uuid.UUID = project):
                return connection.execute(
                    text(
                        "SELECT id, parent_id, level, title FROM oe_costmodel_control_account "
                        "WHERE project_id = :p AND code = :c"
                    ),
                    {"p": str(project_id), "c": code},
                ).one()

            r300, r330, r331, r3399 = row("300"), row("330"), row("331"), row("3399")
            assert r300.parent_id is None and r300.level == 1
            assert str(r330.parent_id) == ids["300"] and r330.level == 2
            assert str(r331.parent_id) == ids["330"] and r331.level == 3
            # 3399 is deeper than anything here: it nests under the most specific code that covers it.
            assert str(r3399.parent_id) == ids["330"]
            # A title that is just the code comes from the shipped list; a real name is kept.
            assert r330.title == "Außenwände / External walls"
            assert r331.title == "Load-bearing walls"
            assert r3399.title == ""
            # A custom standard keeps the parents its user set (none here).
            assert row("A1.1").parent_id is None
            assert row("300", other).parent_id is None

            migration.downgrade()
            migration.downgrade()
            columns = {c["name"] for c in inspect(connection).get_columns("oe_costmodel_control_account")}
            assert not {"title", "level", "own_amount", "is_leaf_postable"} & columns
            tables = set(inspect(connection).get_table_names())
            assert "oe_costmodel_position_allocation" not in tables
            assert "oe_costmodel_code_list" not in tables

            migration.upgrade()
            columns = {c["name"] for c in inspect(connection).get_columns("oe_costmodel_control_account")}
            assert {"title", "level", "own_amount", "is_leaf_postable"} <= columns
            assert row("331").level == 3

        await session.run_sync(check)
