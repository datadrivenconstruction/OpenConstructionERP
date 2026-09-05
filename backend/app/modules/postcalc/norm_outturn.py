# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""What a production norm predicted, against what the work really consumed.

Issue #457. The rest of this module answers productivity per BILL LINE. This
answers it per NORM, and the difference is not a presentation choice. A norm is
reused across a bill - that is the whole point of a norm library - so "did this
norm hold on this job" is a question about every position priced from it at
once, and no per-line row answers it however much provenance the line carries.
An estimator who wants to correct next year's library needs the norm's own
verdict, not fourteen line verdicts to average by eye.

Two baselines, and they are not the same number
-----------------------------------------------

"What was estimated" is ambiguous in a way that quietly produces the wrong
answer, so both readings are reported side by side and neither is called simply
"estimated":

* the BILL baseline (``bill_*``) is what the priced line says. It comes from
  the resource split stored on the position at the moment the assembly was
  applied, it already carries the bid factor, the regional factor and any FX
  conversion, and it is immutable: it is what the client was offered. It exists
  for every position that was ever priced.
* the NORM baseline (``norm_*``) is what the library says TODAY. It is read
  live from ``ProductionNorm.labor_hours_per_unit``, through a row anybody can
  edit and anybody can delete, and it is ``None`` when that row is gone.

They agree on the day a bill is priced and drift apart afterwards, which is
exactly the interesting case: the library has been corrected since, or the
estimator overrode it. Collapsing them into one "estimated" figure would report
one of those two answers and let the reader assume the other.

Which one drives ``status``
---------------------------

The bill baseline, always. It is immutable and it is present for every priced
line, so the verdict does not change under an edit to the library and does not
disappear when a norm is deleted. The norm baseline is reported beside it as
``norm_productivity_factor``, which is the library's current opinion of the same
work, and comparing the two factors is how an estimator sees whether the library
has already been corrected in the direction the site is pointing.

Aggregation
-----------

Summed numerator over summed denominator: ``sum(actual_hours) /
sum(earned_hours)`` over every position in the group. Never the mean of the
per-line factors, which weights a 3 m2 patch the same as a 900 m2 elevation and
is a different number with no useful meaning.

Where it refuses to answer
--------------------------

Every refusal is a status from the shared vocabulary in
:mod:`app.modules.postcalc.model`, never a zero, because a zero here reads as
"this cost nothing" and the truth is "nobody has recorded anything yet". The
one case worth spelling out is mixed units: if the positions in a group do not
all share a unit, their quantities cannot be added, so there is no denominator,
the per-unit figures and both factors come back ``None`` and the status is
``no_baseline``. ``mixed_units`` is the flag that says which of the two reasons
for a missing baseline this is - the same device ``on_cost_spine`` uses on the
position-actuals row to distinguish two reasons for a zero.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from app.modules.postcalc.model import (
    STATUS_I18N_KEYS,
    STATUS_NO_ACTUALS,
    STATUS_NO_BASELINE,
    STATUS_NO_PROGRESS,
    STATUS_ON_PLAN,
    STATUS_OVER_PRODUCTIVE,
    STATUS_UNDER_PRODUCTIVE,
)

#: Quanta, matching ``costmodel.position_actuals`` so a figure does not change
#: shape between the row it was read from and the rollup over it.
_MONEY_Q = Decimal("0.01")
_QTY_Q = Decimal("0.0001")
_HOURS_Q = Decimal("0.01")
_FACTOR_Q = Decimal("0.0001")
_PCT_Q = Decimal("0.01")
_ZERO = Decimal("0")
_ONE = Decimal("1")
_HUNDRED = Decimal("100")

#: A factor within this fraction of 1.0 is on plan. Same default and same
#: reasoning as the per-line report: normal site noise is not a finding.
DEFAULT_TOLERANCE = Decimal("0.05")


def _dec(value: object) -> Decimal:
    """Coerce anything stored or serialised into a finite Decimal, never raising."""
    if isinstance(value, Decimal):
        return value if value.is_finite() else _ZERO
    if value is None or value == "":
        return _ZERO
    try:
        out = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return _ZERO
    return out if out.is_finite() else _ZERO


@dataclass(frozen=True)
class NormBaseline:
    """The live library row behind a norm id, when it still exists."""

    work_key: str = ""
    name: str = ""
    unit: str = ""
    labour_hours_per_unit: Decimal | None = None
    machine_hours_per_unit: Decimal | None = None


@dataclass(frozen=True)
class NormOutturn:
    """One production norm, with every position priced from it rolled up.

    Money is in the project base currency, quantities in the norm's own unit.
    ``None`` never means zero: it means the figure has no denominator, no
    baseline or no live norm row, and ``status``, ``mixed_units`` and
    ``norm_row_present`` say which.
    """

    norm_id: str
    work_key: str = ""
    name: str = ""
    unit: str = ""

    positions: int = 0
    mixed_units: bool = False
    #: False when the norm this bill was priced from has since been deleted from
    #: the library. The bill and the outturn are still reported: the work was
    #: estimated and it was done, and a row that vanished with the library entry
    #: would say neither ever happened. This is the reason the identity is
    #: copied onto the position rather than resolved through the assembly.
    norm_row_present: bool = False

    # ── What the bill says. Immutable, and what the client was offered. ──
    bill_quantity: Decimal = _ZERO
    bill_amount: Decimal = _ZERO
    bill_labour_hours: Decimal = _ZERO
    bill_labour_hours_per_unit: Decimal | None = None

    # ── What the library says today. Live, mutable, deletable. ───────────
    norm_labour_hours_per_unit: Decimal | None = None
    norm_labour_hours: Decimal | None = None

    # ── What the job actually did. ───────────────────────────────────────
    installed_quantity: Decimal = _ZERO
    actual_labour_hours: Decimal = _ZERO
    actual_plant_hours: Decimal = _ZERO
    committed_amount: Decimal = _ZERO
    claimed_amount: Decimal = _ZERO
    #: None when no position in the group has any priced consumption on the
    #: material ledger. An unmetered norm and a norm that consumed no material
    #: are different statements and only one of them is worth a number.
    consumed_amount: Decimal | None = None

    # ── The comparison, against each baseline in turn. ───────────────────
    earned_hours: Decimal | None = None
    hours_variance: Decimal | None = None
    productivity_factor: Decimal | None = None
    variance_pct: Decimal | None = None

    norm_earned_hours: Decimal | None = None
    norm_productivity_factor: Decimal | None = None

    status: str = STATUS_NO_ACTUALS

    @property
    def status_i18n_key(self) -> str:
        """Stable translation key for ``status``; the label itself is the UI's."""
        return STATUS_I18N_KEYS.get(self.status, "postcalc.status.no_actuals")

    def to_dict(self) -> dict[str, object]:
        """Serialise for the wire. Money and hours as strings, never floats."""

        def _s(value: Decimal | None) -> str | None:
            return None if value is None else format(value, "f")

        return {
            "norm_id": self.norm_id,
            "work_key": self.work_key,
            "name": self.name,
            "unit": self.unit,
            "positions": self.positions,
            "mixed_units": self.mixed_units,
            "norm_row_present": self.norm_row_present,
            "bill_quantity": _s(self.bill_quantity),
            "bill_amount": _s(self.bill_amount),
            "bill_labour_hours": _s(self.bill_labour_hours),
            "bill_labour_hours_per_unit": _s(self.bill_labour_hours_per_unit),
            "norm_labour_hours_per_unit": _s(self.norm_labour_hours_per_unit),
            "norm_labour_hours": _s(self.norm_labour_hours),
            "installed_quantity": _s(self.installed_quantity),
            "actual_labour_hours": _s(self.actual_labour_hours),
            "actual_plant_hours": _s(self.actual_plant_hours),
            "committed_amount": _s(self.committed_amount),
            "claimed_amount": _s(self.claimed_amount),
            "consumed_amount": _s(self.consumed_amount),
            "earned_hours": _s(self.earned_hours),
            "hours_variance": _s(self.hours_variance),
            "productivity_factor": _s(self.productivity_factor),
            "variance_pct": _s(self.variance_pct),
            "norm_earned_hours": _s(self.norm_earned_hours),
            "norm_productivity_factor": _s(self.norm_productivity_factor),
            "status": self.status,
            "status_i18n_key": self.status_i18n_key,
        }


@dataclass
class NormOutturnReport:
    """Every norm this project's bill was priced from, and how each one held."""

    currency: str = ""
    norms: list[NormOutturn] = field(default_factory=list)
    #: Positions carrying no norm at all. Reported rather than left to be
    #: inferred from a short list: on most bills this is the majority of the
    #: rows, and a reader who does not know that reads a two-norm report as a
    #: two-item bill.
    positions_without_norm: int = 0
    #: Positions whose norm was deleted from the library after they were priced.
    positions_with_deleted_norm: int = 0

    @property
    def norms_answerable(self) -> int:
        """How many norms actually produced a verdict rather than a refusal."""
        return sum(1 for n in self.norms if n.productivity_factor is not None)

    def to_dict(self) -> dict[str, object]:
        return {
            "currency": self.currency,
            "norms": [n.to_dict() for n in self.norms],
            "positions_without_norm": self.positions_without_norm,
            "positions_with_deleted_norm": self.positions_with_deleted_norm,
            "norms_answerable": self.norms_answerable,
        }


def _classify(factor: Decimal, tolerance: Decimal) -> str:
    """On plan, over the norm or under it, against a band around 1.0."""
    if factor > _ONE + tolerance:
        return STATUS_UNDER_PRODUCTIVE
    if factor < _ONE - tolerance:
        return STATUS_OVER_PRODUCTIVE
    return STATUS_ON_PLAN


def _installed_quantity(row: object) -> Decimal:
    """Quantity in place on one position: billed quantity times percent complete.

    Zero when the crew has never reported on the position, which the caller must
    not confuse with a reported zero. The distinction survives one level up:
    a group where nobody reported anything has no installed quantity at all and
    comes back ``no_actuals`` or ``no_progress``, never a factor.
    """
    pct = getattr(row, "installed_percent", None)
    if pct is None:
        return _ZERO
    return _dec(getattr(row, "estimate_quantity", None)) * _dec(pct) / _HUNDRED


def group_by_norm(
    rows: list[object],
    *,
    baselines: dict[str, NormBaseline],
    bill_labour_hours_per_unit: dict[uuid.UUID, Decimal],
    currency: str = "",
    tolerance: Decimal = DEFAULT_TOLERANCE,
) -> NormOutturnReport:
    """Roll position-actuals rows up into one row per production norm.

    Pure, so the whole comparison is testable from plain values on any
    interpreter without a database - the same discipline the rest of this module
    keeps.

    Args:
        rows: ``costmodel.position_actuals.PositionActuals`` rows, taken as
            plain objects so this needs neither the ORM nor a session. Rows
            whose ``norm_id`` is empty are counted and otherwise ignored.
        baselines: ``{norm_id: NormBaseline}`` for the norms that still exist in
            the library. A norm id with no entry here was deleted after the bill
            was priced from it, and is reported with ``norm_row_present`` False
            rather than dropped.
        bill_labour_hours_per_unit: labour hours per position unit, read from
            each position's stored resource split. Keyed by position id, absent
            for a position that carries no split.
        currency: the project base currency the money columns are already in.
        tolerance: the on-plan band around a factor of 1.0.

    Returns:
        A :class:`NormOutturnReport`, its norms ordered by work key so a saved
        report and a live run line up row for row.
    """
    grouped: dict[str, list[object]] = {}
    without_norm = 0
    for row in rows:
        norm_id = str(getattr(row, "norm_id", "") or "")
        if not norm_id:
            without_norm += 1
            continue
        grouped.setdefault(norm_id, []).append(row)

    out: list[NormOutturn] = []
    deleted = 0
    for norm_id, group in grouped.items():
        baseline = baselines.get(norm_id)
        if baseline is None:
            deleted += len(group)
        out.append(
            _one_norm(
                norm_id,
                group,
                baseline=baseline,
                bill_labour_hours_per_unit=bill_labour_hours_per_unit,
                tolerance=tolerance,
            )
        )

    out.sort(key=lambda n: n.work_key or n.norm_id)
    return NormOutturnReport(
        currency=currency,
        norms=out,
        positions_without_norm=without_norm,
        positions_with_deleted_norm=deleted,
    )


def _one_norm(
    norm_id: str,
    group: list[object],
    *,
    baseline: NormBaseline | None,
    bill_labour_hours_per_unit: dict[uuid.UUID, Decimal],
    tolerance: Decimal,
) -> NormOutturn:
    """Roll one norm's positions up. Split out so the grouping above stays readable."""
    units = {str(getattr(row, "unit", "") or "").strip() for row in group}
    units.discard("")
    mixed_units = len(units) > 1

    bill_quantity = _ZERO
    bill_amount = _ZERO
    bill_hours = _ZERO
    installed_quantity = _ZERO
    actual_labour = _ZERO
    actual_plant = _ZERO
    committed = _ZERO
    claimed = _ZERO
    consumed = _ZERO
    any_consumption = False

    for row in group:
        quantity = _dec(getattr(row, "estimate_quantity", None))
        bill_quantity += quantity
        bill_amount += _dec(getattr(row, "estimate_amount", None))
        bill_hours += bill_labour_hours_per_unit.get(getattr(row, "boq_position_id", None), _ZERO) * quantity
        installed_quantity += _installed_quantity(row)
        actual_labour += _dec(getattr(row, "labour_hours", None))
        actual_plant += _dec(getattr(row, "plant_hours", None))
        committed += _dec(getattr(row, "committed_amount", None))
        claimed += _dec(getattr(row, "claimed_amount", None))
        row_consumed = _dec(getattr(row, "consumed_amount", None))
        if row_consumed != _ZERO:
            any_consumption = True
        consumed += row_consumed

    # Quantities can only be added when they are in one unit. Where they are
    # not, every per-unit figure below loses its denominator; ``mixed_units``
    # is what tells the reader that is the reason rather than an unpriced bill.
    has_denominator = bill_quantity > _ZERO and not mixed_units
    bill_hpu = (bill_hours / bill_quantity) if has_denominator else None
    norm_hpu = baseline.labour_hours_per_unit if baseline is not None else None
    norm_hours = (norm_hpu * bill_quantity).quantize(_HOURS_Q) if (norm_hpu is not None and has_denominator) else None

    has_baseline = bill_hpu is not None and bill_hours > _ZERO
    has_progress = installed_quantity > _ZERO

    earned = (bill_hpu * installed_quantity) if (has_baseline and has_progress) else None
    norm_earned = (
        (norm_hpu * installed_quantity) if (norm_hpu is not None and has_progress and not mixed_units) else None
    )

    factor: Decimal | None = None
    norm_factor: Decimal | None = None
    variance_pct: Decimal | None = None
    hours_variance: Decimal | None = None

    if not has_baseline:
        status = STATUS_NO_BASELINE
    elif actual_labour <= _ZERO and not has_progress:
        status = STATUS_NO_ACTUALS
    elif not has_progress:
        # Hours booked against nothing in place. A strong overrun signal and
        # still not a productivity result: there is no quantity to divide by.
        status = STATUS_NO_PROGRESS
    elif actual_labour <= _ZERO:
        # Work in place that nobody booked hours against is a timesheet gap,
        # not a crew that worked for free.
        status = STATUS_NO_ACTUALS
    else:
        hours_variance = actual_labour - earned  # type: ignore[operator]
        factor = actual_labour / earned  # type: ignore[operator]
        variance_pct = (factor - _ONE) * _HUNDRED
        status = _classify(factor, tolerance)

    if norm_earned is not None and norm_earned > _ZERO and actual_labour > _ZERO:
        norm_factor = actual_labour / norm_earned

    return NormOutturn(
        norm_id=norm_id,
        work_key=(baseline.work_key if baseline is not None else "") or _first_work_key(group),
        name=baseline.name if baseline is not None else "",
        unit=(baseline.unit if baseline is not None else "") or (next(iter(units)) if len(units) == 1 else ""),
        positions=len(group),
        mixed_units=mixed_units,
        norm_row_present=baseline is not None,
        bill_quantity=bill_quantity.quantize(_QTY_Q),
        bill_amount=bill_amount.quantize(_MONEY_Q),
        bill_labour_hours=bill_hours.quantize(_HOURS_Q),
        bill_labour_hours_per_unit=None if bill_hpu is None else bill_hpu.quantize(_QTY_Q),
        norm_labour_hours_per_unit=norm_hpu,
        norm_labour_hours=norm_hours,
        installed_quantity=installed_quantity.quantize(_QTY_Q),
        actual_labour_hours=actual_labour.quantize(_HOURS_Q),
        actual_plant_hours=actual_plant.quantize(_HOURS_Q),
        committed_amount=committed.quantize(_MONEY_Q),
        claimed_amount=claimed.quantize(_MONEY_Q),
        consumed_amount=consumed.quantize(_MONEY_Q) if any_consumption else None,
        earned_hours=None if earned is None else earned.quantize(_HOURS_Q),
        hours_variance=None if hours_variance is None else hours_variance.quantize(_HOURS_Q),
        productivity_factor=None if factor is None else factor.quantize(_FACTOR_Q),
        variance_pct=None if variance_pct is None else variance_pct.quantize(_PCT_Q),
        norm_earned_hours=None if norm_earned is None else norm_earned.quantize(_HOURS_Q),
        norm_productivity_factor=None if norm_factor is None else norm_factor.quantize(_FACTOR_Q),
        status=status,
    )


def _first_work_key(group: list[object]) -> str:
    """The work key carried by the positions themselves.

    Used when the library row is gone, which is exactly when it matters: the key
    is the human handle for a norm and a report reading ``(deleted)`` against a
    bare UUID tells an estimator nothing about which norm let them down.
    """
    for row in group:
        key = str(getattr(row, "norm_work_key", "") or "").strip()
        if key:
            return key
    return ""
