"""‌⁠‍Cost Intelligence service (v3.12.0 - Stream B).

Implements three small, independent services that share the same module:

* ``RegionalIndexService`` - region × category factor lookup; backs the
  RSMeans-style "what would this rate cost in city X?" workflow.
* ``CostCertaintyService`` - frequency + recency analysis on the per-item
  usage ledger; emits the green / yellow / red badge thresholds.
* ``CostUsageRecorder`` - append-only writer for the usage ledger,
  invoked from the BOQ apply-rate path.

All three are stateless wrappers around an ``AsyncSession`` so the
caller can keep ownership of the transaction.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Literal

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.costs.models import CostItem, CostItemUsage, RegionalIndex

logger = logging.getLogger(__name__)


# ── Certainty thresholds (single source of truth) ─────────────────────────


# These thresholds intentionally live here - not buried in the router -
# so the integration tests can import them directly when asserting
# boundary behaviour. Keep aligned with the docstring in
# ``schemas.CertaintyBadge``.
#
# Band meaning (revised so a single fresh use is never alarming red):
#   * green  - well proven: frequency >= 10 AND used within the last year.
#   * yellow - in use but not yet proven: at least one use and the most
#     recent use is no older than CERTAINTY_YELLOW_MAX_AGE_DAYS.
#   * red    - either never used (frequency 0) or the last use is older
#     than CERTAINTY_YELLOW_MAX_AGE_DAYS (stale evidence).

CERTAINTY_GREEN_MIN_FREQUENCY = 10
CERTAINTY_GREEN_MAX_AGE_DAYS = 365
# Any non-zero frequency reaches at least yellow, so there is no separate
# yellow frequency floor any more. The only thing that pushes a used item
# back to red is stale evidence (age above the max below).
CERTAINTY_YELLOW_MAX_AGE_DAYS = 1095  # ≈ 3 years
# Sentinel age used when a row has never been logged - keeps the badge
# JSON-clean (no nulls in the numeric field) and slots into the red
# bucket via the threshold logic.
NEVER_USED_AGE_DAYS = 999_999


CertaintyBand = Literal["green", "yellow", "red"]


def classify_certainty(frequency: int, age_days: int) -> CertaintyBand:
    """‌⁠‍Map (frequency, age_days) onto a green / yellow / red band.

    Pure function - exposed so the integration tests can pin the
    boundary behaviour without going through the DB. Matches the
    contract documented on ``CertaintyBadge``.

    Contract:
        * ``red`` - the only alarming state: the item was never used
          (``frequency == 0``) or the last use is stale (older than
          ``CERTAINTY_YELLOW_MAX_AGE_DAYS``). A single fresh use is never
          red.
        * ``green`` - well proven: ``frequency >= 10`` and used within the
          last year (``age_days < CERTAINTY_GREEN_MAX_AGE_DAYS``).
        * ``yellow`` - everything in between: at least one use whose most
          recent occurrence is no older than
          ``CERTAINTY_YELLOW_MAX_AGE_DAYS``.

    Args:
        frequency: Total recorded uses (``>= 0``).
        age_days: Days since the most recent use, or
            ``NEVER_USED_AGE_DAYS`` when the item has never been used.

    Returns:
        ``"green"`` / ``"yellow"`` / ``"red"``.
    """
    # Never used, or evidence too old to trust - the only red cases.
    if frequency <= 0 or age_days > CERTAINTY_YELLOW_MAX_AGE_DAYS:
        return "red"
    # Well proven: high frequency and a recent use.
    if frequency >= CERTAINTY_GREEN_MIN_FREQUENCY and age_days < CERTAINTY_GREEN_MAX_AGE_DAYS:
        return "green"
    # In use but not yet proven (any non-stale use) - reassuring, not alarming.
    return "yellow"


# ── Regional index lookup ─────────────────────────────────────────────────


class RegionalIndexService:
    """‌⁠‍Region × category cost-factor lookup."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    @staticmethod
    def _norm(value: str | None) -> str:
        return (value or "").strip().upper()

    async def list_for_region(self, region_code: str) -> list[RegionalIndex]:
        """Return every index row for ``region_code`` (most recent first)."""
        norm = self._norm(region_code)
        if not norm:
            return []
        stmt = (
            select(RegionalIndex)
            .where(func.upper(RegionalIndex.region_code) == norm)
            .order_by(
                RegionalIndex.category.asc(),
                RegionalIndex.subcategory.asc().nullsfirst(),
                desc(RegionalIndex.effective_date),
            )
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def latest_for_region_category(
        self,
        region_code: str,
        category: str,
        *,
        subcategory: str | None = None,
        as_of: date | None = None,
    ) -> RegionalIndex | None:
        """Return the most recent index row for (region, category[, sub]).

        ``as_of`` defaults to today. When ``subcategory`` is None the
        whole-category row is returned; when supplied, the subcategory
        row wins only if one exists, otherwise we fall back to the
        whole-category row (so callers don't need to know which
        granularity the catalogue has data at).
        """
        norm_region = self._norm(region_code)
        norm_cat = (category or "").strip().lower()
        if not norm_region or not norm_cat:
            return None
        cutoff = as_of or datetime.now(UTC).date()

        async def _query(sub: str | None) -> RegionalIndex | None:
            stmt = (
                select(RegionalIndex)
                .where(
                    func.upper(RegionalIndex.region_code) == norm_region,
                    func.lower(RegionalIndex.category) == norm_cat,
                    RegionalIndex.effective_date <= cutoff,
                )
                .order_by(desc(RegionalIndex.effective_date))
                .limit(1)
            )
            if sub is None:
                stmt = stmt.where(RegionalIndex.subcategory.is_(None))
            else:
                stmt = stmt.where(RegionalIndex.subcategory == sub)
            res = await self.session.execute(stmt)
            return res.scalar_one_or_none()

        if subcategory:
            sub_row = await _query(subcategory.strip().lower())
            if sub_row is not None:
                return sub_row
        return await _query(None)

    async def adjust(
        self,
        region_code: str,
        category: str,
        base_rate: Decimal | float | str,
        *,
        subcategory: str | None = None,
    ) -> tuple[Decimal, Decimal, str, date | None]:
        """Compute ``(adjusted_rate, factor, source, effective_date)``.

        When no index row matches, the factor is ``Decimal("1")`` and the
        source is ``"baseline"`` - the caller's frontend renders the
        same shape either way.

        Round-7: returns ``Decimal`` so the multiply is exact (no float
        intermediates). Pydantic schemas serialise to strings on the wire.
        """
        base = base_rate if isinstance(base_rate, Decimal) else Decimal(str(base_rate))
        if base < 0:
            base = Decimal("0")
        row = await self.latest_for_region_category(region_code, category, subcategory=subcategory)
        if row is None:
            return base, Decimal("1"), "baseline", None
        factor: Decimal = row.factor if isinstance(row.factor, Decimal) else Decimal(str(row.factor))
        # Guard against an absurd 0-or-negative factor leaking from a
        # bad seed; the badge UI assumes ``factor > 0``.
        if factor <= 0:
            factor = Decimal("1")
        # Quantise to 4 decimal places - matches the legacy round(..., 4).
        adjusted = (base * factor).quantize(Decimal("0.0001"))
        return adjusted, factor, row.source or "baseline", row.effective_date


# ── Cost item usage ───────────────────────────────────────────────────────


class CostUsageRecorder:
    """‌⁠‍Append-only writer for the per-item usage ledger."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def record(
        self,
        cost_item_id: uuid.UUID,
        *,
        project_id: uuid.UUID,
        unit_rate_at_use: Decimal | float | str,
        context: str = "boq",
        used_by: uuid.UUID | None = None,
    ) -> CostItemUsage:
        """Insert a usage row. Caller owns the commit.

        Accepts ``Decimal`` (Round-7 preferred), ``float`` (legacy callers
        still in flight), or numeric strings - all coerced to ``Decimal``
        via the ``str()`` round-trip so float imprecision never leaks into
        the persisted ledger entry.
        """
        amount = unit_rate_at_use if isinstance(unit_rate_at_use, Decimal) else Decimal(str(unit_rate_at_use))
        row = CostItemUsage(
            cost_item_id=cost_item_id,
            project_id=project_id,
            unit_rate_at_use=amount,
            context=context,
            used_by=used_by,
        )
        self.session.add(row)
        await self.session.flush()
        return row


class CostCertaintyService:
    """‌⁠‍Frequency + recency analysis backing the certainty badge."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def compute(self, cost_item_id: uuid.UUID) -> dict[str, object]:
        """Return a dict matching ``schemas.CertaintyBadge``.

        Raises:
            LookupError: when the cost item id is unknown - the router
                maps this to a 404 so callers can distinguish "rate
                with zero usage" (frequency=0, red badge) from "no
                such rate".
        """
        # Validate parent exists so we can populate ``source``.
        item_stmt = select(CostItem).where(CostItem.id == cost_item_id)
        item = (await self.session.execute(item_stmt)).scalar_one_or_none()
        if item is None:
            raise LookupError(f"CostItem {cost_item_id!s} not found")

        freq_stmt = select(func.count(CostItemUsage.id)).where(CostItemUsage.cost_item_id == cost_item_id)
        last_stmt = select(func.max(CostItemUsage.used_at)).where(CostItemUsage.cost_item_id == cost_item_id)
        frequency = int((await self.session.execute(freq_stmt)).scalar_one() or 0)
        last_used = (await self.session.execute(last_stmt)).scalar_one_or_none()

        if last_used is None:
            age_days = NEVER_USED_AGE_DAYS
            last_used_iso: datetime | None = None
        else:
            # SQLite hands back naive datetimes; PostgreSQL hands back
            # aware ones. Normalise to UTC-aware so the diff math is
            # consistent across backends.
            if last_used.tzinfo is None:
                last_used = last_used.replace(tzinfo=UTC)
            now = datetime.now(UTC)
            delta = now - last_used
            age_days = max(0, int(delta.total_seconds() // 86400))
            last_used_iso = last_used

        band = classify_certainty(frequency, age_days)
        return {
            "cost_item_id": cost_item_id,
            "frequency": frequency,
            "age_days": age_days,
            "source": item.source or "manual",
            "confidence_badge": band,
            "last_used_at": last_used_iso,
        }
