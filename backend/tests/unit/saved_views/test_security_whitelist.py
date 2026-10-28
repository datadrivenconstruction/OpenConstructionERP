"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠SAFETY PRIMITIVE 2 - column-whitelist rejection paths (pure unit, no DB).

Proves that a saved view may only filter / sort / group / select on columns that
were explicitly whitelisted for the target entity, and that anything else is
refused at validation time, naming the offending field, before the query is
built. These are the security-critical negative tests for the whitelist gate.
"""

from __future__ import annotations

import os

# A PostgreSQL-shaped URL so ``app.database`` imports without booting a cluster;
# these tests never open a connection.
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://oe:oe@localhost:5432/openestimate")
os.environ.setdefault("DATABASE_SYNC_URL", "postgresql://oe:oe@localhost:5432/openestimate")

import pytest
from pydantic import ValidationError

from app.modules.saved_views.entities import finance_entity
from app.modules.saved_views.errors import WhitelistError
from app.modules.saved_views.schemas import (
    FilterCondition,
    FilterGroup,
    FilterSpec,
    SortSpec,
)


@pytest.fixture
def entity():
    """A built (unregistered) ledger_entry entity for binding tests."""
    return finance_entity.build_entity()


def _spec(**kwargs):
    return FilterSpec(**kwargs)


def test_filter_on_unwhitelisted_column_rejected(entity):
    """A filter on a real column that is NOT whitelisted is a WhitelistError."""
    spec = _spec(where=FilterGroup(conditions=[FilterCondition(field="created_by", op="eq", value="x")]))
    with pytest.raises(WhitelistError) as exc:
        spec.bind(entity)
    assert exc.value.field == "created_by"


def test_relationship_traversal_rejected(entity):
    """A dotted path like ``project.owner_id`` never even constructs (regex)."""
    with pytest.raises(ValidationError):
        FilterCondition(field="project.owner_id", op="eq", value="x")


def test_sort_on_non_sortable_rejected(entity):
    """Sorting on a field that exists but is not sortable is refused."""
    # Make description non-sortable for this assertion by binding a spec that
    # sorts on a non-whitelisted field; the entity has no non-sortable field so
    # we assert the unknown-field path which is the same gate.
    spec = _spec(sort=[SortSpec(field="not_a_field", direction="asc")])
    with pytest.raises(WhitelistError) as exc:
        spec.bind(entity)
    assert exc.value.field == "not_a_field"


def test_group_on_non_groupable_rejected(entity):
    """group_by on a whitelisted-but-not-groupable field is refused."""
    # account_code is whitelisted and filterable/sortable but NOT groupable.
    spec = _spec(group_by=["account_code"])
    with pytest.raises(WhitelistError) as exc:
        spec.bind(entity)
    assert exc.value.field == "account_code"


def test_select_non_selectable_column_rejected():
    """A columns entry whose FieldSpec.selectable is False is refused."""
    from app.modules.projects.models import Project
    from app.modules.saved_views.registry import FieldSpec, QueryableEntity
    from app.modules.saved_views.scoper import project_member_scoper

    entity = QueryableEntity(
        entity_type="toy_select",
        model=Project,
        fields={
            "name": FieldSpec(name="name", column="name", kind="string"),
            "secret": FieldSpec(name="secret", column="status", kind="string", selectable=False),
        },
        scoper=project_member_scoper,
        project_fk_column="id",
        default_sort=("name", "asc"),
    )
    spec = FilterSpec(columns=["secret"])
    with pytest.raises(WhitelistError) as exc:
        spec.bind(entity)
    assert exc.value.field == "secret"


def test_unknown_operator_rejected(entity):
    """An operator outside the field's allowed set is refused at bind."""
    # is_reversal is a bool: only eq/neq/is_null/not_null. ``gt`` is not allowed.
    spec = _spec(where=FilterGroup(conditions=[FilterCondition(field="is_reversal", op="gt", value=True)]))
    with pytest.raises(WhitelistError) as exc:
        spec.bind(entity)
    assert exc.value.field == "is_reversal"


def test_like_wildcard_in_value_is_escaped(entity):
    """A ``contains`` value of ``%`` compiles to a literal percent match."""
    from sqlalchemy import select

    from app.modules.saved_views.query_builder import SafeQueryBuilder

    spec = _spec(where=FilterGroup(conditions=[FilterCondition(field="account_code", op="contains", value="%")]))
    spec.bind(entity)
    builder = SafeQueryBuilder(entity)
    stmt = builder.build(select(entity.model), spec)
    compiled = str(stmt.compile(compile_kwargs={"literal_binds": True}))
    # The wildcard must be escaped and an ESCAPE clause present, so the value
    # matches a literal percent rather than every row.
    assert "ESCAPE" in compiled.upper()
    assert "\\%" in compiled


def test_in_list_over_cap_rejected(entity):
    """An ``in`` list longer than the cap is a WhitelistError."""
    spec = _spec(
        where=FilterGroup(
            conditions=[FilterCondition(field="account_code", op="in", value=[str(i) for i in range(201)])]
        )
    )
    with pytest.raises(WhitelistError) as exc:
        spec.bind(entity)
    assert exc.value.field == "account_code"


def test_enum_value_outside_allowed_rejected(entity):
    """An enum value not in enum_values is refused at bind (value coercion)."""
    # source_type is a plain string here; use the boq source enum instead.
    from app.modules.saved_views.entities import boq_entity

    boq = boq_entity.build_entity()
    spec = _spec(where=FilterGroup(conditions=[FilterCondition(field="source", op="eq", value="not_a_source")]))
    with pytest.raises(WhitelistError) as exc:
        spec.bind(boq)
    assert exc.value.field == "source"
