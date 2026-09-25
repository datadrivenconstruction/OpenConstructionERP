# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data access for the FX register.

Every function here is pure persistence: no HTTP, no rate arithmetic, no
policy decisions. That separation is what lets the conversion maths be tested
without a database and the storage rules be tested without the network.

Two behaviours are worth knowing:

* Writes ``flush()`` and never ``commit()``. The transaction boundary belongs
  to the caller - a service that refreshes rate sets and the legacy cache
  together must be able to fail as one unit.
* A locked rate set is refused, not silently rewritten. Locking is the promise
  a pinned project relies on, so breaking it has to be an error the caller
  sees, not a value that quietly changed underneath an estimate.

Reads use ``select()`` with explicit predicates rather than ``session.get()``,
which answers from the identity map and can hand back a row another statement
in the same session already deleted.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.fx.models import (
    FxPolicy,
    FxRate,
    FxRateQuote,
    FxRateSet,
    PppFactor,
)

#: Quotes are stored as ``Numeric(20, 10)``; quantize on write so a value the
#: caller built at higher precision is rounded once, here, rather than by the
#: driver in a way that differs between PostgreSQL and an in-process test.
_QUOTE_EXPONENT = Decimal("0.0000000001")

#: Legacy cache column is ``Numeric(18, 6)``.
_LEGACY_EXPONENT = Decimal("0.000001")


class RateSetLockedError(RuntimeError):
    """Raised when a write would modify a rate set that has been locked.

    A locked set backs pinned project estimates, so rewriting it would change
    figures that have already been signed off. Callers translate this to a
    conflict rather than retrying.
    """

    def __init__(self, message: str, *, rate_date: date | None = None) -> None:
        super().__init__(message)
        self.rate_date = rate_date


def _q_quote(value: Decimal) -> Decimal:
    """Round a quoted rate to the stored scale (10 dp, half up)."""
    return value.quantize(_QUOTE_EXPONENT, rounding=ROUND_HALF_UP)


def _q_legacy(value: Decimal) -> Decimal:
    """Round a legacy-cache rate to its stored scale (6 dp, half up)."""
    return value.quantize(_LEGACY_EXPONENT, rounding=ROUND_HALF_UP)


# ── Rate sets ────────────────────────────────────────────────────────────────


async def get_rate_set(session: AsyncSession, rate_set_id: uuid.UUID) -> FxRateSet | None:
    """Fetch one rate set with its quotes, or ``None``.

    Args:
        session: Active async session.
        rate_set_id: Primary key of the set.

    Returns:
        The set with ``quotes`` populated, or ``None`` when no such set exists.
    """
    stmt = select(FxRateSet).where(FxRateSet.id == rate_set_id)
    return (await session.execute(stmt)).scalar_one_or_none()


async def list_rate_sets(
    session: AsyncSession,
    *,
    base_currency: str | None = None,
    source: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> Sequence[FxRateSet]:
    """List rate sets newest first.

    Args:
        session: Active async session.
        base_currency: Restrict to sets quoted against this base.
        source: Restrict to one provenance (``ecb`` / ``seed`` / ``manual``).
        limit: Maximum number of sets to return.
        offset: Number of sets to skip.

    Returns:
        Rate sets ordered by effective date descending, then capture time.
    """
    stmt = select(FxRateSet).order_by(FxRateSet.rate_date.desc(), FxRateSet.fetched_at.desc())
    if base_currency:
        stmt = stmt.where(FxRateSet.base_currency == base_currency.upper())
    if source:
        stmt = stmt.where(FxRateSet.source == source)
    stmt = stmt.limit(limit).offset(offset)
    return (await session.execute(stmt)).scalars().all()


async def count_rate_sets(
    session: AsyncSession,
    *,
    base_currency: str | None = None,
    source: str | None = None,
) -> int:
    """Count rate sets matching the same filters as :func:`list_rate_sets`."""
    stmt = select(func.count()).select_from(FxRateSet)
    if base_currency:
        stmt = stmt.where(FxRateSet.base_currency == base_currency.upper())
    if source:
        stmt = stmt.where(FxRateSet.source == source)
    return int((await session.execute(stmt)).scalar_one())


async def latest_rate_set(
    session: AsyncSession,
    *,
    base_currency: str = "EUR",
    on_date: date | None = None,
    source: str | None = None,
) -> FxRateSet | None:
    """The rate set that applies on a date: newest set effective on or before it.

    This is the point-in-time lookup the register exists for. A rate published
    on Friday still applies over the weekend, so the answer is the most recent
    set not *after* the requested date rather than an exact date match.

    Args:
        session: Active async session.
        base_currency: Base the set must be quoted against.
        on_date: Date the rate must be valid on; ``None`` means "latest known".
        source: Restrict to one provenance, e.g. only hand-entered sets.

    Returns:
        The applicable set with its quotes, or ``None`` if none is on file.
    """
    stmt = select(FxRateSet).where(FxRateSet.base_currency == base_currency.upper())
    if on_date is not None:
        stmt = stmt.where(FxRateSet.rate_date <= on_date)
    if source:
        stmt = stmt.where(FxRateSet.source == source)
    stmt = stmt.order_by(FxRateSet.rate_date.desc(), FxRateSet.fetched_at.desc()).limit(1)
    return (await session.execute(stmt)).scalars().first()


async def preceding_rate_set(session: AsyncSession, rate_set: FxRateSet) -> FxRateSet | None:
    """The set immediately before ``rate_set`` for the same base and source.

    Used to compare a freshly ingested set against the one it supersedes, which
    is how a mistyped or corrupted feed value is caught before it reprices an
    estimate.
    """
    stmt = (
        select(FxRateSet)
        .where(
            FxRateSet.base_currency == rate_set.base_currency,
            FxRateSet.source == rate_set.source,
            FxRateSet.rate_date < rate_set.rate_date,
        )
        .order_by(FxRateSet.rate_date.desc(), FxRateSet.fetched_at.desc())
        .limit(1)
    )
    return (await session.execute(stmt)).scalars().first()


async def upsert_rate_set(
    session: AsyncSession,
    *,
    base_currency: str,
    rate_date: date,
    source: str,
    rates: Mapping[str, Decimal],
    source_ref: str = "",
    note: str = "",
    fetched_at: datetime | None = None,
    lock: bool = False,
) -> FxRateSet:
    """Create or replace the rate set for ``(base_currency, rate_date, source)``.

    Re-ingesting the same feed for the same day replaces the quotes rather than
    appending a second set, so a retried refresh is idempotent. A quote for the
    base currency itself is dropped: the base is implicit at 1, and storing it
    would let a corrupt feed introduce a base-against-itself rate other than 1.

    Args:
        session: Active async session.
        base_currency: ISO 4217 base the rates are quoted against.
        rate_date: Date the rates are effective for.
        source: Provenance key (``ecb`` / ``seed`` / ``manual``).
        rates: Currency code to units-per-base.
        source_ref: Feed URL or document reference the figures were read from.
        note: Free-text remark stored on the set.
        fetched_at: Capture timestamp; defaults to the model's own default.
        lock: Lock the set against later modification.

    Returns:
        The created or updated set, flushed, with its quotes attached.

    Raises:
        RateSetLockedError: If an existing set for this key is locked.
    """
    base = base_currency.upper()
    stmt = select(FxRateSet).where(
        FxRateSet.base_currency == base,
        FxRateSet.rate_date == rate_date,
        FxRateSet.source == source,
    )
    rate_set = (await session.execute(stmt)).scalar_one_or_none()

    if rate_set is None:
        rate_set = FxRateSet(base_currency=base, rate_date=rate_date, source=source)
        session.add(rate_set)
    elif rate_set.is_locked:
        raise RateSetLockedError(
            f"Rate set {base} {rate_date.isoformat()} from {source} is locked and cannot be rewritten",
            rate_date=rate_date,
        )

    rate_set.source_ref = source_ref
    rate_set.note = note
    if fetched_at is not None:
        rate_set.fetched_at = fetched_at
    if lock:
        rate_set.is_locked = True

    quotes: list[FxRateQuote] = []
    for code, value in rates.items():
        currency = str(code).upper()
        if currency == base or len(currency) != 3 or not currency.isalpha():
            continue
        if value <= 0:
            continue
        quotes.append(FxRateQuote(currency=currency, rate=_q_quote(value)))
    # Retire the superseded quotes in their own flush. Swapping the collection
    # in one step makes SQLAlchemy insert the replacements before it deletes the
    # rows they collide with, and the unique constraint on
    # (rate_set_id, currency) rejects the whole batch. Emptying first also lets
    # ``delete-orphan`` drop the currencies the new publication no longer
    # carries, rather than leaving stale quotes behind.
    if rate_set.quotes:
        rate_set.quotes = []
        await session.flush()
    rate_set.quotes = quotes

    await session.flush()
    return rate_set


async def set_rate_set_locked(session: AsyncSession, rate_set: FxRateSet, *, locked: bool) -> FxRateSet:
    """Lock or unlock a rate set and flush the change."""
    rate_set.is_locked = locked
    await session.flush()
    return rate_set


async def delete_rate_set(session: AsyncSession, rate_set: FxRateSet) -> None:
    """Delete a rate set and its quotes.

    Raises:
        RateSetLockedError: If the set is locked; unlock it deliberately first.
    """
    if rate_set.is_locked:
        raise RateSetLockedError(
            f"Rate set {rate_set.base_currency} {rate_set.rate_date.isoformat()} "
            f"from {rate_set.source} is locked and cannot be deleted"
        )
    await session.delete(rate_set)
    await session.flush()


def quotes_as_map(rate_set: FxRateSet) -> dict[str, Decimal]:
    """The set's quotes as a ``{currency: units-per-base}`` dict.

    Reads the already-loaded ``quotes`` collection (``selectin``), so this stays
    a pure function and emits no SQL.
    """
    return {quote.currency.upper(): Decimal(quote.rate) for quote in rate_set.quotes}


# ── Project policy ───────────────────────────────────────────────────────────


async def get_policy(
    session: AsyncSession,
    project_id: uuid.UUID,
    *,
    with_pinned_set: bool = False,
) -> FxPolicy | None:
    """Fetch a project's FX policy, or ``None``.

    Args:
        session: Active async session.
        project_id: Project the policy belongs to.
        with_pinned_set: Eagerly load ``pinned_rate_set`` (and its quotes).
            The relationship is ``raise_on_sql``, so a caller that intends to
            read the pinned set must ask for it here.

    Returns:
        The policy, or ``None`` when the project has not configured one.
    """
    stmt = select(FxPolicy).where(FxPolicy.project_id == project_id)
    if with_pinned_set:
        stmt = stmt.options(selectinload(FxPolicy.pinned_rate_set))
    return (await session.execute(stmt)).scalar_one_or_none()


async def list_policies(session: AsyncSession, *, limit: int = 50, offset: int = 0) -> Sequence[FxPolicy]:
    """List configured project policies, newest first."""
    stmt = select(FxPolicy).order_by(FxPolicy.created_at.desc()).limit(limit).offset(offset)
    return (await session.execute(stmt)).scalars().all()


async def upsert_policy(
    session: AsyncSession,
    project_id: uuid.UUID,
    *,
    estimating_currency: str,
    procurement_currency: str,
    reporting_currency: str,
    rate_mode: str,
    pinned_rate_set_id: uuid.UUID | None = None,
    max_rate_age_days: int = 30,
    note: str = "",
) -> FxPolicy:
    """Create or update the FX policy for a project and flush it.

    Args:
        session: Active async session.
        project_id: Project the policy belongs to.
        estimating_currency: Currency the estimate is built in.
        procurement_currency: Currency commitments are placed in.
        reporting_currency: Currency the client is reported to in.
        rate_mode: ``live`` or ``pinned``.
        pinned_rate_set_id: Set to pin to when ``rate_mode`` is ``pinned``.
        max_rate_age_days: Staleness tolerance before validation warns.
        note: Free-text remark.

    Returns:
        The stored policy.
    """
    policy = (await session.execute(select(FxPolicy).where(FxPolicy.project_id == project_id))).scalar_one_or_none()
    if policy is None:
        policy = FxPolicy(project_id=project_id)
        session.add(policy)
    policy.estimating_currency = estimating_currency.upper()
    policy.procurement_currency = procurement_currency.upper()
    policy.reporting_currency = reporting_currency.upper()
    policy.rate_mode = rate_mode
    policy.pinned_rate_set_id = pinned_rate_set_id
    policy.max_rate_age_days = max_rate_age_days
    policy.note = note
    await session.flush()
    return policy


async def delete_policy(session: AsyncSession, policy: FxPolicy) -> None:
    """Delete a project's FX policy."""
    await session.delete(policy)
    await session.flush()


# ── Legacy latest-rate cache ─────────────────────────────────────────────────


async def list_latest_rates(session: AsyncSession, base_currency: str = "EUR") -> Sequence[FxRate]:
    """Rows of the legacy latest-rate cache for a base currency."""
    stmt = select(FxRate).where(FxRate.base_currency == base_currency.upper())
    return (await session.execute(stmt)).scalars().all()


async def count_latest_rates(session: AsyncSession, base_currency: str = "EUR") -> int:
    """Number of currencies held in the legacy latest-rate cache."""
    stmt = select(func.count()).select_from(FxRate).where(FxRate.base_currency == base_currency.upper())
    return int((await session.execute(stmt)).scalar_one())


async def upsert_latest_rates(
    session: AsyncSession,
    rates: Mapping[str, Decimal],
    rate_date: date,
    *,
    base_currency: str = "EUR",
    source: str,
    only_if_empty: bool = False,
) -> int:
    """Refresh the legacy latest-rate cache. Returns the number of rows written.

    Args:
        session: Active async session.
        rates: Currency code to units-per-base.
        rate_date: Date the rates are effective for.
        base_currency: Base the rates are quoted against.
        source: Provenance key recorded on each row.
        only_if_empty: Leave a populated cache untouched. Used on the offline
            fallback path so bundled seed values never overwrite live ones.

    Returns:
        Count of rows inserted or updated.
    """
    base = base_currency.upper()
    existing = {row.currency.upper(): row for row in await list_latest_rates(session, base)}
    if only_if_empty and existing:
        return 0
    written = 0
    for code, value in rates.items():
        currency = str(code).upper()
        if currency == base or len(currency) != 3 or not currency.isalpha():
            continue
        if value <= 0:
            continue
        quantized = _q_legacy(value)
        row = existing.get(currency)
        if row is None:
            session.add(
                FxRate(
                    base_currency=base,
                    currency=currency,
                    rate=quantized,
                    rate_date=rate_date,
                    source=source,
                )
            )
        else:
            row.rate = quantized
            row.rate_date = rate_date
            row.source = source
        written += 1
    await session.flush()
    return written


# ── PPP factors ──────────────────────────────────────────────────────────────


async def get_ppp_factor(session: AsyncSession, country_iso3: str, *, active_only: bool = True) -> PppFactor | None:
    """Fetch a country's PPP factor row.

    Args:
        session: Active async session.
        country_iso3: ISO 3166-1 alpha-3 country code.
        active_only: Skip retired rows. Retiring a factor is a direct database
            write today (see :class:`~app.modules.fx.models.PppFactor`), but the
            default read still has to honour the flag, or a row someone took out
            of service would keep pricing.

    Returns:
        The factor row, or ``None``.
    """
    stmt = select(PppFactor).where(PppFactor.country_iso3 == country_iso3.upper())
    if active_only:
        stmt = stmt.where(PppFactor.is_active.is_(True))
    return (await session.execute(stmt)).scalar_one_or_none()


async def count_ppp_factors(session: AsyncSession, *, active_only: bool = True) -> int:
    """Number of countries with a PPP factor on file."""
    stmt = select(func.count()).select_from(PppFactor)
    if active_only:
        stmt = stmt.where(PppFactor.is_active.is_(True))
    return int((await session.execute(stmt)).scalar_one())


async def upsert_ppp_factor(
    session: AsyncSession,
    country_iso3: str,
    *,
    factor: Decimal,
    year: int,
    currency: str = "",
    source: str = "worldbank",
) -> PppFactor:
    """Store a country's PPP factor and flush it.

    An existing row is reactivated on update: a country whose factor was retired
    and is then re-fetched is back in service, and leaving it inactive would
    make the fresh figure invisible to every reader.
    """
    code = country_iso3.upper()
    row = await get_ppp_factor(session, code, active_only=False)
    if row is None:
        row = PppFactor(country_iso3=code)
        session.add(row)
    row.factor = factor
    row.year = year
    row.currency = currency.upper()
    row.source = source
    row.is_active = True
    await session.flush()
    return row
