# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Internationalization foundation ORM models.

Tables:
    oe_i18n_exchange_rate - currency exchange rates (manual, ECB, custom sources)
    oe_i18n_country       - country registry with translations and regional settings
    oe_i18n_work_calendar - work calendars with holidays per country/year
    oe_i18n_tax_config    - tax configurations per country (VAT, GST, etc.)
"""

from sqlalchemy import JSON, Boolean, CheckConstraint, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ExchangeRate(Base):
    """Currency exchange rate entry.

    Stores exchange rates between currency pairs. Rates are stored as strings
    for SQLite compatibility. Supports manual entry and automated feeds (ECB, custom).
    """

    __tablename__ = "oe_i18n_exchange_rate"
    __table_args__ = (UniqueConstraint("from_currency", "to_currency", "rate_date", name="uq_exchange_rate_pair_date"),)

    from_currency: Mapped[str] = mapped_column(String(10), index=True, nullable=False)
    to_currency: Mapped[str] = mapped_column(String(10), index=True, nullable=False)
    rate: Mapped[str] = mapped_column(String(50), nullable=False)  # Decimal as string for SQLite compat
    rate_date: Mapped[str] = mapped_column(String(40), nullable=False)  # ISO date string, e.g. "2026-04-07"
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
    """Country registry entry.

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


#: How a tax row combines with the federal rate of the same country.
#:
#: ``national``
#:     The country has no federal/provincial split in our data; the row is
#:     the whole tax for whatever it applies to. Most rows are this.
#: ``federal``
#:     The country-wide rate itself, levied everywhere (Canadian GST).
#: ``replaces_federal``
#:     A sub-national rate that supersedes the federal row rather than
#:     adding to it. A harmonised Canadian HST rate is the whole tax in
#:     its province; adding the federal 5 % on top would overstate it.
#: ``stacks_on_federal``
#:     A sub-national rate levied alongside the federal row, both charged on
#:     the pre-tax amount, so the two add (Canadian QST, PST and RST).
#: ``compounds_on_federal``
#:     A sub-national rate charged on the amount *including* the federal
#:     tax, so the two multiply rather than add. 5 % federal and a 7 %
#:     compounding provincial rate come to 12.35 %, not 12 %. No Canadian
#:     jurisdiction does this today - Quebec was the last and stopped on
#:     2013-01-01 - but the ordering of two taxes changes the total, so a
#:     model that cannot say which order they apply in cannot express a
#:     historical period, a retroactive claim, or a jurisdiction outside
#:     Canada that still works this way.
#:
#: There is deliberately no "unspecified" member and the column is NOT
#: NULL: an absent value is what let a reader supply the obvious guess,
#: which is right in a stacking province and wrong in a harmonised one.
TAX_COMBINATIONS = (
    "national",
    "federal",
    "replaces_federal",
    "stacks_on_federal",
    "compounds_on_federal",
)

#: The members that describe a rate belonging to one subdivision rather than
#: to the whole country. Exactly these three require ``subdivision_code``, and
#: the other two forbid it; see the check constraint on the table.
SUBNATIONAL_COMBINATIONS = ("replaces_federal", "stacks_on_federal", "compounds_on_federal")


class TaxConfiguration(Base):
    """Tax configuration for a country.

    Supports multiple tax types (VAT, GST, sales tax, etc.) with effective
    date ranges. NULL effective_to means the rate is currently active.
    """

    __tablename__ = "oe_i18n_tax_config"
    __table_args__ = (
        Index("ix_tax_config_country_type", "country_code", "tax_type"),
        Index("ix_tax_config_country_subdivision", "country_code", "subdivision_code"),
        # The invariant the subdivision axis rests on, stated about the data
        # rather than about the code paths that write it: a rate belongs to a
        # subdivision or it belongs to the country, and it says which by
        # carrying a subdivision code or not carrying one. A sub-national row
        # with no subdivision is the silent defect - it drops out of every
        # per-province query and the province reads as federal-only - and a
        # country-wide row that names a province is the same mistake mirrored.
        #
        # Written as an equality of two booleans rather than two implications
        # so both directions are one statement and neither can be relaxed
        # without the other being noticed.
        #
        # Named without a ``ck_`` prefix on purpose: ``Base.metadata`` carries a
        # ``ck_%(table_name)s_%(constraint_name)s`` naming convention, so the
        # finished name in the database is
        # ``ck_oe_i18n_tax_config_subdivision_matches_combination``. Spelling
        # the prefix here too would produce it twice. The revision adds the
        # constraint by explicit DDL under that same finished name, so the two
        # routes into the schema cannot end up naming one rule differently -
        # the trap ``v3267_saved_views_team_share`` already records.
        CheckConstraint(
            "(combination IN ('replaces_federal', 'stacks_on_federal', 'compounds_on_federal'))"
            " = (subdivision_code IS NOT NULL)",
            name="subdivision_matches_combination",
        ),
    )

    country_code: Mapped[str] = mapped_column(String(2), index=True, nullable=False)
    tax_name: Mapped[str] = mapped_column(String(255), nullable=False)
    tax_name_translations: Mapped[dict | None] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=True
    )
    tax_code: Mapped[str | None] = mapped_column(String(50), nullable=True)  # VAT, GST, HST, etc.
    rate_pct: Mapped[str] = mapped_column(String(20), nullable=False)  # e.g. "19.0" - string for SQLite compat
    tax_type: Mapped[str] = mapped_column(String(50), nullable=False)  # vat / sales_tax / gst / service_tax / customs
    combination: Mapped[str] = mapped_column(  # one of TAX_COMBINATIONS
        String(20),
        nullable=False,
        default="national",
        server_default="national",
    )
    # ── Subdivision axis (migration v3307) ───────────────────────────────
    # ISO 3166-2, e.g. "CA-ON", matching the ``subdivision_code`` the region
    # packs already publish. NULL is not an unset default: it is the positive
    # statement that this rate belongs to the whole country, which is what the
    # Canadian federal GST row is. The check constraint above ties the two
    # meanings together so a NULL can never mean "nobody filled this in".
    #
    # Before this column the province lived inside ``tax_code`` as a naming
    # convention - HST_ON, PST_BC - that nothing enforced, that differed
    # between countries, and that only a test helper ever parsed. A convention
    # a query cannot filter on is not an axis.
    subdivision_code: Mapped[str | None] = mapped_column(String(6), nullable=True)
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
