# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""An edit must not re-price a position from resource rows that are not per-unit norms.

``BOQService.update_position`` re-derives ``unit_rate`` as ``sum(quantity *
unit_rate)`` over the resources whenever the incoming list differs from the
stored one. That is right for every hand-entered buildup, where ``quantity`` is
per one unit of the position. The AI estimator stores rows whose quantity is
``factor * position_quantity``, and its fallback stores allowance rows whose
quantity is the position quantity itself; positions booked before the estimator
read the catalogue norm hold the position quantity on every row. On those the
derivation faithfully summed numbers of the wrong size and overwrote a correct
rate with roughly quantity times the correct value, on an ordinary edit that
nobody audits.

These tests pin the guard: the stored rate stands, the position is stamped and
gets a warning, and a buildup that IS per-unit still re-derives exactly as
before. The rule tests pin that the stamp and the estimator's own flags reach
the validation report.

Isolation mirrors ``test_boq_resourceless_unit_rate``: each DB test runs inside
a rolled-back outer transaction via ``tests._pg``.

Run:
    cd backend
    python -m pytest tests/unit/test_boq_unit_rate_survives_untrusted_resources.py -v --tb=short
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

import pytest
import pytest_asyncio

from app.core.validation.engine import Severity, ValidationContext, rule_registry
from app.modules.boq.resource_norms import (
    AI_ESTIMATOR_SOURCE,
    CATEGORY_ASSUMED_NORM,
    CATEGORY_FALLBACK_ALLOWANCE,
    CATEGORY_WHOLE_POSITION_QUANTITIES,
    UNIT_RATE_KEPT_KEY,
    UNIT_RATE_KEPT_WARNING_PREFIX,
    clear_unit_rate_kept,
    resource_subtotal,
    stamp_unit_rate_kept,
    untrusted_buildup_reason,
)
from app.modules.boq.schemas import PositionUpdate
from app.modules.boq.service import BOQService
from app.modules.boq.validators import UnitRateNotRederivedFromUntrustedBuildup
from tests._pg import transactional_session

OWNER_ID = uuid.uuid4()


# ── Pure predicate ───────────────────────────────────────────────────────────


def _fallback_rows(position_qty: float, rate: float) -> list[dict[str, Any]]:
    """Exactly what ``_ensure_resources`` writes when the catalogue has no components."""
    return [
        {
            "name": "Labor allowance",
            "code": "",
            "unit": "m3",
            "type": "labor",
            "factor": 1.0,
            "unit_rate": f"{rate * 0.4:f}",
            "quantity": position_qty,
            "estimated": True,
        },
        {
            "name": "Material allowance",
            "code": "",
            "unit": "m3",
            "type": "material",
            "factor": 1.0,
            "unit_rate": f"{rate * 0.6:f}",
            "quantity": position_qty,
            "estimated": True,
        },
    ]


def test_fallback_allowance_rows_are_untrusted_whatever_the_source() -> None:
    reason = untrusted_buildup_reason(
        source="manual", metadata={}, quantity="250", resources=_fallback_rows(250.0, 40.0)
    )
    assert reason == CATEGORY_FALLBACK_ALLOWANCE


def test_a_per_unit_allowance_is_trusted_the_flag_alone_says_nothing_about_size() -> None:
    """The flagship seeder writes allowance rows at quantity one; their sum IS the unit rate."""
    rows = [
        {
            "name": "Labor allowance",
            "type": "labor",
            "unit": "ls",
            "quantity": 1.0,
            "unit_rate": "14.00",
            "estimated": True,
        },
        {
            "name": "Material allowance",
            "type": "material",
            "unit": "ls",
            "quantity": 1.0,
            "unit_rate": "26.00",
            "estimated": True,
        },
    ]
    assert untrusted_buildup_reason(source="manual", metadata={}, quantity=250, resources=rows) is None


def test_an_allowance_at_position_quantity_one_has_nothing_at_stake() -> None:
    rows = _fallback_rows(1.0, 40.0)
    assert untrusted_buildup_reason(source=AI_ESTIMATOR_SOURCE, metadata={}, quantity=1, resources=rows) is None


def test_a_row_with_an_assumed_norm_is_untrusted() -> None:
    rows = [{"factor": 1.0, "quantity": 12.0, "unit_rate": "42", "factor_estimated": True}]
    assert untrusted_buildup_reason(source="manual", metadata={}, quantity=12, resources=rows) == CATEGORY_ASSUMED_NORM


@pytest.mark.parametrize(
    ("factor", "quantity"),
    [
        (1.0, 12.0),  # pre-fix: the norm collapsed to one, the row holds the position quantity
        (0.85, 10.2),  # post-fix: the norm survived and was multiplied by the position quantity
    ],
)
def test_estimator_rows_holding_whole_position_quantities_are_untrusted(factor: float, quantity: float) -> None:
    rows = [{"name": "Bricklayer", "factor": factor, "quantity": quantity, "unit_rate": "42.00", "type": "labor"}]
    reason = untrusted_buildup_reason(source=AI_ESTIMATOR_SOURCE, metadata={}, quantity="12", resources=rows)
    assert reason == CATEGORY_WHOLE_POSITION_QUANTITIES


def test_the_run_id_identifies_an_estimator_position_when_the_source_was_overwritten() -> None:
    rows = [{"factor": 1.0, "quantity": 12.0, "unit_rate": "42.00"}]
    meta = {"ai_estimator_run_id": str(uuid.uuid4())}
    assert untrusted_buildup_reason(source="manual", metadata=meta, quantity=12, resources=rows) is not None


def test_a_position_quantity_of_one_makes_the_total_and_the_norm_coincide() -> None:
    """With quantity one the sum is right either way, so nothing is blocked."""
    rows = [{"factor": 0.85, "quantity": 0.85, "unit_rate": "42.00"}]
    assert untrusted_buildup_reason(source=AI_ESTIMATOR_SOURCE, metadata={}, quantity=1, resources=rows) is None


def test_per_unit_rows_on_an_estimator_position_are_trusted() -> None:
    """The shape the review path writes back: quantity is the norm, not the total."""
    rows = [{"factor": 0.85, "quantity": 0.85, "unit_rate": "42.00"}, {"factor": 58.0, "quantity": 58.0}]
    assert untrusted_buildup_reason(source=AI_ESTIMATOR_SOURCE, metadata={}, quantity=12, resources=rows) is None


def test_a_hand_entered_row_never_matches_even_when_its_quantity_equals_the_position_quantity() -> None:
    """No ``factor`` key, no estimator source: an estimator's shape is not inferred from a number."""
    rows = [{"name": "Concrete", "quantity": 12.0, "unit_rate": "90"}]
    assert untrusted_buildup_reason(source="manual", metadata={}, quantity=12, resources=rows) is None
    assert untrusted_buildup_reason(source=AI_ESTIMATOR_SOURCE, metadata={}, quantity=12, resources=rows) is None


def test_nothing_to_judge_is_trusted() -> None:
    assert untrusted_buildup_reason(source=AI_ESTIMATOR_SOURCE, metadata={}, quantity=12, resources=None) is None
    assert untrusted_buildup_reason(source=AI_ESTIMATOR_SOURCE, metadata={}, quantity=12, resources=[]) is None
    assert untrusted_buildup_reason(source=AI_ESTIMATOR_SOURCE, metadata={}, quantity=12, resources="x") is None


def test_the_stamp_and_its_marker_are_written_once_and_cleared_together() -> None:
    meta: dict[str, Any] = {"boq_quality_warnings": ["Duplicate content: something"]}
    stamp_unit_rate_kept(meta, reason=CATEGORY_FALLBACK_ALLOWANCE, unit_rate="40")
    stamp_unit_rate_kept(meta, reason=CATEGORY_FALLBACK_ALLOWANCE, unit_rate="40")
    markers = [w for w in meta["boq_quality_warnings"] if w.startswith(UNIT_RATE_KEPT_WARNING_PREFIX)]
    assert len(markers) == 1, "a second blocked edit must replace the marker, not stack it"
    assert meta[UNIT_RATE_KEPT_KEY]["kept_unit_rate"] == "40"
    assert clear_unit_rate_kept(meta) is True
    assert UNIT_RATE_KEPT_KEY not in meta
    assert meta["boq_quality_warnings"] == ["Duplicate content: something"], "a foreign warning survives the clear"
    assert clear_unit_rate_kept(meta) is False


# ── DB: the guard inside update_position ─────────────────────────────────────


@pytest_asyncio.fixture
async def session():
    async with transactional_session() as s:
        from app.modules.users.models import User

        s.add(
            User(
                id=OWNER_ID,
                email=f"o-{uuid.uuid4().hex[:6]}@test.io",
                hashed_password="x",
                full_name="O",
            )
        )
        await s.flush()
        await s.commit()
        yield s


async def _make_position(
    session,
    *,
    unit_rate: str,
    quantity: str,
    metadata_: dict[str, Any],
    source: str = "manual",
):
    """Create Project + BOQ + one leaf Position; return (service, position)."""
    from app.modules.boq.models import BOQ, Position
    from app.modules.projects.models import Project

    project_id = uuid.uuid4()
    session.add(Project(id=project_id, name="P", owner_id=OWNER_ID, currency="EUR"))
    await session.flush()
    boq = BOQ(id=uuid.uuid4(), project_id=project_id, name="B")
    session.add(boq)
    await session.flush()
    pos = Position(
        id=uuid.uuid4(),
        boq_id=boq.id,
        ordinal="0010",
        description="p",
        unit="m3",
        quantity=quantity,
        unit_rate=unit_rate,
        total=str(Decimal(quantity) * Decimal(unit_rate)),
        source=source,
        metadata_=metadata_,
        sort_order=10,
    )
    session.add(pos)
    await session.commit()
    return BOQService(session), pos


def _edited(rows: list[dict[str, Any]], index: int, **changes: Any) -> list[dict[str, Any]]:
    out = [dict(r) for r in rows]
    out[index].update(changes)
    return out


@pytest.mark.asyncio
async def test_a_pre_fix_fallback_position_keeps_its_unit_rate_through_an_edit(session) -> None:
    """The defect, verbatim: 250 units at 40, one resource price edited.

    Before the guard the derivation wrote ``sum(250 * rate)``, two orders of
    magnitude into the contract sum. The rate must stand and the position must
    say why.
    """
    rows = _fallback_rows(250.0, 40.0)
    service, pos = await _make_position(
        session,
        unit_rate="40",
        quantity="250",
        source=AI_ESTIMATOR_SOURCE,
        metadata_={"ai_estimator_run_id": str(uuid.uuid4()), "resources": rows},
    )
    edited = _edited(rows, 0, unit_rate="17.000000")
    would_have_written = resource_subtotal(edited)
    assert would_have_written > Decimal("10000"), "the counterfactual is the overwrite the guard prevents"

    updated = await service.update_position(pos.id, PositionUpdate(metadata={"resources": edited}), actor_id=OWNER_ID)

    assert Decimal(str(updated.unit_rate)) == Decimal("40")
    assert Decimal(str(updated.total)) == Decimal("10000")
    stamp = updated.metadata_[UNIT_RATE_KEPT_KEY]
    assert stamp["reason"] == CATEGORY_FALLBACK_ALLOWANCE
    assert Decimal(stamp["kept_unit_rate"]) == Decimal("40")
    assert any(w.startswith(UNIT_RATE_KEPT_WARNING_PREFIX) for w in updated.metadata_["boq_quality_warnings"])
    assert updated.validation_status == "warnings"
    assert updated.metadata_["resources"][0]["unit_rate"] == "17.000000", "the edit itself is still stored"


@pytest.mark.asyncio
async def test_a_pre_fix_linked_position_keeps_its_unit_rate_through_an_edit(session) -> None:
    """Catalogue-linked rows whose norm collapsed to one carry no flag; the shape is the signal."""
    rows = [
        {
            "name": "Bricklayer",
            "code": "L1",
            "unit": "h",
            "type": "labor",
            "factor": 1.0,
            "quantity": 12.0,
            "unit_rate": "42.00",
        },
        {
            "name": "Brick",
            "code": "M1",
            "unit": "pcs",
            "type": "material",
            "factor": 1.0,
            "quantity": 12.0,
            "unit_rate": "0.55",
        },
    ]
    service, pos = await _make_position(
        session,
        unit_rate="67.6",
        quantity="12",
        source=AI_ESTIMATOR_SOURCE,
        metadata_={"cost_item_id": str(uuid.uuid4()), "resources": rows},
    )

    updated = await service.update_position(
        pos.id,
        PositionUpdate(
            metadata={"cost_item_id": pos.metadata_["cost_item_id"], "resources": _edited(rows, 0, unit_rate="45.00")}
        ),
        actor_id=OWNER_ID,
    )

    assert Decimal(str(updated.unit_rate)) == Decimal("67.6")
    assert updated.metadata_[UNIT_RATE_KEPT_KEY]["reason"] == CATEGORY_WHOLE_POSITION_QUANTITIES


@pytest.mark.asyncio
async def test_a_hand_entered_per_unit_buildup_still_re_derives(session) -> None:
    """The control: the guard must not touch the behaviour every manual bill relies on."""
    service, pos = await _make_position(
        session,
        unit_rate="50",
        quantity="2",
        metadata_={
            "resources": [{"name": "Concrete", "type": "material", "unit": "m3", "quantity": 1, "unit_rate": 50}]
        },
    )

    updated = await service.update_position(
        pos.id,
        PositionUpdate(
            metadata={
                "resources": [
                    {"name": "Concrete", "type": "material", "unit": "m3", "quantity": 2, "unit_rate": 10},
                    {"name": "Crew", "type": "labor", "unit": "h", "quantity": 1, "unit_rate": 5},
                ]
            }
        ),
        actor_id=OWNER_ID,
    )

    assert Decimal(str(updated.unit_rate)) == Decimal("25")
    assert Decimal(str(updated.total)) == Decimal("50")
    assert UNIT_RATE_KEPT_KEY not in (updated.metadata_ or {})


@pytest.mark.asyncio
async def test_an_estimator_position_healed_to_per_unit_norms_re_derives_correctly(session) -> None:
    """The shape the review path writes back must price the line like any other buildup."""
    rows = [
        {"name": "Bricklayer", "type": "labor", "unit": "h", "factor": 0.85, "quantity": 0.85, "unit_rate": "42.00"}
    ]
    service, pos = await _make_position(
        session,
        unit_rate="35.7",
        quantity="12",
        source=AI_ESTIMATOR_SOURCE,
        metadata_={"cost_item_id": str(uuid.uuid4()), "resources": rows},
    )

    updated = await service.update_position(
        pos.id,
        PositionUpdate(
            metadata={"cost_item_id": pos.metadata_["cost_item_id"], "resources": _edited(rows, 0, unit_rate="45.00")}
        ),
        actor_id=OWNER_ID,
    )

    assert Decimal(str(updated.unit_rate)) == Decimal("38.25")  # 0.85 * 45, per unit
    assert Decimal(str(updated.total)) == Decimal("459")  # 12 * 38.25
    assert UNIT_RATE_KEPT_KEY not in updated.metadata_


@pytest.mark.asyncio
async def test_a_trusted_edit_clears_a_stale_stamp(session) -> None:
    """Once the rows can price the line again the warning must not linger."""
    meta: dict[str, Any] = {"resources": [{"name": "Concrete", "type": "material", "quantity": 1, "unit_rate": 50}]}
    stamp_unit_rate_kept(meta, reason=CATEGORY_FALLBACK_ALLOWANCE, unit_rate="50")
    service, pos = await _make_position(session, unit_rate="50", quantity="2", metadata_=meta)

    updated = await service.update_position(
        pos.id,
        PositionUpdate(
            metadata={
                **meta,
                "resources": [{"name": "Concrete", "type": "material", "quantity": 1, "unit_rate": 60}],
            }
        ),
        actor_id=OWNER_ID,
    )

    assert Decimal(str(updated.unit_rate)) == Decimal("60")
    assert UNIT_RATE_KEPT_KEY not in updated.metadata_
    assert "boq_quality_warnings" not in updated.metadata_


# ── The validation rule ──────────────────────────────────────────────────────


def _context(positions: list[dict[str, Any]]) -> ValidationContext:
    return ValidationContext(data={"positions": positions}, metadata={"locale": "en"})


def _position(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": str(uuid.uuid4()),
        "parent_id": None,
        "ordinal": "0010",
        "description": "p",
        "unit": "m3",
        "quantity": 12.0,
        "unit_rate": 40.0,
        "total": 480.0,
        "type": "position",
        "source": "manual",
        "metadata": {},
    }
    base.update(overrides)
    return base


@pytest.mark.asyncio
async def test_the_rule_carries_the_stamp_into_the_report() -> None:
    meta: dict[str, Any] = {"resources": _fallback_rows(12.0, 40.0)}
    stamp_unit_rate_kept(meta, reason=CATEGORY_FALLBACK_ALLOWANCE, unit_rate="40")
    results = await UnitRateNotRederivedFromUntrustedBuildup().validate(_context([_position(metadata=meta)]))

    assert len(results) == 1
    (result,) = results
    assert result.passed is False
    assert result.severity is Severity.WARNING
    assert result.details["reason"] == CATEGORY_FALLBACK_ALLOWANCE
    assert result.details["kept_unit_rate"] == "40"
    assert result.details["stamped_by_edit"] is True
    assert "0010" in result.message


@pytest.mark.asyncio
async def test_the_rule_surfaces_the_estimators_own_flags_before_any_edit() -> None:
    flagged = _position(
        metadata={"resources": [{"factor": 1.0, "quantity": 12.0, "unit_rate": "1", "factor_estimated": True}]}
    )
    results = await UnitRateNotRederivedFromUntrustedBuildup().validate(_context([flagged]))

    assert [r.details["reason"] for r in results] == [CATEGORY_ASSUMED_NORM]
    assert results[0].details["stamped_by_edit"] is False


@pytest.mark.asyncio
async def test_the_rule_and_the_guard_judge_a_position_by_the_same_predicate() -> None:
    """An estimator position holding whole-position quantities is reported before any edit."""
    rows = [{"name": "Bricklayer", "type": "labor", "factor": 0.85, "quantity": 10.2, "unit_rate": "42.00"}]
    stored = _position(source=AI_ESTIMATOR_SOURCE, metadata={"resources": rows})
    results = await UnitRateNotRederivedFromUntrustedBuildup().validate(_context([stored]))

    assert [r.details["reason"] for r in results] == [CATEGORY_WHOLE_POSITION_QUANTITIES]
    assert (
        untrusted_buildup_reason(
            source=stored["source"], metadata=stored["metadata"], quantity=stored["quantity"], resources=rows
        )
        == CATEGORY_WHOLE_POSITION_QUANTITIES
    )


@pytest.mark.asyncio
async def test_the_rule_is_silent_on_a_per_unit_buildup_and_on_sections() -> None:
    clean = _position(metadata={"resources": [{"quantity": 0.85, "unit_rate": "42.00"}]})
    section_meta: dict[str, Any] = {}
    stamp_unit_rate_kept(section_meta, reason=CATEGORY_FALLBACK_ALLOWANCE, unit_rate="0")
    section = _position(type="section", unit="", quantity=0.0, unit_rate=0.0, metadata=section_meta)
    child = _position(parent_id=section["id"])

    assert await UnitRateNotRederivedFromUntrustedBuildup().validate(_context([clean, section, child])) == []
    assert await UnitRateNotRederivedFromUntrustedBuildup().validate(_context([])) == []


def test_the_rule_is_registered_under_the_universal_set() -> None:
    """A rule registered under a set nobody requests never runs."""
    ids = {rule.rule_id for rule in rule_registry.get_rules_for_sets(["boq_quality"])}
    assert UnitRateNotRederivedFromUntrustedBuildup.rule_id in ids
