# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Business logic of the norm pricing module.

Reads the pack data for the project's country, keeps the project's settings,
and derives graded hourly rates. The arithmetic itself lives in
:mod:`app.core.norm_bases` so validation and the API share one definition.
"""

from __future__ import annotations

import uuid
from decimal import Decimal, InvalidOperation
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import norm_bases
from app.modules.norm_pricing.repository import NormPricingRepository
from app.modules.norm_pricing.schemas import (
    CodeCheckOut,
    EstimatePricingSettings,
    FundingClassOut,
    LabeledOption,
    LabourRatesOut,
    MarkupCapOut,
    NormBaseOut,
    NormTypeOut,
    PricingProfile,
    RateOut,
)


def _s(value: Decimal | None) -> str | None:
    return None if value is None else format(value, "f")


def build_profile(
    country: str | None,
    settings: dict[str, Any],
    locale: str | None,
) -> PricingProfile:
    """The pack's offer for a country plus the project's stored choices."""
    bases = norm_bases.norm_bases_for(country)
    pricing = norm_bases.estimate_pricing_for(country)
    if not bases and pricing is None:
        return PricingProfile(available=False)
    label = norm_bases.label_in
    grading = pricing.grading if pricing else None
    return PricingProfile(
        available=True,
        pack_slug=(bases[0].pack_slug if bases else pricing.pack_slug if pricing else None),
        currency=pricing.currency if pricing else None,
        norm_bases=[
            NormBaseOut(
                key=b.key,
                name=b.name,
                classification_key=b.classification_key,
                code_example=b.code_example,
                types=[NormTypeOut(**{k: t.get(k) for k in ("prefix", "title", "collections")}) for t in b.types],
                legacy_prefixes=dict(b.legacy_prefixes),
            )
            for b in bases
        ],
        funding_classes=[
            FundingClassOut(
                key=f.key,
                label=label(f.label, locale),
                source=f.source,
                markup_caps=[
                    MarkupCapOut(key=c.key, label=label(c.label, locale), cap_percent=_s(c.cap_percent) or "")
                    for c in f.markup_caps
                ],
                investor_estimate_at_cap=f.investor_estimate_at_cap,
                min_quotes=f.min_quotes,
            )
            for f in (pricing.funding_classes if pricing else ())
        ],
        location_factors=[
            LabeledOption(key=f.key, label=label(f.label, locale), source=f.source, factor=_s(f.factor))
            for f in (pricing.location_factors if pricing else ())
        ],
        grades=[_s(g) or "" for g in sorted(grading.coefficients)] if grading else [],
        base_grade=_s(grading.base_grade) if grading else None,
        grading_status=grading.status if grading else None,
        default_monthly_hours=_s(pricing.default_monthly_hours) if pricing else None,
        settings=EstimatePricingSettings.model_validate(_clean(settings)),
    )


def _clean(settings: dict[str, Any]) -> dict[str, Any]:
    """Drop stored keys the schema no longer knows, so an old block still reads."""
    return {k: v for k, v in settings.items() if k in EstimatePricingSettings.model_fields and v not in ("",)}


def labour_rates(
    country: str | None,
    settings: dict[str, Any],
    grades: list[str],
) -> LabourRatesOut:
    """Hourly rates for ``grades`` from the project's wage and hours."""
    pricing = norm_bases.estimate_pricing_for(country)
    if pricing is None or pricing.grading is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No labour grading applies to this project")
    try:
        wage = Decimal(str(settings.get("estimate_wage")))
        hours = Decimal(str(settings.get("monthly_hours") or pricing.default_monthly_hours))
    except (InvalidOperation, ValueError, TypeError):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "Set the estimate wage and monthly hours first"
        ) from None
    location = pricing.location_factor(settings.get("labour_location"))
    factor = location.factor if location else Decimal("1")
    rates: list[RateOut] = []
    missing: list[str] = []
    for raw in grades or [format(pricing.grading.base_grade, "f")]:
        try:
            d = norm_bases.graded_hourly_rate(wage, hours, Decimal(raw), pricing.grading)
        except (ValueError, InvalidOperation):
            missing.append(raw)
            continue
        rates.append(
            RateOut(
                grade=_s(d.grade) or "",
                base_grade=_s(d.base_grade) or "",
                base_rate=_s(d.base_rate) or "",
                grade_one_rate=_s(d.grade_one_rate) or "",
                base_coefficient=_s(pricing.grading.coefficient(d.base_grade)) or "",
                coefficient=_s(d.coefficient) or "",
                rate=_s(d.rate) or "",
                location_factor=_s(factor) or "1",
                rate_with_location=_s(norm_bases.quantize_money(d.rate * factor)) or "",
            )
        )
    return LabourRatesOut(
        estimate_wage=_s(wage) or "", monthly_hours=_s(hours) or "", rates=rates, missing_grades=missing
    )


def check_code(country: str | None, code: str) -> CodeCheckOut:
    """Verdict on one code against the first norm base for the country."""
    bases = norm_bases.norm_bases_for(country)
    if not bases:
        return CodeCheckOut(status="no_base", code=code)
    c = bases[0].check(code)
    return CodeCheckOut(
        status=c.status,  # type: ignore[arg-type]
        code=c.code,
        suggested=c.suggested,
        old_prefix=c.old_prefix,
        new_prefix=c.new_prefix,
    )


class NormPricingService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = NormPricingRepository(session)

    async def _project(self, project_id: uuid.UUID) -> tuple[str | None, dict[str, Any]]:
        found = await self.repo.project_country_and_settings(project_id)
        if found is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")
        return found

    async def profile(self, project_id: uuid.UUID, locale: str | None) -> PricingProfile:
        country, settings = await self._project(project_id)
        return build_profile(country, settings, locale)

    async def update_settings(
        self, project_id: uuid.UUID, body: EstimatePricingSettings, locale: str | None
    ) -> PricingProfile:
        """Store the settings after checking each key against the pack's options."""
        country, _ = await self._project(project_id)
        pricing = norm_bases.estimate_pricing_for(country)
        if pricing is None:
            raise HTTPException(status.HTTP_409_CONFLICT, "No pack supplies pricing rules for this project's country")
        if body.funding_class and pricing.funding_class(body.funding_class) is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Unknown funding class {body.funding_class!r}")
        if body.labour_location and pricing.location_factor(body.labour_location) is None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, f"Unknown labour location {body.labour_location!r}"
            )
        stored = {k: v for k, v in body.model_dump(mode="json").items() if v is not None}
        await self.repo.save_settings(project_id, stored)
        return build_profile(country, stored, locale)

    async def labour_rates(self, project_id: uuid.UUID, grades: list[str]) -> LabourRatesOut:
        country, settings = await self._project(project_id)
        return labour_rates(country, settings, grades)

    async def check_code(self, project_id: uuid.UUID, code: str) -> CodeCheckOut:
        country, _ = await self._project(project_id)
        return check_code(country, code)
