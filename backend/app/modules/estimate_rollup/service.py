# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Estimate-rollup service - read-only cross-module composition.

Composes a project's full estimate headline number by reading three sibling
estimating modules and handing their figures to the pure
:mod:`app.modules.estimate_rollup.composition` engine. This layer does the
database reads only; it writes nothing and mutates nothing, and it reuses each
module's own authoritative rollup so the estimate total can never drift from what
each tool shows on its own:

* **BOQ base** - reuses ``boq.service.BOQService.compute_boq_totals``, which
  already sums each BOQ's direct cost plus its markups and converts every leaf to
  the project base currency (Issue #111). We sum those per-BOQ grand totals.
* **Preliminaries** - reuses ``preliminaries.prelim_math.rollup_by_category``
  (the same engine the register and the basis-of-estimate use).
* **Allowances / contingency** - reuses
  ``allowances.service.AllowanceService.build_register_summary`` (held / drawn /
  remaining per currency and type) and folds the REMAINING figures to the base
  currency.

FX: the project base currency and rate table come from the very method the BOQ
rollup uses (``_resolve_project_fx_by_project``), so a multi-currency project
composes into the same base currency the same way throughout the platform.

Degrades gracefully: a project with no BOQ yields a zero base, a project with no
preliminaries / allowances yields just the BOQ base, and any lookup failure
leaves that part at zero rather than raising - a rollup is a read-only summary and
must never 500 a dashboard.
"""

from __future__ import annotations

import logging
import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.allowances.service import AllowanceService
from app.modules.boq.models import BOQ
from app.modules.boq.service import BOQService
from app.modules.estimate_rollup.composition import (
    AllowancesBreakdown,
    EstimateRollup,
    PreliminariesBreakdown,
    compose_estimate_rollup,
    fold_allowances_to_base,
    prelim_breakdown_from_rollup,
)
from app.modules.preliminaries.models import PrelimItem
from app.modules.preliminaries.prelim_math import rollup_by_category

logger = logging.getLogger(__name__)

# Bound the preliminaries scan so a runaway project can never OOM the worker; the
# same ceiling the basis-of-estimate uses for the preliminaries roll-up.
_PRELIM_CAP = 2000

# Zero breakdowns for the graceful-degradation paths.
_EMPTY_PRELIM = PreliminariesBreakdown(
    total=Decimal("0.00"),
    fixed_total=Decimal("0.00"),
    time_related_total=Decimal("0.00"),
    item_count=0,
)
_EMPTY_ALLOWANCES = AllowancesBreakdown(
    total=Decimal("0.00"),
    provisional_sum_total=Decimal("0.00"),
    pc_sum_total=Decimal("0.00"),
    contingency_total=Decimal("0.00"),
    provisional_and_pc_count=0,
    contingency_count=0,
    allowance_count=0,
)


async def _project_boq_ids(session: AsyncSession, project_id: uuid.UUID) -> list[uuid.UUID]:
    """Return every BOQ id under a project (read-only, unpaginated)."""
    rows = await session.execute(select(BOQ.id).where(BOQ.project_id == project_id))
    return list(rows.scalars().all())


async def _boq_base(
    session: AsyncSession,
    boq_service: BOQService,
    project_id: uuid.UUID,
) -> tuple[Decimal, str]:
    """Sum the project's BOQ grand totals into the base currency.

    Reuses ``BOQService.compute_boq_totals`` (direct cost + markups, converted to
    the project base currency) and adds the per-BOQ grand totals. Returns the
    total and the base currency the BOQ rollup reported (``""`` when there is no
    BOQ or none carried a currency), so a project with a BOQ but no project-level
    currency row still labels its total.
    """
    boq_ids = await _project_boq_ids(session, project_id)
    if not boq_ids:
        return Decimal("0"), ""

    totals = await boq_service.compute_boq_totals(boq_ids)
    running = Decimal("0")
    base_currency = ""
    for entry in totals.values():
        # grand_total is a 2 dp float; the str() shortest-repr recovers the exact
        # cents, matching how the BOQ repository callers re-Decimalize it.
        running += Decimal(str(entry.get("grand_total", 0) or 0))
        if not base_currency:
            base_currency = str(entry.get("base_currency", "") or "").strip().upper()
    return running, base_currency


async def _preliminaries_breakdown(session: AsyncSession, project_id: uuid.UUID) -> PreliminariesBreakdown:
    """Roll the project's preliminaries up into a base-currency breakdown."""
    rows = await session.execute(
        select(PrelimItem).where(PrelimItem.project_id == project_id).limit(_PRELIM_CAP),
    )
    items = [
        {
            "item_type": item.item_type,
            "category": item.category,
            "rate_per_period": item.rate_per_period,
            "periods": item.periods,
            "fixed_amount": item.fixed_amount,
        }
        for item in rows.scalars().all()
    ]
    return prelim_breakdown_from_rollup(rollup_by_category(items))


async def _allowances_breakdown(
    session: AsyncSession,
    project_id: uuid.UUID,
    fx_map: dict[str, str],
    base_currency: str,
) -> AllowancesBreakdown:
    """Roll the allowances register up and fold remaining to the base currency."""
    register = await AllowanceService(session).build_register_summary(project_id)
    return fold_allowances_to_base(register, fx_map, base_currency)


async def compute_estimate_rollup(session: AsyncSession, project_id: uuid.UUID) -> EstimateRollup:
    """Compose a project's full estimate total from its estimating modules.

    Reads the BOQ base (measured works + markups), the preliminaries register and
    the allowances / contingency register, reduces every figure to the project
    base currency, and returns the composed :class:`EstimateRollup` -
    ``boq_base + preliminaries + allowances`` with a line-item breakdown.

    Read-only and side-effect-free. Degrades gracefully: a project with no BOQ
    returns a zero base, a project with no preliminaries / allowances returns just
    the BOQ base as the total, and any partial lookup failure leaves that part at
    zero instead of raising.

    Args:
        session: The active async database session.
        project_id: The project to compose.

    Returns:
        The composed :class:`EstimateRollup` (Decimal amounts; the router renders
        them as Decimal strings on the wire).
    """
    boq_service = BOQService(session)

    # Reuse the BOQ rollup's own FX resolution so the base currency and rate
    # table match the measured-works conversion exactly across the platform.
    base_currency, fx_map = await boq_service._resolve_project_fx_by_project(project_id)

    boq_base, boq_reported_currency = await _boq_base(session, boq_service, project_id)
    # Fall back to the currency the BOQ rollup reported if the project row carried
    # none (keeps the total labelled even when only the BOQ knows the currency).
    if not base_currency:
        base_currency = boq_reported_currency

    try:
        preliminaries = await _preliminaries_breakdown(session, project_id)
    except Exception:  # noqa: BLE001 - a rollup must never 500 on one part
        logger.exception("Preliminaries rollup failed for project %s", project_id)
        preliminaries = _EMPTY_PRELIM

    try:
        allowances = await _allowances_breakdown(session, project_id, fx_map, base_currency)
    except Exception:  # noqa: BLE001 - a rollup must never 500 on one part
        logger.exception("Allowances rollup failed for project %s", project_id)
        allowances = _EMPTY_ALLOWANCES

    return compose_estimate_rollup(base_currency, boq_base, preliminaries, allowances)
