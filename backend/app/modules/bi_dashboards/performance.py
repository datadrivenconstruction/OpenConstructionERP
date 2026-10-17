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

from app.core.stats import quartiles, weighted_mean
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


@dataclass
class BenchmarkGroup:
    key: str
    dimensions: dict[str, str | None]
    readings: list[kpi_spec.ProjectReading] = field(default_factory=list)
    summary: BenchmarkSummary | None = None
    conversions: list[UnitConversion] = field(default_factory=list)


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
        mean=(sum(values[1:], values[0]) / len(values)) if values else None,
        records_with_value=sum(r.records for r in available),
    )


def group_readings(
    readings: list[kpi_spec.ProjectReading],
    aggregation: str,
    conversions: dict[str, list[UnitConversion]] | None = None,
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
    """``[{project_id, name, currency}]`` for the cohort, by name."""
    from app.modules.projects.models import Project

    if not project_ids:
        return []
    rows = (
        await session.execute(
            select(Project.id, Project.name, Project.currency).where(Project.id.in_(sorted(project_ids)))
        )
    ).all()
    out = [{"project_id": pid, "name": name or "", "currency": currency or ""} for pid, name, currency in rows]
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
) -> list[BenchmarkGroup]:
    """Read ``spec`` per project over ``cohort`` and summarise each group.

    ``cohort`` must already be access-narrowed (see :func:`resolve_cohort`).
    A source module that is not installed reads as no data, the way every
    KPI degrades. With ``convert`` the readings go through
    :func:`convert_units` first, so compatible units share one group.
    """
    if not cohort:
        return []
    try:
        readings = await kpi_spec.evaluate_spec_by_project(
            spec,
            session,
            project_ids=cohort,
            period_start=period_start,
            period_end=period_end,
        )
    except ImportError:
        return []
    conversions: dict[str, list[UnitConversion]] = {}
    if convert:
        readings, conversions = convert_units(readings, spec)
    return group_readings(readings, spec["aggregation"], conversions)


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
                group_key=kpi_spec.dimension_key([new_dims.get(name) for name in dims]),
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

    merged: dict[tuple[uuid.UUID, str], kpi_spec.ProjectReading] = {}
    order: list[tuple[uuid.UUID, str]] = []
    for reading in readings:
        r = replaced.get(id(reading), reading)
        key = (r.project_id, r.group_key)
        if key in merged:
            merged[key] = _merge_pair(merged[key], r, aggregation)
        else:
            merged[key] = r
            order.append(key)
    return [merged[k] for k in order], {
        key: sorted(found.values(), key=lambda c: c.from_unit) for key, found in conversions.items()
    }


# ── Cohort filters ──────────────────────────────────────────────────────


async def filter_projects(
    session: AsyncSession,
    project_ids: set[uuid.UUID],
    *,
    clients: list[str] | None = None,
    regions: list[str] | None = None,
    project_types: list[str] | None = None,
) -> set[uuid.UUID]:
    """``project_ids`` narrowed to the projects matching every given filter.

    An empty or absent list does not filter. Values are compared exactly as
    stored, which is how :func:`cohort_options` serves them.
    """
    from app.modules.projects.models import Project

    if not project_ids or not (clients or regions or project_types):
        return set(project_ids)
    stmt = select(Project.id).where(Project.id.in_(sorted(project_ids)))
    if clients:
        stmt = stmt.where(Project.client_id.in_(clients))
    if regions:
        stmt = stmt.where(Project.region.in_(regions))
    if project_types:
        stmt = stmt.where(Project.project_type.in_(project_types))
    rows = (await session.execute(stmt)).scalars().all()
    return {r if isinstance(r, uuid.UUID) else uuid.UUID(str(r)) for r in rows}


async def cohort_options(session: AsyncSession, project_ids: set[uuid.UUID]) -> dict[str, list[str]]:
    """The client, region and project type values present on ``project_ids``.

    Only values that occur on a project the caller may open are listed, so
    the options are no window onto the rest of the portfolio.
    """
    from app.modules.projects.models import Project

    out: dict[str, list[str]] = {"clients": [], "regions": [], "project_types": []}
    if not project_ids:
        return out
    rows = (
        await session.execute(
            select(Project.client_id, Project.region, Project.project_type).where(Project.id.in_(sorted(project_ids)))
        )
    ).all()
    for key, index in (("clients", 0), ("regions", 1), ("project_types", 2)):
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


__all__ = [
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
