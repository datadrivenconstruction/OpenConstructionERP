"""FX rate cache and optional PPP factor ORM models.

Tables:
    oe_fx_rate    - cached EUR-based foreign-exchange reference rates. One active
        row per (base_currency, currency) pair, holding the latest rate and the
        date it is effective for. A refresh upserts rather than appends.
    oe_ppp_factor - optional World Bank purchasing-power-parity factors. One
        active row per country (local currency units per international dollar).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import Boolean, Date, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class FxRate(Base):
    """A cached foreign-exchange reference rate quoted against a base currency.

    Rates are EUR-based, mirroring the European Central Bank daily reference
    feed: ``rate`` is the number of units of ``currency`` per one unit of
    ``base_currency`` (always EUR for the ECB feed). Exactly one active row is
    kept per ``(base_currency, currency)`` pair - the latest observed rate and
    the date it is effective for - so a refresh is an upsert, not an append.

    ``rate`` is a ``Numeric(18, 6)`` because an exchange rate is a ratio, not a
    money amount, matching :class:`~app.modules.costs.models.RegionalIndex.factor`.
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
    """

    __tablename__ = "oe_ppp_factor"
    __table_args__ = (UniqueConstraint("country_iso3", name="uq_oe_ppp_factor_country"),)

    # ISO 3166-1 alpha-3 country code (e.g. USA, TUR, CHN). The unique
    # constraint below already indexes this column, so lookups are covered.
    country_iso3: Mapped[str] = mapped_column(String(3), nullable=False)
    # Local currency the factor is denominated in (informational, may be empty).
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="", server_default="")
    # Local currency units per international dollar.
    factor: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False, default=Decimal("1"))
    # Data year of the observation (World Bank mrnev = most recent non-empty).
    year: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    source: Mapped[str] = mapped_column(String(30), nullable=False, default="worldbank", server_default="worldbank")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    def __repr__(self) -> str:
        return f"<PppFactor {self.country_iso3} = {self.factor} /intl$ ({self.year})>"
