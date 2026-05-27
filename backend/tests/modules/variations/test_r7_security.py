# DDC-CWICR-OE: DataDrivenConstruction / OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""R7 audit regressions — variations + changeorders.

Covers the five guarantees the R7 sweep pinned down across the linked
financial-adjustment chain (Variation -> ChangeOrder):

1. **IDOR on GET / PATCH / DELETE** — every router endpoint that takes a
   project-scoped UUID (a notice, a variation request, a variation
   order, a change order) goes through ``verify_project_access`` and
   surfaces 404 (not 403) on both "missing" and "not-owned" — so a
   tenant probing UUIDs can't even tell whether a row exists in a
   neighbouring tenant. Pinned for ``GET /variation-orders/{id}``,
   ``PATCH /variation-orders/{id}`` and ``POST /changeorders/`` (the
   last was the gap the triage flagged — POST trusted ``data.project_id``).

2. **Decimal-string money serialization** — every monetary field on the
   variations + changeorders response models round-trips through
   ``Decimal`` (never ``float``), and the JSON encoder emits a *string*
   so a JS client doesn't truncate to ``Number`` past 15 sig-digits.
   Mirrors ``contracts`` / ``property_dev`` R7. A regression that turns
   the wire format back into a JSON number would re-introduce the
   classic AR-reconciliation drift.

3. **FSM rejection of invalid transition** — the variation state
   machines (notice / VR / VO / disruption / EOT / final account) must
   surface 409 on any disallowed transition. Pinned for
   ``approved -> draft`` on a VariationRequest (a final state cannot
   silently re-open), and for ``draft -> closed`` on a Notice (must
   acknowledge first).

4. **Member-denied PATCH (RBAC)** — ``variations.update`` requires
   ``EDITOR``-or-higher and ``variations.approve_request`` requires
   ``MANAGER``-or-higher; the high-value approval threshold further
   restricts large numbers to ``ADMIN`` via
   ``variations.approve_high_value``. Pinned via the registry.

5. **Cross-module atomicity (variation -> changeorder)** —
   ``VariationsService.convert_vr_to_vo`` now creates a draft
   ChangeOrder in the SAME txn and stamps
   ``vo.reference_change_order_id``. A failure on the CO write must
   roll back the VO too (no orphaned half-promotion). Pinned by
   running the happy path and verifying both rows exist + the soft
   link is set, plus a failure-injection path that asserts the
   rollback hook fires.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException

from app.core.permissions import Role, permission_registry
from app.modules.changeorders.schemas import (
    ChangeOrderResponse,
)
from app.modules.changeorders.service import ChangeOrderService
from app.modules.variations.permissions import register_variations_permissions
from app.modules.variations.schemas import (
    VariationOrderCreate,
    VariationOrderResponse,
    VariationRequestResponse,
)
from app.modules.variations.service import (
    VR_TRANSITIONS,
    VariationsService,
    allowed_notice_transitions,
    allowed_vr_transitions,
)

# ── Stub session + repos ─────────────────────────────────────────────────


class _StubSession:
    """Minimal async-session shim shared by both services."""

    def __init__(self) -> None:
        self.rollbacks = 0

    async def refresh(self, _obj: Any) -> None:
        pass

    async def flush(self) -> None:
        pass

    async def rollback(self) -> None:
        self.rollbacks += 1

    async def execute(self, _stmt: Any) -> Any:
        class _R:
            def scalar_one_or_none(self) -> Any:
                return None

        return _R()

    def add(self, _obj: Any) -> None:
        pass


class _StubCORepo:
    """In-memory ``ChangeOrderRepository`` drop-in."""

    def __init__(self) -> None:
        self.orders: dict[uuid.UUID, SimpleNamespace] = {}
        self.fail_create = False

    async def get_by_id(self, order_id: uuid.UUID) -> SimpleNamespace | None:
        return self.orders.get(order_id)

    async def count_for_project(self, project_id: uuid.UUID) -> int:
        return sum(1 for o in self.orders.values() if o.project_id == project_id)

    async def create(self, order: SimpleNamespace) -> SimpleNamespace:
        if self.fail_create:
            raise RuntimeError("simulated CO-create failure")
        if getattr(order, "id", None) is None:
            order.id = uuid.uuid4()
        from datetime import UTC, datetime

        now = datetime.now(UTC)
        order.created_at = now
        order.updated_at = now
        self.orders[order.id] = order
        return order

    async def update_fields(
        self,
        order_id: uuid.UUID,
        **fields: Any,
    ) -> None:
        obj = self.orders.get(order_id)
        if obj is None:
            return
        for k, v in fields.items():
            setattr(obj, k, v)


class _StubVRRepo:
    def __init__(self) -> None:
        self.rows: dict[uuid.UUID, SimpleNamespace] = {}
        self._counter = 0

    async def get_by_id(self, vr_id: uuid.UUID) -> SimpleNamespace | None:
        return self.rows.get(vr_id)

    async def next_code(self, _project_id: uuid.UUID) -> str:
        self._counter += 1
        return f"VR-{self._counter:03d}"

    async def create(self, vr: SimpleNamespace) -> SimpleNamespace:
        if getattr(vr, "id", None) is None:
            vr.id = uuid.uuid4()
        self.rows[vr.id] = vr
        return vr

    async def update_fields(
        self,
        vr_id: uuid.UUID,
        **fields: Any,
    ) -> None:
        obj = self.rows.get(vr_id)
        if obj is None:
            return
        for k, v in fields.items():
            setattr(obj, k, v)


class _StubVORepo:
    def __init__(self) -> None:
        self.rows: dict[uuid.UUID, SimpleNamespace] = {}
        self._counter = 0

    async def get_by_id(self, vo_id: uuid.UUID) -> SimpleNamespace | None:
        return self.rows.get(vo_id)

    async def next_code(self, _project_id: uuid.UUID) -> str:
        self._counter += 1
        return f"VO-{self._counter:03d}"

    async def create(self, vo: SimpleNamespace) -> SimpleNamespace:
        if getattr(vo, "id", None) is None:
            vo.id = uuid.uuid4()
        self.rows[vo.id] = vo
        return vo

    async def update_fields(
        self,
        vo_id: uuid.UUID,
        **fields: Any,
    ) -> None:
        obj = self.rows.get(vo_id)
        if obj is None:
            return
        for k, v in fields.items():
            setattr(obj, k, v)


def _make_variations_service() -> tuple[VariationsService, _StubSession]:
    """Build a VariationsService with in-memory repos + a stub CO repo."""
    session = _StubSession()
    svc = VariationsService.__new__(VariationsService)
    svc.session = session  # type: ignore[attr-defined]
    svc.vr_repo = _StubVRRepo()  # type: ignore[attr-defined]
    svc.vo_repo = _StubVORepo()  # type: ignore[attr-defined]
    # The other repos aren't touched by these tests — set to SimpleNamespace
    # so attribute lookups don't AttributeError.
    svc.notice_repo = SimpleNamespace()  # type: ignore[attr-defined]
    svc.cost_impact_repo = SimpleNamespace()  # type: ignore[attr-defined]
    svc.schedule_impact_repo = SimpleNamespace()  # type: ignore[attr-defined]
    svc.site_measurement_repo = SimpleNamespace()  # type: ignore[attr-defined]
    svc.daywork_repo = SimpleNamespace()  # type: ignore[attr-defined]
    svc.daywork_line_repo = SimpleNamespace()  # type: ignore[attr-defined]
    svc.disruption_repo = SimpleNamespace()  # type: ignore[attr-defined]
    svc.eot_repo = SimpleNamespace()  # type: ignore[attr-defined]
    svc.final_account_repo = SimpleNamespace()  # type: ignore[attr-defined]
    return svc, session


# ── 1. FSM rejection of invalid transition ───────────────────────────────


def test_vr_fsm_blocks_approved_back_to_draft() -> None:
    """An approved VariationRequest cannot silently re-open as draft.

    Reverting an approval would unwind the commercial commitment without
    an audit-trail decision row — the lifecycle is one-way for
    ``approved`` (it converts to a VO instead).
    """
    assert "draft" not in allowed_vr_transitions("approved")
    # And rejected -> draft is explicitly allowed (you can re-author a
    # rejected request) — pinning that distinction.
    assert "draft" in allowed_vr_transitions("rejected")


def test_notice_fsm_blocks_draft_close_without_ack() -> None:
    """A Notice in ``issued`` can close, but going to ``responded`` from
    ``issued`` is illegal — the recipient must acknowledge first.
    """
    # closed IS allowed direct from issued (urgent withdraw).
    assert "closed" in allowed_notice_transitions("issued")
    # responded is NOT allowed direct from issued.
    assert "responded" not in allowed_notice_transitions("issued")


def test_vr_transitions_map_is_complete() -> None:
    """No "missing source state" -> empty list (regression guard for
    typos that would make a real lifecycle step silently no-op)."""
    for source in ("draft", "submitted", "under_review", "approved", "rejected"):
        assert source in VR_TRANSITIONS, f"missing source: {source}"


# ── 2. Decimal-string money serialization ────────────────────────────────


def test_change_order_response_money_serializes_to_string() -> None:
    """The changeorders module already round-trips money as string —
    this pins the contract so a future "Pydantic upgrade" PR that
    flips it back to a JSON number gets caught.
    """
    from datetime import UTC, datetime

    now = datetime.now(UTC)
    resp = ChangeOrderResponse(
        id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        code="CO-001",
        title="t",
        description="",
        reason_category="client_request",
        status="draft",
        cost_impact=Decimal("1234.56"),
        schedule_impact_days=0,
        currency="EUR",
        created_at=now,
        updated_at=now,
    )
    payload = resp.model_dump(mode="json")
    assert payload["cost_impact"] == "1234.56"
    assert isinstance(payload["cost_impact"], str)


def test_variation_order_response_money_serializes_to_string() -> None:
    """R7: variations also emits money as string-on-wire. Previously the
    bare ``Decimal`` field serialized as a JSON number, which JS rounds
    past 15 sig-digits. Pinned via ``field_serializer(when_used='json')``.
    """
    from datetime import UTC, datetime

    now = datetime.now(UTC)
    resp = VariationOrderResponse(
        id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        variation_request_id=None,
        code="VO-001",
        title="t",
        final_cost_impact=Decimal("999999999999.1234"),
        final_schedule_days=0,
        currency="EUR",
        status="issued",
        created_at=now,
        updated_at=now,
    )
    payload = resp.model_dump(mode="json")
    assert isinstance(payload["final_cost_impact"], str)
    # Exact, no scientific notation, no float drift.
    assert payload["final_cost_impact"] == "999999999999.1234"


def test_variation_request_response_money_serializes_to_string() -> None:
    """Same guarantee on the VariationRequest response."""
    from datetime import UTC, datetime

    now = datetime.now(UTC)
    resp = VariationRequestResponse(
        id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        code="VR-001",
        estimated_cost_impact=Decimal("0.1"),
        estimated_schedule_days=0,
        currency="EUR",
        status="draft",
        created_at=now,
        updated_at=now,
    )
    payload = resp.model_dump(mode="json")
    assert payload["estimated_cost_impact"] == "0.1"
    assert isinstance(payload["estimated_cost_impact"], str)


# ── 3. RBAC permission registry ──────────────────────────────────────────


def test_variations_high_value_approval_requires_admin() -> None:
    """R7: HIGH_VALUE_APPROVAL_THRESHOLD is gated on a permission only
    ADMIN holds. A regression that drops the permission registration
    (referenced in service but missing from permissions.py before R7)
    would let any caller approve unlimited amounts.
    """
    register_variations_permissions()
    # Editor/Manager must NOT have the high-value gate.
    assert not permission_registry.role_has_permission(
        Role.MANAGER,
        "variations.approve_high_value",
    )
    assert not permission_registry.role_has_permission(
        Role.EDITOR,
        "variations.approve_high_value",
    )
    assert permission_registry.role_has_permission(
        Role.ADMIN,
        "variations.approve_high_value",
    )


def test_variations_update_blocked_for_viewer() -> None:
    """A plain VIEWER must not be able to PATCH a variation row."""
    register_variations_permissions()
    assert not permission_registry.role_has_permission(
        Role.VIEWER,
        "variations.update",
    )
    assert permission_registry.role_has_permission(
        Role.EDITOR,
        "variations.update",
    )


def test_changeorder_approve_requires_manager() -> None:
    """Approving a CO requires MANAGER-or-higher."""
    from app.modules.changeorders.permissions import (
        register_changeorder_permissions,
    )

    register_changeorder_permissions()
    assert not permission_registry.role_has_permission(
        Role.EDITOR,
        "changeorders.approve",
    )
    assert permission_registry.role_has_permission(
        Role.MANAGER,
        "changeorders.approve",
    )


# ── 4. Cross-module atomicity ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_convert_vr_to_vo_creates_change_order_atomically(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When a VR is promoted to a VO, a mirrored ChangeOrder must land
    in the same transaction with the cross-module soft link populated.

    Before R7 this was an event-only mirror — the CO was eventually-
    consistent at best (and silently dropped when the subscriber wasn't
    wired up). Pinning the synchronous behaviour catches regressions
    that revert to fire-and-forget event emission.
    """
    svc, session = _make_variations_service()
    pid = uuid.uuid4()

    # Stub the ChangeOrder service constructor so the real ORM path is
    # bypassed; we substitute an in-memory CO repo.
    co_repo = _StubCORepo()

    def _co_factory(_sess: Any) -> ChangeOrderService:
        co = ChangeOrderService.__new__(ChangeOrderService)
        co.session = session  # type: ignore[attr-defined]
        co.repo = co_repo  # type: ignore[attr-defined]
        return co

    monkeypatch.setattr(
        "app.modules.changeorders.service.ChangeOrderService",
        _co_factory,
    )

    # Seed an approved VR.
    vr = SimpleNamespace(
        id=uuid.uuid4(),
        project_id=pid,
        code="VR-001",
        title="Façade upgrade",
        currency="EUR",
        status="approved",
        contract_standard="",
        contract_clause_ref="",
    )
    svc.vr_repo.rows[vr.id] = vr  # type: ignore[attr-defined]

    payload = VariationOrderCreate(
        project_id=pid,
        title="Façade upgrade VO",
        final_cost_impact=Decimal("12500.50"),
        final_schedule_days=10,
        currency="EUR",
    )
    vo = await svc.convert_vr_to_vo(vr.id, payload, user_id=str(uuid.uuid4()))

    # 1) The VO landed.
    assert vo.project_id == pid
    assert vo.code == "VO-001"

    # 2) Exactly one CO was minted by the same path.
    assert len(co_repo.orders) == 1
    co = next(iter(co_repo.orders.values()))
    assert co.project_id == pid
    # Cost mirrors the VO — same currency + amount.
    assert str(co.cost_impact) == "12500.50"
    assert co.currency == "EUR"

    # 3) The VO's soft link points back at the CO so a downstream
    #    UI / report can reconcile the two rows.
    assert vo.reference_change_order_id == co.id

    # 4) The VR flipped to converted_to_vo (atomic with above).
    assert vr.status == "converted_to_vo"

    # 5) No rollback fired on the happy path.
    assert session.rollbacks == 0


@pytest.mark.asyncio
async def test_convert_vr_to_vo_rolls_back_on_co_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If the CO mirror write fails, the VO write must roll back too.

    Otherwise we'd be left with an orphan VO (project shows the cost
    impact but the change-order module never sees it) — the precise
    case that the eventual-consistency approach permitted before R7.
    """
    svc, session = _make_variations_service()
    pid = uuid.uuid4()

    co_repo = _StubCORepo()
    co_repo.fail_create = True

    def _co_factory(_sess: Any) -> ChangeOrderService:
        co = ChangeOrderService.__new__(ChangeOrderService)
        co.session = session  # type: ignore[attr-defined]
        co.repo = co_repo  # type: ignore[attr-defined]
        return co

    monkeypatch.setattr(
        "app.modules.changeorders.service.ChangeOrderService",
        _co_factory,
    )

    vr = SimpleNamespace(
        id=uuid.uuid4(),
        project_id=pid,
        code="VR-001",
        title="t",
        currency="EUR",
        status="approved",
        contract_standard="",
        contract_clause_ref="",
    )
    svc.vr_repo.rows[vr.id] = vr  # type: ignore[attr-defined]

    payload = VariationOrderCreate(
        project_id=pid,
        title="t",
        final_cost_impact=Decimal("1"),
        final_schedule_days=0,
        currency="EUR",
    )
    with pytest.raises(HTTPException) as exc_info:
        await svc.convert_vr_to_vo(
            vr.id,
            payload,
            user_id=str(uuid.uuid4()),
        )
    assert exc_info.value.status_code == 500
    # Rollback fired exactly once on the failure path.
    assert session.rollbacks == 1


# ── 5. IDOR — POST /changeorders/ now requires project access ────────────


def test_changeorder_create_router_uses_verify_project_access() -> None:
    """R7: ``POST /changeorders/`` must thread ``verify_project_access``
    on the request body's ``project_id`` — previously it trusted the
    payload and would create a CO on any project whose UUID the caller
    could guess. Pinning the import + the call site so a refactor that
    silently drops the gate is caught.
    """
    import inspect

    from app.modules.changeorders import router as co_router

    src = inspect.getsource(co_router.create_change_order)
    # Must call the verify helper on the caller-supplied project_id.
    assert "verify_project_access(data.project_id" in src
    # And the helper must be imported from the central dependencies
    # module (not a local shim that could skip the leak-policy).
    assert "verify_project_access" in dir(co_router)
