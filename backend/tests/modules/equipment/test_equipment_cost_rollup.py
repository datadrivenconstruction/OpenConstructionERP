"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Gap C tests: equipment cost rollup to ``BudgetLine.actual``.

Exercises :class:`EquipmentActualsService` (the Gap C shared cost-spine
interface for equipment) and its detached event subscribers. The service is
tested directly against a real PostgreSQL session wrapped in a per-test
transaction that is rolled back on teardown via the canonical
``transactional_session`` helper. The subscriber payload-parsing logic is tested
with a small monkeypatched stub so we never open a second session across
event-loop boundaries (which would raise "Future attached to a different loop").

Money is asserted with exact ``Decimal`` values - the equipment line is one of
the sums every downstream cost rollup reads, so a silent float drift here would
corrupt the 5D model.

Adapts the design's TEST MATRIX (42 cases) to ``transactional_session``:
unit cases 1-22 (service logic + FX + idempotency + billing helper) and
integration cases 23-40 (subscriber dispatch + payload shaping). The two
browser cases (41, 42) are out of scope for this backend suite.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.costmodel.models import BudgetLine
from app.modules.equipment import service as equipment_service
from app.modules.equipment.models import EquipmentRental
from app.modules.equipment.service import (
    EquipmentActualsService,
    _coerce_project_id,
    _on_fuel_logged,
    _on_parts_logged,
    _on_rental_returned,
    _to_decimal_nonneg,
    compute_rental_billing,
)
from tests._pg import transactional_session

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    """Isolated PostgreSQL session per test (rolled back on teardown)."""
    async with transactional_session() as sess:
        yield sess


# ── Seed helpers ────────────────────────────────────────────────────────────


async def _seed_project(
    session: AsyncSession,
    *,
    currency: str = "EUR",
    fx_rates: list | None = None,
) -> uuid.UUID:
    """Insert a user + project and return the project id."""
    from app.modules.projects.models import Project
    from app.modules.users.models import User

    owner = User(
        id=uuid.uuid4(),
        email=f"gapc-{uuid.uuid4().hex[:10]}@equipment.io",
        hashed_password="x",
        full_name="Gap C Owner",
        role="admin",
    )
    session.add(owner)
    await session.flush()

    project = Project(
        id=uuid.uuid4(),
        name="Gap C project",
        owner_id=owner.id,
        currency=currency,
        fx_rates=fx_rates or [],
    )
    session.add(project)
    await session.flush()
    return project.id


async def _equipment_lines(session: AsyncSession, project_id: uuid.UUID) -> list[BudgetLine]:
    """Return all budget lines for a project ordered by creation."""
    rows = (
        (
            await session.execute(
                select(BudgetLine).where(BudgetLine.project_id == project_id).order_by(BudgetLine.created_at)
            )
        )
        .scalars()
        .all()
    )
    return list(rows)


def _make_rental(
    *,
    project_id: uuid.UUID,
    rate_per_day: str = "0",
    rate_per_hour: str = "0",
    start_date: str = "2026-06-01",
    end_date: str | None = None,
    currency: str = "EUR",
) -> EquipmentRental:
    """Build an unpersisted rental for the pure billing helper tests."""
    return EquipmentRental(
        id=uuid.uuid4(),
        equipment_id=uuid.uuid4(),
        project_id=project_id,
        start_date=start_date,
        end_date=end_date,
        internal_rate_per_day=Decimal(rate_per_day),
        internal_rate_per_hour=Decimal(rate_per_hour),
        currency=currency,
        status="active",
    )


# ── Pure numeric guard (case 19, 21) ─────────────────────────────────────────


def test_to_decimal_nonneg_quantize_and_guards() -> None:
    assert _to_decimal_nonneg("12.34") == Decimal("12.34")
    assert _to_decimal_nonneg(None) == Decimal("0")
    assert _to_decimal_nonneg("not-a-number") == Decimal("0")
    assert _to_decimal_nonneg("-5") == Decimal("0")  # negative cost ignored
    assert _to_decimal_nonneg("NaN") == Decimal("0")


def test_coerce_project_id() -> None:
    pid = uuid.uuid4()
    assert _coerce_project_id(str(pid)) == pid
    assert _coerce_project_id(None) is None
    assert _coerce_project_id("") is None
    assert _coerce_project_id("garbage") is None


# ── compute_rental_billing helper (cases 8, 9, 10, 35, 36) ────────────────────


def test_rental_billing_daily_rate() -> None:
    # 2026-06-01 .. 2026-06-10 inclusive = 10 days x 500 = 5000.
    rental = _make_rental(project_id=uuid.uuid4(), rate_per_day="500")
    assert compute_rental_billing(rental, "2026-06-01", "2026-06-10") == Decimal("5000")


def test_rental_billing_fractional_days_inclusive() -> None:
    # 2026-06-01 .. 2026-06-05 inclusive = 5 days.
    rental = _make_rental(project_id=uuid.uuid4(), rate_per_day="100")
    assert compute_rental_billing(rental, "2026-06-01", "2026-06-05") == Decimal("500")


def test_rental_billing_hourly_priority_over_daily() -> None:
    # Hourly rate set AND hours supplied -> hourly wins over daily window.
    rental = _make_rental(project_id=uuid.uuid4(), rate_per_day="500", rate_per_hour="50")
    assert compute_rental_billing(rental, "2026-06-01", "2026-06-10", hours_logged=8) == Decimal("400")


def test_rental_billing_falls_back_to_daily_without_hours() -> None:
    rental = _make_rental(project_id=uuid.uuid4(), rate_per_day="500", rate_per_hour="50")
    # No hours_logged -> day-rate billing.
    assert compute_rental_billing(rental, "2026-06-01", "2026-06-02") == Decimal("1000")


# ── Service: fuel cost posting (cases 1, 2, 3, 13, 14, 15, 16) ────────────────


async def test_post_fuel_cost_new_line(session: AsyncSession) -> None:
    project_id = await _seed_project(session)
    svc = EquipmentActualsService(session)

    applied = await svc.post_actual_to_budget_line(
        project_id=project_id,
        cost_category="equipment:fuel",
        amount_native=Decimal("120.00"),
        currency="EUR",
        source_kind="fuel_log",
        source_ref="fuel-1",
    )
    assert applied == Decimal("120.00")

    lines = await _equipment_lines(session, project_id)
    assert len(lines) == 1
    line = lines[0]
    assert line.category == "equipment"
    assert Decimal(line.actual_amount) == Decimal("120.00")
    assert line.metadata_["kind"] == "equipment_actuals_auto"
    assert line.metadata_["applied_events"] == ["fuel_log:fuel-1"]


async def test_post_fuel_cost_existing_line(session: AsyncSession) -> None:
    project_id = await _seed_project(session)
    svc = EquipmentActualsService(session)

    await svc.post_actual_to_budget_line(
        project_id=project_id,
        cost_category="equipment:fuel",
        amount_native=Decimal("100.00"),
        currency="EUR",
        source_kind="fuel_log",
        source_ref="fuel-1",
    )
    await svc.post_actual_to_budget_line(
        project_id=project_id,
        cost_category="equipment:fuel",
        amount_native=Decimal("50.00"),
        currency="EUR",
        source_kind="fuel_log",
        source_ref="fuel-2",
    )
    lines = await _equipment_lines(session, project_id)
    assert len(lines) == 1  # both land on the same auto line
    assert Decimal(lines[0].actual_amount) == Decimal("150.00")


async def test_post_fuel_cost_idempotent(session: AsyncSession) -> None:
    project_id = await _seed_project(session)
    svc = EquipmentActualsService(session)

    first = await svc.post_actual_to_budget_line(
        project_id=project_id,
        cost_category="equipment:fuel",
        amount_native=Decimal("80.00"),
        currency="EUR",
        source_kind="fuel_log",
        source_ref="dup",
    )
    second = await svc.post_actual_to_budget_line(
        project_id=project_id,
        cost_category="equipment:fuel",
        amount_native=Decimal("80.00"),
        currency="EUR",
        source_kind="fuel_log",
        source_ref="dup",  # same key → no-op
    )
    assert first == Decimal("80.00")
    assert second == Decimal("0")
    lines = await _equipment_lines(session, project_id)
    assert Decimal(lines[0].actual_amount) == Decimal("80.00")  # not 160
    assert lines[0].metadata_["applied_events"] == ["fuel_log:dup"]


async def test_equipment_line_created_once_per_project(session: AsyncSession) -> None:
    project_id = await _seed_project(session)
    svc = EquipmentActualsService(session)

    line_a = await svc._get_or_create_equipment_line(project_id)
    line_b = await svc._get_or_create_equipment_line(project_id)
    assert line_a.id == line_b.id
    lines = await _equipment_lines(session, project_id)
    assert len(lines) == 1


async def test_applied_events_key_format(session: AsyncSession) -> None:
    project_id = await _seed_project(session)
    svc = EquipmentActualsService(session)
    await svc.post_actual_to_budget_line(
        project_id=project_id,
        cost_category="equipment:parts",
        amount_native=Decimal("10.00"),
        currency="EUR",
        source_kind="parts_log",
        source_ref="abc",
    )
    lines = await _equipment_lines(session, project_id)
    assert lines[0].metadata_["applied_events"] == ["parts_log:abc"]


async def test_different_source_kind_same_id_posts_once_each(session: AsyncSession) -> None:
    project_id = await _seed_project(session)
    svc = EquipmentActualsService(session)
    shared_id = "X"
    # fuel_log:X and work_order:X are different keys → both apply.
    a = await svc.post_actual_to_budget_line(
        project_id=project_id,
        cost_category="equipment:fuel",
        amount_native=Decimal("30.00"),
        currency="EUR",
        source_kind="fuel_log",
        source_ref=shared_id,
    )
    b = await svc.post_actual_to_budget_line(
        project_id=project_id,
        cost_category="equipment:work_order",
        amount_native=Decimal("70.00"),
        currency="EUR",
        source_kind="work_order",
        source_ref=shared_id,
    )
    assert a == Decimal("30.00")
    assert b == Decimal("70.00")
    lines = await _equipment_lines(session, project_id)
    assert Decimal(lines[0].actual_amount) == Decimal("100.00")
    assert set(lines[0].metadata_["applied_events"]) == {"fuel_log:X", "work_order:X"}


# ── Service: parts cost posting (cases 6, 7) ──────────────────────────────────


async def test_post_parts_cost_cumulative(session: AsyncSession) -> None:
    project_id = await _seed_project(session)
    svc = EquipmentActualsService(session)
    for ref, amt in (("p1", "10.00"), ("p2", "20.00"), ("p3", "30.50")):
        await svc.post_actual_to_budget_line(
            project_id=project_id,
            cost_category="equipment:parts",
            amount_native=Decimal(amt),
            currency="EUR",
            source_kind="parts_log",
            source_ref=ref,
        )
    lines = await _equipment_lines(session, project_id)
    assert Decimal(lines[0].actual_amount) == Decimal("60.50")


async def test_post_zero_cost_skipped(session: AsyncSession) -> None:
    project_id = await _seed_project(session)
    svc = EquipmentActualsService(session)
    applied = await svc.post_actual_to_budget_line(
        project_id=project_id,
        cost_category="equipment:parts",
        amount_native=Decimal("0"),
        currency="EUR",
        source_kind="parts_log",
        source_ref="zero",
    )
    assert applied == Decimal("0")
    # No line is created for a zero posting.
    assert await _equipment_lines(session, project_id) == []


async def test_post_negative_cost_skipped(session: AsyncSession) -> None:
    project_id = await _seed_project(session)
    svc = EquipmentActualsService(session)
    applied = await svc.post_actual_to_budget_line(
        project_id=project_id,
        cost_category="equipment:parts",
        amount_native=Decimal("-50"),
        currency="EUR",
        source_kind="parts_log",
        source_ref="neg",
    )
    assert applied == Decimal("0")
    assert await _equipment_lines(session, project_id) == []


# ── Service: work-order cost posting (cases 11, 12) ───────────────────────────


async def test_post_work_order_cost(session: AsyncSession) -> None:
    project_id = await _seed_project(session)
    svc = EquipmentActualsService(session)
    applied = await svc.post_actual_to_budget_line(
        project_id=project_id,
        cost_category="equipment:work_order",
        amount_native=Decimal("450.00"),
        currency="EUR",
        source_kind="work_order",
        source_ref="wo-1",
    )
    assert applied == Decimal("450.00")
    lines = await _equipment_lines(session, project_id)
    assert Decimal(lines[0].actual_amount) == Decimal("450.00")


# ── Service: rental billing posting (case 8) ──────────────────────────────────


async def test_post_rental_cost_daily_rate(session: AsyncSession) -> None:
    project_id = await _seed_project(session)
    svc = EquipmentActualsService(session)
    # 10 days x 500/day = 5000 posted (caller computes billing; service posts).
    applied = await svc.post_actual_to_budget_line(
        project_id=project_id,
        cost_category="equipment:rental",
        amount_native=Decimal("5000.00"),
        currency="EUR",
        source_kind="rental",
        source_ref="rental-1",
    )
    assert applied == Decimal("5000.00")
    lines = await _equipment_lines(session, project_id)
    assert Decimal(lines[0].actual_amount) == Decimal("5000.00")


# ── Service: FX (cases 4, 5, 20, 21, 22) ──────────────────────────────────────


async def test_post_fuel_multicurrency_conversion(session: AsyncSession) -> None:
    # Base USD, fuel cost in EUR with a configured rate 1.10 -> 100 EUR = 110 USD.
    project_id = await _seed_project(
        session,
        currency="USD",
        fx_rates=[{"code": "EUR", "rate": "1.10"}],
    )
    svc = EquipmentActualsService(session)
    applied = await svc.post_actual_to_budget_line(
        project_id=project_id,
        cost_category="equipment:fuel",
        amount_native=Decimal("100.00"),
        currency="EUR",
        source_kind="fuel_log",
        source_ref="fx-1",
    )
    assert applied == Decimal("110.00")
    lines = await _equipment_lines(session, project_id)
    assert Decimal(lines[0].actual_amount) == Decimal("110.00")
    # The auto line inherits the project base currency.
    assert lines[0].currency == "USD"


async def test_fx_rate_missing_cost_kept_in_native_currency(session: AsyncSession) -> None:
    # Base USD but no rate configured for GBP -> kept as-is (never zeroed).
    project_id = await _seed_project(session, currency="USD", fx_rates=[])
    svc = EquipmentActualsService(session)
    applied = await svc.post_actual_to_budget_line(
        project_id=project_id,
        cost_category="equipment:fuel",
        amount_native=Decimal("200.00"),
        currency="GBP",
        source_kind="fuel_log",
        source_ref="gbp-1",
    )
    assert applied == Decimal("200.00")  # kept, not zeroed


async def test_fx_rate_zero_or_negative_treated_as_missing(session: AsyncSession) -> None:
    project_id = await _seed_project(
        session,
        currency="USD",
        fx_rates=[{"code": "EUR", "rate": "0"}],
    )
    svc = EquipmentActualsService(session)
    applied = await svc.post_actual_to_budget_line(
        project_id=project_id,
        cost_category="equipment:fuel",
        amount_native=Decimal("90.00"),
        currency="EUR",
        source_kind="fuel_log",
        source_ref="bad-rate",
    )
    # Invalid rate → kept in native units rather than multiplied by 0.
    assert applied == Decimal("90.00")


async def test_mixed_currency_costs_normalized_to_base(session: AsyncSession) -> None:
    project_id = await _seed_project(
        session,
        currency="USD",
        fx_rates=[{"code": "EUR", "rate": "1.10"}, {"code": "JPY", "rate": "0.007"}],
    )
    svc = EquipmentActualsService(session)
    await svc.post_actual_to_budget_line(
        project_id=project_id,
        cost_category="equipment:fuel",
        amount_native=Decimal("100.00"),
        currency="EUR",
        source_kind="fuel_log",
        source_ref="e1",
    )  # 110 USD
    await svc.post_actual_to_budget_line(
        project_id=project_id,
        cost_category="equipment:fuel",
        amount_native=Decimal("10000"),
        currency="JPY",
        source_kind="fuel_log",
        source_ref="j1",
    )  # 70 USD
    await svc.post_actual_to_budget_line(
        project_id=project_id,
        cost_category="equipment:fuel",
        amount_native=Decimal("20.00"),
        currency="USD",
        source_kind="fuel_log",
        source_ref="u1",
    )  # 20 USD
    lines = await _equipment_lines(session, project_id)
    assert Decimal(lines[0].actual_amount) == Decimal("200.00")  # 110 + 70 + 20


async def test_decimal_precision_quantized_to_cents(session: AsyncSession) -> None:
    project_id = await _seed_project(
        session,
        currency="USD",
        fx_rates=[{"code": "EUR", "rate": "1.111"}],
    )
    svc = EquipmentActualsService(session)
    applied = await svc.post_actual_to_budget_line(
        project_id=project_id,
        cost_category="equipment:fuel",
        amount_native=Decimal("10.00"),
        currency="EUR",
        source_kind="fuel_log",
        source_ref="q1",
    )
    # 10.00 * 1.111 = 11.11 (quantized to 2dp).
    assert applied == Decimal("11.11")


# ── Service: project currency edge cases (case 39) ────────────────────────────


async def test_project_without_currency_keeps_native(session: AsyncSession) -> None:
    # No base currency → _amount_in_base treats every value as base (kept as-is),
    # and the auto line's currency is the empty sentinel.
    project_id = await _seed_project(session, currency="")
    svc = EquipmentActualsService(session)
    applied = await svc.post_actual_to_budget_line(
        project_id=project_id,
        cost_category="equipment:fuel",
        amount_native=Decimal("55.00"),
        currency="EUR",
        source_kind="fuel_log",
        source_ref="nc-1",
    )
    assert applied == Decimal("55.00")
    lines = await _equipment_lines(session, project_id)
    assert lines[0].currency == ""


async def test_posting_trail_records_audit(session: AsyncSession) -> None:
    project_id = await _seed_project(session)
    svc = EquipmentActualsService(session)
    await svc.post_actual_to_budget_line(
        project_id=project_id,
        cost_category="equipment:fuel",
        amount_native=Decimal("42.00"),
        currency="EUR",
        source_kind="fuel_log",
        source_ref="audit-1",
        logged_at="2026-06-02",
    )
    lines = await _equipment_lines(session, project_id)
    postings = lines[0].metadata_["postings"]
    assert len(postings) == 1
    entry = postings[0]
    assert entry["source_kind"] == "fuel_log"
    assert entry["source_ref"] == "audit-1"
    assert entry["cost_category"] == "equipment:fuel"
    assert entry["amount"] == "42.00"
    assert entry["currency"] == "EUR"
    assert entry["logged_at"] == "2026-06-02"
    assert "posted_at" in entry


# ── Subscribers: payload parsing & dispatch (cases 23-30) ─────────────────────


def _capture_posts(monkeypatch) -> list[dict]:
    """Replace ``_post_equipment_cost`` with a synchronous capturing stub.

    Avoids opening a second session across event-loop boundaries; we assert the
    subscriber parsed the payload and forwarded the right posting arguments.
    """
    captured: list[dict] = []

    async def _fake_post(**kwargs) -> None:
        captured.append(kwargs)

    monkeypatch.setattr(equipment_service, "_post_equipment_cost", _fake_post)
    return captured


class _Evt:
    def __init__(self, data: dict) -> None:
        self.data = data


async def test_on_fuel_logged_posts_cost(monkeypatch) -> None:
    captured = _capture_posts(monkeypatch)
    pid = uuid.uuid4()
    await _on_fuel_logged(
        _Evt(
            {
                "project_id": str(pid),
                "fuel_log_id": "f-1",
                "cost": "120.00",
                "currency": "EUR",
                "logged_at": "2026-06-01",
            }
        )
    )
    assert len(captured) == 1
    call = captured[0]
    assert call["project_id"] == pid
    assert call["cost_category"] == "equipment:fuel"
    assert call["amount_native"] == Decimal("120.00")
    assert call["currency"] == "EUR"
    assert call["source_kind"] == "fuel_log"
    assert call["source_ref"] == "f-1"


async def test_on_fuel_logged_project_id_null_skipped(monkeypatch) -> None:
    captured = _capture_posts(monkeypatch)
    await _on_fuel_logged(_Evt({"project_id": None, "fuel_log_id": "f-1", "cost": "10"}))
    assert captured == []


async def test_on_fuel_logged_zero_cost_skipped(monkeypatch) -> None:
    captured = _capture_posts(monkeypatch)
    await _on_fuel_logged(_Evt({"project_id": str(uuid.uuid4()), "fuel_log_id": "f-1", "cost": "0"}))
    assert captured == []


async def test_on_fuel_logged_missing_id_skipped(monkeypatch) -> None:
    captured = _capture_posts(monkeypatch)
    await _on_fuel_logged(_Evt({"project_id": str(uuid.uuid4()), "cost": "10"}))
    assert captured == []


async def test_on_parts_logged_uses_line_total(monkeypatch) -> None:
    captured = _capture_posts(monkeypatch)
    pid = uuid.uuid4()
    await _on_parts_logged(
        _Evt(
            {
                "project_id": str(pid),
                "parts_log_id": "p-1",
                "quantity": "3",
                "unit_cost": "25.00",
                "line_total": "75.00",
                "currency": "EUR",
            }
        )
    )
    assert len(captured) == 1
    assert captured[0]["amount_native"] == Decimal("75.00")
    assert captured[0]["cost_category"] == "equipment:parts"
    assert captured[0]["source_kind"] == "parts_log"
    assert captured[0]["source_ref"] == "p-1"


async def test_on_parts_logged_falls_back_to_quantity_times_unit_cost(monkeypatch) -> None:
    captured = _capture_posts(monkeypatch)
    pid = uuid.uuid4()
    await _on_parts_logged(
        _Evt(
            {
                "project_id": str(pid),
                "parts_log_id": "p-2",
                "quantity": "4",
                "unit_cost": "12.50",
                # no line_total
                "currency": "EUR",
            }
        )
    )
    assert len(captured) == 1
    assert captured[0]["amount_native"] == Decimal("50.00")


async def test_on_rental_returned_posts_billing(monkeypatch) -> None:
    captured = _capture_posts(monkeypatch)
    pid = uuid.uuid4()
    await _on_rental_returned(
        _Evt(
            {
                "rental_id": "r-1",
                "project_id": str(pid),
                "billing_amount": "5000.00",
                "currency": "EUR",
                "end_date": "2026-06-10",
            }
        )
    )
    assert len(captured) == 1
    call = captured[0]
    assert call["amount_native"] == Decimal("5000.00")
    assert call["cost_category"] == "equipment:rental"
    assert call["source_kind"] == "rental"
    assert call["source_ref"] == "r-1"


async def test_on_rental_returned_zero_billing_skipped(monkeypatch) -> None:
    captured = _capture_posts(monkeypatch)
    await _on_rental_returned(
        _Evt({"rental_id": "r-2", "project_id": str(uuid.uuid4()), "billing_amount": "0", "currency": "EUR"})
    )
    assert captured == []


# ── return_rental integration: emits the rollup trigger (cases 29, 30, 34) ────


async def test_return_rental_emits_event_and_sets_calculated_at(session: AsyncSession, monkeypatch) -> None:
    """Returning a rental computes billing, stamps billing_calculated_at and
    emits ``equipment.rental_returned`` with the billing amount."""
    from app.modules.equipment.models import Equipment
    from app.modules.equipment.service import EquipmentService

    project_id = await _seed_project(session)

    # Seed an active equipment unit so the rental's FK resolves.
    equipment = Equipment(id=uuid.uuid4(), code=f"EQ-{uuid.uuid4().hex[:6]}", name="Excavator", status="active")
    session.add(equipment)
    await session.flush()

    rental = EquipmentRental(
        id=uuid.uuid4(),
        equipment_id=equipment.id,
        project_id=project_id,
        start_date="2026-06-01",
        end_date=None,
        internal_rate_per_day=Decimal("500"),
        internal_rate_per_hour=Decimal("0"),
        currency="EUR",
        status="active",
    )
    session.add(rental)
    await session.flush()

    captured: list[tuple[str, dict]] = []

    def _fake_detached(name: str, data: dict | None = None, source_module: str | None = None):
        captured.append((name, data or {}))

    monkeypatch.setattr(equipment_service.event_bus, "publish_detached", _fake_detached)

    svc = EquipmentService(session)
    returned = await svc.return_rental(rental.id, end_date="2026-06-10")

    assert returned.status == "returned"
    assert returned.end_date == "2026-06-10"
    assert returned.billing_calculated_at is not None

    assert len(captured) == 1
    name, data = captured[0]
    assert name == "equipment.rental_returned"
    assert data["rental_id"] == str(rental.id)
    assert data["project_id"] == str(project_id)
    assert data["billing_amount"] == "5000"  # 10 days x 500
    assert data["billing_type"] == "daily"
    assert data["currency"] == "EUR"


async def test_return_rental_zero_billing_no_event(session: AsyncSession, monkeypatch) -> None:
    """A rental with no rates produces 0 billing → no rollup event emitted."""
    from app.modules.equipment.models import Equipment
    from app.modules.equipment.service import EquipmentService

    project_id = await _seed_project(session)
    equipment = Equipment(id=uuid.uuid4(), code=f"EQ-{uuid.uuid4().hex[:6]}", name="Idle", status="active")
    session.add(equipment)
    await session.flush()

    rental = EquipmentRental(
        id=uuid.uuid4(),
        equipment_id=equipment.id,
        project_id=project_id,
        start_date="2026-06-01",
        end_date=None,
        internal_rate_per_day=Decimal("0"),
        internal_rate_per_hour=Decimal("0"),
        currency="EUR",
        status="active",
    )
    session.add(rental)
    await session.flush()

    captured: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        equipment_service.event_bus,
        "publish_detached",
        lambda name, data=None, source_module=None: captured.append((name, data or {})),
    )

    svc = EquipmentService(session)
    await svc.return_rental(rental.id, end_date="2026-06-10")
    assert captured == []
