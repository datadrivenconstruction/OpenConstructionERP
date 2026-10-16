# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Removal verbs for a purchase order: cancel (void) and delete.

A purchase order is a commercial document, so "get rid of it" is three
different operations depending on what the document has already done:

* a ``draft`` PO that never left ``draft`` and that nothing points at may be
  deleted outright - budget commits at ``approved``, so a PO that was never
  approved has no finance marker to compensate and no number a supplier has
  seen;
* a PO that has been approved or issued must be CANCELLED, which keeps the
  row and its ``po_number`` and flips the status to ``cancelled``;
* a PO that goods receipts, retainage releases, payable invoices or
  requisitions point at is refused with 409, naming every holder by kind and
  count, because destroying it would take an audit trail with it.

The same holder guard has to sit behind every door into ``cancelled``. There
are two: the dedicated ``cancel_po`` verb and a PATCH that sets
``status="cancelled"``. A guard on only one of them is bypassable, which is
the failure mode the module already documented for the two doors into
``approved``.

Repositories are stubbed, mirroring ``test_procurement_data_integrity.py``.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi import HTTPException

from app.modules.procurement.schemas import POCreate, POUpdate
from app.modules.procurement.service import ProcurementService

PROJECT_ID = uuid.uuid4()


# ── Stubs ──────────────────────────────────────────────────────────────────


class _StubPORepo:
    """PO repository stub carrying the dependent counts the guard reads.

    ``holders`` is the dial the tests turn: it maps the holder kind to the
    number of rows pointing at the PO, so a test can state "two goods
    receipts and one payable invoice" without a database.
    """

    def __init__(self) -> None:
        self.rows: dict[uuid.UUID, Any] = {}
        self._counter = 0
        self._item_repo: _StubPOItemRepo | None = None
        self.holders: dict[str, int] = {}
        self.left_draft: bool = False
        self.deleted: list[uuid.UUID] = []
        #: Ordered log of the calls the removal path makes, so a test can
        #: assert that the row lock is taken BEFORE anything is counted.
        self.calls: list[str] = []

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
        """Record that the row lock was taken.

        There is no database behind this stub, so this can say nothing about
        whether ``FOR UPDATE`` actually serialises anything - only a
        PostgreSQL-backed test could. What it CAN pin down is ordering, which
        is the half of the fix that lives in this module: the lock has to be
        taken before the guard counts, or the counts are answering about a
        row nothing is holding still.
        """
        self.calls.append("lock")

    # ── Dependent counts read by the removal guard ─────────────────────

    async def count_goods_receipts(self, po_id: uuid.UUID) -> int:
        self.calls.append("count_goods_receipts")
        return self.holders.get("goods_receipt", 0)

    async def count_retainage_releases(self, po_id: uuid.UUID) -> int:
        self.calls.append("count_retainage_releases")
        return self.holders.get("retainage_release", 0)

    async def count_requisitions(self, po_id: uuid.UUID) -> int:
        self.calls.append("count_requisitions")
        return self.holders.get("requisition", 0)

    async def count_payable_invoices(self, po_id: uuid.UUID, project_id: uuid.UUID) -> int:
        self.calls.append("count_payable_invoices")
        return self.holders.get("payable_invoice", 0)

    async def has_left_draft(self, po_id: uuid.UUID) -> bool:
        self.calls.append("has_left_draft")
        return self.left_draft

    async def delete(self, po_id: uuid.UUID) -> None:
        self.calls.append("delete")
        self.deleted.append(po_id)
        self.rows.pop(po_id, None)


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


class _EmptyResult:
    def all(self) -> list[Any]:
        return []

    def scalars(self) -> _EmptyResult:
        # The requisition release (issue #516) reads rows as scalars; the
        # stub has none to release, so the holder counts below decide.
        return self

    def scalar_one_or_none(self) -> Any:
        return None


class _StubSession:
    def expunge(self, _obj: Any) -> None:  # noqa: D401 - stub
        return None

    async def execute(self, _stmt: Any) -> _EmptyResult:
        return _EmptyResult()


def _make_service() -> ProcurementService:
    svc = ProcurementService.__new__(ProcurementService)
    svc.session = _StubSession()
    svc.po_repo = _StubPORepo()
    svc.po_item_repo = _StubPOItemRepo()
    svc.po_repo._item_repo = svc.po_item_repo
    return svc


def _po_data(**overrides: Any) -> POCreate:
    defaults = {
        "project_id": PROJECT_ID,
        "po_type": "standard",
        "amount_subtotal": "1000.00",
        "tax_amount": "0",
    }
    defaults.update(overrides)
    return POCreate(**defaults)


def _holder_kinds(detail: Any) -> dict[str, int]:
    """Flatten a structured 409 detail into ``{kind: count}``."""
    assert isinstance(detail, dict), f"409 detail must be structured, got {type(detail)}"
    return {h["kind"]: h["count"] for h in detail.get("holders", [])}


# ── 1. Cancel refuses while holders exist (the PATCH door) ─────────────────


@pytest.mark.asyncio
async def test_patch_to_cancelled_blocked_when_goods_receipts_exist() -> None:
    """PATCH status='cancelled' on a received-against PO is a 409.

    This is the door that exists today, so it is the one that proves the
    guard is not bypassable. Cancelling a PO that has been delivered against
    would leave confirmed goods receipts pointing at a voided commitment and
    strip the commitment from under the three-way match.
    """
    svc = _make_service()
    po = await svc.create_po(_po_data())
    svc.po_repo.rows[po.id].status = "issued"
    svc.po_repo.holders = {"goods_receipt": 2}

    with pytest.raises(HTTPException) as exc:
        await svc.update_po(po.id, POUpdate(status="cancelled"))

    assert exc.value.status_code == 409
    assert _holder_kinds(exc.value.detail) == {"goods_receipt": 2}
    assert svc.po_repo.rows[po.id].status == "issued", "the refusal must not have moved the status"


@pytest.mark.asyncio
async def test_cancel_po_blocked_when_holders_exist_named_by_kind_and_count() -> None:
    """The dedicated cancel verb names every holder, not just the first."""
    svc = _make_service()
    po = await svc.create_po(_po_data())
    svc.po_repo.rows[po.id].status = "issued"
    svc.po_repo.holders = {"goods_receipt": 2, "payable_invoice": 1, "retainage_release": 3}

    with pytest.raises(HTTPException) as exc:
        await svc.cancel_po(po.id, reason="ordered in error")

    assert exc.value.status_code == 409
    assert _holder_kinds(exc.value.detail) == {
        "goods_receipt": 2,
        "payable_invoice": 1,
        "retainage_release": 3,
    }


# ── 2. Cancel keeps the record and its number ──────────────────────────────


@pytest.mark.asyncio
async def test_cancel_po_keeps_the_row_and_the_number() -> None:
    """An issued PO with no holders is voided, not deleted.

    The row survives with its ``po_number`` intact - that number is what the
    supplier quotes, and a gap in the sequence is what an auditor asks about.
    """
    svc = _make_service()
    po = await svc.create_po(_po_data())
    number = po.po_number
    svc.po_repo.rows[po.id].status = "issued"

    cancelled = await svc.cancel_po(po.id, reason="supplier withdrew")

    assert cancelled.status == "cancelled"
    assert cancelled.po_number == number
    assert svc.po_repo.deleted == [], "cancel must never delete the row"


@pytest.mark.asyncio
async def test_cancel_po_records_the_reason() -> None:
    """The void reason is kept on the PO so the record explains itself."""
    svc = _make_service()
    po = await svc.create_po(_po_data())
    svc.po_repo.rows[po.id].status = "issued"

    cancelled = await svc.cancel_po(po.id, reason="duplicate of PO-0007")

    assert cancelled.metadata_["cancellation"]["reason"] == "duplicate of PO-0007"


@pytest.mark.asyncio
async def test_cancel_po_rejects_a_terminal_po() -> None:
    """A completed PO is terminal; cancelling it is a 409, not a silent no-op."""
    svc = _make_service()
    po = await svc.create_po(_po_data())
    svc.po_repo.rows[po.id].status = "completed"

    with pytest.raises(HTTPException) as exc:
        await svc.cancel_po(po.id, reason="too late")
    assert exc.value.status_code == 409


# ── 3. Delete is draft-only and holder-free ────────────────────────────────


@pytest.mark.asyncio
async def test_delete_po_allowed_for_an_untouched_draft() -> None:
    """The mistyped PO nobody has seen can go away completely."""
    svc = _make_service()
    po = await svc.create_po(_po_data())

    await svc.delete_po(po.id)

    assert svc.po_repo.deleted == [po.id]


@pytest.mark.asyncio
async def test_delete_po_refuses_an_issued_po_and_points_at_cancel() -> None:
    """An issued PO is never deleted; the refusal names the verb that applies."""
    svc = _make_service()
    po = await svc.create_po(_po_data())
    svc.po_repo.rows[po.id].status = "issued"

    with pytest.raises(HTTPException) as exc:
        await svc.delete_po(po.id)

    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "purchase_order_not_deletable"
    assert svc.po_repo.deleted == []


@pytest.mark.asyncio
async def test_delete_po_refuses_a_draft_that_was_reopened_from_cancelled() -> None:
    """A PO reverted to draft after being issued is not an untouched draft.

    The FSM allows ``cancelled -> draft``, so current status alone cannot tell
    a never-issued PO from one whose number a supplier already has. The audit
    trail is the evidence, and it says this one left draft.
    """
    svc = _make_service()
    po = await svc.create_po(_po_data())
    svc.po_repo.left_draft = True

    with pytest.raises(HTTPException) as exc:
        await svc.delete_po(po.id)

    assert exc.value.status_code == 409
    assert svc.po_repo.deleted == []


@pytest.mark.asyncio
async def test_delete_po_refuses_a_draft_with_holders_naming_them() -> None:
    """Even a draft is held by a requisition that points at it and is past ``ordered``.

    A requisition still only ``ordered`` is released back to ``approved`` before
    the count (issue #516); one that has started receiving stays a holder.

    ``MaterialRequisition.po_id`` is ``ON DELETE SET NULL``, so a raw delete
    does not fail - it silently unlinks the requisition that raised this PO.
    """
    svc = _make_service()
    po = await svc.create_po(_po_data())
    svc.po_repo.holders = {"requisition": 1}

    with pytest.raises(HTTPException) as exc:
        await svc.delete_po(po.id)

    assert exc.value.status_code == 409
    assert _holder_kinds(exc.value.detail) == {"requisition": 1}
    assert svc.po_repo.deleted == []


@pytest.mark.asyncio
async def test_delete_po_404_for_a_missing_row() -> None:
    """Deleting something that is not there is a 404, not a silent success."""
    svc = _make_service()
    with pytest.raises(HTTPException) as exc:
        await svc.delete_po(uuid.uuid4())
    assert exc.value.status_code == 404


# ── 4. Cancelling an issued PO releases the budget commitment ──────────────


@pytest.mark.asyncio
async def test_cancel_from_issued_publishes_the_decommit_event(monkeypatch: Any) -> None:
    """Finance must shed the commitment when an issued PO is voided.

    Budget commits at ``approved`` and is not released by ``approved ->
    issued``, so a PO cancelled out of ``issued`` still carries a live
    ``committed_from_po`` marker. Without ``procurement.po.cancelled`` the
    committed figure keeps a phantom commitment for good.
    """
    published: list[tuple[str, dict]] = []

    async def _capture(event_type: str, data: dict, **_kw: Any) -> None:
        published.append((event_type, data))

    import app.modules.procurement.service as svc_mod

    monkeypatch.setattr(svc_mod, "_safe_publish", _capture)

    svc = _make_service()
    po = await svc.create_po(_po_data())
    svc.po_repo.rows[po.id].status = "issued"

    await svc.cancel_po(po.id, reason="site stood down")

    names = [name for name, _ in published]
    assert "procurement.po.cancelled" in names, f"published {names}"


# ── 5. The removal path holds the row while it decides ─────────────────────
#
# These pin ORDERING only. The stub has no database, so nothing here proves
# that ``FOR UPDATE`` serialises anything - that would take a PostgreSQL-backed
# test running two concurrent transactions. What they do prove is the half
# that lives in this module: every question the removal path asks is asked
# after the row is locked. Without that ordering the counts describe a row
# nothing is holding still, and a goods receipt inserted in the window is
# CASCADEd away by the delete without an error.


@pytest.mark.asyncio
async def test_delete_locks_the_row_before_it_asks_anything_about_it() -> None:
    """The lock precedes the status trail read, the counts and the delete."""
    svc = _make_service()
    po = await svc.create_po(_po_data())

    await svc.delete_po(po.id)

    calls = svc.po_repo.calls
    assert "lock" in calls, f"the removal path never took the row lock: {calls}"
    assert calls[0] == "lock", f"something ran before the lock was taken: {calls}"
    # Every read the decision rests on, and the write itself, come after it.
    for later in ("has_left_draft", "count_goods_receipts", "delete"):
        assert later in calls, f"{later} never ran: {calls}"
        assert calls.index("lock") < calls.index(later), f"{later} ran before the lock: {calls}"


@pytest.mark.asyncio
async def test_cancel_locks_the_row_before_it_counts_holders() -> None:
    """The dedicated cancel verb takes the same lock before counting."""
    svc = _make_service()
    po = await svc.create_po(_po_data())
    svc.po_repo.rows[po.id].status = "issued"

    await svc.cancel_po(po.id, reason="site stood down")

    calls = svc.po_repo.calls
    assert calls[0] == "lock", f"something ran before the lock was taken: {calls}"
    assert calls.index("lock") < calls.index("count_goods_receipts"), f"counted before locking: {calls}"


@pytest.mark.asyncio
async def test_patch_door_to_cancelled_also_locks_before_counting() -> None:
    """The PATCH door reaches the guard, so it inherits the guard's lock.

    The lock lives in ``_refuse_if_po_is_held`` rather than in each caller
    precisely so this door cannot skip it. A door that counts without locking
    is a door somebody can walk around.
    """
    svc = _make_service()
    po = await svc.create_po(_po_data())
    svc.po_repo.rows[po.id].status = "issued"

    await svc.update_po(po.id, POUpdate(status="cancelled"))

    calls = svc.po_repo.calls
    assert "lock" in calls, f"the PATCH door counted without locking: {calls}"
    assert calls.index("lock") < calls.index("count_goods_receipts"), f"counted before locking: {calls}"
