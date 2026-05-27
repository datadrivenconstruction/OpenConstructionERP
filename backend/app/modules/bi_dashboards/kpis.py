# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""‌⁠‍KPI formula registry — every system KPI as a registered Python function.

Each KPI:
    * Is registered with :func:`register_kpi(code)`
    * Returns a :class:`KPIComputation` (Decimal value + record count + breakdown)
    * Gracefully degrades to ``Decimal("0")`` with ``source_record_count=0``
      when its source module is missing or any query raises (``ImportError``
      / ``OperationalError``). The module is read-only across the platform
      and must never crash because an upstream module was uninstalled.

The registry is process-local. Custom KPIs registered by community
modules survive a hot reload of this file but not a worker restart —
modules should register inside their own ``on_startup`` hook.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from datetime import date as _date
from decimal import Decimal
from typing import Any, Awaitable, Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


@dataclass
class KPIComputation:
    """‌⁠‍The shape every KPI formula returns."""

    value: Decimal = Decimal("0")
    unit: str = "ratio"
    source_record_count: int = 0
    breakdown: dict[str, Any] = field(default_factory=dict)


KPIFormula = Callable[..., Awaitable[KPIComputation]]

# Global registry — populated by @register_kpi decorators below.
KPI_FORMULAS: dict[str, KPIFormula] = {}

# Metadata for system KPIs — drives the seed step that writes KPIDefinition
# rows. Order must match @register_kpi declarations or seeding is wrong.
SYSTEM_KPI_META: dict[str, dict[str, Any]] = {}


def register_kpi(
    code: str,
    *,
    name: str | None = None,
    unit: str = "ratio",
    category: str = "operational",
    aggregation: str = "last",
    source_modules: list[str] | None = None,
    target_default: Decimal | None = None,
    description: str = "",
) -> Callable[[KPIFormula], KPIFormula]:
    """‌⁠‍Decorator registering a KPI formula in :data:`KPI_FORMULAS`.

    Also stores metadata used by :func:`bootstrap_system_kpis` when
    seeding the :class:`KPIDefinition` table on startup.
    """

    def decorator(fn: KPIFormula) -> KPIFormula:
        KPI_FORMULAS[code] = fn
        SYSTEM_KPI_META[code] = {
            "code": code,
            "name": name or code.replace("_", " ").title(),
            "description": description or (fn.__doc__ or "").strip().split("\n")[0],
            "formula_ref": code,
            "source_modules": source_modules or [],
            "unit": unit,
            "target_default": target_default,
            "aggregation": aggregation,
            "category": category,
            "is_system": True,
        }
        return fn

    return decorator


# ── Helpers ────────────────────────────────────────────────────────────


async def _safe_count(session: AsyncSession, query: Any) -> int:
    """Run ``COUNT(*)`` over a select, returning 0 on any failure."""
    try:
        result = await session.execute(query)
        rows = list(result.scalars().all())
        return len(rows)
    except Exception:
        logger.debug("KPI safe_count: query failed", exc_info=True)
        return 0


def _to_decimal(value: Any) -> Decimal:
    """Coerce anything to Decimal, returning 0 on failure."""
    if value is None:
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except Exception:
        return Decimal("0")


def _safe_div(numerator: Decimal, denominator: Decimal) -> Decimal:
    if denominator == 0:
        return Decimal("0")
    return numerator / denominator


# ── Financial KPIs ─────────────────────────────────────────────────────


# ── EVM core helpers ───────────────────────────────────────────────────


@dataclass
class EVMSnapshot:
    """The five EVM primitives + counts for any project (or portfolio).

    All Decimal values default to 0 so consumer KPIs can derive without
    re-querying. Returned by :func:`_evm_snapshot`.
    """

    bac: Decimal = Decimal("0")  # Budget at completion
    pv: Decimal = Decimal("0")  # Planned value (BCWS)
    ev: Decimal = Decimal("0")  # Earned value (BCWP)
    ac: Decimal = Decimal("0")  # Actual cost (ACWP)
    record_count: int = 0
    breakdown: dict[str, Any] = field(default_factory=dict)


async def _evm_snapshot(
    session: AsyncSession,
    project_id: uuid.UUID | None,
) -> EVMSnapshot:
    """Build the five EVM primitives by probing tasks + finance modules.

    Strategy:
        * BAC: project.budget OR Σ Task.planned_value (whichever is larger)
        * PV:  Σ Task.planned_value
        * EV:  Σ Task.earned_value (calculated upstream as % complete × BAC)
        * AC:  Σ Expense.amount (finance.Expense) + Σ PurchaseOrder.total_amount
                (procurement.PurchaseOrder)
    """
    snap = EVMSnapshot()
    # Tasks → PV + EV + count
    try:
        from app.modules.tasks.models import Task  # type: ignore

        stmt = select(Task)
        if project_id is not None:
            stmt = stmt.where(Task.project_id == project_id)
        rows = (await session.execute(stmt)).scalars().all()
        for row in rows:
            pv = _to_decimal(getattr(row, "planned_value", 0))
            ev = _to_decimal(getattr(row, "earned_value", 0))
            snap.pv += pv
            snap.ev += ev
            snap.record_count += 1
    except ImportError:
        pass
    except Exception:
        logger.debug("evm: tasks probe failed", exc_info=True)

    # Project budget → BAC
    try:
        from app.modules.projects.models import Project  # type: ignore

        if project_id is not None:
            proj = await session.get(Project, project_id)
            if proj is not None:
                snap.bac = max(
                    _to_decimal(getattr(proj, "budget", None)),
                    _to_decimal(getattr(proj, "contract_value", None)),
                )
    except ImportError:
        pass
    except Exception:
        logger.debug("evm: project probe failed", exc_info=True)
    if snap.bac == 0:
        snap.bac = snap.pv  # Fall back to Σ planned_value

    # Finance.Expense → AC (subset)
    try:
        from app.modules.finance.models import Expense  # type: ignore

        stmt = select(Expense)
        if project_id is not None:
            stmt = stmt.where(Expense.project_id == project_id)
        rows = (await session.execute(stmt)).scalars().all()
        for row in rows:
            snap.ac += _to_decimal(getattr(row, "amount", 0))
            snap.record_count += 1
    except ImportError:
        pass
    except Exception:
        logger.debug("evm: finance probe failed", exc_info=True)

    snap.breakdown = {
        "bac": str(snap.bac),
        "pv": str(snap.pv),
        "ev": str(snap.ev),
        "ac": str(snap.ac),
    }
    return snap


@register_kpi(
    "cpi",
    name="Cost Performance Index",
    unit="ratio",
    category="financial",
    source_modules=["finance", "tasks", "projects"],
    target_default=Decimal("1.0"),
    description="EV / AC (PMBOK). > 1.0 = under budget; < 1.0 = over budget.",
)
async def cpi_kpi(
    session: AsyncSession,
    project_id: uuid.UUID | None = None,
    **_: Any,
) -> KPIComputation:
    """Cost Performance Index = EV / AC."""
    snap = await _evm_snapshot(session, project_id)
    value = _safe_div(snap.ev, snap.ac) if snap.ac > 0 else Decimal("0")
    return KPIComputation(
        value=value,
        unit="ratio",
        source_record_count=snap.record_count,
        breakdown=snap.breakdown,
    )


@register_kpi(
    "spi",
    name="Schedule Performance Index",
    unit="ratio",
    category="schedule",
    source_modules=["tasks"],
    target_default=Decimal("1.0"),
    description="EV / PV (PMBOK). > 1.0 = ahead of schedule.",
)
async def spi_kpi(
    session: AsyncSession,
    project_id: uuid.UUID | None = None,
    **_: Any,
) -> KPIComputation:
    """Schedule Performance Index = EV / PV."""
    snap = await _evm_snapshot(session, project_id)
    value = _safe_div(snap.ev, snap.pv) if snap.pv > 0 else Decimal("0")
    return KPIComputation(
        value=value,
        unit="ratio",
        source_record_count=snap.record_count,
        breakdown=snap.breakdown,
    )


# ── Additional EVM KPIs (per PMBOK 7) ──────────────────────────────────


@register_kpi(
    "cv",
    name="Cost Variance",
    unit="currency",
    category="financial",
    source_modules=["finance", "tasks", "projects"],
    target_default=Decimal("0"),
    description="EV - AC. Negative = over budget.",
)
async def cv_kpi(
    session: AsyncSession,
    project_id: uuid.UUID | None = None,
    **_: Any,
) -> KPIComputation:
    snap = await _evm_snapshot(session, project_id)
    return KPIComputation(
        value=snap.ev - snap.ac,
        unit="currency",
        source_record_count=snap.record_count,
        breakdown=snap.breakdown,
    )


@register_kpi(
    "sv",
    name="Schedule Variance",
    unit="currency",
    category="schedule",
    source_modules=["tasks", "projects"],
    target_default=Decimal("0"),
    description="EV - PV. Negative = behind schedule.",
)
async def sv_kpi(
    session: AsyncSession,
    project_id: uuid.UUID | None = None,
    **_: Any,
) -> KPIComputation:
    snap = await _evm_snapshot(session, project_id)
    return KPIComputation(
        value=snap.ev - snap.pv,
        unit="currency",
        source_record_count=snap.record_count,
        breakdown=snap.breakdown,
    )


@register_kpi(
    "eac",
    name="Estimate at Completion",
    unit="currency",
    category="financial",
    source_modules=["finance", "tasks", "projects"],
    description=("AC + (BAC - EV) / (CPI * SPI) — assumes both perf indices persist (common in construction)."),
)
async def eac_kpi(
    session: AsyncSession,
    project_id: uuid.UUID | None = None,
    **_: Any,
) -> KPIComputation:
    snap = await _evm_snapshot(session, project_id)
    if snap.ac == 0 or snap.ev == 0 or snap.pv == 0:
        return KPIComputation(
            value=snap.bac,
            unit="currency",
            source_record_count=snap.record_count,
            breakdown=snap.breakdown,
        )
    cpi = _safe_div(snap.ev, snap.ac)
    spi = _safe_div(snap.ev, snap.pv)
    denom = cpi * spi
    if denom == 0:
        eac = snap.ac
    else:
        eac = snap.ac + _safe_div(snap.bac - snap.ev, denom)
    return KPIComputation(
        value=eac,
        unit="currency",
        source_record_count=snap.record_count,
        breakdown={**snap.breakdown, "cpi": str(cpi), "spi": str(spi)},
    )


@register_kpi(
    "etc",
    name="Estimate to Complete",
    unit="currency",
    category="financial",
    source_modules=["finance", "tasks", "projects"],
    description="EAC - AC. Money still needed to finish.",
)
async def etc_kpi(
    session: AsyncSession,
    project_id: uuid.UUID | None = None,
    **_: Any,
) -> KPIComputation:
    eac_result = await eac_kpi(session, project_id=project_id)
    snap = await _evm_snapshot(session, project_id)
    return KPIComputation(
        value=eac_result.value - snap.ac,
        unit="currency",
        source_record_count=snap.record_count,
        breakdown={**snap.breakdown, "eac": str(eac_result.value)},
    )


@register_kpi(
    "vac",
    name="Variance at Completion",
    unit="currency",
    category="financial",
    source_modules=["finance", "tasks", "projects"],
    description="BAC - EAC. Negative = expected to finish over budget.",
)
async def vac_kpi(
    session: AsyncSession,
    project_id: uuid.UUID | None = None,
    **_: Any,
) -> KPIComputation:
    eac_result = await eac_kpi(session, project_id=project_id)
    snap = await _evm_snapshot(session, project_id)
    return KPIComputation(
        value=snap.bac - eac_result.value,
        unit="currency",
        source_record_count=snap.record_count,
        breakdown={**snap.breakdown, "eac": str(eac_result.value)},
    )


@register_kpi(
    "tcpi",
    name="To-Complete Performance Index",
    unit="ratio",
    category="financial",
    source_modules=["finance", "tasks", "projects"],
    description="(BAC - EV) / (BAC - AC). CPI required for the remaining work.",
)
async def tcpi_kpi(
    session: AsyncSession,
    project_id: uuid.UUID | None = None,
    **_: Any,
) -> KPIComputation:
    snap = await _evm_snapshot(session, project_id)
    denom = snap.bac - snap.ac
    if denom <= 0:
        return KPIComputation(
            value=Decimal("0"),
            unit="ratio",
            source_record_count=snap.record_count,
            breakdown=snap.breakdown,
        )
    value = _safe_div(snap.bac - snap.ev, denom)
    return KPIComputation(
        value=value,
        unit="ratio",
        source_record_count=snap.record_count,
        breakdown=snap.breakdown,
    )


@register_kpi(
    "procurement_savings",
    name="Procurement Savings",
    unit="percent",
    category="financial",
    source_modules=["procurement"],
    description="(Budgeted - actual) / budgeted on POs.",
)
async def procurement_savings_kpi(
    session: AsyncSession,
    project_id: uuid.UUID | None = None,
    **_: Any,
) -> KPIComputation:
    """Procurement savings = (budgeted - actual) / budgeted."""
    budgeted = Decimal("0")
    actual = Decimal("0")
    count = 0
    try:
        from app.modules.procurement.models import PurchaseOrder  # type: ignore

        stmt = select(PurchaseOrder)
        if project_id is not None:
            stmt = stmt.where(PurchaseOrder.project_id == project_id)
        rows = (await session.execute(stmt)).scalars().all()
        for row in rows:
            budgeted += _to_decimal(
                getattr(row, "budgeted_amount", None) or getattr(row, "budget", 0),
            )
            actual += _to_decimal(getattr(row, "total_amount", 0))
            count += 1
    except ImportError:
        pass
    except Exception:
        logger.debug("procurement_savings: probe failed", exc_info=True)

    if budgeted <= 0:
        return KPIComputation(
            value=Decimal("0"),
            unit="percent",
            source_record_count=count,
        )
    pct = (budgeted - actual) / budgeted * Decimal("100")
    return KPIComputation(
        value=pct,
        unit="percent",
        source_record_count=count,
        breakdown={"budgeted": str(budgeted), "actual": str(actual)},
    )


@register_kpi(
    "change_order_ratio",
    name="Change Order Ratio",
    unit="percent",
    category="financial",
    source_modules=["changeorders"],
    description="Total CO value / original contract value.",
)
async def change_order_ratio_kpi(
    session: AsyncSession,
    project_id: uuid.UUID | None = None,
    **_: Any,
) -> KPIComputation:
    co_value = Decimal("0")
    count = 0
    try:
        from app.modules.changeorders.models import ChangeOrder  # type: ignore

        stmt = select(ChangeOrder)
        if project_id is not None:
            stmt = stmt.where(ChangeOrder.project_id == project_id)
        rows = (await session.execute(stmt)).scalars().all()
        for row in rows:
            co_value += _to_decimal(
                getattr(row, "amount", None) or getattr(row, "total", 0),
            )
            count += 1
    except ImportError:
        pass
    except Exception:
        logger.debug("change_order_ratio: probe failed", exc_info=True)

    contract_value = Decimal("0")
    try:
        from app.modules.projects.models import Project  # type: ignore

        if project_id is not None:
            proj = await session.get(Project, project_id)
            if proj is not None:
                contract_value = _to_decimal(
                    getattr(proj, "contract_value", None) or getattr(proj, "budget", 0),
                )
    except ImportError:
        pass
    except Exception:
        logger.debug("change_order_ratio: project probe failed", exc_info=True)

    if contract_value <= 0:
        return KPIComputation(
            value=Decimal("0"),
            unit="percent",
            source_record_count=count,
        )
    pct = co_value / contract_value * Decimal("100")
    return KPIComputation(
        value=pct,
        unit="percent",
        source_record_count=count,
        breakdown={
            "change_order_total": str(co_value),
            "contract_value": str(contract_value),
        },
    )


@register_kpi(
    "cash_in_30d",
    name="Cash Inflow (30d)",
    unit="currency",
    category="financial",
    source_modules=["finance"],
    description="Projected cash inflow over the next 30 days.",
)
async def cash_in_30d_kpi(
    session: AsyncSession,
    project_id: uuid.UUID | None = None,
    **_: Any,
) -> KPIComputation:
    total = Decimal("0")
    count = 0
    horizon = datetime.now(UTC).date() + timedelta(days=30)
    try:
        from app.modules.finance.models import Invoice  # type: ignore

        stmt = select(Invoice)
        if project_id is not None:
            stmt = stmt.where(Invoice.project_id == project_id)
        rows = (await session.execute(stmt)).scalars().all()
        for row in rows:
            due = getattr(row, "due_date", None)
            if due is None or (isinstance(due, _date) and due <= horizon):
                amt = _to_decimal(getattr(row, "amount", 0))
                paid = _to_decimal(getattr(row, "paid_amount", 0))
                total += max(Decimal("0"), amt - paid)
                count += 1
    except ImportError:
        pass
    except Exception:
        logger.debug("cash_in_30d: probe failed", exc_info=True)
    return KPIComputation(
        value=total,
        unit="currency",
        source_record_count=count,
    )


@register_kpi(
    "cash_out_30d",
    name="Cash Outflow (30d)",
    unit="currency",
    category="financial",
    source_modules=["finance"],
    description="Projected cash outflow over the next 30 days.",
)
async def cash_out_30d_kpi(
    session: AsyncSession,
    project_id: uuid.UUID | None = None,
    **_: Any,
) -> KPIComputation:
    total = Decimal("0")
    count = 0
    horizon = datetime.now(UTC).date() + timedelta(days=30)
    try:
        from app.modules.finance.models import Expense  # type: ignore

        stmt = select(Expense)
        if project_id is not None:
            stmt = stmt.where(Expense.project_id == project_id)
        rows = (await session.execute(stmt)).scalars().all()
        for row in rows:
            due = getattr(row, "due_date", None)
            if due is None or (isinstance(due, _date) and due <= horizon):
                total += _to_decimal(getattr(row, "amount", 0))
                count += 1
    except ImportError:
        pass
    except Exception:
        logger.debug("cash_out_30d: probe failed", exc_info=True)
    return KPIComputation(
        value=total,
        unit="currency",
        source_record_count=count,
    )


@register_kpi(
    "dso",
    name="Days Sales Outstanding",
    unit="days",
    category="financial",
    source_modules=["finance"],
    description="Average days from invoice issue to payment.",
)
async def dso_kpi(
    session: AsyncSession,
    project_id: uuid.UUID | None = None,
    **_: Any,
) -> KPIComputation:
    total_days = Decimal("0")
    count = 0
    try:
        from app.modules.finance.models import Invoice  # type: ignore

        stmt = select(Invoice)
        if project_id is not None:
            stmt = stmt.where(Invoice.project_id == project_id)
        rows = (await session.execute(stmt)).scalars().all()
        for row in rows:
            issued = getattr(row, "issue_date", None) or getattr(
                row,
                "issued_at",
                None,
            )
            paid_at = getattr(row, "paid_at", None) or getattr(
                row,
                "paid_date",
                None,
            )
            if issued is None or paid_at is None:
                continue
            try:
                if isinstance(issued, datetime):
                    issued = issued.date()
                if isinstance(paid_at, datetime):
                    paid_at = paid_at.date()
                delta = (paid_at - issued).days
                total_days += Decimal(delta)
                count += 1
            except Exception:
                continue
    except ImportError:
        pass
    except Exception:
        logger.debug("dso: probe failed", exc_info=True)

    avg = _safe_div(total_days, Decimal(count)) if count > 0 else Decimal("0")
    return KPIComputation(
        value=avg,
        unit="days",
        source_record_count=count,
    )


# ── Quality KPIs ───────────────────────────────────────────────────────


@register_kpi(
    "first_pass_yield",
    name="First Pass Yield",
    unit="percent",
    category="quality",
    source_modules=["inspections", "ncr"],
    target_default=Decimal("95"),
    description="Passed inspections / total inspections.",
)
async def first_pass_yield_kpi(
    session: AsyncSession,
    project_id: uuid.UUID | None = None,
    **_: Any,
) -> KPIComputation:
    total = 0
    passed = 0
    try:
        from app.modules.inspections.models import Inspection  # type: ignore

        stmt = select(Inspection)
        if project_id is not None:
            stmt = stmt.where(Inspection.project_id == project_id)
        rows = (await session.execute(stmt)).scalars().all()
        for row in rows:
            total += 1
            status_val = (getattr(row, "status", "") or "").lower()
            if status_val in ("passed", "pass", "approved", "completed"):
                passed += 1
    except ImportError:
        pass
    except Exception:
        logger.debug("first_pass_yield: probe failed", exc_info=True)

    if total == 0:
        return KPIComputation(
            value=Decimal("0"),
            unit="percent",
            source_record_count=0,
        )
    pct = Decimal(passed) / Decimal(total) * Decimal("100")
    return KPIComputation(
        value=pct,
        unit="percent",
        source_record_count=total,
        breakdown={"passed": passed, "total": total},
    )


@register_kpi(
    "copq",
    name="Cost of Poor Quality",
    unit="currency",
    category="quality",
    source_modules=["ncr"],
    description="Sum of NCR cost impact.",
)
async def copq_kpi(
    session: AsyncSession,
    project_id: uuid.UUID | None = None,
    **_: Any,
) -> KPIComputation:
    total = Decimal("0")
    count = 0
    try:
        from app.modules.ncr.models import NCR  # type: ignore

        stmt = select(NCR)
        if project_id is not None:
            stmt = stmt.where(NCR.project_id == project_id)
        rows = (await session.execute(stmt)).scalars().all()
        for row in rows:
            total += _to_decimal(
                getattr(row, "cost_impact", None) or getattr(row, "cost", 0),
            )
            count += 1
    except ImportError:
        pass
    except Exception:
        logger.debug("copq: probe failed", exc_info=True)
    return KPIComputation(
        value=total,
        unit="currency",
        source_record_count=count,
    )


@register_kpi(
    "punch_close_rate",
    name="Punch List Close Rate",
    unit="percent",
    category="quality",
    source_modules=["punchlist"],
    description="Closed punch items / total.",
)
async def punch_close_rate_kpi(
    session: AsyncSession,
    project_id: uuid.UUID | None = None,
    **_: Any,
) -> KPIComputation:
    total = 0
    closed = 0
    try:
        from app.modules.punchlist.models import PunchItem  # type: ignore

        stmt = select(PunchItem)
        if project_id is not None:
            stmt = stmt.where(PunchItem.project_id == project_id)
        rows = (await session.execute(stmt)).scalars().all()
        for row in rows:
            total += 1
            status_val = (getattr(row, "status", "") or "").lower()
            if status_val in ("closed", "resolved", "completed", "verified"):
                closed += 1
    except ImportError:
        pass
    except Exception:
        logger.debug("punch_close_rate: probe failed", exc_info=True)

    if total == 0:
        return KPIComputation(
            value=Decimal("0"),
            unit="percent",
            source_record_count=0,
        )
    pct = Decimal(closed) / Decimal(total) * Decimal("100")
    return KPIComputation(
        value=pct,
        unit="percent",
        source_record_count=total,
        breakdown={"closed": closed, "total": total},
    )


@register_kpi(
    "rfi_close_avg_days",
    name="RFI Close Avg Days",
    unit="days",
    category="quality",
    source_modules=["rfi"],
    description="Average days from RFI open to close.",
)
async def rfi_close_avg_days_kpi(
    session: AsyncSession,
    project_id: uuid.UUID | None = None,
    **_: Any,
) -> KPIComputation:
    total_days = Decimal("0")
    count = 0
    try:
        from app.modules.rfi.models import RFI  # type: ignore

        stmt = select(RFI)
        if project_id is not None:
            stmt = stmt.where(RFI.project_id == project_id)
        rows = (await session.execute(stmt)).scalars().all()
        for row in rows:
            opened = getattr(row, "created_at", None) or getattr(
                row,
                "opened_at",
                None,
            )
            closed = getattr(row, "closed_at", None) or getattr(
                row,
                "responded_at",
                None,
            )
            if opened is None or closed is None:
                continue
            try:
                if isinstance(opened, datetime):
                    opened_d = opened.date()
                else:
                    opened_d = opened
                if isinstance(closed, datetime):
                    closed_d = closed.date()
                else:
                    closed_d = closed
                delta = (closed_d - opened_d).days
                total_days += Decimal(max(0, delta))
                count += 1
            except Exception:
                continue
    except ImportError:
        pass
    except Exception:
        logger.debug("rfi_close_avg_days: probe failed", exc_info=True)

    avg = _safe_div(total_days, Decimal(count)) if count > 0 else Decimal("0")
    return KPIComputation(value=avg, unit="days", source_record_count=count)


# ── Safety KPIs ────────────────────────────────────────────────────────


@register_kpi(
    "safety_trir",
    name="Total Recordable Incident Rate",
    unit="ratio",
    category="safety",
    source_modules=["safety"],
    target_default=Decimal("0"),
    description="(Recordable incidents × 200000) / hours worked.",
)
async def safety_trir_kpi(
    session: AsyncSession,
    project_id: uuid.UUID | None = None,
    **_: Any,
) -> KPIComputation:
    incidents = 0
    hours_worked = Decimal("200000")  # Industry-standard normaliser
    try:
        from app.modules.safety.models import Incident  # type: ignore

        stmt = select(Incident)
        if project_id is not None:
            stmt = stmt.where(Incident.project_id == project_id)
        rows = (await session.execute(stmt)).scalars().all()
        for row in rows:
            # Recordable = not "first_aid_only"
            severity = (getattr(row, "severity", "") or "").lower()
            if severity in (
                "minor",
                "major",
                "fatal",
                "lost_time",
                "recordable",
                "medical_treatment",
            ):
                incidents += 1
        # Try to find actual hours-worked records — gracefully fall back
        try:
            from app.modules.safety.models import WorkHours  # type: ignore

            stmt2 = select(WorkHours)
            if project_id is not None:
                stmt2 = stmt2.where(WorkHours.project_id == project_id)
            wh_rows = (await session.execute(stmt2)).scalars().all()
            total_hours = sum(
                (_to_decimal(getattr(r, "hours", 0)) for r in wh_rows),
                Decimal("0"),
            )
            if total_hours > 0:
                hours_worked = total_hours
        except Exception:
            pass
    except ImportError:
        pass
    except Exception:
        logger.debug("safety_trir: probe failed", exc_info=True)

    trir = Decimal(incidents) * Decimal("200000") / hours_worked if hours_worked > 0 else Decimal("0")
    return KPIComputation(
        value=trir,
        unit="ratio",
        source_record_count=incidents,
        breakdown={
            "incidents": incidents,
            "hours_worked": str(hours_worked),
        },
    )


# ── Sustainability ─────────────────────────────────────────────────────


@register_kpi(
    "embodied_carbon_per_m2",
    name="Embodied Carbon per m2",
    unit="ratio",
    category="sustainability",
    source_modules=["carbon", "projects"],
    description="Total Scope 3 emissions / project gross floor area.",
)
async def embodied_carbon_per_m2_kpi(
    session: AsyncSession,
    project_id: uuid.UUID | None = None,
    **_: Any,
) -> KPIComputation:
    total_emissions = Decimal("0")
    project_area = Decimal("0")
    count = 0
    try:
        from app.modules.carbon.models import (  # type: ignore
            CarbonInventory,
        )

        stmt = select(CarbonInventory)
        if project_id is not None:
            stmt = stmt.where(CarbonInventory.project_id == project_id)
        rows = (await session.execute(stmt)).scalars().all()
        for row in rows:
            total_emissions += _to_decimal(
                getattr(row, "scope3_kgco2e", None) or getattr(row, "kgco2e", 0),
            )
            count += 1
    except ImportError:
        pass
    except Exception:
        logger.debug("embodied_carbon_per_m2: carbon probe failed", exc_info=True)

    try:
        from app.modules.projects.models import Project  # type: ignore

        if project_id is not None:
            proj = await session.get(Project, project_id)
            if proj is not None:
                project_area = _to_decimal(
                    getattr(proj, "gross_floor_area_m2", None) or getattr(proj, "area_m2", 0),
                )
    except ImportError:
        pass
    except Exception:
        logger.debug("embodied_carbon_per_m2: project probe failed", exc_info=True)

    value = _safe_div(total_emissions, project_area)
    return KPIComputation(
        value=value,
        unit="ratio",
        source_record_count=count,
        breakdown={
            "total_kgco2e": str(total_emissions),
            "area_m2": str(project_area),
        },
    )


# ── Operational ────────────────────────────────────────────────────────


@register_kpi(
    "equipment_utilization",
    name="Equipment Utilization",
    unit="percent",
    category="operational",
    source_modules=["equipment"],
    description="hours_used / hours_available.",
)
async def equipment_utilization_kpi(
    session: AsyncSession,
    project_id: uuid.UUID | None = None,
    **_: Any,
) -> KPIComputation:
    used = Decimal("0")
    available = Decimal("0")
    count = 0
    try:
        from app.modules.equipment.models import Equipment  # type: ignore

        stmt = select(Equipment)
        if project_id is not None:
            stmt = stmt.where(Equipment.project_id == project_id)
        rows = (await session.execute(stmt)).scalars().all()
        for row in rows:
            used += _to_decimal(getattr(row, "hours_used", 0))
            available += _to_decimal(
                getattr(row, "hours_available", None) or getattr(row, "total_hours", 0),
            )
            count += 1
    except ImportError:
        pass
    except Exception:
        logger.debug("equipment_utilization: probe failed", exc_info=True)

    if available <= 0:
        return KPIComputation(
            value=Decimal("0"),
            unit="percent",
            source_record_count=count,
        )
    pct = used / available * Decimal("100")
    return KPIComputation(
        value=pct,
        unit="percent",
        source_record_count=count,
        breakdown={"hours_used": str(used), "hours_available": str(available)},
    )


@register_kpi(
    "subcontractor_avg_rating",
    name="Subcontractor Avg Rating",
    unit="ratio",
    category="operational",
    source_modules=["subcontractors"],
    description="Average of SubcontractorRating.score.",
)
async def subcontractor_avg_rating_kpi(
    session: AsyncSession,
    project_id: uuid.UUID | None = None,
    **_: Any,
) -> KPIComputation:
    total = Decimal("0")
    count = 0
    try:
        from app.modules.subcontractors.models import (  # type: ignore
            SubcontractorRating,
        )

        stmt = select(SubcontractorRating)
        if project_id is not None:
            stmt = stmt.where(SubcontractorRating.project_id == project_id)
        rows = (await session.execute(stmt)).scalars().all()
        for row in rows:
            total += _to_decimal(getattr(row, "score", 0))
            count += 1
    except ImportError:
        pass
    except Exception:
        logger.debug("subcontractor_avg_rating: probe failed", exc_info=True)

    avg = _safe_div(total, Decimal(count)) if count > 0 else Decimal("0")
    return KPIComputation(value=avg, unit="ratio", source_record_count=count)


@register_kpi(
    "bid_win_rate",
    name="Bid Win Rate",
    unit="percent",
    category="operational",
    source_modules=["bid_management", "tendering"],
    description="Won bids / submitted bids.",
)
async def bid_win_rate_kpi(
    session: AsyncSession,
    project_id: uuid.UUID | None = None,
    **_: Any,
) -> KPIComputation:
    won = 0
    total = 0
    # Try bid_management first, then tendering as fallback
    for module_path, model_name in (
        ("app.modules.bid_management.models", "Bid"),
        ("app.modules.tendering.models", "Bid"),
    ):
        try:
            module = __import__(module_path, fromlist=[model_name])
            Bid = getattr(module, model_name)  # noqa: N806
            stmt = select(Bid)
            if project_id is not None:
                stmt = stmt.where(Bid.project_id == project_id)
            rows = (await session.execute(stmt)).scalars().all()
            for row in rows:
                total += 1
                status_val = (getattr(row, "status", "") or "").lower()
                if status_val in ("won", "awarded", "accepted"):
                    won += 1
            if total > 0:
                break
        except ImportError:
            continue
        except Exception:
            logger.debug(
                "bid_win_rate: %s probe failed",
                module_path,
                exc_info=True,
            )
            continue

    if total == 0:
        return KPIComputation(
            value=Decimal("0"),
            unit="percent",
            source_record_count=0,
        )
    pct = Decimal(won) / Decimal(total) * Decimal("100")
    return KPIComputation(
        value=pct,
        unit="percent",
        source_record_count=total,
        breakdown={"won": won, "total": total},
    )


@register_kpi(
    "project_count_active",
    name="Active Project Count",
    unit="count",
    category="operational",
    source_modules=["projects"],
    description="Count of projects with status='active' or similar.",
)
async def project_count_active_kpi(
    session: AsyncSession,
    project_id: uuid.UUID | None = None,  # noqa: ARG001 — global only
    **_: Any,
) -> KPIComputation:
    count = 0
    try:
        from app.modules.projects.models import Project  # type: ignore

        rows = (await session.execute(select(Project))).scalars().all()
        for row in rows:
            status_val = (getattr(row, "status", "") or "").lower()
            if status_val in ("active", "in_progress", "construction", ""):
                count += 1
    except ImportError:
        pass
    except Exception:
        logger.debug("project_count_active: probe failed", exc_info=True)

    return KPIComputation(
        value=Decimal(count),
        unit="count",
        source_record_count=count,
    )


# ── Bootstrap ──────────────────────────────────────────────────────────


def list_system_kpis() -> list[dict[str, Any]]:
    """Return metadata for every registered system KPI."""
    return [dict(meta) for meta in SYSTEM_KPI_META.values()]


# ── Drill-down record providers ─────────────────────────────────────────
# A KPI's "drill-down" returns the underlying rows that fed the aggregate —
# e.g. for ``cpi`` we return the (project_id, finance.Expense.amount,
# task.earned_value) rows. Each provider is registered against a KPI code
# and returns a list of dicts, capped at ``limit``.

KPIRecordProvider = Callable[..., Awaitable[list[dict[str, Any]]]]
KPI_RECORD_PROVIDERS: dict[str, KPIRecordProvider] = {}


def register_kpi_records(code: str) -> Callable[[KPIRecordProvider], KPIRecordProvider]:
    """Decorator registering a drill-down record provider for a KPI."""

    def decorator(fn: KPIRecordProvider) -> KPIRecordProvider:
        KPI_RECORD_PROVIDERS[code] = fn
        return fn

    return decorator


async def _evm_drilldown_records(
    session: AsyncSession,
    project_id: uuid.UUID | None,
    limit: int,
) -> list[dict[str, Any]]:
    """Shared drill-down implementation for every EVM KPI.

    Returns one row per task with its PV/EV plus the matching finance
    expenses (joined logically via project_id only — strict task-expense
    linking is upstream).
    """
    records: list[dict[str, Any]] = []
    try:
        from app.modules.tasks.models import Task  # type: ignore

        stmt = select(Task).limit(limit)
        if project_id is not None:
            stmt = stmt.where(Task.project_id == project_id)
        rows = (await session.execute(stmt)).scalars().all()
        for row in rows:
            records.append(
                {
                    "kind": "task",
                    "id": str(row.id),
                    "name": getattr(row, "name", ""),
                    "planned_value": str(_to_decimal(getattr(row, "planned_value", 0))),
                    "earned_value": str(_to_decimal(getattr(row, "earned_value", 0))),
                    "project_id": str(getattr(row, "project_id", "")),
                },
            )
    except ImportError:
        pass
    except Exception:
        logger.debug("evm drilldown: tasks probe failed", exc_info=True)
    try:
        from app.modules.finance.models import Expense  # type: ignore

        stmt = select(Expense).limit(limit)
        if project_id is not None:
            stmt = stmt.where(Expense.project_id == project_id)
        rows = (await session.execute(stmt)).scalars().all()
        for row in rows:
            records.append(
                {
                    "kind": "expense",
                    "id": str(row.id),
                    "amount": str(_to_decimal(getattr(row, "amount", 0))),
                    "project_id": str(getattr(row, "project_id", "")),
                    "vendor_id": str(getattr(row, "vendor_id", "") or ""),
                    "category": getattr(row, "category", "") or "",
                },
            )
    except ImportError:
        pass
    except Exception:
        logger.debug("evm drilldown: finance probe failed", exc_info=True)
    return records


for _evm_code in ("cpi", "spi", "cv", "sv", "eac", "etc", "vac", "tcpi"):
    KPI_RECORD_PROVIDERS[_evm_code] = _evm_drilldown_records


@register_kpi_records("safety_trir")
async def _safety_trir_records(
    session: AsyncSession,
    project_id: uuid.UUID | None,
    limit: int,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    try:
        from app.modules.safety.models import Incident  # type: ignore

        stmt = select(Incident).limit(limit)
        if project_id is not None:
            stmt = stmt.where(Incident.project_id == project_id)
        rows = (await session.execute(stmt)).scalars().all()
        for row in rows:
            records.append(
                {
                    "kind": "incident",
                    "id": str(row.id),
                    "severity": getattr(row, "severity", "") or "",
                    "occurred_at": str(getattr(row, "occurred_at", "") or ""),
                    "project_id": str(getattr(row, "project_id", "") or ""),
                },
            )
    except ImportError:
        pass
    except Exception:
        logger.debug("safety_trir drilldown: probe failed", exc_info=True)
    return records


@register_kpi_records("project_count_active")
async def _projects_active_records(
    session: AsyncSession,
    project_id: uuid.UUID | None,  # noqa: ARG001
    limit: int,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    try:
        from app.modules.projects.models import Project  # type: ignore

        stmt = select(Project).limit(limit)
        rows = (await session.execute(stmt)).scalars().all()
        for row in rows:
            records.append(
                {
                    "kind": "project",
                    "id": str(row.id),
                    "name": getattr(row, "name", "") or "",
                    "status": getattr(row, "status", "") or "",
                    "budget": str(_to_decimal(getattr(row, "budget", 0))),
                },
            )
    except ImportError:
        pass
    except Exception:
        logger.debug("project_count_active drilldown: probe failed", exc_info=True)
    return records


async def drilldown(
    code: str,
    session: AsyncSession,
    *,
    project_id: uuid.UUID | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Return underlying records for a KPI, capped at ``limit``.

    Returns ``[]`` if no provider is registered or the probe fails.
    """
    provider = KPI_RECORD_PROVIDERS.get(code)
    if provider is None:
        return []
    try:
        return await provider(session, project_id, limit)
    except Exception:
        logger.exception("drilldown: provider for %s raised", code)
        return []


# ── Benchmark (portfolio median) ────────────────────────────────────────


async def benchmark(
    code: str,
    session: AsyncSession,
    *,
    project_id: uuid.UUID | None,
) -> dict[str, Any]:
    """Return ``{value, median, percentile}`` comparing the project's KPI
    to the portfolio median computed across all active projects.

    Skipped when:
        * ``project_id`` is None (caller already at portfolio level)
        * No other projects exist
    """
    if project_id is None:
        return {}
    try:
        from app.modules.projects.models import Project  # type: ignore

        rows = (await session.execute(select(Project))).scalars().all()
    except ImportError:
        return {}
    except Exception:
        logger.debug("benchmark: project list failed", exc_info=True)
        return {}

    project_values: list[Decimal] = []
    target_value: Decimal | None = None
    for proj in rows:
        try:
            result = await compute(code, session, project_id=proj.id)
        except Exception:
            continue
        if result.source_record_count == 0:
            continue
        project_values.append(result.value)
        if proj.id == project_id:
            target_value = result.value
    if not project_values or target_value is None:
        return {}
    project_values.sort()
    n = len(project_values)
    median = (
        (project_values[n // 2 - 1] + project_values[n // 2]) / Decimal("2") if n % 2 == 0 else project_values[n // 2]
    )
    rank = sum(1 for v in project_values if v <= target_value)
    percentile = Decimal(rank) * Decimal("100") / Decimal(n)
    return {
        "value": str(target_value),
        "median": str(median),
        "percentile": str(percentile.quantize(Decimal("0.01"))),
        "portfolio_size": n,
    }


async def compute(
    code: str,
    session: AsyncSession,
    *,
    project_id: uuid.UUID | None = None,
    period_start: _date | None = None,
    period_end: _date | None = None,
    filters: dict[str, Any] | None = None,
) -> KPIComputation:
    """Invoke a registered KPI safely.

    Returns a zero-value :class:`KPIComputation` when the code is unknown
    or when the formula raises — never bubble up to API callers, this
    module is purely consumer code.
    """
    fn = KPI_FORMULAS.get(code)
    if fn is None:
        logger.debug("compute: unknown KPI code=%s", code)
        return KPIComputation()
    try:
        return await fn(
            session,
            project_id=project_id,
            period_start=period_start,
            period_end=period_end,
            filters=filters or {},
        )
    except Exception:
        logger.exception("compute: KPI %s formula raised", code)
        return KPIComputation()


__all__ = [
    "EVMSnapshot",
    "KPIComputation",
    "KPIFormula",
    "KPIRecordProvider",
    "KPI_FORMULAS",
    "KPI_RECORD_PROVIDERS",
    "SYSTEM_KPI_META",
    "benchmark",
    "compute",
    "drilldown",
    "list_system_kpis",
    "register_kpi",
    "register_kpi_records",
]
