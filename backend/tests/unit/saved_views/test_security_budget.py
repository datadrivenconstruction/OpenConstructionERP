"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠SAFETY PRIMITIVE 3 - the result budget (pure unit, no DB).

Proves the hard row cap, the no-unlimited clamp, the static complexity ceiling
(refused BEFORE any database round-trip), the capped count path, and that a
statement-timeout surfaces as a 422-mappable BudgetError rather than a 500.
"""

from __future__ import annotations

import os

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://oe:oe@localhost:5432/openestimate")
os.environ.setdefault("DATABASE_SYNC_URL", "postgresql://oe:oe@localhost:5432/openestimate")

import uuid
from types import SimpleNamespace

import pytest

from app.modules.saved_views.entities import finance_entity
from app.modules.saved_views.errors import BudgetError
from app.modules.saved_views.query_builder import (
    GLOBAL_MAX_ROWS,
    MAX_COMPLEXITY,
    SafeQueryBuilder,
    assert_within_budget,
)
from app.modules.saved_views.schemas import FilterCondition, FilterGroup, FilterSpec
from app.modules.saved_views.scoper import ScopeContext
from app.modules.saved_views.service import SavedViewService
from tests.unit.saved_views._fixtures import SpySession


@pytest.fixture(autouse=True)
def _register_ledger_entity():
    """Ensure the ledger_entry entity is registered for service-level tests."""
    from app.modules.saved_views.registry import entity_registry

    if entity_registry.get("ledger_entry") is None:
        finance_entity.register()
    return


@pytest.fixture
def entity():
    return finance_entity.build_entity()


def _ctx() -> ScopeContext:
    return ScopeContext(
        user_id=uuid.uuid4(),
        role="editor",
        project_id=uuid.uuid4(),
        workspace_slug=None,
        is_admin=False,
    )


def test_row_cap_limits_query(entity):
    """The builder always appends a LIMIT of cap + 1 (the truncation sentinel)."""
    builder = SafeQueryBuilder(entity)
    spec = FilterSpec(page_size=50)
    from sqlalchemy import select

    stmt = builder.build(select(entity.model), spec)
    compiled = str(stmt.compile(compile_kwargs={"literal_binds": True}))
    # cap is min(50, entity.max_rows, GLOBAL_MAX_ROWS) -> 50; +1 sentinel -> 51.
    assert "LIMIT 51" in compiled.upper().replace("\n", " ")


def test_page_size_over_global_cap_clamps(entity):
    """A page_size above the global cap clamps down, never unbounded."""
    builder = SafeQueryBuilder(entity)
    assert builder.row_cap(10_000) == min(entity.max_rows, GLOBAL_MAX_ROWS)


def test_page_size_zero_clamps_not_unlimited(entity):
    """A non-positive page_size clamps to the entity default, never unbounded."""
    builder = SafeQueryBuilder(entity)
    assert builder.row_cap(0) == entity.default_page_size
    assert builder.row_cap(-5) == entity.default_page_size


def test_complexity_ceiling_rejects_pathological_spec(entity):
    """20 ORed filters + 2 group_bys exceeds MAX_COMPLEXITY -> BudgetError."""
    builder = SafeQueryBuilder(entity)
    spec = FilterSpec(
        where=FilterGroup(
            join="or",
            conditions=[FilterCondition(field="account_code", op="eq", value=str(i)) for i in range(15)],
        ),
        group_by=["transaction_ref"],
    )
    assert builder.estimate_cost(spec) > MAX_COMPLEXITY
    with pytest.raises(BudgetError):
        assert_within_budget(builder, spec)


@pytest.mark.asyncio
async def test_over_budget_spec_refused_before_any_db_hit(entity):
    """An over-budget spec is refused before execute() is ever called.

    The service runs against a SpySession whose ``execute`` raises if reached; a
    BudgetError must be raised first, proving the static gate short-circuits the
    round-trip.
    """
    spy = SpySession()
    service = SavedViewService(spy)  # type: ignore[arg-type]
    spec = FilterSpec(
        where=FilterGroup(conditions=[FilterCondition(field="account_code", op="eq", value=str(i)) for i in range(15)]),
        group_by=["transaction_ref"],
    )
    with pytest.raises(BudgetError):
        await service.run_adhoc("ledger_entry", spec, _ctx())
    # The spy never saw a real query (the audit row may be added, never executed).
    assert spy.executed == []


def test_count_path_is_capped(entity):
    """The count query wraps a row-capped subquery so it cannot scan unbounded."""
    builder = SafeQueryBuilder(entity)
    spec = FilterSpec(page_size=50)
    from sqlalchemy import select

    stmt = builder.build_count(select(entity.model), spec)
    compiled = str(stmt.compile(compile_kwargs={"literal_binds": True})).upper().replace("\n", " ")
    assert "COUNT" in compiled
    # The inner subquery carries the cap + 1 limit.
    assert "LIMIT 51" in compiled


@pytest.mark.asyncio
async def test_statement_timeout_yields_budget_error_not_500(entity):
    """A DB timeout during execution is normalised to a BudgetError (-> 422)."""

    class TimeoutSession(SpySession):
        def __init__(self) -> None:
            super().__init__()
            self.bind = SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))

        async def execute(self, stmt):  # noqa: ANN001, ANN201
            # Let the SET LOCAL statement_timeout pass, fail the real query.
            text_sql = str(getattr(stmt, "text", "")).lower()
            if "statement_timeout" in text_sql:
                return
            raise RuntimeError("canceling statement due to statement timeout")

    service = SavedViewService(TimeoutSession())  # type: ignore[arg-type]
    spec = FilterSpec(where=FilterGroup(conditions=[FilterCondition(field="account_code", op="eq", value="330")]))
    # Patch the scoper so we do not need a real project-access round-trip.
    from app.modules.saved_views import service as service_mod

    async def _fake_scoped_base(self_inner, entity_inner, ctx_inner):  # noqa: ANN001
        from sqlalchemy import select

        return select(entity_inner.model)

    original = service_mod.SavedViewService._scoped_base
    service_mod.SavedViewService._scoped_base = _fake_scoped_base  # type: ignore[assignment]
    try:
        with pytest.raises(BudgetError):
            await service.run_adhoc("ledger_entry", spec, _ctx())
    finally:
        service_mod.SavedViewService._scoped_base = original  # type: ignore[assignment]
