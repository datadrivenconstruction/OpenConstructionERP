# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The capital plan revision creates its four tables, runs twice, and can be undone.

Runs on PostgreSQL (the suite's database) and on a throwaway SQLite file.
"""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import inspect

from tests._pg import transactional_session

_PATH = Path(__file__).resolve().parents[2] / "alembic/versions/vcap01_capital_plan.py"
_TABLES = (
    "oe_capital_plan",
    "oe_capital_plan_envelope",
    "oe_capital_plan_scenario",
    "oe_capital_plan_item",
)


def _load():
    spec = importlib.util.spec_from_file_location("capital_plan_migration", _PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _walk(migration, connection, monkeypatch) -> None:
    monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))

    def tables() -> set[str]:
        return set(inspect(connection).get_table_names())

    migration.upgrade()
    migration.upgrade()
    assert set(_TABLES) <= tables()
    uniques = {u["name"] for u in inspect(connection).get_unique_constraints("oe_capital_plan_envelope")}
    assert "uq_capital_plan_envelope_year_label" in uniques
    migration.downgrade()
    assert not set(_TABLES) & tables()
    migration.downgrade()
    migration.upgrade()
    assert set(_TABLES) <= tables()


def test_the_revision_chains_after_the_site_survey_revision() -> None:
    migration = _load()
    assert migration.revision == "vcap01_capital_plan"
    assert migration.down_revision == "vdro01_site_survey_captures"


def test_the_revision_is_the_only_head() -> None:
    revisions: set[str] = set()
    parents: set[str] = set()
    for path in _PATH.parent.glob("*.py"):
        for node in ast.parse(path.read_text(encoding="utf-8")).body:
            target = getattr(node, "target", None) or (node.targets[0] if isinstance(node, ast.Assign) else None)
            name = getattr(target, "id", None)
            if name not in ("revision", "down_revision") or node.value is None:
                continue
            value = ast.literal_eval(node.value)
            if name == "revision":
                revisions.add(value)
            else:
                parents.update([value] if isinstance(value, str) else value or [])
    assert len(revisions - parents) == 1


@pytest.mark.asyncio
async def test_upgrade_and_downgrade_on_postgresql(monkeypatch) -> None:
    migration = _load()
    async with transactional_session(disable_fks=True) as session:

        def run(sync_session) -> None:
            connection = sync_session.connection()
            for table in _TABLES:
                connection.execute(sa.text(f"DROP TABLE IF EXISTS {table} CASCADE"))
            _walk(migration, connection, monkeypatch)

        await session.run_sync(run)


def test_upgrade_and_downgrade_on_sqlite(monkeypatch, tmp_path) -> None:
    migration = _load()
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'capital_plan.db'}")
    with engine.begin() as connection:
        connection.execute(sa.text("CREATE TABLE oe_portfolio_node (id CHAR(32) PRIMARY KEY)"))
        _walk(migration, connection, monkeypatch)
    engine.dispose()
