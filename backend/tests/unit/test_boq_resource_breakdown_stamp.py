# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Server-side canonical M/L/E rollup + the resource_split_mismatch rule.

The BOQ grid's Material/Labor/Equipment split columns read
``metadata.resource_breakdown`` as their fallback. Historically only the
assembly apply path and the demo seeder stamped it - positions created or
updated through the BOQ service carried ``metadata.resources`` but never the
rollup, so the columns went blank whenever the live resources array had no
usable totals. These tests pin:

* ``_stamp_resource_breakdown`` derives each resource's contribution from its
  ``total`` when present, else ``quantity * unit_rate`` (per-unit norm), and
  writes ``{type: {total, pct}}`` mirroring ``assemblies/service.py``.
* ``BOQService.add_position`` / ``update_position`` stamp the rollup whenever
  the metadata carries resources, and skip it when resources are absent.
* The new ``boq_quality.resource_split_mismatch`` WARNING rule flags positions
  whose per-unit resource subtotal drifts more than 5% from the unit rate.

DB isolation uses the shared PostgreSQL transactional session
(``tests._pg.transactional_session``); the rule tests are pure Python.

Run:
    cd backend
    python -m pytest tests/unit/test_boq_resource_breakdown_stamp.py -v --tb=short
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio

from app.core.validation.engine import Severity, ValidationContext
from app.core.validation.rules import ResourceSplitMismatch
from app.modules.boq.models import BOQ
from app.modules.boq.schemas import PositionCreate, PositionUpdate
from app.modules.boq.service import BOQService, _stamp_resource_breakdown
from app.modules.projects.models import Project
from tests._pg import transactional_session

OWNER_ID = uuid.uuid4()


# ── Pure helper: _stamp_resource_breakdown ─────────────────────────────────


def test_stamp_derives_total_from_quantity_times_rate() -> None:
    """Resources without a stored total contribute quantity * unit_rate."""
    meta = {
        "resources": [
            {"name": "Concrete", "type": "material", "quantity": 1.0, "unit_rate": 75.0},
            {"name": "Crew", "type": "labor", "quantity": 0.7, "unit_rate": 30.0},
            {"name": "Pump", "type": "equipment", "quantity": 0.1, "unit_rate": 40.0},
        ]
    }
    _stamp_resource_breakdown(meta)
    bd = meta["resource_breakdown"]
    assert bd["material"]["total"] == pytest.approx(75.0)
    assert bd["labor"]["total"] == pytest.approx(21.0)
    assert bd["equipment"]["total"] == pytest.approx(4.0)
    assert bd["material"]["pct"] == pytest.approx(75.0)
    assert bd["labor"]["pct"] == pytest.approx(21.0)
    assert bd["equipment"]["pct"] == pytest.approx(4.0)
    assert sum(v["pct"] for v in bd.values()) == pytest.approx(100.0)


def test_stamp_prefers_stored_total_and_coerces_strings() -> None:
    """A stored total (string-Decimal, Issue #131 shape) wins over qty*rate."""
    meta = {
        "resources": [
            {"type": "material", "quantity": 2, "unit_rate": 10, "total": "60.00"},
            {"type": "labor", "quantity": 1, "unit_rate": "40.00"},
        ]
    }
    _stamp_resource_breakdown(meta)
    bd = meta["resource_breakdown"]
    assert bd["material"]["total"] == pytest.approx(60.0)  # NOT 20 (qty*rate)
    assert bd["labor"]["total"] == pytest.approx(40.0)
    assert bd["material"]["pct"] == pytest.approx(60.0)


def test_stamp_skips_when_resources_absent_or_zero() -> None:
    """No resources / zero subtotal -> metadata untouched (no fake rollup)."""
    meta_none: dict = {"foo": "bar"}
    _stamp_resource_breakdown(meta_none)
    assert "resource_breakdown" not in meta_none

    meta_empty: dict = {"resources": []}
    _stamp_resource_breakdown(meta_empty)
    assert "resource_breakdown" not in meta_empty

    meta_zero: dict = {"resources": [{"type": "material", "quantity": 0, "unit_rate": 0}]}
    _stamp_resource_breakdown(meta_zero)
    assert "resource_breakdown" not in meta_zero


def test_stamp_pops_stale_rollup_on_early_return() -> None:
    """Audit m5: wiping resources must also wipe a previously stamped split.

    Without the pop, a position whose resources were removed (or zeroed)
    would keep serving the old M/L/E split to the grid forever.
    """
    stale = {"material": {"total": 75.0, "pct": 100.0}}

    meta_removed = {"resource_breakdown": dict(stale)}
    _stamp_resource_breakdown(meta_removed)
    assert "resource_breakdown" not in meta_removed

    meta_emptied = {"resources": [], "resource_breakdown": dict(stale)}
    _stamp_resource_breakdown(meta_emptied)
    assert "resource_breakdown" not in meta_emptied

    meta_zeroed = {
        "resources": [{"type": "material", "quantity": 0, "unit_rate": 0}],
        "resource_breakdown": dict(stale),
    }
    _stamp_resource_breakdown(meta_zeroed)
    assert "resource_breakdown" not in meta_zeroed


def test_stamp_buckets_unknown_type_as_other() -> None:
    meta = {
        "resources": [
            {"type": "material", "quantity": 1, "unit_rate": 50},
            {"quantity": 1, "unit_rate": 50},  # no type -> "other"
        ]
    }
    _stamp_resource_breakdown(meta)
    bd = meta["resource_breakdown"]
    assert bd["other"]["pct"] == pytest.approx(50.0)


# ── Service integration: add_position / update_position stamp ──────────────


@pytest_asyncio.fixture
async def session():
    async with transactional_session() as s:
        from app.modules.users.models import User

        s.add(
            User(
                id=OWNER_ID,
                email=f"rbd-{uuid.uuid4().hex[:6]}@test.io",
                hashed_password="x",
                full_name="Rollup Tester",
            )
        )
        await s.flush()
        await s.commit()
        yield s


async def _make_project_boq(session) -> uuid.UUID:
    project_id = uuid.uuid4()
    session.add(
        Project(
            id=project_id,
            name=f"RollupProj {uuid.uuid4().hex[:6]}",
            owner_id=OWNER_ID,
            currency="EUR",
        )
    )
    await session.flush()
    boq = BOQ(id=uuid.uuid4(), project_id=project_id, name="Rollup BOQ")
    session.add(boq)
    await session.commit()
    return boq.id


_RESOURCES = [
    {"name": "Concrete C30/37", "code": "", "type": "material", "unit": "m3", "quantity": 1.0, "unit_rate": 75.0},
    {"name": "Crew", "code": "", "type": "labor", "unit": "h", "quantity": 0.7, "unit_rate": 30.0},
    {"name": "Pump", "code": "", "type": "equipment", "unit": "h", "quantity": 0.1, "unit_rate": 40.0},
]


@pytest.mark.asyncio
async def test_add_position_stamps_resource_breakdown(session) -> None:
    boq_id = await _make_project_boq(session)
    service = BOQService(session)
    pos = await service.add_position(
        PositionCreate(
            boq_id=boq_id,
            ordinal="01.001",
            description="Concrete wall",
            unit="m3",
            quantity="10",
            unit_rate="100.00",
            source="manual",
            metadata={"resources": [dict(r) for r in _RESOURCES]},
        )
    )
    bd = pos.metadata_["resource_breakdown"]
    assert bd["material"]["pct"] == pytest.approx(75.0)
    assert bd["labor"]["pct"] == pytest.approx(21.0)
    assert bd["equipment"]["pct"] == pytest.approx(4.0)


@pytest.mark.asyncio
async def test_add_position_without_resources_does_not_stamp(session) -> None:
    boq_id = await _make_project_boq(session)
    service = BOQService(session)
    pos = await service.add_position(
        PositionCreate(
            boq_id=boq_id,
            ordinal="01.002",
            description="Plain manual position",
            unit="m2",
            quantity="5",
            unit_rate="20.00",
            source="manual",
            metadata={},
        )
    )
    assert "resource_breakdown" not in (pos.metadata_ or {})


@pytest.mark.asyncio
async def test_update_position_restamps_resource_breakdown(session) -> None:
    boq_id = await _make_project_boq(session)
    service = BOQService(session)
    pos = await service.add_position(
        PositionCreate(
            boq_id=boq_id,
            ordinal="01.003",
            description="Wall",
            unit="m3",
            quantity="10",
            unit_rate="100.00",
            source="manual",
            metadata={"resources": [dict(r) for r in _RESOURCES]},
        )
    )
    # Patch the resources: labor rate doubles -> rollup must follow.
    new_resources = [dict(r) for r in _RESOURCES]
    new_resources[1]["unit_rate"] = 60.0  # labor 0.7 * 60 = 42
    updated = await service.update_position(
        pos.id,
        PositionUpdate(metadata={"resources": new_resources}),
    )
    bd = updated.metadata_["resource_breakdown"]
    # New subtotal = 75 + 42 + 4 = 121
    assert bd["material"]["total"] == pytest.approx(75.0)
    assert bd["labor"]["total"] == pytest.approx(42.0)
    assert bd["material"]["pct"] == pytest.approx(75.0 / 121.0 * 100.0)
    assert bd["labor"]["pct"] == pytest.approx(42.0 / 121.0 * 100.0)


# ── Validation rule: boq_quality.resource_split_mismatch ───────────────────


def _ctx(positions: list[dict], locale: str = "en") -> ValidationContext:
    return ValidationContext(data={"positions": positions}, metadata={"locale": locale})


class TestResourceSplitMismatchRule:
    @pytest.mark.asyncio
    async def test_matching_subtotal_passes(self) -> None:
        rule = ResourceSplitMismatch()
        pos = {
            "id": "p1",
            "ordinal": "01.001",
            "unit": "m3",
            "unit_rate": 100.0,
            "metadata": {"resources": [{"type": "material", "quantity": 1, "unit_rate": 100}]},
        }
        results = await rule.validate(_ctx([pos]))
        assert len(results) == 1
        assert results[0].passed is True

    @pytest.mark.asyncio
    async def test_drift_within_five_percent_passes(self) -> None:
        rule = ResourceSplitMismatch()
        pos = {
            "id": "p1",
            "ordinal": "01.001",
            "unit": "m3",
            "unit_rate": 100.0,
            "metadata": {"resources": [{"type": "material", "quantity": 1, "unit_rate": 96}]},
        }
        results = await rule.validate(_ctx([pos]))
        assert len(results) == 1
        assert results[0].passed is True

    @pytest.mark.asyncio
    async def test_drift_beyond_five_percent_warns(self) -> None:
        rule = ResourceSplitMismatch()
        pos = {
            "id": "p1",
            "ordinal": "01.001",
            "unit": "m3",
            "unit_rate": 100.0,
            "metadata": {
                "resources": [
                    {"type": "material", "quantity": 1, "unit_rate": 50},
                    {"type": "labor", "total": "30.00"},
                ]
            },
        }
        results = await rule.validate(_ctx([pos]))
        assert len(results) == 1
        assert results[0].passed is False
        assert results[0].severity == Severity.WARNING
        assert results[0].details["resource_subtotal"] == pytest.approx(80.0)
        assert "01.001" in results[0].message

    @pytest.mark.asyncio
    async def test_positions_without_resources_are_skipped(self) -> None:
        rule = ResourceSplitMismatch()
        pos = {"id": "p1", "ordinal": "01.001", "unit": "m2", "unit_rate": 100.0, "metadata": {}}
        results = await rule.validate(_ctx([pos]))
        assert results == []

    @pytest.mark.asyncio
    async def test_zero_rate_positions_are_skipped(self) -> None:
        """Zero rates belong to position_has_unit_rate, not this rule."""
        rule = ResourceSplitMismatch()
        pos = {
            "id": "p1",
            "ordinal": "01.001",
            "unit": "m3",
            "unit_rate": 0,
            "metadata": {"resources": [{"type": "material", "quantity": 1, "unit_rate": 10}]},
        }
        results = await rule.validate(_ctx([pos]))
        assert results == []

    @pytest.mark.asyncio
    async def test_registered_in_boq_quality_rule_set(self) -> None:
        from app.core.validation.engine import rule_registry
        from app.core.validation.rules import register_builtin_rules

        register_builtin_rules()
        rules = rule_registry.get_rules_for_sets(["boq_quality"])
        assert any(r.rule_id == "boq_quality.resource_split_mismatch" for r in rules)
