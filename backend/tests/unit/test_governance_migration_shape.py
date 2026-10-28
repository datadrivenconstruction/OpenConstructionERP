# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Revision v68 declares the schema the governance models declare, compared without a database.

A fresh install builds these tables from the models (``create_all``); an
upgraded one builds them from the revision. The round trip on PostgreSQL
(``tests/pg/test_governance_migration.py``) reflects both, but it runs only
where PostgreSQL does. This file compares the two declarations themselves:
column types, nullability, server defaults, primary keys, the column lists of
indexes and unique constraints, and what each foreign key points at.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from app.database import GUID
from app.modules.project_governance import models as gm

_MODELS = (
    gm.GovernanceCatalogue,
    gm.GovernanceCatalogueVersion,
    gm.GovernanceModel,
    gm.GovernanceArea,
    gm.GovernanceGate,
    gm.GovernanceDocument,
    gm.GovernanceCheck,
    gm.GovernanceDecision,
    gm.GovernanceCondition,
    gm.GovernanceChangeRequest,
)
TABLES = [m.__tablename__ for m in _MODELS]
_PG = postgresql.dialect()


def _revision() -> Any:
    path = Path(__file__).resolve().parents[2] / "alembic" / "versions" / "v68_project_governance.py"
    spec = importlib.util.spec_from_file_location("v68_project_governance_shape", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _tables_of_the_revision() -> dict[str, sa.Table]:
    """The tables ``upgrade`` creates, built from the same declarations it hands to ``create_table``."""
    rev = _revision()
    metadata = sa.MetaData()
    # The one table outside the module a governance foreign key points at.
    sa.Table("oe_projects_project", metadata, sa.Column("id", GUID(), primary_key=True))
    out: dict[str, sa.Table] = {}
    for name, columns, indexes in rev._TABLES:
        table = sa.Table(name, metadata, *rev._base(), *columns())
        for index_name, index_columns in indexes:
            sa.Index(index_name, *[table.c[c] for c in index_columns])
        out[name] = table
    return out


def _default(column: sa.Column) -> str | None:
    if column.server_default is None:
        return None
    arg = column.server_default.arg
    return arg if isinstance(arg, str) else str(arg.compile(dialect=_PG))


def _added_by_the_hook(index: sa.Index) -> bool:
    """An index ``app.core.pg_optimizations`` hung on the metadata, recognised by its exact name.

    After any ``create_all`` in the process the hook adds its own indexes to
    the shared metadata of the models (a foreign key column, ``project_id``
    with ``created_at`` or ``status``), so in a full run the models carry
    indexes no revision declares. Only the name the hook would give these very
    columns is let through; an index of any other name has to be declared.
    """
    from app.core.pg_optimizations import _index_name

    columns = [c.name for c in index.columns]
    table = index.table.name
    return index.name in (_index_name(table, columns), _index_name(table, columns, gin=True))


def _shape(table: sa.Table) -> dict[str, Any]:
    return {
        "columns": {c.name: (c.type.compile(dialect=_PG), bool(c.nullable), _default(c)) for c in table.columns},
        "primary_key": [c.name for c in table.primary_key.columns],
        "indexes": {
            i.name: ([c.name for c in i.columns], bool(i.unique)) for i in table.indexes if not _added_by_the_hook(i)
        },
        "unique": {
            u.name: [c.name for c in u.columns] for u in table.constraints if isinstance(u, sa.UniqueConstraint)
        },
        "foreign_keys": {
            fk.name: (
                [c.name for c in fk.columns],
                [e.target_fullname for e in fk.elements],
                fk.ondelete,
            )
            for fk in table.foreign_key_constraints
        },
    }


def test_the_revision_creates_the_ten_tables_of_the_models() -> None:
    assert sorted(_tables_of_the_revision()) == sorted(TABLES)
    assert len(TABLES) == 10


@pytest.mark.parametrize("model", _MODELS, ids=lambda m: m.__tablename__)
@pytest.mark.parametrize("part", ["columns", "primary_key", "indexes", "unique", "foreign_keys"])
def test_the_revision_and_the_model_declare_the_same(model: Any, part: str) -> None:
    from_models = _shape(model.__table__)[part]
    from_revision = _shape(_tables_of_the_revision()[model.__tablename__])[part]
    assert from_revision == from_models


def _every_index(table: sa.Table) -> dict[str, tuple[list[str], bool]]:
    return {i.name: ([c.name for c in i.columns], bool(i.unique)) for i in table.indexes}


@pytest.mark.parametrize("model", _MODELS, ids=lambda m: m.__tablename__)
def test_an_index_the_revision_creates_is_an_index_of_the_model_whatever_its_name(model: Any) -> None:
    """An index the module declares under the hook's own name is filtered above; here it is not."""
    from_revision = _every_index(_tables_of_the_revision()[model.__tablename__])
    from_models = _every_index(model.__table__)
    assert from_revision.items() <= from_models.items()


@pytest.mark.parametrize("model", _MODELS, ids=lambda m: m.__tablename__)
def test_no_index_of_the_model_repeats_an_index_of_the_hook_under_another_name(model: Any) -> None:
    """Two names for the same columns are two indexes in the database and one too many.

    The hook guards by name only, so an index of ours on (``project_id``,
    ``status``) under a name of ours gets a twin after any ``create_all``.
    """
    from app.core.pg_optimizations import _desired_indexes

    table = model.__table__
    before = set(table.indexes)
    try:
        list(_desired_indexes(table))  # building them hangs them on the table
        by_columns: dict[tuple[str, ...], list[str]] = {}
        for index in table.indexes:
            by_columns.setdefault(tuple(c.name for c in index.columns), []).append(str(index.name))
        assert {cols: names for cols, names in by_columns.items() if len(names) > 1} == {}
    finally:
        table.indexes.difference_update(set(table.indexes) - before)


def test_only_an_index_named_exactly_as_the_hook_names_it_is_let_through() -> None:
    from app.core.pg_optimizations import _index_name

    metadata = sa.MetaData()
    table = sa.Table(
        "oe_governance_probe",
        metadata,
        sa.Column("project_id", sa.Integer),
        sa.Column("status", sa.String(20)),
    )
    hooked = sa.Index(_index_name(table.name, ["project_id", "status"]), table.c.project_id, table.c.status)
    own = sa.Index("ix_oe_gov_probe_status", table.c.status)
    same_prefix = sa.Index("ix_oe_governance_probe_made_up", table.c.status)
    assert _added_by_the_hook(hooked) is True
    assert _added_by_the_hook(own) is False
    # The prefix alone is no excuse: an undeclared index of the module would hide behind it.
    assert _added_by_the_hook(same_prefix) is False
    assert sorted(_shape(table)["indexes"]) == ["ix_oe_gov_probe_status", "ix_oe_governance_probe_made_up"]


def test_the_comparison_reads_real_defaults_and_targets() -> None:
    """Guards the comparison itself: an empty shape on both sides would compare equal."""
    shape = _shape(gm.GovernanceGate.__table__)
    assert shape["columns"]["created_at"][2] == "now()"
    assert shape["columns"]["id"][1] is False
    assert shape["primary_key"] == ["id"]
    assert any("oe_projects_project.id" in targets for _, targets, _ in shape["foreign_keys"].values())
    assert all(columns for columns, _ in shape["indexes"].values()) and shape["indexes"]
    everything = [_shape(m.__table__) for m in _MODELS]
    assert sum(len(s["foreign_keys"]) for s in everything) >= 8
    assert sum(len(s["unique"]) for s in everything) >= 2
