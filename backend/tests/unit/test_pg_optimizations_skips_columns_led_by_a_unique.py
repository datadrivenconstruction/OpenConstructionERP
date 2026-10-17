# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The performance-index pass must not index a column a table-level unique already leads.

``pg_optimizations`` adds a btree index on every foreign-key column that is not
already the left-most column of an index. It counted model ``Index`` objects
and columns flagged ``index=True`` / ``unique=True``, but not a table-level
``UniqueConstraint``. PostgreSQL backs every unique constraint with a unique
btree index, so a foreign key leading one, such as
``UniqueConstraint("site_area_id", "stage_id")`` on the site area allocation,
got a second, redundant index: more to write on every insert, nothing gained on
any read.
"""

from __future__ import annotations

from sqlalchemy import Column, ForeignKey, Integer, MetaData, String, Table, UniqueConstraint

from app.core.pg_optimizations import _desired_indexes


def _parent(md: MetaData) -> Table:
    return Table("oe_test_pgopt_parent", md, Column("id", Integer, primary_key=True))


def _desired_columns(table: Table) -> list[tuple[str, ...]]:
    return [tuple(c.name for c in ix.columns) for ix in _desired_indexes(table)]


def test_a_foreign_key_leading_a_composite_unique_gets_no_second_index() -> None:
    md = MetaData()
    _parent(md)
    table = Table(
        "oe_test_pgopt_alloc",
        md,
        Column("id", Integer, primary_key=True),
        Column("parent_id", Integer, ForeignKey("oe_test_pgopt_parent.id"), nullable=False),
        Column("stage", String(20), nullable=False),
        UniqueConstraint("parent_id", "stage", name="uq_oe_test_pgopt_alloc_parent_stage"),
    )

    assert ("parent_id",) not in _desired_columns(table)


def test_a_foreign_key_with_a_single_column_table_level_unique_gets_no_second_index() -> None:
    md = MetaData()
    _parent(md)
    table = Table(
        "oe_test_pgopt_one",
        md,
        Column("id", Integer, primary_key=True),
        Column("parent_id", Integer, ForeignKey("oe_test_pgopt_parent.id"), nullable=False),
        UniqueConstraint("parent_id", name="uq_oe_test_pgopt_one_parent"),
    )

    assert ("parent_id",) not in _desired_columns(table)


def test_a_foreign_key_that_is_not_leading_the_unique_is_still_indexed() -> None:
    """Only the left-most column of a btree serves lookups on that column alone."""
    md = MetaData()
    _parent(md)
    table = Table(
        "oe_test_pgopt_second",
        md,
        Column("id", Integer, primary_key=True),
        Column("stage", String(20), nullable=False),
        Column("parent_id", Integer, ForeignKey("oe_test_pgopt_parent.id"), nullable=False),
        UniqueConstraint("stage", "parent_id", name="uq_oe_test_pgopt_second_stage_parent"),
    )

    assert ("parent_id",) in _desired_columns(table)
