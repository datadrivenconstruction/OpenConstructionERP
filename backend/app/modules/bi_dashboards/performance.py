# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Cross-project performance benchmark: one KPI, read per project, ranked.

The question this answers is the one an estimator and a manager both ask of
finished work: across these projects, what did we actually achieve, and what
range is normal. It is read from the same whitelisted KPI specs as every
custom KPI, grouped by project instead of summed over the portfolio, so a
benchmark can never reach a row a KPI could not.

Three rules carry the design, and each one exists because the obvious
implementation breaks it.

* **The benchmark of a ratio is a ratio of sums.** Two projects at 100 h over
  50 m2 and 300 h over 200 m2 did 400 h over 250 m2: 1.60 h/m2. The mean of
  their own ratios is 1.75 and weighs a small job like a big one. The median
  and quartiles are still over per-project values, because they answer a
  different question (what does a typical project look like), and both are
  served so neither is mistaken for the other.
* **Units are never mixed silently.** Each unit and currency a KPI spans is
  its own group, with its own benchmark. On request, readings in two units of
  the same physical dimension (m2 and ft2, m3 and yd3, kg, t and lb, hours
  and minutes) are converted into one of them and merged, and every
  conversion is listed beside the figures it changed. Units of different
  dimensions, units nobody can convert (``set``, a locale label) and
  currencies are never merged.
* **Absent is not zero.** A project with no installed quantity has no
  productivity, and is shown as unavailable with the reason, not ranked first.

Scope is the cohort the caller picked, intersected with what the caller may
open. A project outside that intersection is not named, not counted and not
distinguished from one that does not exist.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field, replace
from datetime import date as _date
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.stats import percentile, quartiles, weighted_mean
from app.core.unit_conversion import convert_strict, strict_unit_factor, unit_dimension
from app.modules.bi_dashboards import kpi_spec

#: Largest cohort one request may name. A benchmark over more than this is a
#: portfolio report, and the default (every project the caller can open)
#: covers that case without a list in the request.
MAX_COHORT = 500

#: Why a benchmark group has no weighted figure.
WEIGHT_NOT_APPLICABLE = "not_applicable"

#: Ready-made performance KPIs, keyed by a stable id the UI translates.
#:
#: Each is an ordinary spec, validated at import time below, so a preset is
#: exactly what a person could have typed into the custom KPI form and
#: nothing more. The ids are part of the API: the frontend names its labels
#: after them.
PRESETS: dict[str, dict[str, Any]] = {
    "labour_hours_per_installed_unit": {
        "entity": "position_progress",
        "aggregation": "ratio",
        "field": "labour_hours",
        "denominator_field": "installed_quantity",
        # Only positions with something installed, which is the set
        # post-calculation compares too: hours on a position not yet started
        # are work in progress, not a slower rate.
        "filters": [{"field": "installed_quantity", "op": "gt", "value": 0}],
    },
    "plant_hours_per_installed_unit": {
        "entity": "position_progress",
        "aggregation": "ratio",
        "field": "plant_hours",
        "denominator_field": "installed_quantity",
        # Only positions with something installed, which is the set
        # post-calculation compares too: hours on a position not yet started
        # are work in progress, not a slower rate.
        "filters": [{"field": "installed_quantity", "op": "gt", "value": 0}],
    },
    "estimate_rate_per_unit": {
        "entity": "boq_position",
        "aggregation": "ratio",
        "field": "amount",
        "denominator_field": "quantity",
    },
    "budget_per_floor_area": {
        "entity": "project",
        "aggregation": "ratio",
        "field": "budget_estimate",
        "denominator_field": "gross_floor_area",
    },
    "approved_labour_hours": {
        "entity": "field_time_line",
        "aggregation": "sum",
        "field": "labour_hours",
    },
    "installed_units_per_labour_hour": {
        "entity": "position_progress",
        "aggregation": "ratio",
        "field": "installed_quantity",
        "denominator_field": "labour_hours",
        "filters": [{"field": "installed_quantity", "op": "gt", "value": 0}],
    },
    "installed_quantity": {
        "entity": "position_progress",
        "aggregation": "sum",
        "field": "installed_quantity",
    },
    "actual_cost_per_floor_area": {
        "entity": "project",
        "aggregation": "ratio",
        "field": "actual_cost",
        "denominator_field": "gross_floor_area",
    },
}

#: The presets in their validated, stored form.
VALIDATED_PRESETS: dict[str, dict[str, Any]] = {key: kpi_spec.validate_spec(spec) for key, spec in PRESETS.items()}


class UnknownPerformanceKPI(LookupError):
    """The request named a KPI that is neither a preset nor a custom spec."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(f"unknown performance KPI {code!r}")


@dataclass
class BenchmarkSummary:
    """The cohort figures for one unit/currency group."""

    weighted: Decimal | None
    weighted_unavailable_reason: str | None
    median: Decimal | None
    p25: Decimal | None
    p75: Decimal | None
    minimum: Decimal | None
    maximum: Decimal | None
    projects_with_data: int
    projects_with_value: int
    records: int
    #: Plain arithmetic mean of the per-project values: every project counts
    #: once whatever its size. Served beside the weighted figure, never in
    #: its place, so the two can be told apart.
    mean: Decimal | None = None
    #: Records behind the projects that have a value, which is the evidence
    #: a minimum-observations rule is about.
    records_with_value: int = 0
    #: The tails, only once there are :data:`TAIL_PERCENTILES_FROM` projects
    #: with a value: P10 of four projects is an interpolation between the two
    #: smallest, which reads like a finding and is not one.
    p10: Decimal | None = None
    p90: Decimal | None = None
    #: Sample standard deviation of the per-project values (n - 1), from two
    #: projects up, and the coefficient of variation: the deviation over the
    #: absolute mean, unset when the mean is zero.
    stddev: Decimal | None = None
    cv: Decimal | None = None
    #: Readings without a value, counted by why: ``zero_denominator`` (the
    #: project booked hours and installed nothing) or ``no_data``.
    excluded: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class UnitConversion:
    """One conversion applied to land readings in a group's unit.

    ``factor`` is how many ``to_unit`` one ``from_unit`` is (1 m2 = 10.7639
    ft2), which is the line a reader checks; the value of a rate per unit
    moves by its reciprocal, and the benchmark applies that, not the reader.
    """

    from_unit: str
    to_unit: str
    factor: Decimal


@dataclass(frozen=True)
class CurrencyConversion:
    """One exchange rate applied to land money in the reporting currency.

    ``rate`` is how many ``to_currency`` one ``from_currency`` is, taken from
    the platform's FX register for ``as_of`` (``source`` says which feed or
    set), so the reader can redo the arithmetic and see whose rate it was.
    """

    from_currency: str
    to_currency: str
    rate: Decimal
    as_of: _date | None = None
    source: str = ""


@dataclass
class BenchmarkGroup:
    key: str
    dimensions: dict[str, str | None]
    readings: list[kpi_spec.ProjectReading] = field(default_factory=list)
    summary: BenchmarkSummary | None = None
    conversions: list[UnitConversion] = field(default_factory=list)
    currency_conversions: list[CurrencyConversion] = field(default_factory=list)


#: Projects with a value from which P10 and P90 are served.
TAIL_PERCENTILES_FROM = 10


def _dispersion(values: list[Decimal], mean: Decimal | None) -> tuple[Decimal | None, Decimal | None]:
    """``(sample standard deviation, coefficient of variation)``, each ``None`` when undefined."""
    if mean is None or len(values) < 2:
        return None, None
    squares = sum(((v - mean) * (v - mean) for v in values[1:]), (values[0] - mean) * (values[0] - mean))
    stddev = (squares / Decimal(len(values) - 1)).sqrt()
    cv = stddev / abs(mean) if mean != 0 else None
    return stddev, cv


def summarise(readings: list[kpi_spec.ProjectReading], aggregation: str) -> BenchmarkSummary:
    """The benchmark of one group, from its per-project readings.

    Pure, so the semantics are tested without a database: the weighted figure
    re-divides the summed numerators and denominators for a ratio or a
    weighted average, weighs an average by its row counts, and has no
    weighted reading at all for a sum, count, min or max, whose per-project
    values are totals and extremes rather than rates.
    """
    available = [r for r in readings if r.value is not None]
    values = [r.value for r in available if r.value is not None]
    p25, median, p75 = quartiles(values)

    weighted: Decimal | None = None
    reason: str | None = None
    if aggregation in ("ratio", "weighted_avg"):
        numerator = sum((r.numerator or Decimal("0") for r in available), Decimal("0"))
        denominator = sum((r.denominator or Decimal("0") for r in available), Decimal("0"))
        weighted, reason = (
            kpi_spec.ratio_value(numerator, denominator) if available else (None, kpi_spec.UNAVAILABLE_NO_DATA)
        )
    elif aggregation == "avg":
        weighted = weighted_mean(values, [r.denominator or Decimal("0") for r in available])
        reason = None if weighted is not None else kpi_spec.UNAVAILABLE_NO_DATA
    else:
        reason = WEIGHT_NOT_APPLICABLE

    mean = (sum(values[1:], values[0]) / len(values)) if values else None
    stddev, cv = _dispersion(values, mean)
    p10 = p90 = None
    if len(values) >= TAIL_PERCENTILES_FROM:
        ordered = sorted(values)
        p10, p90 = percentile(ordered, 10), percentile(ordered, 90)
    excluded: dict[str, int] = {}
    for r in readings:
        if r.value is None:
            why = r.unavailable_reason or kpi_spec.UNAVAILABLE_NO_DATA
            excluded[why] = excluded.get(why, 0) + 1

    return BenchmarkSummary(
        weighted=weighted,
        weighted_unavailable_reason=reason,
        median=median,
        p25=p25,
        p75=p75,
        minimum=min(values) if values else None,
        maximum=max(values) if values else None,
        projects_with_data=len({r.project_id for r in readings}),
        projects_with_value=len({r.project_id for r in available}),
        records=sum(r.records for r in readings),
        mean=mean,
        records_with_value=sum(r.records for r in available),
        p10=p10,
        p90=p90,
        stddev=stddev,
        cv=cv,
        excluded=excluded,
    )


def group_readings(
    readings: list[kpi_spec.ProjectReading],
    aggregation: str,
    conversions: dict[str, list[UnitConversion]] | None = None,
    fx: FxRates | None = None,
) -> list[BenchmarkGroup]:
    """Bucket readings by unit/currency partition and summarise each bucket.

    Groups come back largest evidence first, so the group most projects
    share is the one a reader sees first. ``conversions`` maps a group key to
    the conversions :func:`convert_units` applied to reach it.
    """
    groups: dict[str, BenchmarkGroup] = {}
    for reading in readings:
        group = groups.get(reading.group_key)
        if group is None:
            group = groups[reading.group_key] = BenchmarkGroup(key=reading.group_key, dimensions=reading.dimensions)
        group.readings.append(reading)
    for group in groups.values():
        group.summary = summarise(group.readings, aggregation)
        group.conversions = list((conversions or {}).get(group.key, []))
        if fx is not None:
            converted = sorted({c for r in group.readings for c in r.converted_from_currency})
            group.currency_conversions = [
                CurrencyConversion(
                    from_currency=c,
                    to_currency=fx.to_currency,
                    rate=fx.rates[c],
                    as_of=fx.as_of,
                    source=fx.source,
                )
                for c in converted
                if c in fx.rates
            ]
    return sorted(
        groups.values(),
        key=lambda g: (-(g.summary.projects_with_value if g.summary else 0), g.key),
    )


async def resolve_spec(session: AsyncSession, *, kpi: str | None, spec: dict[str, Any] | None) -> dict[str, Any]:
    """The validated spec a request asks for.

    A raw ``spec`` is validated here, on the same terms ``POST /kpis`` uses.
    A ``kpi`` is a preset id first and a stored custom KPI code second.

    Raises:
        KPISpecError: The raw spec is outside the whitelist.
        UnknownPerformanceKPI: ``kpi`` names nothing with a spec.
    """
    if spec is not None:
        return kpi_spec.validate_spec(spec)
    code = (kpi or "").strip()
    if code in VALIDATED_PRESETS:
        return VALIDATED_PRESETS[code]
    loaded = await kpi_spec.load_custom_spec(session, code) if code else None
    if loaded is None:
        raise UnknownPerformanceKPI(code)
    # Stored specs were validated when they were created; validating again
    # costs nothing and keeps a row edited by hand from reaching the binder.
    return kpi_spec.validate_spec(loaded.spec)


def resolve_cohort(requested: list[uuid.UUID], accessible: set[uuid.UUID]) -> set[uuid.UUID]:
    """The projects a benchmark reads: the request, narrowed to what may be seen.

    An empty request means every accessible project. A requested id outside
    ``accessible`` is dropped silently, the same way for a project that
    exists and one that does not, so the response is no existence oracle.
    """
    if not requested:
        return set(accessible)
    return {pid for pid in requested if pid in accessible}


async def project_labels(session: AsyncSession, project_ids: set[uuid.UUID]) -> list[dict[str, Any]]:
    """``[{project_id, name, currency, client, region, status, project_type}]`` for the cohort, by name."""
    from app.modules.projects.models import Project

    if not project_ids:
        return []
    rows = (
        await session.execute(
            select(
                Project.id,
                Project.name,
                Project.currency,
                Project.client_id,
                Project.region,
                Project.status,
                Project.project_type,
            ).where(Project.id.in_(sorted(project_ids)))
        )
    ).all()
    out = [
        {
            "project_id": pid,
            "name": name or "",
            "currency": currency or "",
            "client": (client or "").strip() or None,
            "region": (region or "").strip() or None,
            "status": status or None,
            "project_type": project_type or None,
        }
        for pid, name, currency, client, region, status, project_type in rows
    ]
    out.sort(key=lambda p: (p["name"].casefold(), str(p["project_id"])))
    return out


async def benchmark(
    session: AsyncSession,
    *,
    spec: dict[str, Any],
    cohort: set[uuid.UUID],
    period_start: _date | None = None,
    period_end: _date | None = None,
    convert: bool = False,
    split: Split | None = None,
    fx: FxRates | None = None,
    cost_index: CostIndex | None = None,
) -> list[BenchmarkGroup]:
    """Read ``spec`` per project over ``cohort`` and summarise each group.

    ``cohort`` must already be access-narrowed (see :func:`resolve_cohort`).
    A source module that is not installed reads as no data, the way every
    KPI degrades. ``split`` (from :func:`resolve_split`) splits every
    project's reading by a project attribute or a row field. With ``fx`` money
    in other currencies is restated in the reporting currency first, then with
    ``convert`` compatible units are merged (:func:`convert_units`); both list
    what they applied. With ``cost_index`` money is first brought to its
    reference month and region, month by month and in its own currency
    (:func:`normalise_costs`), and only then converted.
    """
    if not cohort:
        return []
    indexed = cost_index if cost_index is not None and cost_index_applies(spec) else None
    try:
        readings = await kpi_spec.evaluate_spec_by_project(
            spec,
            session,
            project_ids=cohort,
            period_start=period_start,
            period_end=period_end,
            split_field=split.row_field if split else None,
            by_period=indexed is not None and indexed.temporal,
        )
    except ImportError:
        return []
    if split is not None and split.project_attribute is not None:
        values = await project_attribute_values(session, cohort, split.project_attribute)
        apply_project_split(readings, values, split.project_attribute)
    if indexed is not None:
        regions = await project_regions(session, cohort) if indexed.target_region else {}
        readings = normalise_costs(readings, spec, indexed, project_regions=regions)
    if fx is not None:
        readings = convert_currencies(readings, spec, fx)
    conversions: dict[str, list[UnitConversion]] = {}
    if convert:
        readings, conversions = convert_units(readings, spec)
    return group_readings(readings, spec["aggregation"], conversions, fx)


# ── Unit conversion ─────────────────────────────────────────────────────

#: How a field carrying the ``unit`` dimension moves when its unit changes.
#:
#: ``+1`` for a quantity (10 m2 is 107.6 ft2), ``-1`` for a rate per unit
#: (50 per m2 is 4.65 per ft2). A field that declares a ``unit`` dimension
#: and is missing here would be converted as if unit-free, which is wrong in
#: either direction, so the test suite holds this table to the catalog.
UNIT_EXPONENTS: dict[tuple[str, str], int] = {
    ("boq_position", "quantity"): 1,
    ("boq_position", "unit_rate"): -1,
    ("cost_item_usage", "unit_rate_at_use"): -1,
    ("position_progress", "planned_quantity"): 1,
    ("position_progress", "installed_quantity"): 1,
}

#: The dimension name a reading's unit is carried under.
UNIT_DIMENSION = "unit"


def _field_exponent(spec: dict[str, Any], key: str) -> int:
    name = spec.get(key)
    return UNIT_EXPONENTS.get((str(spec.get("entity")), str(name)), 0) if name else 0


def quotient_exponents(spec: dict[str, Any]) -> tuple[int, int]:
    """How a reading's numerator and denominator move with its unit.

    For a ratio they are the two fields' exponents. For a weighted average
    the numerator is ``sum(field * weight)`` and the denominator the weight.
    For every other aggregation the value itself is the numerator and there
    is no denominator that carries a unit (an average's denominator is a row
    count), so the second exponent is zero.
    """
    aggregation = spec["aggregation"]
    if aggregation == "count":
        return 0, 0
    field_exp = _field_exponent(spec, "field")
    if aggregation == "ratio":
        return field_exp, _field_exponent(spec, "denominator_field")
    if aggregation == "weighted_avg":
        weight_exp = _field_exponent(spec, "weight_field")
        return field_exp + weight_exp, weight_exp
    return field_exp, 0


def value_exponent(spec: dict[str, Any]) -> int:
    """How a reading's value moves with its unit: +1 a quantity, -1 a rate per unit, 0 neither."""
    numerator, denominator = quotient_exponents(spec)
    if spec["aggregation"] in ("ratio", "weighted_avg"):
        return numerator - denominator
    return numerator


#: The unit each dimension's factors are stated against. On a tie for the
#: unit a group is converted into, the base unit wins.
_BASE_UNITS: dict[str, str] = {
    "length": "m",
    "area": "m2",
    "volume": "m3",
    "mass": "kg",
    "count": "pcs",
    "time": "h",
}


def _scale(value: Decimal | None, from_unit: str, to_unit: str, exponent: int) -> Decimal | None:
    if value is None or exponent == 0:
        return value
    return convert_strict(value, from_unit, to_unit, exponent)


def _usable_unit(value: str | None) -> str | None:
    if value is None or value in ("", kpi_spec.NULL_GROUP_KEY):
        return None
    return value


def _merge_pair(a: kpi_spec.ProjectReading, b: kpi_spec.ProjectReading, aggregation: str) -> kpi_spec.ProjectReading:
    """One project's two readings that landed in one group after conversion, as one."""
    merged = replace(
        a,
        records=a.records + b.records,
        converted_from=sorted(set(a.converted_from) | set(b.converted_from)),
        converted_from_currency=sorted(set(a.converted_from_currency) | set(b.converted_from_currency)),
        # Two readings merged have no single figure "before conversion"; the
        # group lists every rate and unit factor that was applied instead.
        original_value=None,
        original_currency=a.original_currency if a.original_currency == b.original_currency else None,
        fx_rate=a.fx_rate if a.fx_rate == b.fx_rate else None,
        index_base_periods=sorted(set(a.index_base_periods) | set(b.index_base_periods)),
        index_factor=a.index_factor if a.index_factor == b.index_factor else None,
        index_missing_periods=sorted(set(a.index_missing_periods) | set(b.index_missing_periods)),
        location_factor=a.location_factor if a.location_factor == b.location_factor else None,
        unadjusted_value=None,
    )
    if aggregation in ("ratio", "weighted_avg"):
        merged.numerator = (a.numerator or Decimal("0")) + (b.numerator or Decimal("0"))
        merged.denominator = (a.denominator or Decimal("0")) + (b.denominator or Decimal("0"))
        merged.value, merged.unavailable_reason = kpi_spec.ratio_value(merged.numerator, merged.denominator)
        return merged
    values = [v for v in (a.value, b.value) if v is not None]
    if not values:
        merged.value = None
    elif aggregation in ("sum", "count"):
        merged.value = sum(values[1:], values[0])
    elif aggregation == "min":
        merged.value = min(values)
    elif aggregation == "max":
        merged.value = max(values)
    else:  # avg: re-weigh by the rows behind each side
        merged.value = weighted_mean(
            [a.value or Decimal("0"), b.value or Decimal("0")],
            [Decimal(a.records if a.value is not None else 0), Decimal(b.records if b.value is not None else 0)],
        )
        merged.denominator = Decimal(merged.records)
    merged.unavailable_reason = None if merged.value is not None else kpi_spec.UNAVAILABLE_NO_DATA
    return merged


def convert_units(
    readings: list[kpi_spec.ProjectReading],
    spec: dict[str, Any],
) -> tuple[list[kpi_spec.ProjectReading], dict[str, list[UnitConversion]]]:
    """Convert readings in compatible units into one unit per dimension.

    Readings are bucketed by every dimension except the unit (so currencies
    stay apart) and by the unit's physical dimension. Inside a bucket the
    target is the unit the most projects with a value already use, ties to
    the most records and then alphabetically, so the figure most readers
    recognise is the one they see. A reading whose unit is unknown, missing
    or of another dimension is left exactly as it was, in its own group.

    Returns:
        The readings (converted ones replaced, one per project and group)
        and, per resulting group key, the conversions applied to reach it.
    """
    dims = kpi_spec.spec_dimensions(spec)
    if UNIT_DIMENSION not in dims:
        return readings, {}
    aggregation = spec["aggregation"]
    num_exp, den_exp = quotient_exponents(spec)
    val_exp = value_exponent(spec)

    def family_of(reading: kpi_spec.ProjectReading) -> str | None:
        return unit_dimension(_usable_unit(reading.dimensions.get(UNIT_DIMENSION)))

    buckets: dict[tuple[Any, ...], list[kpi_spec.ProjectReading]] = {}
    for reading in readings:
        family = family_of(reading)
        if family is None:
            continue
        others = tuple(sorted((k, v or "") for k, v in reading.dimensions.items() if k != UNIT_DIMENSION))
        buckets.setdefault((others, family), []).append(reading)

    replaced: dict[int, kpi_spec.ProjectReading] = {}
    conversions: dict[str, dict[tuple[str, str], UnitConversion]] = {}
    for members in buckets.values():
        units = {str(r.dimensions[UNIT_DIMENSION]) for r in members}
        if len(units) < 2:
            continue
        with_value: dict[str, set[uuid.UUID]] = {}
        records: dict[str, int] = {}
        for r in members:
            u = str(r.dimensions[UNIT_DIMENSION])
            records[u] = records.get(u, 0) + r.records
            if r.value is not None:
                with_value.setdefault(u, set()).add(r.project_id)
        base = _BASE_UNITS.get(family_of(members[0]) or "", "")
        target = min(
            units,
            key=lambda u: (
                -len(with_value.get(u, ())),
                -records.get(u, 0),
                strict_unit_factor(u, base) != 1,
                u,
            ),
        )
        for r in members:
            unit = str(r.dimensions[UNIT_DIMENSION])
            factor = strict_unit_factor(unit, target)
            if unit == target or factor is None:
                continue
            new_dims = {**r.dimensions, UNIT_DIMENSION: target}
            converted = replace(
                r,
                dimensions=new_dims,
                group_key=kpi_spec.dimension_key(list(new_dims.values())),
                converted_from=sorted({*r.converted_from, unit}),
            )
            if aggregation in ("ratio", "weighted_avg"):
                converted.numerator = _scale(r.numerator, unit, target, num_exp)
                converted.denominator = _scale(r.denominator, unit, target, den_exp)
                if r.value is not None:
                    converted.value, converted.unavailable_reason = kpi_spec.ratio_value(
                        converted.numerator, converted.denominator
                    )
            else:
                converted.value = _scale(r.value, unit, target, val_exp)
            replaced[id(r)] = converted
            conversions.setdefault(converted.group_key, {})[(unit, target)] = UnitConversion(
                from_unit=unit, to_unit=target, factor=factor
            )

    out = merge_duplicates([replaced.get(id(reading), reading) for reading in readings], aggregation)
    return out, {key: sorted(found.values(), key=lambda c: c.from_unit) for key, found in conversions.items()}


def merge_duplicates(readings: list[kpi_spec.ProjectReading], aggregation: str) -> list[kpi_spec.ProjectReading]:
    """One reading per project and group, merging the ones a conversion brought together."""
    merged: dict[tuple[uuid.UUID, str], kpi_spec.ProjectReading] = {}
    order: list[tuple[uuid.UUID, str]] = []
    for r in readings:
        key = (r.project_id, r.group_key)
        if key in merged:
            merged[key] = _merge_pair(merged[key], r, aggregation)
        else:
            merged[key] = r
            order.append(key)
    return [merged[k] for k in order]


# ── Cohort filters ──────────────────────────────────────────────────────


async def filter_projects(
    session: AsyncSession,
    project_ids: set[uuid.UUID],
    *,
    clients: list[str] | None = None,
    regions: list[str] | None = None,
    project_types: list[str] | None = None,
    statuses: list[str] | None = None,
) -> set[uuid.UUID]:
    """``project_ids`` narrowed to the projects matching every given filter.

    An empty or absent list does not filter. Values are compared exactly as
    stored, which is how :func:`cohort_options` serves them.
    """
    from app.modules.projects.models import Project

    if not project_ids or not (clients or regions or project_types or statuses):
        return set(project_ids)
    stmt = select(Project.id).where(Project.id.in_(sorted(project_ids)))
    if clients:
        stmt = stmt.where(Project.client_id.in_(clients))
    if regions:
        stmt = stmt.where(Project.region.in_(regions))
    if project_types:
        stmt = stmt.where(Project.project_type.in_(project_types))
    if statuses:
        stmt = stmt.where(Project.status.in_(statuses))
    rows = (await session.execute(stmt)).scalars().all()
    return {r if isinstance(r, uuid.UUID) else uuid.UUID(str(r)) for r in rows}


async def cohort_options(session: AsyncSession, project_ids: set[uuid.UUID]) -> dict[str, list[str]]:
    """The client, region, project type and status values present on ``project_ids``.

    Only values that occur on a project the caller may open are listed, so
    the options are no window onto the rest of the portfolio.
    """
    from app.modules.projects.models import Project

    out: dict[str, list[str]] = {"clients": [], "regions": [], "project_types": [], "statuses": []}
    if not project_ids:
        return out
    rows = (
        await session.execute(
            select(Project.client_id, Project.region, Project.project_type, Project.status).where(
                Project.id.in_(sorted(project_ids))
            )
        )
    ).all()
    for key, index in (("clients", 0), ("regions", 1), ("project_types", 2), ("statuses", 3)):
        values = {str(row[index]).strip() for row in rows if row[index] and str(row[index]).strip()}
        out[key] = sorted(values, key=str.casefold)
    return out


def with_row_filters(spec: dict[str, Any], row_filters: list[dict[str, Any]]) -> dict[str, Any]:
    """``spec`` with extra row filters, validated as one spec.

    This is how a benchmark set says "only positions classified 330": the
    filters go through the same whitelist as any custom KPI, so a filter on
    a field the KPI's entity does not have is a named 422 rather than a
    silently ignored condition.

    Raises:
        KPISpecError: A filter is outside the whitelist for this entity.
    """
    if not row_filters:
        return spec
    return kpi_spec.validate_spec({**spec, "filters": [*spec.get("filters", []), *row_filters]})


# ── Evidence and headline ───────────────────────────────────────────────

#: The statistics a benchmark set may lead with.
STATISTICS: tuple[str, ...] = ("weighted", "mean", "median")

#: Why a group falls short of a minimum.
SHORTFALL_PROJECTS = "too_few_projects"
SHORTFALL_RECORDS = "too_few_records"


def evidence_shortfall(summary: BenchmarkSummary, *, min_projects: int = 0, min_records: int = 0) -> list[str]:
    """The minimums a group misses; empty when its evidence is sufficient."""
    out: list[str] = []
    if summary.projects_with_value < min_projects:
        out.append(SHORTFALL_PROJECTS)
    if summary.records_with_value < min_records:
        out.append(SHORTFALL_RECORDS)
    return out


def headline(summary: BenchmarkSummary, statistic: str) -> tuple[Decimal | None, str]:
    """The figure a group leads with, and the statistic it actually is.

    A weighted figure does not exist for a sum, count, min or max; asking for
    it there falls back to the median, and the returned name says so, so the
    label on screen is never one that was asked for but not delivered.
    """
    if statistic == "mean":
        return summary.mean, "mean"
    if statistic == "median":
        return summary.median, "median"
    if summary.weighted_unavailable_reason == WEIGHT_NOT_APPLICABLE:
        return summary.median, "median"
    return summary.weighted, "weighted"


# ── Estimate against history ────────────────────────────────────────────

#: Projects behind the range from which a check reads medium, then high.
CONFIDENCE_MEDIUM_FROM = 3
CONFIDENCE_HIGH_FROM = 10

#: Why an estimate could not be checked.
CHECK_NO_GROUP = "no_comparable_group"
CHECK_NOT_PER_UNIT = "kpi_not_per_unit"
CHECK_NO_ESTIMATE = "no_estimate_value"


@dataclass
class EstimateCheck:
    """Where one estimate value sits in a group's historical range.

    A reading for a person to weigh, never a value to write back: nothing
    here changes the estimate it was asked about.
    """

    value: Decimal
    unit_factor: Decimal | None
    group: BenchmarkGroup
    headline: Decimal | None
    statistic: str
    variance: Decimal | None
    percentile_rank: Decimal | None
    band: str | None
    confidence: str
    shortfall: list[str]


def find_group(
    groups: list[BenchmarkGroup],
    *,
    unit: str | None,
    currency: str | None,
) -> tuple[BenchmarkGroup, str | None] | None:
    """The group an estimate in ``unit`` and ``currency`` is comparable with.

    A group's currency must equal the estimate's; a group's unit must equal
    it or convert to it. Among several matches the one with the most projects
    wins. Returns the group and the estimate's unit when it has to be
    converted into the group's (``None`` when it is the same unit).
    """
    best: tuple[BenchmarkGroup, str | None] | None = None
    best_evidence = -1
    for group in groups:
        convert_from: str | None = None
        ok = True
        for name, raw in group.dimensions.items():
            have = _usable_unit(raw)
            if name == UNIT_DIMENSION:
                if have is None or not unit:
                    ok = have is None and not unit
                elif have.strip().casefold() != unit.strip().casefold():
                    ok = strict_unit_factor(unit, have) is not None
                    convert_from = unit
            elif name == "currency":
                ok = (have or "").upper() == (currency or "").strip().upper()
            if not ok:
                break
        evidence = group.summary.projects_with_value if group.summary else 0
        if ok and evidence > best_evidence:
            best, best_evidence = (group, convert_from), evidence
    return best


def check_value(
    group: BenchmarkGroup,
    value: Decimal,
    *,
    spec: dict[str, Any],
    from_unit: str | None = None,
    statistic: str = "weighted",
    min_projects: int = 0,
    min_records: int = 0,
) -> EstimateCheck:
    """Place ``value`` in ``group``'s historical range.

    ``from_unit`` is the estimate's unit when it differs from the group's
    (from :func:`find_group`); the value is converted the way the KPI's value
    carries its unit, so a rate per m2 checked against a group in ft2 is
    divided by 10.7639, never multiplied. ``unit_factor`` on the result is
    what the value was multiplied by.

    The percentile rank counts a tie as half below, the usual convention, so
    a value equal to every project's lands at 50 and not at 100.
    """
    summary = group.summary or summarise(group.readings, spec["aggregation"])
    converted = value
    unit_factor: Decimal | None = None
    target = _usable_unit(group.dimensions.get(UNIT_DIMENSION))
    if from_unit is not None and target is not None:
        moved = convert_strict(value, from_unit, target, value_exponent(spec))
        if moved is not None:
            converted, unit_factor = moved, moved / value
    lead, used = headline(summary, statistic)
    variance = (converted - lead) / lead if lead is not None and lead != 0 else None
    values = [r.value for r in group.readings if r.value is not None]
    rank: Decimal | None = None
    if values:
        below = sum(1 for v in values if v < converted)
        equal = sum(1 for v in values if v == converted)
        rank = (Decimal(below) + Decimal(equal) / 2) / Decimal(len(values)) * 100
    band: str | None = None
    if summary.p25 is not None and summary.p75 is not None:
        band = "below" if converted < summary.p25 else "above" if converted > summary.p75 else "within"
    shortfall = evidence_shortfall(summary, min_projects=min_projects, min_records=min_records)
    projects = summary.projects_with_value
    if shortfall or projects < CONFIDENCE_MEDIUM_FROM:
        confidence = "low"
    elif projects < CONFIDENCE_HIGH_FROM:
        confidence = "medium"
    else:
        confidence = "high"
    return EstimateCheck(
        value=converted,
        unit_factor=unit_factor,
        group=group,
        headline=lead,
        statistic=used,
        variance=variance,
        percentile_rank=rank,
        band=band,
        confidence=confidence,
        shortfall=shortfall,
    )


#: Numerators a bill position states per unit itself.
_POSITION_MONEY_FIELDS = frozenset({"amount", "total", "unit_rate"})
_POSITION_QUANTITY_FIELDS = frozenset({"quantity", "planned_quantity", "installed_quantity"})


def position_estimate_kind(spec: dict[str, Any]) -> str | None:
    """What a bill position contributes to a check of this KPI, if anything.

    ``"labour_hours"``: the KPI is labour hours per unit, and the position's
    estimate is the labour hours per unit of its resource split, the figure
    post-calculation calls planned hours per unit. ``"unit_rate"``: the KPI
    is money per unit, and the position's estimate is its unit rate. ``None``
    for anything else, which has no per-position estimate.
    """
    if spec.get("entity") not in ("boq_position", "position_progress"):
        return None
    aggregation = spec["aggregation"]
    field_name = spec.get("field")
    if aggregation == "ratio" and spec.get("denominator_field") in _POSITION_QUANTITY_FIELDS:
        if field_name == "labour_hours":
            return "labour_hours"
        if field_name in _POSITION_MONEY_FIELDS:
            return "unit_rate"
        return None
    if aggregation in ("avg", "weighted_avg") and field_name == "unit_rate":
        return "unit_rate"
    return None


async def position_estimate(
    session: AsyncSession,
    position_id: uuid.UUID,
    spec: dict[str, Any],
    accessible: set[uuid.UUID],
) -> tuple[Decimal, str, str] | str | None:
    """The estimate a bill position states for this KPI.

    Returns ``(value, unit, currency)``, or a reason code when the position
    has no figure for it, or ``None`` when the position does not exist or
    belongs to a project outside ``accessible`` (the two are not told apart).
    """
    from app.modules.boq.models import BOQ, Position
    from app.modules.projects.models import Project

    row = (
        await session.execute(
            select(Position, Project.id, Project.currency)
            .join(BOQ, BOQ.id == Position.boq_id)
            .join(Project, Project.id == BOQ.project_id)
            .where(Position.id == position_id)
        )
    ).first()
    if row is None:
        return None
    position, project_id, currency = row
    if project_id not in accessible:
        return None
    return estimate_of(position, currency or "", spec)


# ── Compound units ──────────────────────────────────────────────────────

#: What a field without a declared unit or currency dimension is measured
#: in. Hours are hours whatever the entity, a floor area is m2 GFA (the
#: project form records it so), durations and ages are days.
_FIELD_UNITS: dict[str, str] = {
    "hours": "h",
    "labour_hours": "h",
    "plant_hours": "h",
    "gross_floor_area": "m2",
    "duration_days": "d",
    "total_float": "d",
    "free_float": "d",
    "price_age_days": "d",
    "percent_complete": "%",
    "progress_pct": "%",
    "percentage": "%",
}


def _measure_unit(spec: dict[str, Any], key: str, dimensions: dict[str, str | None]) -> str | None:
    name = spec.get(key)
    if not name:
        return None
    entry = kpi_spec.ENTITY_CATALOG.get(str(spec.get("entity")))
    declared = entry.dimensions.get(str(name), ()) if entry else ()
    if not declared:
        return _FIELD_UNITS.get(str(name))
    currency = _usable_unit(dimensions.get(CURRENCY_DIMENSION)) if CURRENCY_DIMENSION in declared else None
    unit = _usable_unit(dimensions.get(UNIT_DIMENSION)) if UNIT_DIMENSION in declared else None
    if CURRENCY_DIMENSION in declared and UNIT_DIMENSION in declared:
        return f"{currency}/{unit}" if currency and unit else None
    return currency or unit


def value_unit(spec: dict[str, Any], dimensions: dict[str, str | None]) -> str | None:
    """The compound unit one group's values are in, such as ``h/m2`` or ``EUR/m2``.

    Built from what the KPI's fields are measured in and the group's own unit
    and currency, so the same KPI reads ``h/m2`` in one group and ``h/m3`` in
    the next. ``None`` when it cannot be stated honestly: a count, or a field
    whose unit or currency the group does not carry.
    """
    aggregation = spec["aggregation"]
    if aggregation == "count":
        return None
    numerator = _measure_unit(spec, "field", dimensions)
    if aggregation != "ratio":
        return numerator
    denominator = _measure_unit(spec, "denominator_field", dimensions)
    if numerator and denominator:
        return f"{numerator}/{denominator}"
    if denominator:
        return f"1/{denominator}"
    # A ratio whose denominator unit is unknown is not in the numerator's unit.
    return None


# ── Splits ──────────────────────────────────────────────────────────────

#: Project attributes a benchmark can be split by, and the column each reads.
#: ``end_year`` is the year of the recorded actual end date: a finished job
#: is filed under the year it finished, a running one under "not set".
PROJECT_SPLITS: dict[str, str] = {
    "client": "client_id",
    "region": "region",
    "project_type": "project_type",
    "status": "status",
    "phase": "phase",
    "country": "country_code",
    "end_year": "actual_end_date",
}

#: Most groups a split benchmark returns; the rest are counted, not dropped
#: silently. A split by a field with a thousand values is a data export.
MAX_SPLIT_GROUPS = 60


@dataclass(frozen=True)
class Split:
    """How a benchmark's readings are split beyond unit and currency.

    Exactly one of the two is set: a project attribute from
    :data:`PROJECT_SPLITS`, or a row-level field of the KPI's entity such as
    ``classification.din276``.
    """

    project_attribute: str | None = None
    row_field: str | None = None

    @property
    def name(self) -> str:
        return self.project_attribute or self.row_field or ""


def resolve_split(spec: dict[str, Any], split_by: str | None) -> Split | None:
    """The split a request names, checked against the KPI's entity.

    Raises:
        KPISpecError: ``split_by`` is neither a project attribute nor a
            groupable field of the entity.
    """
    name = (split_by or "").strip()
    if not name:
        return None
    if name in PROJECT_SPLITS:
        return Split(project_attribute=name)
    return Split(row_field=kpi_spec.validate_split_field(spec, name))


async def project_attribute_values(
    session: AsyncSession,
    project_ids: set[uuid.UUID],
    attribute: str,
) -> dict[uuid.UUID, str | None]:
    """``{project_id: value}`` of one :data:`PROJECT_SPLITS` attribute, blank read as unset."""
    from app.modules.projects.models import Project

    if not project_ids:
        return {}
    column = getattr(Project, PROJECT_SPLITS[attribute])
    rows = (await session.execute(select(Project.id, column).where(Project.id.in_(sorted(project_ids))))).all()
    out: dict[uuid.UUID, str | None] = {}
    for pid, raw in rows:
        text = str(raw).strip() if raw is not None else ""
        if attribute == "end_year":
            text = text[:4] if len(text) >= 4 and text[:4].isdigit() else ""
        out[pid if isinstance(pid, uuid.UUID) else uuid.UUID(str(pid))] = text or None
    return out


def apply_project_split(
    readings: list[kpi_spec.ProjectReading],
    values: dict[uuid.UUID, str | None],
    attribute: str,
) -> None:
    """Prefix each reading's dimensions with its project's ``attribute`` value, in place."""
    for r in readings:
        r.dimensions = {attribute: values.get(r.project_id), **r.dimensions}
        r.group_key = kpi_spec.dimension_key(list(r.dimensions.values()))


def cap_groups(groups: list[BenchmarkGroup], limit: int = MAX_SPLIT_GROUPS) -> tuple[list[BenchmarkGroup], int]:
    """The largest ``limit`` groups and how many were left out."""
    return groups[:limit], max(0, len(groups) - limit)


# ── Currency normalisation ──────────────────────────────────────────────

#: The dimension a reading's currency is carried under.
CURRENCY_DIMENSION = "currency"


@dataclass(frozen=True)
class FxRates:
    """Exchange rates into one reporting currency, as the FX register gave them.

    ``rates[code]`` is how many ``to_currency`` one ``code`` is. A currency
    missing from it is not converted and keeps its own group.
    """

    to_currency: str
    rates: dict[str, Decimal]
    as_of: _date | None = None
    source: str = ""


def _currency_exponent(spec: dict[str, Any], key: str) -> int:
    name = spec.get(key)
    entry = kpi_spec.ENTITY_CATALOG.get(str(spec.get("entity")))
    if not name or entry is None:
        return 0
    return 1 if CURRENCY_DIMENSION in entry.dimensions.get(str(name), ()) else 0


def currency_exponents(spec: dict[str, Any]) -> tuple[int, int]:
    """How a reading's numerator and denominator move with an exchange rate.

    The money twin of :func:`quotient_exponents`: a field in a currency moves
    by the rate, a weighted average's numerator by the field's and the
    weight's together, a count never.
    """
    aggregation = spec["aggregation"]
    if aggregation == "count":
        return 0, 0
    field_exp = _currency_exponent(spec, "field")
    if aggregation == "ratio":
        return field_exp, _currency_exponent(spec, "denominator_field")
    if aggregation == "weighted_avg":
        weight_exp = _currency_exponent(spec, "weight_field")
        return field_exp + weight_exp, weight_exp
    return field_exp, 0


def currency_value_exponent(spec: dict[str, Any]) -> int:
    """How a reading's value moves with an exchange rate: 1 money, 0 not money, -1 per money."""
    numerator, denominator = currency_exponents(spec)
    if spec["aggregation"] in ("ratio", "weighted_avg"):
        return numerator - denominator
    return numerator


def _times_rate(value: Decimal | None, rate: Decimal, exponent: int) -> Decimal | None:
    if value is None or exponent == 0:
        return value
    out = value
    for _ in range(abs(exponent)):
        out = out * rate if exponent > 0 else out / rate
    return out


def convert_currencies(
    readings: list[kpi_spec.ProjectReading],
    spec: dict[str, Any],
    fx: FxRates,
) -> list[kpi_spec.ProjectReading]:
    """Restate readings in other currencies in ``fx.to_currency``.

    Only on request, and only with a rate the FX register has: a currency
    with no rate, or a reading with no currency at all, is left exactly as it
    was in its own group, never merged on a guess. Each converted reading
    keeps its original value, currency and the rate applied, and lists the
    currency it came from. A ratio's two sums are converted and re-divided,
    so a money-over-money ratio is unchanged, as it should be.
    """
    if CURRENCY_DIMENSION not in kpi_spec.spec_dimensions(spec):
        return readings
    aggregation = spec["aggregation"]
    num_exp, den_exp = currency_exponents(spec)
    target = fx.to_currency.strip().upper()
    out: list[kpi_spec.ProjectReading] = []
    for r in readings:
        code = (_usable_unit(r.dimensions.get(CURRENCY_DIMENSION)) or "").strip().upper()
        rate = fx.rates.get(code)
        if not code or code == target or rate is None or rate <= 0:
            out.append(r)
            continue
        new_dims = {**r.dimensions, CURRENCY_DIMENSION: target}
        converted = replace(
            r,
            dimensions=new_dims,
            group_key=kpi_spec.dimension_key(list(new_dims.values())),
            converted_from_currency=sorted({*r.converted_from_currency, code}),
            original_value=r.value,
            original_currency=code,
            fx_rate=rate,
        )
        if aggregation in ("ratio", "weighted_avg"):
            converted.numerator = _times_rate(r.numerator, rate, num_exp)
            converted.denominator = _times_rate(r.denominator, rate, den_exp)
            if r.value is not None:
                converted.value, converted.unavailable_reason = kpi_spec.ratio_value(
                    converted.numerator, converted.denominator
                )
        else:
            converted.value = _times_rate(r.value, rate, num_exp)
        out.append(converted)
    return merge_duplicates(out, aggregation)


async def load_fx_rates(
    session: AsyncSession,
    to_currency: str,
    *,
    on_date: _date | None = None,
) -> FxRates:
    """Rates into ``to_currency`` for every currency the platform's FX register knows.

    Resolved once for the whole request (register, then cache, then the
    bundled seed, exactly as every other conversion in the platform). A
    currency the register cannot price is simply absent, and a reading in it
    keeps its own group; :func:`reading_currencies` names those afterwards.
    """
    target = to_currency.strip().upper()
    try:
        from app.modules.fx.service import FxService, convert_via_base
    except ImportError:  # pragma: no cover - FX module not installed
        return FxRates(to_currency=target, rates={})
    resolved = await FxService(session).resolve_rates(on_date=on_date)
    rates: dict[str, Decimal] = {}
    for code in sorted({str(c).upper() for c in resolved.rates} | {str(resolved.base_currency).upper()}):
        if code == target:
            continue
        try:
            _converted, rate = convert_via_base(
                Decimal("1"), code, target, resolved.rates, base_currency=resolved.base_currency
            )
        except Exception:  # noqa: S112 - a currency the set cannot price stays apart
            continue
        rate_d = Decimal(str(rate))
        if rate_d.is_finite() and rate_d > 0:
            rates[code] = rate_d
    return FxRates(to_currency=target, rates=rates, as_of=resolved.as_of, source=str(resolved.source or ""))


def reading_currencies(readings_or_groups: list[BenchmarkGroup]) -> set[str]:
    """The currency codes the groups of a benchmark span."""
    return {
        str(g.dimensions.get(CURRENCY_DIMENSION) or "").strip().upper()
        for g in readings_or_groups
        if _usable_unit(g.dimensions.get(CURRENCY_DIMENSION))
    }


# ── Cost index: historical money at a reference date and region ─────────

#: Why a reading has no value once a cost index was asked for.
INDEX_PERIOD_MISSING = "index_period_missing"
NO_RECORD_DATE = "no_record_date"
NO_LOCATION_FACTOR = "no_location_factor"
NO_PROJECT_REGION = "no_project_region"


class CostIndexError(ValueError):
    """The request asked for a series, period or region the register does not hold."""


@dataclass(frozen=True)
class CostIndex:
    """What to bring historical money to, from the price index register.

    A temporal part (``points`` of one series and the ``target_period`` the
    money is brought to) and a location part (``target_region`` and every
    regional factor), either or both. ``region_factors`` is keyed by the
    trimmed, upper-cased region code.
    """

    series_id: uuid.UUID | None = None
    series_name: str | None = None
    points: dict[str, Decimal] = field(default_factory=dict)
    target_period: str | None = None
    target_region: str | None = None
    region_factors: dict[str, Decimal] = field(default_factory=dict)

    @property
    def temporal(self) -> bool:
        """Whether money is brought to another month."""
        return bool(self.points) and self.target_period is not None

    @property
    def target_region_factor(self) -> Decimal | None:
        """The regional factor of the region money is brought to."""
        return self.region_factors.get(_region_key(self.target_region)) if self.target_region else None


def _region_key(value: str | None) -> str:
    return (value or "").strip().upper()


def cost_index_applies(spec: dict[str, Any]) -> bool:
    """Whether the KPI carries money a cost index can move (hours per m2 does not)."""
    return currency_exponents(spec) != (0, 0)


def pick_target_period(points: dict[str, Decimal], requested: str | None) -> str:
    """The month money is brought to: the one asked for, or the series' latest.

    Raises:
        CostIndexError: The series is empty, or lacks the month asked for.
    """
    if not points:
        raise CostIndexError("the cost index series has no points")
    if requested is None:
        return max(points)
    if requested not in points:
        raise CostIndexError(f"the cost index series has no point for {requested}")
    return requested


def _moved(
    reading: kpi_spec.ProjectReading, factor: Decimal, num_exp: int, den_exp: int, aggregation: str
) -> kpi_spec.ProjectReading:
    """``reading`` with its money multiplied by ``factor``, the way an exchange rate moves it."""
    out = replace(reading)
    if aggregation in ("ratio", "weighted_avg"):
        out.numerator = _times_rate(reading.numerator, factor, num_exp)
        out.denominator = _times_rate(reading.denominator, factor, den_exp)
        if reading.value is not None:
            out.value, out.unavailable_reason = kpi_spec.ratio_value(out.numerator, out.denominator)
    else:
        out.value = _times_rate(reading.value, factor, num_exp)
    return out


def _merged(parts: list[kpi_spec.ProjectReading], aggregation: str) -> kpi_spec.ProjectReading:
    merged = parts[0]
    for part in parts[1:]:
        merged = _merge_pair(merged, part, aggregation)
    return merged


def _effective_factor(before: Decimal | None, after: Decimal | None, factors: set[Decimal]) -> Decimal | None:
    """The one factor that takes the value before to the value after."""
    from app.modules.price_index.index_math import quantize_factor

    if len(factors) == 1:
        return next(iter(factors))
    if before is None or after is None or before == 0:
        return None
    return quantize_factor(after / before)


def normalise_costs(
    readings: list[kpi_spec.ProjectReading],
    spec: dict[str, Any],
    index: CostIndex,
    *,
    project_regions: dict[uuid.UUID, str | None],
) -> list[kpi_spec.ProjectReading]:
    """Bring each reading's money to ``index``'s month and region, one month at a time.

    ``readings`` come per project, group and month (``period``), as
    :func:`kpi_spec.evaluate_spec_by_project` gives them with ``by_period``.
    Each month moves by its own factor ``index(target) / index(month)`` and
    the months of one project and group are then merged, so a project whose
    money spans years is not restated with a single factor. The location
    factor is ``region(target) / region(project's region)``.

    Nothing is guessed. A month the series has no point for, rows without a
    date, a project without a region or a region without a factor exclude the
    whole reading with that reason: counting the rest of the project, or the
    money that cannot move as it was beside money that moved, would print a
    figure that is neither. A KPI without money is returned as it came.
    """
    from app.modules.price_index.index_math import PeriodNotFoundError, quantize_factor, resolve_factor

    aggregation = spec["aggregation"]
    if not cost_index_applies(spec):
        return [replace(r, period=None) for r in readings]
    num_exp, den_exp = currency_exponents(spec)

    buckets: dict[tuple[uuid.UUID, str], list[kpi_spec.ProjectReading]] = {}
    for reading in readings:
        buckets.setdefault((reading.project_id, reading.group_key), []).append(reading)

    out: list[kpi_spec.ProjectReading] = []
    for (pid, _key), parts in buckets.items():
        reason: str | None = None
        location: Decimal | None = None
        region = _region_key(project_regions.get(pid)) if index.target_region else ""
        if index.target_region:
            target_factor = index.target_region_factor
            base_factor = index.region_factors.get(region) if region else None
            if not region:
                reason = NO_PROJECT_REGION
            elif base_factor is None or base_factor <= 0 or target_factor is None:
                reason = NO_LOCATION_FACTOR
            else:
                location = quantize_factor(target_factor / base_factor)

        temporal_parts: list[kpi_spec.ProjectReading] = []
        moved_parts: list[kpi_spec.ProjectReading] = []
        factors: set[Decimal] = set()
        missing: list[str] = []
        for part in parts:
            temporal = Decimal("1")
            if index.temporal:
                if part.period is None:
                    reason = reason or NO_RECORD_DATE
                    continue
                try:
                    temporal = resolve_factor(index.points, part.period, str(index.target_period))
                except PeriodNotFoundError:
                    missing.append(part.period)
                    continue
                factors.add(temporal)
            timed = _moved(part, temporal, num_exp, den_exp, aggregation)
            temporal_parts.append(timed)
            moved_parts.append(_moved(timed, location, num_exp, den_exp, aggregation) if location else timed)
        if missing and reason is None:
            reason = INDEX_PERIOD_MISSING

        before = _merged(parts, aggregation)
        series = index.series_name if index.temporal else None
        target_period = index.target_period if index.temporal else None
        if reason is not None:
            out.append(
                replace(
                    before,
                    value=None,
                    numerator=None,
                    denominator=None,
                    unavailable_reason=reason,
                    period=None,
                    index_series=series,
                    index_target_period=target_period,
                    index_missing_periods=sorted(set(missing)),
                    location_region=region or None,
                    unadjusted_value=before.value,
                )
            )
            continue
        timed_all = _merged(temporal_parts, aggregation)
        after = _merged(moved_parts, aggregation)
        out.append(
            replace(
                after,
                period=None,
                index_series=series,
                index_base_periods=sorted({p.period for p in parts if p.period}) if index.temporal else [],
                index_target_period=target_period,
                index_factor=_effective_factor(before.value, timed_all.value, factors) if index.temporal else None,
                index_missing_periods=[],
                location_region=region or None,
                location_factor=location,
                unadjusted_value=before.value,
            )
        )
    return out


async def load_cost_index(
    session: AsyncSession,
    *,
    series_id: uuid.UUID | None,
    target_period: str | None,
    target_region: str | None,
) -> CostIndex | None:
    """The series points and regional factors a request names, checked against the register.

    ``None`` when the request asked for neither.

    Raises:
        CostIndexError: The price index module is not installed, the series
            does not exist or lacks the target month, or the target region
            has no factor.
    """
    region = (target_region or "").strip() or None
    if series_id is None and region is None:
        return None
    try:
        from app.modules.price_index.models import CostIndexPoint, CostIndexSeries, LocationFactor
    except ImportError as exc:  # pragma: no cover - module removed
        raise CostIndexError("the price index module is not installed") from exc

    name: str | None = None
    points: dict[str, Decimal] = {}
    period: str | None = None
    if series_id is not None:
        series = await session.get(CostIndexSeries, series_id)
        if series is None:
            raise CostIndexError("cost index series not found")
        name = series.name
        rows = await session.execute(
            select(CostIndexPoint.period, CostIndexPoint.factor).where(CostIndexPoint.series_id == series_id)
        )
        points = {str(p).strip(): Decimal(str(f)) for p, f in rows.all() if p and str(p).strip()}
        period = pick_target_period(points, target_period)

    factors: dict[str, Decimal] = {}
    if region is not None:
        rows = await session.execute(select(LocationFactor.region_code, LocationFactor.factor))
        factors = {_region_key(code): Decimal(str(f)) for code, f in rows.all() if _region_key(code)}
        target_factor = factors.get(_region_key(region))
        if target_factor is None or target_factor <= 0:
            raise CostIndexError(f"no location factor for region {region}")
    return CostIndex(
        series_id=series_id,
        series_name=name,
        points=points,
        target_period=period,
        target_region=_region_key(region) if region else None,
        region_factors=factors,
    )


async def project_regions(session: AsyncSession, project_ids: set[uuid.UUID]) -> dict[uuid.UUID, str | None]:
    """Each project's region as stored, for the location factor."""
    if not project_ids:
        return {}
    from app.modules.projects.models import Project

    rows = await session.execute(select(Project.id, Project.region).where(Project.id.in_(project_ids)))
    return {pid: region for pid, region in rows.all()}


# ── Data quality ────────────────────────────────────────────────────────


@dataclass
class DataQuality:
    """How much of the cohort's site data a productivity benchmark can use.

    Each share is ``None`` when its denominator is zero: a cohort with no
    hours has no linked-hours coverage, which is not the same as 0 %.
    """

    projects: int
    hours_total: Decimal | None = None
    hours_linked: Decimal | None = None
    hours_linked_share: Decimal | None = None
    positions_total: int | None = None
    positions_with_progress: int | None = None
    progress_share: Decimal | None = None
    classification_key: str | None = None
    positions_classified: int | None = None
    classification_share: Decimal | None = None


def _share(part: Decimal | int | None, whole: Decimal | int | None) -> Decimal | None:
    if part is None or whole is None or Decimal(whole) == 0:
        return None
    return (Decimal(part) / Decimal(whole)).quantize(Decimal("0.0001"))


async def data_quality(
    session: AsyncSession,
    cohort: set[uuid.UUID],
    *,
    period_start: _date | None = None,
    period_end: _date | None = None,
    classification_key: str | None = None,
) -> DataQuality:
    """Coverage of the cohort's actuals, in two set-based queries.

    * Hours: counted labour and plant hours (approved, not reversed, in the
      period) and the part of them booked against a bill position. Hours on
      no position can never reach a per-unit figure.
    * Positions: priced bill lines (quantity above zero), how many have any
      reported progress, and how many carry ``classification_key``.

    ``cohort`` must already be access-narrowed. A source module that is not
    installed leaves its half unset rather than reading zero.
    """
    out = DataQuality(projects=len(cohort), classification_key=classification_key or None)
    if not cohort:
        return out
    from sqlalchemy import case, func

    from app.core.sql_numeric import numeric_value

    ids = sorted(cohort)
    try:
        from app.modules.field_time.counted import counted_timesheet_clause
        from app.modules.field_time.models import FieldTimesheet, FieldTimesheetLine
    except ImportError:  # pragma: no cover - field time not installed
        pass
    else:
        stmt = (
            select(
                func.sum(FieldTimesheetLine.hours),
                func.sum(case((FieldTimesheetLine.boq_position_id.is_not(None), FieldTimesheetLine.hours), else_=0)),
            )
            .join(FieldTimesheet, FieldTimesheetLine.timesheet_id == FieldTimesheet.id)
            .where(counted_timesheet_clause(), FieldTimesheet.project_id.in_(ids))
        )
        if period_start is not None:
            stmt = stmt.where(FieldTimesheet.date >= period_start)
        if period_end is not None:
            stmt = stmt.where(FieldTimesheet.date <= period_end)
        total, linked = (await session.execute(stmt)).one()
        out.hours_total = Decimal(str(total or 0))
        out.hours_linked = Decimal(str(linked or 0))
        out.hours_linked_share = _share(out.hours_linked, out.hours_total)
    try:
        from app.modules.boq.models import BOQ, Position
        from app.modules.progress.installed import latest_percent_subquery
    except ImportError:  # pragma: no cover - boq or progress not installed
        return out
    latest = latest_percent_subquery()
    measures: list[Any] = [func.count(), func.count(latest.c.percent_complete)]
    key = (classification_key or "").strip()
    if key and kpi_spec.JSON_KEY_RE.fullmatch(key):
        measures.append(func.count(Position.classification[key].as_string()))
    else:
        out.classification_key = None
    stmt = (
        select(*measures)
        .select_from(Position)
        .join(BOQ, Position.boq_id == BOQ.id)
        .outerjoin(
            latest,
            (latest.c.boq_position_id == Position.id) & (latest.c.project_id == BOQ.project_id),
        )
        .where(BOQ.project_id.in_(ids), numeric_value(Position.quantity) > 0)
    )
    row = (await session.execute(stmt)).one()
    out.positions_total = int(row[0] or 0)
    out.positions_with_progress = int(row[1] or 0)
    out.progress_share = _share(out.positions_with_progress, out.positions_total)
    if out.classification_key:
        out.positions_classified = int(row[2] or 0)
        out.classification_share = _share(out.positions_classified, out.positions_total)
    return out


# ── Drilldown ───────────────────────────────────────────────────────────

#: Largest page of contributing records one drilldown call returns.
MAX_DRILL_PAGE = 200


@dataclass
class DrillRecord:
    """One row that contributes to a project's reading, as stored and as counted."""

    record_id: str
    boq_id: str | None
    position_id: str | None
    ref: str
    description: str
    dimensions: dict[str, str | None]
    numerator: Decimal | None
    denominator: Decimal | None
    #: The two figures restated in the group's unit and currency, which is
    #: what the reading adds up; equal to the stored ones when nothing moved.
    counted_numerator: Decimal | None
    counted_denominator: Decimal | None
    #: The cost index and location factor this row's money moved by, unset
    #: when none was asked for or the row's month cannot be moved.
    index_factor: Decimal | None = None


@dataclass
class DrillResult:
    records: list[DrillRecord]
    total_records: int
    numerator: Decimal | None
    denominator: Decimal | None
    value: Decimal | None
    unavailable_reason: str | None


def _row_measures(bound: kpi_spec.BoundEntity, spec: dict[str, Any]) -> tuple[Any, Any | None]:
    """The per-row numerator and denominator whose aggregate is the reading."""
    from sqlalchemy import literal

    aggregation = spec["aggregation"]
    if aggregation == "count":
        return literal(1), None
    value = bound.resolve_field(spec["field"]).expr
    if aggregation == "ratio":
        return value, bound.resolve_field(spec["denominator_field"]).expr
    if aggregation == "weighted_avg":
        weight = bound.resolve_field(spec["weight_field"]).expr
        return value * weight, weight
    if aggregation == "avg":
        return value, literal(1)
    return value, None


def _restate(
    value: Decimal | None,
    dims: dict[str, str | None],
    *,
    unit_exp: int,
    currency_exp: int,
    target_unit: str | None,
    fx: FxRates | None,
    index_factor: Decimal | None = None,
) -> Decimal | None:
    """One stored figure in the group's unit, month, region and currency, or ``None`` when it cannot be."""
    if value is None:
        return None
    out: Decimal | None = value
    unit = _usable_unit(dims.get(UNIT_DIMENSION))
    if unit_exp and target_unit and unit and unit != target_unit:
        out = convert_strict(out, unit, target_unit, unit_exp)
        if out is None:
            return None
    if index_factor is not None:
        out = _times_rate(out, index_factor, currency_exp)
    code = (_usable_unit(dims.get(CURRENCY_DIMENSION)) or "").upper()
    if currency_exp and fx is not None and code and code != fx.to_currency:
        rate = fx.rates.get(code)
        if rate is None:
            return None
        out = _times_rate(out, rate, currency_exp)
    return out


async def drilldown(
    session: AsyncSession,
    spec: dict[str, Any],
    *,
    project_id: uuid.UUID,
    dimensions: dict[str, list[str | None]],
    split: Split | None = None,
    target_unit: str | None = None,
    fx: FxRates | None = None,
    period_start: _date | None = None,
    period_end: _date | None = None,
    offset: int = 0,
    limit: int = 50,
    cost_index: CostIndex | None = None,
    project_region: str | None = None,
) -> DrillResult:
    """The rows behind one project's reading in one group, and their totals.

    ``project_id`` must already be access-checked. ``dimensions`` gives, per
    row-level dimension of the group, the stored values that land in it: the
    group's unit plus every unit the reading lists as ``converted_from``, the
    reporting currency plus every currency converted from. A project-level
    split is not a row field and is ignored here, the project already fixes
    it.

    The totals are computed in SQL over every matching row, not summed from
    the page, and restated into ``target_unit`` and ``fx`` the same way the
    benchmark restated the reading, so they equal the reading's numerator and
    denominator exactly. The page is ordered by the numerator, biggest
    contributor first. With ``cost_index`` every row moves by the factor of
    its own month and the project's region, as :func:`normalise_costs` moved
    the reading, and a month that cannot move leaves the totals unavailable
    with the same reason.
    """
    from sqlalchemy import func, literal, or_

    from app.modules.price_index.index_math import PeriodNotFoundError, quantize_factor, resolve_factor

    bound = kpi_spec.bind_entity(spec["entity"])
    aggregation = spec["aggregation"]
    row_dims = ([split.row_field] if split and split.row_field else []) + kpi_spec.spec_dimensions(spec)
    dim_exprs = [bound.resolve_field(name).expr for name in row_dims]
    num_expr, den_expr = _row_measures(bound, spec)
    unit_num, unit_den = quotient_exponents(spec)
    cur_num, cur_den = currency_exponents(spec)
    indexed = cost_index if cost_index is not None and cost_index_applies(spec) else None
    period_exprs = kpi_spec.period_bucket_exprs(bound) if indexed is not None and indexed.temporal else []
    blocked: str | None = None
    location: Decimal | None = None
    if indexed is not None and indexed.target_region:
        region = _region_key(project_region)
        base_factor = indexed.region_factors.get(region) if region else None
        target_factor = indexed.target_region_factor
        if not region:
            blocked = NO_PROJECT_REGION
        elif base_factor is None or base_factor <= 0 or target_factor is None:
            blocked = NO_LOCATION_FACTOR
        else:
            location = quantize_factor(target_factor / base_factor)

    def factor_for(period: str | None) -> tuple[Decimal | None, str | None]:
        """The row's combined factor, or why it has none."""
        if indexed is None:
            return None, None
        if blocked is not None:
            return None, blocked
        factor = Decimal("1")
        if indexed.temporal:
            if period is None:
                return None, NO_RECORD_DATE
            try:
                factor = resolve_factor(indexed.points, period, str(indexed.target_period))
            except PeriodNotFoundError:
                return None, INDEX_PERIOD_MISSING
        if location is not None:
            factor = factor * location
        return factor, None

    def scoped(stmt: Any) -> Any:
        stmt = kpi_spec._base_predicates(
            stmt,
            bound,
            spec,
            project_id=project_id,
            period_start=period_start,
            period_end=period_end,
            allowed_project_ids={project_id},
        )
        for name, expr in zip(row_dims, dim_exprs, strict=True):
            allowed = dimensions.get(name)
            if allowed is None:
                continue
            values = [v for v in allowed if v is not None and v != kpi_spec.NULL_GROUP_KEY]
            wants_null = any(v is None or v == kpi_spec.NULL_GROUP_KEY for v in allowed)
            clauses = []
            if values:
                clauses.append(expr.in_(values))
            if wants_null:
                clauses.append(expr.is_(None))
            stmt = stmt.where(or_(*clauses) if clauses else literal(False))
        return stmt

    if aggregation in ("min", "max"):
        folded = func.min(num_expr) if aggregation == "min" else func.max(num_expr)
        total_measures = [folded, literal(None)]
    else:
        total_measures = [func.sum(num_expr), func.sum(den_expr) if den_expr is not None else literal(None)]
    totals_stmt = scoped(select(*dim_exprs, *period_exprs, *total_measures, func.count()).select_from(bound.model))
    if dim_exprs or period_exprs:
        totals_stmt = totals_stmt.group_by(*dim_exprs, *period_exprs)

    from app.modules.bi_dashboards.kpis import _to_decimal

    numerator: Decimal | None = None
    denominator: Decimal | None = None
    total_records = 0
    unmovable: str | None = None
    for raw in (await session.execute(totals_stmt)).all():
        row = list(raw)
        count = int(row.pop() or 0)
        if count == 0:
            continue
        values = dict(zip(row_dims, (None if v is None else str(v) for v in row[: len(row_dims)]), strict=True))
        month = kpi_spec.period_bucket_key(*row[len(row_dims) : len(row_dims) + 2]) if period_exprs else None
        factor, why = factor_for(month)
        unmovable = unmovable or why
        n_raw, d_raw = row[len(row_dims) + len(period_exprs) :]
        n = _restate(
            _to_decimal(n_raw) if n_raw is not None else None,
            values,
            unit_exp=unit_num,
            currency_exp=cur_num,
            target_unit=target_unit,
            fx=fx,
            index_factor=factor,
        )
        d = _restate(
            _to_decimal(d_raw) if d_raw is not None else None,
            values,
            unit_exp=unit_den,
            currency_exp=cur_den,
            target_unit=target_unit,
            fx=fx,
            index_factor=factor,
        )
        total_records += count
        if aggregation == "min":
            numerator = n if numerator is None or (n is not None and n < numerator) else numerator
        elif aggregation == "max":
            numerator = n if numerator is None or (n is not None and n > numerator) else numerator
        else:
            numerator = (numerator or Decimal("0")) + (n or Decimal("0"))
            if d is not None:
                denominator = (denominator or Decimal("0")) + d

    value: Decimal | None
    reason: str | None = None
    if total_records == 0:
        value, reason = None, kpi_spec.UNAVAILABLE_NO_DATA
    elif unmovable is not None:
        numerator = denominator = None
        value, reason = None, unmovable
    elif aggregation in ("ratio", "weighted_avg", "avg"):
        value, reason = kpi_spec.ratio_value(numerator, denominator)
    else:
        value = numerator

    def column(key: str) -> Any:
        expr = bound.record_columns.get(key)
        return (expr if expr is not None else literal(None)).label(f"rec_{key}")

    page_stmt = scoped(
        select(
            column("id"),
            column("boq_id"),
            column("position_id"),
            column("ref"),
            column("description"),
            *dim_exprs,
            *period_exprs,
            num_expr.label("rec_num"),
            (den_expr if den_expr is not None else literal(None)).label("rec_den"),
        ).select_from(bound.model)
    )
    page_stmt = (
        page_stmt.order_by(num_expr.desc(), bound.record_columns.get("id", literal(None)))
        .offset(max(0, offset))
        .limit(max(1, min(limit, MAX_DRILL_PAGE)))
    )
    records: list[DrillRecord] = []
    for raw in (await session.execute(page_stmt)).all():
        row = list(raw)
        rid, boq_id, position_id, ref, description = row[:5]
        dim_values = row[5 : 5 + len(row_dims)]
        month = kpi_spec.period_bucket_key(*row[5 + len(row_dims) : 7 + len(row_dims)]) if period_exprs else None
        factor, _why = factor_for(month)
        n_raw, d_raw = row[5 + len(row_dims) + len(period_exprs) :]
        dims = dict(zip(row_dims, (None if v is None else str(v) for v in dim_values), strict=True))
        n = _to_decimal(n_raw) if n_raw is not None else None
        d = _to_decimal(d_raw) if d_raw is not None else None
        records.append(
            DrillRecord(
                record_id=str(rid) if rid is not None else "",
                boq_id=str(boq_id) if boq_id is not None else None,
                position_id=str(position_id) if position_id is not None else None,
                ref=str(ref or ""),
                description=str(description or ""),
                dimensions=dims,
                numerator=n,
                denominator=d,
                counted_numerator=_restate(
                    n,
                    dims,
                    unit_exp=unit_num,
                    currency_exp=cur_num,
                    target_unit=target_unit,
                    fx=fx,
                    index_factor=factor,
                ),
                counted_denominator=_restate(
                    d,
                    dims,
                    unit_exp=unit_den,
                    currency_exp=cur_den,
                    target_unit=target_unit,
                    fx=fx,
                    index_factor=factor,
                ),
                index_factor=factor,
            )
        )
    return DrillResult(
        records=records,
        total_records=total_records,
        numerator=numerator,
        denominator=denominator,
        value=value,
        unavailable_reason=reason,
    )


# ── Historical context for bill positions ───────────────────────────────

#: Why a bill position has no historical context.
CONTEXT_NO_CLASSIFICATION = "no_classification"

#: Most positions one context request may ask about.
MAX_CONTEXT_POSITIONS = 500


@dataclass
class PositionContext:
    """Where one bill position's own figure sits among comparable past positions."""

    position_id: uuid.UUID
    status: str
    classification_code: str | None = None
    unit: str | None = None
    currency: str | None = None
    estimate: Decimal | None = None
    check: EstimateCheck | None = None


def pick_classification_key(classifications: list[dict[str, Any]], requested: str | None) -> str | None:
    """The classification standard positions are matched on.

    The requested key when it is a valid key, otherwise the key the most of
    these positions carry a code under (ties alphabetically), so an estimate
    classified by DIN 276 is matched by DIN 276 without anyone choosing it.
    """
    wanted = (requested or "").strip()
    if wanted:
        return wanted if kpi_spec.JSON_KEY_RE.fullmatch(wanted) else None
    counts: dict[str, int] = {}
    for item in classifications:
        if not isinstance(item, dict):
            continue
        for key, code in item.items():
            if isinstance(key, str) and kpi_spec.JSON_KEY_RE.fullmatch(key) and str(code or "").strip():
                counts[key] = counts.get(key, 0) + 1
    if not counts:
        return None
    return min(counts, key=lambda k: (-counts[k], k))


def estimate_of(position: Any, currency: str, spec: dict[str, Any]) -> tuple[Decimal, str, str] | str:
    """A loaded position's own figure for this KPI, or the reason it has none.

    The same reading :func:`position_estimate` gives, for a position the
    caller has already loaded and access-checked.
    """
    kind = position_estimate_kind(spec)
    if kind is None:
        return CHECK_NOT_PER_UNIT
    if kind == "labour_hours":
        from app.modules.postcalc.service import _per_unit_hours, _resources_of
        from app.modules.price_breakdown.model import ResourceKind

        hours = _per_unit_hours(_resources_of({"metadata_": position.metadata_}), ResourceKind.LABOUR)
        if hours <= 0:
            return CHECK_NO_ESTIMATE
        return hours, position.unit or "", currency or ""
    try:
        rate = Decimal(str(position.unit_rate))
    except ArithmeticError:
        return CHECK_NO_ESTIMATE
    if not rate.is_finite() or rate <= 0:
        return CHECK_NO_ESTIMATE
    return rate, position.unit or "", currency or ""


async def position_context(
    session: AsyncSession,
    spec: dict[str, Any],
    *,
    position_ids: list[uuid.UUID],
    accessible: set[uuid.UUID],
    classification_key: str | None = None,
    include_own_projects: bool = False,
    convert: bool = True,
    statistic: str = "weighted",
    min_projects: int = 0,
    min_records: int = 0,
) -> tuple[str | None, list[PositionContext]]:
    """Historical context for bill positions, in one benchmark query.

    Comparable means the same classification code under one standard
    (:func:`pick_classification_key`) and a unit that is the same or converts.
    The cohort is every project the caller may open except, by default, the
    positions' own projects, so a position is never compared with itself.
    Positions outside ``accessible`` are left out of the answer entirely.

    Returns the classification key used and one context per readable position,
    in the order asked. Nothing is written.
    """
    from app.modules.boq.models import BOQ, Position
    from app.modules.projects.models import Project

    ids = list(dict.fromkeys(position_ids))[:MAX_CONTEXT_POSITIONS]
    if not ids:
        return None, []
    rows = (
        await session.execute(
            select(Position, BOQ.project_id, Project.currency)
            .join(BOQ, BOQ.id == Position.boq_id)
            .join(Project, Project.id == BOQ.project_id)
            .where(Position.id.in_(ids))
        )
    ).all()
    loaded = {pos.id: (pos, pid, currency or "") for pos, pid, currency in rows if pid in accessible}
    key = pick_classification_key([pos.classification or {} for pos, _p, _c in loaded.values()], classification_key)

    def code_of(position: Any) -> str | None:
        raw = (position.classification or {}).get(key) if key else None
        text = str(raw).strip() if raw is not None else ""
        return text or None

    codes = sorted({c for pos, _p, _c in loaded.values() if (c := code_of(pos))})[: kpi_spec.MAX_IN_VALUES]
    groups: list[BenchmarkGroup] = []
    split: Split | None = None
    if key and codes:
        own = {pid for _pos, pid, _c in loaded.values()}
        cohort = set(accessible) if include_own_projects else set(accessible) - own
        split = resolve_split(spec, f"classification.{key}")
        scoped = with_row_filters(spec, [{"field": f"classification.{key}", "op": "in", "value": codes}])
        groups = await benchmark(session, spec=scoped, cohort=cohort, convert=convert, split=split)

    out: list[PositionContext] = []
    for pid in ids:
        if pid not in loaded:
            continue
        position, _project, currency = loaded[pid]
        code = code_of(position)
        ctx = PositionContext(position_id=pid, status="ok", classification_code=code, unit=position.unit or None)
        found = estimate_of(position, currency, spec)
        if isinstance(found, str):
            ctx.status = found
            out.append(ctx)
            continue
        value, unit, cur = found
        ctx.estimate, ctx.currency = value, cur or None
        if code is None or split is None:
            ctx.status = CONTEXT_NO_CLASSIFICATION
            out.append(ctx)
            continue
        candidates = [g for g in groups if g.dimensions.get(split.name) == code]
        match = find_group(candidates, unit=unit, currency=cur)
        if match is None:
            ctx.status = CHECK_NO_GROUP
            out.append(ctx)
            continue
        group, from_unit = match
        ctx.check = check_value(
            group,
            value,
            spec=spec,
            from_unit=from_unit,
            statistic=statistic,
            min_projects=min_projects,
            min_records=min_records,
        )
        out.append(ctx)
    return key, out


__all__ = [
    "CONTEXT_NO_CLASSIFICATION",
    "CURRENCY_DIMENSION",
    "MAX_CONTEXT_POSITIONS",
    "MAX_DRILL_PAGE",
    "MAX_SPLIT_GROUPS",
    "PROJECT_SPLITS",
    "TAIL_PERCENTILES_FROM",
    "INDEX_PERIOD_MISSING",
    "NO_LOCATION_FACTOR",
    "NO_PROJECT_REGION",
    "NO_RECORD_DATE",
    "CostIndex",
    "CostIndexError",
    "CurrencyConversion",
    "DataQuality",
    "DrillRecord",
    "DrillResult",
    "FxRates",
    "PositionContext",
    "Split",
    "apply_project_split",
    "cap_groups",
    "convert_currencies",
    "cost_index_applies",
    "load_cost_index",
    "normalise_costs",
    "pick_target_period",
    "project_regions",
    "currency_exponents",
    "currency_value_exponent",
    "data_quality",
    "drilldown",
    "estimate_of",
    "load_fx_rates",
    "merge_duplicates",
    "pick_classification_key",
    "position_context",
    "project_attribute_values",
    "reading_currencies",
    "resolve_split",
    "value_unit",
    "CHECK_NOT_PER_UNIT",
    "CHECK_NO_ESTIMATE",
    "CHECK_NO_GROUP",
    "MAX_COHORT",
    "PRESETS",
    "SHORTFALL_PROJECTS",
    "SHORTFALL_RECORDS",
    "STATISTICS",
    "UNIT_DIMENSION",
    "UNIT_EXPONENTS",
    "VALIDATED_PRESETS",
    "WEIGHT_NOT_APPLICABLE",
    "BenchmarkGroup",
    "BenchmarkSummary",
    "EstimateCheck",
    "UnitConversion",
    "UnknownPerformanceKPI",
    "benchmark",
    "check_value",
    "cohort_options",
    "convert_units",
    "evidence_shortfall",
    "filter_projects",
    "find_group",
    "group_readings",
    "headline",
    "position_estimate",
    "position_estimate_kind",
    "project_labels",
    "quotient_exponents",
    "resolve_cohort",
    "resolve_spec",
    "summarise",
    "value_exponent",
    "with_row_filters",
]
