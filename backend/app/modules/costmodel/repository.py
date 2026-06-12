"""‌⁠‍5D Cost Model data access layer.

All database queries for cost snapshots, budget lines, and cash flow entries
live here.  No business logic - pure data access - *except* for the
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

from app.modules.costmodel.models import (
    BudgetLine,
    CashFlow,
    ControlAccount,
    CostLine,
    CostSnapshot,
)

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
      remains deterministic - flapping silent zeroes were the worst
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
        # No FX rate configured - keep in its own units rather than zero.
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
        real snapshot - otherwise the dashboard SPI/CPI flips to scenario
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
        """Return every budget line for ``project_id`` - used by the
        currency-aware aggregators below. Extracted into its own method
        so unit tests can stub it without monkey-patching SQLAlchemy.
        """
        stmt = select(BudgetLine).where(BudgetLine.project_id == project_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def distinct_currencies(self, project_id: uuid.UUID) -> set[str]:
        """Return the distinct non-blank ISO currency codes on a project's budget lines.

        The dashboard uses this to decide whether summing across budget lines
        is safe (a single currency) or whether to raise the ``mixed_currency``
        flag (multiple currencies, which may have crossed a missing fx_rate
        during conversion). Reuses ``_list_lines_for_rollup`` so the data
        access stays in the repository and unit tests can stub it without
        monkey-patching SQLAlchemy. Blank/None currencies are treated as
        legacy base-currency rows and ignored.
        """
        lines = await self._list_lines_for_rollup(project_id)
        return {
            (getattr(line, "currency", "") or "").strip().upper()
            for line in lines
            if (getattr(line, "currency", "") or "").strip()
        }

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

    async def find_for_actual_posting(
        self,
        project_id: uuid.UUID,
        *,
        cost_line_id: uuid.UUID | None,
        category: str | None,
    ) -> BudgetLine | None:
        """Find the single budget line that an actual-cost posting targets.

        Used by ``CostSpineService.post_actual_to_budget_line`` to locate (or
        decide to create) the row that accumulates ``actual_amount`` for a
        given ``(project_id, cost_line_id, cost_category)`` triple. The
        ``category`` column is NOT NULL (default ``""``), so a ``None`` /
        uncategorised posting is matched against the empty-string sentinel
        rather than SQL NULL - a headerless invoice posting therefore lands on
        one stable "uncategorised" row instead of fanning out new rows.
        ``cost_line_id`` is genuinely nullable and matched with ``IS NULL``.

        When several rows somehow share the triple (legacy data) the oldest by
        ``created_at`` wins so repeated postings stay deterministic and land on
        the same row.
        """
        stmt = select(BudgetLine).where(
            BudgetLine.project_id == project_id,
            BudgetLine.category == (category or ""),
        )
        if cost_line_id is None:
            stmt = stmt.where(BudgetLine.cost_line_id.is_(None))
        else:
            stmt = stmt.where(BudgetLine.cost_line_id == cost_line_id)
        stmt = stmt.order_by(BudgetLine.created_at.asc()).limit(1)
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def get_by_position(
        self,
        project_id: uuid.UUID,
        boq_position_id: uuid.UUID,
    ) -> BudgetLine | None:
        """Return the budget line wired to a BOQ position, if any.

        Used by the progress -> earned-value bridge to find the row that
        carries ``earned_amount`` for a position. When several rows somehow
        share the position (legacy data) the oldest by ``created_at`` wins so
        repeated progress recordings stay deterministic and land on the same
        row (mirrors :meth:`find_for_actual_posting`).

        Args:
            project_id: Project the budget line belongs to.
            boq_position_id: BOQ position the line is wired to.

        Returns:
            The matching budget line, or ``None`` when the position has no
            budget line yet (budget may not have been generated).
        """
        stmt = (
            select(BudgetLine)
            .where(
                BudgetLine.project_id == project_id,
                BudgetLine.boq_position_id == boq_position_id,
            )
            .order_by(BudgetLine.created_at.asc())
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def existing_position_ids(self, project_id: uuid.UUID) -> set[uuid.UUID]:
        """Return the set of BOQ position IDs already wired to a budget line.

        Used by ``generate_budget_from_boq`` to make the auto-generation
        endpoint idempotent - re-running it must not silently double the
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


# ── Cost Spine repositories (v6.4) ────────────────────────────────────────────


class ControlAccountRepository:
    """Data access for ControlAccount (Cost Breakdown Structure tree)."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, account_id: uuid.UUID) -> ControlAccount | None:
        """Get a control account by ID."""
        return await self.session.get(ControlAccount, account_id)

    async def list_for_project(self, project_id: uuid.UUID) -> list[ControlAccount]:
        """Return every control account for a project, tree-ordered.

        Ordered depth-first by ``(sort_order, code)`` within each parent so a
        flat list renders as a stable indented tree without a second pass.
        """
        stmt = select(ControlAccount).where(ControlAccount.project_id == project_id)
        result = await self.session.execute(stmt)
        accounts = list(result.scalars().all())

        # Build a parent -> children map then walk depth-first. Doing the
        # ordering in Python (rather than a recursive CTE) keeps this
        # identical on SQLite and PostgreSQL.
        children: dict[uuid.UUID | None, list[ControlAccount]] = {}
        for acct in accounts:
            children.setdefault(acct.parent_id, []).append(acct)
        for bucket in children.values():
            bucket.sort(key=lambda a: (a.sort_order, a.code))

        ordered: list[ControlAccount] = []

        def _walk(parent_key: uuid.UUID | None) -> None:
            for child in children.get(parent_key, []):
                ordered.append(child)
                _walk(child.id)

        # Roots are nodes whose parent is None OR whose parent is not in this
        # project (orphan after a SET NULL); start from None, then sweep any
        # accounts not yet emitted so nothing is silently dropped.
        _walk(None)
        if len(ordered) != len(accounts):
            seen = {a.id for a in ordered}
            for acct in sorted(accounts, key=lambda a: (a.sort_order, a.code)):
                if acct.id not in seen:
                    ordered.append(acct)
        return ordered

    async def get_by_project_code(self, project_id: uuid.UUID, code: str) -> ControlAccount | None:
        """Look up a control account by its project-unique code."""
        stmt = (
            select(ControlAccount)
            .where(
                ControlAccount.project_id == project_id,
                ControlAccount.code == code,
            )
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def create(self, account: ControlAccount) -> ControlAccount:
        """Insert a new control account."""
        self.session.add(account)
        await self.session.flush()
        return account

    async def update_fields(self, account_id: uuid.UUID, **fields: object) -> None:
        """Update specific fields on a control account."""
        stmt = update(ControlAccount).where(ControlAccount.id == account_id).values(**fields)
        await self.session.execute(stmt)
        await self.session.flush()
        self.session.expire_all()

    async def delete(self, account_id: uuid.UUID) -> None:
        """Delete a control account."""
        stmt = delete(ControlAccount).where(ControlAccount.id == account_id)
        await self.session.execute(stmt)

    async def count_lines_referencing(self, account_id: uuid.UUID) -> int:
        """Count cost lines pointing at this control account.

        Used to block deletion (409) while lines still reference the account.
        """
        stmt = select(func.count()).where(CostLine.control_account_id == account_id)
        return (await self.session.execute(stmt)).scalar_one()


class CostLineRepository:
    """Data access for CostLine (the canonical scope item)."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, line_id: uuid.UUID) -> CostLine | None:
        """Get a cost line by ID."""
        return await self.session.get(CostLine, line_id)

    async def list_for_project(
        self,
        project_id: uuid.UUID,
        *,
        control_account_id: uuid.UUID | None = None,
        status: str | None = None,
        offset: int = 0,
        limit: int = 200,
    ) -> tuple[list[CostLine], int]:
        """List cost lines for a project with optional account/status filters.

        Returns a ``(lines, total_count)`` tuple where ``total_count`` reflects
        the filter set, not the page.
        """
        base = select(CostLine).where(CostLine.project_id == project_id)
        if control_account_id is not None:
            base = base.where(CostLine.control_account_id == control_account_id)
        if status is not None:
            base = base.where(CostLine.status == status)

        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = base.order_by(CostLine.code, CostLine.created_at).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        lines = list(result.scalars().all())
        return lines, total

    async def get_by_project_code(self, project_id: uuid.UUID, code: str) -> CostLine | None:
        """Look up a cost line by its project-unique code."""
        stmt = (
            select(CostLine)
            .where(
                CostLine.project_id == project_id,
                CostLine.code == code,
            )
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def list_by_boq(self, project_id: uuid.UUID, boq_id: uuid.UUID) -> list[CostLine]:
        """Return every cost line generated from a given BOQ."""
        stmt = select(CostLine).where(
            CostLine.project_id == project_id,
            CostLine.boq_id == boq_id,
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def existing_by_boq_position(self, project_id: uuid.UUID) -> dict[str, CostLine]:
        """Map ``str(boq_position_id) -> CostLine`` for the project's BOQ-sourced lines.

        Only rows whose ``boq_position_id`` is set are returned, keyed by the
        position id as a string. This is the stable dedup index used by
        ``generate_from_boq``: the originating BOQ position is the true
        invariant (exactly one cost line per position in a project), whereas a
        line's ``code`` is a random ``CL-XXXX`` when the position has no
        ``reference_code`` and therefore cannot be matched across runs.

        One query, no N+1. When two rows somehow share a position id (should be
        impossible given the per-position invariant) the lowest ``code`` wins so
        the result stays deterministic.
        """
        stmt = select(CostLine).where(
            CostLine.project_id == project_id,
            CostLine.boq_position_id.is_not(None),
        )
        result = await self.session.execute(stmt)
        out: dict[str, CostLine] = {}
        for line in result.scalars().all():
            key = str(line.boq_position_id)
            existing = out.get(key)
            if existing is None or line.code < existing.code:
                out[key] = line
        return out

    async def create(self, line: CostLine) -> CostLine:
        """Insert a new cost line."""
        self.session.add(line)
        await self.session.flush()
        return line

    async def bulk_create(self, lines: list[CostLine]) -> list[CostLine]:
        """Insert multiple cost lines at once."""
        self.session.add_all(lines)
        await self.session.flush()
        return lines

    async def update_fields(self, line_id: uuid.UUID, **fields: object) -> None:
        """Update specific fields on a cost line."""
        stmt = update(CostLine).where(CostLine.id == line_id).values(**fields)
        await self.session.execute(stmt)
        await self.session.flush()
        self.session.expire_all()

    async def delete(self, line_id: uuid.UUID) -> None:
        """Delete a cost line."""
        stmt = delete(CostLine).where(CostLine.id == line_id)
        await self.session.execute(stmt)


class CostSpineRepository:
    """Currency-aware grouped aggregates for the Cost Spine rollup.

    Every aggregate is computed from ONE grouped/scanned query per source and
    converted to the project base currency in Python (the FX conversion is
    per-row because a forgotten rate must surface visibly rather than zero out,
    matching ``BudgetLineRepository``). The result is keyed by cost-line id so
    the service can assemble a per-line and project-wide rollup without N+1.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        # ``_project_fx_context`` lives on BudgetLineRepository; hold an
        # instance and reuse it so FX semantics stay in one place.
        self._budget_repo = BudgetLineRepository(session)

    async def _fx_context(self, project_id: uuid.UUID) -> tuple[str, dict[str, str]]:
        return await self._budget_repo._project_fx_context(project_id)

    async def budget_aggregate_by_cost_line(self, project_id: uuid.UUID) -> dict[str, dict[str, Decimal]]:
        """Planned / committed / actual per cost line, FX-converted.

        One scan of the project's budget lines (only those carrying a
        ``cost_line_id``); converted via ``_amount_in_base`` and the project
        fx context, then summed in Python keyed by cost-line id string.
        """
        base, fx = await self._fx_context(project_id)
        stmt = select(
            BudgetLine.cost_line_id,
            BudgetLine.planned_amount,
            BudgetLine.committed_amount,
            BudgetLine.actual_amount,
            BudgetLine.currency,
        ).where(
            BudgetLine.project_id == project_id,
            BudgetLine.cost_line_id.is_not(None),
        )
        result = await self.session.execute(stmt)

        out: dict[str, dict[str, Decimal]] = {}
        for cost_line_id, planned, committed, actual, currency in result.all():
            key = str(cost_line_id)
            line_ccy = (currency or "").strip().upper()
            bucket = out.setdefault(
                key,
                {"planned": Decimal("0"), "committed": Decimal("0"), "actual": Decimal("0")},
            )
            bucket["planned"] += _amount_in_base(planned, line_ccy, base, fx)
            bucket["committed"] += _amount_in_base(committed, line_ccy, base, fx)
            bucket["actual"] += _amount_in_base(actual, line_ccy, base, fx)
        return out

    async def po_committed_by_cost_line(self, project_id: uuid.UUID) -> dict[str, Decimal]:
        """Committed PO value per cost line, FX-converted by PO currency.

        Joins ``PurchaseOrderItem`` to its parent ``PurchaseOrder`` (one query)
        and counts only POs whose status is genuinely committed
        (issued / partially_received / completed). Each item amount is
        converted using the PARENT PO currency, since the item carries no
        currency of its own.
        """
        from app.modules.procurement.models import PurchaseOrder, PurchaseOrderItem

        base, fx = await self._fx_context(project_id)
        committed_statuses = ("issued", "partially_received", "completed")
        stmt = (
            select(
                PurchaseOrderItem.cost_line_id,
                PurchaseOrderItem.amount,
                PurchaseOrder.currency_code,
            )
            .join(PurchaseOrder, PurchaseOrder.id == PurchaseOrderItem.po_id)
            .where(
                PurchaseOrder.project_id == project_id,
                PurchaseOrder.status.in_(committed_statuses),
                PurchaseOrderItem.cost_line_id.is_not(None),
            )
        )
        result = await self.session.execute(stmt)

        out: dict[str, Decimal] = {}
        for cost_line_id, amount, po_currency in result.all():
            key = str(cost_line_id)
            po_ccy = (po_currency or "").strip().upper()
            out[key] = out.get(key, Decimal("0")) + _amount_in_base(amount, po_ccy, base, fx)
        return out

    async def contract_value_by_cost_line(self, project_id: uuid.UUID) -> dict[str, Decimal]:
        """Contracted SoV value per cost line, FX-converted by contract currency.

        Joins ``ContractLine`` to its parent ``Contract`` (one query). Contract
        money is ``Numeric`` (Decimal), so each ``total_value`` is coerced to a
        string before passing through ``_amount_in_base`` (which expects the
        stored money-string convention). Contract currency is upper-normalized.
        """
        from app.modules.contracts.models import Contract, ContractLine

        base, fx = await self._fx_context(project_id)
        stmt = (
            select(
                ContractLine.cost_line_id,
                ContractLine.total_value,
                Contract.currency,
            )
            .join(Contract, Contract.id == ContractLine.contract_id)
            .where(
                Contract.project_id == project_id,
                ContractLine.cost_line_id.is_not(None),
            )
        )
        result = await self.session.execute(stmt)

        out: dict[str, Decimal] = {}
        for cost_line_id, total_value, contract_currency in result.all():
            key = str(cost_line_id)
            ccy = (contract_currency or "").strip().upper()
            raw = str(total_value) if total_value is not None else "0"
            out[key] = out.get(key, Decimal("0")) + _amount_in_base(raw, ccy, base, fx)
        return out

    async def claimed_to_date_by_cost_line(self, project_id: uuid.UUID) -> dict[str, Decimal]:
        """Cumulative claimed value per cost line, FX-converted.

        For each contract line linked to a cost line, takes the latest progress
        claim line's ``cumulative_completed_value`` (the running total already
        nets prior claims). Joined in one query: ProgressClaimLine ->
        ContractLine -> Contract, plus ProgressClaim for the parent currency.
        Numeric money is coerced to string before conversion.
        """
        from app.modules.contracts.models import (
            Contract,
            ContractLine,
            ProgressClaim,
            ProgressClaimLine,
        )

        base, fx = await self._fx_context(project_id)
        stmt = (
            select(
                ContractLine.cost_line_id,
                ProgressClaimLine.cumulative_completed_value,
                ProgressClaim.currency,
                ProgressClaimLine.contract_line_id,
                ProgressClaim.claim_number,
            )
            .join(ContractLine, ContractLine.id == ProgressClaimLine.contract_line_id)
            .join(Contract, Contract.id == ContractLine.contract_id)
            .join(ProgressClaim, ProgressClaim.id == ProgressClaimLine.progress_claim_id)
            .where(
                Contract.project_id == project_id,
                ContractLine.cost_line_id.is_not(None),
            )
        )
        result = await self.session.execute(stmt)

        # cumulative_completed_value already running-totals prior claims, so
        # per (cost_line, contract_line) we keep the MAX cumulative seen and
        # sum those maxima across contract lines that share a cost line. This
        # avoids double-counting earlier interim claims for the same SoV line.
        per_line_max: dict[tuple[str, str], tuple[Decimal, str]] = {}
        for cost_line_id, cumulative, claim_ccy, contract_line_id, _claim_no in result.all():
            cost_key = str(cost_line_id)
            cl_key = str(contract_line_id)
            ccy = (claim_ccy or "").strip().upper()
            raw = str(cumulative) if cumulative is not None else "0"
            value = _amount_in_base(raw, ccy, base, fx)
            existing = per_line_max.get((cost_key, cl_key))
            if existing is None or value > existing[0]:
                per_line_max[(cost_key, cl_key)] = (value, ccy)

        out: dict[str, Decimal] = {}
        for (cost_key, _cl_key), (value, _ccy) in per_line_max.items():
            out[cost_key] = out.get(cost_key, Decimal("0")) + value
        return out
