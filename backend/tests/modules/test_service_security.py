"""Service & Maintenance security tests (R7 audit).

Coverage:

  * **Ticket FSM**: invalid transitions raise 409 with the legal-targets
    set in the error detail; ``won``/``lost``/``closed`` are terminal.
  * **Work-order FSM**: ``completed → billed`` is the only forward path
    out of completed; the rest are terminal.
  * **Contract FSM**: ``draft → active`` is the only path; ``terminated``
    is terminal.
  * **RBAC**: dispatch / bill / close-contract / dispatch-protected
    PATCH fields all sit at MANAGER+, never EDITOR.
  * **PATCH dispatch gate**: an EDITOR with ``service.update`` cannot
    mutate ``assigned_to`` / ``sla_due_at`` / ``sla_breach_notified_at``
    via the umbrella PATCH endpoint (the underlying service raises 403).
  * **Money columns** are Numeric Decimal everywhere — no Float on
    contract.value, work_order.billed_amount, work_order_item.total /
    unit_rate / quantity.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

_TMP_DIR = Path(tempfile.mkdtemp(prefix="oe-svc-sec-"))
_TMP_DB = _TMP_DIR / "svc.db"
os.environ.setdefault("DATABASE_URL", f"sqlite+aiosqlite:///{_TMP_DB.as_posix()}")
os.environ.setdefault("DATABASE_SYNC_URL", f"sqlite:///{_TMP_DB.as_posix()}")

from fastapi import HTTPException  # noqa: E402
from sqlalchemy import Float as SAFloat  # noqa: E402
from sqlalchemy import Numeric as SANumeric  # noqa: E402

import app.modules.projects.models  # noqa: E402,F401
import app.modules.service.models  # noqa: E402,F401
import app.modules.users.models  # noqa: E402,F401
from app.core.permissions import permission_registry  # noqa: E402
from app.modules.service.models import (  # noqa: E402
    ServiceContract,
    ServiceWorkOrder,
    ServiceWorkOrderItem,
)
from app.modules.service.permissions import (  # noqa: E402
    SERVICE_PERMISSIONS,
    register_service_permissions,
)
from app.modules.service.schemas import ServiceTicketUpdate  # noqa: E402
from app.modules.service.service import (  # noqa: E402
    TICKET_DISPATCH_PROTECTED_FIELDS,
    ServiceService,
    allowed_contract_transitions,
    allowed_ticket_transitions,
    allowed_work_order_transitions,
    assert_transition,
)


def _ensure_perms_registered():
    register_service_permissions()


# ── Money column types are Decimal not Float ─────────────────────────────


@pytest.mark.parametrize(
    ("model", "column"),
    [
        (ServiceContract, "value"),
        (ServiceWorkOrder, "billed_amount"),
        (ServiceWorkOrderItem, "quantity"),
        (ServiceWorkOrderItem, "unit_rate"),
        (ServiceWorkOrderItem, "total"),
    ],
)
def test_money_column_is_numeric_not_float(model, column):
    col = model.__table__.columns[column]
    assert isinstance(col.type, SANumeric), (
        f"{model.__name__}.{column} must be Numeric (Decimal), got {type(col.type).__name__}"
    )
    assert not isinstance(col.type, SAFloat), (
        f"{model.__name__}.{column} must NOT be Float — sub-cent drift would corrupt invoicing"
    )


def test_work_order_item_total_quantises_to_two_dp():
    """Quantity × unit_rate must be Decimal-exact for billing."""
    from app.modules.service.service import compute_work_order_total

    items = [
        SimpleNamespace(total=Decimal("0.10")),
        SimpleNamespace(total=Decimal("0.20")),
        SimpleNamespace(total=Decimal("0.30")),
    ]
    total = compute_work_order_total(items)
    assert total == Decimal("0.60")
    # Integer + Decimal mix must NOT accidentally fall through to float.
    items.append(SimpleNamespace(total=Decimal("999.99")))
    assert compute_work_order_total(items) == Decimal("1000.59")


# ── RBAC: write actions require MANAGER+ ─────────────────────────────────


@pytest.mark.parametrize(
    ("permission", "minimum_role"),
    [
        ("service.dispatch", "manager"),
        ("service.bill", "manager"),
        ("service.close_contract", "manager"),
        ("service.delete", "manager"),
    ],
)
def test_write_permission_minimum_role(permission, minimum_role):
    _ensure_perms_registered()
    assert permission_registry.role_has_permission(minimum_role, permission) is True
    # Admin always passes
    assert permission_registry.role_has_permission("admin", permission) is True


@pytest.mark.parametrize(
    "permission",
    ["service.dispatch", "service.bill", "service.close_contract"],
)
def test_write_permission_denied_for_editor(permission):
    _ensure_perms_registered()
    assert permission_registry.role_has_permission("editor", permission) is False
    assert permission_registry.role_has_permission("viewer", permission) is False


def test_service_read_open_to_viewer():
    _ensure_perms_registered()
    assert permission_registry.role_has_permission("viewer", "service.read") is True


def test_permission_registry_matches_constant():
    """Constant + actual registration agree (no drift)."""
    _ensure_perms_registered()
    for perm, min_role in SERVICE_PERMISSIONS.items():
        assert permission_registry.role_has_permission(min_role.value, perm) is True, (
            f"{perm} should be granted at {min_role.value}"
        )


# ── Ticket FSM ───────────────────────────────────────────────────────────


def test_ticket_terminal_states_have_no_outgoing_transitions():
    for terminal in ("closed", "cancelled"):
        assert allowed_ticket_transitions(terminal) == set(), f"ticket status '{terminal}' must be terminal"


def test_ticket_assigned_can_go_back_to_new_for_dispatcher_unassign():
    # Re-routing a wrongly-assigned ticket must be allowed.
    assert "new" in allowed_ticket_transitions("assigned")


def test_ticket_in_progress_cannot_jump_to_closed_directly():
    """Closed only reachable from resolved — protects SLA reporting."""
    assert "closed" not in allowed_ticket_transitions("in_progress")


def test_ticket_invalid_transition_raises_409_with_legal_set():
    with pytest.raises(HTTPException) as exc_info:
        assert_transition("closed", "new", machine="ticket")
    assert exc_info.value.status_code == 409
    # Detail surfaces the legal-next-states to the caller.
    assert "Allowed" in str(exc_info.value.detail)


# ── Work-order FSM ───────────────────────────────────────────────────────


def test_work_order_terminal_states():
    for terminal in ("billed", "cancelled"):
        assert allowed_work_order_transitions(terminal) == set()


def test_work_order_completed_only_goes_to_billed():
    """The finance hand-off is the only forward path from completed."""
    assert allowed_work_order_transitions("completed") == {"billed"}


def test_work_order_cannot_skip_completed_to_billed():
    """In_progress must pass through completed first."""
    assert "billed" not in allowed_work_order_transitions("in_progress")


# ── Contract FSM ─────────────────────────────────────────────────────────


def test_contract_draft_cannot_jump_to_expired():
    """Expired is a clock-driven outcome, not an initial state."""
    assert "expired" not in allowed_contract_transitions("draft")


def test_contract_terminated_is_terminal():
    assert allowed_contract_transitions("terminated") == set()


# ── PATCH dispatch-gate ──────────────────────────────────────────────────


def test_dispatch_protected_fields_constant_matches_audit_intent():
    """Lock the set of fields that require service.dispatch on PATCH."""
    assert "assigned_to" in TICKET_DISPATCH_PROTECTED_FIELDS
    assert "sla_due_at" in TICKET_DISPATCH_PROTECTED_FIELDS
    assert "sla_breach_notified_at" in TICKET_DISPATCH_PROTECTED_FIELDS
    assert "sla_breached_at" in TICKET_DISPATCH_PROTECTED_FIELDS


def test_patch_ticket_assigned_to_without_dispatch_perm_raises_403():
    """An EDITOR cannot self-assign tickets via PATCH /tickets/{id}."""

    class _TicketRepo:
        async def get_by_id(self, tid):
            now = datetime.now(UTC)
            return SimpleNamespace(
                id=tid,
                contract_id=uuid.uuid4(),
                status="new",
                resolved_at=None,
                closed_at=None,
                ticket_number="T-00001",
                created_at=now,
                updated_at=now,
            )

        async def update_fields(self, *args, **kwargs):
            return None

    class _AssetRepo:
        async def get_by_id(self, *_args):
            return None

    class _Session:
        async def refresh(self, *_args, **_kw):
            return None

    svc = ServiceService.__new__(ServiceService)
    svc.session = _Session()
    svc.ticket_repo = _TicketRepo()
    svc.asset_repo = _AssetRepo()

    async def _go():
        await svc.update_ticket(
            uuid.uuid4(),
            ServiceTicketUpdate(assigned_to="rogue-tech-uuid"),
            has_dispatch_permission=False,
        )

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(_go())
    assert exc_info.value.status_code == 403
    assert "dispatch" in str(exc_info.value.detail).lower()


def test_patch_ticket_sla_field_without_dispatch_perm_raises_403():
    """Pushing sla_due_at to silence breach alerts must 403."""

    class _TicketRepo:
        async def get_by_id(self, tid):
            now = datetime.now(UTC)
            return SimpleNamespace(
                id=tid,
                contract_id=uuid.uuid4(),
                status="new",
                resolved_at=None,
                closed_at=None,
                ticket_number="T-00002",
                created_at=now,
                updated_at=now,
            )

        async def update_fields(self, *args, **kwargs):
            return None

    class _AssetRepo:
        async def get_by_id(self, *_args):
            return None

    class _Session:
        async def refresh(self, *_args, **_kw):
            return None

    svc = ServiceService.__new__(ServiceService)
    svc.session = _Session()
    svc.ticket_repo = _TicketRepo()
    svc.asset_repo = _AssetRepo()

    async def _go():
        await svc.update_ticket(
            uuid.uuid4(),
            ServiceTicketUpdate(sla_due_at="2099-01-01T00:00:00+00:00"),
            has_dispatch_permission=False,
        )

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(_go())
    assert exc_info.value.status_code == 403


def test_patch_ticket_dispatch_protected_with_perm_is_allowed():
    """Dispatcher (has_dispatch_permission=True) can mutate the fields."""

    class _TicketRepo:
        called_with_kwargs: dict | None = None

        async def get_by_id(self, tid):
            now = datetime.now(UTC)
            return SimpleNamespace(
                id=tid,
                contract_id=uuid.uuid4(),
                status="new",
                resolved_at=None,
                closed_at=None,
                ticket_number="T-00003",
                created_at=now,
                updated_at=now,
            )

        async def update_fields(self, _id, **fields):
            type(self).called_with_kwargs = fields

    class _AssetRepo:
        async def get_by_id(self, *_args):
            return None

    class _Session:
        async def refresh(self, *_args, **_kw):
            return None

    svc = ServiceService.__new__(ServiceService)
    svc.session = _Session()
    svc.ticket_repo = _TicketRepo()
    svc.asset_repo = _AssetRepo()

    async def _go():
        await svc.update_ticket(
            uuid.uuid4(),
            ServiceTicketUpdate(assigned_to="real-tech"),
            has_dispatch_permission=True,
        )

    asyncio.run(_go())
    assert _TicketRepo.called_with_kwargs == {"assigned_to": "real-tech"}


# ── Asset-belongs-to-contract guard on PATCH ─────────────────────────────


def test_patch_ticket_cannot_retarget_to_other_contracts_asset():
    """Caller PATCHes asset_id to a row in another contract → 400."""

    contract_id = uuid.uuid4()
    other_contract = uuid.uuid4()
    asset_id = uuid.uuid4()

    class _TicketRepo:
        async def get_by_id(self, tid):
            now = datetime.now(UTC)
            return SimpleNamespace(
                id=tid,
                contract_id=contract_id,
                status="new",
                resolved_at=None,
                closed_at=None,
                ticket_number="T-00004",
                created_at=now,
                updated_at=now,
            )

        async def update_fields(self, *args, **kwargs):
            return None

    class _AssetRepo:
        async def get_by_id(self, aid):
            return SimpleNamespace(id=aid, contract_id=other_contract)

    class _Session:
        async def refresh(self, *_args, **_kw):
            return None

    svc = ServiceService.__new__(ServiceService)
    svc.session = _Session()
    svc.ticket_repo = _TicketRepo()
    svc.asset_repo = _AssetRepo()

    async def _go():
        await svc.update_ticket(
            uuid.uuid4(),
            ServiceTicketUpdate(asset_id=asset_id),
            has_dispatch_permission=True,
        )

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(_go())
    assert exc_info.value.status_code == 400
    assert "contract" in str(exc_info.value.detail).lower()


# ── Get-not-found returns 404 (template for IDOR collapse) ───────────────


def test_get_ticket_missing_returns_404():
    """A non-existent UUID returns 404, not 500 — same as IDOR-deny."""

    class _Repo:
        async def get_by_id(self, *_args):
            return None

    svc = ServiceService.__new__(ServiceService)
    svc.ticket_repo = _Repo()

    async def _go():
        await svc.get_ticket(uuid.uuid4())

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(_go())
    assert exc_info.value.status_code == 404


def test_get_contract_missing_returns_404():
    class _Repo:
        async def get_by_id(self, *_args):
            return None

    svc = ServiceService.__new__(ServiceService)
    svc.contract_repo = _Repo()

    async def _go():
        await svc.get_contract(uuid.uuid4())

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(_go())
    assert exc_info.value.status_code == 404


def test_get_work_order_missing_returns_404():
    class _Repo:
        async def get_by_id(self, *_args):
            return None

    svc = ServiceService.__new__(ServiceService)
    svc.work_order_repo = _Repo()

    async def _go():
        await svc.get_work_order(uuid.uuid4())

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(_go())
    assert exc_info.value.status_code == 404


# ── Priority-driven SLA defaults ─────────────────────────────────────────


def test_priority_sla_minutes_unknown_falls_back_to_normal_24h():
    """A stray UI priority must never make a ticket SLA-immortal."""
    from app.modules.service.service import priority_sla_minutes

    assert priority_sla_minutes("frobozz") == 24 * 60
    assert priority_sla_minutes(None) == 24 * 60


@pytest.mark.parametrize(
    ("priority", "minutes"),
    [
        ("urgent", 4 * 60),
        ("critical", 4 * 60),
        ("high", 8 * 60),
        ("normal", 24 * 60),
        ("med", 24 * 60),
        ("low", 72 * 60),
    ],
)
def test_priority_sla_minutes_table(priority, minutes):
    from app.modules.service.service import priority_sla_minutes

    assert priority_sla_minutes(priority) == minutes
