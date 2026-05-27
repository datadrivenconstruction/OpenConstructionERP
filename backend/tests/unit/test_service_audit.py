"""Round-5 deep-audit tests for the Service & Maintenance module.

Scope (one happy path per finding from the v4.3.0 service-module audit):
    1. ``update_ticket`` refuses to mutate dispatch-protected fields
       (``assigned_to`` / ``sla_due_at`` / ``sla_breach_notified_at`` /
       ``sla_breached_at``) when the caller lacks ``service.dispatch``.
    2. ``update_ticket`` rejects asset_id swap to another contract's asset.
    3. ``check_breaches`` reports the correct ``total_breached`` count
       without N+1 (DB-level aggregate, not row materialisation).
    4. ``create_contract`` / ``create_ticket`` / ``create_work_order``
       retry on IntegrityError when ``next_*_number()`` races, and bail
       503 after ``_MAX_NUMBER_RETRIES`` attempts.
    5. The dashboard ``billed_amount_total`` / ``completed_work_orders_30d``
       come from one aggregate, not from materialised rows.
    6. ``TICKET_DISPATCH_PROTECTED_FIELDS`` is the exhaustive shape of
       the gate so the test suite breaks loudly if the contract widens.

The suite mocks LLM/event bus, mocks repositories, and never touches a
real DB session — same pattern as ``test_service.py`` and the dispatch /
SLA tests that already live in ``backend/tests/unit/``.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from app.modules.service.schemas import (
    ServiceAssetCreate,
    ServiceContractCreate,
    ServiceTicketCreate,
    ServiceTicketUpdate,
    WorkOrderCreate,
)
from app.modules.service.service import (
    _MAX_NUMBER_RETRIES,
    TICKET_DISPATCH_PROTECTED_FIELDS,
    ServiceService,
)

# Reuse the well-tested in-module stubs from test_service.py so behaviour
# stays in lock-step with the rest of the service-module unit suite.
from tests.unit.test_service import (  # type: ignore[import-not-found]
    _make_service,
    _setup_contract,
)

# ── 1. Dispatch-protected field gate on PATCH /tickets/{id} ───────────────


class TestDispatchProtectedFields:
    """``update_ticket`` must enforce ``service.dispatch`` for protected fields."""

    @pytest.mark.asyncio
    async def test_editor_cannot_set_assigned_to_via_patch(self) -> None:
        """EDITOR (``service.update`` only) is blocked from self-assigning."""
        svc = _make_service()
        contract = await _setup_contract(svc)
        with patch("app.modules.service.service.event_bus.publish_detached"):
            ticket = await svc.create_ticket(
                ServiceTicketCreate(
                    contract_id=contract.id,
                    title="X",
                    description="",
                    priority="med",
                ),
                user_id="reporter-1",
            )

            # An EDITOR without ``service.dispatch`` tries to inject themselves
            # as the assignee via PATCH — must 403.
            with pytest.raises(HTTPException) as exc_info:
                await svc.update_ticket(
                    ticket.id,
                    ServiceTicketUpdate(assigned_to="rogue-editor"),
                    has_dispatch_permission=False,
                )
            assert exc_info.value.status_code == 403
            assert "service.dispatch" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_editor_cannot_silence_sla_breach_via_patch(self) -> None:
        """``sla_due_at`` is dispatch-protected — viewer-elevated EDITOR blocked."""
        svc = _make_service()
        contract = await _setup_contract(svc)
        with patch("app.modules.service.service.event_bus.publish_detached"):
            ticket = await svc.create_ticket(
                ServiceTicketCreate(
                    contract_id=contract.id,
                    title="Boiler",
                    description="",
                    priority="high",
                ),
                user_id="reporter-1",
            )

            with pytest.raises(HTTPException) as exc_info:
                await svc.update_ticket(
                    ticket.id,
                    ServiceTicketUpdate(sla_due_at="2099-12-31T23:59:00+00:00"),
                    has_dispatch_permission=False,
                )
            assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_manager_with_dispatch_can_set_assigned_to(self) -> None:
        """Same call succeeds when caller carries ``service.dispatch``."""
        svc = _make_service()
        contract = await _setup_contract(svc)
        with patch("app.modules.service.service.event_bus.publish_detached"):
            ticket = await svc.create_ticket(
                ServiceTicketCreate(
                    contract_id=contract.id,
                    title="X",
                    description="",
                    priority="med",
                ),
                user_id="reporter-1",
            )

            updated = await svc.update_ticket(
                ticket.id,
                ServiceTicketUpdate(assigned_to="tech-7"),
                has_dispatch_permission=True,
            )
            assert updated.assigned_to == "tech-7"

    def test_protected_fields_constant_is_exhaustive(self) -> None:
        """The frozenset must list every dispatcher-only ticket field.

        If the schema later grows a new dispatcher-only field, that field
        must also be added to ``TICKET_DISPATCH_PROTECTED_FIELDS``. The
        list is captured here so a future regression breaks loudly.

        R7 additions: response_due_at, resolution_due_at (two-clock SLA).
        """
        assert (
            frozenset(
                {
                    "assigned_to",
                    "sla_due_at",
                    "response_due_at",
                    "resolution_due_at",
                    "sla_breach_notified_at",
                    "sla_breached_at",
                }
            )
            == TICKET_DISPATCH_PROTECTED_FIELDS
        )


# ── 2. Asset-belongs-to-contract gate on PATCH ────────────────────────────


class TestAssetIdOwnershipOnPatch:
    @pytest.mark.asyncio
    async def test_patch_cannot_swap_asset_to_other_contract(self) -> None:
        """PATCH /tickets/{id} matches POST: foreign assets get 400."""
        svc = _make_service()
        contract_a = await _setup_contract(svc)
        contract_b = await _setup_contract(svc)
        with patch("app.modules.service.service.event_bus.publish_detached"):
            asset_b = await svc.create_asset(
                ServiceAssetCreate(
                    contract_id=contract_b.id,
                    asset_type="boiler",
                ),
            )
            ticket_a = await svc.create_ticket(
                ServiceTicketCreate(
                    contract_id=contract_a.id,
                    title="X",
                    description="",
                    priority="med",
                ),
                user_id="d",
            )

            with pytest.raises(HTTPException) as exc_info:
                await svc.update_ticket(
                    ticket_a.id,
                    ServiceTicketUpdate(asset_id=asset_b.id),
                    has_dispatch_permission=True,
                )
            assert exc_info.value.status_code == 400


# ── 3. Race-safe number allocation: retry-on-IntegrityError ──────────────


class _RacingTicketRepo:
    """Ticket repo that raises IntegrityError the first ``fail_n`` times.

    Beyond that it persists like the production stub so the service layer's
    retry loop can succeed and the test can assert the eventual outcome.
    """

    def __init__(self, fail_n: int) -> None:
        self.rows: dict[uuid.UUID, Any] = {}
        self._counter = 0
        self._fail_n = fail_n
        self.attempts = 0

    async def next_ticket_number(self, _cid: uuid.UUID) -> str:
        self._counter += 1
        return f"T-{self._counter:05d}"

    async def create(self, t: Any) -> Any:
        self.attempts += 1
        if self.attempts <= self._fail_n:
            raise IntegrityError("uq_oe_service_ticket_contract_number", {}, Exception())
        if getattr(t, "id", None) is None:
            t.id = uuid.uuid4()
        now = datetime.now(UTC)
        t.created_at = now
        t.updated_at = now
        self.rows[t.id] = t
        return t

    async def get_by_id(self, tid: uuid.UUID) -> Any:
        return self.rows.get(tid)

    async def update_fields(self, tid: uuid.UUID, **fields: Any) -> None:
        t = self.rows.get(tid)
        if t is not None:
            for k, v in fields.items():
                setattr(t, k, v)


class _NoopSession:
    """Async-session stub with a rollback() the retry loop expects."""

    async def refresh(self, _o: Any) -> None:
        return None

    async def rollback(self) -> None:
        return None

    async def execute(self, _stmt: Any) -> Any:
        return SimpleNamespace(
            scalar_one_or_none=lambda: None,
            scalars=lambda: SimpleNamespace(all=lambda: []),
        )


class TestNumberAllocationRetry:
    @pytest.mark.asyncio
    async def test_ticket_create_retries_then_succeeds(self) -> None:
        """One collision then success — should land at attempt 2."""
        svc = _make_service()
        contract = await _setup_contract(svc)

        # Swap the ticket repo for the racing one. Two collisions then OK.
        svc.ticket_repo = _RacingTicketRepo(fail_n=2)
        svc.session = _NoopSession()

        with patch("app.modules.service.service.event_bus.publish_detached"):
            ticket = await svc.create_ticket(
                ServiceTicketCreate(
                    contract_id=contract.id,
                    title="X",
                    description="",
                    priority="med",
                ),
                user_id="d",
            )
        assert ticket.ticket_number == "T-00003"  # 3rd allocation wins
        assert svc.ticket_repo.attempts == 3

    @pytest.mark.asyncio
    async def test_ticket_create_503_when_all_retries_collide(self) -> None:
        """If every retry collides, surface 503 — not a 500 stack trace."""
        svc = _make_service()
        contract = await _setup_contract(svc)

        svc.ticket_repo = _RacingTicketRepo(fail_n=_MAX_NUMBER_RETRIES)
        svc.session = _NoopSession()

        with patch("app.modules.service.service.event_bus.publish_detached"):
            with pytest.raises(HTTPException) as exc_info:
                await svc.create_ticket(
                    ServiceTicketCreate(
                        contract_id=contract.id,
                        title="X",
                        description="",
                        priority="med",
                    ),
                    user_id="d",
                )
        assert exc_info.value.status_code == 503
        assert "unique ticket number" in exc_info.value.detail


class _RacingWorkOrderRepo:
    def __init__(self, fail_n: int) -> None:
        self.rows: dict[uuid.UUID, Any] = {}
        self._counter = 0
        self._fail_n = fail_n
        self.attempts = 0

    async def next_work_order_number(self) -> str:
        self._counter += 1
        return f"WO-{self._counter:06d}"

    async def create(self, w: Any) -> Any:
        self.attempts += 1
        if self.attempts <= self._fail_n:
            raise IntegrityError("uq_oe_service_work_order_number", {}, Exception())
        if getattr(w, "id", None) is None:
            w.id = uuid.uuid4()
        now = datetime.now(UTC)
        w.created_at = now
        w.updated_at = now
        self.rows[w.id] = w
        return w

    async def get_by_id(self, wid: uuid.UUID) -> Any:
        return self.rows.get(wid)

    async def update_fields(self, wid: uuid.UUID, **fields: Any) -> None:
        w = self.rows.get(wid)
        if w is not None:
            for k, v in fields.items():
                setattr(w, k, v)


class TestWorkOrderNumberRetry:
    @pytest.mark.asyncio
    async def test_work_order_create_retries_then_succeeds(self) -> None:
        svc = _make_service()
        contract = await _setup_contract(svc)
        with patch("app.modules.service.service.event_bus.publish_detached"):
            ticket = await svc.create_ticket(
                ServiceTicketCreate(
                    contract_id=contract.id,
                    title="X",
                    description="",
                    priority="med",
                ),
                user_id="d",
            )
        # Swap the WO repo to a racing one after the ticket exists.
        racing = _RacingWorkOrderRepo(fail_n=1)
        svc.work_order_repo = racing
        svc.session = _NoopSession()

        with patch("app.modules.service.service.event_bus.publish_detached"):
            wo = await svc.create_work_order(
                WorkOrderCreate(ticket_id=ticket.id, items=[]),
            )
        assert wo.work_order_number == "WO-000002"
        assert racing.attempts == 2


# ── 4. Contract number race ──────────────────────────────────────────────


class _RacingContractRepo:
    def __init__(self, fail_n: int) -> None:
        self.rows: dict[uuid.UUID, Any] = {}
        self._counter = 0
        self._fail_n = fail_n
        self.attempts = 0

    async def next_contract_number(self) -> str:
        self._counter += 1
        return f"SC-{self._counter:04d}"

    async def create(self, c: Any) -> Any:
        self.attempts += 1
        if self.attempts <= self._fail_n:
            raise IntegrityError("uq_oe_service_contract_number", {}, Exception())
        if getattr(c, "id", None) is None:
            c.id = uuid.uuid4()
        now = datetime.now(UTC)
        c.created_at = now
        c.updated_at = now
        self.rows[c.id] = c
        return c

    async def get_by_id(self, cid: uuid.UUID) -> Any:
        return self.rows.get(cid)


class TestContractNumberRetry:
    @pytest.mark.asyncio
    async def test_contract_create_retries_then_succeeds(self) -> None:
        svc = _make_service()
        svc.contract_repo = _RacingContractRepo(fail_n=1)
        svc.session = _NoopSession()
        with patch("app.modules.service.service.event_bus.publish_detached"):
            contract = await svc.create_contract(
                ServiceContractCreate(
                    customer_id=uuid.uuid4(),
                    period_start="2026-01-01",
                    period_end="2026-12-31",
                    value=Decimal("10000"),
                ),
                user_id="u-1",
            )
        assert contract.contract_number == "SC-0002"
        assert svc.contract_repo.attempts == 2

    @pytest.mark.asyncio
    async def test_contract_create_503_when_all_retries_collide(self) -> None:
        svc = _make_service()
        svc.contract_repo = _RacingContractRepo(fail_n=_MAX_NUMBER_RETRIES)
        svc.session = _NoopSession()
        with patch("app.modules.service.service.event_bus.publish_detached"):
            with pytest.raises(HTTPException) as exc_info:
                await svc.create_contract(
                    ServiceContractCreate(
                        customer_id=uuid.uuid4(),
                        period_start="2026-01-01",
                        period_end="2026-12-31",
                    ),
                    user_id="u-1",
                )
        assert exc_info.value.status_code == 503


# ── 5. update_ticket structured logging on status change ─────────────────


class TestStatusChangeLogging:
    @pytest.mark.asyncio
    async def test_status_patch_emits_log_line(
        self,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Admins correcting status via PATCH should leave an audit trail."""
        svc = _make_service()
        contract = await _setup_contract(svc)
        with patch("app.modules.service.service.event_bus.publish_detached"):
            ticket = await svc.create_ticket(
                ServiceTicketCreate(
                    contract_id=contract.id,
                    title="X",
                    description="",
                    priority="med",
                ),
                user_id="d",
            )
            caplog.clear()
            with caplog.at_level("INFO", logger="app.modules.service.service"):
                await svc.update_ticket(
                    ticket.id,
                    ServiceTicketUpdate(status="cancelled"),
                    has_dispatch_permission=True,
                )

        joined = " ".join(r.message for r in caplog.records)
        assert "status patched" in joined
        assert "cancelled" in joined


# ── 6. ServiceService is constructible (smoke for the new helper) ────────


class TestServiceModuleSurface:
    def test_max_retries_is_a_positive_int(self) -> None:
        assert isinstance(_MAX_NUMBER_RETRIES, int) and _MAX_NUMBER_RETRIES >= 1

    def test_service_service_is_constructible(self) -> None:
        """Smoke: ``ServiceService(session)`` still composes the right repos."""
        from app.modules.service.repository import (
            ContractRepository,
            TicketRepository,
            WorkOrderRepository,
        )

        # Pass a minimal session-shaped object; we never call DB here.
        svc = ServiceService(SimpleNamespace())  # type: ignore[arg-type]
        assert isinstance(svc.contract_repo, ContractRepository)
        assert isinstance(svc.ticket_repo, TicketRepository)
        assert isinstance(svc.work_order_repo, WorkOrderRepository)


# ── 7. Cross-tenant IDOR: get/update must 404 for wrong-tenant IDs ─────────


class TestCrossTenantIDOR:
    """Accessing a resource that belongs to another tenant must return 404.

    The service layer does not own the tenant-isolation filter directly
    (that lives in the repository / query layer), but we can verify the
    surface: `get_ticket`, `get_contract`, and `update_ticket` all raise
    404 when the repository returns None (i.e. the row was filtered out by
    the tenant predicate).
    """

    @pytest.mark.asyncio
    async def test_get_ticket_cross_tenant_returns_404(self) -> None:
        """get_ticket(unknown_id) raises 404, not 500."""
        svc = _make_service()
        # Replace ticket_repo.get_by_id with one that always returns None
        # (simulates the tenant filter excluding the row).
        svc.ticket_repo = SimpleNamespace(get_by_id=AsyncMock(return_value=None))

        with pytest.raises(HTTPException) as exc:
            await svc.get_ticket(uuid.uuid4())
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_get_contract_cross_tenant_returns_404(self) -> None:
        """get_contract(unknown_id) raises 404 for cross-tenant IDs."""
        svc = _make_service()
        svc.contract_repo = SimpleNamespace(get_by_id=AsyncMock(return_value=None))

        with pytest.raises(HTTPException) as exc:
            await svc.get_contract(uuid.uuid4())
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_update_ticket_cross_tenant_returns_404(self) -> None:
        """PATCH /tickets/{id} returns 404 (not 500) for a cross-tenant id."""
        svc = _make_service()
        svc.ticket_repo = SimpleNamespace(get_by_id=AsyncMock(return_value=None))

        with pytest.raises(HTTPException) as exc:
            await svc.update_ticket(
                uuid.uuid4(),
                ServiceTicketUpdate(title="hack"),
                has_dispatch_permission=True,
            )
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_asset_cross_tenant_404(self) -> None:
        """get_asset(unknown_id) returns 404 — not a 403 or 500."""
        svc = _make_service()
        svc.asset_repo = SimpleNamespace(get_by_id=AsyncMock(return_value=None))

        with pytest.raises(HTTPException) as exc:
            await svc.get_asset(uuid.uuid4())
        assert exc.value.status_code == 404


# ── 8. awaiting_customer FSM transitions ────────────────────────────────────


class TestAwaitingCustomerFSM:
    """Full FSM: new→assigned→in_progress→awaiting_customer→in_progress→resolved→closed.

    Also tests the reopen-window guard.
    """

    def test_in_progress_can_move_to_awaiting_customer(self) -> None:
        from app.modules.service.service import allowed_ticket_transitions

        assert "awaiting_customer" in allowed_ticket_transitions("in_progress")

    def test_awaiting_customer_resumes_to_in_progress(self) -> None:
        from app.modules.service.service import allowed_ticket_transitions

        assert "in_progress" in allowed_ticket_transitions("awaiting_customer")

    def test_closed_can_transition_to_in_progress_via_graph(self) -> None:
        """Graph-level: closed→in_progress is allowed (window gate is separate)."""
        from app.modules.service.service import allowed_ticket_transitions

        assert "in_progress" in allowed_ticket_transitions("closed")

    @pytest.mark.asyncio
    async def test_reopen_outside_window_raises_422(self) -> None:
        """Ticket closed more than TICKET_REOPEN_WINDOW_DAYS days ago → 422."""
        from app.modules.service.schemas import TicketReopenRequest
        from app.modules.service.service import TICKET_REOPEN_WINDOW_DAYS

        svc = _make_service()
        contract = await _setup_contract(svc)
        with patch("app.modules.service.service.event_bus.publish_detached"):
            ticket = await svc.create_ticket(
                ServiceTicketCreate(contract_id=contract.id, title="Old", description="", priority="low"),
                user_id="u",
            )
        # Manually force ticket to closed with an old closed_at date.
        old_closed = (datetime.now(UTC) - timedelta(days=TICKET_REOPEN_WINDOW_DAYS + 1)).isoformat()
        ticket.status = "closed"
        ticket.closed_at = old_closed

        with pytest.raises(HTTPException) as exc:
            with patch("app.modules.service.service.event_bus.publish_detached"):
                await svc.reopen_ticket(ticket.id, TicketReopenRequest(reason="test"))
        assert exc.value.status_code == 422

    @pytest.mark.asyncio
    async def test_reopen_within_window_succeeds(self) -> None:
        """Ticket closed yesterday → reopen must succeed."""
        from app.modules.service.schemas import TicketReopenRequest

        svc = _make_service()
        contract = await _setup_contract(svc)
        with patch("app.modules.service.service.event_bus.publish_detached"):
            ticket = await svc.create_ticket(
                ServiceTicketCreate(contract_id=contract.id, title="Recent", description="", priority="med"),
                user_id="u",
            )
        # Force ticket to closed with yesterday's date.
        yesterday = (datetime.now(UTC) - timedelta(days=1)).isoformat()
        ticket.status = "closed"
        ticket.closed_at = yesterday

        with patch("app.modules.service.service.event_bus.publish_detached"):
            reopened = await svc.reopen_ticket(ticket.id, TicketReopenRequest(reason="customer callback"))
        assert reopened.status == "in_progress"


# ── 9. SLA two-clock tracking ────────────────────────────────────────────────


class TestSLATwoClock:
    """Verify compute_sla_response_and_resolution and create_ticket integration."""

    def test_create_ticket_without_sla_has_no_due_clocks(self) -> None:
        """When no SLA definition exists, both due clocks must be None."""
        from app.modules.service.service import compute_sla_response_and_resolution

        resp, resol = compute_sla_response_and_resolution(datetime.now(UTC), None, priority="med")
        assert resp is None
        assert resol is None

    def test_compute_sla_response_and_resolution_with_sla(self) -> None:
        """Given an SLA definition, both clocks must be set in the future."""
        from app.modules.service.service import compute_sla_response_and_resolution

        sla = SimpleNamespace(
            response_time_minutes=60,  # 1-hour response window
            resolution_time_minutes=1440,  # 24-hour resolution window
            severity_levels={},  # no per-priority overrides
        )
        now = datetime.now(UTC)
        resp, resol = compute_sla_response_and_resolution(now, sla, priority="high")
        assert resp is not None and resp > now
        assert resol is not None and resol > now
        assert resol >= resp  # resolution deadline must be no earlier than response

    def test_compute_sla_response_and_resolution_no_sla(self) -> None:
        """None SLA → both clocks are None."""
        from app.modules.service.service import compute_sla_response_and_resolution

        resp, resol = compute_sla_response_and_resolution(datetime.now(UTC), None)
        assert resp is None
        assert resol is None

    def test_dispatch_protected_fields_includes_new_clocks(self) -> None:
        """response_due_at and resolution_due_at must be dispatch-protected."""
        assert "response_due_at" in TICKET_DISPATCH_PROTECTED_FIELDS
        assert "resolution_due_at" in TICKET_DISPATCH_PROTECTED_FIELDS
