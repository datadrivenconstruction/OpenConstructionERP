"""‌⁠‍Internationalization foundation service — business logic layer.

Wraps repository classes and adds business logic for:
- Currency conversion with Decimal precision
- Working-day calculations using country calendars
- ECB rate fetching and storage
- Delegating CRUD to repositories
"""

import logging
import uuid
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.i18n_foundation.models import (
    ExchangeRate,
    TaxConfiguration,
    WorkCalendar,
)
from app.modules.i18n_foundation.repository import (
    CountryRepository,
    ExchangeRateRepository,
    TaxConfigRepository,
    WorkCalendarRepository,
)
from app.modules.i18n_foundation.schemas import ConvertResponse, WorkingDaysResponse

logger = logging.getLogger(__name__)


class I18nFoundationService:
    """‌⁠‍Business logic for internationalization foundation operations."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.exchange_rate_repo = ExchangeRateRepository(session)
        self.country_repo = CountryRepository(session)
        self.work_calendar_repo = WorkCalendarRepository(session)
        self.tax_config_repo = TaxConfigRepository(session)

    # ── Currency Conversion ────────────────────────────────────────────────

    async def convert_currency(
        self,
        from_currency: str,
        to_currency: str,
        amount: str,
        rate_date: str | None = None,
    ) -> ConvertResponse:
        """‌⁠‍Convert an amount between two currencies.

        Uses Decimal arithmetic for precision. Looks up the exchange rate
        from the database. Supports direct pair lookup and EUR-based
        cross-rate calculation.

        Args:
            from_currency: Source currency code (e.g. "EUR").
            to_currency: Target currency code (e.g. "USD").
            amount: Amount as string for Decimal parsing (e.g. "1500.50").
            rate_date: Optional ISO date string for historical rates.

        Returns:
            ConvertResponse with original and converted amounts.

        Raises:
            HTTPException 400: If amount is not a valid decimal number.
            HTTPException 404: If no exchange rate is found for the pair.
        """
        # Validate amount as Decimal
        try:
            decimal_amount = Decimal(amount)
        except (InvalidOperation, ValueError) as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid amount: '{amount}' is not a valid number",
            ) from exc

        from_code = from_currency.upper()
        to_code = to_currency.upper()

        # Same-currency shortcut
        if from_code == to_code:
            return ConvertResponse(
                original_amount=amount,
                converted_amount=amount,
                from_currency=from_code,
                to_currency=to_code,
                rate="1",
                rate_date=rate_date or date.today().isoformat(),
            )

        # Try direct pair lookup
        rate_obj = await self.exchange_rate_repo.get_rate(from_code, to_code, rate_date)

        if rate_obj is not None:
            rate_decimal = Decimal(rate_obj.rate)
            converted = decimal_amount * rate_decimal
            return ConvertResponse(
                original_amount=amount,
                converted_amount=str(converted.quantize(Decimal("0.0001"))),
                from_currency=from_code,
                to_currency=to_code,
                rate=rate_obj.rate,
                rate_date=rate_obj.rate_date,
            )

        # Try reverse pair (e.g. looking for USD->EUR when only EUR->USD exists)
        reverse_obj = await self.exchange_rate_repo.get_rate(to_code, from_code, rate_date)
        if reverse_obj is not None:
            reverse_rate = Decimal(reverse_obj.rate)
            if reverse_rate != 0:
                effective_rate = Decimal("1") / reverse_rate
                converted = decimal_amount * effective_rate
                return ConvertResponse(
                    original_amount=amount,
                    converted_amount=str(converted.quantize(Decimal("0.0001"))),
                    from_currency=from_code,
                    to_currency=to_code,
                    rate=str(effective_rate.quantize(Decimal("0.000001"))),
                    rate_date=reverse_obj.rate_date,
                )

        # Try cross-rate via EUR (most ECB rates are EUR-based)
        if from_code != "EUR" and to_code != "EUR":
            eur_from = await self.exchange_rate_repo.get_rate("EUR", from_code, rate_date)
            eur_to = await self.exchange_rate_repo.get_rate("EUR", to_code, rate_date)

            if eur_from is not None and eur_to is not None:
                rate_from = Decimal(eur_from.rate)
                rate_to = Decimal(eur_to.rate)
                if rate_from != 0:
                    cross_rate = rate_to / rate_from
                    converted = decimal_amount * cross_rate
                    used_date = max(eur_from.rate_date, eur_to.rate_date)
                    return ConvertResponse(
                        original_amount=amount,
                        converted_amount=str(converted.quantize(Decimal("0.0001"))),
                        from_currency=from_code,
                        to_currency=to_code,
                        rate=str(cross_rate.quantize(Decimal("0.000001"))),
                        rate_date=used_date,
                    )

        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(f"No exchange rate found for {from_code}/{to_code}" + (f" on {rate_date}" if rate_date else "")),
        )

    # ── Working Days Calculation ───────────────────────────────────────────

    async def get_working_days(
        self,
        country_code: str,
        from_date: str,
        to_date: str,
    ) -> WorkingDaysResponse:
        """Calculate the number of working days between two dates.

        Loads the work calendar for the country and year(s), counts
        business days excluding holidays defined in the calendar.

        Args:
            country_code: Two-letter ISO country code (e.g. "DE").
            from_date: Start date as ISO string (e.g. "2026-01-05").
            to_date: End date as ISO string (e.g. "2026-01-31").

        Returns:
            WorkingDaysResponse with working and calendar day counts.

        Raises:
            HTTPException 400: If dates are invalid.
            HTTPException 404: If no work calendar exists for the country/year.
        """
        try:
            start = date.fromisoformat(from_date)
            end = date.fromisoformat(to_date)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid date format: {exc}",
            ) from exc

        if start > end:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="from_date must be on or before to_date",
            )

        code = country_code.upper()

        # Collect all unique years spanned by the date range
        years = set()
        for yr in range(start.year, end.year + 1):
            years.add(str(yr))

        # Load calendars for each year
        holiday_dates: set[date] = set()
        work_day_numbers: set[int] = {1, 2, 3, 4, 5}  # Default Mon-Fri

        for year_str in sorted(years):
            calendar = await self.work_calendar_repo.get_for_country(code, year_str)
            if calendar is not None:
                work_day_numbers = set(calendar.work_days)
                # Parse holiday exceptions
                for exc_entry in calendar.exceptions or []:
                    exc_date_str = exc_entry.get("date")
                    if exc_date_str:
                        try:
                            holiday_dates.add(date.fromisoformat(exc_date_str))
                        except ValueError:
                            logger.warning(
                                "Invalid holiday date in calendar %s: %s",
                                calendar.id,
                                exc_date_str,
                            )

        # Count working days
        working_days = 0
        calendar_days = 0
        current = start
        while current <= end:
            calendar_days += 1
            # isoweekday(): Monday=1, Sunday=7
            if current.isoweekday() in work_day_numbers and current not in holiday_dates:
                working_days += 1
            current += timedelta(days=1)

        return WorkingDaysResponse(
            country_code=code,
            from_date=from_date,
            to_date=to_date,
            working_days=working_days,
            calendar_days=calendar_days,
        )

    # ── ECB Rate Fetching ──────────────────────────────────────────────────

    async def fetch_ecb_rates(self) -> int:
        """Fetch latest daily rates from ECB and store new ones.

        Calls the ECB XML feed, parses the response, and inserts rates
        that don't already exist for the given date/pair. Existing rates
        are skipped (no duplicates).

        Returns:
            Number of newly stored exchange rates.
        """
        from app.modules.i18n_foundation.ecb_fetcher import fetch_ecb_daily_rates

        raw_rates = await fetch_ecb_daily_rates()
        if not raw_rates:
            logger.info("ECB fetch returned no rates")
            return 0

        new_count = 0
        for rate_data in raw_rates:
            # Check if this rate already exists
            existing = await self.exchange_rate_repo.get_rate(
                from_currency=rate_data["from_currency"],
                to_currency=rate_data["to_currency"],
                rate_date=rate_data["rate_date"],
            )
            if existing is not None:
                continue

            await self.exchange_rate_repo.create(
                {
                    "from_currency": rate_data["from_currency"],
                    "to_currency": rate_data["to_currency"],
                    "rate": rate_data["rate"],
                    "rate_date": rate_data["rate_date"],
                    "source": "ecb",
                    "is_manual": False,
                    "metadata": {},
                }
            )
            new_count += 1

        logger.info(
            "ECB rate fetch complete: %d new rates stored (%d total fetched)",
            new_count,
            len(raw_rates),
        )
        return new_count

    # ── Exchange Rate CRUD (delegating) ────────────────────────────────────

    async def list_exchange_rates(
        self,
        *,
        from_currency: str | None = None,
        to_currency: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[ExchangeRate], int]:
        """List exchange rates with filters and total count."""
        items = await self.exchange_rate_repo.list(
            from_currency=from_currency,
            to_currency=to_currency,
            date_from=date_from,
            date_to=date_to,
            limit=limit,
            offset=offset,
        )
        total = await self.exchange_rate_repo.count(
            from_currency=from_currency,
            to_currency=to_currency,
            date_from=date_from,
            date_to=date_to,
        )
        return items, total

    async def get_exchange_rate(self, rate_id: uuid.UUID) -> ExchangeRate:
        """Get exchange rate by ID. Raises 404 if not found."""
        rate = await self.exchange_rate_repo.get(rate_id)
        if rate is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Exchange rate not found",
            )
        return rate

    async def create_exchange_rate(self, data: dict) -> ExchangeRate:
        """Create a new exchange rate entry."""
        return await self.exchange_rate_repo.create(data)

    async def update_exchange_rate(
        self,
        rate_id: uuid.UUID,
        data: dict,
    ) -> ExchangeRate:
        """Update an exchange rate. Raises 404 if not found."""
        result = await self.exchange_rate_repo.update(rate_id, data)
        if result is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Exchange rate not found",
            )
        return result

    async def delete_exchange_rate(self, rate_id: uuid.UUID) -> None:
        """Delete an exchange rate. Raises 404 if not found."""
        deleted = await self.exchange_rate_repo.delete(rate_id)
        if not deleted:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Exchange rate not found",
            )

    # ── Country CRUD (delegating, read-only) ───────────────────────────────

    async def list_countries(
        self,
        *,
        region_group: str | None = None,
        is_active: bool = True,
    ) -> list:
        """List countries with optional region filter."""
        return await self.country_repo.list(region_group=region_group, is_active=is_active)

    async def get_country_by_iso(self, iso_code: str):  # noqa: ANN201
        """Get country by ISO code. Raises 404 if not found."""
        country = await self.country_repo.get_by_iso(iso_code)
        if country is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Country '{iso_code.upper()}' not found",
            )
        return country

    async def count_countries(self) -> int:
        """Total number of active countries."""
        return await self.country_repo.count()

    # ── Work Calendar CRUD (delegating) ────────────────────────────────────

    async def list_work_calendars(
        self,
        *,
        country_code: str | None = None,
        year: str | None = None,
    ) -> list[WorkCalendar]:
        """List work calendars with optional filters."""
        return await self.work_calendar_repo.list(country_code=country_code, year=year)

    async def get_work_calendar(self, calendar_id: uuid.UUID) -> WorkCalendar:
        """Get work calendar by ID. Raises 404 if not found."""
        calendar = await self.work_calendar_repo.get(calendar_id)
        if calendar is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Work calendar not found",
            )
        return calendar

    async def create_work_calendar(self, data: dict) -> WorkCalendar:
        """Create a new work calendar."""
        return await self.work_calendar_repo.create(data)

    async def update_work_calendar(
        self,
        calendar_id: uuid.UUID,
        data: dict,
    ) -> WorkCalendar:
        """Update a work calendar. Raises 404 if not found."""
        result = await self.work_calendar_repo.update(calendar_id, data)
        if result is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Work calendar not found",
            )
        return result

    # ── Tax Config CRUD (delegating) ───────────────────────────────────────

    async def list_tax_configs(
        self,
        *,
        country_code: str | None = None,
        tax_type: str | None = None,
    ) -> list[TaxConfiguration]:
        """List tax configurations with optional filters."""
        return await self.tax_config_repo.list(country_code=country_code, tax_type=tax_type)

    async def get_tax_config(self, config_id: uuid.UUID) -> TaxConfiguration:
        """Get tax configuration by ID. Raises 404 if not found."""
        config = await self.tax_config_repo.get(config_id)
        if config is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Tax configuration not found",
            )
        return config

    async def get_active_taxes_for_country(
        self,
        country_code: str,
    ) -> list[TaxConfiguration]:
        """Get all currently active tax configurations for a country."""
        return await self.tax_config_repo.get_active_for_country(country_code)

    async def create_tax_config(self, data: dict) -> TaxConfiguration:
        """Create a new tax configuration."""
        return await self.tax_config_repo.create(data)

    async def update_tax_config(
        self,
        config_id: uuid.UUID,
        data: dict,
    ) -> TaxConfiguration:
        """Update a tax configuration. Raises 404 if not found."""
        result = await self.tax_config_repo.update(config_id, data)
        if result is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Tax configuration not found",
            )
        return result
