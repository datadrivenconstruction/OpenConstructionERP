# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""Domain model for post-calculation (Nachkalkulation) productivity analysis.

Post-calculation closes the loop of an estimate. The estimate side says how many
labour hours a unit of work *should* take (the norm baked into every priced
position's resource split); the site side records how many hours were *actually*
booked and how much was *actually* installed. Comparing the two per BoQ line, per
resource and across the project tells an estimator where the norms held and where
they did not - and hands back a concrete list of productivity factors to feed into
the next estimate.

Everything here is a plain dataclass plus its ``to_dict`` and a Markdown renderer.
It is ``Decimal``-exact and carries no ORM, database or FastAPI dependency, so the
whole model is trivially constructed and asserted from plain values, exactly like
the ``price_breakdown`` and ``resource_summary`` libraries. The compute that fills
these structures lives in :mod:`app.modules.postcalc.service`.

Key quantity, the productivity factor:

    planned_hours_per_unit = planned_labour_hours / planned_quantity
    actual_hours_per_unit  = actual_labour_hours  / actual_quantity (installed)
    productivity_factor    = actual_hours_per_unit / planned_hours_per_unit
                           = actual_labour_hours / earned_hours

where ``earned_hours = planned_hours_per_unit * actual_quantity`` is the hours the
estimate budgeted for the quantity that was actually installed. A factor above 1
means the crew spent more hours than the estimate allowed for the work done
(under-productive); below 1 means fewer (over-productive). Money is never a float.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from app.modules.price_breakdown import ResourceKind, kind_i18n_key

# Quantisation quanta - money and hours to 2 dp, quantities and factors to 4 dp,
# percentages to 2 dp. Matches the platform-wide reporting convention.
_MONEY_Q = Decimal("0.01")
_HOURS_Q = Decimal("0.01")
_QTY_Q = Decimal("0.0001")
_FACTOR_Q = Decimal("0.0001")
_PCT_Q = Decimal("0.01")

# Per-line productivity status vocabulary. Data-only tokens: a frontend maps them
# to a traffic-light and a translated label; nothing here depends on a locale file.
STATUS_ON_PLAN = "on_plan"
STATUS_UNDER_PRODUCTIVE = "under_productive"
STATUS_OVER_PRODUCTIVE = "over_productive"
STATUS_NO_BASELINE = "no_baseline"  # estimate carries no labour norm for the line
STATUS_NO_ACTUALS = "no_actuals"  # nothing booked and nothing installed yet
STATUS_NO_PROGRESS = "no_progress"  # hours booked but no installed quantity recorded

# Stable i18n keys for the line statuses (same contract as ``kind_i18n_key``).
STATUS_I18N_KEYS: dict[str, str] = {
    STATUS_ON_PLAN: "postcalc.status.on_plan",
    STATUS_UNDER_PRODUCTIVE: "postcalc.status.under_productive",
    STATUS_OVER_PRODUCTIVE: "postcalc.status.over_productive",
    STATUS_NO_BASELINE: "postcalc.status.no_baseline",
    STATUS_NO_ACTUALS: "postcalc.status.no_actuals",
    STATUS_NO_PROGRESS: "postcalc.status.no_progress",
}

# Display order of the resource categories, most labour-driven to least, kept
# stable so a saved report and a live run line up row for row.
KIND_ORDER: tuple[ResourceKind, ...] = (
    ResourceKind.LABOUR,
    ResourceKind.MACHINERY,
    ResourceKind.MATERIAL,
    ResourceKind.EQUIPMENT,
    ResourceKind.SUBCONTRACT,
    ResourceKind.OTHER,
)

# English default labels per category. Defaults only; each row also carries the
# stable ``price_breakdown.kind.<value>`` i18n key so a UI can translate the head.
KIND_LABELS: dict[ResourceKind, str] = {
    ResourceKind.LABOUR: "Labour",
    ResourceKind.MACHINERY: "Machinery",
    ResourceKind.MATERIAL: "Material",
    ResourceKind.EQUIPMENT: "Equipment",
    ResourceKind.SUBCONTRACT: "Subcontract",
    ResourceKind.OTHER: "Other",
}

# The two resource kinds whose demand is measured in bookable hours, so a real
# hours-based productivity factor can be computed for them (labour from field
# timesheets, machinery from plant hours). Every other kind is compared on cost.
HOUR_BASED_KINDS: frozenset[ResourceKind] = frozenset({ResourceKind.LABOUR, ResourceKind.MACHINERY})


def _q(value: Decimal | None, quant: Decimal) -> str | None:
    """Quantise a ``Decimal`` to a string, passing ``None`` through unchanged."""
    if value is None:
        return None
    return str(value.quantize(quant, rounding=ROUND_HALF_UP))


@dataclass
class LineProductivity:
    """Planned-vs-actual labour productivity for one BoQ line.

    Labour hours are the classic post-calculation metric: an estimate's unit rate
    is built on a labour norm (hours per unit), and the site books the hours it
    actually took. This compares the two for the quantity that was actually
    installed. Plant and subcontract demand roll up per category in
    :class:`ResourceProductivity`; this line view carries the labour factor an
    estimator tunes and, beside it, the material money - the half of a position
    that usually loses the money and that a labour factor alone cannot see.

    Material is compared on cost only, never on quantity. A position is measured
    in one unit and the material issued against it in another (the bill prices
    "m2" of formwork while the store counts "pcs" of panels), so a quantity delta
    across the two would be arithmetic on two different things. Money has no such
    problem. ``actual_material_cost`` is ``None`` - unknown, not zero - wherever
    the site recorded no priced consumption for the line.

    Two comparisons are offered for each of the two money categories, and they
    answer different questions. ``*_cost_variance`` is against the whole line as
    priced, which is the budget question. The ``*_cost_variance_earned``
    properties are against ``earned_*_cost``, the money the estimate allowed for
    the quantity that was actually installed, which is the performance question
    and the only fair one on a line that is half built.
    """

    ref: str
    description: str
    unit: str
    currency: str
    planned_quantity: Decimal
    actual_quantity: Decimal
    planned_hours: Decimal
    actual_hours: Decimal
    planned_hours_per_unit: Decimal | None
    actual_hours_per_unit: Decimal | None
    earned_hours: Decimal | None
    hours_variance: Decimal | None
    productivity_factor: Decimal | None
    variance_pct: Decimal | None
    planned_labour_cost: Decimal
    actual_labour_cost: Decimal | None
    labour_cost_variance: Decimal | None
    status: str
    # Money the estimate allowed for the quantity actually installed. ``None``
    # when the line has no baseline to earn against. Defaulted so a caller that
    # predates the material half of this report still constructs.
    earned_labour_cost: Decimal | None = None
    planned_material_cost: Decimal = Decimal("0")
    earned_material_cost: Decimal | None = None
    # From the site material ledger. ``None`` means no priced consumption was
    # recorded for the line, which is not the same as nothing having been used.
    actual_material_cost: Decimal | None = None
    material_cost_variance: Decimal | None = None
    # The BoQ position this line reads, so a consumer can fetch its history.
    # ``None`` for a line handed in without one (a file upload, a test).
    position_id: str | None = None

    @property
    def labour_cost_variance_earned(self) -> Decimal | None:
        """Actual labour money against what the installed quantity earned."""
        if self.actual_labour_cost is None or self.earned_labour_cost is None:
            return None
        return self.actual_labour_cost - self.earned_labour_cost

    @property
    def material_cost_variance_earned(self) -> Decimal | None:
        """Actual material money against what the installed quantity earned."""
        if self.actual_material_cost is None or self.earned_material_cost is None:
            return None
        return self.actual_material_cost - self.earned_material_cost

    @property
    def is_under_productive(self) -> bool:
        """True when the line spent more hours per unit than the estimate allowed."""
        return self.status == STATUS_UNDER_PRODUCTIVE

    @property
    def is_over_productive(self) -> bool:
        """True when the line beat the estimate's labour norm."""
        return self.status == STATUS_OVER_PRODUCTIVE

    @property
    def progress_pct(self) -> Decimal | None:
        """Installed quantity as a percentage of the planned quantity."""
        if self.planned_quantity <= 0:
            return None
        return self.actual_quantity / self.planned_quantity * Decimal("100")

    def to_dict(self) -> dict[str, Any]:
        """JSON-ready view (money/hours 2 dp, quantities/factor 4 dp, pct 2 dp)."""
        return {
            "ref": self.ref,
            "position_id": self.position_id,
            "description": self.description,
            "unit": self.unit,
            "currency": self.currency,
            "planned_quantity": _q(self.planned_quantity, _QTY_Q),
            "actual_quantity": _q(self.actual_quantity, _QTY_Q),
            "progress_pct": _q(self.progress_pct, _PCT_Q),
            "planned_hours": _q(self.planned_hours, _HOURS_Q),
            "actual_hours": _q(self.actual_hours, _HOURS_Q),
            "planned_hours_per_unit": _q(self.planned_hours_per_unit, _FACTOR_Q),
            "actual_hours_per_unit": _q(self.actual_hours_per_unit, _FACTOR_Q),
            "earned_hours": _q(self.earned_hours, _HOURS_Q),
            "hours_variance": _q(self.hours_variance, _HOURS_Q),
            "productivity_factor": _q(self.productivity_factor, _FACTOR_Q),
            "variance_pct": _q(self.variance_pct, _PCT_Q),
            "planned_labour_cost": _q(self.planned_labour_cost, _MONEY_Q),
            "earned_labour_cost": _q(self.earned_labour_cost, _MONEY_Q),
            "actual_labour_cost": _q(self.actual_labour_cost, _MONEY_Q),
            "labour_cost_variance": _q(self.labour_cost_variance, _MONEY_Q),
            "labour_cost_variance_earned": _q(self.labour_cost_variance_earned, _MONEY_Q),
            "planned_material_cost": _q(self.planned_material_cost, _MONEY_Q),
            "earned_material_cost": _q(self.earned_material_cost, _MONEY_Q),
            "actual_material_cost": _q(self.actual_material_cost, _MONEY_Q),
            "material_cost_variance": _q(self.material_cost_variance, _MONEY_Q),
            "material_cost_variance_earned": _q(self.material_cost_variance_earned, _MONEY_Q),
            "status": self.status,
            "status_i18n_key": STATUS_I18N_KEYS.get(self.status, ""),
        }


@dataclass
class ResourceProductivity:
    """Planned-vs-actual rollup for one resource category across the project.

    For the hour-based categories (labour, machinery) this carries a real
    productivity factor built from earned vs actual hours. For material,
    equipment, subcontract and other, hours do not apply, so only the planned
    (and, where known, actual) cost is meaningful and ``productivity_factor`` is
    ``None``.

    ``actual_cost`` is ``None`` for a category no actuals source can price, and
    that ``None`` is load-bearing: labour and plant are priced from approved
    timesheets, material from the site inventory ledger, and subcontract,
    equipment and other from nothing at all today. A category with no source
    keeps saying it does not know rather than reporting a zero that would read
    as money nobody spent.

    ``earned_cost`` is the money the estimate allowed for the quantity actually
    installed, so a half-built line does not look like a saving. It covers every
    line the estimate priced for this category, which is what makes it
    comparable to ``planned_cost``.

    ``earned_cost_compared`` covers only the lines whose actual for this category
    is known, and it is the one the variance is built from. The two differ
    whenever the field can price some lines and not others: material consumption
    metered against three positions out of forty earns three positions' worth of
    budget, and subtracting it from forty positions' worth would report a saving
    of the thirty-seven nobody measured.
    """

    kind: ResourceKind
    planned_hours: Decimal
    earned_hours: Decimal
    actual_hours: Decimal
    productivity_factor: Decimal | None
    variance_pct: Decimal | None
    planned_cost: Decimal
    actual_cost: Decimal | None
    cost_variance: Decimal | None
    status: str
    earned_cost: Decimal = Decimal("0")
    earned_cost_compared: Decimal | None = None

    @property
    def cost_variance_earned(self) -> Decimal | None:
        """Actual money against what the same lines earned.

        Both sides cover the lines this category could be priced on, so the
        answer is over or under on comparable work rather than on the gap
        between what was measured and what was not.
        """
        if self.actual_cost is None or self.earned_cost_compared is None:
            return None
        return self.actual_cost - self.earned_cost_compared

    @property
    def label(self) -> str:
        """English default heading for the category."""
        return KIND_LABELS[self.kind]

    @property
    def is_hour_based(self) -> bool:
        """True for labour and machinery - the categories booked in hours."""
        return self.kind in HOUR_BASED_KINDS

    def to_dict(self) -> dict[str, Any]:
        """JSON-ready view of the category rollup."""
        return {
            "kind": self.kind.value,
            "kind_i18n_key": kind_i18n_key(self.kind),
            "label": self.label,
            "is_hour_based": self.is_hour_based,
            "planned_hours": _q(self.planned_hours, _HOURS_Q),
            "earned_hours": _q(self.earned_hours, _HOURS_Q),
            "actual_hours": _q(self.actual_hours, _HOURS_Q),
            "productivity_factor": _q(self.productivity_factor, _FACTOR_Q),
            "variance_pct": _q(self.variance_pct, _PCT_Q),
            "planned_cost": _q(self.planned_cost, _MONEY_Q),
            "earned_cost": _q(self.earned_cost, _MONEY_Q),
            "earned_cost_compared": _q(self.earned_cost_compared, _MONEY_Q),
            "actual_cost": _q(self.actual_cost, _MONEY_Q),
            "cost_variance": _q(self.cost_variance, _MONEY_Q),
            "cost_variance_earned": _q(self.cost_variance_earned, _MONEY_Q),
            "status": self.status,
        }


@dataclass
class FeedbackFactor:
    """A productivity factor to feed back into estimating for one line of work.

    Post-calculation is only worth doing if the site's real productivity updates
    the next estimate. Each factor pairs the estimate's current labour norm with
    the norm the site actually achieved for the same work, plus a confidence score
    driven by how much of the line was installed. Nothing is applied automatically
    - the estimator reviews the suggestion and confirms it (AI-augmented,
    human-confirmed), so ``confidence`` is guidance, never a certainty.
    """

    ref: str
    description: str
    unit: str
    current_hours_per_unit: Decimal
    observed_hours_per_unit: Decimal
    suggested_hours_per_unit: Decimal
    productivity_factor: Decimal
    variance_pct: Decimal
    observed_quantity: Decimal
    confidence: Decimal
    recommendation: str
    position_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """JSON-ready view of the estimating feedback factor."""
        return {
            "ref": self.ref,
            "description": self.description,
            "unit": self.unit,
            "current_hours_per_unit": _q(self.current_hours_per_unit, _FACTOR_Q),
            "observed_hours_per_unit": _q(self.observed_hours_per_unit, _FACTOR_Q),
            "suggested_hours_per_unit": _q(self.suggested_hours_per_unit, _FACTOR_Q),
            "productivity_factor": _q(self.productivity_factor, _FACTOR_Q),
            "variance_pct": _q(self.variance_pct, _PCT_Q),
            "observed_quantity": _q(self.observed_quantity, _QTY_Q),
            "confidence": _q(self.confidence, _PCT_Q),
            "recommendation": self.recommendation,
            "position_id": self.position_id,
        }


@dataclass
class ProjectPostCalc:
    """The whole post-calculation report: per-line, per-resource and project rollup."""

    currency: str
    total_planned_hours: Decimal
    total_earned_hours: Decimal
    total_actual_hours: Decimal
    overall_productivity_factor: Decimal | None
    overall_variance_pct: Decimal | None
    total_planned_labour_cost: Decimal
    total_actual_labour_cost: Decimal | None
    total_planned_value: Decimal
    line_count: int
    compared_line_count: int
    status_counts: dict[str, int]
    # Money side of the report. The earned totals are what the estimate allowed
    # for the quantity installed, and the actual totals are ``None`` where no
    # source can price the category. Defaulted so a caller that predates the
    # material half of this report still constructs.
    #
    # Each category carries two earned totals. The plain one covers every line
    # with a baseline and belongs next to the planned total; the ``_compared``
    # one covers only the lines whose actual is known and is the only one that
    # may be subtracted from the actual. Comparing a forty-line earned total
    # against a three-line actual reports the thirty-seven unmeasured lines as a
    # saving, which is the single easiest way to make this page lie.
    total_earned_labour_cost: Decimal = Decimal("0")
    total_earned_labour_cost_compared: Decimal | None = None
    total_planned_material_cost: Decimal = Decimal("0")
    total_earned_material_cost: Decimal = Decimal("0")
    total_earned_material_cost_compared: Decimal | None = None
    total_actual_material_cost: Decimal | None = None
    # How many lines the field could price. A total built from three of forty
    # lines is a different statement from one built from all forty, and the
    # difference is invisible in the total itself.
    labour_priced_line_count: int = 0
    material_priced_line_count: int = 0
    lines: list[LineProductivity] = field(default_factory=list)
    resources: list[ResourceProductivity] = field(default_factory=list)
    feedback_factors: list[FeedbackFactor] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """JSON-ready view of the entire report."""
        return {
            "currency": self.currency,
            "total_planned_hours": _q(self.total_planned_hours, _HOURS_Q),
            "total_earned_hours": _q(self.total_earned_hours, _HOURS_Q),
            "total_actual_hours": _q(self.total_actual_hours, _HOURS_Q),
            "overall_productivity_factor": _q(self.overall_productivity_factor, _FACTOR_Q),
            "overall_variance_pct": _q(self.overall_variance_pct, _PCT_Q),
            "total_planned_labour_cost": _q(self.total_planned_labour_cost, _MONEY_Q),
            "total_earned_labour_cost": _q(self.total_earned_labour_cost, _MONEY_Q),
            "total_earned_labour_cost_compared": _q(self.total_earned_labour_cost_compared, _MONEY_Q),
            "total_actual_labour_cost": _q(self.total_actual_labour_cost, _MONEY_Q),
            "total_planned_material_cost": _q(self.total_planned_material_cost, _MONEY_Q),
            "total_earned_material_cost": _q(self.total_earned_material_cost, _MONEY_Q),
            "total_earned_material_cost_compared": _q(self.total_earned_material_cost_compared, _MONEY_Q),
            "total_actual_material_cost": _q(self.total_actual_material_cost, _MONEY_Q),
            "labour_priced_line_count": self.labour_priced_line_count,
            "material_priced_line_count": self.material_priced_line_count,
            "total_planned_value": _q(self.total_planned_value, _MONEY_Q),
            "line_count": self.line_count,
            "compared_line_count": self.compared_line_count,
            "status_counts": dict(self.status_counts),
            "lines": [line.to_dict() for line in self.lines],
            "resources": [res.to_dict() for res in self.resources],
            "feedback_factors": [ff.to_dict() for ff in self.feedback_factors],
        }


def _fmt(value: str | None) -> str:
    """Render an optional quantised string as a table cell (``-`` for missing)."""
    return value if value is not None else "-"


def _row(cells: list[str]) -> str:
    """Assemble one Markdown table row from its cell values."""
    return "| " + " | ".join(cells) + " |"


def render_markdown(report: ProjectPostCalc) -> str:
    """Render a post-calculation report as an auditable Markdown document.

    The report shows, per line, the planned and actual quantity and hours, the
    planned and actual hours-per-unit, and the productivity factor, so every
    headline number can be traced back to its inputs. It then rolls the labour and
    plant categories up, and lists the productivity factors to feed back into
    estimating.
    """
    cur = report.currency or ""
    out: list[str] = []
    out.append("# Post-calculation - productivity analysis")
    out.append("")
    out.append(
        "Planned labour norms from the estimate against the hours actually booked "
        "on site for the quantity actually installed."
    )
    out.append("")

    # ── Project summary ──────────────────────────────────────────────────────
    out.append("## Project summary")
    out.append("")
    out.append("| Metric | Value |")
    out.append("| --- | --- |")
    out.append(f"| Planned labour hours | {_fmt(_q(report.total_planned_hours, _HOURS_Q))} |")
    out.append(f"| Earned hours (for installed qty) | {_fmt(_q(report.total_earned_hours, _HOURS_Q))} |")
    out.append(f"| Actual labour hours booked | {_fmt(_q(report.total_actual_hours, _HOURS_Q))} |")
    out.append(f"| Productivity factor (actual / earned) | {_fmt(_q(report.overall_productivity_factor, _FACTOR_Q))} |")
    out.append(f"| Variance | {_fmt(_q(report.overall_variance_pct, _PCT_Q))} % |")
    out.append(f"| Planned labour cost | {_fmt(_q(report.total_planned_labour_cost, _MONEY_Q))} {cur} |")
    out.append(
        f"| Earned labour cost (for installed qty) | {_fmt(_q(report.total_earned_labour_cost, _MONEY_Q))} {cur} |"
    )
    # The compared earned total is the one that pairs with the actual below it.
    # Printing only the full one next to a partial actual invites the reader to
    # subtract two figures that cover different sets of lines.
    out.append(
        f"| Earned labour cost (lines with an actual) | "
        f"{_fmt(_q(report.total_earned_labour_cost_compared, _MONEY_Q))} {cur} |"
    )
    out.append(f"| Actual labour cost | {_fmt(_q(report.total_actual_labour_cost, _MONEY_Q))} {cur} |")
    out.append(f"| Lines with priced labour | {report.labour_priced_line_count} / {report.line_count} |")
    out.append(f"| Planned material cost | {_fmt(_q(report.total_planned_material_cost, _MONEY_Q))} {cur} |")
    out.append(
        f"| Earned material cost (for installed qty) | {_fmt(_q(report.total_earned_material_cost, _MONEY_Q))} {cur} |"
    )
    out.append(
        f"| Earned material cost (lines with an actual) | "
        f"{_fmt(_q(report.total_earned_material_cost_compared, _MONEY_Q))} {cur} |"
    )
    out.append(f"| Actual material cost | {_fmt(_q(report.total_actual_material_cost, _MONEY_Q))} {cur} |")
    out.append(f"| Lines with priced material | {report.material_priced_line_count} / {report.line_count} |")
    out.append(f"| Lines compared / total | {report.compared_line_count} / {report.line_count} |")
    out.append("")

    # ── Per-line productivity ────────────────────────────────────────────────
    out.append("## Productivity by line")
    out.append("")
    out.append(
        "| Ref | Description | Unit | Planned qty | Actual qty | Planned h/unit | "
        "Actual h/unit | Earned h | Actual h | Factor | Variance % | Status |"
    )
    out.append("| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |")
    for line in report.lines:
        out.append(
            _row(
                [
                    line.ref or "-",
                    line.description or "-",
                    line.unit or "-",
                    _fmt(_q(line.planned_quantity, _QTY_Q)),
                    _fmt(_q(line.actual_quantity, _QTY_Q)),
                    _fmt(_q(line.planned_hours_per_unit, _FACTOR_Q)),
                    _fmt(_q(line.actual_hours_per_unit, _FACTOR_Q)),
                    _fmt(_q(line.earned_hours, _HOURS_Q)),
                    _fmt(_q(line.actual_hours, _HOURS_Q)),
                    _fmt(_q(line.productivity_factor, _FACTOR_Q)),
                    _fmt(_q(line.variance_pct, _PCT_Q)),
                    line.status,
                ]
            )
        )
    out.append("")

    # ── Material money per line ──────────────────────────────────────────────
    #
    # Kept as its own table rather than as four more columns on the one above.
    # The hours table answers how fast the crew worked and this one answers what
    # the material cost, and a reader looking for the second question should not
    # have to scroll past ten columns of the first. Compared against earned
    # rather than planned money, because a line that is half built has spent
    # about half its material budget and that is not a saving.
    out.append("## Material cost by line")
    out.append("")
    priced = [line for line in report.lines if line.actual_material_cost is not None]
    if priced:
        out.append(
            "| Ref | Description | Unit | Planned qty | Installed qty | Earned material | Actual material | Variance |"
        )
        out.append("| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |")
        for line in priced:
            out.append(
                _row(
                    [
                        line.ref or "-",
                        line.description or "-",
                        line.unit or "-",
                        _fmt(_q(line.planned_quantity, _QTY_Q)),
                        _fmt(_q(line.actual_quantity, _QTY_Q)),
                        _fmt(_q(line.earned_material_cost, _MONEY_Q)),
                        _fmt(_q(line.actual_material_cost, _MONEY_Q)),
                        _fmt(_q(line.material_cost_variance_earned, _MONEY_Q)),
                    ]
                )
            )
    else:
        out.append(
            "No material consumption has been priced against these lines yet, so the "
            "material half of the estimate cannot be checked."
        )
    out.append("")

    # ── Resource categories ──────────────────────────────────────────────────
    out.append("## Productivity by resource")
    out.append("")
    out.append(
        "| Resource | Planned h | Earned h | Actual h | Factor | Variance % | "
        "Planned cost | Earned cost | Earned (compared) | Actual cost | Lost or saved |"
    )
    out.append("| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
    for res in report.resources:
        out.append(
            _row(
                [
                    res.label,
                    _fmt(_q(res.planned_hours, _HOURS_Q)),
                    _fmt(_q(res.earned_hours, _HOURS_Q)),
                    _fmt(_q(res.actual_hours, _HOURS_Q)),
                    _fmt(_q(res.productivity_factor, _FACTOR_Q)),
                    _fmt(_q(res.variance_pct, _PCT_Q)),
                    _fmt(_q(res.planned_cost, _MONEY_Q)),
                    _fmt(_q(res.earned_cost, _MONEY_Q)),
                    _fmt(_q(res.earned_cost_compared, _MONEY_Q)),
                    _fmt(_q(res.actual_cost, _MONEY_Q)),
                    _fmt(_q(res.cost_variance_earned, _MONEY_Q)),
                ]
            )
        )
    out.append("")

    # ── Estimating feedback ──────────────────────────────────────────────────
    out.append("## Factors to feed back to estimating")
    out.append("")
    if report.feedback_factors:
        out.append(
            "Observed labour norms for the largest deviations. Review and confirm "
            "before applying - nothing here is applied automatically."
        )
        out.append("")
        out.append(
            "| Ref | Description | Unit | Estimate h/unit | Observed h/unit | "
            "Suggested h/unit | Factor | Confidence | Recommendation |"
        )
        out.append("| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- |")
        for ff in report.feedback_factors:
            out.append(
                _row(
                    [
                        ff.ref or "-",
                        ff.description or "-",
                        ff.unit or "-",
                        _fmt(_q(ff.current_hours_per_unit, _FACTOR_Q)),
                        _fmt(_q(ff.observed_hours_per_unit, _FACTOR_Q)),
                        _fmt(_q(ff.suggested_hours_per_unit, _FACTOR_Q)),
                        _fmt(_q(ff.productivity_factor, _FACTOR_Q)),
                        _fmt(_q(ff.confidence, _PCT_Q)),
                        ff.recommendation,
                    ]
                )
            )
    else:
        out.append("No lines have enough booked hours and installed quantity yet to suggest a norm change.")
    out.append("")

    return "\n".join(out)
