# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Conceptual (ROM) estimate engine and persistence service.

This module holds the elemental cost-per-m2 reference data and the pure,
database-free estimator that turns a handful of inputs (building type, gross
floor area, quality level, region) into a headline total, a six-element cost
breakdown and an honest accuracy band. It is the day-one starting point of a
project, before any detailed take-off or BOQ exists.

Design (kept deliberately clear and simple for a worldwide user):

- International by default. No hardcoded currency: base rates are expressed in a
  neutral *reference basis* and adjusted by a data-driven regional cost factor
  whose worldwide default is ``1`` (the ``global`` region). Areas may be entered
  in metric or imperial units and are converted to canonical m2 before any
  benchmark, so two projects measured in different unit systems compare exactly.
- Explainable. Every total is returned with the elemental breakdown that built
  it and a plain-language note, so a user can trust the number.
- Honest about precision. A ROM figure is order-of-magnitude, so it always
  carries an accuracy band. The band widens when no regional data is applied.

The heavy lifting (Decimal-exact arithmetic, unit conversion, guards, cost per
m2 of gross floor area) reuses the shared elemental primitives in
:mod:`app.modules.costmodel.elemental` rather than re-implementing them.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.costmodel.elemental import (
    ElementInput,
    apply_regional_factor,
    build_elemental_estimate,
    to_canonical_quantity,
)
from app.modules.rom_estimate.models import RomEstimate
from app.modules.rom_estimate.schemas import (
    RomAccuracyBand,
    RomBuildingTypeOption,
    RomCreateBoqRequest,
    RomCreateBoqResponse,
    RomElementBreakdown,
    RomElementOption,
    RomEstimateRequest,
    RomEstimateResult,
    RomFactorOption,
    RomReconciliation,
    RomReferenceResponse,
)

if TYPE_CHECKING:
    from app.modules.boq.service import BOQService

_CENTS = Decimal("0.01")


def _round_money(value: Decimal) -> Decimal:
    """Round a Decimal to 2 places (money precision), half-up."""
    return value.quantize(_CENTS, rounding=ROUND_HALF_UP)


# ── Elemental categories (canonical order, stable keys) ──────────────────────
# The six-element split mirrors the elemental cost-planning method used in
# early-stage estimating (substructure, superstructure, envelope, services,
# finishes, external works). Keys are stable so the UI can translate labels.

ELEMENT_LABELS: dict[str, str] = {
    "substructure": "Substructure",
    "superstructure": "Superstructure",
    "envelope": "Envelope",
    "services": "Building services (MEP)",
    "finishes": "Finishes",
    "externals": "External works",
}
ELEMENT_KEYS: tuple[str, ...] = tuple(ELEMENT_LABELS)


# ── Reference data ───────────────────────────────────────────────────────────


@dataclass(frozen=True)
class BuildingTypeProfile:
    """Reference profile for one building type.

    ``base_rate_per_m2`` is the indicative cost per m2 of gross floor area at
    standard quality on the worldwide (``global``) region, in the neutral
    reference basis. ``shares`` splits that rate across the six elements and
    always sums to 1. ``accuracy_low_pct`` / ``accuracy_high_pct`` are the
    signed percentage bounds of the order-of-magnitude band for this type.
    """

    label: str
    base_rate_per_m2: Decimal
    shares: dict[str, Decimal]
    accuracy_low_pct: Decimal
    accuracy_high_pct: Decimal


def _shares(sub: str, sup: str, env: str, serv: str, fin: str, ext: str) -> dict[str, Decimal]:
    """Build an ordered element-share map from six decimal strings (sum = 1)."""
    return {
        "substructure": Decimal(sub),
        "superstructure": Decimal(sup),
        "envelope": Decimal(env),
        "services": Decimal(serv),
        "finishes": Decimal(fin),
        "externals": Decimal(ext),
    }


# Indicative base rates (reference basis, cost per m2 of GFA) and elemental
# splits per building type. The relative magnitudes reflect that services-heavy
# types (healthcare, hospitality) cost more per m2 and carry more MEP, while
# sheds (warehouse) are structure-dominated and cheap per m2.
BUILDING_TYPES: dict[str, BuildingTypeProfile] = {
    "residential_low": BuildingTypeProfile(
        "Low-rise housing",
        Decimal("1400"),
        _shares("0.10", "0.24", "0.20", "0.18", "0.18", "0.10"),
        Decimal("-20"),
        Decimal("30"),
    ),
    "residential_multi": BuildingTypeProfile(
        "Apartment building",
        Decimal("1800"),
        _shares("0.09", "0.26", "0.19", "0.21", "0.16", "0.09"),
        Decimal("-22"),
        Decimal("32"),
    ),
    "office": BuildingTypeProfile(
        "Office building",
        Decimal("2000"),
        _shares("0.08", "0.22", "0.18", "0.30", "0.14", "0.08"),
        Decimal("-25"),
        Decimal("35"),
    ),
    "retail": BuildingTypeProfile(
        "Retail / shop",
        Decimal("1500"),
        _shares("0.09", "0.20", "0.17", "0.28", "0.18", "0.08"),
        Decimal("-25"),
        Decimal("35"),
    ),
    "industrial": BuildingTypeProfile(
        "Industrial / factory",
        Decimal("900"),
        _shares("0.12", "0.30", "0.22", "0.16", "0.08", "0.12"),
        Decimal("-20"),
        Decimal("30"),
    ),
    "warehouse": BuildingTypeProfile(
        "Warehouse / logistics",
        Decimal("700"),
        _shares("0.14", "0.32", "0.22", "0.12", "0.06", "0.14"),
        Decimal("-18"),
        Decimal("28"),
    ),
    "education": BuildingTypeProfile(
        "School / education",
        Decimal("2100"),
        _shares("0.09", "0.22", "0.18", "0.26", "0.17", "0.08"),
        Decimal("-25"),
        Decimal("38"),
    ),
    "healthcare": BuildingTypeProfile(
        "Hospital / healthcare",
        Decimal("3400"),
        _shares("0.07", "0.18", "0.15", "0.38", "0.16", "0.06"),
        Decimal("-30"),
        Decimal("50"),
    ),
    "hospitality": BuildingTypeProfile(
        "Hotel / hospitality",
        Decimal("2600"),
        _shares("0.07", "0.20", "0.16", "0.30", "0.21", "0.06"),
        Decimal("-28"),
        Decimal("45"),
    ),
    "civic": BuildingTypeProfile(
        "Civic / cultural",
        Decimal("2400"),
        _shares("0.08", "0.22", "0.20", "0.26", "0.16", "0.08"),
        Decimal("-30"),
        Decimal("48"),
    ),
    "parking": BuildingTypeProfile(
        "Car park",
        Decimal("750"),
        _shares("0.16", "0.40", "0.14", "0.10", "0.06", "0.14"),
        Decimal("-18"),
        Decimal("28"),
    ),
}


@dataclass(frozen=True)
class FactorOption:
    """A named multiplier (quality level or regional cost factor)."""

    label: str
    factor: Decimal


# Quality levels: economy through luxury, applied as a multiplier on the base
# rate. Standard is the 1.0 reference.
QUALITY_LEVELS: dict[str, FactorOption] = {
    "economy": FactorOption("Economy", Decimal("0.80")),
    "standard": FactorOption("Standard", Decimal("1.00")),
    "premium": FactorOption("Premium", Decimal("1.28")),
    "luxury": FactorOption("Luxury", Decimal("1.65")),
}

# Regional cost factors. Data-driven multipliers with a documented worldwide
# default of 1 (``global``); there is no single country hardcoded as "the"
# answer. Use ``global`` when the locality is unknown - the accuracy band then
# widens to reflect the missing local data.
REGIONS: dict[str, FactorOption] = {
    "global": FactorOption("Global (worldwide default)", Decimal("1.00")),
    "north_america": FactorOption("North America", Decimal("1.10")),
    "western_europe": FactorOption("Western Europe", Decimal("1.15")),
    "northern_europe": FactorOption("Northern Europe", Decimal("1.20")),
    "southern_europe": FactorOption("Southern Europe", Decimal("0.92")),
    "eastern_europe": FactorOption("Eastern Europe", Decimal("0.72")),
    "middle_east": FactorOption("Middle East", Decimal("0.88")),
    "east_asia": FactorOption("East Asia", Decimal("0.95")),
    "southeast_asia": FactorOption("Southeast Asia", Decimal("0.60")),
    "south_asia": FactorOption("South Asia", Decimal("0.48")),
    "oceania": FactorOption("Oceania", Decimal("1.18")),
    "latin_america": FactorOption("Latin America", Decimal("0.68")),
    "africa": FactorOption("Africa", Decimal("0.62")),
}

# Estimate class metadata and the extra band widening applied when no regional
# cost data is used (the estimate is left on the worldwide default).
ESTIMATE_CLASS: str = "order_of_magnitude"
ESTIMATE_CLASS_LABEL: str = "Order-of-magnitude (concept)"
_GLOBAL_REGION_KEY: str = "global"
_UNLOCALIZED_WIDEN_LOW: Decimal = Decimal("-8")
_UNLOCALIZED_WIDEN_HIGH: Decimal = Decimal("12")
_BAND_LOW_FLOOR: Decimal = Decimal("-60")
_BAND_HIGH_CAP: Decimal = Decimal("150")

REFERENCE_BASIS_NOTE: str = (
    "Base rates are indicative order-of-magnitude figures in a neutral reference "
    "basis, adjusted by a regional cost factor (worldwide default 1). Treat the "
    "result as a starting point and refine it with a detailed take-off."
)


# ── Validation helpers (clear messages listing the valid options) ────────────


def _resolve_building_type(key: str) -> BuildingTypeProfile:
    profile = BUILDING_TYPES.get((key or "").strip().lower())
    if profile is None:
        known = ", ".join(sorted(BUILDING_TYPES))
        raise ValueError(f"Unknown building type {key!r}. Choose one of: {known}.")
    return profile


def _resolve_quality(key: str) -> tuple[str, FactorOption]:
    norm = (key or "").strip().lower()
    option = QUALITY_LEVELS.get(norm)
    if option is None:
        known = ", ".join(QUALITY_LEVELS)
        raise ValueError(f"Unknown quality level {key!r}. Choose one of: {known}.")
    return norm, option


def _resolve_region(key: str) -> tuple[str, FactorOption]:
    norm = (key or "").strip().lower()
    option = REGIONS.get(norm)
    if option is None:
        known = ", ".join(REGIONS)
        raise ValueError(f"Unknown region {key!r}. Choose one of: {known}.")
    return norm, option


# ── Pure estimator ───────────────────────────────────────────────────────────


def _reconcile_to_total(amounts: list[Decimal], total: Decimal) -> list[Decimal]:
    """Nudge the largest element so the breakdown sums exactly to ``total``.

    Rounding each element independently can leave a few cents of residue against
    the headline total. Adding that residue to the largest line keeps the
    breakdown internally consistent (it always sums to the total shown), which
    is what a user expects when they read the lines.
    """
    if not amounts:
        return amounts
    residual = total - sum(amounts)
    if residual == 0:
        return amounts
    largest_index = max(range(len(amounts)), key=lambda i: amounts[i])
    adjusted = list(amounts)
    adjusted[largest_index] = _round_money(adjusted[largest_index] + residual)
    return adjusted


def build_rom_estimate(request: RomEstimateRequest) -> RomEstimateResult:
    """Build a conceptual (ROM) estimate from minimal input.

    The total is ``base rate x quality factor x regional factor x gross floor
    area`` (in canonical m2). It is split across the six elements by the
    building type's characteristic shares, and returned with an
    order-of-magnitude accuracy band.

    Args:
        request: The validated request (building type, GFA, quality, region,
            optional unit and currency).

    Returns:
        A fully populated :class:`RomEstimateResult`.

    Raises:
        ValueError: When the building type, quality or region is unknown, the
            unit is unsupported, or the gross floor area is not positive.
    """
    profile = _resolve_building_type(request.building_type)
    building_key = request.building_type.strip().lower()
    quality_key, quality = _resolve_quality(request.quality)
    region_key, region = _resolve_region(request.region)

    # Canonical m2 for the headline benchmark and a positive-area guard. The
    # rates below are per m2, so the whole estimate is computed on the canonical
    # metric area; a GFA entered in ft2 therefore yields the same cost per m2 and
    # total as the identical area entered in m2.
    gfa_canonical, canonical_unit = to_canonical_quantity(request.gross_floor_area, request.gfa_unit)
    if gfa_canonical <= 0:
        raise ValueError("Gross floor area must be greater than zero to build an estimate.")

    # Base cost per m2: the estimator's own rate when supplied (so the currency
    # becomes a real figure rather than a neutral reference basis), else the
    # building-type reference rate. A missing or non-positive override falls back
    # to the reference so the number is never anchored to nonsense.
    override = request.base_rate_per_m2_override
    use_override = override is not None and override.is_finite() and override > 0
    base_rate_per_m2 = override if use_override else profile.base_rate_per_m2

    # One elemental input per category; the quality factor is baked into the
    # per-element rate, the regional factor is applied by the shared engine so
    # the resulting notes explain it explicitly. Quantity is the canonical m2
    # area so money is always (m2 x cost-per-m2), never (ft2 x cost-per-m2).
    quality_base = base_rate_per_m2 * quality.factor
    elements: list[ElementInput] = [
        ElementInput(
            name=ELEMENT_LABELS[key],
            quantity=gfa_canonical,
            unit=canonical_unit,
            unit_rate=quality_base * profile.shares[key],
        )
        for key in ELEMENT_KEYS
    ]

    estimate = build_elemental_estimate(
        elements,
        regional_factor=region.factor,
        gross_floor_area=gfa_canonical,
        gross_floor_area_unit=canonical_unit,
        currency=request.currency,
    )

    # Region-applied amounts, reconciled so the breakdown sums to the total.
    amounts = _reconcile_to_total([line.adjusted_total for line in estimate.elements], estimate.total)
    breakdown = [
        RomElementBreakdown(
            key=key,
            label=ELEMENT_LABELS[key],
            cost_share_pct=_round_money(profile.shares[key] * Decimal("100")),
            rate_per_m2=apply_regional_factor(quality_base * profile.shares[key], region.factor),
            amount=amounts[index],
        )
        for index, key in enumerate(ELEMENT_KEYS)
    ]

    accuracy = _build_accuracy_band(profile, region_key, estimate.total)
    cost_per_m2 = estimate.cost_per_gfa or Decimal("0")

    notes = (
        f"Order-of-magnitude estimate for a {profile.label.lower()} of "
        f"{gfa_canonical} m2 at {quality.label.lower()} quality, {region.label}. "
        f"Cost per m2 is {cost_per_m2}, giving a total of {estimate.total}. "
        f"Realistic range {accuracy.low_amount} to {accuracy.high_amount} "
        f"({accuracy.low_pct}% to +{accuracy.high_pct}%). Refine with a detailed take-off."
    )

    return RomEstimateResult(
        building_type=building_key,
        building_type_label=profile.label,
        quality=quality_key,
        quality_label=quality.label,
        region=region_key,
        region_label=region.label,
        currency=request.currency,
        gross_floor_area=request.gross_floor_area,
        gfa_unit=request.gfa_unit,
        gfa_canonical_m2=gfa_canonical,
        quality_factor=quality.factor,
        regional_factor=region.factor,
        cost_per_m2=cost_per_m2,
        subtotal_base=estimate.subtotal_base,
        total=estimate.total,
        accuracy=accuracy,
        elements=breakdown,
        notes=notes,
    )


def _build_accuracy_band(profile: BuildingTypeProfile, region_key: str, total: Decimal) -> RomAccuracyBand:
    """Compute the accuracy band, widening it when no regional data is applied."""
    low_pct = profile.accuracy_low_pct
    high_pct = profile.accuracy_high_pct
    localized = region_key != _GLOBAL_REGION_KEY
    if not localized:
        low_pct += _UNLOCALIZED_WIDEN_LOW
        high_pct += _UNLOCALIZED_WIDEN_HIGH
    low_pct = max(low_pct, _BAND_LOW_FLOOR)
    high_pct = min(high_pct, _BAND_HIGH_CAP)

    low_amount = _round_money(total * (Decimal("1") + low_pct / Decimal("100")))
    high_amount = _round_money(total * (Decimal("1") + high_pct / Decimal("100")))

    if localized:
        note = (
            "Order-of-magnitude accuracy. A regional cost factor was applied, so "
            "the range reflects concept-stage uncertainty for this building type."
        )
    else:
        note = (
            "Order-of-magnitude accuracy, widened because no regional cost factor "
            "was applied (region left at the worldwide default). Select a region "
            "to narrow the range."
        )

    return RomAccuracyBand(
        estimate_class=ESTIMATE_CLASS,
        estimate_class_label=ESTIMATE_CLASS_LABEL,
        low_pct=low_pct,
        high_pct=high_pct,
        low_amount=low_amount,
        high_amount=high_amount,
        localized=localized,
        note=note,
    )


# ── Reference metadata ───────────────────────────────────────────────────────


def build_reference() -> RomReferenceResponse:
    """Return the full reference table for populating the UI form."""
    return RomReferenceResponse(
        building_types=[
            RomBuildingTypeOption(
                key=key,
                label=profile.label,
                base_rate_per_m2=profile.base_rate_per_m2,
                accuracy_low_pct=profile.accuracy_low_pct,
                accuracy_high_pct=profile.accuracy_high_pct,
            )
            for key, profile in BUILDING_TYPES.items()
        ],
        quality_levels=[
            RomFactorOption(key=key, label=opt.label, factor=opt.factor) for key, opt in QUALITY_LEVELS.items()
        ],
        regions=[RomFactorOption(key=key, label=opt.label, factor=opt.factor) for key, opt in REGIONS.items()],
        elements=[RomElementOption(key=key, label=label) for key, label in ELEMENT_LABELS.items()],
        default_quality="standard",
        default_region="global",
        reference_basis_note=REFERENCE_BASIS_NOTE,
    )


# ── Persistence (map a result to a stored row, and the reverse) ──────────────


def rom_result_to_row_kwargs(
    result: RomEstimateResult,
    *,
    project_id: uuid.UUID,
    name: str,
    created_by: uuid.UUID | None,
) -> dict[str, object]:
    """Map a computed result to :class:`RomEstimate` column kwargs (pure).

    Money and ratios are stored as strings (the platform Decimal-as-string
    convention). The breakdown is stored as JSON so the saved estimate keeps a
    faithful snapshot even if the reference rates later change.
    """
    return {
        "project_id": project_id,
        "name": (name or "").strip(),
        "building_type": result.building_type,
        "quality": result.quality,
        "region": result.region,
        "currency": result.currency,
        "gross_floor_area": format(result.gross_floor_area, "f"),
        "gfa_unit": result.gfa_unit,
        "cost_per_m2": format(result.cost_per_m2, "f"),
        "total_cost": format(result.total, "f"),
        "estimate_class": result.accuracy.estimate_class,
        "accuracy_low_pct": format(result.accuracy.low_pct, "f"),
        "accuracy_high_pct": format(result.accuracy.high_pct, "f"),
        "accuracy_low_amount": format(result.accuracy.low_amount, "f"),
        "accuracy_high_amount": format(result.accuracy.high_amount, "f"),
        "breakdown": [line.model_dump(mode="json") for line in result.elements],
        "created_by": created_by,
    }


# ── Reconciliation (concept vs live detailed BOQ) ────────────────────────────
# Once a detailed BOQ exists, nobody sees whether the design still tracks the
# concept it was approved on. These pure helpers turn a stored conceptual total
# and the live detailed total into an explicit drift with a traffic-light band,
# so the concept number stays a live benchmark (design-development cost control).

STATUS_NO_BASELINE: str = "no_baseline"
STATUS_ON_TRACK: str = "on_track"
STATUS_OVER: str = "over"
STATUS_UNDER: str = "under"

# Default on-track tolerance. Design-development cost control classically flags
# drift beyond roughly +-10% of the approved concept, so 10% is the sensible
# worldwide default; it is a plain percentage (not a fraction).
DEFAULT_RECONCILE_TOLERANCE_PCT: Decimal = Decimal("10")


def _parse_money(value: str | Decimal | None) -> Decimal | None:
    """Parse a stored money string to a finite Decimal, or ``None`` when unusable.

    Args:
        value: A Decimal-as-string (the storage convention), a Decimal, or None.

    Returns:
        The finite Decimal value, or ``None`` when the input is missing or does
        not parse to a finite number.
    """
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value if value.is_finite() else None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return parsed if parsed.is_finite() else None


def build_reconciliation(
    *,
    project_id: uuid.UUID,
    conceptual_total: Decimal | None,
    detailed_total: Decimal,
    currency: str = "",
    conceptual_currency: str = "",
    boq_count: int = 0,
    conceptual_estimate_id: uuid.UUID | None = None,
    conceptual_name: str = "",
    conceptual_created_at: datetime | None = None,
    tolerance_pct: Decimal = DEFAULT_RECONCILE_TOLERANCE_PCT,
) -> RomReconciliation:
    """Reconcile a conceptual total against the live detailed BOQ total (pure).

    The variance is ``detailed_total - conceptual_total`` and the percentage is
    that variance over the conceptual total. The status band is:

    - ``no_baseline`` when there is no conceptual total, or it is not positive
      (a zero baseline is not a usable benchmark for percentage drift);
    - ``over`` when the detailed total exceeds the concept by more than the
      tolerance;
    - ``under`` when it falls short by more than the tolerance;
    - ``on_track`` otherwise.

    Args:
        project_id: The project the reconciliation is for.
        conceptual_total: The stored conceptual baseline total, or ``None``.
        detailed_total: The live detailed BOQ total (``Decimal("0")`` with no BOQ).
        currency: Currency the reconciliation is expressed in (BOQ base currency).
        conceptual_currency: Currency label stored on the conceptual estimate.
        boq_count: Number of BOQs summed into the detailed total.
        conceptual_estimate_id: Id of the baseline estimate, or ``None``.
        conceptual_name: Name of the baseline estimate.
        conceptual_created_at: When the baseline estimate was saved.
        tolerance_pct: On-track tolerance band (absolute percent).

    Returns:
        A fully populated :class:`RomReconciliation`.
    """
    detailed = detailed_total if detailed_total is not None else Decimal("0")
    tolerance = abs(tolerance_pct)
    base_currency = (currency or "").strip().upper()
    concept_currency = (conceptual_currency or "").strip().upper()
    reconciliation_currency = base_currency or concept_currency
    mismatch = bool(base_currency and concept_currency and base_currency != concept_currency)

    common = {
        "project_id": project_id,
        "detailed_total": detailed,
        "tolerance_pct": tolerance,
        "currency": reconciliation_currency,
        "conceptual_currency": concept_currency,
        "currency_mismatch": mismatch,
        "boq_count": boq_count,
        "conceptual_estimate_id": conceptual_estimate_id,
        "conceptual_name": conceptual_name,
        "conceptual_created_at": conceptual_created_at,
    }

    # No usable baseline (missing, non-positive, or non-finite): report the
    # detailed side honestly but leave the variance null - there is nothing
    # meaningful to divide by. This is the zero / again-zero guard.
    if conceptual_total is None or not conceptual_total.is_finite() or conceptual_total <= 0:
        return RomReconciliation(
            status=STATUS_NO_BASELINE,
            conceptual_total=conceptual_total,
            variance_amount=None,
            variance_pct=None,
            **common,
        )

    variance_amount = detailed - conceptual_total
    variance_pct = _round_money(variance_amount / conceptual_total * Decimal("100"))
    if variance_pct > tolerance:
        status = STATUS_OVER
    elif variance_pct < -tolerance:
        status = STATUS_UNDER
    else:
        status = STATUS_ON_TRACK

    return RomReconciliation(
        status=status,
        conceptual_total=conceptual_total,
        variance_amount=variance_amount,
        variance_pct=variance_pct,
        **common,
    )


# ── Persistence (session-bound) ──────────────────────────────────────────────


@dataclass
class RomEstimateService:
    """Session-bound persistence for saved conceptual estimates."""

    session: AsyncSession
    _computed: object = field(default=None, compare=False)

    async def create_estimate(
        self,
        project_id: uuid.UUID,
        request: RomEstimateRequest,
        created_by: uuid.UUID | None,
    ) -> RomEstimate:
        """Compute a ROM estimate and persist it against a project.

        Raises:
            ValueError: When the request is invalid (propagated from the pure
                estimator so the router can turn it into a 422).
        """
        result = build_rom_estimate(request)
        row = RomEstimate(
            **rom_result_to_row_kwargs(
                result,
                project_id=project_id,
                name=request.name,
                created_by=created_by,
            )
        )
        self.session.add(row)
        await self.session.flush()
        await self.session.refresh(row)
        return row

    async def list_estimates(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
    ) -> list[RomEstimate]:
        """List a project's saved estimates, newest first."""
        stmt = (
            select(RomEstimate)
            .where(RomEstimate.project_id == project_id)
            .order_by(RomEstimate.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_estimate(self, estimate_id: uuid.UUID) -> RomEstimate | None:
        """Fetch a single saved estimate by id (or ``None``)."""
        return await self.session.get(RomEstimate, estimate_id)

    async def delete_estimate(self, estimate_id: uuid.UUID) -> None:
        """Delete a saved estimate."""
        row = await self.session.get(RomEstimate, estimate_id)
        if row is not None:
            await self.session.delete(row)
            await self.session.flush()

    async def latest_estimate(self, project_id: uuid.UUID) -> RomEstimate | None:
        """Return the most-recent saved conceptual estimate for a project (or None).

        This is the baseline the detailed design is reconciled against: the last
        concept the team saved for the project.
        """
        stmt = (
            select(RomEstimate)
            .where(RomEstimate.project_id == project_id)
            .order_by(RomEstimate.created_at.desc())
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def _collect_project_boq_ids(
        self,
        boq_service: BOQService,
        project_id: uuid.UUID,
    ) -> list[uuid.UUID]:
        """Collect every BOQ id for a project, paging the BOQ list to avoid a cap.

        Pages through :meth:`BOQService.list_boqs_for_project` so a project with
        many BOQs still contributes its full detailed total (the single-page
        default limit would silently truncate it).
        """
        ids: list[uuid.UUID] = []
        offset = 0
        page = 200
        while True:
            boqs, total = await boq_service.list_boqs_for_project(project_id, offset=offset, limit=page)
            ids.extend(boq.id for boq in boqs)
            offset += len(boqs)
            if not boqs or offset >= total:
                break
        return ids

    async def _sum_detailed_total(
        self,
        boq_service: BOQService,
        boq_ids: list[uuid.UUID],
    ) -> tuple[Decimal, str]:
        """Sum the FX-correct grand total of every BOQ into the project base currency.

        Reuses :meth:`BOQService.compute_boq_totals`, the same currency-aware
        rollup the BOQ list / detail / export paths use, so the detailed number
        is comparable to nothing but itself elsewhere in the app. Each per-BOQ
        ``grand_total`` is already quantized to cents, so bridging it through
        ``Decimal(str(...))`` is exact (no binary-float drift), and the sum stays
        Decimal throughout.

        Returns:
            ``(detailed_total, base_currency)`` - the summed total and the project
            base currency reported by the rollup (empty when there is no BOQ).
        """
        if not boq_ids:
            return Decimal("0"), ""
        breakdown = await boq_service.compute_boq_totals(boq_ids)
        total = Decimal("0")
        base_currency = ""
        for data in breakdown.values():
            total += Decimal(str(data.get("grand_total", 0) or 0))
            if not base_currency:
                base_currency = str(data.get("base_currency") or "")
        return _round_money(total), base_currency

    async def reconcile_with_boq(
        self,
        project_id: uuid.UUID,
        *,
        tolerance_pct: Decimal = DEFAULT_RECONCILE_TOLERANCE_PCT,
    ) -> RomReconciliation:
        """Reconcile the project's conceptual baseline against its live BOQ total.

        Reads the most-recent saved conceptual (ROM) estimate and the FX-correct
        sum of the project's detailed BOQ grand totals, then computes the drift.
        Read only - it persists nothing. Degrades gracefully: with no saved
        conceptual estimate the status is ``no_baseline``; with no BOQ the
        detailed total is ``0``.

        Args:
            project_id: The project to reconcile.
            tolerance_pct: On-track tolerance band (absolute percent).

        Returns:
            The computed :class:`RomReconciliation`.
        """
        # Local import: the BOQ service is only needed for this read path and a
        # module-level import would couple module load order unnecessarily.
        from app.modules.boq.service import BOQService

        baseline = await self.latest_estimate(project_id)
        conceptual_total = _parse_money(baseline.total_cost) if baseline is not None else None
        conceptual_currency = baseline.currency if baseline is not None else ""

        boq_service = BOQService(self.session)
        boq_ids = await self._collect_project_boq_ids(boq_service, project_id)
        detailed_total, base_currency = await self._sum_detailed_total(boq_service, boq_ids)

        return build_reconciliation(
            project_id=project_id,
            conceptual_total=conceptual_total,
            detailed_total=detailed_total,
            currency=base_currency,
            conceptual_currency=conceptual_currency,
            boq_count=len(boq_ids),
            conceptual_estimate_id=baseline.id if baseline is not None else None,
            conceptual_name=baseline.name if baseline is not None else "",
            conceptual_created_at=baseline.created_at if baseline is not None else None,
            tolerance_pct=tolerance_pct,
        )

    # ── Handoff: concept -> detailed (seed a provisional BOQ) ────────────────

    async def create_boq_from_rom(
        self,
        project_id: uuid.UUID,
        request: RomCreateBoqRequest,
        created_by: uuid.UUID | None,
    ) -> RomCreateBoqResponse:
        """Save a ROM estimate as the project baseline and seed a provisional BOQ.

        This is the day-one handoff from concept to detailed estimating:

        (a) The conceptual estimate is persisted as the project baseline by
            reusing :meth:`create_estimate` (so the concept-vs-detailed
            reconciliation immediately goes live), and

        (b) a draft BOQ is created whose six elemental sections each carry one
            provisional lump-sum line priced at the concept rate per m2
            (quantity = gross floor area in canonical m2, unit rate = the
            element's cost per m2, so the line total reproduces the concept
            amount). Every row is marked ``source="rom_estimate"`` and the BOQ
            metadata is stamped with the concept baseline (building type, GFA,
            cost per m2, region, quality, currency and total) so the handoff is
            fully traceable and can be refined with a detailed take-off.

        Money stays Decimal-as-string end to end (no binary-float arithmetic).
        The BOQ is built from the persisted breakdown snapshot, so it always
        matches the saved baseline exactly.

        Args:
            project_id: The project the estimate and BOQ belong to.
            request: The estimate inputs plus the name for the created BOQ.
            created_by: The acting user's id (stored on the saved estimate).

        Returns:
            A :class:`RomCreateBoqResponse` with the new BOQ id, the saved
            estimate id and the section/position counts.

        Raises:
            ValueError: When the estimate input is invalid (propagated from the
                pure estimator so the router can turn it into a 422).
        """
        # (a) Persist the conceptual estimate as the project baseline.
        row = await self.create_estimate(project_id, request, created_by)

        # Local imports: the BOQ models/repositories are only needed on this
        # write path, and a module-level import would couple module load order
        # (mirrors the ``reconcile_with_boq`` read path above).
        from app.modules.boq.models import BOQ, Position
        from app.modules.boq.repository import BOQRepository, PositionRepository

        boq_repo = BOQRepository(self.session)
        position_repo = PositionRepository(self.session)

        currency = row.currency or ""
        profile = BUILDING_TYPES.get(row.building_type)
        building_label = profile.label if profile is not None else row.building_type

        # Canonical m2 for the seeded quantities so a GFA entered in ft2 still
        # produces per-m2 line items whose total reconstructs the element amount.
        canonical_gfa, _canonical_unit = to_canonical_quantity(
            _parse_money(row.gross_floor_area) or Decimal("0"),
            row.gfa_unit,
        )
        gfa_str = format(canonical_gfa, "f")

        boq_name = (request.boq_name or "").strip() or f"{building_label} - concept estimate"
        boq = BOQ(
            project_id=project_id,
            name=boq_name[:255],
            description=(
                "Provisional bill of quantities seeded from the conceptual (ROM) "
                "estimate. Each section carries one concept-rate allowance to be "
                "refined with a detailed take-off."
            ),
            status="draft",
            estimate_type="order_of_magnitude",
            metadata_={
                "source": "rom_estimate",
                "rom_estimate_id": str(row.id),
                "rom_baseline": {
                    "building_type": row.building_type,
                    "building_type_label": building_label,
                    "gross_floor_area": gfa_str,
                    "gfa_unit": "m2",
                    "cost_per_m2": row.cost_per_m2,
                    "region": row.region,
                    "quality": row.quality,
                    "currency": currency,
                    "total": row.total_cost,
                },
            },
        )
        boq = await boq_repo.create(boq)

        # (b) One elemental section + one concept-rate line per element, built
        #     from the persisted breakdown snapshot (single source of truth).
        sections_created = 0
        positions_created = 0
        sort = 0
        for idx, line in enumerate(row.breakdown or []):
            if not isinstance(line, dict):
                continue
            key = str(line.get("key", "") or "")
            label = str(line.get("label", "") or key or "Element")
            rate = _parse_money(line.get("rate_per_m2")) or Decimal("0")
            amount = _parse_money(line.get("amount")) or Decimal("0")
            ordinal = f"{idx + 1:02d}"

            section = Position(
                boq_id=boq.id,
                parent_id=None,
                ordinal=ordinal,
                description=label,
                unit="section",
                quantity="0",
                unit_rate="0",
                total="0",
                classification={},
                source="rom_estimate",
                cad_element_ids=[],
                validation_status="pending",
                metadata_={"rom_element": key},
                sort_order=sort,
            )
            section = await position_repo.create(section)
            sections_created += 1
            sort += 1

            leaf = Position(
                boq_id=boq.id,
                parent_id=section.id,
                ordinal=f"{ordinal}.0010",
                description=f"{label} - concept allowance (provisional)",
                unit="m2",
                quantity=gfa_str,
                unit_rate=format(rate, "f"),
                total=format(amount, "f"),
                classification={},
                source="rom_estimate",
                cad_element_ids=[],
                validation_status="pending",
                metadata_={
                    "rom_element": key,
                    "provisional": True,
                    "rom_estimate_id": str(row.id),
                },
                sort_order=sort,
            )
            await position_repo.create(leaf)
            positions_created += 1
            sort += 1

        return RomCreateBoqResponse(
            boq_id=str(boq.id),
            estimate_id=str(row.id),
            sections_created=sections_created,
            positions_created=positions_created,
        )
