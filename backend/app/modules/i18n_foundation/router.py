"""Internationalization foundation API routes.

Endpoints:
    # Exchange Rates
    GET    /exchange-rates               — List rates with filters (public)
    POST   /exchange-rates               — Create manual rate (auth)
    GET    /exchange-rates/convert       — Convert amount between currencies (public)
    POST   /exchange-rates/fetch-ecb     — Fetch rates from ECB (admin)
    GET    /exchange-rates/{rate_id}     — Get single rate (public)
    PATCH  /exchange-rates/{rate_id}     — Update rate (auth)
    DELETE /exchange-rates/{rate_id}     — Delete rate (auth)

    # Countries
    GET    /countries                    — List all countries (public)
    GET    /countries/{iso_code}         — Get country by ISO code (public)

    # Work Calendars
    GET    /work-calendars               — List calendars (public)
    GET    /work-calendars/working-days  — Calculate working days (public)
    POST   /work-calendars               — Create calendar (auth)
    GET    /work-calendars/{calendar_id} — Get single calendar (public)
    PATCH  /work-calendars/{calendar_id} — Update calendar (auth)

    # Tax Configs
    GET    /tax-configs                  — List configs (public)
    GET    /tax-configs/by-country/{code}— Active taxes for country (public)
    POST   /tax-configs                  — Create config (auth)
    GET    /tax-configs/{config_id}      — Get single config (public)
    PATCH  /tax-configs/{config_id}      — Update config (auth)
"""

import logging
import uuid

from fastapi import APIRouter, Depends, Query, status

from app.dependencies import CurrentUserId, RequirePermission, SessionDep
from app.modules.i18n_foundation.schemas import (
    ConvertResponse,
    CountryListResponse,
    CountryResponse,
    ExchangeRateCreate,
    ExchangeRateListResponse,
    ExchangeRateResponse,
    ExchangeRateUpdate,
    TaxConfigCreate,
    TaxConfigListResponse,
    TaxConfigResponse,
    TaxConfigUpdate,
    WorkCalendarCreate,
    WorkCalendarListResponse,
    WorkCalendarResponse,
    WorkCalendarUpdate,
    WorkingDaysResponse,
)
from app.modules.i18n_foundation.service import I18nFoundationService

router = APIRouter()
logger = logging.getLogger(__name__)


def _get_service(session: SessionDep) -> I18nFoundationService:
    return I18nFoundationService(session)


# ═══════════════════════════════════════════════════════════════════════════
#  Exchange Rates
# ═══════════════════════════════════════════════════════════════════════════


@router.get("/exchange-rates/", response_model=ExchangeRateListResponse)
async def list_exchange_rates(
    service: I18nFoundationService = Depends(_get_service),
    from_currency: str | None = Query(default=None, description="Filter by source currency"),
    to_currency: str | None = Query(default=None, description="Filter by target currency"),
    date_from: str | None = Query(default=None, description="Rates on or after this date"),
    date_to: str | None = Query(default=None, description="Rates on or before this date"),
    limit: int = Query(default=100, ge=1, le=1000, description="Max results"),
    offset: int = Query(default=0, ge=0, description="Offset for pagination"),
) -> ExchangeRateListResponse:
    """List exchange rates with optional filters."""
    items, total = await service.list_exchange_rates(
        from_currency=from_currency,
        to_currency=to_currency,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
        offset=offset,
    )
    return ExchangeRateListResponse(
        items=[ExchangeRateResponse.model_validate(r) for r in items],
        total=total,
    )


@router.post(
    "/exchange-rates/",
    response_model=ExchangeRateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_exchange_rate(
    data: ExchangeRateCreate,
    _user_id: CurrentUserId,
    service: I18nFoundationService = Depends(_get_service),
) -> ExchangeRateResponse:
    """Create a new exchange rate entry (auth required)."""
    rate = await service.create_exchange_rate(data.model_dump())
    return ExchangeRateResponse.model_validate(rate)


@router.get("/exchange-rates/convert/", response_model=ConvertResponse)
async def convert_currency(
    from_currency: str = Query(..., min_length=3, max_length=3, description="Source currency"),
    to_currency: str = Query(..., min_length=3, max_length=3, description="Target currency"),
    amount: str = Query(..., min_length=1, description="Amount to convert"),
    date: str | None = Query(default=None, description="Historical rate date (ISO format)"),
    service: I18nFoundationService = Depends(_get_service),
) -> ConvertResponse:
    """Convert an amount between currencies using stored exchange rates."""
    return await service.convert_currency(
        from_currency=from_currency,
        to_currency=to_currency,
        amount=amount,
        rate_date=date,
    )


@router.post("/exchange-rates/fetch-ecb/")
async def fetch_ecb_rates(
    _user_id: CurrentUserId,
    _admin: None = Depends(RequirePermission("admin")),
    service: I18nFoundationService = Depends(_get_service),
) -> dict:
    """Fetch latest exchange rates from ECB (admin only).

    Downloads the daily EUR reference rates and stores any new ones.
    Existing rates for the same date/pair are skipped.
    """
    count = await service.fetch_ecb_rates()
    return {"status": "ok", "new_rates": count}


@router.get("/exchange-rates/{rate_id}", response_model=ExchangeRateResponse)
async def get_exchange_rate(
    rate_id: uuid.UUID,
    service: I18nFoundationService = Depends(_get_service),
) -> ExchangeRateResponse:
    """Get a single exchange rate by ID."""
    rate = await service.get_exchange_rate(rate_id)
    return ExchangeRateResponse.model_validate(rate)


@router.patch("/exchange-rates/{rate_id}", response_model=ExchangeRateResponse)
async def update_exchange_rate(
    rate_id: uuid.UUID,
    data: ExchangeRateUpdate,
    _user_id: CurrentUserId,
    service: I18nFoundationService = Depends(_get_service),
) -> ExchangeRateResponse:
    """Update an exchange rate entry (auth required)."""
    rate = await service.update_exchange_rate(rate_id, data.model_dump(exclude_unset=True))
    return ExchangeRateResponse.model_validate(rate)


@router.delete(
    "/exchange-rates/{rate_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_exchange_rate(
    rate_id: uuid.UUID,
    _user_id: CurrentUserId,
    service: I18nFoundationService = Depends(_get_service),
) -> None:
    """Delete an exchange rate entry (auth required)."""
    await service.delete_exchange_rate(rate_id)


# ═══════════════════════════════════════════════════════════════════════════
#  Countries
# ═══════════════════════════════════════════════════════════════════════════


@router.get("/countries/", response_model=CountryListResponse)
async def list_countries(
    service: I18nFoundationService = Depends(_get_service),
    region: str | None = Query(default=None, description="Filter by region group (EU, DACH, etc.)"),
) -> CountryListResponse:
    """List all active countries, optionally filtered by region."""
    items = await service.list_countries(region_group=region)
    total = len(items)
    return CountryListResponse(
        items=[CountryResponse.model_validate(c) for c in items],
        total=total,
    )


@router.get("/countries/{iso_code}", response_model=CountryResponse)
async def get_country(
    iso_code: str,
    service: I18nFoundationService = Depends(_get_service),
) -> CountryResponse:
    """Get a country by its ISO 3166-1 alpha-2 code."""
    country = await service.get_country_by_iso(iso_code)
    return CountryResponse.model_validate(country)


# ═══════════════════════════════════════════════════════════════════════════
#  Work Calendars
# ═══════════════════════════════════════════════════════════════════════════


@router.get("/work-calendars/", response_model=WorkCalendarListResponse)
async def list_work_calendars(
    service: I18nFoundationService = Depends(_get_service),
    country_code: str | None = Query(default=None, description="Filter by country code"),
    year: str | None = Query(default=None, description="Filter by year (e.g. 2026)"),
) -> WorkCalendarListResponse:
    """List work calendars with optional filters."""
    items = await service.list_work_calendars(country_code=country_code, year=year)
    total = len(items)
    return WorkCalendarListResponse(
        items=[WorkCalendarResponse.model_validate(c) for c in items],
        total=total,
    )


@router.get("/work-calendars/working-days/", response_model=WorkingDaysResponse)
async def calculate_working_days(
    country_code: str = Query(..., min_length=2, max_length=2, description="ISO country code"),
    from_date: str = Query(..., description="Start date (ISO format)"),
    to_date: str = Query(..., description="End date (ISO format)"),
    service: I18nFoundationService = Depends(_get_service),
) -> WorkingDaysResponse:
    """Calculate the number of working days between two dates.

    Uses the country's work calendar to determine work days and holidays.
    Falls back to Monday-Friday if no calendar is found.
    """
    return await service.get_working_days(
        country_code=country_code,
        from_date=from_date,
        to_date=to_date,
    )


@router.post(
    "/work-calendars/",
    response_model=WorkCalendarResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_work_calendar(
    data: WorkCalendarCreate,
    _user_id: CurrentUserId,
    service: I18nFoundationService = Depends(_get_service),
) -> WorkCalendarResponse:
    """Create a new work calendar (auth required)."""
    calendar = await service.create_work_calendar(data.model_dump())
    return WorkCalendarResponse.model_validate(calendar)


@router.get("/work-calendars/{calendar_id}", response_model=WorkCalendarResponse)
async def get_work_calendar(
    calendar_id: uuid.UUID,
    service: I18nFoundationService = Depends(_get_service),
) -> WorkCalendarResponse:
    """Get a work calendar by ID."""
    calendar = await service.get_work_calendar(calendar_id)
    return WorkCalendarResponse.model_validate(calendar)


@router.patch("/work-calendars/{calendar_id}", response_model=WorkCalendarResponse)
async def update_work_calendar(
    calendar_id: uuid.UUID,
    data: WorkCalendarUpdate,
    _user_id: CurrentUserId,
    service: I18nFoundationService = Depends(_get_service),
) -> WorkCalendarResponse:
    """Update a work calendar (auth required)."""
    calendar = await service.update_work_calendar(
        calendar_id, data.model_dump(exclude_unset=True)
    )
    return WorkCalendarResponse.model_validate(calendar)


# ═══════════════════════════════════════════════════════════════════════════
#  Tax Configurations
# ═══════════════════════════════════════════════════════════════════════════


@router.get("/tax-configs/", response_model=TaxConfigListResponse)
async def list_tax_configs(
    service: I18nFoundationService = Depends(_get_service),
    country_code: str | None = Query(default=None, description="Filter by country code"),
    tax_type: str | None = Query(default=None, description="Filter by tax type (vat, gst, etc.)"),
) -> TaxConfigListResponse:
    """List tax configurations with optional filters."""
    items = await service.list_tax_configs(country_code=country_code, tax_type=tax_type)
    total = len(items)
    return TaxConfigListResponse(
        items=[TaxConfigResponse.model_validate(c) for c in items],
        total=total,
    )


@router.get("/tax-configs/by-country/{country_code}", response_model=TaxConfigListResponse)
async def get_active_taxes_for_country(
    country_code: str,
    service: I18nFoundationService = Depends(_get_service),
) -> TaxConfigListResponse:
    """Get all currently active tax configurations for a country.

    Active means effective_to is NULL or >= today.
    """
    items = await service.get_active_taxes_for_country(country_code)
    total = len(items)
    return TaxConfigListResponse(
        items=[TaxConfigResponse.model_validate(c) for c in items],
        total=total,
    )


@router.post(
    "/tax-configs/",
    response_model=TaxConfigResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_tax_config(
    data: TaxConfigCreate,
    _user_id: CurrentUserId,
    service: I18nFoundationService = Depends(_get_service),
) -> TaxConfigResponse:
    """Create a new tax configuration (auth required)."""
    config = await service.create_tax_config(data.model_dump())
    return TaxConfigResponse.model_validate(config)


@router.get("/tax-configs/{config_id}", response_model=TaxConfigResponse)
async def get_tax_config(
    config_id: uuid.UUID,
    service: I18nFoundationService = Depends(_get_service),
) -> TaxConfigResponse:
    """Get a tax configuration by ID."""
    config = await service.get_tax_config(config_id)
    return TaxConfigResponse.model_validate(config)


@router.patch("/tax-configs/{config_id}", response_model=TaxConfigResponse)
async def update_tax_config(
    config_id: uuid.UUID,
    data: TaxConfigUpdate,
    _user_id: CurrentUserId,
    service: I18nFoundationService = Depends(_get_service),
) -> TaxConfigResponse:
    """Update a tax configuration (auth required)."""
    config = await service.update_tax_config(config_id, data.model_dump(exclude_unset=True))
    return TaxConfigResponse.model_validate(config)
