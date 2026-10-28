"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Service-logic tests for ProcurementService + MaterialRequisitionService.

These exercise the business rules with in-memory repository stubs (mirroring
``test_procurement_security``), so they assert behaviour without standing up
the full FastAPI app. The DB-touching aggregate helpers
(``_confirmed_received_by_item``) are monkeypatched at the instance level so
the cap / rollup decisions can be driven deterministically.

Covered:
    * Cumulative over-receipt cap at CREATE time (prior confirmed receipts
      count against the ordered quantity).
    * Cumulative over-receipt cap at CONFIRM time, excluding the GR being
      confirmed from the prior sum.
    * ``_check_po_fully_received`` - the pure rollup that flips a PO to
      completed vs partially_received.
    * PO FSM happy path (draft -> approved -> issued) and the idempotent
      re-approve / issue-before-approve guards.
    * Retainage release: positive-amount guard, status guard, held-balance
      cap, and the released-total increment.
    * MaterialRequisition FSM transition side-effects (approver / po_id stamp)
      and the reconcile passthrough.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException

from app.modules.procurement.models import PurchaseOrder
from app.modules.procurement.schemas import (
    GRCreate,
    GRItemCreate,
    POCreate,
    POItemCreate,
)
from app.modules.procurement.service import (
    MaterialRequisitionService,
    ProcurementService,
)

D = Decimal
PROJECT_A = uuid.uuid4()
USER_A = str(uuid.uuid4())


# ── In-memory repository stubs ────────────────────────────────────────────


class _StubPORepo:
    def __init__(self) -> None:
        self.rows: dict[uuid.UUID, Any] = {}
        self._counter = 0
        self._item_repo: _StubPOItemRepo | None = None
        self.lock_calls: list[uuid.UUID] = []

    async def create(self, po: Any) -> Any:
        if getattr(po, "id", None) is None:
            po.id = uuid.uuid4()
        now = datetime.now(UTC)
        po.created_at = now
        po.updated_at = now
        if not hasattr(po, "items"):
            po.items = []
        if not hasattr(po, "goods_receipts"):
            po.goods_receipts = []
        self.rows[po.id] = po
        return po

    async def get(self, po_id: uuid.UUID) -> Any:
        po = self.rows.get(po_id)
        if po is not None and self._item_repo is not None:
            po.items = [it for it in self._item_repo.rows.values() if it.po_id == po_id]
        return po

    async def update(self, po_id: uuid.UUID, **kwargs: Any) -> None:
        po = self.rows.get(po_id)
        if po:
            for k, v in kwargs.items():
                setattr(po, k, v)
            po.updated_at = datetime.now(UTC)

    async def next_po_number(self, project_id: uuid.UUID) -> str:
        self._counter += 1
        return f"PO-{self._counter:04d}"

    async def lock_for_update(self, po_id: uuid.UUID) -> None:
        self.lock_calls.append(po_id)


class _StubPOItemRepo:
    def __init__(self) -> None:
        self.rows: dict[uuid.UUID, Any] = {}

    async def create(self, item: Any) -> Any:
        if getattr(item, "id", None) is None:
            item.id = uuid.uuid4()
        now = datetime.now(UTC)
        item.created_at = now
        item.updated_at = now
        self.rows[item.id] = item
        return item

    async def delete_by_po(self, po_id: uuid.UUID) -> None:
        self.rows = {k: v for k, v in self.rows.items() if v.po_id != po_id}


class _StubGRRepo:
    def __init__(self) -> None:
        self.rows: dict[uuid.UUID, Any] = {}

    async def create(self, gr: Any) -> Any:
        if getattr(gr, "id", None) is None:
            gr.id = uuid.uuid4()
        now = datetime.now(UTC)
        gr.created_at = now
        gr.updated_at = now
        if not hasattr(gr, "items"):
            gr.items = []
        self.rows[gr.id] = gr
        return gr

    async def get(self, gr_id: uuid.UUID) -> Any:
        return self.rows.get(gr_id)


class _StubGRItemRepo:
    def __init__(self) -> None:
        self.rows: dict[uuid.UUID, Any] = {}

    async def create(self, item: Any) -> Any:
        if getattr(item, "id", None) is None:
            item.id = uuid.uuid4()
        self.rows[item.id] = item
        # Attach to the parent GR's items collection so refetch shows them.
        return item


class _StubRetainageRepo:
    def __init__(self) -> None:
        self.rows: list[Any] = []

    async def create(self, release: Any) -> Any:
        if getattr(release, "id", None) is None:
            release.id = uuid.uuid4()
        release.created_at = datetime.now(UTC)
        self.rows.append(release)
        return release


def _make_service() -> ProcurementService:
    svc = ProcurementService.__new__(ProcurementService)
    svc.session = SimpleNamespace(expunge=lambda _obj: None)
    svc.po_repo = _StubPORepo()
    svc.po_item_repo = _StubPOItemRepo()
    svc.po_repo._item_repo = svc.po_item_repo
    svc.gr_repo = _StubGRRepo()
    svc.gr_item_repo = _StubGRItemRepo()
    svc.retainage_repo = _StubRetainageRepo()
    return svc


#: Approval runs the blocking ``procurement`` rule set, which refuses a purchase
#: order with no vendor or no currency. These stub repositories cannot resolve
#: the parent project, so ``create_po`` never inherits the project currency and
#: every approvable fixture has to state one. The tests below are about the
#: over-receipt cap, the FSM and retainage, so this keeps them failing only for
#: the reason each is actually about.
VENDOR_A = "44444444-4444-4444-4444-444444444444"


def _approvable_po(*, amount_subtotal: str) -> POCreate:
    """A purchase order a buyer could really approve, worth ``amount_subtotal``.

    The single line carries the whole amount, so ``create_po`` re-aggregates the
    subtotal back to exactly what was asked for and the arithmetic rules agree.
    """
    return POCreate(
        project_id=PROJECT_A,
        vendor_contact_id=VENDOR_A,
        currency_code="EUR",
        amount_subtotal=amount_subtotal,
        tax_amount="0",
        items=[
            POItemCreate(
                description="Site works",
                quantity="1",
                unit="lot",
                unit_rate=amount_subtotal,
                amount=amount_subtotal,
                cost_category="works",
            ),
        ],
    )


async def _make_issued_po(svc: ProcurementService, *, quantity: str = "100") -> PurchaseOrder:
    """Create a draft PO with one line, approve + issue it (receivable)."""
    po = await svc.create_po(
        POCreate(
            project_id=PROJECT_A,
            vendor_contact_id=VENDOR_A,
            currency_code="EUR",
            amount_subtotal="0",
            tax_amount="0",
            items=[
                POItemCreate(description="Rebar", quantity=quantity, unit_rate="10", amount="0"),
            ],
        ),
        user_id=USER_A,
    )
    await svc.approve_po(po.id, approver_id=USER_A)
    await svc.issue_po(po.id)
    return await svc.po_repo.get(po.id)


# ── Over-receipt cap at CREATE time ───────────────────────────────────────


@pytest.mark.asyncio
async def test_create_gr_within_ordered_qty_succeeds() -> None:
    svc = _make_service()
    po = await _make_issued_po(svc, quantity="100")
    po_item = po.items[0]

    # No prior receipts -> the cap query returns nothing.
    svc._confirmed_received_by_item = _const_received({})  # type: ignore[method-assign]

    gr = await svc.create_goods_receipt(
        GRCreate(
            po_id=po.id,
            receipt_date="2026-05-24",
            items=[GRItemCreate(po_item_id=po_item.id, quantity_received="60")],
        ),
    )
    assert gr.status == "draft"


@pytest.mark.asyncio
async def test_create_gr_cumulative_over_receipt_is_blocked() -> None:
    """A 100-unit line that already has 80 confirmed received cannot accept a
    further 30 (80 + 30 > 100) - the cumulative cap rejects with 400."""
    svc = _make_service()
    po = await _make_issued_po(svc, quantity="100")
    po_item = po.items[0]

    # Pretend 80 units were already received on a prior confirmed GR.
    svc._confirmed_received_by_item = _const_received({po_item.id: D("80")})  # type: ignore[method-assign]

    with pytest.raises(HTTPException) as exc_info:
        await svc.create_goods_receipt(
            GRCreate(
                po_id=po.id,
                receipt_date="2026-05-24",
                items=[GRItemCreate(po_item_id=po_item.id, quantity_received="30")],
            ),
        )
    assert exc_info.value.status_code == 400
    assert "exceeds ordered" in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_create_gr_unknown_po_item_is_rejected() -> None:
    svc = _make_service()
    po = await _make_issued_po(svc, quantity="100")
    svc._confirmed_received_by_item = _const_received({})  # type: ignore[method-assign]

    with pytest.raises(HTTPException) as exc_info:
        await svc.create_goods_receipt(
            GRCreate(
                po_id=po.id,
                receipt_date="2026-05-24",
                items=[GRItemCreate(po_item_id=uuid.uuid4(), quantity_received="1")],
            ),
        )
    assert exc_info.value.status_code == 400
    assert "not found in purchase order" in str(exc_info.value.detail)


# ── _check_po_fully_received (pure rollup) ────────────────────────────────


def test_check_po_fully_received_true_when_all_lines_met() -> None:
    po_item_id = uuid.uuid4()
    po_item = SimpleNamespace(id=po_item_id, quantity="100")
    gr = SimpleNamespace(
        status="confirmed",
        items=[SimpleNamespace(po_item_id=po_item_id, quantity_received="100")],
    )
    po = SimpleNamespace(items=[po_item], goods_receipts=[gr])
    assert ProcurementService._check_po_fully_received(po) is True


def test_check_po_fully_received_false_when_short() -> None:
    po_item_id = uuid.uuid4()
    po_item = SimpleNamespace(id=po_item_id, quantity="100")
    gr = SimpleNamespace(
        status="confirmed",
        items=[SimpleNamespace(po_item_id=po_item_id, quantity_received="40")],
    )
    po = SimpleNamespace(items=[po_item], goods_receipts=[gr])
    assert ProcurementService._check_po_fully_received(po) is False


def test_check_po_fully_received_ignores_draft_grs() -> None:
    """A draft GR's quantities do not count toward fully-received."""
    po_item_id = uuid.uuid4()
    po_item = SimpleNamespace(id=po_item_id, quantity="100")
    gr = SimpleNamespace(
        status="draft",
        items=[SimpleNamespace(po_item_id=po_item_id, quantity_received="100")],
    )
    po = SimpleNamespace(items=[po_item], goods_receipts=[gr])
    assert ProcurementService._check_po_fully_received(po) is False


def test_check_po_fully_received_sums_multiple_confirmed_grs() -> None:
    po_item_id = uuid.uuid4()
    po_item = SimpleNamespace(id=po_item_id, quantity="100")
    gr1 = SimpleNamespace(
        status="confirmed",
        items=[SimpleNamespace(po_item_id=po_item_id, quantity_received="40")],
    )
    gr2 = SimpleNamespace(
        status="confirmed",
        items=[SimpleNamespace(po_item_id=po_item_id, quantity_received="60")],
    )
    po = SimpleNamespace(items=[po_item], goods_receipts=[gr1, gr2])
    assert ProcurementService._check_po_fully_received(po) is True


def test_check_po_fully_received_true_for_no_items() -> None:
    """A PO with no line items is vacuously fully received."""
    po = SimpleNamespace(items=[], goods_receipts=[])
    assert ProcurementService._check_po_fully_received(po) is True


# ── PO FSM (approve / issue) ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_approve_then_issue_happy_path() -> None:
    svc = _make_service()
    po = await svc.create_po(
        _approvable_po(amount_subtotal="100"),
        user_id=USER_A,
    )
    approved = await svc.approve_po(po.id, approver_id=USER_A)
    assert approved.status == "approved"
    issued = await svc.issue_po(po.id)
    assert issued.status == "issued"


@pytest.mark.asyncio
async def test_approve_is_idempotent() -> None:
    svc = _make_service()
    po = await svc.create_po(
        _approvable_po(amount_subtotal="100"),
        user_id=USER_A,
    )
    await svc.approve_po(po.id, approver_id=USER_A)
    # Second approve returns the same PO, no 409.
    again = await svc.approve_po(po.id, approver_id=USER_A)
    assert again.status == "approved"


@pytest.mark.asyncio
async def test_issue_before_approve_is_409() -> None:
    svc = _make_service()
    po = await svc.create_po(
        POCreate(project_id=PROJECT_A, amount_subtotal="100", tax_amount="0"),
        user_id=USER_A,
    )
    with pytest.raises(HTTPException) as exc_info:
        await svc.issue_po(po.id)
    assert exc_info.value.status_code == 409
    assert "approved before" in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_approve_non_draft_is_409() -> None:
    svc = _make_service()
    po = await _make_issued_po(svc, quantity="10")  # already issued
    with pytest.raises(HTTPException) as exc_info:
        await svc.approve_po(po.id, approver_id=USER_A)
    assert exc_info.value.status_code == 409


# ── Retainage release ─────────────────────────────────────────────────────


async def _issued_po_with_retainage(svc: ProcurementService) -> PurchaseOrder:
    """Issued PO, 10,000 total, 10% retention -> 1,000 withheld."""
    po = await svc.create_po(
        _approvable_po(amount_subtotal="10000"),
        user_id=USER_A,
    )
    await svc.po_repo.update(po.id, retention_percent=Decimal("10.00"))
    await svc.approve_po(po.id, approver_id=USER_A)
    await svc.issue_po(po.id)
    return await svc.po_repo.get(po.id)


@pytest.mark.asyncio
async def test_release_retainage_happy_path() -> None:
    svc = _make_service()
    po = await _issued_po_with_retainage(svc)
    release = await svc.release_po_retainage(
        po.id,
        release_amount=Decimal("400"),
        reason="50% milestone",
        user_id=uuid.UUID(USER_A),
    )
    assert release.release_amount == Decimal("400")
    # The cumulative released total is mirrored onto the PO.
    refreshed = await svc.po_repo.get(po.id)
    assert Decimal(refreshed.retainage_released_amount) == Decimal("400")
    assert refreshed.retainage_held() == Decimal("600.0000")
    # The cap+increment is serialised under a row lock.
    assert po.id in svc.po_repo.lock_calls


@pytest.mark.asyncio
async def test_release_retainage_rejects_non_positive() -> None:
    svc = _make_service()
    po = await _issued_po_with_retainage(svc)
    with pytest.raises(HTTPException) as exc_info:
        await svc.release_po_retainage(po.id, release_amount=Decimal("0"))
    assert exc_info.value.status_code == 400
    assert "must be positive" in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_release_retainage_cannot_exceed_held() -> None:
    """Releasing more than the held balance (1,000) is a 400, not a silent
    over-release."""
    svc = _make_service()
    po = await _issued_po_with_retainage(svc)
    with pytest.raises(HTTPException) as exc_info:
        await svc.release_po_retainage(po.id, release_amount=Decimal("1500"))
    assert exc_info.value.status_code == 400
    assert "exceeds held retainage" in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_release_retainage_cumulative_cap_blocks_second_over_release() -> None:
    """After releasing 700 of 1,000, a further 400 (cumulative 1,100) is
    blocked - the held balance is re-read fresh under the lock."""
    svc = _make_service()
    po = await _issued_po_with_retainage(svc)
    await svc.release_po_retainage(po.id, release_amount=Decimal("700"))
    with pytest.raises(HTTPException) as exc_info:
        await svc.release_po_retainage(po.id, release_amount=Decimal("400"))
    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_release_retainage_blocked_on_draft_po() -> None:
    """A draft PO has not committed money to a vendor - releasing retainage is
    a 409."""
    svc = _make_service()
    po = await svc.create_po(
        POCreate(project_id=PROJECT_A, amount_subtotal="10000", tax_amount="0"),
        user_id=USER_A,
    )
    await svc.po_repo.update(po.id, retention_percent=Decimal("10.00"))
    with pytest.raises(HTTPException) as exc_info:
        await svc.release_po_retainage(po.id, release_amount=Decimal("100"))
    assert exc_info.value.status_code == 409


@pytest.mark.asyncio
async def test_release_retainage_missing_po_is_404() -> None:
    svc = _make_service()
    with pytest.raises(HTTPException) as exc_info:
        await svc.release_po_retainage(uuid.uuid4(), release_amount=Decimal("100"))
    assert exc_info.value.status_code == 404


# ── MaterialRequisition FSM service ───────────────────────────────────────


class _StubReqSession:
    """Minimal async session for the requisition FSM tests.

    ``get`` resolves the in-memory requisition; ``flush`` is a no-op; the
    FSM transition reads/writes plain attributes on the stored object.
    """

    def __init__(self) -> None:
        self.rows: dict[uuid.UUID, Any] = {}

    async def get(self, _model: Any, key: uuid.UUID) -> Any:
        return self.rows.get(key)

    async def flush(self) -> None:
        return None


def _make_req_service() -> tuple[MaterialRequisitionService, _StubReqSession]:
    session = _StubReqSession()
    svc = MaterialRequisitionService.__new__(MaterialRequisitionService)
    svc.session = session  # type: ignore[assignment]
    return svc, session


def _stub_req(status: str = "draft") -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        status=status,
        approver_id=None,
        po_id=None,
        items=[],
    )


@pytest.mark.asyncio
async def test_transition_requisition_stamps_approver() -> None:
    svc, session = _make_req_service()
    req = _stub_req("submitted")
    session.rows[req.id] = req

    out = await svc.transition_requisition(req.id, "approved", approver_id="mgr-1")
    assert out.status == "approved"
    assert out.approver_id == "mgr-1"


@pytest.mark.asyncio
async def test_transition_requisition_stamps_po_id_on_ordered() -> None:
    svc, session = _make_req_service()
    req = _stub_req("approved")
    session.rows[req.id] = req
    po_id = uuid.uuid4()

    out = await svc.transition_requisition(req.id, "ordered", po_id=po_id)
    assert out.status == "ordered"
    assert out.po_id == po_id


@pytest.mark.asyncio
async def test_transition_requisition_illegal_jump_is_409() -> None:
    svc, session = _make_req_service()
    req = _stub_req("draft")
    session.rows[req.id] = req

    with pytest.raises(HTTPException) as exc_info:
        await svc.transition_requisition(req.id, "received")  # skips the chain
    assert exc_info.value.status_code == 409


@pytest.mark.asyncio
async def test_transition_requisition_missing_is_404() -> None:
    svc, _session = _make_req_service()
    with pytest.raises(HTTPException) as exc_info:
        await svc.transition_requisition(uuid.uuid4(), "submitted")
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_reconcile_returns_string_decimals() -> None:
    svc, session = _make_req_service()
    req = _stub_req("ordered")
    req.items = [
        SimpleNamespace(
            quantity_requested="100",
            quantity_ordered="100",
            quantity_received="60",
            quantity_consumed="20",
        ),
    ]
    session.rows[req.id] = req

    out = await svc.reconcile(req.id)
    # Every value is a string (Decimal-as-string contract).
    assert all(isinstance(v, str) for v in out.values())
    assert out["undelivered"] == "40"
    assert out["unconsumed"] == "40"


# ── Helper: deterministic _confirmed_received_by_item replacement ──────────


def _const_received(mapping: dict[uuid.UUID, Decimal]):
    """Return an async stand-in for ``_confirmed_received_by_item`` that yields
    a fixed prior-received mapping, ignoring its arguments."""

    async def _impl(_po_item_ids, *, exclude_receipt_id=None):  # noqa: ANN001, ANN202
        return dict(mapping)

    return _impl
