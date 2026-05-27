"""‌⁠‍Internationalization foundation data access layer.

Four repository classes — one per entity. Pure data access, no business logic.
All queries use SQLAlchemy async select() + where() patterns.
"""

from __future__ import annotations

import logging
import uuid
from datetime import date

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.i18n_foundation.models import (
    Country,
    ExchangeRate,
    TaxConfiguration,
    WorkCalendar,
)

logger = logging.getLogger(__name__)


# ── ExchangeRateRepository ─────────────────────────────────────────────────


class ExchangeRateRepository:
    """‌⁠‍Data access for ExchangeRate model."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list(
        self,
        *,
        from_currency: str | None = None,
        to_currency: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ExchangeRate]:
        """‌⁠‍List exchange rates with optional filters.

        Args:
            from_currency: Filter by source currency (e.g. "EUR").
            to_currency: Filter by target currency (e.g. "USD").
            date_from: Filter rates on or after this ISO date.
            date_to: Filter rates on or before this ISO date.
            limit: Maximum number of results.
            offset: Number of results to skip.

        Returns:
            List of ExchangeRate model instances.
        """
        stmt = select(ExchangeRate)

        if from_currency is not None:
            stmt = stmt.where(ExchangeRate.from_currency == from_currency.upper())
        if to_currency is not None:
            stmt = stmt.where(ExchangeRate.to_currency == to_currency.upper())
        if date_from is not None:
            stmt = stmt.where(ExchangeRate.rate_date >= date_from)
        if date_to is not None:
            stmt = stmt.where(ExchangeRate.rate_date <= date_to)

        stmt = stmt.order_by(ExchangeRate.rate_date.desc()).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def count(
        self,
        *,
        from_currency: str | None = None,
        to_currency: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> int:
        """Count exchange rates matching the given filters."""
        stmt = select(func.count()).select_from(ExchangeRate)

        if from_currency is not None:
            stmt = stmt.where(ExchangeRate.from_currency == from_currency.upper())
        if to_currency is not None:
            stmt = stmt.where(ExchangeRate.to_currency == to_currency.upper())
        if date_from is not None:
            stmt = stmt.where(ExchangeRate.rate_date >= date_from)
        if date_to is not None:
            stmt = stmt.where(ExchangeRate.rate_date <= date_to)

        return (await self.session.execute(stmt)).scalar_one()

    async def get(self, rate_id: uuid.UUID) -> ExchangeRate | None:
        """Get exchange rate by ID."""
        return await self.session.get(ExchangeRate, rate_id)

    async def get_rate(
        self,
        from_currency: str,
        to_currency: str,
        rate_date: str | None = None,
    ) -> ExchangeRate | None:
        """Get the latest rate for a currency pair, or the rate at a specific date.

        Args:
            from_currency: Source currency code (e.g. "EUR").
            to_currency: Target currency code (e.g. "USD").
            rate_date: ISO date string. If None, returns the most recent rate.

        Returns:
            The matching ExchangeRate, or None if not found.
        """
        stmt = select(ExchangeRate).where(
            ExchangeRate.from_currency == from_currency.upper(),
            ExchangeRate.to_currency == to_currency.upper(),
        )

        if rate_date is not None:
            stmt = stmt.where(ExchangeRate.rate_date == rate_date)
        else:
            stmt = stmt.order_by(ExchangeRate.rate_date.desc())

        stmt = stmt.limit(1)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def create(self, data: dict) -> ExchangeRate:
        """Insert a new exchange rate.

        Args:
            data: Dictionary of field values matching ExchangeRate columns.

        Returns:
            The newly created ExchangeRate instance.
        """
        # Normalize currency codes to uppercase
        if "from_currency" in data:
            data["from_currency"] = data["from_currency"].upper()
        if "to_currency" in data:
            data["to_currency"] = data["to_currency"].upper()
        # Rename 'metadata' key to 'metadata_' for ORM column
        if "metadata" in data:
            data["metadata_"] = data.pop("metadata")

        rate = ExchangeRate(**data)
        self.session.add(rate)
        await self.session.flush()
        return rate

    async def update(self, rate_id: uuid.UUID, data: dict) -> ExchangeRate | None:
        """Update an exchange rate by ID.

        Args:
            rate_id: The UUID of the rate to update.
            data: Dictionary of field values to update.

        Returns:
            The updated ExchangeRate, or None if not found.
        """
        existing = await self.session.get(ExchangeRate, rate_id)
        if existing is None:
            return None

        # Normalize currency codes
        if "from_currency" in data:
            data["from_currency"] = data["from_currency"].upper()
        if "to_currency" in data:
            data["to_currency"] = data["to_currency"].upper()
        if "metadata" in data:
            data["metadata_"] = data.pop("metadata")

        if data:
            stmt = update(ExchangeRate).where(ExchangeRate.id == rate_id).values(**data)
            await self.session.execute(stmt)
            await self.session.flush()
            self.session.expire_all()

        return await self.session.get(ExchangeRate, rate_id)

    async def delete(self, rate_id: uuid.UUID) -> bool:
        """Delete an exchange rate by ID.

        Args:
            rate_id: The UUID of the rate to delete.

        Returns:
            True if the rate was deleted, False if not found.
        """
        existing = await self.session.get(ExchangeRate, rate_id)
        if existing is None:
            return False
        await self.session.delete(existing)
        await self.session.flush()
        return True

    async def bulk_create(self, items: list[dict]) -> list[ExchangeRate]:
        """Insert multiple exchange rates at once.

        Args:
            items: List of dicts with ExchangeRate field values.

        Returns:
            List of created ExchangeRate instances.
        """
        rates: list[ExchangeRate] = []
        for data in items:
            if "from_currency" in data:
                data["from_currency"] = data["from_currency"].upper()
            if "to_currency" in data:
                data["to_currency"] = data["to_currency"].upper()
            if "metadata" in data:
                data["metadata_"] = data.pop("metadata")
            rates.append(ExchangeRate(**data))
        self.session.add_all(rates)
        await self.session.flush()
        return rates


# ── CountryRepository ──────────────────────────────────────────────────────


class CountryRepository:
    """Data access for Country model."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list(
        self,
        *,
        region_group: str | None = None,
        is_active: bool = True,
    ) -> list[Country]:
        """List countries with optional filters.

        Args:
            region_group: Filter by region group (e.g. "EU", "DACH", "MENA").
            is_active: Filter by active status (default True).

        Returns:
            List of Country model instances sorted by name_en.
        """
        stmt = select(Country).where(Country.is_active == is_active)

        if region_group is not None:
            stmt = stmt.where(Country.region_group == region_group)

        stmt = stmt.order_by(Country.name_en)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_iso(self, iso_code: str) -> Country | None:
        """Get country by ISO 3166-1 alpha-2 code.

        Args:
            iso_code: Two-letter country code (e.g. "DE", "US").

        Returns:
            The matching Country, or None if not found.
        """
        stmt = select(Country).where(Country.iso_code == iso_code.upper())
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def count(self) -> int:
        """Total number of active countries."""
        stmt = select(func.count()).select_from(select(Country).where(Country.is_active.is_(True)).subquery())
        return (await self.session.execute(stmt)).scalar_one()


# ── WorkCalendarRepository ─────────────────────────────────────────────────


class WorkCalendarRepository:
    """Data access for WorkCalendar model."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list(
        self,
        *,
        country_code: str | None = None,
        year: str | None = None,
    ) -> list[WorkCalendar]:
        """List work calendars with optional filters.

        Args:
            country_code: Filter by country ISO code.
            year: Filter by year (e.g. "2026").

        Returns:
            List of WorkCalendar model instances.
        """
        stmt = select(WorkCalendar)

        if country_code is not None:
            stmt = stmt.where(WorkCalendar.country_code == country_code.upper())
        if year is not None:
            stmt = stmt.where(WorkCalendar.year == year)

        stmt = stmt.order_by(WorkCalendar.country_code, WorkCalendar.year)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get(self, calendar_id: uuid.UUID) -> WorkCalendar | None:
        """Get work calendar by ID."""
        return await self.session.get(WorkCalendar, calendar_id)

    async def get_for_country(
        self,
        country_code: str,
        year: str,
    ) -> WorkCalendar | None:
        """Get the work calendar for a specific country and year.

        Args:
            country_code: Two-letter ISO country code.
            year: Calendar year as string (e.g. "2026").

        Returns:
            The matching WorkCalendar, or None if not found.
        """
        stmt = select(WorkCalendar).where(
            WorkCalendar.country_code == country_code.upper(),
            WorkCalendar.year == year,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def create(self, data: dict) -> WorkCalendar:
        """Insert a new work calendar.

        Args:
            data: Dictionary of field values matching WorkCalendar columns.

        Returns:
            The newly created WorkCalendar instance.
        """
        if "country_code" in data:
            data["country_code"] = data["country_code"].upper()
        if "metadata" in data:
            data["metadata_"] = data.pop("metadata")

        calendar = WorkCalendar(**data)
        self.session.add(calendar)
        await self.session.flush()
        return calendar

    async def update(self, calendar_id: uuid.UUID, data: dict) -> WorkCalendar | None:
        """Update a work calendar by ID.

        Args:
            calendar_id: The UUID of the calendar to update.
            data: Dictionary of field values to update.

        Returns:
            The updated WorkCalendar, or None if not found.
        """
        existing = await self.session.get(WorkCalendar, calendar_id)
        if existing is None:
            return None

        if "country_code" in data:
            data["country_code"] = data["country_code"].upper()
        if "metadata" in data:
            data["metadata_"] = data.pop("metadata")

        if data:
            stmt = update(WorkCalendar).where(WorkCalendar.id == calendar_id).values(**data)
            await self.session.execute(stmt)
            await self.session.flush()
            self.session.expire_all()

        return await self.session.get(WorkCalendar, calendar_id)


# ── TaxConfigRepository ───────────────────────────────────────────────────


class TaxConfigRepository:
    """Data access for TaxConfiguration model."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list(
        self,
        *,
        country_code: str | None = None,
        tax_type: str | None = None,
    ) -> list[TaxConfiguration]:
        """List tax configurations with optional filters.

        Args:
            country_code: Filter by country ISO code.
            tax_type: Filter by tax type (e.g. "vat", "gst").

        Returns:
            List of TaxConfiguration model instances.
        """
        stmt = select(TaxConfiguration)

        if country_code is not None:
            stmt = stmt.where(TaxConfiguration.country_code == country_code.upper())
        if tax_type is not None:
            stmt = stmt.where(TaxConfiguration.tax_type == tax_type)

        stmt = stmt.order_by(TaxConfiguration.country_code, TaxConfiguration.tax_name)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get(self, config_id: uuid.UUID) -> TaxConfiguration | None:
        """Get tax configuration by ID."""
        return await self.session.get(TaxConfiguration, config_id)

    async def get_active_for_country(
        self,
        country_code: str,
    ) -> list[TaxConfiguration]:
        """Get all currently active tax configurations for a country.

        Active means effective_to is NULL or effective_to >= today's date.

        Args:
            country_code: Two-letter ISO country code.

        Returns:
            List of active TaxConfiguration instances.
        """
        today = date.today().isoformat()
        stmt = (
            select(TaxConfiguration)
            .where(
                TaxConfiguration.country_code == country_code.upper(),
                (TaxConfiguration.effective_to.is_(None)) | (TaxConfiguration.effective_to >= today),
            )
            .order_by(TaxConfiguration.tax_name)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def create(self, data: dict) -> TaxConfiguration:
        """Insert a new tax configuration.

        Args:
            data: Dictionary of field values matching TaxConfiguration columns.

        Returns:
            The newly created TaxConfiguration instance.
        """
        if "country_code" in data:
            data["country_code"] = data["country_code"].upper()
        if "metadata" in data:
            data["metadata_"] = data.pop("metadata")

        config = TaxConfiguration(**data)
        self.session.add(config)
        await self.session.flush()
        return config

    async def update(self, config_id: uuid.UUID, data: dict) -> TaxConfiguration | None:
        """Update a tax configuration by ID.

        Args:
            config_id: The UUID of the config to update.
            data: Dictionary of field values to update.

        Returns:
            The updated TaxConfiguration, or None if not found.
        """
        existing = await self.session.get(TaxConfiguration, config_id)
        if existing is None:
            return None

        if "country_code" in data:
            data["country_code"] = data["country_code"].upper()
        if "metadata" in data:
            data["metadata_"] = data.pop("metadata")

        if data:
            stmt = update(TaxConfiguration).where(TaxConfiguration.id == config_id).values(**data)
            await self.session.execute(stmt)
            await self.session.flush()
            self.session.expire_all()

        return await self.session.get(TaxConfiguration, config_id)
