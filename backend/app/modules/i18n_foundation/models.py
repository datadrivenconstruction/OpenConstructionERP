"""‌⁠‍Internationalization foundation ORM models.

Tables:
    oe_i18n_exchange_rate — currency exchange rates (manual, ECB, custom sources)
    oe_i18n_country       — country registry with translations and regional settings
    oe_i18n_work_calendar — work calendars with holidays per country/year
    oe_i18n_tax_config    — tax configurations per country (VAT, GST, etc.)
"""

from sqlalchemy import JSON, Boolean, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ExchangeRate(Base):
    """‌⁠‍Currency exchange rate entry.

    Stores exchange rates between currency pairs. Rates are stored as strings
    for SQLite compatibility. Supports manual entry and automated feeds (ECB, custom).
    """

    __tablename__ = "oe_i18n_exchange_rate"
    __table_args__ = (UniqueConstraint("from_currency", "to_currency", "rate_date", name="uq_exchange_rate_pair_date"),)

    from_currency: Mapped[str] = mapped_column(String(10), index=True, nullable=False)
    to_currency: Mapped[str] = mapped_column(String(10), index=True, nullable=False)
    rate: Mapped[str] = mapped_column(String(50), nullable=False)  # Decimal as string for SQLite compat
    rate_date: Mapped[str] = mapped_column(String(20), nullable=False)  # ISO date string, e.g. "2026-04-07"
    source: Mapped[str] = mapped_column(String(50), nullable=False, default="manual")  # manual / ecb / custom
    is_manual: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:
        return f"<ExchangeRate {self.from_currency}/{self.to_currency} {self.rate} @ {self.rate_date}>"


class Country(Base):
    """‌⁠‍Country registry entry.

    Stores ISO country codes, localized names, default currency/measurement,
    and regional grouping. Name translations are stored as a JSON dict for
    fast queries without joins.
    """

    __tablename__ = "oe_i18n_country"

    iso_code: Mapped[str] = mapped_column(String(2), unique=True, index=True, nullable=False)
    iso_code_3: Mapped[str | None] = mapped_column(String(3), nullable=True)
    name_en: Mapped[str] = mapped_column(String(255), nullable=False)  # Denormalized for fast queries
    name_translations: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False
    )  # {"en": "Germany", "de": "Deutschland", ...}
    currency_default: Mapped[str | None] = mapped_column(String(10), nullable=True)
    measurement_default: Mapped[str | None] = mapped_column(String(20), nullable=True)  # metric / imperial
    phone_code: Mapped[str | None] = mapped_column(String(10), nullable=True)
    address_format_template: Mapped[dict | None] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=True
    )
    region_group: Mapped[str | None] = mapped_column(String(50), nullable=True)  # EU, DACH, MENA, NA, APAC, etc.
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:
        return f"<Country {self.iso_code} ({self.name_en})>"


class WorkCalendar(Base):
    """Work calendar for a country/year.

    Defines working days per week, hours per day, and holiday exceptions.
    Used for scheduling, duration calculations, and regional labour planning.
    """

    __tablename__ = "oe_i18n_work_calendar"
    __table_args__ = (UniqueConstraint("country_code", "year", name="uq_work_calendar_country_year"),)

    country_code: Mapped[str] = mapped_column(String(2), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    name_translations: Mapped[dict | None] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=True
    )
    year: Mapped[str] = mapped_column(String(4), nullable=False)  # e.g. "2026"
    work_hours_per_day: Mapped[str] = mapped_column(String(10), nullable=False, default="8")  # Decimal as string
    work_days: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False
    )  # ISO weekday numbers, e.g. [1,2,3,4,5] for Mon-Fri
    exceptions: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False
    )  # Array of holiday objects
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:
        return f"<WorkCalendar {self.country_code} {self.year} ({self.name})>"


class TaxConfiguration(Base):
    """Tax configuration for a country.

    Supports multiple tax types (VAT, GST, sales tax, etc.) with effective
    date ranges. NULL effective_to means the rate is currently active.
    """

    __tablename__ = "oe_i18n_tax_config"
    __table_args__ = (Index("ix_tax_config_country_type", "country_code", "tax_type"),)

    country_code: Mapped[str] = mapped_column(String(2), index=True, nullable=False)
    tax_name: Mapped[str] = mapped_column(String(255), nullable=False)
    tax_name_translations: Mapped[dict | None] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=True
    )
    tax_code: Mapped[str | None] = mapped_column(String(50), nullable=True)  # VAT, GST, HST, etc.
    rate_pct: Mapped[str] = mapped_column(String(20), nullable=False)  # e.g. "19.0" — string for SQLite compat
    tax_type: Mapped[str] = mapped_column(String(50), nullable=False)  # vat / sales_tax / gst / service_tax / customs
    effective_from: Mapped[str | None] = mapped_column(String(20), nullable=True)  # ISO date string
    effective_to: Mapped[str | None] = mapped_column(String(20), nullable=True)  # NULL = currently active
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:
        return f"<TaxConfiguration {self.country_code} {self.tax_name} {self.rate_pct}%>"
