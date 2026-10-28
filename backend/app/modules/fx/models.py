# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠FX rate register ORM models: published rate sets, quotes, policy and PPP.

A construction project is routinely estimated in one currency, procured in a
second and reported to the client in a third, so "what is the rate" is never a
sufficient question. The register answers three:

* **Which rate applied on a date?** ``oe_fx_rate_set`` + ``oe_fx_rate_quote``
  hold the full history, one set per (base, date, source), so a figure priced
  last quarter can still be reproduced today.
* **Where did that rate come from?** A rate set carries its source, the
  document or URL it was read from, when it was fetched and whether it has been
  locked against further edits.
* **What did the project agree to use?** ``oe_fx_policy`` records the project's
  three currencies, whether it tracks live rates or a pinned set, and how stale
  a rate may get before it is flagged.

Tables:
    oe_fx_rate_set   - one published rate set: base currency, effective date,
        source and provenance. Owns its quotes.
    oe_fx_rate_quote - one currency's rate inside a set (units of the currency
        per one unit of the set's base currency).
    oe_fx_policy     - per-project currency policy and rate pinning.
    oe_fx_rate       - legacy "latest rate per pair" compatibility cache, kept
        current alongside the rate sets so an installation that has not
        refreshed since upgrading still resolves rates.
    oe_ppp_factor    - optional World Bank purchasing-power-parity factors.

Rates are ``Numeric(20, 10)`` on the new tables. Six decimals is enough for a
rate quoted against a strong currency but loses roughly one percent of an
inverse rate such as VND per EUR, and construction budgets are converted in
both directions.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import GUID, Base

#: Rate sets are published, not edited: a locked set is the reproducibility
#: guarantee behind a pinned policy.
RATE_MODE_LIVE = "live"
RATE_MODE_PINNED = "pinned"
RATE_MODES: frozenset[str] = frozenset({RATE_MODE_LIVE, RATE_MODE_PINNED})

#: Where a rate set came from. ``ecb`` is the live daily reference feed,
#: ``seed`` the bundled offline fallback, ``manual`` a hand-entered set (a
#: contract rate, a bank quote, a treasury instruction).
SOURCE_ECB = "ecb"
SOURCE_SEED = "seed"
SOURCE_MANUAL = "manual"


def _utcnow() -> datetime:
    """Timezone-aware UTC now, used as the Python-side default for ``fetched_at``."""
    return datetime.now(UTC)


class FxRateSet(Base):
    """One published set of exchange rates: the unit of provenance and history.

    A set is identified by ``(base_currency, rate_date, source)``: the European
    Central Bank's rates for 3 March and a bank's own quote for the same day are
    two different sets, and both are keepable. ``quotes`` is the point of the
    row, so it loads with ``selectin``; reading a set without its rates is never
    what a caller wants.

    ``is_locked`` marks a set that must not change again. A project pinned to a
    locked set can reprice identically a year later, which is the difference
    between an auditable estimate and a number that quietly drifted.
    """

    __tablename__ = "oe_fx_rate_set"
    __table_args__ = (
        UniqueConstraint(
            "base_currency",
            "rate_date",
            "source",
            name="uq_oe_fx_rate_set_base_date_source",
        ),
        Index("ix_oe_fx_rate_set_base_date", "base_currency", "rate_date"),
    )

    # ISO 4217 code every quote in this set is expressed against.
    base_currency: Mapped[str] = mapped_column(String(3), nullable=False, default="EUR", server_default="EUR")
    # The date the rates are effective for, not the date they were downloaded.
    rate_date: Mapped[date] = mapped_column(Date(), nullable=False)
    # ecb | seed | manual.
    source: Mapped[str] = mapped_column(String(30), nullable=False, default=SOURCE_ECB, server_default=SOURCE_ECB)
    # Where the figures were read from: a feed URL, a bank statement reference,
    # a contract clause. Free text, because provenance outside a feed is prose.
    source_ref: Mapped[str] = mapped_column(String(500), nullable=False, default="", server_default="")
    # When the set was captured. Distinct from ``rate_date``: a feed published
    # on Friday may only be fetched on Monday, and both facts matter in audit.
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        server_default=func.now(),
    )
    # A locked set is immutable; the repository refuses to rewrite its quotes.
    is_locked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    note: Mapped[str] = mapped_column(String(500), nullable=False, default="", server_default="")

    # The rates are the reason the set exists, so load them with the parent.
    quotes: Mapped[list[FxRateQuote]] = relationship(
        back_populates="rate_set",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="FxRateQuote.currency",
    )

    def __repr__(self) -> str:
        return f"<FxRateSet {self.base_currency} {self.rate_date} from {self.source}>"


class FxRateQuote(Base):
    """One currency's rate inside a rate set.

    ``rate`` is units of ``currency`` per one unit of the owning set's base
    currency, matching the shape of the ECB reference feed. The base currency
    itself is never quoted; it is implicit at 1.

    ``rate_set`` is a many-to-one back-reference, so it is ``raise_on_sql``: the
    foreign key is already in the column, and an implicit walk back up from a
    quote loaded on its own is precisely the lazy load that breaks in an async
    session. Callers that need the parent order it eagerly.
    """

    __tablename__ = "oe_fx_rate_quote"
    __table_args__ = (UniqueConstraint("rate_set_id", "currency", name="uq_oe_fx_rate_quote_set_currency"),)

    rate_set_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_fx_rate_set.id", name="fk_oe_fx_rate_quote_rate_set", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    # Units of ``currency`` per one base unit. A ratio, not a money amount.
    rate: Mapped[Decimal] = mapped_column(Numeric(20, 10), nullable=False, default=Decimal("1"))

    rate_set: Mapped[FxRateSet] = relationship(back_populates="quotes", lazy="raise_on_sql")

    def __repr__(self) -> str:
        return f"<FxRateQuote {self.currency} = {self.rate}>"


class FxPolicy(Base):
    """A project's currency policy: which currencies, and which rates.

    One row per project. The three currencies are the three questions a cost
    manager actually faces - the estimate is built in one, commitments are
    placed in another, and the client is reported to in a third - and keeping
    them apart is what lets a report say whether a movement came from scope or
    from the rate.

    ``rate_mode`` is ``live`` (always use the newest available set) or
    ``pinned`` (always use ``pinned_rate_set``). ``max_rate_age_days`` is the
    staleness the project tolerates before validation flags it.

    ``pinned_rate_set`` is a many-to-one scalar and therefore ``raise_on_sql``:
    the id is already on the row, and every caller that needs the set itself
    asks for it explicitly.
    """

    __tablename__ = "oe_fx_policy"
    __table_args__ = (UniqueConstraint("project_id", name="uq_oe_fx_policy_project"),)

    # Plain GUID rather than a cross-module foreign key, matching how the costs
    # module references projects; the unique constraint indexes it.
    project_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False)
    # The currency the estimate is built in.
    estimating_currency: Mapped[str] = mapped_column(String(3), nullable=False, default="EUR", server_default="EUR")
    # The currency commitments are placed in.
    procurement_currency: Mapped[str] = mapped_column(String(3), nullable=False, default="EUR", server_default="EUR")
    # The currency the client is reported to in.
    reporting_currency: Mapped[str] = mapped_column(String(3), nullable=False, default="EUR", server_default="EUR")
    # live | pinned.
    rate_mode: Mapped[str] = mapped_column(
        String(10), nullable=False, default=RATE_MODE_LIVE, server_default=RATE_MODE_LIVE
    )
    pinned_rate_set_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_fx_rate_set.id", name="fk_oe_fx_policy_pinned_rate_set", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # How old the backing rate set may be before validation warns.
    max_rate_age_days: Mapped[int] = mapped_column(Integer, nullable=False, default=30, server_default="30")
    note: Mapped[str] = mapped_column(String(500), nullable=False, default="", server_default="")

    pinned_rate_set: Mapped[FxRateSet | None] = relationship(lazy="raise_on_sql")

    def __repr__(self) -> str:
        return f"<FxPolicy project={self.project_id} report_in={self.reporting_currency} mode={self.rate_mode}>"


class FxRate(Base):
    """Latest cached rate per ``(base_currency, currency)`` pair.

    This is the module's original single-row-per-pair cache and is retained as a
    compatibility layer, not as a second source of truth: a refresh writes the
    full ``FxRateSet`` history *and* refreshes this table in the same
    transaction, and rate resolution consults it only when no rate set exists.
    That matters on an installation upgraded from an earlier version, where this
    table already holds usable rates and the history does not.

    ``rate`` is a ``Numeric(18, 6)`` ratio, matching
    :class:`~app.modules.costs.models.RegionalIndex.factor`.
    """

    __tablename__ = "oe_fx_rate"
    __table_args__ = (UniqueConstraint("base_currency", "currency", name="uq_oe_fx_rate_base_currency"),)

    # ISO 4217 code the rate is quoted against (EUR for the ECB feed).
    base_currency: Mapped[str] = mapped_column(String(3), nullable=False, default="EUR", server_default="EUR")
    # ISO 4217 code of the target currency (e.g. USD, TRY, CNY).
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    # Units of ``currency`` per one ``base_currency``. Ratio, not money.
    rate: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False, default=Decimal("1"))
    # ECB reference date the rate is effective for ("as of").
    rate_date: Mapped[date] = mapped_column(Date(), nullable=False)
    # ecb (live feed) | seed (bundled fallback) | manual (hand-entered).
    source: Mapped[str] = mapped_column(String(30), nullable=False, default="ecb", server_default="ecb")

    def __repr__(self) -> str:
        return f"<FxRate 1 {self.base_currency} = {self.rate} {self.currency} as-of {self.rate_date}>"


class PppFactor(Base):
    """An optional World Bank purchasing-power-parity conversion factor.

    ``factor`` is local currency units per international dollar (World Bank
    indicator ``PA.NUS.PPP``, "PPP conversion factor, GDP"). One active row is
    kept per ``country_iso3``; the PPP path is optional and degrades to an
    "unavailable" response when a country's factor has never been fetched.
    ``factor`` is a ``Numeric(18, 6)`` ratio like :class:`FxRate.rate`.

    ``is_active`` is honoured on read - a cleared row is invisible to the
    lookup, and re-fetching a country reactivates it. Nothing in the module
    clears the flag today: it exists so a superseded observation can be retired
    without deleting it, but retiring one currently means a direct database
    write. This is deliberately not exposed rather than half-exposed.
    """

    __tablename__ = "oe_ppp_factor"
    __table_args__ = (UniqueConstraint("country_iso3", name="uq_oe_ppp_factor_country"),)

    # ISO 3166-1 alpha-3 country code (e.g. USA, TUR, CHN). The unique
    # constraint below already indexes this column, so lookups are covered.
    country_iso3: Mapped[str] = mapped_column(String(3), nullable=False)
    # Local currency the factor is denominated in, filled from the currency the
    # lookup was made for so a stored row is readable on its own.
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="", server_default="")
    # Local currency units per international dollar.
    factor: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False, default=Decimal("1"))
    # Data year of the observation (World Bank mrnev = most recent non-empty).
    year: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    source: Mapped[str] = mapped_column(String(30), nullable=False, default="worldbank", server_default="worldbank")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    def __repr__(self) -> str:
        return f"<PppFactor {self.country_iso3} = {self.factor} /intl$ ({self.year})>"
