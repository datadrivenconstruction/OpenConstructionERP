# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The review path for resource buildups the AI estimator stored the wrong size.

Rows written before the estimator read the catalogue norm hold the position
quantity on every line; rows written after hold ``factor * position_quantity``;
fallback allowance rows hold the position quantity and carry no catalogue link.
None of them can be told from a correct buildup by a single field, and none of
them may be repaired unattended: AI results are never applied here without a
person confirming them.

So the path is a listing and a per-position call. The listing classifies every
position of a project and says which ones a catalogue link can recover. The
call re-derives ONE position's rows from that link, writing per-unit norms and
keeping the previous rows, and only after the caller confirms. A position
without a usable link is marked and left as it is. Money is never touched.

These tests pin the classification, the re-derivation, the confirmation gate,
the marking branch, and the end-to-end consequence: after re-derivation an
ordinary edit prices the line correctly again.

Run:
    cd backend
    python -m pytest tests/unit/test_boq_resource_norm_review.py -v --tb=short
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

import pytest
import pytest_asyncio
from fastapi import HTTPException

from app.modules.boq.resource_norms import (
    AI_ESTIMATOR_SOURCE,
    CATEGORY_ASSUMED_NORM,
    CATEGORY_FALLBACK_ALLOWANCE,
    CATEGORY_NORM_COLLAPSED,
    CATEGORY_WHOLE_POSITION_QUANTITIES,
    REVIEW_CATEGORIES,
    REVIEW_KEY,
    UNIT_RATE_KEPT_KEY,
    classify_buildup,
    rederive_rows_from_catalogue,
    stamp_unit_rate_kept,
)
from app.modules.boq.resource_review import ResourceNormReviewService
from app.modules.boq.resource_review_router import resource_review_router
from app.modules.boq.schemas import PositionUpdate
from app.modules.boq.service import BOQService
from tests._pg import transactional_session

OWNER_ID = uuid.uuid4()

# The catalogue row the tests link to: a bricklayer norm and a brick norm.
COMPONENTS: list[dict[str, Any]] = [
    {"code": "L1", "description": "Bricklayer", "unit": "h", "quantity": 0.85, "unit_rate": "42.00", "type": "labor"},
    {"code": "M1", "description": "Brick", "unit": "pcs", "quantity": 58.0, "unit_rate": "0.55", "type": "material"},
]


def _pre_fix_rows(position_qty: float) -> list[dict[str, Any]]:
    """What apply stored before the fix: factor 1.0, quantity = position quantity."""
    return [
        {
            "name": "Bricklayer",
            "code": "L1",
            "unit": "h",
            "type": "labor",
            "factor": 1.0,
            "quantity": position_qty,
            "unit_rate": "42.00",
        },
        {
            "name": "Brick",
            "code": "M1",
            "unit": "pcs",
            "type": "material",
            "factor": 1.0,
            "quantity": position_qty,
            "unit_rate": "0.55",
        },
    ]


def _fallback_rows(position_qty: float, rate: float) -> list[dict[str, Any]]:
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


# ── Pure classification ──────────────────────────────────────────────────────


def test_fallback_rows_are_review_only_even_with_a_link() -> None:
    verdict = classify_buildup(
        source=AI_ESTIMATOR_SOURCE,
        metadata={"cost_item_id": str(uuid.uuid4())},
        quantity=250,
        resources=_fallback_rows(250.0, 40.0),
    )
    assert verdict is not None
    assert verdict.category == CATEGORY_FALLBACK_ALLOWANCE
    assert verdict.recoverable is False
    assert (verdict.row_count, verdict.flagged_rows) == (2, 2)


def test_assumed_norm_rows_are_review_only() -> None:
    rows = [
        {"factor": 1.0, "quantity": 12.0, "unit_rate": "1", "factor_estimated": True},
        {"factor": 0.85, "quantity": 10.2},
    ]
    verdict = classify_buildup(source=AI_ESTIMATOR_SOURCE, metadata={"cost_item_id": "x"}, quantity=12, resources=rows)
    assert verdict is not None
    assert verdict.category == CATEGORY_ASSUMED_NORM
    assert verdict.recoverable is False
    assert verdict.flagged_rows == 1


@pytest.mark.parametrize("linked", [True, False])
def test_a_collapsed_norm_is_recoverable_exactly_when_a_catalogue_link_exists(linked: bool) -> None:
    meta = {"cost_item_id": str(uuid.uuid4())} if linked else {}
    verdict = classify_buildup(source=AI_ESTIMATOR_SOURCE, metadata=meta, quantity="12", resources=_pre_fix_rows(12.0))
    assert verdict is not None
    assert verdict.category == CATEGORY_NORM_COLLAPSED
    assert verdict.recoverable is linked


def test_post_fix_whole_position_quantities_are_their_own_category() -> None:
    rows = [
        {"factor": 0.85, "quantity": 10.2, "unit_rate": "42.00"},
        {"factor": 58.0, "quantity": 696.0, "unit_rate": "0.55"},
    ]
    verdict = classify_buildup(source=AI_ESTIMATOR_SOURCE, metadata={"cost_item_id": "x"}, quantity=12, resources=rows)
    assert verdict is not None
    assert verdict.category == CATEGORY_WHOLE_POSITION_QUANTITIES
    assert verdict.recoverable is True
    assert verdict.flagged_rows == 2


def test_a_clean_buildup_is_not_listed() -> None:
    per_unit = [{"factor": 0.85, "quantity": 0.85, "unit_rate": "42.00"}]
    assert classify_buildup(source=AI_ESTIMATOR_SOURCE, metadata={}, quantity=12, resources=per_unit) is None
    assert classify_buildup(source=AI_ESTIMATOR_SOURCE, metadata={}, quantity=1, resources=per_unit) is None
    manual = [{"quantity": 12.0, "unit_rate": "90"}]
    assert classify_buildup(source="manual", metadata={}, quantity=12, resources=manual) is None
    assert classify_buildup(source=AI_ESTIMATOR_SOURCE, metadata={}, quantity=12, resources=[]) is None
    assert classify_buildup(source=AI_ESTIMATOR_SOURCE, metadata={}, quantity=12, resources=None) is None


def test_quantity_one_with_every_norm_at_one_is_listed_for_a_human_to_decide() -> None:
    """Shape cannot tell a lost norm from a norm that genuinely is one; the listing asks."""
    verdict = classify_buildup(source=AI_ESTIMATOR_SOURCE, metadata={}, quantity=1, resources=_pre_fix_rows(1.0))
    assert verdict is not None
    assert verdict.category == CATEGORY_NORM_COLLAPSED


def test_an_allowance_split_is_listed_only_when_it_holds_the_position_quantity() -> None:
    """Three writers flag allowances ``estimated``; only the whole-position shape mis-prices the line."""
    per_unit = [
        {"name": "Labor allowance", "type": "labor", "quantity": 1.0, "unit_rate": "14.00", "estimated": True},
        {"name": "Material allowance", "type": "material", "quantity": 1.0, "unit_rate": "26.00", "estimated": True},
    ]
    assert classify_buildup(source="manual", metadata={}, quantity=250, resources=per_unit) is None
    assert (
        classify_buildup(source=AI_ESTIMATOR_SOURCE, metadata={}, quantity=1, resources=_fallback_rows(1.0, 40.0))
        is None
    )
    verdict = classify_buildup(source="manual", metadata={}, quantity=250, resources=_fallback_rows(250.0, 40.0))
    assert verdict is not None
    assert verdict.category == CATEGORY_FALLBACK_ALLOWANCE, "the demo seeder's shape, whatever the source says"


def test_every_category_the_listing_reports_is_one_the_classifier_can_return() -> None:
    assert set(REVIEW_CATEGORIES) == {
        CATEGORY_FALLBACK_ALLOWANCE,
        CATEGORY_ASSUMED_NORM,
        CATEGORY_NORM_COLLAPSED,
        CATEGORY_WHOLE_POSITION_QUANTITIES,
    }


# ── Pure re-derivation ───────────────────────────────────────────────────────


def test_rederived_rows_are_per_unit_norms_in_the_estimators_shape() -> None:
    rows = rederive_rows_from_catalogue(COMPONENTS)
    assert [r["quantity"] for r in rows] == [0.85, 58.0]
    assert [r["factor"] for r in rows] == [0.85, 58.0], (
        "factor is kept for readers of estimator rows and equals the norm"
    )
    assert [r["unit_rate"] for r in rows] == ["42.00", "0.55"]
    assert [r["type"] for r in rows] == ["labor", "material"]
    assert [r["name"] for r in rows] == ["Bricklayer", "Brick"]
    assert not any("factor_estimated" in r for r in rows)


def test_a_component_without_a_norm_is_flagged_rather_than_assumed_silently() -> None:
    rows = rederive_rows_from_catalogue(
        [{"code": "X", "unit": "pcs", "unit_rate": "1.00"}, {"code": "F", "factor": 0.4}]
    )
    assert rows[0]["quantity"] == 1.0
    assert rows[0]["factor_estimated"] is True
    assert rows[1]["quantity"] == 0.4
    assert "factor_estimated" not in rows[1]


def test_junk_components_are_skipped_not_fatal() -> None:
    assert rederive_rows_from_catalogue(None) == []
    assert rederive_rows_from_catalogue("nope") == []
    assert len(rederive_rows_from_catalogue([{"code": "L1", "quantity": 2.0}, "text", None])) == 1


# ── DB fixtures ──────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def session():
    async with transactional_session() as s:
        from app.modules.users.models import User

        s.add(User(id=OWNER_ID, email=f"o-{uuid.uuid4().hex[:6]}@test.io", hashed_password="x", full_name="O"))
        await s.flush()
        await s.commit()
        yield s


async def _make_project(session) -> tuple[uuid.UUID, uuid.UUID]:
    from app.modules.boq.models import BOQ
    from app.modules.projects.models import Project

    project_id = uuid.uuid4()
    session.add(Project(id=project_id, name="P", owner_id=OWNER_ID, currency="EUR"))
    await session.flush()
    boq = BOQ(id=uuid.uuid4(), project_id=project_id, name="B")
    session.add(boq)
    await session.flush()
    return project_id, boq.id


async def _make_cost_item(session, components: list[dict[str, Any]] | None = None) -> uuid.UUID:
    from app.modules.costs.models import CostItem

    item = CostItem(
        id=uuid.uuid4(),
        code=f"BRK-{uuid.uuid4().hex[:6]}",
        description="Brickwork",
        unit="m2",
        rate="67.60",
        currency="EUR",
        source="custom",
        components=COMPONENTS if components is None else components,
    )
    session.add(item)
    await session.flush()
    return item.id


async def _add_position(
    session,
    boq_id: uuid.UUID,
    *,
    ordinal: str,
    quantity: str,
    unit_rate: str,
    metadata_: dict[str, Any],
    source: str = AI_ESTIMATOR_SOURCE,
):
    from app.modules.boq.models import Position

    pos = Position(
        id=uuid.uuid4(),
        boq_id=boq_id,
        ordinal=ordinal,
        description=f"position {ordinal}",
        unit="m2",
        quantity=quantity,
        unit_rate=unit_rate,
        total=str(Decimal(quantity) * Decimal(unit_rate)),
        source=source,
        metadata_=metadata_,
        sort_order=int(ordinal),
    )
    session.add(pos)
    await session.flush()
    return pos


# ── DB: the listing ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_the_listing_counts_by_category_and_says_what_a_link_can_recover(session) -> None:
    project_id, boq_id = await _make_project(session)
    item_id = await _make_cost_item(session)
    fallback = await _add_position(
        session,
        boq_id,
        ordinal="10",
        quantity="250",
        unit_rate="40",
        metadata_={"resources": _fallback_rows(250.0, 40.0)},
    )
    collapsed = await _add_position(
        session,
        boq_id,
        ordinal="20",
        quantity="12",
        unit_rate="67.6",
        metadata_={"cost_item_id": str(item_id), "resources": _pre_fix_rows(12.0)},
    )
    await _add_position(
        session,
        boq_id,
        ordinal="30",
        quantity="3",
        unit_rate="50",
        source="manual",
        metadata_={"resources": [{"name": "Concrete", "type": "material", "quantity": 1, "unit_rate": 50}]},
    )
    await session.commit()

    report = await ResourceNormReviewService(session).list_for_project(project_id)

    assert report["boq_count"] == 1
    assert report["positions_scanned"] == 3
    assert report["positions_flagged"] == 2
    assert report["recoverable"] == 1
    assert report["review_only"] == 1
    assert report["counts"] == {
        CATEGORY_FALLBACK_ALLOWANCE: 1,
        CATEGORY_ASSUMED_NORM: 0,
        CATEGORY_NORM_COLLAPSED: 1,
        CATEGORY_WHOLE_POSITION_QUANTITIES: 0,
    }
    by_id = {entry["position_id"]: entry for entry in report["positions"]}
    assert by_id[str(fallback.id)]["recoverable"] is False
    assert by_id[str(fallback.id)]["cost_item_id"] is None
    assert Decimal(by_id[str(fallback.id)]["resource_subtotal"]) == Decimal("10000"), "what an edit would have written"
    assert by_id[str(collapsed.id)]["recoverable"] is True
    assert by_id[str(collapsed.id)]["cost_item_id"] == str(item_id)
    assert by_id[str(collapsed.id)]["unit_rate_kept_on_edit"] is None


@pytest.mark.asyncio
async def test_the_listing_of_a_clean_project_is_empty_not_an_error(session) -> None:
    project_id, boq_id = await _make_project(session)
    await _add_position(session, boq_id, ordinal="10", quantity="3", unit_rate="50", source="manual", metadata_={})
    await session.commit()

    report = await ResourceNormReviewService(session).list_for_project(project_id)

    assert report["positions_scanned"] == 1
    assert report["positions_flagged"] == 0
    assert report["positions"] == []
    assert sum(report["counts"].values()) == 0


@pytest.mark.asyncio
async def test_the_listing_reports_an_edit_that_had_to_keep_the_rate(session) -> None:
    project_id, boq_id = await _make_project(session)
    meta: dict[str, Any] = {"resources": _fallback_rows(250.0, 40.0)}
    stamp_unit_rate_kept(meta, reason=CATEGORY_FALLBACK_ALLOWANCE, unit_rate="40")
    await _add_position(session, boq_id, ordinal="10", quantity="250", unit_rate="40", metadata_=meta)
    await session.commit()

    (entry,) = (await ResourceNormReviewService(session).list_for_project(project_id))["positions"]

    assert entry["unit_rate_kept_on_edit"]["reason"] == CATEGORY_FALLBACK_ALLOWANCE


# ── DB: the per-position call ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_re_deriving_requires_confirmation_and_writes_nothing_without_it(session) -> None:
    _project_id, boq_id = await _make_project(session)
    item_id = await _make_cost_item(session)
    rows = _pre_fix_rows(12.0)
    pos = await _add_position(
        session,
        boq_id,
        ordinal="10",
        quantity="12",
        unit_rate="67.6",
        metadata_={"cost_item_id": str(item_id), "resources": rows},
    )
    await session.commit()

    with pytest.raises(HTTPException) as excinfo:
        await ResourceNormReviewService(session).review_position(pos.id, confirm=False, actor_id=OWNER_ID)

    assert excinfo.value.status_code == 422
    await session.refresh(pos)
    assert pos.metadata_["resources"] == rows
    assert REVIEW_KEY not in pos.metadata_


@pytest.mark.asyncio
async def test_re_deriving_rewrites_the_rows_to_per_unit_norms_and_leaves_the_money_alone(session) -> None:
    _project_id, boq_id = await _make_project(session)
    item_id = await _make_cost_item(session)
    rows = _pre_fix_rows(12.0)
    meta: dict[str, Any] = {"cost_item_id": str(item_id), "resources": rows, "review_reason": "old"}
    stamp_unit_rate_kept(meta, reason=CATEGORY_NORM_COLLAPSED, unit_rate="67.6")
    pos = await _add_position(session, boq_id, ordinal="10", quantity="12", unit_rate="67.6", metadata_=meta)
    version_before = int(pos.version or 0)
    await session.commit()

    result = await ResourceNormReviewService(session).review_position(pos.id, confirm=True, actor_id=OWNER_ID)

    assert result["action"] == "rederived"
    assert result["category"] == CATEGORY_NORM_COLLAPSED
    assert (result["rows_before"], result["rows_after"]) == (2, 2)
    # 12 * (42.00 + 0.55) was what an edit would have written; the catalogue sum is what stands now.
    assert Decimal(result["resource_subtotal_before"]) == Decimal("510.60")
    assert Decimal(result["resource_subtotal_after"]) == Decimal("67.60")
    assert Decimal(result["unit_rate"]) == Decimal("67.6")

    await session.refresh(pos)
    stored = pos.metadata_
    assert [r["quantity"] for r in stored["resources"]] == [0.85, 58.0]
    assert Decimal(str(pos.unit_rate)) == Decimal("67.6")
    assert Decimal(str(pos.total)) == Decimal("811.2")
    assert stored[REVIEW_KEY]["action"] == "rederived"
    assert stored[REVIEW_KEY]["previous_resources"] == rows, "the rows before are kept so the step can be reversed"
    assert stored[REVIEW_KEY]["by"] == str(OWNER_ID)
    assert stored[REVIEW_KEY]["cost_item_id"] == str(item_id)
    assert "review_reason" not in stored
    assert UNIT_RATE_KEPT_KEY not in stored
    assert set(stored["resource_breakdown"]) == {"labor", "material"}
    assert stored["resource_breakdown"]["labor"]["total"] == pytest.approx(35.7)
    assert pos.validation_status == "pending"
    assert int(pos.version) == version_before + 1


@pytest.mark.asyncio
async def test_after_re_derivation_an_ordinary_edit_prices_the_line_correctly_again(session) -> None:
    """The point of the whole path: the edit that used to detonate now does arithmetic."""
    _project_id, boq_id = await _make_project(session)
    item_id = await _make_cost_item(session)
    pos = await _add_position(
        session,
        boq_id,
        ordinal="10",
        quantity="12",
        unit_rate="67.6",
        metadata_={"cost_item_id": str(item_id), "resources": _pre_fix_rows(12.0)},
    )
    await session.commit()
    await ResourceNormReviewService(session).review_position(pos.id, confirm=True, actor_id=OWNER_ID)
    await session.refresh(pos)

    edited = [dict(r) for r in pos.metadata_["resources"]]
    edited[0]["unit_rate"] = "45.00"  # the bricklayer got a raise
    updated = await BOQService(session).update_position(
        pos.id,
        PositionUpdate(metadata={**pos.metadata_, "resources": edited}),
        actor_id=OWNER_ID,
    )

    assert Decimal(str(updated.unit_rate)) == Decimal("70.15")  # 0.85 * 45 + 58 * 0.55, per unit
    assert Decimal(str(updated.total)) == Decimal("841.8")  # 12 * 70.15
    assert UNIT_RATE_KEPT_KEY not in updated.metadata_


@pytest.mark.asyncio
async def test_a_fallback_position_is_marked_and_its_rows_are_left_untouched(session) -> None:
    _project_id, boq_id = await _make_project(session)
    rows = _fallback_rows(250.0, 40.0)
    pos = await _add_position(
        session, boq_id, ordinal="10", quantity="250", unit_rate="40", metadata_={"resources": rows}
    )
    await session.commit()

    result = await ResourceNormReviewService(session).review_position(pos.id, confirm=True, actor_id=OWNER_ID)

    assert result["action"] == "marked"
    assert result["review_reason"] == CATEGORY_FALLBACK_ALLOWANCE
    await session.refresh(pos)
    assert pos.metadata_["resources"] == rows
    assert pos.metadata_["review_reason"] == CATEGORY_FALLBACK_ALLOWANCE
    assert pos.metadata_[REVIEW_KEY]["action"] == "marked"
    assert Decimal(str(pos.unit_rate)) == Decimal("40")


@pytest.mark.asyncio
async def test_a_link_to_a_catalogue_row_without_components_marks_instead_of_rewriting(session) -> None:
    _project_id, boq_id = await _make_project(session)
    item_id = await _make_cost_item(session, components=[])
    rows = _pre_fix_rows(12.0)
    pos = await _add_position(
        session,
        boq_id,
        ordinal="10",
        quantity="12",
        unit_rate="67.6",
        metadata_={"cost_item_id": str(item_id), "resources": rows},
    )
    await session.commit()

    result = await ResourceNormReviewService(session).review_position(pos.id, confirm=True, actor_id=OWNER_ID)

    assert result["action"] == "marked"
    assert result["review_reason"] == "catalogue_row_unavailable"
    await session.refresh(pos)
    assert pos.metadata_["resources"] == rows


@pytest.mark.asyncio
async def test_a_clean_position_is_refused_rather_than_rewritten(session) -> None:
    _project_id, boq_id = await _make_project(session)
    pos = await _add_position(
        session,
        boq_id,
        ordinal="10",
        quantity="3",
        unit_rate="50",
        source="manual",
        metadata_={"resources": [{"name": "Concrete", "type": "material", "quantity": 1, "unit_rate": 50}]},
    )
    await session.commit()

    with pytest.raises(HTTPException) as excinfo:
        await ResourceNormReviewService(session).review_position(pos.id, confirm=True, actor_id=OWNER_ID)
    assert excinfo.value.status_code == 409


@pytest.mark.asyncio
async def test_a_locked_bill_is_not_touched(session) -> None:
    from app.modules.boq.models import BOQ

    _project_id, boq_id = await _make_project(session)
    item_id = await _make_cost_item(session)
    pos = await _add_position(
        session,
        boq_id,
        ordinal="10",
        quantity="12",
        unit_rate="67.6",
        metadata_={"cost_item_id": str(item_id), "resources": _pre_fix_rows(12.0)},
    )
    (await session.get(BOQ, boq_id)).is_locked = True
    await session.commit()

    with pytest.raises(HTTPException) as excinfo:
        await ResourceNormReviewService(session).review_position(pos.id, confirm=True, actor_id=OWNER_ID)
    assert excinfo.value.status_code == 409


@pytest.mark.asyncio
async def test_a_missing_position_is_a_404(session) -> None:
    with pytest.raises(HTTPException) as excinfo:
        await ResourceNormReviewService(session).review_position(uuid.uuid4(), confirm=True, actor_id=OWNER_ID)
    assert excinfo.value.status_code == 404


# ── The routes ───────────────────────────────────────────────────────────────


def test_the_review_router_exposes_the_two_routes() -> None:
    routes = {(route.path, method) for route in resource_review_router.routes for method in (route.methods or ())}
    assert ("/projects/{project_id}/resource-norm-review", "GET") in routes
    assert ("/positions/{position_id}/resource-norm-review", "POST") in routes


def test_the_boq_router_mounts_the_review_routes() -> None:
    """The module loader mounts one router per module; a sub-router nobody includes answers nowhere.

    Current FastAPI does not copy an included router's routes into the parent
    table; it appends one marker that resolves them when a request arrives, so
    a flat read of ``router.routes`` reports an included sub-router as absent.
    The test therefore reads the router the way the module loader does.
    """
    from app.core.module_loader import _walk_routes
    from app.modules.boq.router import router as boq_router

    mounted = {
        (path, method)
        for path, route in _walk_routes(boq_router.routes)
        for method in (getattr(route, "methods", None) or ())
    }
    assert ("/projects/{project_id}/resource-norm-review", "GET") in mounted
    assert ("/positions/{position_id}/resource-norm-review", "POST") in mounted
