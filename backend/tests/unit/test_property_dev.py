"""Unit tests for :mod:`app.modules.property_dev`.

Scope:
    Covers pure helpers (freeze deadline, selection totals, option
    compatibility, plot pricing, can-modify-selection, construction
    progress), state machines (plot/buyer/selection/handover/warranty),
    and the workflow service methods (reserve_plot, lock_selection,
    submit_for_production, convert_buyer_to_contracted,
    complete_handover, raise_warranty_claim).

Repositories + event bus are stubbed — no database touched.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from app.modules.property_dev.permissions import PROPERTY_DEV_PERMISSIONS
from app.modules.property_dev.schemas import (
    BuyerContractRequest,
    BuyerSelectionItemCreate,
    HandoverCompleteRequest,
    PlotReserveRequest,
    WarrantyClaimCreate,
)
from app.modules.property_dev.service import (
    PropertyDevService,
    allowed_buyer_transitions,
    allowed_handover_transitions,
    allowed_plot_transitions,
    allowed_selection_transitions,
    allowed_warranty_transitions,
    can_modify_selection,
    compute_buyer_selection_total,
    compute_freeze_deadline,
    compute_plot_final_price,
    derive_plot_construction_progress,
    validate_option_compatibility,
)

DEV_ID = uuid.uuid4()


# ── Stub repos ──────────────────────────────────────────────────────────


class _StubRepo:
    """Generic in-memory repository compatible with the service."""

    def __init__(self) -> None:
        self.rows: dict[uuid.UUID, Any] = {}

    async def create(self, obj: Any) -> Any:
        if getattr(obj, "id", None) is None:
            obj.id = uuid.uuid4()
        now = datetime.now(UTC)
        obj.created_at = now
        obj.updated_at = now
        self.rows[obj.id] = obj
        return obj

    async def get_by_id(self, oid: uuid.UUID) -> Any:
        return self.rows.get(oid)

    async def update_fields(self, oid: uuid.UUID, **kwargs: Any) -> None:
        obj = self.rows.get(oid)
        if obj is None:
            return
        for k, v in kwargs.items():
            setattr(obj, k, v)
        obj.updated_at = datetime.now(UTC)

    async def delete(self, oid: uuid.UUID) -> None:
        self.rows.pop(oid, None)


class _StubBuyerRepo(_StubRepo):
    async def get_for_plot(self, plot_id: uuid.UUID) -> Any:
        for r in self.rows.values():
            if getattr(r, "plot_id", None) == plot_id:
                return r
        return None


class _StubSelectionRepo(_StubRepo):
    async def list_for_buyer(self, buyer_id: uuid.UUID) -> list[Any]:
        return [r for r in self.rows.values() if r.buyer_id == buyer_id]

    async def current_selection_for_buyer(self, buyer_id: uuid.UUID) -> Any:
        rows = await self.list_for_buyer(buyer_id)
        return rows[-1] if rows else None


class _StubSelectionItemRepo(_StubRepo):
    async def list_for_selection(self, selection_id: uuid.UUID) -> list[Any]:
        return [r for r in self.rows.values() if r.selection_id == selection_id]


class _StubHandoverDocRepo(_StubRepo):
    async def list_for_handover(self, handover_id: uuid.UUID) -> list[Any]:
        return [r for r in self.rows.values() if getattr(r, "handover_id", None) == handover_id]


class _StubSession:
    """Minimal session — service never touches it directly during these tests."""

    pass


def _make_service() -> PropertyDevService:
    service = PropertyDevService.__new__(PropertyDevService)
    service.session = _StubSession()
    service.developments = _StubRepo()
    service.house_types = _StubRepo()
    service.variants = _StubRepo()
    service.plots = _StubRepo()
    service.option_groups = _StubRepo()
    service.options = _StubRepo()
    service.buyers = _StubBuyerRepo()
    service.selections = _StubSelectionRepo()
    service.selection_items = _StubSelectionItemRepo()
    service.handovers = _StubRepo()
    service.handover_docs = _StubHandoverDocRepo()
    service.snags = _StubRepo()
    service.warranty = _StubRepo()
    return service


def _plot(**overrides: Any) -> Any:
    defaults = {
        "id": uuid.uuid4(),
        "development_id": DEV_ID,
        "plot_number": "P-001",
        "house_type_id": None,
        "house_type_variant_id": None,
        "status": "planned",
        "price_base": Decimal("400000"),
        "currency": "EUR",
        "reservation_deadline": None,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _buyer(**overrides: Any) -> Any:
    defaults = {
        "id": uuid.uuid4(),
        "development_id": DEV_ID,
        "plot_id": None,
        "full_name": "Test Buyer",
        "email": "test@example.org",
        "status": "lead",
        "contract_value": Decimal("0"),
        "currency": "",
        "contract_signed_at": None,
        "deposit_paid_at": None,
        "freeze_deadline": None,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


# ── Pure helpers: freeze_deadline ───────────────────────────────────────


def test_compute_freeze_deadline_basic() -> None:
    handover = date(2026, 12, 1)
    assert compute_freeze_deadline(handover, 60) == date(2026, 10, 2)


def test_compute_freeze_deadline_zero_offset() -> None:
    handover = date(2026, 6, 15)
    assert compute_freeze_deadline(handover, 0) == handover


def test_compute_freeze_deadline_negative_offset_clamped() -> None:
    handover = date(2026, 6, 15)
    assert compute_freeze_deadline(handover, -30) == handover


# ── Pure helpers: selection total ───────────────────────────────────────


def test_compute_selection_total_basic() -> None:
    items = [
        SimpleNamespace(quantity=1, unit_price_snapshot=Decimal("100.00")),
        SimpleNamespace(quantity=2, unit_price_snapshot=Decimal("50.00")),
    ]
    assert compute_buyer_selection_total(items) == Decimal("200.00")


def test_compute_selection_total_empty() -> None:
    assert compute_buyer_selection_total([]) == Decimal("0")


def test_compute_selection_total_decimal_precision() -> None:
    items = [
        SimpleNamespace(quantity=3, unit_price_snapshot=Decimal("33.33")),
    ]
    assert compute_buyer_selection_total(items) == Decimal("99.99")


# ── Pure helpers: option compatibility ──────────────────────────────────


def _opt(code: str, oid: Any, rules: dict | None = None) -> Any:
    return SimpleNamespace(id=oid, code=code, compatibility_rules=rules or {})


def test_validate_compatibility_must_have_satisfied() -> None:
    opts = [_opt("FLR-OAK", "1", {"must_have": ["KIT-LUX"]}), _opt("KIT-LUX", "2")]
    ok, viol = validate_option_compatibility(["1", "2"], opts)
    assert ok is True
    assert viol == []


def test_validate_compatibility_must_have_missing() -> None:
    opts = [_opt("FLR-OAK", "1", {"must_have": ["KIT-LUX"]})]
    ok, viol = validate_option_compatibility(["1"], opts)
    assert ok is False
    assert any("KIT-LUX" in v for v in viol)


def test_validate_compatibility_must_not_have_violated() -> None:
    opts = [
        _opt("FLR-CARPET", "1", {"must_not_have": ["FLR-OAK"]}),
        _opt("FLR-OAK", "2"),
    ]
    ok, viol = validate_option_compatibility(["1", "2"], opts)
    assert ok is False
    assert any("FLR-OAK" in v for v in viol)


def test_validate_compatibility_explicit_rules_override() -> None:
    opts = [_opt("OPT-A", "1"), _opt("OPT-B", "2")]
    ok, viol = validate_option_compatibility(["1"], opts, rules={"must_have": ["OPT-B"]})
    assert ok is False
    assert any("OPT-B" in v for v in viol)


# ── Pure helpers: plot final price ──────────────────────────────────────


def test_compute_plot_final_price_no_variant_no_options() -> None:
    plot = SimpleNamespace(price_base=Decimal("300000"))
    assert compute_plot_final_price(plot, None, []) == Decimal("300000")


def test_compute_plot_final_price_with_variant_modifier() -> None:
    plot = SimpleNamespace(price_base=Decimal("400000"))
    variant = SimpleNamespace(modifier_pct=Decimal("5.0"))
    # 5% of 400k = 20k
    assert compute_plot_final_price(plot, variant, []) == Decimal("420000.0")


def test_compute_plot_final_price_with_options() -> None:
    plot = SimpleNamespace(price_base=Decimal("400000"))
    variant = SimpleNamespace(modifier_pct=Decimal("0"))
    selections = [
        SimpleNamespace(total_price=Decimal("8500")),
        SimpleNamespace(total_price=Decimal("3200")),
    ]
    assert compute_plot_final_price(plot, variant, selections) == Decimal("411700")


# ── Pure helpers: can_modify_selection ──────────────────────────────────


def test_can_modify_selection_before_deadline() -> None:
    buyer = _buyer(status="reserved", freeze_deadline="2030-01-01")
    assert can_modify_selection(buyer, date(2026, 6, 1)) is True


def test_can_modify_selection_after_deadline() -> None:
    buyer = _buyer(status="reserved", freeze_deadline="2026-01-01")
    assert can_modify_selection(buyer, date(2026, 6, 1)) is False


def test_can_modify_selection_no_deadline() -> None:
    buyer = _buyer(status="reserved", freeze_deadline=None)
    assert can_modify_selection(buyer, date(2026, 6, 1)) is True


def test_can_modify_selection_cancelled() -> None:
    buyer = _buyer(status="cancelled", freeze_deadline="2030-01-01")
    assert can_modify_selection(buyer, date(2026, 6, 1)) is False


# ── Pure helpers: construction progress ─────────────────────────────────


def test_derive_progress_unweighted() -> None:
    plot_id = uuid.uuid4()
    packages = [
        {"plot_id": str(plot_id), "weight": 1, "percent_complete": 100},
        {"plot_id": str(plot_id), "weight": 1, "percent_complete": 50},
    ]
    assert derive_plot_construction_progress(plot_id, packages) == Decimal("75.00")


def test_derive_progress_no_packages() -> None:
    plot_id = uuid.uuid4()
    assert derive_plot_construction_progress(plot_id, []) == Decimal("0")


def test_derive_progress_filters_other_plots() -> None:
    plot_id = uuid.uuid4()
    other = uuid.uuid4()
    packages = [
        {"plot_id": str(plot_id), "weight": 1, "percent_complete": 80},
        {"plot_id": str(other), "weight": 1, "percent_complete": 0},
    ]
    assert derive_plot_construction_progress(plot_id, packages) == Decimal("80.00")


# ── State machines ──────────────────────────────────────────────────────


def test_plot_transitions_valid() -> None:
    assert "reserved" in allowed_plot_transitions("planned")
    assert "sold" in allowed_plot_transitions("reserved")
    assert "handed_over" in allowed_plot_transitions("sold")


def test_plot_transitions_terminal() -> None:
    assert allowed_plot_transitions("handed_over") == set()


def test_buyer_transitions_valid() -> None:
    assert "reserved" in allowed_buyer_transitions("lead")
    assert "contracted" in allowed_buyer_transitions("reserved")
    assert "completed" in allowed_buyer_transitions("contracted")


def test_buyer_transitions_invalid_skip() -> None:
    # lead can't jump straight to contracted
    assert "contracted" not in allowed_buyer_transitions("lead")


def test_selection_transitions_valid() -> None:
    assert "submitted" in allowed_selection_transitions("draft")
    assert "locked" in allowed_selection_transitions("submitted")
    assert allowed_selection_transitions("locked") == {"cancelled"}


def test_handover_transitions_valid() -> None:
    assert "completed" in allowed_handover_transitions("scheduled")
    assert allowed_handover_transitions("completed") == set()


def test_warranty_transitions_valid() -> None:
    assert "accepted" in allowed_warranty_transitions("under_review")
    assert "closed" in allowed_warranty_transitions("accepted")
    assert allowed_warranty_transitions("closed") == set()


# ── Workflow: reserve_plot ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_reserve_plot_success() -> None:
    svc = _make_service()
    plot = _plot(status="planned")
    svc.plots.rows[plot.id] = plot
    req = PlotReserveRequest(full_name="Alice", email="a@ex.com")
    out_plot, buyer = await svc.reserve_plot(plot.id, req)
    assert out_plot.status == "reserved"
    assert buyer.status == "reserved"
    assert buyer.plot_id == plot.id


@pytest.mark.asyncio
async def test_reserve_plot_double_reservation_raises() -> None:
    svc = _make_service()
    plot = _plot(status="reserved")
    svc.plots.rows[plot.id] = plot
    req = PlotReserveRequest(full_name="Alice", email="a@ex.com")
    with pytest.raises(HTTPException) as exc:
        await svc.reserve_plot(plot.id, req)
    assert exc.value.status_code == 409


# ── Workflow: convert_buyer_to_contracted ───────────────────────────────


@pytest.mark.asyncio
async def test_convert_buyer_lead_to_contracted_emits_event() -> None:
    svc = _make_service()
    buyer = _buyer(status="lead")
    svc.buyers.rows[buyer.id] = buyer
    req = BuyerContractRequest(
        contract_value=Decimal("420000"),
        currency="EUR",
        contract_signed_at="2026-04-15",
    )
    with patch("app.modules.property_dev.service.event_bus.publish_detached") as pub:
        result = await svc.convert_buyer_to_contracted(buyer.id, req)
    assert result.status == "contracted"
    pub.assert_called_once()
    args, kwargs = pub.call_args
    assert args[0] == "property_dev.buyer.contracted"


@pytest.mark.asyncio
async def test_convert_buyer_invalid_status_raises() -> None:
    svc = _make_service()
    buyer = _buyer(status="completed")
    svc.buyers.rows[buyer.id] = buyer
    req = BuyerContractRequest(
        contract_value=Decimal("420000"),
        currency="EUR",
        contract_signed_at="2026-04-15",
    )
    with pytest.raises(HTTPException):
        await svc.convert_buyer_to_contracted(buyer.id, req)


# ── Workflow: lock_selection + submit_for_production ────────────────────


@pytest.mark.asyncio
async def test_lock_selection_emits_event_and_flips_status() -> None:
    svc = _make_service()
    buyer = _buyer()
    svc.buyers.rows[buyer.id] = buyer
    sel = SimpleNamespace(
        id=uuid.uuid4(),
        buyer_id=buyer.id,
        status="submitted",
        locked_at=None,
        total_options_value=Decimal("12000"),
        submitted_at="2026-04-01",
        notes=None,
    )
    svc.selections.rows[sel.id] = sel
    with patch("app.modules.property_dev.service.event_bus.publish_detached") as pub:
        out = await svc.lock_selection(sel.id)
    assert out.status == "locked"
    pub.assert_called_once()
    assert pub.call_args[0][0] == "property_dev.selection.locked"


@pytest.mark.asyncio
async def test_submit_for_production_emits_event_and_flips_items() -> None:
    svc = _make_service()
    buyer = _buyer()
    svc.buyers.rows[buyer.id] = buyer
    sel = SimpleNamespace(
        id=uuid.uuid4(),
        buyer_id=buyer.id,
        status="locked",
        locked_at="2026-04-01",
        total_options_value=Decimal("12000"),
    )
    svc.selections.rows[sel.id] = sel
    item = SimpleNamespace(
        id=uuid.uuid4(),
        selection_id=sel.id,
        option_id=uuid.uuid4(),
        quantity=1,
        unit_price_snapshot=Decimal("6000"),
        total_price=Decimal("6000"),
        included_in_production=False,
    )
    svc.selection_items.rows[item.id] = item
    with patch("app.modules.property_dev.service.event_bus.publish_detached") as pub:
        await svc.submit_for_production(buyer.id)
    assert item.included_in_production is True
    pub.assert_called_once()
    assert pub.call_args[0][0] == "property_dev.selection.submitted_for_production"


@pytest.mark.asyncio
async def test_submit_for_production_requires_locked() -> None:
    svc = _make_service()
    buyer = _buyer()
    svc.buyers.rows[buyer.id] = buyer
    sel = SimpleNamespace(id=uuid.uuid4(), buyer_id=buyer.id, status="draft")
    svc.selections.rows[sel.id] = sel
    with pytest.raises(HTTPException) as exc:
        await svc.submit_for_production(buyer.id)
    assert exc.value.status_code == 409


# ── Workflow: add_selection_item ────────────────────────────────────────


@pytest.mark.asyncio
async def test_add_selection_item_updates_total() -> None:
    svc = _make_service()
    sel = SimpleNamespace(
        id=uuid.uuid4(),
        buyer_id=uuid.uuid4(),
        status="draft",
        total_options_value=Decimal("0"),
    )
    svc.selections.rows[sel.id] = sel
    opt = SimpleNamespace(
        id=uuid.uuid4(),
        code="OPT-A",
        price_delta=Decimal("100"),
        currency="EUR",
        is_active=True,
    )
    svc.options.rows[opt.id] = opt
    payload = BuyerSelectionItemCreate(option_id=opt.id, quantity=3)
    item = await svc.add_selection_item(sel.id, payload)
    assert item.total_price == Decimal("300")
    assert sel.total_options_value == Decimal("300")


@pytest.mark.asyncio
async def test_add_selection_item_rejects_locked() -> None:
    svc = _make_service()
    sel = SimpleNamespace(
        id=uuid.uuid4(),
        buyer_id=uuid.uuid4(),
        status="locked",
        total_options_value=Decimal("0"),
    )
    svc.selections.rows[sel.id] = sel
    opt = SimpleNamespace(
        id=uuid.uuid4(),
        code="OPT-A",
        price_delta=Decimal("100"),
        currency="EUR",
        is_active=True,
    )
    svc.options.rows[opt.id] = opt
    payload = BuyerSelectionItemCreate(option_id=opt.id, quantity=1)
    with pytest.raises(HTTPException) as exc:
        await svc.add_selection_item(sel.id, payload)
    assert exc.value.status_code == 409


# ── Workflow: complete_handover ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_complete_handover_emits_event_and_flips_plot() -> None:
    svc = _make_service()
    plot = _plot(status="sold")
    svc.plots.rows[plot.id] = plot
    h = SimpleNamespace(
        id=uuid.uuid4(),
        plot_id=plot.id,
        scheduled_at="2026-04-10",
        completed_at=None,
        snag_count_at_handover=0,
        final_check_passed=False,
        keys_handed_over_at=None,
        customer_signature_ref=None,
        notes=None,
    )
    svc.handovers.rows[h.id] = h
    req = HandoverCompleteRequest(
        completed_at="2026-04-15",
        customer_signature_ref="sig::xyz",
        final_check_passed=True,
        snag_count_at_handover=2,
    )
    with patch("app.modules.property_dev.service.event_bus.publish_detached") as pub:
        out = await svc.complete_handover(h.id, req)
    assert out.completed_at == "2026-04-15"
    assert plot.status == "handed_over"
    pub.assert_called_once()
    assert pub.call_args[0][0] == "property_dev.handover.completed"


@pytest.mark.asyncio
async def test_complete_handover_advances_contracted_buyer_to_completed() -> None:
    """A contracted buyer on the plot must reach ``completed`` once keys
    are handed over — otherwise revenue_completed / buyers_by_status /
    the buyer-stage UI never reflect a finished sale."""
    svc = _make_service()
    plot = _plot(status="sold")
    svc.plots.rows[plot.id] = plot
    buyer = _buyer(status="contracted", plot_id=plot.id)
    svc.buyers.rows[buyer.id] = buyer
    h = SimpleNamespace(
        id=uuid.uuid4(),
        plot_id=plot.id,
        scheduled_at="2026-04-10",
        completed_at=None,
        snag_count_at_handover=0,
        final_check_passed=False,
        keys_handed_over_at=None,
        customer_signature_ref=None,
        notes=None,
    )
    svc.handovers.rows[h.id] = h
    req = HandoverCompleteRequest(
        completed_at="2026-04-15",
        customer_signature_ref="sig::xyz",
    )
    with patch("app.modules.property_dev.service.event_bus.publish_detached"):
        await svc.complete_handover(h.id, req)
    assert buyer.status == "completed"


@pytest.mark.asyncio
async def test_complete_handover_leaves_non_contracted_buyer_untouched() -> None:
    """Only ``contracted`` buyers advance — a still-reserved buyer is not
    illegally jumped to ``completed`` (skips the contract hand-off)."""
    svc = _make_service()
    plot = _plot(status="sold")
    svc.plots.rows[plot.id] = plot
    buyer = _buyer(status="reserved", plot_id=plot.id)
    svc.buyers.rows[buyer.id] = buyer
    h = SimpleNamespace(
        id=uuid.uuid4(),
        plot_id=plot.id,
        scheduled_at="2026-04-10",
        completed_at=None,
        snag_count_at_handover=0,
        final_check_passed=False,
        keys_handed_over_at=None,
        customer_signature_ref=None,
        notes=None,
    )
    svc.handovers.rows[h.id] = h
    req = HandoverCompleteRequest(
        completed_at="2026-04-15",
        customer_signature_ref="sig::xyz",
    )
    with patch("app.modules.property_dev.service.event_bus.publish_detached"):
        await svc.complete_handover(h.id, req)
    assert buyer.status == "reserved"


# ── Workflow: reserve_plot integrity guards ─────────────────────────────


@pytest.mark.asyncio
async def test_reserve_plot_rejects_cross_development_buyer() -> None:
    svc = _make_service()
    plot = _plot(status="planned")
    svc.plots.rows[plot.id] = plot
    other_dev = uuid.uuid4()
    buyer = _buyer(status="lead", development_id=other_dev)
    svc.buyers.rows[buyer.id] = buyer
    req = PlotReserveRequest(buyer_id=buyer.id)
    with pytest.raises(HTTPException) as exc:
        await svc.reserve_plot(plot.id, req)
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_reserve_plot_rejects_when_plot_already_has_buyer() -> None:
    svc = _make_service()
    plot = _plot(status="planned")
    svc.plots.rows[plot.id] = plot
    existing = _buyer(status="reserved", plot_id=plot.id)
    svc.buyers.rows[existing.id] = existing
    req = PlotReserveRequest(full_name="New", email="n@ex.com")
    with pytest.raises(HTTPException) as exc:
        await svc.reserve_plot(plot.id, req)
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_reserve_plot_releases_buyers_old_plot() -> None:
    svc = _make_service()
    old_plot = _plot(status="reserved", plot_number="P-OLD")
    new_plot = _plot(status="planned", plot_number="P-NEW")
    svc.plots.rows[old_plot.id] = old_plot
    svc.plots.rows[new_plot.id] = new_plot
    buyer = _buyer(status="reserved", plot_id=old_plot.id)
    svc.buyers.rows[buyer.id] = buyer
    req = PlotReserveRequest(buyer_id=buyer.id)
    out_plot, out_buyer = await svc.reserve_plot(new_plot.id, req)
    assert out_plot.status == "reserved"
    assert out_buyer.plot_id == new_plot.id
    # The previously-held plot must be freed, not orphaned in 'reserved'.
    assert old_plot.status == "planned"


# ── Workflow: raise_warranty_claim ──────────────────────────────────────


@pytest.mark.asyncio
async def test_raise_warranty_claim_creates_and_emits_event() -> None:
    svc = _make_service()
    plot_id, buyer_id = uuid.uuid4(), uuid.uuid4()
    payload = WarrantyClaimCreate(
        plot_id=plot_id,
        buyer_id=buyer_id,
        category="defect",
        description="Heating not working",
    )
    with patch("app.modules.property_dev.service.event_bus.publish_detached") as pub:
        claim = await svc.raise_warranty_claim(plot_id, buyer_id, payload)
    assert claim.status == "raised"
    assert claim.description == "Heating not working"
    pub.assert_called_once()
    assert pub.call_args[0][0] == "property_dev.warranty.raised"


# ── Repository CRUD basics ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_repo_create_and_get() -> None:
    repo = _StubRepo()
    obj = SimpleNamespace(id=None, name="x")
    await repo.create(obj)
    fetched = await repo.get_by_id(obj.id)
    assert fetched is obj


@pytest.mark.asyncio
async def test_repo_update_fields_mutates_row() -> None:
    repo = _StubRepo()
    obj = SimpleNamespace(id=None, name="x", status="open")
    await repo.create(obj)
    await repo.update_fields(obj.id, status="closed")
    assert obj.status == "closed"


@pytest.mark.asyncio
async def test_repo_delete_removes_row() -> None:
    repo = _StubRepo()
    obj = SimpleNamespace(id=None)
    await repo.create(obj)
    await repo.delete(obj.id)
    assert await repo.get_by_id(obj.id) is None


# ── Permissions ─────────────────────────────────────────────────────────


def test_permissions_constants_registered() -> None:
    keys = set(PROPERTY_DEV_PERMISSIONS.keys())
    expected = {
        "property_dev.read",
        "property_dev.create",
        "property_dev.update",
        "property_dev.delete",
        "property_dev.reserve_plot",
        "property_dev.contract_buyer",
        "property_dev.lock_selection",
        "property_dev.handover",
        "property_dev.fix_snag",
        "property_dev.process_warranty",
    }
    assert expected.issubset(keys)


def test_permissions_register_idempotent() -> None:
    from app.modules.property_dev.permissions import register_property_dev_permissions

    register_property_dev_permissions()
    register_property_dev_permissions()  # second call must not throw


# ── Snag fix / wont-fix transitions ─────────────────────────────────────


@pytest.mark.asyncio
async def test_mark_snag_fixed_updates_state() -> None:
    svc = _make_service()
    snag = SimpleNamespace(
        id=uuid.uuid4(),
        handover_id=uuid.uuid4(),
        status="open",
        severity="minor",
        description="Hairline crack",
        fixed_at=None,
        fix_notes=None,
        location_in_plot=None,
        reported_at=None,
    )
    svc.snags.rows[snag.id] = snag
    out = await svc.mark_snag_fixed(snag.id, fix_notes="Filled & repainted")
    assert out.status == "fixed"
    assert out.fix_notes == "Filled & repainted"


# ── Warranty status transitions ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_warranty_accept_close_chain() -> None:
    svc = _make_service()
    claim = SimpleNamespace(
        id=uuid.uuid4(),
        plot_id=uuid.uuid4(),
        buyer_id=uuid.uuid4(),
        status="under_review",
        accepted_at=None,
        closed_at=None,
    )
    svc.warranty.rows[claim.id] = claim
    out = await svc.warranty_accept(claim.id)
    assert out.status == "accepted"
    out = await svc.warranty_close(claim.id)
    assert out.status == "closed"


@pytest.mark.asyncio
async def test_warranty_invalid_transition_raises() -> None:
    svc = _make_service()
    claim = SimpleNamespace(
        id=uuid.uuid4(),
        plot_id=uuid.uuid4(),
        buyer_id=uuid.uuid4(),
        status="closed",
    )
    svc.warranty.rows[claim.id] = claim
    with pytest.raises(HTTPException) as exc:
        await svc.warranty_accept(claim.id)
    assert exc.value.status_code == 409


# ── Residual development appraisal (RICS Red Book) ──────────────────────


def test_residual_appraisal_viable_project() -> None:
    """A standard residential development with healthy margins."""
    from app.modules.property_dev.service import compute_residual_appraisal

    out = compute_residual_appraisal(
        gross_development_value=Decimal("10000000"),
        construction_cost=Decimal("6000000"),
        professional_fees_pct=Decimal("10"),
        finance_cost=Decimal("200000"),
        sales_costs_pct=Decimal("3"),
        developer_profit_target_pct=Decimal("20"),
        contingency_pct=Decimal("5"),
    )
    # Professional fees = 6m * 10% = 600k; contingency = 6m * 5% = 300k.
    assert out["professional_fees"] == Decimal("600000.00")
    assert out["contingency"] == Decimal("300000.00")
    # Sales 3% of 10m = 300k; profit 20% of 10m = 2m.
    assert out["sales_costs"] == Decimal("300000.00")
    assert out["developer_profit"] == Decimal("2000000.00")
    # Residual = 10m − (6m + 600k + 300k + 200k + 300k + 2m) = 600k.
    assert out["residual_land_value"] == Decimal("600000.00")
    assert out["viable"] is True
    assert "RICS" in out["method"]


def test_residual_appraisal_unviable_when_cost_exceeds_gdv() -> None:
    from app.modules.property_dev.service import compute_residual_appraisal

    out = compute_residual_appraisal(
        gross_development_value=Decimal("5000000"),
        construction_cost=Decimal("6000000"),
        professional_fees_pct=Decimal("12"),
        developer_profit_target_pct=Decimal("20"),
        contingency_pct=Decimal("5"),
    )
    assert out["residual_land_value"] < 0
    assert out["viable"] is False


def test_residual_appraisal_profit_metrics() -> None:
    from app.modules.property_dev.service import compute_residual_appraisal

    out = compute_residual_appraisal(
        gross_development_value=Decimal("1000000"),
        construction_cost=Decimal("500000"),
        professional_fees_pct=Decimal("0"),
        finance_cost=Decimal("0"),
        sales_costs_pct=Decimal("0"),
        developer_profit_target_pct=Decimal("20"),
        contingency_pct=Decimal("0"),
    )
    # Profit 200k vs total dev cost 500k → 40% on cost; 20% on GDV.
    assert out["profit_on_cost"] == Decimal("0.4000")
    assert out["profit_on_gdv"] == Decimal("0.2000")


def test_sales_velocity_typical_pace() -> None:
    from app.modules.property_dev.service import compute_sales_velocity

    out = compute_sales_velocity(sold_units=12, total_units=48, months_on_market=4)
    # 12 / 4 = 3 units / month; 36 remaining → 12 months to sellout.
    assert out["velocity_units_per_month"] == Decimal("3.00")
    assert out["absorption_pct"] == Decimal("25.00")
    assert out["months_to_sellout"] == Decimal("12.0")


def test_sales_velocity_zero_months_safe() -> None:
    from app.modules.property_dev.service import compute_sales_velocity

    out = compute_sales_velocity(sold_units=0, total_units=20, months_on_market=0)
    assert out["velocity_units_per_month"] == Decimal("0")
    assert out["months_to_sellout"] is None


def test_sales_velocity_complete_sellout() -> None:
    from app.modules.property_dev.service import compute_sales_velocity

    out = compute_sales_velocity(sold_units=20, total_units=20, months_on_market=10)
    assert out["absorption_pct"] == Decimal("100.00")
    assert out["months_to_sellout"] == Decimal("0")
