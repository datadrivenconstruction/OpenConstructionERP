# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Integration tests for the EAC v2 runner (EAC-1.4 / RFC 35 §1.6 / §1.7).

The runner wraps :func:`execute_rule` with the persistence envelope
that ``POST /rulesets/{id}:run`` and the Celery worker share. We
exercise the full path here against an in-memory SQLite session so
``EacRun`` and ``EacRunResultItem`` writes are observable.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Register EAC tables with Base.metadata.
import app.modules.eac.models  # noqa: F401
from app.database import Base
from app.modules.eac.engine.runner import (
    bim_element_to_canonical,
    dry_run_rule,
    run_ruleset,
)
from app.modules.eac.models import (
    EacRule,
    EacRuleset,
    EacRun,
    EacRunResultItem,
)


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)

    @event.listens_for(engine.sync_engine, "connect")
    def _enable_sqlite_fks(dbapi_conn, _conn_record) -> None:  # type: ignore[no-untyped-def]
        try:
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()
        except Exception:  # noqa: BLE001
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


# ── Helpers ────────────────────────────────────────────────────────────


def _walls_canonical() -> list[dict]:
    return [
        {
            "stable_id": "wall_001",
            "element_type": "Wall",
            "ifc_class": "IfcWall",
            "level": "Level 1",
            "discipline": "ARC",
            "properties": {"FireRating": "F90"},
            "quantities": {"area_m2": 25.0, "volume_m3": 6.0},
        },
        {
            "stable_id": "wall_002",
            "element_type": "Wall",
            "ifc_class": "IfcWall",
            "level": "Level 1",
            "discipline": "ARC",
            "properties": {"FireRating": "F30"},
            "quantities": {"area_m2": 12.5, "volume_m3": 3.0},
        },
    ]


async def _make_ruleset(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    rules: list[dict],
) -> EacRuleset:
    """Build a minimal EacRuleset with N rules and return it."""
    ruleset = EacRuleset(
        name="test_ruleset",
        kind="validation",
        tenant_id=tenant_id,
    )
    session.add(ruleset)
    await session.flush()
    for definition in rules:
        rule = EacRule(
            ruleset_id=ruleset.id,
            name=definition["name"],
            output_mode=definition["output_mode"],
            definition_json=definition,
            tenant_id=tenant_id,
        )
        session.add(rule)
    await session.flush()
    return ruleset


# ── Dry-run path ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_dry_run_returns_executor_result() -> None:
    body = {
        "schema_version": "2.0",
        "name": "F90_check",
        "output_mode": "boolean",
        "selector": {"kind": "category", "values": ["Wall"]},
        "predicate": {
            "kind": "triplet",
            "attribute": {"kind": "exact", "name": "FireRating"},
            "constraint": {"operator": "eq", "value": "F90"},
        },
    }
    result = await dry_run_rule(body, _walls_canonical())
    assert result.elements_matched == 2
    assert result.elements_passed == 1


@pytest.mark.asyncio
async def test_dry_run_rejects_malformed_definition() -> None:
    from app.modules.eac.engine.executor import ExecutionError

    bad = {"schema_version": "2.0", "name": "x", "output_mode": "bogus"}
    with pytest.raises(ExecutionError):
        await dry_run_rule(bad, [])


@pytest.mark.asyncio
async def test_dry_run_with_session_runs_semantic_validation(
    session: AsyncSession,
) -> None:
    """An alias_id that doesn't resolve must be rejected by the
    semantic validator — not just the executor's per-element fallback."""
    from app.modules.eac.engine.executor import ExecutionError

    body = {
        "schema_version": "2.0",
        "name": "bad_alias",
        "output_mode": "boolean",
        "selector": {"kind": "category", "values": ["Wall"]},
        "predicate": {
            "kind": "triplet",
            "attribute": {"kind": "alias", "alias_id": "alias_does_not_exist"},
            "constraint": {"operator": "exists"},
        },
    }
    with pytest.raises(ExecutionError, match="semantic"):
        await dry_run_rule(body, [], session=session, tenant_id=uuid.uuid4())


# ── Run-ruleset persistence ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_run_ruleset_persists_run_and_results(session: AsyncSession) -> None:
    tenant_id = uuid.uuid4()
    ruleset = await _make_ruleset(
        session,
        tenant_id=tenant_id,
        rules=[
            {
                "schema_version": "2.0",
                "name": "F90_check",
                "output_mode": "boolean",
                "selector": {"kind": "category", "values": ["Wall"]},
                "predicate": {
                    "kind": "triplet",
                    "attribute": {"kind": "exact", "name": "FireRating"},
                    "constraint": {"operator": "eq", "value": "F90"},
                },
            }
        ],
    )

    run = await run_ruleset(
        session=session,
        ruleset_id=ruleset.id,
        tenant_id=tenant_id,
        elements=_walls_canonical(),
    )

    assert run.status == "success"
    assert run.elements_evaluated == 2
    assert run.elements_matched == 2
    assert run.summary_json is not None
    assert len(run.summary_json["rules"]) == 1

    rows = (
        await session.scalars(
            select(EacRunResultItem).where(EacRunResultItem.run_id == run.id)
        )
    ).all()
    assert len(rows) == 2
    by_id = {r.element_id: r for r in rows}
    assert by_id["wall_001"].pass_ is True
    assert by_id["wall_002"].pass_ is False


@pytest.mark.asyncio
async def test_run_ruleset_aggregate_persists_synthetic_row(
    session: AsyncSession,
) -> None:
    tenant_id = uuid.uuid4()
    ruleset = await _make_ruleset(
        session,
        tenant_id=tenant_id,
        rules=[
            {
                "schema_version": "2.0",
                "name": "total_volume",
                "output_mode": "aggregate",
                "selector": {"kind": "category", "values": ["Wall"]},
                "formula": "SUM(volume_m3)",
                "result_unit": "m3",
            }
        ],
    )

    run = await run_ruleset(
        session=session,
        ruleset_id=ruleset.id,
        tenant_id=tenant_id,
        elements=_walls_canonical(),
    )

    assert run.status == "success"
    rows = (
        await session.scalars(
            select(EacRunResultItem).where(EacRunResultItem.run_id == run.id)
        )
    ).all()
    assert len(rows) == 1
    assert rows[0].element_id == "__aggregate__"
    assert rows[0].pass_ is None
    assert rows[0].result_value is not None
    assert rows[0].result_value["value"] == pytest.approx(9.0)
    assert rows[0].result_value["result_unit"] == "m3"


@pytest.mark.asyncio
async def test_run_ruleset_issue_mode_persists_failures(
    session: AsyncSession,
) -> None:
    tenant_id = uuid.uuid4()
    ruleset = await _make_ruleset(
        session,
        tenant_id=tenant_id,
        rules=[
            {
                "schema_version": "2.0",
                "name": "missing_F90",
                "output_mode": "issue",
                "selector": {"kind": "category", "values": ["Wall"]},
                "predicate": {
                    "kind": "triplet",
                    "attribute": {"kind": "exact", "name": "FireRating"},
                    "constraint": {"operator": "eq", "value": "F90"},
                },
                "issue_template": {
                    "title": "Wall {stable_id} not F90",
                    "topic_type": "issue",
                    "priority": "high",
                },
            }
        ],
    )

    run = await run_ruleset(
        session=session,
        ruleset_id=ruleset.id,
        tenant_id=tenant_id,
        elements=_walls_canonical(),
    )
    rows = (
        await session.scalars(
            select(EacRunResultItem).where(EacRunResultItem.run_id == run.id)
        )
    ).all()
    assert len(rows) == 1
    assert rows[0].element_id == "wall_002"
    assert rows[0].pass_ is False
    assert rows[0].result_value["title"] == "Wall wall_002 not F90"
    assert rows[0].result_value["priority"] == "high"


@pytest.mark.asyncio
async def test_run_ruleset_records_unsupported_clash(session: AsyncSession) -> None:
    tenant_id = uuid.uuid4()
    ruleset = await _make_ruleset(
        session,
        tenant_id=tenant_id,
        rules=[
            {
                "schema_version": "2.0",
                "name": "wall_door_clash",
                "output_mode": "clash",
                "selector": {"kind": "category", "values": ["Wall"]},
                "clash_config": {
                    "set_a": {"kind": "category", "values": ["Wall"]},
                    "set_b": {"kind": "category", "values": ["Door"]},
                    "method": "obb",
                    "test": "intersection_volume",
                },
            }
        ],
    )

    run = await run_ruleset(
        session=session,
        ruleset_id=ruleset.id,
        tenant_id=tenant_id,
        elements=_walls_canonical(),
    )
    # Clash is unsupported in MVP — the rule outcome carries the error,
    # but the run finishes (status=failed for an all-error run).
    assert run.status == "failed"
    assert run.error_count == 1
    assert run.summary_json["rules"][0]["error"] is not None


@pytest.mark.asyncio
async def test_run_ruleset_rejects_other_tenant(session: AsyncSession) -> None:
    from app.modules.eac.engine.executor import ExecutionError

    owner_tenant = uuid.uuid4()
    intruder_tenant = uuid.uuid4()
    ruleset = await _make_ruleset(
        session,
        tenant_id=owner_tenant,
        rules=[
            {
                "schema_version": "2.0",
                "name": "x",
                "output_mode": "boolean",
                "selector": {"kind": "category", "values": ["Wall"]},
            }
        ],
    )

    with pytest.raises(ExecutionError, match="tenant"):
        await run_ruleset(
            session=session,
            ruleset_id=ruleset.id,
            tenant_id=intruder_tenant,
            elements=_walls_canonical(),
        )


# ── BIM canonical adapter ─────────────────────────────────────────────


def test_bim_element_to_canonical_flattens_psets() -> None:
    class _FakeBIMElement:
        stable_id = "elem_1"
        element_type = "Wall"
        name = "Exterior Wall"
        storey = "Level 1"
        discipline = "ARC"
        properties = {
            "Pset_WallCommon": {"FireRating": "F90"},
            "ifc_class": "IfcWall",
            "groups": ["fireproof"],
        }
        quantities = {"area_m2": 12.0}

    out = bim_element_to_canonical(_FakeBIMElement())
    assert out["stable_id"] == "elem_1"
    assert out["element_type"] == "Wall"
    assert out["ifc_class"] == "IfcWall"
    assert out["level"] == "Level 1"
    # Both nested + flat shapes must be present so the resolver finds either.
    assert out["properties"]["Pset_WallCommon"] == {"FireRating": "F90"}
    assert out["properties"]["Pset_WallCommon.FireRating"] == "F90"
    assert out["groups"] == ["fireproof"]
    assert out["quantities"] == {"area_m2": 12.0}


def test_bim_element_to_canonical_handles_missing_fields() -> None:
    class _Sparse:
        stable_id = "elem_2"
        element_type = None
        name = None
        storey = None
        discipline = None
        properties = None
        quantities = None

    out = bim_element_to_canonical(_Sparse())
    assert out["stable_id"] == "elem_2"
    assert out["properties"] == {}
    assert out["quantities"] == {}
    assert out["classification"] == {}
