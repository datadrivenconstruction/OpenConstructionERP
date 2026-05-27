"""Unit tests for :class:`EquipmentService` and pure helpers.

Scope:
    * compute_next_due — hours/km/date triggers
    * is_blocked_from_assignment — inspection + status gates
    * assign_to_project — event emission + ValueError on blocked
    * compute_rental_billing — day vs hour rates
    * depreciation_value_at — linear method
    * record_damage — auto-creates a maintenance work order
    * record_telemetry — only updates equipment counters when reading newer
    * repository CRUD basics
    * permission constants registered
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.modules.equipment.models import (
    Equipment,
    EquipmentRental,
    MaintenanceSchedule,
)
from app.modules.equipment.schemas import (
    DamageReportCreate,
    EquipmentCreate,
    InspectionCreate,
    TelemetryReadingCreate,
)
from app.modules.equipment.service import (
    EquipmentService,
    compute_next_due,
    compute_rental_billing,
    depreciation_value_at,
)

# ── Helpers / stubs ──────────────────────────────────────────────────────


PROJECT_ID = uuid.uuid4()


class _StubSession:
    def __init__(self) -> None:
        self._added: list[Any] = []

    def add(self, obj: Any) -> None:
        self._added.append(obj)

    async def flush(self) -> None:
        pass

    async def refresh(self, obj: Any) -> None:
        pass

    async def execute(self, _stmt: Any) -> Any:
        return SimpleNamespace(scalars=lambda: _EmptyScalars(), scalar_one=lambda: 0)

    async def delete(self, obj: Any) -> None:
        pass

    def expire_all(self) -> None:
        pass


class _EmptyScalars:
    def all(self) -> list:
        return []


def _make_service() -> EquipmentService:
    """Construct an EquipmentService with stub repositories.

    Each repo is a MagicMock with async methods so callers can swap in
    return values per-test.
    """
    service = EquipmentService.__new__(EquipmentService)
    service.session = _StubSession()
    service.equipment_repo = _make_repo()
    service.type_repo = _make_repo()
    service.telemetry_repo = _make_repo()
    service.schedule_repo = _make_repo()
    service.workorder_repo = _make_repo()
    service.inspection_repo = _make_repo()
    service.rental_repo = _make_repo()
    service.fuel_repo = _make_repo()
    service.parts_repo = _make_repo()
    service.damage_repo = _make_repo()
    return service


def _make_repo() -> MagicMock:
    repo = MagicMock()
    # default async returns
    repo.get_by_id = AsyncMock(return_value=None)
    repo.get_by_code = AsyncMock(return_value=None)
    repo.create = AsyncMock(side_effect=lambda x: _attach_meta(x))
    repo.update_fields = AsyncMock(return_value=None)
    repo.delete = AsyncMock(return_value=None)
    repo.list_all = AsyncMock(return_value=[])
    repo.list_for_equipment = AsyncMock(return_value=[])
    repo.list_active = AsyncMock(return_value=[])
    repo.list_ = AsyncMock(return_value=([], 0))
    repo.list_since = AsyncMock(return_value=[])
    repo.latest_telemetry = AsyncMock(return_value=None)
    repo.count_open_for_equipment = AsyncMock(return_value=0)
    repo.count_active = AsyncMock(return_value=0)
    repo.cost_in_range = AsyncMock(return_value=Decimal("0"))
    repo.expiring_within = AsyncMock(return_value=[])
    repo.expired_for_equipment = AsyncMock(return_value=[])
    repo.fuel_consumption = AsyncMock(return_value={"liters": Decimal("0"), "cost": Decimal("0")})
    return repo


def _attach_meta(obj: Any) -> Any:
    if getattr(obj, "id", None) is None:
        obj.id = uuid.uuid4()
    now = datetime.now(UTC)
    if not hasattr(obj, "created_at") or obj.created_at is None:
        obj.created_at = now
    if not hasattr(obj, "updated_at") or obj.updated_at is None:
        obj.updated_at = now
    return obj


def _make_equipment(**overrides: Any) -> Equipment:
    e = Equipment(
        code=overrides.get("code", "EQ-TEST"),
        name=overrides.get("name", "Test Excavator"),
        type_code=overrides.get("type_code", "excavator"),
        ownership=overrides.get("ownership", "owned"),
        status=overrides.get("status", "active"),
        hour_meter=Decimal(str(overrides.get("hour_meter", 1000))),
        odometer_km=Decimal(str(overrides.get("odometer_km", 5000))),
        depreciation_method=overrides.get("depreciation_method", "linear"),
        purchase_date=overrides.get("purchase_date"),
        purchase_value=overrides.get("purchase_value"),
        useful_life_years=overrides.get("useful_life_years"),
        residual_value=overrides.get("residual_value"),
    )
    e.id = overrides.get("id", uuid.uuid4())
    e.last_telemetry_at = overrides.get("last_telemetry_at")
    e.location_lat = overrides.get("location_lat")
    e.location_lng = overrides.get("location_lng")
    e.created_at = datetime.now(UTC)
    e.updated_at = datetime.now(UTC)
    e.metadata_ = {}
    e.currency = "EUR"
    return e


# ── compute_next_due ─────────────────────────────────────────────────────


def test_compute_next_due_hours_uses_last_completed_meter() -> None:
    s = MaintenanceSchedule(
        equipment_id=uuid.uuid4(),
        trigger_type="hours",
        trigger_threshold=Decimal("500"),
        last_completed_meter=Decimal("1000"),
    )
    result = compute_next_due(s, current_hour_meter=Decimal("1200"))
    assert result["next_due_meter"] == Decimal("1500")
    assert result["next_due_date"] is None


def test_compute_next_due_hours_falls_back_to_current() -> None:
    s = MaintenanceSchedule(
        equipment_id=uuid.uuid4(),
        trigger_type="hours",
        trigger_threshold=Decimal("250"),
    )
    result = compute_next_due(s, current_hour_meter=Decimal("800"))
    assert result["next_due_meter"] == Decimal("1050")


def test_compute_next_due_km() -> None:
    s = MaintenanceSchedule(
        equipment_id=uuid.uuid4(),
        trigger_type="km",
        trigger_threshold=Decimal("10000"),
        last_completed_meter=Decimal("5000"),
    )
    result = compute_next_due(s, current_km=Decimal("7000"))
    assert result["next_due_meter"] == Decimal("15000")


def test_compute_next_due_date() -> None:
    s = MaintenanceSchedule(
        equipment_id=uuid.uuid4(),
        trigger_type="date",
        trigger_threshold=Decimal("90"),
        last_completed_at="2026-01-01",
    )
    result = compute_next_due(s, today="2026-02-01")
    assert result["next_due_date"] == "2026-04-01"
    assert result["next_due_meter"] is None


# ── compute_rental_billing ───────────────────────────────────────────────


def test_compute_rental_billing_by_day() -> None:
    rental = EquipmentRental(
        equipment_id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        start_date="2026-01-01",
        internal_rate_per_day=Decimal("200"),
        internal_rate_per_hour=Decimal("0"),
        currency="EUR",
        status="active",
    )
    # 1..10 January = 10 days
    bill = compute_rental_billing(rental, "2026-01-01", "2026-01-10")
    assert bill == Decimal("2000")


def test_compute_rental_billing_by_hour_preferred() -> None:
    rental = EquipmentRental(
        equipment_id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        start_date="2026-01-01",
        internal_rate_per_day=Decimal("200"),
        internal_rate_per_hour=Decimal("30"),
        currency="EUR",
        status="active",
    )
    bill = compute_rental_billing(rental, "2026-01-01", "2026-01-10", hours_logged=Decimal("40"))
    assert bill == Decimal("1200")


def test_compute_rental_billing_zero_for_invalid_dates() -> None:
    rental = EquipmentRental(
        equipment_id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        start_date="2026-01-01",
        internal_rate_per_day=Decimal("200"),
        internal_rate_per_hour=Decimal("0"),
        currency="EUR",
        status="active",
    )
    assert compute_rental_billing(rental, "garbage", "garbage") == Decimal("0")


# ── depreciation_value_at ────────────────────────────────────────────────


def test_depreciation_linear_partial() -> None:
    today = date.today()
    purchase = today - timedelta(days=365 * 5)  # five years ago
    e = _make_equipment(
        purchase_date=purchase.isoformat(),
        purchase_value=Decimal("100000"),
        useful_life_years=10,
        residual_value=Decimal("10000"),
        depreciation_method="linear",
    )
    nbv = depreciation_value_at(e, as_of_date=today.isoformat())
    # 5/10 elapsed → ~55_000 (100k - (90k * 0.5))
    assert Decimal("54500") < nbv < Decimal("55500")


def test_depreciation_linear_after_life() -> None:
    today = date.today()
    purchase = today - timedelta(days=365 * 20)
    e = _make_equipment(
        purchase_date=purchase.isoformat(),
        purchase_value=Decimal("100000"),
        useful_life_years=10,
        residual_value=Decimal("10000"),
        depreciation_method="linear",
    )
    nbv = depreciation_value_at(e, as_of_date=today.isoformat())
    assert nbv == Decimal("10000")


def test_depreciation_missing_data_returns_zero() -> None:
    e = _make_equipment()
    assert depreciation_value_at(e) == Decimal("0")


def test_depreciation_unsupported_method_raises() -> None:
    """Methods other than linear / declining_balance still 501.

    ``declining_balance`` is now a first-class method; the new sentinel for
    "method not implemented" is an arbitrary string the dispatch doesn't know.
    """
    today = date(2026, 1, 1)
    e = _make_equipment(
        depreciation_method="units_of_production",
        purchase_value=Decimal("100000"),
        purchase_date=(today - timedelta(days=365)).isoformat(),
        useful_life_years=5,
        residual_value=Decimal("10000"),
    )
    with pytest.raises(NotImplementedError):
        depreciation_value_at(e, as_of_date=today.isoformat())


def test_depreciation_declining_balance_lower_than_linear() -> None:
    """DDB always sits below SL on the same unit at the same date.

    The whole point of DDB is to front-load depreciation. Mid-life NBV under
    DDB must be strictly less than under SL.
    """
    today = date(2026, 1, 1)
    purchased = (today - timedelta(days=2 * 365)).isoformat()  # 2 of 5 years in
    sl = _make_equipment(
        purchase_value=Decimal("100000"),
        purchase_date=purchased,
        depreciation_method="linear",
        useful_life_years=5,
        residual_value=Decimal("10000"),
    )
    ddb = _make_equipment(
        purchase_value=Decimal("100000"),
        purchase_date=purchased,
        depreciation_method="declining_balance",
        useful_life_years=5,
        residual_value=Decimal("10000"),
    )
    nbv_sl = depreciation_value_at(sl, as_of_date=today.isoformat())
    nbv_ddb = depreciation_value_at(ddb, as_of_date=today.isoformat())
    # Both must be above residual.
    assert nbv_sl > Decimal("10000")
    assert nbv_ddb > Decimal("10000")
    # DDB front-loads depreciation, so mid-life it sits below linear.
    assert nbv_ddb < nbv_sl


def test_depreciation_declining_balance_lands_on_residual_at_eol() -> None:
    """End-of-life DDB hits ``residual_value`` to the cent."""
    today = date(2026, 1, 1)
    # Fully past useful life
    purchased = (today - timedelta(days=6 * 365)).isoformat()
    ddb = _make_equipment(
        purchase_value=Decimal("100000"),
        purchase_date=purchased,
        depreciation_method="declining_balance",
        useful_life_years=5,
        residual_value=Decimal("10000"),
    )
    nbv = depreciation_value_at(ddb, as_of_date=today.isoformat())
    assert nbv == Decimal("10000")


# ── is_blocked_from_assignment ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_is_blocked_when_status_not_active() -> None:
    svc = _make_service()
    e = _make_equipment(status="under_maintenance")
    svc.equipment_repo.get_by_id = AsyncMock(return_value=e)
    blocked = await svc.is_blocked_from_assignment(e.id)
    assert blocked is True


@pytest.mark.asyncio
async def test_is_blocked_when_inspection_expired() -> None:
    svc = _make_service()
    e = _make_equipment(status="active")
    svc.equipment_repo.get_by_id = AsyncMock(return_value=e)

    # Fake one expired annual inspection
    fake_insp = SimpleNamespace(
        equipment_id=e.id,
        inspection_type="annual",
        valid_until="2020-01-01",
    )
    svc.inspection_repo.list_for_equipment = AsyncMock(return_value=[fake_insp])
    blocked = await svc.is_blocked_from_assignment(e.id, today="2026-05-12")
    assert blocked is True


@pytest.mark.asyncio
async def test_is_not_blocked_when_active_and_valid_inspection() -> None:
    svc = _make_service()
    e = _make_equipment(status="active")
    svc.equipment_repo.get_by_id = AsyncMock(return_value=e)

    fake_insp = SimpleNamespace(
        equipment_id=e.id,
        inspection_type="annual",
        valid_until="2099-01-01",
    )
    svc.inspection_repo.list_for_equipment = AsyncMock(return_value=[fake_insp])
    blocked = await svc.is_blocked_from_assignment(e.id, today="2026-05-12")
    assert blocked is False


# ── assign_to_project ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_assign_to_project_raises_when_blocked() -> None:
    svc = _make_service()
    e = _make_equipment(status="under_maintenance")
    svc.equipment_repo.get_by_id = AsyncMock(return_value=e)

    with pytest.raises(ValueError):
        await svc.assign_to_project(
            e.id,
            PROJECT_ID,
            start_date="2026-05-12",
            daily_rate=Decimal("200"),
            hourly_rate=Decimal("30"),
        )


@pytest.mark.asyncio
async def test_assign_to_project_succeeds_and_emits_event() -> None:
    svc = _make_service()
    e = _make_equipment(status="active")
    svc.equipment_repo.get_by_id = AsyncMock(return_value=e)
    svc.inspection_repo.list_for_equipment = AsyncMock(return_value=[])

    captured: list[str] = []

    def _capture(event_name: str, *_args: Any, **_kwargs: Any) -> None:
        captured.append(event_name)

    with patch(
        "app.modules.equipment.service.event_bus.publish_detached",
        side_effect=_capture,
    ):
        rental = await svc.assign_to_project(
            e.id,
            PROJECT_ID,
            start_date="2026-05-12",
            daily_rate=Decimal("200"),
            hourly_rate=Decimal("30"),
            currency="EUR",
        )

    assert rental.equipment_id == e.id
    assert rental.project_id == PROJECT_ID
    assert rental.status == "active"
    assert "equipment.assigned" in captured


@pytest.mark.asyncio
async def test_assign_to_project_rejects_inverted_dates() -> None:
    """end_date before start_date is a corrupt billing window — rejected.

    Without the guard the rental persists but compute_rental_billing
    silently returns 0 and the unit never counts as utilized.
    """
    svc = _make_service()
    e = _make_equipment(status="active")
    svc.equipment_repo.get_by_id = AsyncMock(return_value=e)
    svc.inspection_repo.list_for_equipment = AsyncMock(return_value=[])

    with pytest.raises(ValueError):
        await svc.assign_to_project(
            e.id,
            PROJECT_ID,
            start_date="2026-05-12",
            daily_rate=Decimal("200"),
            hourly_rate=Decimal("30"),
            end_date="2026-05-01",
        )


# ── complete_work_order state guard ──────────────────────────────────────


@pytest.mark.asyncio
async def test_complete_work_order_rejects_double_completion() -> None:
    """Re-completing a completed WO must 409, not re-roll the schedule.

    The bug it guards: a second /complete call would bump
    last_completed_meter and push next_due_meter further out, so the
    unit would silently skip its next service interval.
    """
    from fastapi import HTTPException

    svc = _make_service()
    wo = SimpleNamespace(
        id=uuid.uuid4(),
        equipment_id=uuid.uuid4(),
        schedule_id=None,
        status="completed",
    )
    svc.workorder_repo.get_by_id = AsyncMock(return_value=wo)

    with pytest.raises(HTTPException) as exc:
        await svc.complete_work_order(wo.id)
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_complete_work_order_rejects_cancelled() -> None:
    """A cancelled WO cannot be silently resurrected to completed."""
    from fastapi import HTTPException

    svc = _make_service()
    wo = SimpleNamespace(
        id=uuid.uuid4(),
        equipment_id=uuid.uuid4(),
        schedule_id=None,
        status="cancelled",
    )
    svc.workorder_repo.get_by_id = AsyncMock(return_value=wo)

    with pytest.raises(HTTPException) as exc:
        await svc.complete_work_order(wo.id)
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_complete_work_order_happy_path_scheduled() -> None:
    """A scheduled WO with no parent schedule completes cleanly."""
    svc = _make_service()
    wo = SimpleNamespace(
        id=uuid.uuid4(),
        equipment_id=uuid.uuid4(),
        schedule_id=None,
        status="scheduled",
    )
    svc.workorder_repo.get_by_id = AsyncMock(return_value=wo)
    captured: dict[str, Any] = {}

    async def _capture(_id: Any, **fields: Any) -> None:
        captured.update(fields)

    svc.workorder_repo.update_fields = AsyncMock(side_effect=_capture)

    result = await svc.complete_work_order(wo.id, completed_at="2026-05-15")
    assert result is wo
    assert captured["status"] == "completed"
    assert captured["completed_at"] == "2026-05-15"


# ── return_rental state guard ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_return_rental_rejects_double_return() -> None:
    """Returning an already-returned rental must not overwrite end_date."""
    from fastapi import HTTPException

    svc = _make_service()
    rental = SimpleNamespace(
        id=uuid.uuid4(),
        start_date="2026-01-01",
        end_date="2026-03-01",
        status="returned",
    )
    svc.rental_repo.get_by_id = AsyncMock(return_value=rental)

    with pytest.raises(HTTPException) as exc:
        await svc.return_rental(rental.id)
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_return_rental_rejects_end_before_start() -> None:
    """A return date earlier than start_date is rejected (409)."""
    from fastapi import HTTPException

    svc = _make_service()
    rental = SimpleNamespace(
        id=uuid.uuid4(),
        start_date="2026-05-01",
        end_date=None,
        status="active",
    )
    svc.rental_repo.get_by_id = AsyncMock(return_value=rental)

    with pytest.raises(HTTPException) as exc:
        await svc.return_rental(rental.id, end_date="2026-04-01")
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_return_rental_happy_path() -> None:
    """An active rental returns cleanly and stamps the end date."""
    svc = _make_service()
    rental = SimpleNamespace(
        id=uuid.uuid4(),
        start_date="2026-01-01",
        end_date=None,
        status="active",
    )
    svc.rental_repo.get_by_id = AsyncMock(return_value=rental)
    captured: dict[str, Any] = {}

    async def _capture(_id: Any, **fields: Any) -> None:
        captured.update(fields)

    svc.rental_repo.update_fields = AsyncMock(side_effect=_capture)

    await svc.return_rental(rental.id, end_date="2026-06-01")
    assert captured["status"] == "returned"
    assert captured["end_date"] == "2026-06-01"


# ── fleet utilization (overlap merge + N+1 removal) ──────────────────────


def test_busy_days_merges_overlapping_rentals() -> None:
    """Concurrent rentals must not double-count a shared day.

    Two rentals fully covering Jan 1–10 should yield 10 busy days, not
    20 (which would push utilization over 100% before the clamp).
    """
    from app.modules.equipment.repository import _busy_days_in_window

    r1 = SimpleNamespace(start_date="2026-01-01", end_date="2026-01-10")
    r2 = SimpleNamespace(start_date="2026-01-05", end_date="2026-01-10")
    busy = _busy_days_in_window([r1, r2], date(2026, 1, 1), date(2026, 1, 31))
    assert busy == 10


# ── record_damage ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_record_damage_creates_work_order() -> None:
    svc = _make_service()
    e = _make_equipment()
    svc.equipment_repo.get_by_id = AsyncMock(return_value=e)

    created_workorders: list[Any] = []

    async def _record_wo(wo: Any) -> Any:
        _attach_meta(wo)
        created_workorders.append(wo)
        return wo

    svc.workorder_repo.create = AsyncMock(side_effect=_record_wo)

    captured: list[str] = []

    def _capture(event_name: str, *_args: Any, **_kwargs: Any) -> None:
        captured.append(event_name)

    with patch(
        "app.modules.equipment.service.event_bus.publish_detached",
        side_effect=_capture,
    ):
        damage = await svc.record_damage(
            DamageReportCreate(
                equipment_id=e.id,
                reported_at="2026-05-12",
                severity="major",
                description="Hydraulic boom cracked at base",
            )
        )

    assert damage.severity == "major"
    assert len(created_workorders) == 1
    wo = created_workorders[0]
    assert wo.equipment_id == e.id
    assert wo.status == "scheduled"
    assert "Damage" in (wo.work_summary or "")
    assert "equipment.damage_reported" in captured


# ── record_telemetry ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_record_telemetry_updates_when_newer() -> None:
    svc = _make_service()
    old_time = datetime.now(UTC) - timedelta(hours=2)
    e = _make_equipment(last_telemetry_at=old_time)
    svc.equipment_repo.get_by_id = AsyncMock(return_value=e)

    captured_updates: dict[str, Any] = {}

    async def _capture_update(_id: Any, **fields: Any) -> None:
        captured_updates.update(fields)

    svc.equipment_repo.update_fields = AsyncMock(side_effect=_capture_update)

    new_time = datetime.now(UTC)
    await svc.record_telemetry(
        e.id,
        TelemetryReadingCreate(
            recorded_at=new_time,
            hour_meter=Decimal("1500"),
            odometer_km=Decimal("8000"),
            lat=51.5,
            lng=-0.1,
        ),
    )

    assert captured_updates["hour_meter"] == Decimal("1500")
    assert captured_updates["odometer_km"] == Decimal("8000")
    assert captured_updates["last_telemetry_at"] == new_time


@pytest.mark.asyncio
async def test_record_telemetry_skips_when_older() -> None:
    svc = _make_service()
    new_time = datetime.now(UTC)
    e = _make_equipment(last_telemetry_at=new_time)
    svc.equipment_repo.get_by_id = AsyncMock(return_value=e)

    called = False

    async def _capture_update(_id: Any, **_fields: Any) -> None:
        nonlocal called
        called = True

    svc.equipment_repo.update_fields = AsyncMock(side_effect=_capture_update)

    old_time = new_time - timedelta(hours=5)
    await svc.record_telemetry(
        e.id,
        TelemetryReadingCreate(
            recorded_at=old_time,
            hour_meter=Decimal("9999"),
        ),
    )

    # Older reading must NOT update the equipment counters
    assert called is False


# ── repository CRUD basics ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_equipment_rejects_duplicate_code() -> None:
    svc = _make_service()
    svc.equipment_repo.get_by_code = AsyncMock(return_value=_make_equipment())

    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        await svc.create_equipment(EquipmentCreate(code="EQ-DUP", name="Dup", type_code="excavator"))
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_create_equipment_happy_path() -> None:
    svc = _make_service()
    svc.equipment_repo.get_by_code = AsyncMock(return_value=None)
    svc.equipment_repo.create = AsyncMock(side_effect=_attach_meta)

    e = await svc.create_equipment(EquipmentCreate(code="EQ-100", name="Cat 320", type_code="excavator"))
    assert e.code == "EQ-100"
    assert e.id is not None


@pytest.mark.asyncio
async def test_get_equipment_not_found() -> None:
    svc = _make_service()
    svc.equipment_repo.get_by_id = AsyncMock(return_value=None)

    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        await svc.get_equipment(uuid.uuid4())
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_check_inspection_compliance_marks_expired() -> None:
    svc = _make_service()
    fake_eid = uuid.uuid4()
    insps = [
        SimpleNamespace(
            equipment_id=fake_eid,
            inspection_type="annual",
            valid_until="2020-01-01",
        ),
        SimpleNamespace(
            equipment_id=fake_eid,
            inspection_type="quarterly",
            valid_until="2099-01-01",
        ),
    ]
    svc.inspection_repo.list_for_equipment = AsyncMock(return_value=insps)
    result = await svc.check_inspection_compliance(fake_eid, today="2026-05-12")
    assert result == {"annual": True, "quarterly": False}


@pytest.mark.asyncio
async def test_create_inspection_invokes_repo() -> None:
    svc = _make_service()
    e = _make_equipment()
    svc.equipment_repo.get_by_id = AsyncMock(return_value=e)
    svc.inspection_repo.create = AsyncMock(side_effect=_attach_meta)

    insp = await svc.create_inspection(
        InspectionCreate(
            equipment_id=e.id,
            inspection_type="annual",
            inspected_at="2026-01-01",
            valid_until="2027-01-01",
        )
    )
    assert insp.inspection_type == "annual"
    assert insp.valid_until == "2027-01-01"


# ── permissions registration ─────────────────────────────────────────────


def test_permissions_registered() -> None:
    from app.core.permissions import permission_registry
    from app.modules.equipment.permissions import register_equipment_permissions

    register_equipment_permissions()
    perms = permission_registry.list_all()
    expected = {
        "equipment.create",
        "equipment.read",
        "equipment.update",
        "equipment.delete",
        "equipment.assign",
        "equipment.record_telemetry",
        "equipment.complete_maintenance",
        "equipment.record_damage",
        "equipment.approve_inspection",
    }
    assert expected.issubset(set(perms))


# ── Fuel / parts event emission ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_fuel_log_emits_event_with_active_project() -> None:
    """Recording a fuel fill emits `equipment.fuel_logged` carrying project_id.

    When the equipment unit is on an active rental on the fuel-log date, the
    rental's project_id is surfaced on the event so the finance subscriber
    can credit equipment cost to that project.
    """
    from app.modules.equipment.schemas import FuelLogCreate

    svc = _make_service()
    equipment_id = uuid.uuid4()
    project_id = uuid.uuid4()
    svc.equipment_repo.get_by_id = AsyncMock(return_value=_make_equipment(id=equipment_id))
    rental = SimpleNamespace(
        id=uuid.uuid4(),
        equipment_id=equipment_id,
        project_id=project_id,
        start_date="2026-01-01",
        end_date=None,
        status="active",
    )
    svc.rental_repo.list_ = AsyncMock(return_value=([rental], 1))

    with patch("app.modules.equipment.service.event_bus.publish_detached") as bus:
        await svc.create_fuel_log(
            FuelLogCreate(
                equipment_id=equipment_id,
                logged_at="2026-05-13",
                fuel_liters=Decimal("120"),
                cost=Decimal("180.50"),
                currency="EUR",
            )
        )

    names = [c.args[0] for c in bus.call_args_list]
    assert "equipment.fuel_logged" in names
    payload = next(c.args[1] for c in bus.call_args_list if c.args[0] == "equipment.fuel_logged")
    assert payload["project_id"] == str(project_id)
    assert payload["cost"] == "180.50"


@pytest.mark.asyncio
async def test_create_fuel_log_emits_event_without_project_when_idle() -> None:
    """When the equipment is between rentals, project_id is None."""
    from app.modules.equipment.schemas import FuelLogCreate

    svc = _make_service()
    equipment_id = uuid.uuid4()
    svc.equipment_repo.get_by_id = AsyncMock(return_value=_make_equipment(id=equipment_id))
    svc.rental_repo.list_ = AsyncMock(return_value=([], 0))

    with patch("app.modules.equipment.service.event_bus.publish_detached") as bus:
        await svc.create_fuel_log(
            FuelLogCreate(
                equipment_id=equipment_id,
                logged_at="2026-05-13",
                fuel_liters=Decimal("80"),
                cost=Decimal("120"),
                currency="EUR",
            )
        )

    payload = next(c.args[1] for c in bus.call_args_list if c.args[0] == "equipment.fuel_logged")
    assert payload["project_id"] is None


# ── Telemetry-driven WO auto-trigger ──────────────────────────────────────


@pytest.mark.asyncio
async def test_record_telemetry_triggers_maintenance_check() -> None:
    """A newer telemetry reading calls generate_due_work_orders.

    The trigger is the *only* path that lets a routine telematics ping
    create the WO. Without it, a unit can sail past its service hour
    threshold for weeks before anyone notices.
    """
    svc = _make_service()
    equipment_id = uuid.uuid4()
    svc.equipment_repo.get_by_id = AsyncMock(return_value=_make_equipment(id=equipment_id, last_telemetry_at=None))
    triggered: list[uuid.UUID] = []

    async def fake_generator(*, equipment_id: uuid.UUID, lookahead_hours: float) -> list:
        triggered.append(equipment_id)
        return []

    svc.generate_due_work_orders = fake_generator  # type: ignore[assignment]

    with patch("app.modules.equipment.service.event_bus.publish_detached"):
        await svc.record_telemetry(
            equipment_id,
            TelemetryReadingCreate(
                recorded_at=datetime(2026, 5, 13, 9, 0, tzinfo=UTC),
                hour_meter=Decimal("1250"),
            ),
        )

    assert triggered == [equipment_id]


# ── generate_due_work_orders ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_generate_due_work_orders_hours_fires_within_lookahead() -> None:
    """An 'hours' schedule whose next_due_meter is within the lookahead of
    the unit's current hour-meter produces a scheduled WO + event."""
    svc = _make_service()
    eid = uuid.uuid4()
    equipment = _make_equipment(id=eid, hour_meter=1480)
    schedule = SimpleNamespace(
        id=uuid.uuid4(),
        equipment_id=eid,
        trigger_type="hours",
        next_due_meter=Decimal("1500"),  # 20 h away — within 50 h lookahead
        next_due_date=None,
        description="500h service",
    )
    svc.schedule_repo.list_active = AsyncMock(return_value=[schedule])
    svc.equipment_repo.get_by_id = AsyncMock(return_value=equipment)
    svc.workorder_repo.list_ = AsyncMock(return_value=([], 0))

    created: list[Any] = []

    async def _create(wo: Any) -> Any:
        _attach_meta(wo)
        created.append(wo)
        return wo

    svc.workorder_repo.create = AsyncMock(side_effect=_create)

    captured: list[str] = []

    def _cap(name: str, *_a: Any, **_k: Any) -> None:
        captured.append(name)

    with patch(
        "app.modules.equipment.service.event_bus.publish_detached",
        side_effect=_cap,
    ):
        wos = await svc.generate_due_work_orders(equipment_id=eid)

    assert len(wos) == 1
    assert created[0].schedule_id == schedule.id
    assert created[0].status == "scheduled"
    assert "equipment.maintenance_due" in captured


@pytest.mark.asyncio
async def test_generate_due_work_orders_dedupes_open_wo() -> None:
    """If an open WO already references the schedule, no duplicate is made."""
    svc = _make_service()
    eid = uuid.uuid4()
    sid = uuid.uuid4()
    equipment = _make_equipment(id=eid, hour_meter=1490)
    schedule = SimpleNamespace(
        id=sid,
        equipment_id=eid,
        trigger_type="hours",
        next_due_meter=Decimal("1500"),
        next_due_date=None,
        description="x",
    )
    existing_wo = SimpleNamespace(id=uuid.uuid4(), schedule_id=sid)
    svc.schedule_repo.list_active = AsyncMock(return_value=[schedule])
    svc.equipment_repo.get_by_id = AsyncMock(return_value=equipment)
    svc.workorder_repo.list_ = AsyncMock(return_value=([existing_wo], 1))
    svc.workorder_repo.create = AsyncMock()

    wos = await svc.generate_due_work_orders(equipment_id=eid)
    assert wos == []
    svc.workorder_repo.create.assert_not_called()


@pytest.mark.asyncio
async def test_generate_due_work_orders_skips_not_yet_due() -> None:
    """A schedule far from due (beyond lookahead) yields nothing."""
    svc = _make_service()
    eid = uuid.uuid4()
    equipment = _make_equipment(id=eid, hour_meter=1000)
    schedule = SimpleNamespace(
        id=uuid.uuid4(),
        equipment_id=eid,
        trigger_type="hours",
        next_due_meter=Decimal("1500"),  # 500 h away — well beyond 50 h
        next_due_date=None,
        description="x",
    )
    svc.schedule_repo.list_active = AsyncMock(return_value=[schedule])
    svc.equipment_repo.get_by_id = AsyncMock(return_value=equipment)
    svc.workorder_repo.create = AsyncMock()

    wos = await svc.generate_due_work_orders(equipment_id=eid)
    assert wos == []
    svc.workorder_repo.create.assert_not_called()


# ── create_schedule auto-computes next-due ───────────────────────────────


@pytest.mark.asyncio
async def test_create_schedule_auto_computes_next_due_meter() -> None:
    """When next_due_* is omitted, create_schedule projects it from the
    unit's current meter + threshold."""
    from app.modules.equipment.schemas import MaintenanceScheduleCreate

    svc = _make_service()
    eid = uuid.uuid4()
    equipment = _make_equipment(id=eid, hour_meter=1200)
    svc.equipment_repo.get_by_id = AsyncMock(return_value=equipment)
    svc.schedule_repo.create = AsyncMock(side_effect=_attach_meta)

    sched = await svc.create_schedule(
        MaintenanceScheduleCreate(
            equipment_id=eid,
            trigger_type="hours",
            trigger_threshold=Decimal("250"),
        )
    )
    assert sched.next_due_meter == Decimal("1450")
    assert sched.next_due_date is None


# ── create_rental resolves the active project for fuel/parts ─────────────


@pytest.mark.asyncio
async def test_create_rental_happy_path_emits_assigned() -> None:
    """create_rental delegates to assign_to_project and emits the event."""
    from app.modules.equipment.schemas import EquipmentRentalCreate

    svc = _make_service()
    eid = uuid.uuid4()
    svc.equipment_repo.get_by_id = AsyncMock(return_value=_make_equipment(id=eid, status="active"))
    svc.inspection_repo.list_for_equipment = AsyncMock(return_value=[])

    captured: list[str] = []

    def _cap(name: str, *_a: Any, **_k: Any) -> None:
        captured.append(name)

    with patch(
        "app.modules.equipment.service.event_bus.publish_detached",
        side_effect=_cap,
    ):
        rental = await svc.create_rental(
            EquipmentRentalCreate(
                equipment_id=eid,
                project_id=PROJECT_ID,
                start_date="2026-05-15",
                internal_rate_per_day=Decimal("300"),
                internal_rate_per_hour=Decimal("45"),
                currency="USD",
            )
        )
    assert rental.status == "active"
    assert rental.currency == "USD"
    assert "equipment.assigned" in captured


# ── parts log event carries project + line total ─────────────────────────


@pytest.mark.asyncio
async def test_create_parts_log_emits_event_with_line_total() -> None:
    from app.modules.equipment.schemas import PartsLogCreate

    svc = _make_service()
    eid = uuid.uuid4()
    pid = uuid.uuid4()
    svc.equipment_repo.get_by_id = AsyncMock(return_value=_make_equipment(id=eid))
    rental = SimpleNamespace(
        id=uuid.uuid4(),
        equipment_id=eid,
        project_id=pid,
        start_date="2026-01-01",
        end_date=None,
        status="active",
    )
    svc.rental_repo.list_ = AsyncMock(return_value=([rental], 1))

    with patch("app.modules.equipment.service.event_bus.publish_detached") as bus:
        await svc.create_parts_log(
            PartsLogCreate(
                equipment_id=eid,
                part_number="FILT-9",
                quantity=Decimal("3"),
                unit_cost=Decimal("12.50"),
                currency="GBP",
                logged_at="2026-05-15",
            )
        )

    payload = next(c.args[1] for c in bus.call_args_list if c.args[0] == "equipment.parts_logged")
    assert payload["project_id"] == str(pid)
    assert payload["line_total"] == "37.5000"
    assert payload["currency"] == "GBP"


# ── per-unit + fleet dashboards ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_equipment_dashboard_aggregates_unit_kpis() -> None:
    svc = _make_service()
    eid = uuid.uuid4()
    equipment = _make_equipment(id=eid, status="active")
    svc.equipment_repo.get_by_id = AsyncMock(return_value=equipment)
    svc.fuel_repo.cost_in_range = AsyncMock(return_value=Decimal("420.00"))
    svc.workorder_repo.count_open_for_equipment = AsyncMock(return_value=2)
    insp = SimpleNamespace(equipment_id=eid, inspection_type="annual")
    svc.inspection_repo.expiring_within = AsyncMock(return_value=[insp])
    svc.inspection_repo.list_for_equipment = AsyncMock(return_value=[])

    with patch(
        "app.modules.equipment.service.utilization_for_equipment",
        new=AsyncMock(return_value=63.5),
    ):
        dash = await svc.equipment_dashboard(eid)

    assert dash.code == equipment.code
    assert dash.fuel_cost_mtd == Decimal("420.00")
    assert dash.open_work_orders == 2
    assert dash.expiring_inspections == 1
    assert dash.utilization_pct == 63.5
    assert dash.blocked is False


@pytest.mark.asyncio
async def test_fleet_dashboard_counts_by_status_and_type() -> None:
    svc = _make_service()
    e1 = _make_equipment(id=uuid.uuid4(), status="active", type_code="excavator")
    e2 = _make_equipment(id=uuid.uuid4(), status="under_maintenance", type_code="excavator")
    e3 = _make_equipment(id=uuid.uuid4(), status="active", type_code="crane")
    svc.equipment_repo.list_ = AsyncMock(return_value=([e1, e2, e3], 3))
    svc.fuel_repo.cost_in_range = AsyncMock(return_value=Decimal("0"))
    svc.workorder_repo.count_open_fleet = AsyncMock(return_value=4)
    svc.inspection_repo.expiring_within = AsyncMock(return_value=[])
    svc.equipment_repo.list_blocked = AsyncMock(return_value=[e2])
    svc.rental_repo.count_active = AsyncMock(return_value=1)

    with patch(
        "app.modules.equipment.service.fleet_utilization_avg",
        new=AsyncMock(return_value=42.0),
    ):
        fleet = await svc.fleet_dashboard()

    assert fleet.total_units == 3
    assert fleet.counts_by_status == {"active": 2, "under_maintenance": 1}
    assert fleet.counts_by_type == {"excavator": 2, "crane": 1}
    assert fleet.open_work_orders == 4
    assert fleet.blocked_units == 1
    assert fleet.active_rentals == 1
    assert fleet.utilization_pct == 42.0


# ── update_equipment no-op + field patch ─────────────────────────────────


@pytest.mark.asyncio
async def test_update_equipment_noop_returns_unchanged() -> None:
    from app.modules.equipment.schemas import EquipmentUpdate

    svc = _make_service()
    e = _make_equipment()
    svc.equipment_repo.get_by_id = AsyncMock(return_value=e)
    svc.equipment_repo.update_fields = AsyncMock()

    result = await svc.update_equipment(e.id, EquipmentUpdate())
    assert result is e
    svc.equipment_repo.update_fields.assert_not_called()


@pytest.mark.asyncio
async def test_update_equipment_applies_only_set_fields() -> None:
    from app.modules.equipment.schemas import EquipmentUpdate

    svc = _make_service()
    e = _make_equipment()
    svc.equipment_repo.get_by_id = AsyncMock(return_value=e)
    captured: dict[str, Any] = {}

    async def _cap(_id: Any, **fields: Any) -> None:
        captured.update(fields)

    svc.equipment_repo.update_fields = AsyncMock(side_effect=_cap)

    await svc.update_equipment(e.id, EquipmentUpdate(name="Renamed"))
    assert captured == {"name": "Renamed"}
