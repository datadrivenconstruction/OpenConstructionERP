"""Demo seed data for the costmodel (5D / EVM) module.

Loaded on demand via ``await seed_costmodel(session, project_ids)``. For each
covered project it creates a small but realistic cost model that drives the 5D
and EVM views:

    - a Cost Breakdown Structure of control accounts (one root plus a few leaves)
    - cost lines hanging off the leaf control accounts
    - budget lines (planned, committed, actual, forecast) per cost category
    - a 12 month cash flow curve with cumulative S curve totals
    - 12 monthly EVM snapshots with realistic earned value progress so SPI / CPI
      and the forecast EAC come out sensible (work is a little behind schedule
      and slightly over budget)

All money and index fields in this module are stored as plain strings (the
column vocabulary stays uniform across the cost spine), so every numeric value
is computed with Decimal and then serialised to a string before assignment.

The seed is idempotent: it short circuits and returns an empty dict when a
snapshot already exists for the first project id.
"""

from __future__ import annotations

import logging
import uuid
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.costmodel.models import (
    BudgetLine,
    CashFlow,
    ControlAccount,
    CostLine,
    CostSnapshot,
)

logger = logging.getLogger(__name__)

FLAGSHIP_PROJECT_ID = uuid.UUID("f1a95000-0001-4a00-8b00-000000000001")

# Budget at Completion (BAC) used to scale the planned S curve. The earned value
# curve below lags the planned curve a touch (behind schedule) and the actual
# cost curve runs slightly ahead of earned value (over budget), which keeps the
# derived SPI / CPI indices believable for an EVM demo.
_BAC = Decimal("2000000")

# 12 monthly periods (YYYY-MM) covering the demo project timeline.
_PERIODS = [
    "2026-01",
    "2026-02",
    "2026-03",
    "2026-04",
    "2026-05",
    "2026-06",
    "2026-07",
    "2026-08",
    "2026-09",
    "2026-10",
    "2026-11",
    "2026-12",
]

# Cumulative planned percent complete (BCWS as a fraction of BAC) at each period.
# A typical front loaded then tapering construction S curve.
_PLANNED_PCT = [
    Decimal("0.03"),
    Decimal("0.08"),
    Decimal("0.16"),
    Decimal("0.27"),
    Decimal("0.40"),
    Decimal("0.54"),
    Decimal("0.67"),
    Decimal("0.78"),
    Decimal("0.87"),
    Decimal("0.93"),
    Decimal("0.97"),
    Decimal("1.00"),
]

# Snapshots are taken through period index 6 (2026-07): work is in progress, so
# only the first seven periods carry earned value and actual cost.
_PROGRESS_PERIODS = 7

# Control accounts: (code, name, classification standard, list of cost lines).
# Each cost line tuple is (code, description, unit, quantity, unit_rate).
_CONTROL_ACCOUNTS = [
    (
        "300",
        "Building construction",
        "din276",
        [
            ("300.10", "Reinforced concrete walls C30/37", "m3", "850", "320"),
            ("300.20", "Reinforced concrete slabs C30/37", "m3", "640", "295"),
            ("300.30", "Structural steel frame", "ton", "120", "2400"),
        ],
    ),
    (
        "400",
        "Building services (MEP)",
        "din276",
        [
            ("400.10", "HVAC ductwork and units", "lsum", "1", "180000"),
            ("400.20", "Electrical installation", "lsum", "1", "145000"),
            ("400.30", "Plumbing and drainage", "lsum", "1", "98000"),
        ],
    ),
    (
        "500",
        "Outdoor facilities",
        "din276",
        [
            ("500.10", "Site paving and kerbs", "m2", "2200", "85"),
            ("500.20", "Landscaping and planting", "lsum", "1", "60000"),
        ],
    ),
]

# Budget lines: (category, description, planned, committed, actual, forecast).
_BUDGET_LINES = [
    ("material", "Concrete, rebar and steel materials", "780000", "640000", "410000", "795000"),
    ("labor", "Site labor and supervision", "520000", "300000", "260000", "535000"),
    ("equipment", "Cranes, formwork and plant hire", "210000", "150000", "120000", "215000"),
    ("subcontractor", "MEP subcontract packages", "360000", "280000", "150000", "365000"),
    ("overhead", "Site overhead and general conditions", "90000", "90000", "55000", "92000"),
    ("contingency", "Risk contingency reserve", "40000", "0", "0", "30000"),
]

_CURRENCY = "EUR"


def _money(value: Decimal) -> str:
    """Serialise a Decimal as a 2 decimal place money string."""
    return str(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _ratio(value: Decimal) -> str:
    """Serialise a performance index Decimal as a 3 decimal place string."""
    return str(value.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP))


async def _seed_one_project(session: AsyncSession, project_id: uuid.UUID) -> dict[str, int]:
    """Seed a single project's cost model. Returns per entity counts."""
    counts = {
        "control_accounts": 0,
        "cost_lines": 0,
        "budget_lines": 0,
        "cash_flows": 0,
        "snapshots": 0,
    }

    # --- Cost Breakdown Structure: control accounts plus their cost lines ---
    # Keep created cost lines in a local list so we never touch a lazy
    # relationship (account.cost_lines) after a flush under async.
    created_cost_lines: list[CostLine] = []
    for sort_order, (acct_code, acct_name, standard, lines) in enumerate(_CONTROL_ACCOUNTS):
        account = ControlAccount(
            project_id=project_id,
            parent_id=None,
            code=acct_code,
            name=acct_name,
            classification_standard=standard,
            status="open",
            sort_order=sort_order,
            metadata_={"seed": True, "demo": True},
        )
        session.add(account)
        await session.flush()
        counts["control_accounts"] += 1

        for line_code, description, unit, qty_str, rate_str in lines:
            quantity = Decimal(qty_str)
            unit_rate = Decimal(rate_str)
            amount = quantity * unit_rate
            cost_line = CostLine(
                project_id=project_id,
                control_account_id=account.id,
                code=line_code,
                description=description,
                unit=unit,
                source="manual",
                boq_position_id=None,
                boq_id=None,
                estimate_quantity=str(quantity),
                estimate_unit_rate=str(unit_rate),
                estimate_amount=_money(amount),
                currency=_CURRENCY,
                status="active",
                metadata_={"seed": True, "demo": True},
            )
            session.add(cost_line)
            created_cost_lines.append(cost_line)
    await session.flush()
    counts["cost_lines"] += len(created_cost_lines)

    # --- Budget lines per cost category ---
    for category, description, planned, committed, actual, forecast in _BUDGET_LINES:
        budget_line = BudgetLine(
            project_id=project_id,
            boq_position_id=None,
            activity_id=None,
            cost_line_id=None,
            control_account_id=None,
            category=category,
            description=description,
            planned_amount=_money(Decimal(planned)),
            committed_amount=_money(Decimal(committed)),
            actual_amount=_money(Decimal(actual)),
            forecast_amount=_money(Decimal(forecast)),
            period_start="2026-01-01",
            period_end="2026-12-31",
            currency=_CURRENCY,
            overrun_alert_threshold_pct="10",
            overrun_alerted_at=None,
            metadata_={"seed": True, "demo": True},
        )
        session.add(budget_line)
        counts["budget_lines"] += 1
    await session.flush()

    # --- Monthly cash flow S curve ---
    cumulative_planned = Decimal("0")
    cumulative_actual = Decimal("0")
    for idx, period in enumerate(_PERIODS):
        planned_cum = (_BAC * _PLANNED_PCT[idx]).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        prev_planned_cum = (
            (_BAC * _PLANNED_PCT[idx - 1]).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            if idx > 0
            else Decimal("0")
        )
        planned_outflow = planned_cum - prev_planned_cum
        cumulative_planned = planned_cum

        if idx < _PROGRESS_PERIODS:
            # Actual outflow trails planned slightly (about 96% realised so far).
            actual_outflow = (planned_outflow * Decimal("0.96")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            cumulative_actual += actual_outflow
            actual_cum_str = _money(cumulative_actual)
        else:
            actual_outflow = Decimal("0")
            actual_cum_str = _money(cumulative_actual)

        cash_flow = CashFlow(
            project_id=project_id,
            period=period,
            category="total",
            planned_inflow="0.00",
            planned_outflow=_money(planned_outflow),
            actual_inflow="0.00",
            actual_outflow=_money(actual_outflow),
            cumulative_planned=_money(cumulative_planned),
            cumulative_actual=actual_cum_str,
            metadata_={"seed": True, "demo": True},
        )
        session.add(cash_flow)
        counts["cash_flows"] += 1
    await session.flush()

    # --- Monthly EVM snapshots ---
    # BCWP (earned value) lags BCWS (planned value) slightly so SPI < 1, and
    # ACWP (actual cost) runs a touch above BCWP so CPI < 1. The forecast EAC
    # uses the classic BAC / CPI formula.
    for idx, period in enumerate(_PERIODS):
        planned_cost = (_BAC * _PLANNED_PCT[idx]).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        if idx < _PROGRESS_PERIODS:
            earned_value = (planned_cost * Decimal("0.95")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            actual_cost = (earned_value * Decimal("1.04")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            spi = earned_value / planned_cost if planned_cost > 0 else Decimal("0")
            cpi = earned_value / actual_cost if actual_cost > 0 else Decimal("0")
            forecast_eac = (_BAC / cpi).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            spi_str = _ratio(spi)
            cpi_str = _ratio(cpi)
            notes = "Work in progress: slightly behind schedule, marginally over budget."
        else:
            earned_value = Decimal("0")
            actual_cost = Decimal("0")
            forecast_eac = _BAC
            spi_str = "0"
            cpi_str = "0"
            notes = "Future period: no earned value recorded yet."

        snapshot = CostSnapshot(
            project_id=project_id,
            period=period,
            planned_cost=_money(planned_cost),
            earned_value=_money(earned_value),
            actual_cost=_money(actual_cost),
            forecast_eac=_money(forecast_eac),
            spi=spi_str,
            cpi=cpi_str,
            notes=notes,
            metadata_={"seed": True, "demo": True, "bac": _money(_BAC)},
        )
        session.add(snapshot)
        counts["snapshots"] += 1
    await session.flush()

    return counts


async def seed_costmodel(
    session: AsyncSession,
    project_ids: list[uuid.UUID],
) -> dict[str, int]:
    """Seed demo cost model data (control accounts, budgets, cash flow, EVM).

    Seeds at most the first three project ids, always including the flagship
    project id when it is present. Idempotent: if a cost snapshot already exists
    for the first project id, the function returns an empty dict immediately.

    Args:
        session: Active async SQLAlchemy session.
        project_ids: Project ids to seed; the flagship project is always covered
            when present.

    Returns:
        A dict mapping entity name to the number of rows inserted.
    """
    if not project_ids:
        return {}

    # Idempotency guard: bail out if the first project already has a snapshot.
    existing = await session.execute(select(CostSnapshot.id).where(CostSnapshot.project_id == project_ids[0]).limit(1))
    if existing.scalar_one_or_none() is not None:
        return {}

    # Build the target set: first three project ids, always including the
    # flagship when present, while preserving order and dropping duplicates.
    targets: list[uuid.UUID] = list(project_ids[:3])
    if FLAGSHIP_PROJECT_ID in project_ids and FLAGSHIP_PROJECT_ID not in targets:
        targets.append(FLAGSHIP_PROJECT_ID)

    seen: set[uuid.UUID] = set()
    ordered_targets: list[uuid.UUID] = []
    for pid in targets:
        if pid not in seen:
            seen.add(pid)
            ordered_targets.append(pid)

    counts: dict[str, int] = {
        "control_accounts": 0,
        "cost_lines": 0,
        "budget_lines": 0,
        "cash_flows": 0,
        "snapshots": 0,
    }
    for pid in ordered_targets:
        project_counts = await _seed_one_project(session, pid)
        for key, value in project_counts.items():
            counts[key] += value

    await session.flush()
    logger.info("Costmodel seed inserted: %s", counts)
    return counts
