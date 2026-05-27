"""Unit tests for the Service & Maintenance module.

Scope:
    * State-machine helpers (tickets / work orders / contracts) — pure functions.
    * SLA due-at computation, with and without priority override.
    * ServiceService orchestration with stubbed repos + session.
    * Permission constants are registered exactly once and at the right level.

Repositories and event bus are stubbed; no DB is touched.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from app.core.permissions import Role, permission_registry
from app.modules.service.permissions import (
    SERVICE_PERMISSIONS,
    register_service_permissions,
)
from app.modules.service.schemas import (
    DebriefReportCreate,
    ServiceAssetCreate,
    ServiceContractCreate,
    ServiceTicketCreate,
    TicketDispatchRequest,
    WorkOrderCompleteRequest,
    WorkOrderCreate,
    WorkOrderItemCreate,
)
from app.modules.service.service import (
    ServiceService,
    _utcnow_iso,
    allowed_contract_transitions,
    allowed_ticket_transitions,
    allowed_work_order_transitions,
    assert_transition,
    compute_sla_due_at,
    compute_work_order_total,
)

# ── Shared fakes ──────────────────────────────────────────────────────────


CUSTOMER_ID = uuid.uuid4()


class _StubSession:
    """Minimal AsyncSession stand-in — only the methods the service touches."""

    async def refresh(self, _obj: Any) -> None:
        return None

    async def execute(self, _stmt: Any) -> Any:
        return SimpleNamespace(
            scalar_one_or_none=lambda: None,
            scalars=lambda: _EmptyScalars(),
        )


class _EmptyScalars:
    def all(self) -> list[Any]:
        return []


def _stamp(obj: Any) -> Any:
    now = datetime.now(UTC)
    if getattr(obj, "id", None) is None:
        obj.id = uuid.uuid4()
    obj.created_at = now
    obj.updated_at = now
    return obj


class _StubContractRepo:
    def __init__(self) -> None:
        self.rows: dict[uuid.UUID, Any] = {}
        self._counter = 0

    async def next_contract_number(self) -> str:
        self._counter += 1
        return f"SC-{self._counter:04d}"

    async def create(self, c: Any) -> Any:
        self.rows[_stamp(c).id] = c
        return c

    async def get_by_id(self, cid: uuid.UUID) -> Any:
        return self.rows.get(cid)

    async def update_fields(self, cid: uuid.UUID, **fields: Any) -> None:
        c = self.rows.get(cid)
        if c is not None:
            for k, v in fields.items():
                setattr(c, k, v)
            c.updated_at = datetime.now(UTC)

    async def delete(self, cid: uuid.UUID) -> None:
        self.rows.pop(cid, None)

    async def list_all(
        self,
        *,
        offset: int = 0,
        limit: int = 50,
        status: str | None = None,
    ) -> tuple[list[Any], int]:
        rows = list(self.rows.values())
        if status is not None:
            rows = [r for r in rows if r.status == status]
        return rows[offset : offset + limit], len(rows)


class _StubAssetRepo:
    def __init__(self) -> None:
        self.rows: dict[uuid.UUID, Any] = {}

    async def create(self, a: Any) -> Any:
        self.rows[_stamp(a).id] = a
        return a

    async def get_by_id(self, aid: uuid.UUID) -> Any:
        return self.rows.get(aid)

    async def update_fields(self, aid: uuid.UUID, **fields: Any) -> None:
        a = self.rows.get(aid)
        if a is not None:
            for k, v in fields.items():
                setattr(a, k, v)

    async def delete(self, aid: uuid.UUID) -> None:
        self.rows.pop(aid, None)

    async def list_for_contract(
        self,
        contract_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 100,
        status: str | None = None,
    ) -> tuple[list[Any], int]:
        rows = [r for r in self.rows.values() if r.contract_id == contract_id]
        return rows[offset : offset + limit], len(rows)


class _StubTicketRepo:
    def __init__(self) -> None:
        self.rows: dict[uuid.UUID, Any] = {}
        self._counter = 0

    async def next_ticket_number(self, _contract_id: uuid.UUID) -> str:
        self._counter += 1
        return f"T-{self._counter:05d}"

    async def create(self, t: Any) -> Any:
        self.rows[_stamp(t).id] = t
        return t

    async def get_by_id(self, tid: uuid.UUID) -> Any:
        return self.rows.get(tid)

    async def update_fields(self, tid: uuid.UUID, **fields: Any) -> None:
        t = self.rows.get(tid)
        if t is not None:
            for k, v in fields.items():
                setattr(t, k, v)

    async def delete(self, tid: uuid.UUID) -> None:
        self.rows.pop(tid, None)

    async def list_for_contract(
        self,
        cid: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
        status: str | None = None,
        priority: str | None = None,
    ) -> tuple[list[Any], int]:
        rows = [r for r in self.rows.values() if r.contract_id == cid]
        if status is not None:
            rows = [r for r in rows if r.status == status]
        if priority is not None:
            rows = [r for r in rows if r.priority == priority]
        return rows[offset : offset + limit], len(rows)

    async def count_open_for_contract(self, cid: uuid.UUID) -> int:
        return sum(
            1 for r in self.rows.values() if r.contract_id == cid and r.status in ("new", "assigned", "in_progress")
        )

    async def count_in_progress_for_contract(self, cid: uuid.UUID) -> int:
        return sum(1 for r in self.rows.values() if r.contract_id == cid and r.status == "in_progress")


class _StubWorkOrderRepo:
    def __init__(self) -> None:
        self.rows: dict[uuid.UUID, Any] = {}
        self._counter = 0

    async def next_work_order_number(self) -> str:
        self._counter += 1
        return f"WO-{self._counter:06d}"

    async def create(self, w: Any) -> Any:
        self.rows[_stamp(w).id] = w
        return w

    async def get_by_id(self, wid: uuid.UUID) -> Any:
        return self.rows.get(wid)

    async def update_fields(self, wid: uuid.UUID, **fields: Any) -> None:
        w = self.rows.get(wid)
        if w is not None:
            for k, v in fields.items():
                setattr(w, k, v)


class _StubWorkOrderItemRepo:
    def __init__(self) -> None:
        self.rows: list[Any] = []

    async def create(self, item: Any) -> Any:
        _stamp(item)
        self.rows.append(item)
        return item

    async def list_for_work_order(self, wid: uuid.UUID) -> list[Any]:
        return [r for r in self.rows if r.work_order_id == wid]

    async def get_by_id(self, item_id: uuid.UUID) -> Any:
        return next((r for r in self.rows if r.id == item_id), None)

    async def update_fields(self, item_id: uuid.UUID, **fields: Any) -> None:
        # Mirrors _BaseRepo.update_fields (repository.py) so the double
        # honours the real repository contract the service relies on.
        obj = next((r for r in self.rows if r.id == item_id), None)
        if obj is None:
            return
        for key, value in fields.items():
            setattr(obj, key, value)


class _StubDebriefRepo:
    def __init__(self) -> None:
        self.rows: list[Any] = []

    async def create(self, d: Any) -> Any:
        _stamp(d)
        self.rows.append(d)
        return d


class _StubSLARepo:
    def __init__(self) -> None:
        self.rows: dict[uuid.UUID, Any] = {}

    async def get_by_id(self, sid: uuid.UUID) -> Any:
        return self.rows.get(sid)


class _StubScheduleRepo:
    async def list_due_within(
        self,
        _contract_id: uuid.UUID,
        _due_before: str,
    ) -> list[Any]:
        return []


def _make_service() -> ServiceService:
    svc = ServiceService.__new__(ServiceService)
    svc.session = _StubSession()
    svc.contract_repo = _StubContractRepo()
    svc.asset_repo = _StubAssetRepo()
    svc.ticket_repo = _StubTicketRepo()
    svc.work_order_repo = _StubWorkOrderRepo()
    svc.work_order_item_repo = _StubWorkOrderItemRepo()
    svc.debrief_repo = _StubDebriefRepo()
    svc.sla_repo = _StubSLARepo()
    svc.schedule_repo = _StubScheduleRepo()
    return svc


def _contract_data(**overrides: Any) -> ServiceContractCreate:
    defaults: dict[str, Any] = {
        "customer_id": CUSTOMER_ID,
        "title": "Demo contract",
        "period_start": "2026-01-01",
        "period_end": "2026-12-31",
        "sla_tier": "standard",
        "status": "draft",
        "value": Decimal("12000"),
        "currency": "EUR",
    }
    defaults.update(overrides)
    return ServiceContractCreate(**defaults)


async def _setup_contract(svc: ServiceService, **overrides: Any) -> Any:
    """Create a contract and return the persisted row."""
    with patch("app.modules.service.service.event_bus.publish_detached"):
        return await svc.create_contract(_contract_data(**overrides), user_id="dispatcher")


# ── State-machine helpers ─────────────────────────────────────────────────


def test_ticket_transitions_table() -> None:
    """Legal transitions match the documented state diagram."""
    assert "assigned" in allowed_ticket_transitions("new")
    assert "in_progress" in allowed_ticket_transitions("assigned")
    assert "resolved" in allowed_ticket_transitions("in_progress")
    assert "closed" in allowed_ticket_transitions("resolved")
    # closed → in_progress is the reopen path (window-gated in service).
    assert "in_progress" in allowed_ticket_transitions("closed")
    # cancelled is a true terminal
    assert allowed_ticket_transitions("cancelled") == set()
    # Cancellation allowed from every live state
    for live in ("new", "assigned", "in_progress"):
        assert "cancelled" in allowed_ticket_transitions(live)


def test_work_order_transitions_table() -> None:
    assert "dispatched" in allowed_work_order_transitions("scheduled")
    assert "in_progress" in allowed_work_order_transitions("dispatched")
    assert "completed" in allowed_work_order_transitions("in_progress")
    # R7: completed → verified (supervisor sign-off) or billed (legacy path)
    assert "verified" in allowed_work_order_transitions("completed")
    assert "billed" in allowed_work_order_transitions("completed")
    # R7: billed → closed (terminal)
    assert "closed" in allowed_work_order_transitions("billed")
    assert allowed_work_order_transitions("closed") == set()


def test_contract_transitions_table() -> None:
    assert "active" in allowed_contract_transitions("draft")
    assert "expired" in allowed_contract_transitions("active")
    assert "terminated" in allowed_contract_transitions("expired")
    assert allowed_contract_transitions("terminated") == set()


def test_assert_transition_rejects_invalid() -> None:
    with pytest.raises(HTTPException) as exc_info:
        assert_transition("closed", "new", machine="ticket")
    assert exc_info.value.status_code == 409


def test_assert_transition_idempotent_self() -> None:
    """current → current is allowed (no-op for status writes)."""
    assert_transition("new", "new", machine="ticket")


# ── SLA computation ───────────────────────────────────────────────────────


def test_compute_sla_due_at_uses_default_when_no_override() -> None:
    sla = SimpleNamespace(response_time_minutes=120, severity_levels={})
    reported = datetime(2026, 5, 12, 9, 0, tzinfo=UTC)
    due = compute_sla_due_at(reported, sla, priority="med")  # type: ignore[arg-type]
    assert due == reported + timedelta(minutes=120)


def test_compute_sla_due_at_priority_override() -> None:
    sla = SimpleNamespace(
        response_time_minutes=240,
        severity_levels={"critical": {"response_time_minutes": 30}},
    )
    reported = datetime(2026, 5, 12, 9, 0, tzinfo=UTC)
    due = compute_sla_due_at(reported, sla, priority="critical")  # type: ignore[arg-type]
    assert due == reported + timedelta(minutes=30)


def test_compute_sla_due_at_none_sla_returns_none() -> None:
    assert compute_sla_due_at(datetime.now(UTC), None) is None


# ── Service: contract / asset / ticket ───────────────────────────────────


@pytest.mark.asyncio
async def test_create_contract_assigns_number_and_user() -> None:
    svc = _make_service()
    with patch("app.modules.service.service.event_bus.publish_detached"):
        contract = await svc.create_contract(_contract_data(), user_id="u-1")
    assert contract.contract_number == "SC-0001"
    assert contract.created_by == "u-1"
    assert contract.status == "draft"


@pytest.mark.asyncio
async def test_create_ticket_computes_sla_due_at() -> None:
    """SLA-due is set to reported_at + response_time when contract has SLA."""
    svc = _make_service()

    # Insert an SLA the service can find.
    sla_id = uuid.uuid4()
    svc.sla_repo.rows[sla_id] = SimpleNamespace(
        id=sla_id,
        response_time_minutes=60,
        resolution_time_minutes=480,  # 8h resolution window
        severity_levels={"high": {"response_time_minutes": 15}},
    )

    contract = await _setup_contract(svc)
    contract.sla_definition_id = sla_id  # stub now points at the SLA

    reported = "2026-05-12T09:00:00+00:00"
    with patch("app.modules.service.service.event_bus.publish_detached"):
        ticket = await svc.create_ticket(
            ServiceTicketCreate(
                contract_id=contract.id,
                title="Boiler down",
                description="No heat.",
                priority="high",
                reported_at=reported,
            ),
            user_id="dispatcher",
        )

    # 15-minute override applies.
    expected = datetime(2026, 5, 12, 9, 15, tzinfo=UTC).isoformat()
    assert ticket.sla_due_at == expected
    assert ticket.status == "new"
    assert ticket.ticket_number == "T-00001"


@pytest.mark.asyncio
async def test_dispatch_requires_assignee() -> None:
    """The service guards the empty-technician case in addition to the schema layer.

    The schema would already reject technician_id='', but we want the service
    method itself to refuse empty input — otherwise callers that build the
    request from raw dicts (legacy admin tooling, scripts) could slip through.
    """
    svc = _make_service()
    contract = await _setup_contract(svc)
    with patch("app.modules.service.service.event_bus.publish_detached"):
        ticket = await svc.create_ticket(
            ServiceTicketCreate(
                contract_id=contract.id,
                title="X",
                description="Y",
                priority="med",
            ),
            user_id="d",
        )

    # Bypass Pydantic by instantiating the model with model_construct so
    # the service's own runtime check is what raises 422.
    bad_body = TicketDispatchRequest.model_construct(technician_id="", notes="")
    with patch("app.modules.service.service.event_bus.publish_detached"):
        with pytest.raises(HTTPException) as exc_info:
            await svc.dispatch_ticket(ticket.id, bad_body)
        assert exc_info.value.status_code == 422


@pytest.mark.asyncio
async def test_dispatch_emits_event() -> None:
    svc = _make_service()
    contract = await _setup_contract(svc)
    with patch("app.modules.service.service.event_bus.publish_detached") as bus:
        ticket = await svc.create_ticket(
            ServiceTicketCreate(
                contract_id=contract.id,
                title="X",
                description="Y",
                priority="med",
            ),
            user_id="d",
        )
        bus.reset_mock()
        updated = await svc.dispatch_ticket(
            ticket.id,
            TicketDispatchRequest(technician_id="tech-7"),
        )

    assert updated.status == "assigned"
    assert updated.assigned_to == "tech-7"
    event_names = [call.args[0] for call in bus.call_args_list]
    assert "service.ticket.dispatched" in event_names


@pytest.mark.asyncio
async def test_resolve_then_close_ticket() -> None:
    svc = _make_service()
    contract = await _setup_contract(svc)
    with patch("app.modules.service.service.event_bus.publish_detached"):
        ticket = await svc.create_ticket(
            ServiceTicketCreate(
                contract_id=contract.id,
                title="X",
                description="Y",
                priority="med",
                assigned_to="tech-1",
            ),
            user_id="d",
        )
        # Take to in_progress, then resolve, then close.
        ticket.status = "in_progress"  # bypass via stub for brevity
        resolved = await svc.resolve_ticket(ticket.id)
        assert resolved.status == "resolved"
        closed = await svc.close_ticket(ticket.id)
        assert closed.status == "closed"


@pytest.mark.asyncio
async def test_create_ticket_rejects_asset_mismatch() -> None:
    svc = _make_service()
    contract = await _setup_contract(svc)

    other_contract = await _setup_contract(svc)
    asset = await svc.create_asset(
        ServiceAssetCreate(contract_id=other_contract.id, asset_type="boiler"),
    )
    with patch("app.modules.service.service.event_bus.publish_detached"):
        with pytest.raises(HTTPException) as exc_info:
            await svc.create_ticket(
                ServiceTicketCreate(
                    contract_id=contract.id,
                    asset_id=asset.id,
                    title="X",
                    description="Y",
                    priority="med",
                ),
                user_id="d",
            )
        assert exc_info.value.status_code == 400


# ── Work-order completion + billing ───────────────────────────────────────


@pytest.mark.asyncio
async def test_complete_work_order_sums_items_into_billed_amount() -> None:
    svc = _make_service()
    contract = await _setup_contract(svc, currency="EUR")
    with patch("app.modules.service.service.event_bus.publish_detached"):
        ticket = await svc.create_ticket(
            ServiceTicketCreate(
                contract_id=contract.id,
                title="X",
                description="Y",
                priority="med",
                assigned_to="tech-1",
            ),
            user_id="d",
        )
        ticket.status = "in_progress"
        wo = await svc.create_work_order(
            WorkOrderCreate(
                ticket_id=ticket.id,
                technician_id="tech-1",
                status="scheduled",
                currency="EUR",
                items=[
                    WorkOrderItemCreate(
                        item_type="labor",
                        description="Service",
                        quantity=Decimal("2"),
                        unit="h",
                        unit_rate=Decimal("75"),
                    ),
                    WorkOrderItemCreate(
                        item_type="material",
                        description="Filter",
                        quantity=Decimal("1"),
                        unit="pcs",
                        unit_rate=Decimal("120"),
                        total=Decimal("120"),
                    ),
                ],
            ),
        )
        # Move WO to in_progress so we can complete it.
        wo.status = "in_progress"
        completed = await svc.complete_work_order(
            wo.id,
            WorkOrderCompleteRequest(
                debrief=DebriefReportCreate(
                    problem="No heat",
                    cause="Worn filter",
                    solution="Replaced filter and tested",
                    follow_up_required=False,
                ),
                customer_signature="data:image/png;base64,FAKE",
            ),
        )

    # 2h × 75 + 120 = 270
    assert Decimal(completed.billed_amount) == Decimal("270.00")
    assert completed.status == "completed"
    assert completed.customer_signature is not None
    # Debrief was persisted
    assert len(svc.debrief_repo.rows) == 1


@pytest.mark.asyncio
async def test_bill_work_order_emits_finance_event() -> None:
    svc = _make_service()
    contract = await _setup_contract(svc, currency="EUR")
    with patch("app.modules.service.service.event_bus.publish_detached") as bus:
        ticket = await svc.create_ticket(
            ServiceTicketCreate(
                contract_id=contract.id,
                title="X",
                description="Y",
                priority="med",
                assigned_to="tech-1",
            ),
            user_id="d",
        )
        ticket.status = "in_progress"
        wo = await svc.create_work_order(
            WorkOrderCreate(
                ticket_id=ticket.id,
                technician_id="tech-1",
                status="completed",
                currency="EUR",
                items=[],
            ),
        )
        bus.reset_mock()
        billed = await svc.bill_work_order(wo.id)

    assert billed.status == "billed"
    assert billed.billed_at is not None
    names = [c.args[0] for c in bus.call_args_list]
    assert "service.work_order.billed" in names


@pytest.mark.asyncio
async def test_bill_rejects_non_completed_work_order() -> None:
    svc = _make_service()
    contract = await _setup_contract(svc)
    with patch("app.modules.service.service.event_bus.publish_detached"):
        ticket = await svc.create_ticket(
            ServiceTicketCreate(
                contract_id=contract.id,
                title="X",
                description="Y",
                priority="med",
                assigned_to="tech-1",
            ),
            user_id="d",
        )
        ticket.status = "in_progress"
        wo = await svc.create_work_order(
            WorkOrderCreate(
                ticket_id=ticket.id,
                technician_id="tech-1",
                status="scheduled",
                items=[],
            ),
        )
        with pytest.raises(HTTPException) as exc_info:
            await svc.bill_work_order(wo.id)
        assert exc_info.value.status_code == 409


# ── compute_work_order_total ─────────────────────────────────────────────


def test_compute_work_order_total_sums_and_rounds() -> None:
    items = [
        SimpleNamespace(total=Decimal("100.005")),
        SimpleNamespace(total=Decimal("50.001")),
    ]
    assert compute_work_order_total(items) == Decimal("150.01")


def test_compute_work_order_total_empty_returns_zero() -> None:
    assert compute_work_order_total([]) == Decimal("0.00")


# ── Repository basics (stub-driven) ───────────────────────────────────────


@pytest.mark.asyncio
async def test_contract_repo_list_filter_by_status() -> None:
    svc = _make_service()
    with patch("app.modules.service.service.event_bus.publish_detached"):
        await svc.create_contract(_contract_data(status="draft"), user_id="u")
        await svc.create_contract(_contract_data(status="active"), user_id="u")
        await svc.create_contract(_contract_data(status="active"), user_id="u")

    rows, total = await svc.contract_repo.list_all(status="active")
    assert total == 2
    assert all(r.status == "active" for r in rows)


@pytest.mark.asyncio
async def test_asset_crud_via_service() -> None:
    svc = _make_service()
    contract = await _setup_contract(svc)
    asset = await svc.create_asset(
        ServiceAssetCreate(contract_id=contract.id, asset_type="boiler"),
    )
    got = await svc.get_asset(asset.id)
    assert got is asset

    with pytest.raises(HTTPException):
        await svc.get_asset(uuid.uuid4())


# ── Permission constants ──────────────────────────────────────────────────


def test_service_permission_constants_complete() -> None:
    """All 7 required permissions are declared at the expected roles."""
    expected = {
        "service.create": Role.EDITOR,
        "service.read": Role.VIEWER,
        "service.update": Role.EDITOR,
        "service.delete": Role.MANAGER,
        "service.dispatch": Role.MANAGER,
        "service.bill": Role.MANAGER,
        "service.close_contract": Role.MANAGER,
    }
    assert expected == SERVICE_PERMISSIONS


def test_register_service_permissions_idempotent() -> None:
    """Running register_service_permissions twice is safe."""
    register_service_permissions()
    register_service_permissions()  # should not raise / should not duplicate
    assert permission_registry.role_has_permission(Role.EDITOR, "service.create")
    assert permission_registry.role_has_permission(Role.VIEWER, "service.read")
    # Dispatch is manager-gated — editors can't dispatch.
    assert not permission_registry.role_has_permission(Role.EDITOR, "service.dispatch")
    assert permission_registry.role_has_permission(Role.MANAGER, "service.dispatch")


# ── Misc ──────────────────────────────────────────────────────────────────


def test_utcnow_iso_returns_parseable() -> None:
    """_utcnow_iso() emits a string that round-trips through fromisoformat."""
    ts = _utcnow_iso()
    parsed = datetime.fromisoformat(ts)
    assert parsed.tzinfo is not None


# ── source-channel on ticket creation ─────────────────────────────────────


@pytest.mark.asyncio
async def test_create_ticket_records_source() -> None:
    """A ticket carries its `source` channel for dispatcher triage + audit."""
    svc = _make_service()
    contract = await _setup_contract(svc)
    with patch("app.modules.service.service.event_bus.publish_detached") as bus:
        ticket = await svc.create_ticket(
            ServiceTicketCreate(
                contract_id=contract.id,
                title="Boiler down",
                description="No heat.",
                priority="med",
                source="portal",
            ),
            user_id="portal:abc",
        )
    assert ticket.source == "portal"
    # Event payload now carries source for downstream subscribers.
    payloads = [c.args[1] for c in bus.call_args_list]
    created_evt = next(p for p in payloads if "source" in p)
    assert created_evt["source"] == "portal"


@pytest.mark.asyncio
async def test_create_ticket_defaults_to_manual_source() -> None:
    """Backwards compat: omitted `source` defaults to manual."""
    svc = _make_service()
    contract = await _setup_contract(svc)
    with patch("app.modules.service.service.event_bus.publish_detached"):
        ticket = await svc.create_ticket(
            ServiceTicketCreate(
                contract_id=contract.id,
                title="X",
                description="Y",
                priority="med",
            ),
            user_id="dispatcher",
        )
    assert ticket.source == "manual"


# ── NCR-from-WO ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_file_ncr_from_wo_requires_project_scoped_contract() -> None:
    """409 when the parent contract is customer-only (no project_id)."""
    from app.modules.service.schemas import NCRFromWorkOrderRequest

    svc = _make_service()
    # Customer-only contract (no project_id).
    contract = await _setup_contract(svc, project_id=None)
    with patch("app.modules.service.service.event_bus.publish_detached"):
        ticket = await svc.create_ticket(
            ServiceTicketCreate(
                contract_id=contract.id,
                title="X",
                description="Y",
                priority="med",
            ),
            user_id="d",
        )
        wo = await svc.create_work_order(
            WorkOrderCreate(ticket_id=ticket.id, items=[]),
        )

    with pytest.raises(HTTPException) as exc_info:
        await svc.file_ncr_from_work_order(
            wo.id,
            NCRFromWorkOrderRequest(
                title="Crack found",
                description="Diagonal crack near support",
            ),
            user_id="engineer-1",
        )
    assert exc_info.value.status_code == 409


# ── Procurement / material request ────────────────────────────────────────


@pytest.mark.asyncio
async def test_request_purchase_for_item_publishes_event() -> None:
    """Material-line PR request publishes `service.work_order.material_requested`."""
    svc = _make_service()
    contract = await _setup_contract(svc)
    with patch("app.modules.service.service.event_bus.publish_detached") as bus:
        ticket = await svc.create_ticket(
            ServiceTicketCreate(
                contract_id=contract.id,
                title="X",
                description="Y",
                priority="med",
            ),
            user_id="d",
        )
        wo = await svc.create_work_order(
            WorkOrderCreate(
                ticket_id=ticket.id,
                items=[
                    WorkOrderItemCreate(
                        item_type="material",
                        description="Filter F7",
                        quantity=Decimal("2"),
                        unit="pcs",
                        unit_rate=Decimal("15.50"),
                    )
                ],
            )
        )
        # The stub work_order_item_repo stores items in a list; grab the one we just added.
        items = svc.work_order_item_repo.rows
        item = next(i for i in items if i.work_order_id == wo.id)

        bus.reset_mock()
        await svc.request_purchase_for_item(wo.id, item.id, user_id="engineer-1")

    event_names = [c.args[0] for c in bus.call_args_list]
    assert "service.work_order.material_requested" in event_names


@pytest.mark.asyncio
async def test_request_purchase_rejects_non_material_items() -> None:
    """Labor / travel items cannot be PR'd — 400."""
    svc = _make_service()
    contract = await _setup_contract(svc)
    with patch("app.modules.service.service.event_bus.publish_detached"):
        ticket = await svc.create_ticket(
            ServiceTicketCreate(
                contract_id=contract.id,
                title="X",
                description="Y",
                priority="med",
            ),
            user_id="d",
        )
        wo = await svc.create_work_order(
            WorkOrderCreate(
                ticket_id=ticket.id,
                items=[
                    WorkOrderItemCreate(
                        item_type="labor",
                        description="2h site visit",
                        quantity=Decimal("2"),
                        unit="h",
                        unit_rate=Decimal("80"),
                    )
                ],
            )
        )
        items = svc.work_order_item_repo.rows
        item = next(i for i in items if i.work_order_id == wo.id)

        with pytest.raises(HTTPException) as exc_info:
            await svc.request_purchase_for_item(wo.id, item.id, user_id="engineer-1")
        assert exc_info.value.status_code == 400


# ── Delete endpoints (wave M1 deep-pass) ──────────────────────────────────
#
# These tests pin the contract that 404 is raised when a delete targets a
# row that doesn't exist (so the router doesn't have to special-case the
# missing row itself), and that successful deletes drop the row from the
# stub repository. They also lock down that the repo.delete call really is
# routed through ``ServiceService`` — guarding against a regression where
# the router would call repo.delete() directly and bypass the existence
# check that ``get_*()`` provides.


@pytest.mark.asyncio
async def test_delete_contract_removes_row() -> None:
    """Happy path — existing contract is removed from the repo."""
    svc = _make_service()
    contract = await _setup_contract(svc)
    assert contract.id in svc.contract_repo.rows

    await svc.delete_contract(contract.id)

    assert contract.id not in svc.contract_repo.rows


@pytest.mark.asyncio
async def test_delete_contract_404_when_missing() -> None:
    """Deleting a non-existent contract raises 404, not 500."""
    svc = _make_service()
    with pytest.raises(HTTPException) as exc_info:
        await svc.delete_contract(uuid.uuid4())
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_delete_asset_removes_row() -> None:
    svc = _make_service()
    contract = await _setup_contract(svc)
    with patch("app.modules.service.service.event_bus.publish_detached"):
        asset = await svc.create_asset(
            ServiceAssetCreate(contract_id=contract.id, asset_type="boiler"),
        )
    assert asset.id in svc.asset_repo.rows

    await svc.delete_asset(asset.id)

    assert asset.id not in svc.asset_repo.rows


@pytest.mark.asyncio
async def test_delete_asset_404_when_missing() -> None:
    svc = _make_service()
    with pytest.raises(HTTPException) as exc_info:
        await svc.delete_asset(uuid.uuid4())
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_delete_ticket_removes_row() -> None:
    svc = _make_service()
    contract = await _setup_contract(svc)
    with patch("app.modules.service.service.event_bus.publish_detached"):
        ticket = await svc.create_ticket(
            ServiceTicketCreate(
                contract_id=contract.id,
                title="To be deleted",
                description="",
                priority="med",
            ),
            user_id="dispatcher",
        )
    assert ticket.id in svc.ticket_repo.rows

    await svc.delete_ticket(ticket.id)

    assert ticket.id not in svc.ticket_repo.rows


@pytest.mark.asyncio
async def test_delete_ticket_404_when_missing() -> None:
    svc = _make_service()
    with pytest.raises(HTTPException) as exc_info:
        await svc.delete_ticket(uuid.uuid4())
    assert exc_info.value.status_code == 404
