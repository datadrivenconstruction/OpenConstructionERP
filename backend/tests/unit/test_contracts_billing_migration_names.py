# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠``v42_contracts_billing_depth`` builds the same schema the models declare.

An install reaches the contracts billing tables one of two ways: ``create_all``
plus the boot heal, which read the models, or the revision chain, which reads
this file. If the two disagree about a constraint name, the migrated install
carries a foreign key the model does not know by that name and the next
revision that drops or alters it by name fails on one population only. If they
disagree about a column or its nullability, one population accepts a row the
other refuses.

Several foreign key names here are longer than PostgreSQL's 63 characters, and
SQLAlchemy shortens those with a hash suffix. A name written by hand would not
carry the suffix, so the revision copies the compiled names, and this file
compiles the models again and compares.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable

from app.modules.contracts.models import (
    ContractLine,
    ProgressClaim,
    ProgressClaimLine,
    RetentionRelease,
    SovAdjustment,
    StoredMaterial,
    StoredMaterialMovement,
)

_REVISION_PATH = Path(__file__).resolve().parents[2] / "alembic" / "versions" / "v42_contracts_billing_depth.py"

NEW_TABLES = {
    model.__tablename__: model for model in (SovAdjustment, RetentionRelease, StoredMaterial, StoredMaterialMovement)
}
EXTENDED_TABLES = {model.__tablename__: model for model in (ProgressClaim, ProgressClaimLine, ContractLine)}


def _revision() -> Any:
    """Load the one revision under test straight from its path."""
    spec = importlib.util.spec_from_file_location("contracts_billing_depth_under_test", _REVISION_PATH)
    assert spec and spec.loader, f"could not load {_REVISION_PATH}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def revision() -> Any:
    return _revision()


@pytest.fixture(scope="module")
def created(revision: Any) -> dict[str, list[Any]]:
    """What each ``_create_*`` helper would pass to ``op.create_table``, captured."""
    captured: dict[str, list[Any]] = {}
    real_op = revision.op
    revision.op = SimpleNamespace(create_table=lambda name, *items: captured.__setitem__(name, list(items)))
    try:
        for helper in ("_create_adjustment", "_create_release", "_create_material", "_create_movement"):
            getattr(revision, helper)()
    finally:
        revision.op = real_op
    return captured


def _compiled(table: Any) -> str:
    return str(CreateTable(table).compile(dialect=postgresql.dialect()))


def _model_constraint_names(table: Any, kind: str) -> set[str]:
    return set(re.findall(rf"CONSTRAINT (\S+) {kind}", _compiled(table)))


def _migration_constraint_names(items: list[Any], kind: str) -> set[str]:
    from sqlalchemy import ForeignKeyConstraint, UniqueConstraint

    wanted = ForeignKeyConstraint if kind == "FOREIGN KEY" else UniqueConstraint
    return {item.name for item in items if isinstance(item, wanted)}


def test_the_revision_creates_exactly_the_new_tables(created: dict[str, list[Any]]) -> None:
    assert set(created) == set(NEW_TABLES)


@pytest.mark.parametrize("table_name", sorted(NEW_TABLES))
@pytest.mark.parametrize("kind", ["FOREIGN KEY", "UNIQUE"])
def test_constraint_names_match_the_compiled_model(table_name: str, kind: str, created: dict[str, list[Any]]) -> None:
    model_names = _model_constraint_names(NEW_TABLES[table_name].__table__, kind)
    assert _migration_constraint_names(created[table_name], kind) == model_names
    for name in model_names:
        assert len(name) <= 63, f"{name} is longer than PostgreSQL keeps"


@pytest.mark.parametrize("table_name", sorted(NEW_TABLES))
def test_new_table_columns_and_nullability_match_the_model(table_name: str, created: dict[str, list[Any]]) -> None:
    from sqlalchemy import Column

    migrated = {item.name: item.nullable for item in created[table_name] if isinstance(item, Column)}
    declared = {column.name: column.nullable for column in NEW_TABLES[table_name].__table__.columns}
    assert migrated == declared


@pytest.mark.parametrize("table_name", sorted(EXTENDED_TABLES))
def test_added_columns_match_the_model(table_name: str, revision: Any) -> None:
    """Each added column exists on the model with the same nullability, and a NOT NULL one carries a default.

    The default is what lets ``add_column`` succeed on a table that already has
    rows, and it is the form the boot heal renders for the same column.
    """
    table = EXTENDED_TABLES[table_name].__table__
    added = revision._columns_added()[table_name]
    assert added, f"the revision adds nothing to {table_name}"
    for column in added:
        assert column.name in table.columns, f"{table_name}.{column.name} is not on the model"
        assert column.nullable == table.columns[column.name].nullable, column.name
        if not column.nullable:
            assert column.server_default is not None, f"{table_name}.{column.name} is NOT NULL without a default"
            assert table.columns[column.name].server_default is not None, column.name


def test_index_names_match_the_compiled_model(revision: Any) -> None:
    """The revision creates each index under the name ``index=True`` gives it.

    Otherwise a healed install and a migrated one each end up with the index
    under a different name, and one of them carries two over the same column
    after the other path has run too.
    """
    added_columns = {table: {column.name for column in cols} for table, cols in revision._columns_added().items()}
    expected: set[tuple[str, str]] = set()
    for table_name, model in {**NEW_TABLES, **EXTENDED_TABLES}.items():
        for index in model.__table__.indexes:
            columns = {column.name for column in index.columns}
            if table_name in EXTENDED_TABLES and not columns <= added_columns.get(table_name, set()):
                # An index this revision does not own, from an earlier one.
                continue
            compiled = str(CreateIndex(index).compile(dialect=postgresql.dialect()))
            name = re.search(r"CREATE (?:UNIQUE )?INDEX (\S+) ON", compiled)
            assert name, compiled
            expected.add((table_name, name.group(1)))
    assert {(table, name) for table, name, _columns in revision._INDEXES} == expected
