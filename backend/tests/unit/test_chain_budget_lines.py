"""Unit tests for the BOQ -> budget -> progress -> schedule chain fixes.

Covers the three audit blockers:

* Blocker 1 - ``CostModelService.generate_budget_from_boq`` creates one
  costmodel BudgetLine per BOQ position (idempotent: positions already
  wired are skipped) with the project currency, so the 5D Cost Spine
  gets its EVM baseline when the BOQ router builds a budget.
* Blocker 2 - ``CostModelService.apply_progress_earned_value`` persists
  EVM earned value (position total x latest percent / 100) on the
  matching budget line; latest reading wins (overwrite, never
  accumulate); skips silently when no budget line exists. The progress
  service wires it synchronously after every recorded entry.
* Blocker 3 - ``generate_from_boq`` duration calculation falls back to
  unit-based production rates so activities with nonzero quantities
  never get a zero duration, flagged ``duration_source =
  "estimated_fallback"``.

Repositories and sessions are faked so no database is required.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.modules.costmodel.service import CostModelService
from app.modules.schedule.service import (
    _calc_duration_from_resources,
    estimate_fallback_duration_days,
    fallback_labor_hours,
)

_PROJECT_ID = uuid.uuid4()
_BOQ_ID = uuid.uuid4()


class _FakeSession:
    """Bare-minimum async session stand-in (repos are replaced anyway)."""

    async def flush(self) -> None:
        return None

    async def refresh(self, obj: object) -> None:
        # record_entry refreshes the entry after the earned-value commit
        return None


class _FakeBudgetRepo:
    """In-memory BudgetLineRepository double."""

    def __init__(self) -> None:
        self.lines: list[object] = []
        self.existing: set[uuid.UUID] = set()
        self.line_by_position: dict[uuid.UUID, object] = {}
        self.update_calls: list[tuple[uuid.UUID, dict]] = []

    async def existing_position_ids(self, project_id: uuid.UUID) -> set[uuid.UUID]:
        return set(self.existing)

    async def bulk_create(self, lines: list[object]) -> list[object]:
        self.lines.extend(lines)
        for line in lines:
            if getattr(line, "boq_position_id", None) is not None:
                self.existing.add(line.boq_position_id)
        return lines

    async def get_by_position(self, project_id: uuid.UUID, boq_position_id: uuid.UUID):
        return self.line_by_position.get(boq_position_id)

    async def get_by_id(self, line_id: uuid.UUID):
        for line in self.line_by_position.values():
            if line.id == line_id:
                return line
        return None

    async def update_fields(self, line_id: uuid.UUID, **fields: object) -> None:
        self.update_calls.append((line_id, fields))
        for line in self.line_by_position.values():
            if line.id == line_id:
                for key, value in fields.items():
                    setattr(line, key, value)


def _position(
    total: str,
    ordinal: str = "01.001",
    description: str = "Concrete works",
    metadata: dict | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        total=total,
        ordinal=ordinal,
        description=description,
        metadata_=metadata or {},
    )


def _make_service(
    monkeypatch: pytest.MonkeyPatch,
    *,
    positions: list[SimpleNamespace] | None = None,
    currency: str = "EUR",
) -> tuple[CostModelService, _FakeBudgetRepo]:
    """Build a CostModelService with faked repos and lazy imports."""
    import app.modules.boq.repository as boq_repo_mod

    service = CostModelService(_FakeSession())
    fake_repo = _FakeBudgetRepo()
    service.budget_repo = fake_repo

    position_index = {p.id: p for p in (positions or [])}

    class _FakePositionRepo:
        def __init__(self, session: object) -> None:
            pass

        async def list_for_boq(self, boq_id: uuid.UUID, limit: int = 10000):
            return list(positions or []), len(positions or [])

        async def get_by_id(self, position_id: uuid.UUID):
            return position_index.get(position_id)

    monkeypatch.setattr(boq_repo_mod, "PositionRepository", _FakePositionRepo)

    async def _fake_currency(project_id: uuid.UUID) -> str:
        return currency

    monkeypatch.setattr(service, "_project_currency", _fake_currency)
    return service, fake_repo


# ── Blocker 1: budget-line creation from BOQ ──────────────────────────────


@pytest.mark.asyncio
async def test_generate_budget_creates_one_line_per_position(monkeypatch: pytest.MonkeyPatch) -> None:
    p1 = _position("1000.50")
    p2 = _position("250", ordinal="01.002", description="Rebar")
    service, repo = _make_service(monkeypatch, positions=[p1, p2])

    created = await service.generate_budget_from_boq(_PROJECT_ID, _BOQ_ID)

    assert len(created) == 2
    by_position = {line.boq_position_id: line for line in created}
    assert set(by_position) == {p1.id, p2.id}
    line1 = by_position[p1.id]
    assert Decimal(line1.planned_amount) == Decimal("1000.50")
    assert Decimal(line1.forecast_amount) == Decimal("1000.50")
    assert line1.actual_amount == "0"
    assert line1.currency == "EUR"
    assert line1.project_id == _PROJECT_ID


@pytest.mark.asyncio
async def test_generate_budget_is_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    p1 = _position("1000")
    p2 = _position("500", ordinal="01.002")
    service, repo = _make_service(monkeypatch, positions=[p1, p2])

    first = await service.generate_budget_from_boq(_PROJECT_ID, _BOQ_ID)
    assert len(first) == 2

    # Re-run: every position is already wired, nothing new is created.
    second = await service.generate_budget_from_boq(_PROJECT_ID, _BOQ_ID)
    assert second == []
    assert len(repo.lines) == 2


@pytest.mark.asyncio
async def test_generate_budget_skips_only_wired_positions(monkeypatch: pytest.MonkeyPatch) -> None:
    p1 = _position("1000")
    p2 = _position("500", ordinal="01.002")
    service, repo = _make_service(monkeypatch, positions=[p1, p2])
    repo.existing = {p1.id}

    created = await service.generate_budget_from_boq(_PROJECT_ID, _BOQ_ID)

    assert len(created) == 1
    assert created[0].boq_position_id == p2.id


@pytest.mark.asyncio
async def test_generate_budget_stamps_position_native_currency(monkeypatch: pytest.MonkeyPatch) -> None:
    """A position imported with a foreign currency marker keeps that stamp.

    planned/forecast amounts are raw position totals in the position's
    NATIVE currency, so stamping the project base currency would mislabel
    the money (audit M4). Positions without a marker (or matching the
    project currency) keep the project currency.
    """
    p_foreign = _position("1000", metadata={"currency": "usd"})
    p_same = _position("500", ordinal="01.002", metadata={"currency": "EUR"})
    p_plain = _position("250", ordinal="01.003")
    service, repo = _make_service(monkeypatch, positions=[p_foreign, p_same, p_plain], currency="EUR")

    created = await service.generate_budget_from_boq(_PROJECT_ID, _BOQ_ID)

    by_position = {line.boq_position_id: line for line in created}
    assert by_position[p_foreign.id].currency == "USD"
    assert by_position[p_same.id].currency == "EUR"
    assert by_position[p_plain.id].currency == "EUR"


# ── Blocker 2: progress -> earned value ───────────────────────────────────


def _budget_line() -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4(), earned_amount=None)


@pytest.mark.asyncio
async def test_progress_updates_earned_value(monkeypatch: pytest.MonkeyPatch) -> None:
    position = _position("2000")
    service, repo = _make_service(monkeypatch, positions=[position])
    line = _budget_line()
    repo.line_by_position[position.id] = line

    updated = await service.apply_progress_earned_value(_PROJECT_ID, position.id, Decimal("50"))

    assert updated is line
    assert line.earned_amount == Decimal("1000.00")


@pytest.mark.asyncio
async def test_earned_value_latest_wins_not_accumulated(monkeypatch: pytest.MonkeyPatch) -> None:
    position = _position("2000")
    service, repo = _make_service(monkeypatch, positions=[position])
    line = _budget_line()
    repo.line_by_position[position.id] = line

    await service.apply_progress_earned_value(_PROJECT_ID, position.id, Decimal("50"))
    await service.apply_progress_earned_value(_PROJECT_ID, position.id, Decimal("80"))

    # Overwrite semantics: 80% of 2000, not 50% + 80%.
    assert line.earned_amount == Decimal("1600.00")

    # Re-recording a lower reading also overwrites (corrections allowed).
    await service.apply_progress_earned_value(_PROJECT_ID, position.id, Decimal("30"))
    assert line.earned_amount == Decimal("600.00")


@pytest.mark.asyncio
async def test_earned_value_skips_without_budget_line(monkeypatch: pytest.MonkeyPatch) -> None:
    position = _position("2000")
    service, repo = _make_service(monkeypatch, positions=[position])

    result = await service.apply_progress_earned_value(_PROJECT_ID, position.id, Decimal("50"))

    assert result is None
    assert repo.update_calls == []


@pytest.mark.asyncio
async def test_earned_value_skips_when_position_gone(monkeypatch: pytest.MonkeyPatch) -> None:
    service, repo = _make_service(monkeypatch, positions=[])
    orphan_position_id = uuid.uuid4()
    repo.line_by_position[orphan_position_id] = _budget_line()

    result = await service.apply_progress_earned_value(_PROJECT_ID, orphan_position_id, Decimal("50"))

    assert result is None
    assert repo.update_calls == []


@pytest.mark.asyncio
async def test_record_entry_triggers_earned_value_sync(monkeypatch: pytest.MonkeyPatch) -> None:
    """The progress service pushes the just-recorded percent to costmodel."""
    import app.modules.costmodel.service as costmodel_service_mod
    from app.modules.progress.schemas import ProgressEntryCreate
    from app.modules.progress.service import ProgressService

    calls: list[tuple[uuid.UUID, uuid.UUID, Decimal]] = []

    class _FakeCostModelService:
        def __init__(self, session: object) -> None:
            pass

        async def apply_progress_earned_value(
            self,
            project_id: uuid.UUID,
            boq_position_id: uuid.UUID,
            percent_complete: Decimal,
        ):
            calls.append((project_id, boq_position_id, percent_complete))
            return SimpleNamespace(id=uuid.uuid4())

    monkeypatch.setattr(costmodel_service_mod, "CostModelService", _FakeCostModelService)

    progress_service = ProgressService(_FakeSession())

    class _FakeProgressRepo:
        async def create_entry(self, entry: object) -> object:
            return entry

    progress_service.repo = _FakeProgressRepo()

    position_id = uuid.uuid4()
    data = ProgressEntryCreate(
        project_id=_PROJECT_ID,
        boq_position_id=position_id,
        period_label="2026-06",
        percent_complete=42.5,
    )
    await progress_service.record_entry(data, user_id="tester")

    assert calls == [(_PROJECT_ID, position_id, Decimal("42.5"))]


@pytest.mark.asyncio
async def test_record_entry_without_position_skips_sync(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.modules.costmodel.service as costmodel_service_mod
    from app.modules.progress.schemas import ProgressEntryCreate
    from app.modules.progress.service import ProgressService

    calls: list[object] = []

    class _FakeCostModelService:
        def __init__(self, session: object) -> None:
            calls.append(session)

    monkeypatch.setattr(costmodel_service_mod, "CostModelService", _FakeCostModelService)

    progress_service = ProgressService(_FakeSession())

    class _FakeProgressRepo:
        async def create_entry(self, entry: object) -> object:
            return entry

    progress_service.repo = _FakeProgressRepo()

    data = ProgressEntryCreate(
        project_id=_PROJECT_ID,
        period_label="2026-06",
        percent_complete=10.0,
    )
    await progress_service.record_entry(data, user_id="tester")

    assert calls == []


# ── Blocker 3: schedule fallback durations ────────────────────────────────


def test_fallback_labor_hours_known_units() -> None:
    assert fallback_labor_hours("m3", 10) == pytest.approx(40.0)
    assert fallback_labor_hours("m2", 100) == pytest.approx(80.0)
    assert fallback_labor_hours("m", 20) == pytest.approx(10.0)
    assert fallback_labor_hours("kg", 100) == pytest.approx(2.0)
    assert fallback_labor_hours("pcs", 5) == pytest.approx(5.0)
    assert fallback_labor_hours("Stk", 5) == pytest.approx(5.0)
    assert fallback_labor_hours("t", 2) == pytest.approx(16.0)
    # Lump sum: flat allowance, independent of quantity
    assert fallback_labor_hours("lsum", 1) == pytest.approx(8.0)
    assert fallback_labor_hours("lsum", 999) == pytest.approx(8.0)
    # Unknown unit: default rate of 1.0 h/unit
    assert fallback_labor_hours("widget", 7) == pytest.approx(7.0)


def test_fallback_unit_aliases_normalized() -> None:
    assert fallback_labor_hours("m³", 10) == fallback_labor_hours("m3", 10)
    assert fallback_labor_hours("M2", 10) == fallback_labor_hours("m2", 10)
    assert fallback_labor_hours("EA", 10) == fallback_labor_hours("pcs", 10)
    assert fallback_labor_hours("psch", 1) == fallback_labor_hours("lsum", 1)


def test_estimate_fallback_duration_days_minimum_one() -> None:
    # Tiny quantity still yields at least 1 day
    assert estimate_fallback_duration_days("kg", 1) == 1
    # m3 x 10 -> 40h -> 5 days at 8h/day
    assert estimate_fallback_duration_days("m3", 10) == 5
    # lsum -> 8h flat -> 1 day
    assert estimate_fallback_duration_days("lsum", 50) == 1
    # Regional calendar hours respected
    assert estimate_fallback_duration_days("m3", 10, hours_per_day=10.0) == 4


@pytest.mark.parametrize("unit", ["m3", "m2", "m", "kg", "pcs", "stk", "t", "lsum", "unknown"])
@pytest.mark.parametrize("quantity", [0.5, 1.0, 12.0, 500.0])
def test_no_zero_duration_for_nonzero_quantity(unit: str, quantity: float) -> None:
    """Any position with quantity > 0 and no labor metadata gets >= 1 day."""
    days, source = _calc_duration_from_resources(
        {},
        quantity,
        unit,
        total_cost=0.0,
        grand_total=100000.0,
        total_days=365,
        hours_per_day=8.0,
        work_days_per_week=5,
    )
    assert days >= 1
    assert source == "estimated_fallback"


def test_labor_metadata_remains_primary_path() -> None:
    days, source = _calc_duration_from_resources(
        {"labor_hours": 2.0, "workers_per_unit": 2},
        10.0,
        "m3",
        total_cost=5000.0,
        grand_total=100000.0,
        total_days=365,
        hours_per_day=8.0,
        work_days_per_week=5,
    )
    assert source == "labor_hours"
    assert days >= 1


def test_resource_sum_path_before_fallback() -> None:
    meta = {"resources": [{"type": "labor", "unit": "hrs", "quantity": 1.5}]}
    days, source = _calc_duration_from_resources(
        meta,
        10.0,
        "m3",
        total_cost=5000.0,
        grand_total=100000.0,
        total_days=365,
        hours_per_day=8.0,
        work_days_per_week=5,
    )
    assert source == "resource_sum"
    assert days >= 1


def test_lump_sum_with_cost_data_prefers_cost_proportional() -> None:
    """A big lump-sum subcontract must not collapse to the flat 8h day.

    Audit m10: for lump-sum units with qty > 0, the cost-proportional
    share wins whenever total cost data is available; the flat allowance
    is strictly the last resort.
    """
    days, source = _calc_duration_from_resources(
        {},
        1.0,
        "lsum",
        total_cost=50000.0,
        grand_total=100000.0,
        total_days=365,
        hours_per_day=8.0,
        work_days_per_week=5,
    )
    assert source == "cost_proportional"
    # Half the project cost -> half the project duration, not 1 day.
    assert days == round(0.5 * 365)


def test_lump_sum_without_cost_data_uses_flat_allowance() -> None:
    days, source = _calc_duration_from_resources(
        {},
        1.0,
        "lsum",
        total_cost=0.0,
        grand_total=100000.0,
        total_days=365,
        hours_per_day=8.0,
        work_days_per_week=5,
    )
    assert source == "estimated_fallback"
    assert days == 1  # 8h flat -> 1 day


def test_non_lump_sum_units_keep_production_rate_path() -> None:
    """Cost data present must NOT divert measured units to proportional."""
    days, source = _calc_duration_from_resources(
        {},
        10.0,
        "m3",
        total_cost=50000.0,
        grand_total=100000.0,
        total_days=365,
        hours_per_day=8.0,
        work_days_per_week=5,
    )
    assert source == "estimated_fallback"
    assert days == 5  # 10 m3 x 4 h -> 40h -> 5 days


def test_cost_proportional_for_zero_quantity() -> None:
    days, source = _calc_duration_from_resources(
        {},
        0.0,
        "lsum",
        total_cost=10000.0,
        grand_total=100000.0,
        total_days=365,
        hours_per_day=8.0,
        work_days_per_week=5,
    )
    assert source == "cost_proportional"
    assert days >= 1


def test_default_minimum_when_nothing_known() -> None:
    days, source = _calc_duration_from_resources(
        {},
        0.0,
        "",
        total_cost=0.0,
        grand_total=0.0,
        total_days=365,
        hours_per_day=8.0,
        work_days_per_week=5,
    )
    assert days == 3
    assert source == "default_minimum"


def test_non_numeric_labor_metadata_falls_back_safely() -> None:
    """String / junk labor metadata must not crash and must yield >= 1 day."""
    days, source = _calc_duration_from_resources(
        {"labor_hours": "n/a", "workers_per_unit": None},
        25.0,
        "m2",
        total_cost=1000.0,
        grand_total=100000.0,
        total_days=365,
        hours_per_day=8.0,
        work_days_per_week=5,
    )
    assert days >= 1
    assert source == "estimated_fallback"
