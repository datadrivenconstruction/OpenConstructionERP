# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""CRUD round-trip tests for EAC v2 ORM models.

Uses an in-memory SQLite engine seeded with ``Base.metadata.create_all``
so we don't depend on Alembic infrastructure (which carries multiple
heads in this repo and would fight with parallel test agents).
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import event, select
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Importing the ORM module registers the EAC tables with Base.metadata.
import app.modules.eac.models  # noqa: F401
from app.database import Base
from app.modules.eac.models import (
    EacGlobalVariable,
    EacRule,
    EacRuleset,
    EacRuleVersion,
    EacRun,
    EacRunResultItem,
)


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    """Yield an isolated in-memory SQLite session per test.

    Enables ``PRAGMA foreign_keys=ON`` on every connection so cascade
    behaviours declared by FK clauses are actually enforced.
    """
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)

    @event.listens_for(engine.sync_engine, "connect")
    def _enable_sqlite_fks(dbapi_conn, _conn_record) -> None:  # type: ignore[no-untyped-def]
        try:
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()
        except Exception:  # noqa: BLE001 — non-SQLite drivers
            pass

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as sess:
        try:
            yield sess
        finally:
            await sess.close()
    await engine.dispose()


# ── Ruleset ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_and_query_ruleset(session: AsyncSession) -> None:
    tenant_id = uuid.uuid4()
    ruleset = EacRuleset(
        name="DACH residential",
        description="Test ruleset",
        kind="validation",
        tenant_id=tenant_id,
        tags=["dach", "residential"],
    )
    session.add(ruleset)
    await session.flush()

    fetched = await session.get(EacRuleset, ruleset.id)
    assert fetched is not None
    assert fetched.name == "DACH residential"
    assert fetched.kind == "validation"
    assert fetched.tags == ["dach", "residential"]
    assert fetched.is_template is False
    assert fetched.is_public_in_marketplace is False
    assert fetched.tenant_id == tenant_id


@pytest.mark.asyncio
async def test_ruleset_self_fk_cascades_set_null(session: AsyncSession) -> None:
    tenant_id = uuid.uuid4()
    parent = EacRuleset(name="parent", kind="mixed", tenant_id=tenant_id)
    session.add(parent)
    await session.flush()

    child = EacRuleset(
        name="child",
        kind="mixed",
        parent_ruleset_id=parent.id,
        tenant_id=tenant_id,
    )
    session.add(child)
    await session.flush()

    # Delete parent and confirm child remains with parent_ruleset_id=None.
    await session.delete(parent)
    await session.flush()

    # Expire the identity map so the child's parent_ruleset_id reflects
    # the DB-level cascade (SQLite mutates the column out-of-band of the
    # ORM session, so the cached copy still points at the parent).
    await session.refresh(child)
    assert child.parent_ruleset_id is None


# ── Rule ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_rule_with_definition_json(session: AsyncSession) -> None:
    tenant_id = uuid.uuid4()
    ruleset = EacRuleset(name="rs1", kind="validation", tenant_id=tenant_id)
    session.add(ruleset)
    await session.flush()

    definition = {
        "schema_version": "2.0",
        "name": "thickness_check",
        "output_mode": "boolean",
        "selector": {"kind": "category", "values": ["Walls"]},
        "predicate": {
            "kind": "triplet",
            "attribute": {"kind": "exact", "name": "Thickness"},
            "constraint": {"operator": "gte", "value": 100},
        },
    }

    rule = EacRule(
        ruleset_id=ruleset.id,
        name="thickness_check",
        output_mode="boolean",
        definition_json=definition,
        tags=["wall", "geometry"],
        tenant_id=tenant_id,
    )
    session.add(rule)
    await session.flush()

    fetched = await session.get(EacRule, rule.id)
    assert fetched is not None
    assert fetched.name == "thickness_check"
    assert fetched.output_mode == "boolean"
    assert fetched.definition_json == definition
    assert fetched.tags == ["wall", "geometry"]
    assert fetched.version == 1
    assert fetched.is_active is True


@pytest.mark.asyncio
async def test_rule_with_formula_and_unit(session: AsyncSession) -> None:
    tenant_id = uuid.uuid4()
    rule = EacRule(
        name="volume_total",
        output_mode="aggregate",
        definition_json={"schema_version": "2.0"},
        formula="SUM(Volume)",
        result_unit="m3",
        tenant_id=tenant_id,
    )
    session.add(rule)
    await session.flush()

    fetched = await session.get(EacRule, rule.id)
    assert fetched is not None
    assert fetched.formula == "SUM(Volume)"
    assert fetched.result_unit == "m3"


@pytest.mark.asyncio
async def test_list_rules_with_filters(session: AsyncSession) -> None:
    tenant_id = uuid.uuid4()
    project_id = uuid.uuid4()
    other_project_id = uuid.uuid4()

    keep = EacRule(
        name="keep",
        output_mode="boolean",
        tenant_id=tenant_id,
        project_id=project_id,
        is_active=True,
    )
    inactive = EacRule(
        name="inactive",
        output_mode="boolean",
        tenant_id=tenant_id,
        project_id=project_id,
        is_active=False,
    )
    other_project = EacRule(
        name="other",
        output_mode="boolean",
        tenant_id=tenant_id,
        project_id=other_project_id,
        is_active=True,
    )
    session.add_all([keep, inactive, other_project])
    await session.flush()

    stmt = select(EacRule).where(
        EacRule.tenant_id == tenant_id,
        EacRule.project_id == project_id,
        EacRule.is_active.is_(True),
    )
    result = await session.execute(stmt)
    rows = list(result.scalars().all())
    names = {r.name for r in rows}
    assert names == {"keep"}


@pytest.mark.asyncio
async def test_rule_version_history(session: AsyncSession) -> None:
    tenant_id = uuid.uuid4()
    rule = EacRule(
        name="v_history",
        output_mode="boolean",
        tenant_id=tenant_id,
        version=1,
    )
    session.add(rule)
    await session.flush()

    v1 = EacRuleVersion(
        rule_id=rule.id,
        version_number=1,
        definition_json={"step": 1},
        change_reason="initial",
        tenant_id=tenant_id,
    )
    v2 = EacRuleVersion(
        rule_id=rule.id,
        version_number=2,
        definition_json={"step": 2},
        change_reason="tighten threshold",
        tenant_id=tenant_id,
    )
    session.add_all([v1, v2])
    await session.flush()

    stmt = (
        select(EacRuleVersion)
        .where(EacRuleVersion.rule_id == rule.id)
        .order_by(EacRuleVersion.version_number)
    )
    result = await session.execute(stmt)
    rows = list(result.scalars().all())
    assert [r.version_number for r in rows] == [1, 2]
    assert rows[1].change_reason == "tighten threshold"


# ── Run + result items ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_run_and_result_items_cascade(session: AsyncSession) -> None:
    tenant_id = uuid.uuid4()
    ruleset = EacRuleset(name="rs", kind="validation", tenant_id=tenant_id)
    session.add(ruleset)
    await session.flush()

    rule = EacRule(
        name="r",
        output_mode="boolean",
        tenant_id=tenant_id,
        ruleset_id=ruleset.id,
    )
    session.add(rule)
    await session.flush()

    run = EacRun(
        ruleset_id=ruleset.id,
        status="success",
        elements_evaluated=2,
        elements_matched=1,
        triggered_by="manual",
        tenant_id=tenant_id,
    )
    session.add(run)
    await session.flush()

    item_pass = EacRunResultItem(
        run_id=run.id,
        rule_id=rule.id,
        element_id="elem_001",
        pass_=True,
        attribute_snapshot={"Thickness": 200},
        tenant_id=tenant_id,
    )
    item_fail = EacRunResultItem(
        run_id=run.id,
        rule_id=rule.id,
        element_id="elem_002",
        pass_=False,
        attribute_snapshot={"Thickness": 50},
        error=None,
        tenant_id=tenant_id,
    )
    session.add_all([item_pass, item_fail])
    await session.flush()

    # Delete the run and confirm result items cascade away.
    await session.delete(run)
    await session.flush()

    stmt = select(EacRunResultItem).where(EacRunResultItem.run_id == run.id)
    leftover = (await session.execute(stmt)).scalars().all()
    assert leftover == []


# ── Global variable ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_global_variable_uniqueness(session: AsyncSession) -> None:
    tenant_id = uuid.uuid4()
    org_id = uuid.uuid4()

    var1 = EacGlobalVariable(
        scope="org",
        scope_id=org_id,
        name="MIN_THICKNESS",
        value_type="number",
        value_json={"value": 100},
        tenant_id=tenant_id,
    )
    session.add(var1)
    await session.flush()

    # Same (scope, scope_id, name) → unique constraint violation
    duplicate = EacGlobalVariable(
        scope="org",
        scope_id=org_id,
        name="MIN_THICKNESS",
        value_type="number",
        value_json={"value": 200},
        tenant_id=tenant_id,
    )
    session.add(duplicate)
    with pytest.raises(Exception) as excinfo:
        await session.flush()
    # SQLAlchemy wraps as IntegrityError; we don't pin the specific class
    # so the test is portable across drivers.
    assert "UNIQUE" in str(excinfo.value).upper() or "UNIQUE" in repr(excinfo.value).upper()


@pytest.mark.asyncio
async def test_global_variable_supports_value_types(session: AsyncSession) -> None:
    tenant_id = uuid.uuid4()
    proj_id = uuid.uuid4()

    rows = [
        EacGlobalVariable(
            scope="project",
            scope_id=proj_id,
            name="MIN_THICKNESS_MM",
            value_type="number",
            value_json={"value": 100},
            tenant_id=tenant_id,
        ),
        EacGlobalVariable(
            scope="project",
            scope_id=proj_id,
            name="DEFAULT_REGION",
            value_type="string",
            value_json={"value": "Berlin"},
            tenant_id=tenant_id,
        ),
        EacGlobalVariable(
            scope="project",
            scope_id=proj_id,
            name="USE_METRIC",
            value_type="boolean",
            value_json={"value": True},
            tenant_id=tenant_id,
        ),
        EacGlobalVariable(
            scope="project",
            scope_id=proj_id,
            name="DEADLINE",
            value_type="date",
            value_json={"value": "2026-12-31"},
            tenant_id=tenant_id,
        ),
    ]
    session.add_all(rows)
    await session.flush()

    stmt = select(EacGlobalVariable).where(EacGlobalVariable.scope_id == proj_id)
    result = await session.execute(stmt)
    fetched = {row.name: row.value_json["value"] for row in result.scalars().all()}
    assert fetched == {
        "MIN_THICKNESS_MM": 100,
        "DEFAULT_REGION": "Berlin",
        "USE_METRIC": True,
        "DEADLINE": "2026-12-31",
    }


# ── Cross-table sanity ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_full_workflow_create_query_update(session: AsyncSession) -> None:
    """Smoke: ruleset → rule → version → run → result item, end-to-end."""
    tenant_id = uuid.uuid4()
    ruleset = EacRuleset(name="full", kind="validation", tenant_id=tenant_id)
    session.add(ruleset)
    await session.flush()

    rule = EacRule(
        name="full_rule",
        ruleset_id=ruleset.id,
        output_mode="boolean",
        definition_json={"selector": {"kind": "category", "values": ["Walls"]}},
        tenant_id=tenant_id,
    )
    session.add(rule)
    await session.flush()

    run = EacRun(
        ruleset_id=ruleset.id,
        status="success",
        elements_evaluated=10,
        elements_matched=8,
        tenant_id=tenant_id,
    )
    session.add(run)
    await session.flush()

    items = [
        EacRunResultItem(
            run_id=run.id,
            rule_id=rule.id,
            element_id=f"elem_{i:03d}",
            pass_=i % 2 == 0,
            tenant_id=tenant_id,
        )
        for i in range(5)
    ]
    session.add_all(items)
    await session.flush()

    # Query a slice of result items for this run + rule.
    stmt = select(EacRunResultItem).where(
        EacRunResultItem.run_id == run.id,
        EacRunResultItem.rule_id == rule.id,
    )
    result = await session.execute(stmt)
    rows = list(result.scalars().all())
    assert len(rows) == 5
    assert sum(1 for r in rows if r.pass_) == 3  # 0, 2, 4
