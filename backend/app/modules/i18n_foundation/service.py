# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Internationalization foundation service - business logic layer.

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

from app.core.provenance import declared, fell_back
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
from app.modules.i18n_foundation.schemas import ConvertResponse, WorkingDaysResponse, WorkingDaysYear
from app.modules.i18n_foundation.subdivisions import KNOWN_SUBDIVISIONS, normalize_subdivision
from app.modules.i18n_foundation.tax_rules import (
    TaxResolution,
    TaxRuleError,
    row_from_orm,
    validate_tax_row,
)
from app.modules.i18n_foundation.tax_rules import resolve as resolve_tax

logger = logging.getLogger(__name__)

#: Axis token for "which country's calendar answered". The per-year axes that
#: :class:`WorkingDaysYear` already reports are about time, not jurisdiction.
_JURISDICTION = "jurisdiction"

#: What the hardcoded week is called when a provenance has to name it.
#:
#: Named for what it is rather than for the slot it fills. A reader seeing this
#: token knows precisely which five days were assumed, and can tell at once that
#: the answer is wrong for a country working Sunday to Thursday. "DEFAULT" would
#: have told them only that no country answered, which ``answered`` already says.
#: Not a country code: this week belongs to nobody.
#:
#: Descriptive, never a discriminant. Branch on ``source`` or ``answered``.
_MONDAY_TO_FRIDAY = "MONDAY_TO_FRIDAY"


def _parse_stored_rate(raw: str, from_code: str, to_code: str) -> Decimal:
    """Parse a stored rate string into a positive, finite Decimal.

    Rate rows reach the table by two write paths - the authenticated POST
    endpoint, whose schema only checks the string's length, and the ECB
    fetcher, which copies whatever the feed's ``rate`` attribute said. Neither
    checks that the string is a usable number, so the value is validated here,
    at the single point where a stored rate is turned into money.

    Args:
        raw: The rate exactly as stored.
        from_code: Source currency of the row, for the error message.
        to_code: Target currency of the row, for the error message.

    Returns:
        The rate as a positive, finite Decimal.

    Raises:
        HTTPException 422: If the stored rate is not a number, is NaN or
            infinite, or is zero or negative. A zero rate would otherwise
            price the whole conversion at nothing, and a non-numeric one
            would surface as an uncaught InvalidOperation.
    """
    try:
        rate = Decimal(raw)
    except (InvalidOperation, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Stored exchange rate for {from_code}/{to_code} is not a valid number: '{raw}'",
        ) from exc

    if not rate.is_finite() or rate <= 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(f"Stored exchange rate for {from_code}/{to_code} must be a positive finite number, got '{raw}'"),
        )
    return rate


class I18nFoundationService:
    """Business logic for internationalization foundation operations."""

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
        """Convert an amount between two currencies.

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
            HTTPException 400: If amount is not a valid decimal number, or is
                NaN or infinite. Decimal() accepts both of those spellings, so
                they are rejected explicitly - money must never be NaN.
            HTTPException 404: If no exchange rate is found for the pair.
            HTTPException 422: If the stored rate itself is unusable.
        """
        # Validate amount as Decimal
        try:
            decimal_amount = Decimal(amount)
        except (InvalidOperation, ValueError) as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid amount: '{amount}' is not a valid number",
            ) from exc

        # Decimal("NaN") and Decimal("Infinity") parse without raising. Left
        # unchecked, NaN flows straight through the same-currency shortcut into
        # the response body, and Infinity blows up in quantize() as a 500.
        if not decimal_amount.is_finite():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid amount: '{amount}' is not a finite number",
            )

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
            rate_decimal = _parse_stored_rate(rate_obj.rate, from_code, to_code)
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
            reverse_rate = _parse_stored_rate(reverse_obj.rate, to_code, from_code)
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
                rate_from = _parse_stored_rate(eur_from.rate, "EUR", from_code)
                rate_to = _parse_stored_rate(eur_to.rate, "EUR", to_code)
                cross_rate = rate_to / rate_from
                converted = decimal_amount * cross_rate
                # Without an explicit rate_date each leg fetched its own latest
                # row, so the two legs can be from different days. A cross rate
                # is only as fresh as its stalest leg - reporting the newer date
                # would claim a freshness the number does not have.
                used_date = min(eur_from.rate_date, eur_to.rate_date)
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

        Loads the work calendar for every year the range spans and counts
        business days excluding the holidays those calendars declare. Both
        ends of the range are inclusive, so a range whose start equals its end
        is one calendar day.

        Each date is judged against its own year's work week. A year with no
        calendar of its own uses the nearest year that has one, looking outside
        the requested range when no spanned year declares a calendar, and falls
        back to Monday-Friday only when the country has no calendar at all.

        Holidays are not carried across years the way the work week is. They
        come only from the calendars inside the range, so a range reaching past
        the last seeded year is counted with no holidays at all.

        Args:
            country_code: Two-letter ISO country code (e.g. "DE").
            from_date: Start date as ISO string (e.g. "2026-01-05").
            to_date: End date as ISO string (e.g. "2026-01-31").

        Returns:
            WorkingDaysResponse with working and calendar day counts.

        Raises:
            HTTPException 400: If the dates are unparseable or out of order.
                A missing calendar is not an error - see the fallback above.
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

        spanned_years = list(range(start.year, end.year + 1))

        # Load the calendar of every spanned year and keep the work weeks
        # apart. A country that changes its working week (the Gulf move from
        # Sun-Thu to Mon-Fri, for instance) has one calendar per year, and a
        # range crossing that boundary must judge each date by its own year.
        holiday_dates: set[date] = set()
        declared_work_days: dict[int, set[int]] = {}

        for year in spanned_years:
            calendar = await self.work_calendar_repo.get_for_country(code, str(year))
            if calendar is None:
                continue
            week = set(calendar.work_days or [])
            if not week:
                # A row that names no working day at all states no working
                # week, and counting with it would make every date in the year
                # a non-working day: a plausible zero rather than a complaint.
                # Treated as absent entirely, holidays included, so the year
                # carries a week from elsewhere and reports both that and
                # holidays_applied False. Taking the holidays while refusing
                # the week would make holidays_applied disagree with the row
                # it is describing.
                logger.warning(
                    "Work calendar %s for %s %s declares no working days; ignoring it",
                    calendar.id,
                    code,
                    year,
                )
                continue
            declared_work_days[year] = week
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

        # Resolve a work week for every spanned year: its own if declared,
        # otherwise the nearest declared year (ties go to the earlier one),
        # otherwise Monday-Friday.
        #
        # When no spanned year declares a calendar, look outside the range
        # before giving up. The seeded file covers a single year, so a range
        # past it used to be judged Monday-Friday even for a country whose
        # declared week is not Monday-Friday: Saudi Arabia's Sunday-Thursday
        # came back exactly inverted, Friday counted as working and Sunday as
        # weekend. Both weeks are five days, so the yearly total was unchanged
        # and only the individual days were wrong.
        #
        # A working week is a rule and can be carried forward. A holiday is a
        # date and cannot, which is why the lookup below covers only the week.
        default_work_days = {1, 2, 3, 4, 5}
        fallback_work_days = declared_work_days
        if not fallback_work_days:
            fallback_work_days = {}
            for other in await self.work_calendar_repo.list(country_code=code):
                try:
                    declared_year = int(other.year)
                except (TypeError, ValueError):
                    logger.warning(
                        "Work calendar %s has an unparseable year: %r",
                        other.id,
                        other.year,
                    )
                    continue
                other_week = set(other.work_days or [])
                if not other_week:
                    # Same reasoning as above, and this is the branch that made
                    # it dangerous: the mapping would be non-empty while the
                    # week inside it was not, so the year reported a week
                    # carried from a real calendar and then counted no working
                    # days in any range, for ever, without a failure anywhere.
                    logger.warning(
                        "Work calendar %s for %s %s declares no working days; ignoring it",
                        other.id,
                        code,
                        declared_year,
                    )
                    continue
                fallback_work_days[declared_year] = other_week

        # Whether this country is known at all, which is a different question
        # from the per-year ones below. By this point the lookup has been
        # widened past the requested range, so an empty mapping here means no
        # calendar exists for the country in any year and the Monday-Friday
        # week about to be used belongs to nobody.
        jurisdiction = (
            declared(_JURISDICTION, code) if fallback_work_days else fell_back(_JURISDICTION, code, _MONDAY_TO_FRIDAY)
        )

        work_days_by_year: dict[int, set[int]] = {}
        resolved_years: list[WorkingDaysYear] = []
        for year in spanned_years:
            carried_from: int | None = None
            if year in declared_work_days:
                work_days_by_year[year] = declared_work_days[year]
                source = "declared"
            elif fallback_work_days:
                nearest = min(fallback_work_days, key=lambda y, target=year: (abs(y - target), y))
                work_days_by_year[year] = fallback_work_days[nearest]
                source = "carried"
                carried_from = nearest
            else:
                work_days_by_year[year] = default_work_days
                source = "default"

            # Holidays come only from a year's own calendar, never carried, so
            # this is not the same question as where the week came from.
            resolved_years.append(
                WorkingDaysYear(
                    year=year,
                    work_week_source=source,
                    work_week_from_year=carried_from,
                    holidays_applied=year in declared_work_days,
                )
            )

        # Count working days
        working_days = 0
        calendar_days = 0
        current = start
        while current <= end:
            calendar_days += 1
            # isoweekday(): Monday=1, Sunday=7
            if current.isoweekday() in work_days_by_year[current.year] and current not in holiday_dates:
                working_days += 1
            current += timedelta(days=1)

        return WorkingDaysResponse(
            country_code=code,
            jurisdiction=jurisdiction,
            from_date=from_date,
            to_date=to_date,
            working_days=working_days,
            calendar_days=calendar_days,
            years=resolved_years,
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
        subdivision_code: str | None = None,
    ) -> list[TaxConfiguration]:
        """List tax configurations with optional filters."""
        return await self.tax_config_repo.list(
            country_code=country_code,
            tax_type=tax_type,
            subdivision_code=subdivision_code,
        )

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

    async def _country_has_federal_layer(self, country_code: str) -> bool:
        """Whether this country already carries a country-wide federal rate.

        A country with a federal layer has a sub-national structure by
        definition - the layer exists so something can sit on top of it - so a
        row there cannot honestly call itself ``national``.
        """
        rows = await self.tax_config_repo.list(country_code=country_code)
        return any(row.combination == "federal" for row in rows)

    async def _validate_tax_row(
        self,
        country_code: str,
        combination: str,
        subdivision_code: str | None,
        rate_pct: str | None = None,
    ) -> None:
        """Apply the tax write rules, reporting a breach as a 422.

        Wraps :func:`~app.modules.i18n_foundation.tax_rules.validate_tax_row`
        and supplies the one input it cannot work out for itself, which needs
        a query.
        """
        try:
            validate_tax_row(
                country_code,
                combination,
                subdivision_code,
                rate_pct=rate_pct,
                country_has_federal_layer=await self._country_has_federal_layer(country_code),
            )
        except TaxRuleError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={"code": exc.code, "message": exc.message},
            ) from exc

    async def create_tax_config(self, data: dict) -> TaxConfiguration:
        """Create a new tax configuration.

        Raises:
            HTTPException: 422 when the row contradicts itself - a
                sub-national rate that does not say which subdivision it
                belongs to, a country-wide one that does, or a rate calling
                itself ``national`` in a country that taxes by subdivision.
                That last one is the quiet failure this guard exists for: a
                Canadian provincial rate left at the default computed as the
                federal 5 % and nothing said so.
        """
        data = dict(data)
        data["subdivision_code"] = normalize_subdivision(data.get("subdivision_code"))
        await self._validate_tax_row(
            data.get("country_code", ""),
            data.get("combination", "national"),
            data["subdivision_code"],
            data.get("rate_pct"),
        )
        return await self.tax_config_repo.create(data)

    async def update_tax_config(
        self,
        config_id: uuid.UUID,
        data: dict,
    ) -> TaxConfiguration:
        """Update a tax configuration. Raises 404 if not found.

        The rules are checked against the row as it will be *after* the patch,
        not against the fields the patch happens to name. Checking only what
        was sent would let a two-step edit walk a row into a state neither
        step could have written in one go - clear the subdivision today, set
        the combination to ``national`` tomorrow.

        Raises:
            HTTPException: 404 if the configuration does not exist, 422 if the
                merged row would break the tax write rules.
        """
        existing = await self.get_tax_config(config_id)

        data = dict(data)
        if "subdivision_code" in data:
            data["subdivision_code"] = normalize_subdivision(data["subdivision_code"])

        merged_country = data.get("country_code") or existing.country_code
        merged_combination = data.get("combination") or existing.combination
        # ``.get`` with a fallback, not ``or``: a patch that names the field
        # with a null is asking to clear it, and that has to survive as None
        # rather than falling back to what the row already had.
        merged_subdivision = data.get("subdivision_code", existing.subdivision_code)
        # ``.get`` with a fallback again, and for a sharper reason than above:
        # ``or`` would fall back to the stored rate whenever the patch sends a
        # falsy one, so ``{"rate_pct": ""}`` would be validated as the old,
        # valid rate and then written as the empty string. That is the same
        # defect this guard exists to remove - the value checked and the value
        # stored being different ones.
        merged_rate = data.get("rate_pct", existing.rate_pct)
        if "rate_pct" in data and not merged_rate:
            # ``rate_pct`` is NOT NULL and every row must carry a rate, so a
            # patch naming the field with a null or an empty string is asking
            # for something the column cannot hold. Caught here rather than
            # left to the rules, which read ``None`` as "the caller did not
            # mention the rate" - the two have to stay distinguishable, or a
            # patch that clears the rate would be validated as the old one.
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={
                    "code": "rate_required",
                    "message": "rate_pct cannot be cleared. Every tax row carries a rate; delete the row instead.",
                },
            )
        await self._validate_tax_row(merged_country, merged_combination, merged_subdivision, merged_rate)

        result = await self.tax_config_repo.update(config_id, data)
        if result is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Tax configuration not found",
            )
        return result

    # ── Tax resolution ─────────────────────────────────────────────────────

    async def resolve_tax_rate(
        self,
        country_code: str,
        subdivision_code: str | None = None,
        on_date: str | None = None,
    ) -> TaxResolution:
        """Total tax rate for a project in one jurisdiction on one date.

        This is the method a caller pricing work should use. The list
        endpoints hand back rows and leave the combining to whoever asked,
        which is how a reader ends up adding a harmonised provincial rate to
        the federal one and reporting an 18 % Ontario invoice.

        Args:
            country_code: ISO 3166-1 alpha-2 of the project's country.
            subdivision_code: ISO 3166-2 of the province, state or territory.
                ``None`` is answered honestly rather than helpfully: for a
                country that taxes by subdivision the result is
                ``subdivision_unknown`` and carries no rate at all.
            on_date: ISO date to price at. Defaults to today, and a past date
                reads the rate that was in force then.

        Returns:
            A :class:`~app.modules.i18n_foundation.tax_rules.TaxResolution`.
            Check ``resolved`` before using ``combined_rate_pct``.

        Raises:
            HTTPException: 409 when the stored rates for this jurisdiction
                contradict each other and no total can be computed from them -
                two rates both replacing the federal one, or a rate whose
                ``rate_pct`` is not a number. The request itself was fine, so
                this is not a 422; the configuration is what needs fixing, and
                the ``code`` in the detail names which rule it breaks. Rows
                written through this service cannot reach either state, but
                rows that predate these rules, or that a deployment wrote
                straight to the table, still can.
        """
        rows = await self.tax_config_repo.list(country_code=country_code)
        try:
            return resolve_tax(
                [row_from_orm(row) for row in rows],
                country_code,
                subdivision_code,
                on_date,
            )
        except TaxRuleError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": exc.code, "message": exc.message},
            ) from exc

    @staticmethod
    def list_subdivisions(country_code: str) -> list[tuple[str, str]]:
        """Subdivisions the platform carries tax rates for, code and name.

        Empty for a country with no registry, which is a different statement
        from "this country has no subdivisions" - see
        :mod:`app.modules.i18n_foundation.subdivisions`.
        """
        registry = KNOWN_SUBDIVISIONS.get(country_code.strip().upper(), {})
        return sorted(registry.items())
