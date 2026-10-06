# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Installing a module over the table an earlier version of it left behind.

Removing a module keeps its records by default, and there is no edit path for
an installed module, so adding a function to one means removing it and
building it again under the same key. The new code then meets the old table.
The generated ``ensure_table`` only creates a table that is missing, so
before this, every read of a new column failed and the module answered 500.

So the install compares the spec with the table first, before it writes a
file:

- What only adds is applied, in one transaction: a new column that may be
  empty (a new optional field or a link, with its foreign key), the status
  column with the first state as its default for the rows already there, the
  indexes the spec declares, and, on PostgreSQL, a field that is no longer
  required losing its NOT NULL.
- What would lose, hide or break records is refused with
  :data:`LAYOUT_CONFLICT` and nothing is changed: a column the spec no longer
  has, a column whose kind of value changed, a link that now points at
  another kind of record, a new required field, and a field that became
  required while records leave it empty.
- A table with no records in it holds nothing to lose, so when it differs in
  any of those ways it is dropped and created again from the spec.

A field that became required where every record has a value is left nullable
in the table: the module's own schemas already require it on every write.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import Boolean, Date, DateTime, Integer, String, Text, inspect, text
from sqlalchemy.types import TypeEngine

from app.core.db_types import MoneyType
from app.database import GUID
from app.modules.module_builder.links import LINK_TARGETS
from app.modules.module_builder.spec import STATUS_CODE_MAX, STATUS_COLUMN, ModuleSpec

logger = logging.getLogger(__name__)

#: The code a refused install carries, for the frontend to say it in the
#: reader's language.
LAYOUT_CONFLICT = "layout_conflict"

# What each problem is called in the refusal's params.
REMOVED = "removed"
CHANGED = "changed"
NEW_REQUIRED = "new_required"
NOW_REQUIRED = "now_required"
NOW_OPTIONAL = "now_optional"

# The column type of each field type, as generator.COLUMN_TYPES writes it into
# the model. A test compares the two through the real generated model.
_FIELD_TYPES: dict[str, Any] = {
    "text": lambda: String(255),
    "long_text": Text,
    "integer": Integer,
    "number": lambda: MoneyType(18, 4),
    "money": lambda: MoneyType(18, 2),
    "date": Date,
    "datetime": lambda: DateTime(timezone=True),
    "boolean": Boolean,
    "select": lambda: String(64),
    "link": GUID,
}


@dataclass(frozen=True)
class Column:
    """One column the generated model declares."""

    name: str
    label: str
    type: TypeEngine
    nullable: bool
    # A SQL literal the column fills existing rows with when it is added.
    default: str | None = None
    # The table a link points at; deleting a row there empties the link.
    references: str | None = None


@dataclass(frozen=True)
class Problem:
    """One way the existing table cannot take the new spec without losing something."""

    column: str
    label: str
    kind: str
    # NOW_REQUIRED only: how many records leave the field empty.
    empty: int = 0


@dataclass
class Plan:
    """What installing over the existing table means."""

    exists: bool = False
    records: int = 0
    add: list[Column] = field(default_factory=list)
    relax: list[Column] = field(default_factory=list)
    indexes: list[tuple[str, str]] = field(default_factory=list)
    problems: list[Problem] = field(default_factory=list)

    @property
    def recreate(self) -> bool:
        """An empty table that differs is dropped and created again."""
        return bool(self.problems) and self.records == 0

    @property
    def refused(self) -> bool:
        return bool(self.problems) and self.records > 0

    @property
    def changes(self) -> bool:
        return bool(self.add or self.relax or self.indexes) or self.recreate


class LayoutConflict(Exception):
    """The table holds records the new spec would lose or could not read."""

    def __init__(self, plan: Plan) -> None:
        self.plan = plan
        super().__init__(message(plan))

    @property
    def params(self) -> dict[str, Any]:
        return {
            "records": self.plan.records,
            "fields": [
                {"name": p.column, "label": p.label, "problem": p.kind, **({"empty": p.empty} if p.empty else {})}
                for p in self.plan.problems
            ],
        }


def expected_columns(spec: ModuleSpec) -> list[Column]:
    """The columns of the table the generated model describes, in its order."""
    columns = [Column("id", "id", GUID(), nullable=False)]
    if spec.entity.project_scoped:
        columns.append(Column("project_id", "project", GUID(), nullable=False, references="oe_projects_project"))
    for f in spec.entity.fields:
        if f.type == "link":
            target = LINK_TARGETS[f.target].table if f.target else None
            columns.append(Column(f.name, f.label, GUID(), nullable=True, references=target))
        else:
            columns.append(Column(f.name, f.label, _FIELD_TYPES[f.type](), nullable=not f.required))
    status = spec.features.status
    if status is not None:
        first = status.states[0].code
        columns.append(Column(STATUS_COLUMN, "status", String(STATUS_CODE_MAX), nullable=False, default=f"'{first}'"))
    columns.append(
        Column("created_at", "created", DateTime(timezone=True), nullable=False, default="CURRENT_TIMESTAMP")
    )
    columns.append(
        Column("updated_at", "updated", DateTime(timezone=True), nullable=False, default="CURRENT_TIMESTAMP")
    )
    return columns


def expected_indexes(spec: ModuleSpec) -> list[tuple[str, str]]:
    """``(name, column)`` of every index the generated model declares."""
    table = spec.table_name
    indexes = []
    if spec.entity.project_scoped:
        indexes.append((f"ix_{table}_project", "project_id"))
    indexes.append((f"ix_{table}_created", "created_at"))
    indexes += [(f"ix_{table}_{f.name}", f.name) for f in spec.link_fields]
    if spec.features.status is not None:
        indexes.append((f"ix_{table}_{STATUS_COLUMN}", STATUS_COLUMN))
    return indexes


def plan(connection: Any, spec: ModuleSpec) -> Plan:
    """Compare the spec with the table on a synchronous connection. Reads only."""
    table = spec.table_name
    inspector = inspect(connection)
    if not inspector.has_table(table):
        return Plan()
    result = Plan(exists=True)
    result.records = int(connection.execute(text(f"SELECT count(*) FROM {_quote(connection, table)}")).scalar_one())

    dialect = connection.dialect
    present = {c["name"]: c for c in inspector.get_columns(table)}
    pointing = {tuple(fk["constrained_columns"]): fk["referred_table"] for fk in inspector.get_foreign_keys(table)}
    expected = expected_columns(spec)
    for column in expected:
        existing = present.get(column.name)
        if existing is None:
            if column.nullable or column.default is not None:
                result.add.append(column)
            else:
                result.problems.append(Problem(column.name, column.label, NEW_REQUIRED))
            continue
        if _ddl(column.type, dialect) != _ddl(existing["type"], dialect) or (
            column.references is not None and pointing.get((column.name,)) != column.references
        ):
            result.problems.append(Problem(column.name, column.label, CHANGED))
            continue
        if not column.nullable and existing["nullable"]:
            empty = _empty(connection, table, column.name)
            if empty:
                result.problems.append(Problem(column.name, column.label, NOW_REQUIRED, empty=empty))
        elif column.nullable and not existing["nullable"]:
            if dialect.name == "postgresql":
                result.relax.append(column)
            else:
                result.problems.append(Problem(column.name, column.label, NOW_OPTIONAL))
    names = {c.name for c in expected}
    result.problems += [Problem(name, name, REMOVED) for name in present if name not in names]

    have = {ix["name"] for ix in inspector.get_indexes(table)}
    result.indexes = [(name, column) for name, column in expected_indexes(spec) if name not in have]
    return result


def apply(connection: Any, spec: ModuleSpec, layout: Plan) -> None:
    """Make the table take the spec, on the connection's open transaction.

    Raises:
        LayoutConflict: The table holds records the spec would lose.
    """
    if layout.refused:
        raise LayoutConflict(layout)
    table = _quote(connection, spec.table_name)
    if layout.recreate:
        # Nothing in it, so nothing to keep: the module creates it afresh on load.
        connection.execute(text(f"DROP TABLE {table}"))
        logger.info("module_builder: %s was empty and differed from the spec, so it is created again", table)
        return
    for column in layout.add:
        connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {_column_ddl(connection, column)}"))
    for column in layout.relax:
        connection.execute(text(f"ALTER TABLE {table} ALTER COLUMN {_quote(connection, column.name)} DROP NOT NULL"))
    for name, column_name in layout.indexes:
        connection.execute(
            text(f"CREATE INDEX {_quote(connection, name)} ON {table} ({_quote(connection, column_name)})")
        )
    if layout.changes:
        logger.info(
            "module_builder: %s took the new spec: added %s, no longer required %s, indexes %s",
            table,
            [c.name for c in layout.add],
            [c.name for c in layout.relax],
            [name for name, _ in layout.indexes],
        )


def prepare(connection: Any, spec: ModuleSpec) -> Plan:
    """Plan and apply in one go, for ``AsyncConnection.run_sync``."""
    layout = plan(connection, spec)
    apply(connection, spec, layout)
    return layout


def message(layout: Plan) -> str:
    """The refusal in plain words, for a reader who never saw the table."""
    count = layout.records
    held = f"{count} record" if count == 1 else f"{count} records"
    reasons = []
    for p in layout.problems:
        name = f'"{p.label}"'
        if p.kind == REMOVED:
            reasons.append(f"{name} is no longer part of it")
        elif p.kind == CHANGED:
            reasons.append(f"{name} now holds a different kind of value")
        elif p.kind == NEW_REQUIRED:
            reasons.append(f"{name} is new and required, and the saved records have no value for it")
        elif p.kind == NOW_REQUIRED:
            reasons.append(f"{name} is now required, and {p.empty} saved records leave it empty")
        else:
            reasons.append(f"{name} is no longer required, which this database cannot change in place")
    return (
        f"This register already holds {held} saved with a different layout: {'; '.join(reasons)}. "
        "Nothing was changed. Keep the old layout for these fields, install the module under a new name, "
        "or remove the old module together with its data first."
    )


def _ddl(type_: TypeEngine, dialect: Any) -> str:
    return type_.compile(dialect=dialect).replace(" ", "").upper()


def _empty(connection: Any, table: str, column: str) -> int:
    stmt = f"SELECT count(*) FROM {_quote(connection, table)} WHERE {_quote(connection, column)} IS NULL"
    return int(connection.execute(text(stmt)).scalar_one())


def _quote(connection: Any, name: str) -> str:
    return connection.dialect.identifier_preparer.quote(name)


def _column_ddl(connection: Any, column: Column) -> str:
    parts = [_quote(connection, column.name), column.type.compile(dialect=connection.dialect)]
    if column.default is not None:
        parts.append(f"DEFAULT {column.default}")
    if not column.nullable:
        parts.append("NOT NULL")
    if column.references is not None:
        parts.append(f"REFERENCES {_quote(connection, column.references)} (id) ON DELETE SET NULL")
    return " ".join(parts)
