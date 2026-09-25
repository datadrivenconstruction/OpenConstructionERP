"""Unit tests for :class:`ProcurementService`.

Scope:
    Covers PO creation, status transitions (draft -> issued -> received),
    goods receipt creation with quantity validation, total computation,
    and the _check_po_fully_received helper. Repositories are stubbed.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from app.modules.procurement.schemas import GRCreate, POCreate, POItemCreate, POUpdate
from app.modules.procurement.service import (
    ProcurementService,
    _compute_po_total,
    _parse_decimal,
)

# ── Helpers / stubs ───────────────────────────────────────────────────────

PROJECT_ID = uuid.uuid4()


def _make_service() -> ProcurementService:
    service = ProcurementService.__new__(ProcurementService)
    service.session = SimpleNamespace(expunge=lambda _obj: None)
    service.po_repo = _StubPORepo()
    service.po_item_repo = _StubPOItemRepo()
    # Wire the repos so po_repo.get() reflects newly inserted items
    # (mirrors the real selectinload(items) eager-load).
    service.po_repo._item_repo = service.po_item_repo
    service.gr_repo = _StubGRRepo()
    service.gr_item_repo = _StubGRItemRepo()
    return service


class _StubPORepo:
    def __init__(self) -> None:
        self.rows: dict[uuid.UUID, Any] = {}
        self._counter = 0
        self._item_repo: _StubPOItemRepo | None = None

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
        # Mirror the real repository's selectinload(items) so service-level
        # reload-after-insert behaviour can be observed in unit tests.
        if po is not None and self._item_repo is not None:
            po.items = [it for it in self._item_repo.rows.values() if it.po_id == po_id]
        return po

    async def list(
        self,
        *,
        project_id: uuid.UUID | None = None,
        status: str | None = None,
        vendor_contact_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[Any], int]:
        rows = list(self.rows.values())
        if project_id:
            rows = [r for r in rows if r.project_id == project_id]
        if status:
            rows = [r for r in rows if r.status == status]
        return rows[offset : offset + limit], len(rows)

    async def update(self, po_id: uuid.UUID, **kwargs: Any) -> None:
        po = self.rows.get(po_id)
        if po:
            for k, v in kwargs.items():
                setattr(po, k, v)
            po.updated_at = datetime.now(UTC)

    async def next_po_number(self, project_id: uuid.UUID) -> str:
        self._counter += 1
        return f"PO-{self._counter:04d}"

    async def stats_for_project(self, project_id: uuid.UUID) -> dict:
        return {
            "total_pos": len(self.rows),
            "by_status": {},
            "total_committed": "0",
            "total_received": 0,
            "pending_delivery_count": 0,
        }


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

    async def list(
        self,
        *,
        po_id: uuid.UUID | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[Any], int]:
        rows = list(self.rows.values())
        if po_id:
            rows = [r for r in rows if r.po_id == po_id]
        return rows[offset : offset + limit], len(rows)

    async def update(self, gr_id: uuid.UUID, **kwargs: Any) -> None:
        gr = self.rows.get(gr_id)
        if gr:
            for k, v in kwargs.items():
                setattr(gr, k, v)


class _StubGRItemRepo:
    def __init__(self) -> None:
        self.rows: dict[uuid.UUID, Any] = {}

    async def create(self, item: Any) -> Any:
        if getattr(item, "id", None) is None:
            item.id = uuid.uuid4()
        self.rows[item.id] = item
        return item


def _po_data(**overrides: Any) -> POCreate:
    defaults = {
        "project_id": PROJECT_ID,
        "po_type": "standard",
        "amount_subtotal": "1000.00",
        "tax_amount": "190.00",
    }
    defaults.update(overrides)
    return POCreate(**defaults)


def _approvable_po_data(**overrides: Any) -> POCreate:
    """``_po_data`` plus everything approval requires.

    Approval runs the blocking ``procurement`` rule set, which refuses a
    purchase order with no lines, no vendor or no currency. Most tests here
    never approve and keep the leaner :func:`_po_data`; the ones that do need a
    purchase order a buyer could really approve. The single line reconciles with
    the 1000.00 subtotal so the arithmetic rules pass too.
    """
    defaults: dict[str, Any] = {
        "vendor_contact_id": str(uuid.uuid4()),
        "currency_code": "EUR",
        "items": [
            POItemCreate(
                description="Cement",
                quantity="10",
                unit="ton",
                unit_rate="100.00",
                amount="1000.00",
                cost_category="materials",
            ),
        ],
    }
    defaults.update(overrides)
    return _po_data(**defaults)


# ── Tests ─────────────────────────────────────────────────────────────────


def test_compute_po_total() -> None:
    """amount_total = subtotal + tax."""
    assert _compute_po_total("1000.00", "190.00") == "1190.00"
    assert _compute_po_total("0", "0") == "0"


def test_parse_decimal_invalid() -> None:
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc_info:
        _parse_decimal("not-a-number", "test_field")
    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_create_po() -> None:
    svc = _make_service()
    po = await svc.create_po(_po_data(), user_id=str(uuid.uuid4()))

    assert po.id is not None
    assert po.po_number == "PO-0001"
    assert po.amount_total == "1190.00"
    assert po.status == "draft"


@pytest.mark.asyncio
async def test_create_po_with_items() -> None:
    svc = _make_service()
    data = _po_data(
        items=[
            POItemCreate(description="Rebar 12mm", quantity="100", unit="kg", unit_rate="2.50", amount="250"),
            POItemCreate(description="Concrete C30", quantity="10", unit="m3", unit_rate="90", amount="900"),
        ],
    )
    po = await svc.create_po(data)
    # Items are created in the item repo
    assert len(svc.po_item_repo.rows) == 2


@pytest.mark.asyncio
async def test_create_po_persists_items_and_reaggregates_totals() -> None:
    """BUG-015: items[] in body must persist as PO line rows, the returned PO
    must expose them, and amount_subtotal must equal Σ(quantity × unit_rate)
    even when the caller did not provide explicit subtotal/line amounts."""
    svc = _make_service()
    data = POCreate(
        project_id=PROJECT_ID,
        po_number="PO-QA-001",
        items=[
            POItemCreate(description="Cement", quantity="100", unit="ton", unit_rate="120"),
            POItemCreate(description="Sand", quantity="50", unit="ton", unit_rate="40"),
        ],
    )

    po = await svc.create_po(data)

    # Both lines persisted with the correct PO FK
    assert len(svc.po_item_repo.rows) == 2
    persisted = list(svc.po_item_repo.rows.values())
    assert all(it.po_id == po.id for it in persisted)
    by_desc = {it.description: it for it in persisted}
    assert by_desc["Cement"].quantity == "100"
    assert by_desc["Cement"].unit_rate == "120"
    assert by_desc["Cement"].amount == "12000"
    assert by_desc["Sand"].amount == "2000"

    # Aggregated totals: 100*120 + 50*40 = 14000, tax=0
    assert po.amount_subtotal == "14000"
    assert po.amount_total == "14000"

    # Returned PO carries the items collection (no longer dropped)
    assert len(po.items) == 2
    assert {it.description for it in po.items} == {"Cement", "Sand"}


@pytest.mark.asyncio
async def test_issue_po() -> None:
    svc = _make_service()
    po = await svc.create_po(_approvable_po_data())
    assert po.status == "draft"

    # A PO is committed money, so it must be approved before it can be issued
    # to a vendor (TOP-30 #10). Budget is committed at approval.
    approved = await svc.approve_po(po.id)
    assert approved.status == "approved"

    issued = await svc.issue_po(po.id)
    assert issued.status == "issued"


@pytest.mark.asyncio
async def test_issue_po_requires_approval() -> None:
    """A draft PO cannot be issued directly; it must be approved first (TOP-30 #10)."""
    svc = _make_service()
    po = await svc.create_po(_po_data())
    assert po.status == "draft"

    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc_info:
        await svc.issue_po(po.id)
    assert exc_info.value.status_code == 409


@pytest.mark.asyncio
async def test_update_po_status_transition_valid() -> None:
    svc = _make_service()
    po = await svc.create_po(_approvable_po_data())

    # draft -> approved is the first legal transition (TOP-30 #10). PATCH is a
    # second door into ``approved``, so it runs the same blocking rule set as
    # the approve endpoint; the fixture is therefore an approvable PO.
    updated = await svc.update_po(po.id, POUpdate(status="approved"))
    assert updated.status == "approved"


@pytest.mark.asyncio
async def test_patch_into_approved_is_gated_like_approve(monkeypatch: pytest.MonkeyPatch) -> None:
    """PATCH must not be an ungated back door into the committed state.

    ``_PO_STATUS_TRANSITIONS`` allows ``draft -> approved``, so without this
    gate a caller could commit an arithmetically broken PO to the budget just by
    avoiding the approve endpoint.
    """
    from fastapi import HTTPException

    from app.modules.procurement import service as proc_service

    published: list[str] = []
    monkeypatch.setattr(
        proc_service.event_bus,
        "publish_detached",
        lambda name, data, source_module=None: published.append(name),
    )

    svc = _make_service()
    po = await svc.create_po(_approvable_po_data(vendor_contact_id=None))
    published.clear()

    with pytest.raises(HTTPException) as exc_info:
        await svc.update_po(po.id, POUpdate(status="approved"))
    assert exc_info.value.status_code == 422
    assert "procurement.po_vendor_assigned" in str(exc_info.value.detail)

    # The gate runs before anything is announced, so no subscriber acts on a
    # change the request is about to abandon. Undoing the write itself is the
    # request session's job (it commits only on a clean return) and cannot be
    # asserted here: these stub repositories have no transaction.
    assert "procurement.po.updated" not in published


@pytest.mark.asyncio
async def test_patch_into_approved_commits_the_budget_like_approve(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Both doors into ``approved`` must publish the same commitment event.

    Previously only ``approve_po`` published ``procurement.po.approved``, while
    *leaving* ``approved`` published the compensating event from either path. So
    PATCH-approve followed by PATCH-revert decremented the committed total by an
    amount that had never been committed.
    """
    from app.modules.procurement import service as proc_service

    published: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        proc_service.event_bus,
        "publish_detached",
        lambda name, data, source_module=None: published.append((name, data)),
    )

    svc = _make_service()
    po = await svc.create_po(_approvable_po_data())
    published.clear()

    await svc.update_po(po.id, POUpdate(status="approved"))
    approved = [data for name, data in published if name == "procurement.po.approved"]
    assert len(approved) == 1, "PATCH into approved must commit exactly once"
    # Same payload shape as approve_po, so no subscriber can tell the doors apart.
    assert set(approved[0]) == {
        "po_id",
        "project_id",
        "po_number",
        "amount_total",
        "amount_subtotal",
        "currency_code",
        "approver_id",
    }
    assert approved[0]["amount_total"] == po.amount_total
    # Finance commits the net, so the net travels with the event.
    assert approved[0]["amount_subtotal"] == po.amount_subtotal

    # And reverting decommits exactly what was committed, not a phantom amount.
    published.clear()
    await svc.update_po(po.id, POUpdate(status="draft"))
    reverted = [data for name, data in published if name == "procurement.po.reverted"]
    assert len(reverted) == 1
    assert reverted[0]["amount_total"] == approved[0]["amount_total"]


@pytest.mark.asyncio
async def test_patching_an_already_approved_po_does_not_commit_twice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The guard is the transition, not the resulting state.

    Editing a note on an approved PO leaves it approved; committing the amount
    again there would trade one ledger asymmetry for a double commit.
    """
    from app.modules.procurement import service as proc_service

    published: list[str] = []
    monkeypatch.setattr(
        proc_service.event_bus,
        "publish_detached",
        lambda name, data, source_module=None: published.append(name),
    )

    svc = _make_service()
    po = await svc.create_po(_approvable_po_data())
    await svc.update_po(po.id, POUpdate(status="approved"))
    published.clear()

    await svc.update_po(po.id, POUpdate(notes="delivery moved to gate 3"))
    assert "procurement.po.approved" not in published

    # Re-sending the same status is also not a fresh transition.
    published.clear()
    await svc.update_po(po.id, POUpdate(status="approved"))
    assert "procurement.po.approved" not in published


@pytest.mark.asyncio
async def test_patch_may_fix_and_approve_in_one_call() -> None:
    """The gate reads the post-patch state, not the PO as it was read.

    Repairing the purchase order and approving it in the same PATCH is
    legitimate and must pass, otherwise the gate would force a pointless
    two-step.
    """
    svc = _make_service()
    po = await svc.create_po(_approvable_po_data(vendor_contact_id=None))

    updated = await svc.update_po(
        po.id,
        POUpdate(vendor_contact_id=str(uuid.uuid4()), status="approved"),
    )
    assert updated.status == "approved"


@pytest.mark.asyncio
async def test_update_po_status_transition_invalid() -> None:
    """draft -> completed is not a valid transition."""
    svc = _make_service()
    po = await svc.create_po(_po_data())

    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc_info:
        await svc.update_po(po.id, POUpdate(status="completed"))
    assert exc_info.value.status_code == 400
    assert "Cannot transition" in exc_info.value.detail


@pytest.mark.asyncio
async def test_update_po_recomputes_total() -> None:
    svc = _make_service()
    po = await svc.create_po(_po_data())
    assert po.amount_total == "1190.00"

    updated = await svc.update_po(po.id, POUpdate(amount_subtotal="2000.00"))
    assert updated.amount_total == "2190.00"


@pytest.mark.asyncio
async def test_create_goods_receipt_wrong_po_status() -> None:
    """Cannot create GR for a draft PO."""
    svc = _make_service()
    po = await svc.create_po(_po_data())
    assert po.status == "draft"

    from fastapi import HTTPException

    gr_data = GRCreate(po_id=po.id, receipt_date="2026-04-10")
    with pytest.raises(HTTPException) as exc_info:
        await svc.create_goods_receipt(gr_data)
    assert exc_info.value.status_code == 400
    assert "issued or partially_received" in exc_info.value.detail


@pytest.mark.asyncio
async def test_create_goods_receipt_success() -> None:
    svc = _make_service()
    po = await svc.create_po(_po_data())
    svc.po_repo.rows[po.id].status = "issued"

    gr_data = GRCreate(po_id=po.id, receipt_date="2026-04-10")
    gr = await svc.create_goods_receipt(gr_data)
    assert gr.id is not None
    assert gr.po_id == po.id


def test_check_po_fully_received_empty_items() -> None:
    """PO with no items is considered fully received."""
    po = SimpleNamespace(items=[], goods_receipts=[])
    assert ProcurementService._check_po_fully_received(po) is True


def test_check_po_fully_received_partial() -> None:
    """PO with items not fully received returns False."""
    po_item_id = uuid.uuid4()
    po_item = SimpleNamespace(id=po_item_id, quantity="100")
    gr_item = SimpleNamespace(po_item_id=po_item_id, quantity_received="50")
    gr = SimpleNamespace(status="confirmed", items=[gr_item])
    po = SimpleNamespace(items=[po_item], goods_receipts=[gr])

    assert ProcurementService._check_po_fully_received(po) is False


def test_check_po_fully_received_complete() -> None:
    """PO fully received returns True."""
    po_item_id = uuid.uuid4()
    po_item = SimpleNamespace(id=po_item_id, quantity="100")
    gr_item = SimpleNamespace(po_item_id=po_item_id, quantity_received="100")
    gr = SimpleNamespace(status="confirmed", items=[gr_item])
    po = SimpleNamespace(items=[po_item], goods_receipts=[gr])

    assert ProcurementService._check_po_fully_received(po) is True


# ── P0-1: 3-way match must report ``no_confirmed_grs`` ─────────────────────


def _make_po_namespace_for_match(
    *,
    gr_status: str | None = None,
) -> SimpleNamespace:
    """Build a minimal PO/GR/item graph for ``_validate_3way_match`` tests."""
    po_item_id = uuid.uuid4()
    po_item = SimpleNamespace(
        id=po_item_id,
        description="Cement",
        quantity="100",
        sort_order=0,
    )
    goods_receipts: list[Any] = []
    if gr_status is not None:
        gr_item = SimpleNamespace(po_item_id=po_item_id, quantity_received="100")
        gr = SimpleNamespace(status=gr_status, items=[gr_item])
        goods_receipts = [gr]
    po = SimpleNamespace(
        items=[po_item],
        goods_receipts=goods_receipts,
        po_number="PO-X",
    )
    return po, po_item_id


def test_validate_3way_match_draft_only_returns_no_confirmed_grs_reason() -> None:
    """Only-draft GRs (and a positive invoice) → ``no_confirmed_grs`` violation."""
    from app.modules.procurement.service import _validate_3way_match

    po, po_item_id = _make_po_namespace_for_match(gr_status="draft")
    proposed = [
        {
            "ordinal": 0,
            "po_item_id": po_item_id,
            "quantity": "100",
            "description": "Cement",
        }
    ]

    violations = _validate_3way_match(po, proposed)

    assert len(violations) == 1
    v = violations[0]
    assert v["reason"] == "no_confirmed_grs"
    assert v["has_draft_grs"] is True
    assert v["has_any_grs"] is True
    assert "draft" in v["message"].lower()


def test_validate_3way_match_no_grs_returns_no_confirmed_grs_reason() -> None:
    """Zero GRs (and a positive invoice) → ``no_confirmed_grs`` violation."""
    from app.modules.procurement.service import _validate_3way_match

    po, po_item_id = _make_po_namespace_for_match(gr_status=None)
    proposed = [
        {
            "ordinal": 0,
            "po_item_id": po_item_id,
            "quantity": "50",
            "description": "Cement",
        }
    ]

    violations = _validate_3way_match(po, proposed)

    assert len(violations) == 1
    v = violations[0]
    assert v["reason"] == "no_confirmed_grs"
    assert v["has_draft_grs"] is False
    assert v["has_any_grs"] is False


def test_validate_3way_match_confirmed_sufficient_returns_empty() -> None:
    """Confirmed GR covers the invoice quantity → no violations."""
    from app.modules.procurement.service import _validate_3way_match

    po, po_item_id = _make_po_namespace_for_match(gr_status="confirmed")
    proposed = [
        {
            "ordinal": 0,
            "po_item_id": po_item_id,
            "quantity": "100",
            "description": "Cement",
        }
    ]

    violations = _validate_3way_match(po, proposed)

    assert violations == []


def test_validate_3way_match_over_invoice_reason_qty_exceeds() -> None:
    """Invoice qty > received → ``qty_exceeds_received`` reason (NOT ``no_confirmed_grs``)."""
    from app.modules.procurement.service import _validate_3way_match

    # Confirmed GR receives only 50, but invoice asks for 100.
    po_item_id = uuid.uuid4()
    po_item = SimpleNamespace(
        id=po_item_id,
        description="Cement",
        quantity="100",
        sort_order=0,
    )
    gr_item = SimpleNamespace(po_item_id=po_item_id, quantity_received="50")
    gr = SimpleNamespace(status="confirmed", items=[gr_item])
    po = SimpleNamespace(items=[po_item], goods_receipts=[gr], po_number="PO-X")

    proposed = [
        {
            "ordinal": 0,
            "po_item_id": po_item_id,
            "quantity": "100",
            "description": "Cement",
        }
    ]

    violations = _validate_3way_match(po, proposed)

    assert len(violations) == 1
    assert violations[0]["reason"] == "qty_exceeds_received"
    assert violations[0]["requested_qty"] == "100"
    assert violations[0]["received_qty"] == "50"
