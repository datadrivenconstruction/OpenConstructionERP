# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Round-trip test for the Full EVM register migration.

A migration nobody has run is a guess. This drives the real ``upgrade()`` and
``downgrade()`` of ``v3264_full_evm_baseline_register`` against a throwaway
PostgreSQL database and checks the three properties the project asks of every
migration: it chains off an existing revision, it is idempotent, and its
downgrade actually reverses it rather than being a ``pass``.

The throwaway database is cloned from the session schema template, so it starts
with the tables already present - which is precisely the state that makes a
non-idempotent ``upgrade()`` blow up on an install that ran ``create_all``.

Migration files are loaded from disk by path: ``alembic/versions`` is a script
directory, not an importable package, and the installed ``alembic`` library
shadows the name.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest
import sqlalchemy as sa
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy.engine import make_url

from tests._pg import isolated_database_url

_VERSIONS = Path(__file__).resolve().parents[3] / "alembic" / "versions"
_REVISION = "v3264_full_evm_baseline_register"

_TABLES = (
    "oe_full_evm_baseline",
    "oe_full_evm_baseline_period",
    "oe_full_evm_measure",
)


def _load(revision: str) -> ModuleType:
    """Import a migration script by file path."""
    path = _VERSIONS / f"{revision}.py"
    spec = importlib.util.spec_from_file_location(f"_migration_{revision}", path)
    assert spec is not None and spec.loader is not None, f"cannot load {path}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def sync_engine():
    """A sync engine on a throwaway, schema-loaded PostgreSQL database."""
    with isolated_database_url() as async_url:
        url = make_url(async_url).set(drivername="postgresql+psycopg2")
        engine = sa.create_engine(url)
        try:
            yield engine
        finally:
            engine.dispose()


def _run(module: ModuleType, connection, direction: str) -> None:
    """Run a migration direction against a live connection."""
    context = MigrationContext.configure(connection)
    with Operations.context(context):
        getattr(module, direction)()


def _present(connection) -> set[str]:
    """Which of the module's tables currently exist."""
    names = set(sa.inspect(connection).get_table_names())
    return {t for t in _TABLES if t in names}


def test_revision_chains_off_an_existing_parent() -> None:
    """The migration declares a real parent revision, not a dangling one."""
    module = _load(_REVISION)

    assert module.revision == _REVISION
    assert module.down_revision == "v3263_cost_match_runs"
    parent = _load(module.down_revision)
    assert parent.revision == module.down_revision


def test_upgrade_is_idempotent_and_downgrade_really_reverses_it(sync_engine) -> None:
    """One database, the whole life cycle, plus the resulting column shapes."""
    module = _load(_REVISION)

    with sync_engine.begin() as connection:
        # The cloned template already has the tables, so a naive CREATE TABLE
        # would fail right here. This is the ran-create_all-first case.
        assert _present(connection) == set(_TABLES)
        _run(module, connection, "upgrade")
        assert _present(connection) == set(_TABLES)

        # Downgrade genuinely drops them - a `pass` would leave them behind.
        _run(module, connection, "downgrade")
        assert _present(connection) == set()

        # Repeating the downgrade on an already-clean database is safe.
        _run(module, connection, "downgrade")
        assert _present(connection) == set()

        # Upgrade rebuilds from nothing, which is the never-installed case.
        _run(module, connection, "upgrade")
        assert _present(connection) == set(_TABLES)

        columns = {c["name"]: c for c in sa.inspect(connection).get_columns("oe_full_evm_measure")}

    # Money is Numeric with four decimals, never float and never text.
    for money in ("bac", "pv", "ev", "ac", "sv", "cv", "eac", "etc", "vac"):
        assert isinstance(columns[money]["type"], sa.Numeric), f"{money} is not Numeric"
        assert columns[money]["type"].scale == 4

    # Index nullability is the correctness property, not a convenience: a NOT
    # NULL column defaulting to zero would report a project that has spent
    # nothing as maximally inefficient.
    for ratio in ("spi", "cpi", "tcpi_bac", "tcpi_eac", "percent_complete", "percent_spent"):
        assert isinstance(columns[ratio]["type"], sa.Numeric), f"{ratio} is not Numeric"
        assert columns[ratio]["nullable"], f"{ratio} must be nullable - NULL means undefined"

    # Both halves of the EAC provenance survive the round trip.
    assert not columns["eac_method"]["nullable"]
    assert not columns["eac_method_effective"]["nullable"]
