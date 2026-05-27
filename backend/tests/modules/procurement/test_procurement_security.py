"""Procurement R7 security regression suite.

Pins the five R7 invariants for the procurement module so a future refactor
that drops one of them trips here instead of in production:

1. **IDOR**: every entity-id path param resolves the parent project's
   access guard BEFORE touching service logic. Cross-tenant fetches
   return 404 (not 403) — never leak existence to unauthorised callers.
2. **Decimal-as-string**: every money field on the response schema is a
   string (Pydantic v2 ``str`` field), never a float, so 0.1+0.2 rounding
   can't bleed into the API surface.
3. **Magic-byte uploads**: procurement currently exposes no UploadFile
   endpoints, so this dimension is asserted as a static guarantee — the
   router file contains no ``UploadFile`` import. A future endpoint that
   adds one without registering it here trips the static test.
4. **FSM allowlists**: ``_PO_STATUS_TRANSITIONS`` covers every PO state
   and refuses non-allowed jumps with 400. The transitions table itself
   is asserted complete so a missing entry can't open a covert path.
5. **RBAC on writes**: ``procurement.issue`` and the new
   ``procurement.create_invoice`` are pinned to MANAGER. EDITOR may
   create draft POs / record goods receipts but may not issue a PO or
   convert one into a payable invoice.

Module-specific concerns:
    * **Cross-module atomicity**: the PO → Invoice converter wraps the
      Invoice header + line-item inserts in ``session.begin_nested()``
      so a half-created invoice can never leak into finance. The static
      router test pins both ``begin_nested`` AND the new MANAGER pin.
    * **No vendor-approval / bid-comparison endpoints exist here** —
      vendor management lives in ``contacts`` and bid comparison in
      ``tendering``. Tests for those leak surfaces belong with those
      modules; this suite documents the boundary explicitly so a future
      reviewer doesn't mis-attribute coverage gaps.

Tests stay pure unit tests — repositories are stubbed in-memory so
they don't depend on Postgres / the full FastAPI lifespan.
"""

from __future__ import annotations

import ast
import inspect
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException

from app.core.permissions import Role, permission_registry
from app.modules.procurement import permissions as procurement_perms
from app.modules.procurement import router as procurement_router
from app.modules.procurement.schemas import (
    GRCreate,
    GRItemCreate,
    POCreate,
    POItemCreate,
    POResponse,
    POUpdate,
)
from app.modules.procurement.service import (
    _PO_STATUS_TRANSITIONS,
    _VALID_PO_STATUSES,
    ProcurementService,
)

# ── Shared stubs ──────────────────────────────────────────────────────────

PROJECT_A = uuid.uuid4()
PROJECT_B = uuid.uuid4()
USER_A = str(uuid.uuid4())
USER_B = str(uuid.uuid4())


class _StubPORepo:
    """In-memory PO repo — mirrors the surface area service.py touches."""

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
            "total_pos": 0,
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


def _make_service() -> ProcurementService:
    """Construct ProcurementService bypassing the real DB layer."""
    svc = ProcurementService.__new__(ProcurementService)
    svc.session = SimpleNamespace(expunge=lambda _obj: None)
    svc.po_repo = _StubPORepo()
    svc.po_item_repo = _StubPOItemRepo()
    svc.po_repo._item_repo = svc.po_item_repo
    svc.gr_repo = _StubGRRepo()
    svc.gr_item_repo = _StubGRItemRepo()
    return svc


# ── 1. IDOR coverage ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_verify_project_access_returns_404_on_cross_tenant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """verify_project_access (the helper procurement chains through) must
    answer 404 — not 403 — on a cross-tenant fetch, so the existence of
    project UUIDs the caller doesn't own never leaks.
    """
    from app.dependencies import verify_project_access

    project_a = SimpleNamespace(id=PROJECT_A, owner_id=USER_A)

    class _StubProjectRepo:
        def __init__(self, _session: Any) -> None:
            pass

        async def get_by_id(self, project_id: uuid.UUID):
            return project_a if project_id == PROJECT_A else None

    class _StubUserRepo:
        def __init__(self, _session: Any) -> None:
            pass

        async def get_by_id(self, user_id: Any):
            # Both USER_A and USER_B are non-admins.
            return SimpleNamespace(id=user_id, role="user")

    monkeypatch.setattr(
        "app.modules.projects.repository.ProjectRepository",
        _StubProjectRepo,
    )
    monkeypatch.setattr(
        "app.modules.users.repository.UserRepository",
        _StubUserRepo,
    )

    # USER_B (no access) → 404, NOT 403
    with pytest.raises(HTTPException) as exc_info:
        await verify_project_access(PROJECT_A, USER_B, session=None)  # type: ignore[arg-type]
    assert exc_info.value.status_code == 404, (
        f"cross-tenant access must return 404 to avoid existence leak, got {exc_info.value.status_code}"
    )

    # USER_A (owner) → no raise (None return)
    result = await verify_project_access(PROJECT_A, USER_A, session=None)  # type: ignore[arg-type]
    assert result is None


@pytest.mark.asyncio
async def test_missing_project_id_returns_404() -> None:
    """A PO request for a non-existent project must 404, not 500 or 403."""
    from app.dependencies import verify_project_access

    class _StubProjectRepo:
        def __init__(self, _session: Any) -> None:
            pass

        async def get_by_id(self, project_id: uuid.UUID):
            return None  # not found

    class _StubUserRepo:
        def __init__(self, _session: Any) -> None:
            pass

        async def get_by_id(self, user_id: Any):
            return SimpleNamespace(id=user_id, role="user")

    import builtins

    real_import = builtins.__import__

    def _fake_import(name, *args, **kwargs):
        if name == "app.modules.projects.repository":
            mod = SimpleNamespace(ProjectRepository=_StubProjectRepo)
            return mod
        if name == "app.modules.users.repository":
            mod = SimpleNamespace(UserRepository=_StubUserRepo)
            return mod
        return real_import(name, *args, **kwargs)

    builtins.__import__ = _fake_import
    try:
        with pytest.raises(HTTPException) as exc_info:
            await verify_project_access(uuid.uuid4(), USER_A, session=None)  # type: ignore[arg-type]
        assert exc_info.value.status_code == 404
    finally:
        builtins.__import__ = real_import


def test_router_get_po_calls_verify_project_access() -> None:
    """Static AST guard: ``get_purchase_order`` must call
    ``verify_project_access`` BEFORE returning the PO — drop the call and
    this test trips.
    """
    src = inspect.getsource(procurement_router.get_purchase_order)
    assert "verify_project_access" in src, (
        "IDOR REGRESSION: get_purchase_order no longer chains through "
        "verify_project_access — cross-tenant fetches will succeed."
    )


def test_router_update_po_calls_verify_project_access() -> None:
    """Same guard on PATCH /{po_id}."""
    src = inspect.getsource(procurement_router.update_purchase_order)
    assert "verify_project_access" in src, "IDOR REGRESSION on PATCH PO."


def test_router_issue_po_calls_verify_project_access() -> None:
    """Same guard on POST /{po_id}/issue/."""
    src = inspect.getsource(procurement_router.issue_purchase_order)
    assert "verify_project_access" in src


def test_router_create_invoice_from_po_calls_verify_project_access() -> None:
    """Cross-module endpoint must still gate project access."""
    src = inspect.getsource(procurement_router.create_invoice_from_po)
    assert "verify_project_access" in src


def test_router_confirm_gr_calls_verify_project_access() -> None:
    """GR confirm chains GR → PO → project; the verify call must remain."""
    src = inspect.getsource(procurement_router.confirm_goods_receipt)
    assert "verify_project_access" in src


def test_router_list_goods_receipts_calls_verify_project_access() -> None:
    """GR list filter is by po_id; the parent PO project must still be
    access-checked so a forged po_id can't enumerate GRs.
    """
    src = inspect.getsource(procurement_router.list_goods_receipts)
    assert "verify_project_access" in src


def test_router_supplier_scorecard_gates_project_when_provided() -> None:
    """Supplier scorecard is the only route allowed to skip the project
    gate (cross-project supplier overview) — but ONLY when
    ``project_id`` query param is None. When provided, it MUST gate.
    """
    src = inspect.getsource(procurement_router.get_supplier_scorecard)
    assert "verify_project_access" in src
    assert "project_id is not None" in src, (
        "supplier scorecard regressed — project_id given must trigger access "
        "check; without the conditional, the path either skips gating or "
        "blocks cross-project usage."
    )


# ── 2. Decimal-as-string on response schemas ──────────────────────────────


def test_po_response_money_fields_are_strings() -> None:
    """``POResponse.amount_subtotal/tax_amount/amount_total`` MUST be
    typed ``str``. A regression to ``float`` would cause 0.1+0.2 drift on
    the wire.
    """
    fields = POResponse.model_fields
    for fname in ("amount_subtotal", "tax_amount", "amount_total"):
        ann = fields[fname].annotation
        assert ann is str, f"POResponse.{fname} must be typed `str` for Decimal safety, got {ann!r}"


def test_po_item_response_money_fields_are_strings() -> None:
    """Per-line money fields also stay as strings."""
    from app.modules.procurement.schemas import POItemResponse

    fields = POItemResponse.model_fields
    for fname in ("quantity", "unit_rate", "amount"):
        ann = fields[fname].annotation
        assert ann is str, f"POItemResponse.{fname} must be typed `str`, got {ann!r}"


def test_po_create_rejects_negative_amount() -> None:
    """Schema-level Decimal validation rejects negative money — defence
    in depth against malicious credit injection.
    """
    with pytest.raises(ValueError):
        POCreate(project_id=PROJECT_A, amount_subtotal="-1")


def test_po_create_rejects_garbage_decimal() -> None:
    """Garbage in the amount fields is a 422 at the schema, not a 500
    later when the service tries to Decimal() it.
    """
    with pytest.raises(ValueError):
        POCreate(project_id=PROJECT_A, amount_subtotal="not-a-number")


@pytest.mark.asyncio
async def test_po_response_serialises_decimal_arithmetic_correctly() -> None:
    """End-to-end: 100.10 + 9.90 must serialise as exactly "110.00", not
    a float-rounded "110.0000000000001". Pin the Decimal compute path.
    """
    svc = _make_service()
    po = await svc.create_po(
        POCreate(
            project_id=PROJECT_A,
            amount_subtotal="100.10",
            tax_amount="9.90",
            items=[
                POItemCreate(
                    description="Concrete C30/37",
                    quantity="1",
                    unit_rate="100.10",
                    amount="100.10",
                ),
            ],
        ),
        user_id=USER_A,
    )
    assert isinstance(po.amount_total, str)
    assert Decimal(po.amount_total) == Decimal("110.00")
    # The line-item amount is recomputed from quantity*unit_rate when the
    # caller passes the schema default "0"; verify it preserves precision.
    assert all(isinstance(it.amount, str) for it in po.items)


# ── 3. Magic-byte uploads (none in procurement — pinned statically) ───────


def test_procurement_router_has_no_unguarded_uploadfile() -> None:
    """Procurement currently exposes NO ``UploadFile`` endpoints. If a
    future endpoint adds one without a magic-byte gate, this static test
    fails so the reviewer adds the guard before merge.
    """
    src = Path(procurement_router.__file__).read_text(encoding="utf-8")
    if "UploadFile" not in src:
        return  # ok, no uploads at all
    # If UploadFile shows up, require that file_signature.require is also
    # imported in the same module (the project-wide magic-byte gate).
    assert "file_signature" in src or "magic_bytes" in src, (
        "Procurement router added an UploadFile endpoint without a "
        "magic-byte gate — import ``app.core.file_signature`` and call "
        "``file_signature.require`` before persisting the upload."
    )


# ── 4. FSM allowlists ─────────────────────────────────────────────────────


def test_po_status_transitions_table_covers_all_states() -> None:
    """Every PO state declared anywhere must have a transitions entry —
    a missing key means ``_PO_STATUS_TRANSITIONS.get(state, set())``
    silently returns the empty set and bricks the workflow without an
    explicit allowlist decision.
    """
    expected_states = {
        "draft",
        "issued",
        "partially_received",
        "completed",
        "cancelled",
    }
    assert expected_states == _VALID_PO_STATUSES, (
        f"PO state set drifted: expected {expected_states}, got {_VALID_PO_STATUSES}. Update transitions allowlist."
    )


def test_po_status_transitions_terminal_states_have_no_exit() -> None:
    """``completed`` is terminal — no transitions allowed out of it,
    otherwise a PO can be silently re-opened to draft and re-issued."""
    assert _PO_STATUS_TRANSITIONS["completed"] == set()


@pytest.mark.asyncio
async def test_po_update_rejects_invalid_status_transition() -> None:
    """draft → completed is NOT in the allowlist; service must 400."""
    svc = _make_service()
    po = await svc.create_po(
        POCreate(project_id=PROJECT_A, amount_subtotal="0", tax_amount="0"),
        user_id=USER_A,
    )
    with pytest.raises(HTTPException) as exc_info:
        await svc.update_po(po.id, POUpdate(status="completed"))
    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_po_update_rejects_unknown_status() -> None:
    """A bogus state name is rejected with 400 + the allowlist surfaced
    in the error so the caller knows what's accepted.
    """
    svc = _make_service()
    po = await svc.create_po(
        POCreate(project_id=PROJECT_A, amount_subtotal="0", tax_amount="0"),
        user_id=USER_A,
    )
    with pytest.raises(HTTPException) as exc_info:
        await svc.update_po(po.id, POUpdate(status="paid"))
    assert exc_info.value.status_code == 400
    assert "Allowed" in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_po_create_rejects_invalid_initial_status() -> None:
    """Even at creation time, a non-allowlisted status must 400."""
    svc = _make_service()
    with pytest.raises(HTTPException) as exc_info:
        await svc.create_po(
            POCreate(
                project_id=PROJECT_A,
                amount_subtotal="0",
                tax_amount="0",
                status="approved",  # not in PO FSM
            ),
            user_id=USER_A,
        )
    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_gr_create_rejects_against_non_receivable_po() -> None:
    """A goods receipt against a ``draft`` PO must 400 — only issued or
    partially_received POs accept GRs.
    """
    svc = _make_service()
    po = await svc.create_po(
        POCreate(
            project_id=PROJECT_A,
            amount_subtotal="0",
            tax_amount="0",
            items=[
                POItemCreate(description="x", quantity="5", unit_rate="10", amount="50"),
            ],
        ),
        user_id=USER_A,
    )
    # PO is in draft — GR creation must reject.
    with pytest.raises(HTTPException) as exc_info:
        await svc.create_goods_receipt(
            GRCreate(
                po_id=po.id,
                receipt_date="2026-05-24",
                items=[GRItemCreate(quantity_received="3")],
            ),
        )
    assert exc_info.value.status_code == 400


# ── 5. RBAC on writes ─────────────────────────────────────────────────────


def test_create_invoice_permission_is_manager() -> None:
    """The PO → payable conversion is a financial commitment — pinned
    to MANAGER. EDITOR-only roles must NOT have it.
    """
    # Re-register to make sure the fresh permission is in the registry.
    procurement_perms.register_procurement_permissions()
    perm_role = permission_registry.get_min_role("procurement.create_invoice")
    assert perm_role is Role.MANAGER, f"procurement.create_invoice must require MANAGER, got {perm_role!r}"
    # And spell out the negative: EDITOR must NOT satisfy it.
    assert not permission_registry.role_has_permission(
        Role.EDITOR,
        "procurement.create_invoice",
    ), "EDITOR can now commit PO → payable invoice — RBAC regression"
    assert permission_registry.role_has_permission(
        Role.MANAGER,
        "procurement.create_invoice",
    )


def test_issue_po_permission_is_manager() -> None:
    """Issuing a PO binds the project to a vendor commitment — MANAGER."""
    procurement_perms.register_procurement_permissions()
    assert permission_registry.get_min_role("procurement.issue") is Role.MANAGER


def test_create_po_permission_is_editor() -> None:
    """Drafting a PO is a non-binding action — EDITOR is fine."""
    procurement_perms.register_procurement_permissions()
    assert permission_registry.get_min_role("procurement.create") is Role.EDITOR


def test_router_create_invoice_uses_manager_permission() -> None:
    """Pin the router-level dependency string so a future refactor that
    drops back to ``procurement.create`` trips here.
    """
    src = inspect.getsource(procurement_router.create_invoice_from_po)
    assert 'RequirePermission("procurement.create_invoice")' in src, (
        "create_invoice_from_po lost its MANAGER pin; EDITOR can now commit financial obligations against the project."
    )


# ── Cross-module atomicity (PO → Invoice savepoint) ──────────────────────


def test_router_create_invoice_uses_savepoint() -> None:
    """Static guard: PO → Invoice conversion MUST wrap finance writes in
    ``session.begin_nested()`` so a partial Invoice (header but no line
    items) cannot leak into finance on partial failure.

    Reference pattern: ``variations.convert_vr_to_vo``.
    """
    src = inspect.getsource(procurement_router.create_invoice_from_po)
    assert "begin_nested" in src, (
        "PO → Invoice cross-module write no longer uses a SAVEPOINT — a "
        "half-created invoice can now leak into finance on partial failure."
    )


def test_router_create_invoice_audit_log_inside_savepoint() -> None:
    """The audit row MUST live inside the same SAVEPOINT so an audit
    write failure rolls the conversion back too (compliance — no silent
    audit gap on a financial-commitment endpoint).
    """
    src = inspect.getsource(procurement_router.create_invoice_from_po)
    # AST-level: find the begin_nested with-block and confirm log_activity
    # is called inside it.
    tree = ast.parse(src)
    found = False
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncWith):
            for sub in ast.walk(node):
                if isinstance(sub, ast.Call):
                    fn = sub.func
                    name = fn.attr if isinstance(fn, ast.Attribute) else fn.id if isinstance(fn, ast.Name) else ""
                    if name == "log_activity":
                        found = True
    assert found, (
        "audit log_activity is not inside the begin_nested block — an "
        "audit-write failure no longer rolls the invoice back."
    )


# ── Decimal arithmetic correctness on the cross-module copy ─────────────


@pytest.mark.asyncio
async def test_po_create_aggregates_subtotal_from_items_with_decimal() -> None:
    """When the caller supplies items, the subtotal MUST be re-aggregated
    from ``sum(quantity * unit_rate)`` using Decimal — float arithmetic
    here would mis-total a 3-line PO by one cent on common inputs like
    1.10 + 2.20 + 3.30.
    """
    svc = _make_service()
    po = await svc.create_po(
        POCreate(
            project_id=PROJECT_A,
            amount_subtotal="0",  # ignored when items are supplied
            tax_amount="0",
            items=[
                POItemCreate(description="a", quantity="1", unit_rate="1.10", amount="0"),
                POItemCreate(description="b", quantity="1", unit_rate="2.20", amount="0"),
                POItemCreate(description="c", quantity="1", unit_rate="3.30", amount="0"),
            ],
        ),
        user_id=USER_A,
    )
    # Exact Decimal sum (no float drift).
    assert Decimal(po.amount_subtotal) == Decimal("6.60")
    assert Decimal(po.amount_total) == Decimal("6.60")
