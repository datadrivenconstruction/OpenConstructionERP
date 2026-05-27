"""‌⁠‍5D Cost Model data access layer.

All database queries for cost snapshots, budget lines, and cash flow entries
live here.  No business logic — pure data access — *except* for the
currency-aware rollup helpers added by the R5 audit (May 2026): mixing
USD and EUR row totals via raw SQL ``SUM`` poisoned the dashboard /
EVM / budget summary for any multi-currency project, so the aggregators
now pull rows in Python and convert through the project's ``fx_rates``
before summing. The conversion logic itself is colocated here so each
caller cannot re-invent its own rules.
"""

import uuid
from decimal import Decimal, InvalidOperation

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.costmodel.models import BudgetLine, CashFlow, CostSnapshot

# ── Currency conversion helper (R5 audit, May 2026) ─────────────────────


def _amount_in_base(
    raw: str | None,
    line_currency: str,
    base_currency: str,
    fx_rates: dict[str, str],
) -> Decimal:
    """Convert a stored money string into the project base currency.

    Mirrors the ``_resource_total_in_base`` / ``_position_total_in_base``
    helpers in ``app.modules.boq.service`` so every cost-domain rollup
    shares one set of FX semantics:

    - missing line currency → treated as base (legacy behaviour for rows
      written before the multi-currency wave shipped);
    - line currency == base → returned verbatim;
    - foreign currency with a configured rate → ``raw * fx_rates[code]``
      (units of base per 1 unit of foreign);
    - foreign currency with NO configured rate → kept in its own units
      (NEVER zeroed) so a forgotten rate surfaces as a visibly-wrong
      total instead of silently dropping money. The cost dashboard
      remains deterministic — flapping silent zeroes were the worst
      possible degradation here.

    All math is Decimal end-to-end so a million-line BAC doesn't drift
    by floating-point accumulation.
    """
    if raw in (None, ""):
        return Decimal("0")
    try:
        amount = Decimal(str(raw))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal("0")
    if not amount.is_finite():
        return Decimal("0")

    code = (line_currency or "").strip().upper()
    base = (base_currency or "").strip().upper()
    if not code or not base or code == base:
        return amount

    rate_raw = fx_rates.get(code)
    if rate_raw is None:
        # No FX rate configured — keep in its own units rather than zero.
        return amount
    try:
        rate = Decimal(str(rate_raw))
    except (InvalidOperation, ValueError, TypeError):
        return amount
    if not rate.is_finite() or rate <= 0:
        return amount

    return amount * rate


# ── CostSnapshot repository ─────────────────────────────────────────────────


class SnapshotRepository:
    """‌⁠‍Data access for CostSnapshot model."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, snapshot_id: uuid.UUID) -> CostSnapshot | None:
        """‌⁠‍Get snapshot by ID."""
        return await self.session.get(CostSnapshot, snapshot_id)

    async def list_for_project(
        self,
        project_id: uuid.UUID,
        *,
        period_from: str | None = None,
        period_to: str | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> tuple[list[CostSnapshot], int]:
        """List snapshots for a project, optionally filtered by period range.

        Args:
            project_id: Target project.
            period_from: Inclusive lower bound (YYYY-MM).
            period_to: Inclusive upper bound (YYYY-MM).
            offset: Pagination offset.
            limit: Pagination limit.

        Returns:
            Tuple of (snapshots, total_count).
        """
        base = select(CostSnapshot).where(CostSnapshot.project_id == project_id)

        if period_from is not None:
            base = base.where(CostSnapshot.period >= period_from)
        if period_to is not None:
            base = base.where(CostSnapshot.period <= period_to)

        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = base.order_by(CostSnapshot.period.asc()).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        snapshots = list(result.scalars().all())

        return snapshots, total

    async def get_latest_for_project(self, project_id: uuid.UUID) -> CostSnapshot | None:
        """Get the most recent *real* monthly snapshot for a project.

        What-if scenarios store their result as a CostSnapshot row with a
        ``wif:<short-id>:YYYY-MM`` period (so they cannot collide with the
        ``(project_id, period)`` unique index introduced in migration
        v3108). Those scenario rows must NEVER masquerade as the latest
        real snapshot — otherwise the dashboard SPI/CPI flips to scenario
        values the moment someone runs a what-if. Filter them out.
        """
        stmt = (
            select(CostSnapshot)
            .where(
                CostSnapshot.project_id == project_id,
                ~CostSnapshot.period.like("wif:%"),
            )
            .order_by(CostSnapshot.period.desc())
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def get_for_project_period(self, project_id: uuid.UUID, period: str) -> CostSnapshot | None:
        """Return the snapshot for ``(project_id, period)`` if one exists.

        Used by ``create_snapshot`` to reject duplicate periods at the
        service layer with a clean 409, backstopped by the DB unique
        index added in migration v3108.
        """
        stmt = (
            select(CostSnapshot)
            .where(
                CostSnapshot.project_id == project_id,
                CostSnapshot.period == period,
            )
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def create(self, snapshot: CostSnapshot) -> CostSnapshot:
        """Insert a new snapshot."""
        self.session.add(snapshot)
        await self.session.flush()
        return snapshot

    async def update_fields(self, snapshot_id: uuid.UUID, **fields: object) -> None:
        """Update specific fields on a snapshot."""
        stmt = update(CostSnapshot).where(CostSnapshot.id == snapshot_id).values(**fields)
        await self.session.execute(stmt)
        await self.session.flush()
        # Expire cached ORM instances so the next get_by_id re-reads from DB
        self.session.expire_all()

    async def delete(self, snapshot_id: uuid.UUID) -> None:
        """Delete a snapshot."""
        stmt = delete(CostSnapshot).where(CostSnapshot.id == snapshot_id)
        await self.session.execute(stmt)


# ── BudgetLine repository ───────────────────────────────────────────────────


class BudgetLineRepository:
    """Data access for BudgetLine model."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, line_id: uuid.UUID) -> BudgetLine | None:
        """Get budget line by ID."""
        return await self.session.get(BudgetLine, line_id)

    async def list_for_project(
        self,
        project_id: uuid.UUID,
        *,
        category: str | None = None,
        offset: int = 0,
        limit: int = 200,
    ) -> tuple[list[BudgetLine], int]:
        """List budget lines for a project with optional category filter.

        Args:
            project_id: Target project.
            category: Optional category filter (e.g. 'material').
            offset: Pagination offset.
            limit: Pagination limit.

        Returns:
            Tuple of (budget_lines, total_count).
        """
        base = select(BudgetLine).where(BudgetLine.project_id == project_id)

        if category is not None:
            base = base.where(BudgetLine.category == category)

        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = base.order_by(BudgetLine.category, BudgetLine.created_at).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        lines = list(result.scalars().all())

        return lines, total

    async def _list_lines_for_rollup(self, project_id: uuid.UUID) -> list[BudgetLine]:
        """Return every budget line for ``project_id`` — used by the
        currency-aware aggregators below. Extracted into its own method
        so unit tests can stub it without monkey-patching SQLAlchemy.
        """
        stmt = select(BudgetLine).where(BudgetLine.project_id == project_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def _project_fx_context(self, project_id: uuid.UUID) -> tuple[str, dict[str, str]]:
        """Resolve the project's base currency and ``fx_rates`` map.

        Returns ``("", {})`` when no project / no fx rates are configured
        so callers can pass the result through ``_amount_in_base`` and
        treat every row as base currency (the legacy behaviour, but only
        when the data genuinely lacks currency info).
        """
        try:
            from app.modules.projects.repository import ProjectRepository

            proj = await ProjectRepository(self.session).get_by_id(project_id)
        except Exception:
            return "", {}

        if proj is None:
            return "", {}

        base = (getattr(proj, "currency", "") or "").strip().upper()
        raw = getattr(proj, "fx_rates", None)
        fx: dict[str, str] = {}
        if isinstance(raw, list):
            for entry in raw:
                if not isinstance(entry, dict):
                    continue
                code = str(entry.get("code") or "").strip().upper()
                rate = str(entry.get("rate") or "").strip()
                if code and rate:
                    fx[code] = rate
        return base, fx

    async def aggregate_by_project(self, project_id: uuid.UUID) -> dict[str, str]:
        """Aggregate budget line totals for a project, currency-aware.

        Pre-audit this used a raw SQL ``SUM(CAST(planned_amount AS Float))``
        which silently combined USD and EUR row totals into nonsense. We
        now load the rows in Python and convert every non-base line via
        the project's ``fx_rates`` (same convention as the BOQ resource
        rollup: ``stored_total * rate`` yields base-currency units).

        Missing FX rates degrade visibly: the foreign-currency value is
        kept as-is rather than zeroed, so a forgotten project-level rate
        surfaces as an obviously-wrong total instead of vanishing.

        Returns:
            Dict with keys ``total_planned``, ``total_committed``,
            ``total_actual``, ``total_forecast`` (string sums in the
            project base currency).
        """
        lines = await self._list_lines_for_rollup(project_id)
        base, fx = await self._project_fx_context(project_id)

        totals = {
            "planned": Decimal("0"),
            "committed": Decimal("0"),
            "actual": Decimal("0"),
            "forecast": Decimal("0"),
        }

        for line in lines:
            line_ccy = (line.currency or "").strip().upper()
            totals["planned"] += _amount_in_base(line.planned_amount, line_ccy, base, fx)
            totals["committed"] += _amount_in_base(line.committed_amount, line_ccy, base, fx)
            totals["actual"] += _amount_in_base(line.actual_amount, line_ccy, base, fx)
            totals["forecast"] += _amount_in_base(line.forecast_amount, line_ccy, base, fx)

        return {
            "total_planned": str(totals["planned"]),
            "total_committed": str(totals["committed"]),
            "total_actual": str(totals["actual"]),
            "total_forecast": str(totals["forecast"]),
        }

    async def aggregate_by_category(self, project_id: uuid.UUID) -> list[dict[str, str]]:
        """Aggregate budget lines grouped by category, currency-aware.

        Same conversion semantics as ``aggregate_by_project``: per-row
        ``currency`` is converted to the project base via ``fx_rates``
        before summing. See that method's docstring for the rationale.

        Returns:
            List of dicts with keys ``category``, ``planned``,
            ``committed``, ``actual``, ``forecast`` (string sums in the
            project base currency).
        """
        lines = await self._list_lines_for_rollup(project_id)
        base, fx = await self._project_fx_context(project_id)

        buckets: dict[str, dict[str, Decimal]] = {}
        for line in lines:
            cat = line.category or ""
            line_ccy = (line.currency or "").strip().upper()
            bucket = buckets.setdefault(
                cat,
                {
                    "planned": Decimal("0"),
                    "committed": Decimal("0"),
                    "actual": Decimal("0"),
                    "forecast": Decimal("0"),
                },
            )
            bucket["planned"] += _amount_in_base(line.planned_amount, line_ccy, base, fx)
            bucket["committed"] += _amount_in_base(line.committed_amount, line_ccy, base, fx)
            bucket["actual"] += _amount_in_base(line.actual_amount, line_ccy, base, fx)
            bucket["forecast"] += _amount_in_base(line.forecast_amount, line_ccy, base, fx)

        return [
            {
                "category": cat,
                "planned": str(bucket["planned"]),
                "committed": str(bucket["committed"]),
                "actual": str(bucket["actual"]),
                "forecast": str(bucket["forecast"]),
            }
            for cat, bucket in sorted(buckets.items())
        ]

    async def create(self, line: BudgetLine) -> BudgetLine:
        """Insert a new budget line."""
        self.session.add(line)
        await self.session.flush()
        return line

    async def bulk_create(self, lines: list[BudgetLine]) -> list[BudgetLine]:
        """Insert multiple budget lines at once."""
        self.session.add_all(lines)
        await self.session.flush()
        return lines

    async def existing_position_ids(self, project_id: uuid.UUID) -> set[uuid.UUID]:
        """Return the set of BOQ position IDs already wired to a budget line.

        Used by ``generate_budget_from_boq`` to make the auto-generation
        endpoint idempotent — re-running it must not silently double the
        BAC by re-creating lines for the same positions.
        """
        stmt = select(BudgetLine.boq_position_id).where(
            BudgetLine.project_id == project_id,
            BudgetLine.boq_position_id.is_not(None),
        )
        result = await self.session.execute(stmt)
        return {row for row in result.scalars().all() if row is not None}

    async def update_fields(self, line_id: uuid.UUID, **fields: object) -> None:
        """Update specific fields on a budget line."""
        stmt = update(BudgetLine).where(BudgetLine.id == line_id).values(**fields)
        await self.session.execute(stmt)
        await self.session.flush()
        # Expire cached ORM instances so the next get_by_id re-reads from DB
        self.session.expire_all()

    async def delete(self, line_id: uuid.UUID) -> None:
        """Delete a budget line."""
        stmt = delete(BudgetLine).where(BudgetLine.id == line_id)
        await self.session.execute(stmt)

    async def delete_for_project(self, project_id: uuid.UUID) -> int:
        """Delete all budget lines for a project. Returns deleted count."""
        count_stmt = select(func.count()).where(BudgetLine.project_id == project_id)
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = delete(BudgetLine).where(BudgetLine.project_id == project_id)
        await self.session.execute(stmt)
        return total


# ── CashFlow repository ─────────────────────────────────────────────────────


class CashFlowRepository:
    """Data access for CashFlow model."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, entry_id: uuid.UUID) -> CashFlow | None:
        """Get cash flow entry by ID."""
        return await self.session.get(CashFlow, entry_id)

    async def list_for_project(
        self,
        project_id: uuid.UUID,
        *,
        category: str | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> tuple[list[CashFlow], int]:
        """List cash flow entries for a project.

        Args:
            project_id: Target project.
            category: Optional category filter.
            offset: Pagination offset.
            limit: Pagination limit.

        Returns:
            Tuple of (entries, total_count).
        """
        base = select(CashFlow).where(CashFlow.project_id == project_id)

        if category is not None:
            base = base.where(CashFlow.category == category)

        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = base.order_by(CashFlow.period.asc()).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        entries = list(result.scalars().all())

        return entries, total

    async def create(self, entry: CashFlow) -> CashFlow:
        """Insert a new cash flow entry."""
        self.session.add(entry)
        await self.session.flush()
        return entry

    async def bulk_create(self, entries: list[CashFlow]) -> list[CashFlow]:
        """Insert multiple cash flow entries at once."""
        self.session.add_all(entries)
        await self.session.flush()
        return entries

    async def update_fields(self, entry_id: uuid.UUID, **fields: object) -> None:
        """Update specific fields on a cash flow entry."""
        stmt = update(CashFlow).where(CashFlow.id == entry_id).values(**fields)
        await self.session.execute(stmt)
        await self.session.flush()
        # Expire cached ORM instances so the next get_by_id re-reads from DB
        self.session.expire_all()

    async def delete(self, entry_id: uuid.UUID) -> None:
        """Delete a cash flow entry."""
        stmt = delete(CashFlow).where(CashFlow.id == entry_id)
        await self.session.execute(stmt)

    async def delete_for_project(self, project_id: uuid.UUID) -> int:
        """Delete all cash flow entries for a project. Returns deleted count."""
        count_stmt = select(func.count()).where(CashFlow.project_id == project_id)
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = delete(CashFlow).where(CashFlow.project_id == project_id)
        await self.session.execute(stmt)
        return total
