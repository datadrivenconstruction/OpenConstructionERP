# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Every writer of resource rows stores per-unit norms, and the estimator's money does not move.

``metadata.resources[].quantity`` is the amount of a resource per ONE unit of
the position; ``sum(quantity * unit_rate)`` is the position's unit rate. The
BOQ service re-derives the unit rate from the rows on an edit that touches
them, so a writer that stores whole-position totals under that key plants a
mis-pricing that only surfaces later, at roughly the position quantity times
the correct rate.

Before 17.1.0 three writers did exactly that: the AI estimator's apply path
stored ``factor * position_quantity``, its fallback allowance stored the
position quantity itself, and the demo seeder's lump-sum allowance did the
same. The flagship seeder was already per unit. These tests pin the release
that closed the gap:

* every writer in the tree yields rows the BOQ classifier reads as per-unit at
  a position quantity other than 1, under the strictest reading (an estimator
  position with a catalogue link), and the pre-release shapes at the same
  quantity are still flagged, so the classifier is not vacuously silent;
* booking the same estimate yields the same ``unit_rate`` and ``total`` as
  before the change, only the resource rows differ;
* the preview shows the figure apply stores.

Run:
    cd backend
    python -m pytest tests/unit/test_every_resource_writer_stores_per_unit_rows.py -v --tb=short
"""

from __future__ import annotations

import asyncio
import uuid
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
import pytest_asyncio

from app.core.demo_projects import _resources_for_position
from app.modules.ai_estimator import schemas
from app.modules.ai_estimator.service import AiEstimatorService
from app.modules.boq.resource_norms import (
    AI_ESTIMATOR_SOURCE,
    CATEGORY_FALLBACK_ALLOWANCE,
    CATEGORY_WHOLE_POSITION_QUANTITIES,
    classify_buildup,
    resource_subtotal,
    untrusted_buildup_reason,
)
from app.scripts.seed_flagship import _build_resource_leaves
from tests._pg import transactional_session

OWNER_ID = uuid.uuid4()

# One position, priced at 67.60 per m2 from a bricklayer norm and a brick norm,
# booked at a quantity that is not 1 so a total-shaped row cannot hide.
POSITION_QTY = 12.0
UNIT_RATE = Decimal("67.60")
GROUP_RESOURCES: list[dict[str, Any]] = [
    {
        "name": "Bricklayer",
        "code": "L1",
        "unit": "h",
        "type": "labor",
        "factor": 0.85,
        "quantity": 0.85,
        "unit_rate": "42.00",
    },
    {
        "name": "Brick",
        "code": "M1",
        "unit": "pcs",
        "type": "material",
        "factor": 58.0,
        "quantity": 58.0,
        "unit_rate": "0.55",
    },
]
CATALOGUE_COMPONENTS: list[dict[str, Any]] = [
    {"code": "L1", "description": "Bricklayer", "unit": "h", "quantity": 0.85, "unit_rate": "42.00", "type": "labor"},
    {"code": "M1", "description": "Brick", "unit": "pcs", "quantity": 58.0, "unit_rate": "0.55", "type": "material"},
]


class _FakeItem:
    def __init__(self, components: Any) -> None:
        self.components = components


class _FakeSession:
    def __init__(self, item: Any) -> None:
        self._item = item

    async def get(self, _model: Any, _pk: Any) -> Any:
        return self._item


# ── The writers ──────────────────────────────────────────────────────────────


def _estimator_apply() -> list[dict[str, Any]]:
    """What ``apply`` stores for a group that kept its breakdown."""
    return AiEstimatorService._per_unit_rows(GROUP_RESOURCES)


def _estimator_catalogue_backfill() -> list[dict[str, Any]]:
    """``_ensure_resources`` path 1: the group lost its rows, the candidate has components."""
    service = object.__new__(AiEstimatorService)
    service.session = _FakeSession(_FakeItem(CATALOGUE_COMPONENTS))  # type: ignore[attr-defined]
    grp = SimpleNamespace(candidate_id=str(uuid.uuid4()), chosen_unit="m2")
    return asyncio.run(AiEstimatorService._ensure_resources(service, grp, Decimal(str(POSITION_QTY)), UNIT_RATE))


def _estimator_fallback() -> list[dict[str, Any]]:
    """``_ensure_resources`` path 2: no candidate, a labour/material allowance split."""
    service = object.__new__(AiEstimatorService)
    grp = SimpleNamespace(candidate_id=None, chosen_unit="m2")
    return asyncio.run(AiEstimatorService._ensure_resources(service, grp, Decimal(str(POSITION_QTY)), UNIT_RATE))


def _demo_seeder() -> list[dict[str, Any]]:
    return _resources_for_position("Brickwork, facing brick", "m2", POSITION_QTY, float(UNIT_RATE), None)


def _flagship_seeder() -> list[dict[str, Any]]:
    raw = [
        {"name": "Bricklayer", "code": "L1", "type": "labor", "unit": "h", "quantity": 0.85, "unit_rate": "42.00"},
        {"name": "Brick", "code": "M1", "type": "material", "unit": "pcs", "quantity": 58.0, "unit_rate": "0.55"},
    ]
    return _build_resource_leaves(raw, UNIT_RATE)


def _flagship_fallback() -> list[dict[str, Any]]:
    return _build_resource_leaves([], UNIT_RATE)


WRITERS = {
    "estimator apply": _estimator_apply,
    "estimator catalogue backfill": _estimator_catalogue_backfill,
    "estimator fallback allowance": _estimator_fallback,
    "demo seeder allowance": _demo_seeder,
    "flagship seeder": _flagship_seeder,
    "flagship fallback allowance": _flagship_fallback,
}

# The strictest reading: an estimator position with a catalogue link, so every
# branch of the classifier is live.
STRICT = {"source": AI_ESTIMATOR_SOURCE, "metadata": {"cost_item_id": str(uuid.uuid4())}}


@pytest.mark.parametrize("writer", sorted(WRITERS))
def test_every_writer_yields_rows_the_classifier_reads_as_per_unit(writer: str) -> None:
    rows = WRITERS[writer]()
    assert rows, f"{writer} wrote no rows"
    assert untrusted_buildup_reason(quantity=POSITION_QTY, resources=rows, **STRICT) is None, rows
    assert classify_buildup(quantity=POSITION_QTY, resources=rows, **STRICT) is None, rows
    # Per unit means the rows sum to the unit rate, not to the position total.
    subtotal = resource_subtotal(rows).quantize(Decimal("0.01"))
    assert subtotal == UNIT_RATE, f"{writer}: rows sum to {subtotal}, not the unit rate"
    assert subtotal != (UNIT_RATE * Decimal(str(POSITION_QTY))).quantize(Decimal("0.01"))


def test_the_pre_release_shapes_at_the_same_quantity_are_still_flagged() -> None:
    """The control: the assertions above are not passing because the classifier is silent."""
    totals = [{**r, "quantity": r["quantity"] * POSITION_QTY} for r in _estimator_apply()]
    verdict = classify_buildup(quantity=POSITION_QTY, resources=totals, **STRICT)
    assert verdict is not None
    assert verdict.category == CATEGORY_WHOLE_POSITION_QUANTITIES

    allowance = [{**r, "quantity": POSITION_QTY} for r in _estimator_fallback()]
    assert untrusted_buildup_reason(quantity=POSITION_QTY, resources=allowance, **STRICT) == CATEGORY_FALLBACK_ALLOWANCE

    demo_totals = [{**r, "quantity": POSITION_QTY} for r in _demo_seeder()]
    assert (
        untrusted_buildup_reason(quantity=POSITION_QTY, resources=demo_totals, **STRICT) == CATEGORY_FALLBACK_ALLOWANCE
    )


def test_the_estimator_fallback_is_one_allowance_per_unit_that_sums_to_the_rate() -> None:
    rows = _estimator_fallback()
    assert [r["quantity"] for r in rows] == [1.0, 1.0]
    assert all(r["estimated"] is True for r in rows)
    assert all(r["factor"] == 1.0 for r in rows)
    assert resource_subtotal(rows).quantize(Decimal("0.01")) == UNIT_RATE


def test_the_demo_seeder_writes_one_allowance_per_unit() -> None:
    rows = _demo_seeder()
    assert [r["quantity"] for r in rows] == [1.0, 1.0, 1.0]
    assert all(r["estimated"] is True for r in rows)
    assert resource_subtotal(rows) == UNIT_RATE
    assert _resources_for_position("Section", "LS", 0.0, 100.0, None) == [], (
        "a zero-quantity row has nothing to build up"
    )


def test_the_preview_shows_the_figure_apply_stores() -> None:
    service = object.__new__(AiEstimatorService)
    preview = AiEstimatorService._preview_resources(service, GROUP_RESOURCES)
    stored = _estimator_apply()
    assert [row.quantity for row in preview] == [row["quantity"] for row in stored] == [0.85, 58.0]
    assert [row.factor for row in preview] == [0.85, 58.0]


# ── Booking the same estimate: the money is unchanged, the rows are not ─────


@pytest_asyncio.fixture
async def session():
    async with transactional_session() as s:
        from app.modules.users.models import User

        s.add(User(id=OWNER_ID, email=f"o-{uuid.uuid4().hex[:6]}@test.io", hashed_password="x", full_name="O"))
        await s.flush()
        await s.commit()
        yield s


async def _book_the_estimate(session) -> Any:
    """Book one confirmed group of 12 m2 at 67.60 through the real ``apply``."""
    from sqlalchemy import select

    from app.modules.ai_estimator.models import AiEstimatorGroup, AiEstimatorRun
    from app.modules.boq.models import Position
    from app.modules.projects.models import Project

    project_id = uuid.uuid4()
    session.add(Project(id=project_id, name="P", owner_id=OWNER_ID, currency="EUR"))
    await session.flush()
    run = AiEstimatorRun(
        id=uuid.uuid4(),
        project_id=project_id,
        user_id=OWNER_ID,
        name="Brickwork",
        status="assembly",
        current_stage="assembly",
        checkpoints={"assembly": {"accepted": True}},
    )
    session.add(run)
    await session.flush()
    session.add(
        AiEstimatorGroup(
            id=uuid.uuid4(),
            run_id=run.id,
            group_key="walls|m2",
            element_ids=["w1", "w2"],
            element_count=2,
            quantities={"area_m2": POSITION_QTY},
            envelope={},
            chosen_unit="m2",
            description="Brickwork, facing brick",
            trade="structure",
            candidate_id=None,
            chosen_code="BRK-01",
            unit_rate=str(UNIT_RATE),
            currency="EUR",
            resources=GROUP_RESOURCES,
            candidates=[],
            match_method="manual",
            status="confirmed",
        )
    )
    await session.flush()

    service = AiEstimatorService(session)

    async def _preview_passes(_run: Any) -> Any:
        return SimpleNamespace(can_apply=True)

    async def _eur(_run: Any) -> tuple[str, dict[str, Any]]:
        return "EUR", {}

    service.build_preview = _preview_passes  # type: ignore[method-assign]
    service._project_currency_context = _eur  # type: ignore[method-assign]
    response = await service.apply(run, schemas.ApplyRequest(boq_name="Per unit"), OWNER_ID)
    assert response.positions_created == 1
    rows = (await session.execute(select(Position).where(Position.boq_id == response.boq_id))).scalars().all()
    assert len(rows) == 1
    return rows[0]


async def test_booking_the_same_estimate_keeps_the_unit_rate_and_total_and_changes_only_the_rows(session) -> None:
    """Before 17.1.0 the same booking wrote unit_rate 67.6000 and total 811.2000 too.

    The money never came from the rows: ``apply`` writes the chosen candidate's
    rate and ``qty * rate``. What changed is the rows beside them, which held
    ``factor * 12`` (10.2 and 696.0) and now hold the norm (0.85 and 58.0).
    """
    position = await _book_the_estimate(session)

    assert position.source == AI_ESTIMATOR_SOURCE
    assert position.quantity == "12.0000"
    assert position.unit_rate == "67.6000"
    assert position.total == "811.2000"

    stored = position.metadata_["resources"]
    pre_release = [{**r, "quantity": r["factor"] * POSITION_QTY} for r in GROUP_RESOURCES]
    assert [r["quantity"] for r in stored] == [0.85, 58.0]
    assert [r["quantity"] for r in pre_release] == pytest.approx([10.2, 696.0])
    assert [r["factor"] for r in stored] == [r["factor"] for r in pre_release]
    assert resource_subtotal(stored) == Decimal(position.unit_rate)
    assert resource_subtotal(pre_release).quantize(Decimal("0.01")) == Decimal(position.total)

    # The stored rows pass the guard the BOQ edit path applies; the old ones did not.
    strict = {"source": position.source, "metadata": position.metadata_, "quantity": position.quantity}
    assert untrusted_buildup_reason(resources=stored, **strict) is None
    assert untrusted_buildup_reason(resources=pre_release, **strict) == CATEGORY_WHOLE_POSITION_QUANTITIES
