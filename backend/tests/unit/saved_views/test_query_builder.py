"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Query builder - operator compilation and bind-parameter safety (no DB).

Locks down that each operator compiles to the expected SQL expression, that
values flow through bind parameters (no literal identifier interpolation), and
that sort / group_by / distinct compile as documented.
"""

from __future__ import annotations

import os

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://oe:oe@localhost:5432/openestimate")
os.environ.setdefault("DATABASE_SYNC_URL", "postgresql://oe:oe@localhost:5432/openestimate")

import pytest
from sqlalchemy import select

from app.modules.saved_views.entities import finance_entity
from app.modules.saved_views.query_builder import SafeQueryBuilder
from app.modules.saved_views.schemas import (
    FilterCondition,
    FilterGroup,
    FilterSpec,
    SortSpec,
)


@pytest.fixture
def entity():
    return finance_entity.build_entity()


@pytest.fixture
def builder(entity):
    return SafeQueryBuilder(entity)


def _compile(stmt, *, literal: bool = True) -> str:
    return str(stmt.compile(compile_kwargs={"literal_binds": literal}))


def _build(builder, entity, spec):
    spec.bind(entity)
    return builder.build(select(entity.model), spec)


def test_eq_compiles_to_equality(builder, entity):
    spec = FilterSpec(where=FilterGroup(conditions=[FilterCondition(field="account_code", op="eq", value="330")]))
    sql = _compile(_build(builder, entity, spec)).lower()
    assert "account_code = '330'" in sql.replace('"', "")


def test_in_compiles_to_in(builder, entity):
    spec = FilterSpec(
        where=FilterGroup(conditions=[FilterCondition(field="account_code", op="in", value=["330", "440"])])
    )
    sql = _compile(_build(builder, entity, spec)).lower()
    assert " in (" in sql


def test_between_compiles_to_between(builder, entity):
    spec = FilterSpec(
        where=FilterGroup(
            conditions=[FilterCondition(field="posted_at", op="between", value=["2026-01-01", "2026-02-01"])]
        )
    )
    sql = _compile(_build(builder, entity, spec)).lower()
    assert "between" in sql


def test_is_null_compiles(builder, entity):
    spec = FilterSpec(where=FilterGroup(conditions=[FilterCondition(field="source_type", op="is_null")]))
    sql = _compile(_build(builder, entity, spec)).lower()
    assert "is null" in sql


def test_or_join_compiles_to_or(builder, entity):
    spec = FilterSpec(
        where=FilterGroup(
            join="or",
            conditions=[
                FilterCondition(field="account_code", op="eq", value="330"),
                FilterCondition(field="account_code", op="eq", value="440"),
            ],
        )
    )
    sql = _compile(_build(builder, entity, spec)).lower()
    assert " or " in sql


def test_bind_parameters_used_not_literal_interpolation(builder, entity):
    """With literal_binds off, the value appears as a bind param, not inline."""
    spec = FilterSpec(where=FilterGroup(conditions=[FilterCondition(field="account_code", op="eq", value="330")]))
    spec.bind(entity)
    stmt = builder.build(select(entity.model), spec)
    sql = _compile(stmt, literal=False)
    # The value 330 must not be inlined; a bind placeholder is used instead.
    assert "330" not in sql
    assert ":account_code" in sql.lower() or "%(account_code" in sql.lower()


def test_sort_applies_direction(builder, entity):
    spec = FilterSpec(sort=[SortSpec(field="posted_at", direction="desc")])
    sql = _compile(_build(builder, entity, spec)).lower()
    assert "order by" in sql and "desc" in sql


def test_default_sort_applied_when_none_given(builder, entity):
    spec = FilterSpec()
    sql = _compile(_build(builder, entity, spec)).lower()
    # finance default_sort is posted_at desc.
    assert "order by" in sql
    assert "posted_at" in sql


def test_group_by_compiles_to_group_and_count(builder, entity):
    spec = FilterSpec(group_by=["transaction_ref"])
    sql = _compile(_build(builder, entity, spec)).lower()
    assert "group by" in sql
    assert "count(" in sql


def test_distinct_compiles(builder, entity):
    spec = FilterSpec(distinct=True)
    sql = _compile(_build(builder, entity, spec)).lower()
    assert "distinct" in sql
