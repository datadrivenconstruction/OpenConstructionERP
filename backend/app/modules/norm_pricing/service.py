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
    WritebackApply,
    WritebackPreview,
    WritebackResult,
    WritebackRow,
    WritebackSkip,
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
                grade_field=b.grade_field,
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
        grading_source=(grading.source or None) if grading else None,
        has_export_layout=bool(pricing and pricing.export_layout),
        default_monthly_hours=_s(pricing.default_monthly_hours) if pricing else None,
        settings=EstimatePricingSettings.model_validate(_clean(settings)),
    )


def _clean(settings: dict[str, Any]) -> dict[str, Any]:
    """Drop stored keys the schema no longer knows, so an old block still reads."""
    return {k: v for k, v in settings.items() if k in EstimatePricingSettings.model_fields and v not in ("",)}


def _rate_out(d: norm_bases.RateDerivation, grading: norm_bases.LabourGrading, factor: Decimal) -> RateOut:
    return RateOut(
        grade=_s(d.grade) or "",
        base_grade=_s(d.base_grade) or "",
        base_rate=_s(d.base_rate) or "",
        grade_one_rate=_s(d.grade_one_rate) or "",
        base_coefficient=_s(grading.coefficient(d.base_grade)) or "",
        coefficient=_s(d.coefficient) or "",
        rate=_s(d.rate) or "",
        location_factor=_s(factor) or "1",
        rate_with_location=_s(norm_bases.quantize_money(d.rate * factor)) or "",
    )


def _wage_and_hours(pricing: norm_bases.EstimatePricing, settings: dict[str, Any]) -> tuple[Decimal, Decimal]:
    try:
        wage = Decimal(str(settings.get("estimate_wage")))
        hours = Decimal(str(settings.get("monthly_hours") or pricing.default_monthly_hours))
    except (InvalidOperation, ValueError, TypeError):
        wage = hours = Decimal("NaN")
    if not wage.is_finite() or not hours.is_finite() or hours <= 0:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Set the estimate wage and monthly hours first")
    return wage, hours


def labour_rates(
    country: str | None,
    settings: dict[str, Any],
    grades: list[str],
) -> LabourRatesOut:
    """Hourly rates for ``grades`` from the project's wage and hours."""
    pricing = norm_bases.estimate_pricing_for(country)
    if pricing is None or pricing.grading is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No labour grading applies to this project")
    wage, hours = _wage_and_hours(pricing, settings)
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
        rates.append(_rate_out(d, pricing.grading, factor))
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
        title=c.title,
    )


_LABOUR_TYPES = frozenset({"labor", "labour"})


def _num(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool) or value == "":
        return None
    try:
        out = Decimal(str(value).strip().replace(",", "."))
    except (InvalidOperation, ValueError):
        return None
    return out if out.is_finite() else None


def plan_labour_writeback(
    country: str | None,
    settings: dict[str, Any],
    lines: list[dict[str, Any]],
    boq_id: str,
) -> WritebackPreview:
    """Which labour resources of a bill would take the project's graded rate.

    A labour row with a grade on the pack's scale gets ``V(grade)`` times the
    project's labour location factor, rounded to cents. A row whose rate already
    equals that counts as unchanged; a row with no grade, or a grade off the
    scale, is listed as skipped with the reason, never guessed. Nothing is written.
    """
    pricing = norm_bases.estimate_pricing_for(country)
    if pricing is None or pricing.grading is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No labour grading applies to this project")
    grading = pricing.grading
    wage, hours = _wage_and_hours(pricing, settings)
    location = pricing.location_factor(settings.get("labour_location"))
    factor = location.factor if location else Decimal("1")
    bases = norm_bases.norm_bases_for(country)
    grade_field = bases[0].grade_field if bases else "grade"
    labour_types = _LABOUR_TYPES | ({bases[0].labour_resource_type} if bases else set())
    changes: list[WritebackRow] = []
    skipped: list[WritebackSkip] = []
    unchanged = 0
    for line in lines:
        rows = (line.get("metadata") or {}).get("resources")
        for index, row in enumerate(rows if isinstance(rows, list) else []):
            if not isinstance(row, dict) or str(row.get("type") or "").strip().lower() not in labour_types:
                continue
            common = {
                "position_id": line["id"],
                "ordinal": str(line.get("ordinal") or ""),
                "resource_index": index,
                "resource_name": str(row.get("name") or row.get("code") or ""),
            }
            raw_grade = row.get(grade_field)
            grade = _num(raw_grade)
            if grade is None:
                skipped.append(WritebackSkip(**common, reason="no_grade"))
                continue
            try:
                d = norm_bases.graded_hourly_rate(wage, hours, grade, grading)
            except ValueError:
                skipped.append(WritebackSkip(**common, reason="grade_off_scale", grade=str(raw_grade)))
                continue
            proposed = norm_bases.quantize_money(d.rate * factor)
            current = _num(row.get("unit_rate"))
            if current is not None and current == proposed:
                unchanged += 1
                continue
            changes.append(
                WritebackRow(
                    **common,
                    description=str(line.get("description") or ""),
                    grade=_s(d.grade) or "",
                    current_rate=_s(current),
                    proposed_rate=_s(proposed) or "",
                    derivation=_rate_out(d, grading, factor),
                )
            )
    return WritebackPreview(
        boq_id=boq_id,
        estimate_wage=_s(wage) or "",
        monthly_hours=_s(hours) or "",
        location_factor=_s(factor) or "1",
        changes=changes,
        unchanged=unchanged,
        skipped=skipped,
    )


def match_confirmed(preview: WritebackPreview, body: WritebackApply) -> dict[str, dict[int, Decimal]]:
    """The confirmed rates per line, each one the figure the server derives now.

    Raises:
        HTTPException 409: an item the preview no longer proposes, or at another rate.
    """
    proposed = {(c.position_id, c.resource_index): Decimal(c.proposed_rate) for c in preview.changes}
    wanted: dict[str, dict[int, Decimal]] = {}
    for item in body.items:
        server = proposed.get((item.position_id, item.resource_index))
        if server is None or _num(item.rate) != server:
            raise HTTPException(status.HTTP_409_CONFLICT, "The bill or the rates changed since the preview")
        wanted.setdefault(item.position_id, {})[item.resource_index] = server
    return wanted


def _json_rate(value: Decimal) -> int | float:
    """Resource rates are JSON numbers; the client does arithmetic on them."""
    return int(value) if value == value.to_integral_value() else float(value)


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

    async def _bill_of(self, project_id: uuid.UUID, boq_id: uuid.UUID) -> None:
        if await self.repo.boq_project(boq_id) != project_id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Bill not found in this project")

    async def writeback_preview(self, project_id: uuid.UUID, boq_id: uuid.UUID) -> WritebackPreview:
        country, settings = await self._project(project_id)
        await self._bill_of(project_id, boq_id)
        return plan_labour_writeback(country, settings, await self.repo.boq_lines(boq_id), str(boq_id))

    async def writeback_apply(
        self, project_id: uuid.UUID, boq_id: uuid.UUID, body: WritebackApply, actor_id: uuid.UUID | None
    ) -> WritebackResult:
        """Write the confirmed rates, each re-derived here and checked against what the person saw.

        Each line is stored through the bill's own update path, so its unit rate
        is re-derived from the resources and the lock and audit log apply as for
        any edit.
        """
        from app.modules.boq.schemas import PositionUpdate
        from app.modules.boq.service import BOQService

        country, settings = await self._project(project_id)
        await self._bill_of(project_id, boq_id)
        lines = await self.repo.boq_lines(boq_id)
        wanted = match_confirmed(plan_labour_writeback(country, settings, lines, str(boq_id)), body)
        by_id = {line["id"]: line for line in lines}
        boq = BOQService(self.session)
        written = 0
        for position_id, changes in wanted.items():
            meta = dict(by_id[position_id]["metadata"])
            rows = [dict(r) if isinstance(r, dict) else r for r in meta.get("resources") or []]
            for index, rate in changes.items():
                rows[index]["unit_rate"] = _json_rate(rate)
                written += 1
            meta["resources"] = rows
            await boq.update_position(uuid.UUID(position_id), PositionUpdate(metadata=meta), actor_id=actor_id)
        return WritebackResult(updated_positions=len(wanted), updated_resources=written)

    async def export_sheet(self, project_id: uuid.UUID, boq_id: uuid.UUID, locale: str | None) -> tuple[bytes, str]:
        """The bill as the market's estimate sheet: ``(xlsx bytes, file name)``."""
        from app.modules.boq.service import BOQService
        from app.modules.norm_pricing.export import build_sheet, render_xlsx

        country, _ = await self._project(project_id)
        await self._bill_of(project_id, boq_id)
        pricing = norm_bases.estimate_pricing_for(country)
        if pricing is None or not pricing.export_layout:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "No estimate sheet layout applies to this project")
        bases = norm_bases.norm_bases_for(country)
        structured = await BOQService(self.session).get_boq_structured_for_export(boq_id, False)
        payload = structured.model_dump(mode="json")
        try:
            sheet = build_sheet(
                pricing.export_layout,
                payload,
                classification_key=bases[0].classification_key if bases else "",
                locale=locale,
            )
        except ValueError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from None
        name = str(payload.get("name") or "estimate")
        return render_xlsx(sheet, heading=name), f"{name}.xlsx"
