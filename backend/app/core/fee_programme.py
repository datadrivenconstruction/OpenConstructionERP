# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Fee programmes: ordered fee lines on component bases, chosen by date.

Many markets price overheads, profit and statutory charges as an ordered list
of lines, each a rate on its own base: management fee on labour plus a tenth
of plant, profit on the cost so far, a safety fee on the works total, a payroll
levy on labour only. The base is what differs between jurisdictions, so it is
data, not code. A line's ``base`` maps terms to weights:

* component kinds: ``labour`` (after the schedule's labour factor),
  ``material``, ``plant``, ``equipment``, ``other``;
* ``direct``: the sum of those five;
* ``lump_sum_measures``, ``provisional_sum``, ``other_items``: amounts that
  sit outside the measured works and enter only the bases that name them;
* ``fenbu``: direct cost plus every earlier line of group ``fenbu`` (the
  measured-works total of a GB 50500 bill; any market can use the group);
* ``line:<code>``: the amount of an earlier line.

A line's rate is the user's rate when given, else the rate of the chosen
option, else the published rate. A line without any rate is ``missing`` and
adds nothing; the screen asks for it instead of guessing. Every amount is
rounded to the cent, half up, line by line, as a bill prints it.

Schedules carry ``effective_from`` / ``effective_to`` and the key of their
successor, so a project picks its schedule by its tender date (or contract
date), not by the newest edition. Standard library only.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

_CENT = Decimal("0.01")
_HUNDRED = Decimal(100)
_ZERO = Decimal(0)
_ONE = Decimal(1)

KIND_TERMS: tuple[str, ...] = ("labour", "material", "plant", "equipment", "other")
OUTSIDE_TERMS: tuple[str, ...] = ("lump_sum_measures", "provisional_sum", "other_items")
COMPONENT_TERMS: tuple[str, ...] = KIND_TERMS + OUTSIDE_TERMS


def _dec(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value).replace(",", "").strip())
    except (InvalidOperation, ValueError):
        return None


def _date(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    text = str(value or "").strip()[:10]
    try:
        return date.fromisoformat(text) if text else None
    except ValueError:
        return None


def _cents(value: Decimal) -> Decimal:
    return value.quantize(_CENT, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class RateBand:
    """Published lower and upper bound of a rate, in percent."""

    min: Decimal | None = None
    mid: Decimal | None = None
    max: Decimal | None = None


@dataclass(frozen=True)
class FeeLine:
    """One line of a fee programme.

    ``floor`` is the lowest rate a non-competitive line may carry; ``"rate"``
    in the data means the published rate itself is the floor.
    """

    code: str
    base: dict[str, Decimal]
    rate: Decimal | None = None
    group: str = "other"
    kind: str = ""
    coefficient: Decimal = _ONE
    band: RateBand = field(default_factory=RateBand)
    non_competitive: bool = False
    floor: Decimal | None = None
    floor_is_rate: bool = False
    user_input: bool = False
    option: str | None = None
    option_rates: dict[str, Decimal] = field(default_factory=dict)
    meta: dict[str, Any] = field(default_factory=dict)

    def published_rate(self, options: Mapping[str, str]) -> Decimal | None:
        """The rate the source gives under the chosen options, if any."""
        if self.option and self.option_rates:
            picked = options.get(self.option)
            if picked in self.option_rates:
                return self.option_rates[picked]
        return self.rate

    def effective_floor(self, options: Mapping[str, str]) -> Decimal | None:
        """The lowest rate allowed under the chosen options, if the source sets one."""
        return self.published_rate(options) if self.floor_is_rate else self.floor


@dataclass(frozen=True)
class FeeSchedule:
    """An ordered fee programme of one jurisdiction and edition."""

    key: str
    jurisdiction: str
    lines: tuple[FeeLine, ...]
    edition: str = ""
    effective_from: date | None = None
    effective_to: date | None = None
    superseded_by: str | None = None
    labour_factor: Decimal | None = None
    vat_rates: dict[str, Decimal] = field(default_factory=dict)
    option_defaults: dict[str, str] = field(default_factory=dict)
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class LineResult:
    """One computed line: what it was taken on, at which rate, and why."""

    code: str
    group: str
    kind: str
    base: Decimal
    rate: Decimal | None
    coefficient: Decimal
    amount: Decimal
    status: str  # published | user | missing
    published: Decimal | None = None
    floor: Decimal | None = None


@dataclass(frozen=True)
class FeeResult:
    """A computed programme with its subtotals, VAT and total."""

    schedule_key: str
    labour: Decimal
    labour_factor_applied: bool
    direct: Decimal
    lines: tuple[LineResult, ...]
    subtotals: dict[str, Decimal]
    pre_tax: Decimal
    vat_rate: Decimal
    vat: Decimal
    tax_inclusive: Decimal
    total: Decimal
    options: dict[str, str] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        """JSON-ready form; money and rates as strings."""
        return {
            "schedule_key": self.schedule_key,
            "labour": str(self.labour),
            "labour_factor_applied": self.labour_factor_applied,
            "direct": str(self.direct),
            "lines": [
                {
                    "code": r.code,
                    "group": r.group,
                    "kind": r.kind,
                    "base": str(r.base),
                    "rate": None if r.rate is None else str(r.rate),
                    "coefficient": str(r.coefficient),
                    "amount": str(r.amount),
                    "status": r.status,
                    "published": None if r.published is None else str(r.published),
                    "floor": None if r.floor is None else str(r.floor),
                }
                for r in self.lines
            ],
            "subtotals": {k: str(v) for k, v in self.subtotals.items()},
            "pre_tax": str(self.pre_tax),
            "vat_rate": str(self.vat_rate),
            "vat": str(self.vat),
            "tax_inclusive": str(self.tax_inclusive),
            "total": str(self.total),
            "options": dict(self.options),
        }


def _line_from_dict(row: Mapping[str, Any]) -> FeeLine:
    band = row.get("band") or {}
    options = row.get("rate_options") or {}
    floor_raw = row.get("floor")
    rate = _dec(row.get("rate"))
    floor_is_rate = floor_raw in ("rate", "option")
    floor = None if floor_is_rate else _dec(floor_raw)
    return FeeLine(
        code=str(row["code"]),
        base={str(k): _dec(v) or _ZERO for k, v in (row.get("base") or {}).items()},
        rate=rate,
        group=str(row.get("group") or "other"),
        kind=str(row.get("kind") or ""),
        coefficient=_dec(row.get("coefficient")) or _ONE,
        band=RateBand(_dec(band.get("min")), _dec(band.get("mid")), _dec(band.get("max"))),
        non_competitive=bool(row.get("non_competitive")),
        floor=floor,
        floor_is_rate=floor_is_rate,
        user_input=bool(row.get("user_input")),
        option=str(options["option"]) if options.get("option") else None,
        option_rates={str(k): _dec(v) or _ZERO for k, v in (options.get("rates") or {}).items()},
        meta={k: v for k, v in row.items() if k not in _LINE_KEYS},
    )


_LINE_KEYS = {
    "code",
    "base",
    "rate",
    "group",
    "kind",
    "coefficient",
    "band",
    "non_competitive",
    "floor",
    "user_input",
    "rate_options",
}
_SCHEDULE_KEYS = {
    "key",
    "jurisdiction",
    "lines",
    "edition",
    "effective_from",
    "effective_to",
    "superseded_by",
    "labour_factor",
    "vat_rates",
    "options",
}


def schedule_from_dict(data: Mapping[str, Any]) -> FeeSchedule:
    """Build a schedule from its JSON form; unknown keys are kept in ``meta``."""
    defaults = {
        str(o["key"]): str(o.get("default") or (o.get("values") or [""])[0])
        for o in data.get("options") or []
        if o.get("key")
    }
    return FeeSchedule(
        key=str(data["key"]),
        jurisdiction=str(data.get("jurisdiction") or ""),
        lines=tuple(_line_from_dict(row) for row in data.get("lines") or []),
        edition=str(data.get("edition") or ""),
        effective_from=_date(data.get("effective_from")),
        effective_to=_date(data.get("effective_to")),
        superseded_by=data.get("superseded_by") or None,
        labour_factor=_dec(data.get("labour_factor")),
        vat_rates={str(k): _dec(v) or _ZERO for k, v in (data.get("vat_rates") or {"general": "9"}).items()},
        option_defaults=defaults,
        meta={k: v for k, v in data.items() if k not in _SCHEDULE_KEYS} | {"options": list(data.get("options") or [])},
    )


def in_force(schedule: FeeSchedule, on: date | None) -> bool:
    """True when ``on`` falls inside the schedule's dates; an unknown date is not judged."""
    if on is None:
        return True
    if schedule.effective_from and on < schedule.effective_from:
        return False
    return not (schedule.effective_to and on > schedule.effective_to)


def resolve(schedules: Iterable[FeeSchedule], on: date | None) -> FeeSchedule | None:
    """The schedule in force on ``on``; the latest start wins when several are.

    Without a date the newest schedule is returned, so a new project sees the
    current rules rather than nothing.
    """
    pool = [s for s in schedules if in_force(s, on)]
    if not pool:
        return None
    return max(pool, key=lambda s: s.effective_from or date.min)


def compute(
    schedule: FeeSchedule,
    components: Mapping[str, Any],
    *,
    rates: Mapping[str, Any] | None = None,
    options: Mapping[str, str] | None = None,
    apply_labour_factor: bool = True,
    tax_method: str = "general",
    tax_inclusive: Any = None,
) -> FeeResult:
    """Run ``schedule`` over component sums and return every line and the total.

    Args:
        schedule: The programme to apply.
        components: Sums per term of :data:`COMPONENT_TERMS`, tax-exclusive.
        rates: User rates in percent per line code; they win over the source.
        options: Chosen option values (zone, grade, class) per option key.
        apply_labour_factor: Whether the schedule's labour factor is applied.
        tax_method: Key into the schedule's ``vat_rates``; unknown reads as 0.
        tax_inclusive: Amounts already carrying their VAT, added after VAT.
    """
    rates = {k: d for k, v in (rates or {}).items() if (d := _dec(v)) is not None}
    chosen = {**schedule.option_defaults, **{k: str(v) for k, v in (options or {}).items() if v}}
    comp = {term: _dec(components.get(term)) or _ZERO for term in COMPONENT_TERMS}
    factor_applied = bool(apply_labour_factor and schedule.labour_factor is not None)
    if factor_applied and schedule.labour_factor is not None:
        comp["labour"] = _cents(comp["labour"] * schedule.labour_factor)
    direct = sum((comp[t] for t in KIND_TERMS), _ZERO)

    amounts: dict[str, Decimal] = {}
    groups: dict[str, Decimal] = {}
    out: list[LineResult] = []
    for line in schedule.lines:
        base = _ZERO
        for term, weight in line.base.items():
            if term == "direct":
                value = direct
            elif term == "fenbu":
                value = direct + groups.get("fenbu", _ZERO)
            elif term.startswith("line:"):
                value = amounts.get(term[5:], _ZERO)
            elif term.startswith("group:"):
                value = groups.get(term[6:], _ZERO)
            else:
                value = comp.get(term, _ZERO)
            base += value * weight
        published = line.published_rate(chosen)
        if line.code in rates:
            rate: Decimal | None = rates[line.code]
            status = "user"
        else:
            rate = published
            status = "published" if rate is not None else "missing"
        amount = _cents(base * rate * line.coefficient / _HUNDRED) if rate is not None else _ZERO
        amounts[line.code] = amount
        groups[line.group] = groups.get(line.group, _ZERO) + amount
        out.append(
            LineResult(
                line.code,
                line.group,
                line.kind,
                _cents(base),
                rate,
                line.coefficient,
                amount,
                status,
                published,
                line.effective_floor(chosen),
            )
        )

    subtotals = {"direct": direct, "fenbu": direct + groups.get("fenbu", _ZERO)}
    subtotals.update({f"group:{g}": v for g, v in groups.items()})
    outside = sum((comp[t] for t in OUTSIDE_TERMS), _ZERO)
    pre_tax = direct + outside + sum(amounts.values(), _ZERO)
    vat_rate = schedule.vat_rates.get(tax_method, _ZERO)
    vat = _cents(pre_tax * vat_rate / _HUNDRED)
    inclusive = _dec(tax_inclusive) or _ZERO
    return FeeResult(
        schedule_key=schedule.key,
        labour=comp["labour"],
        labour_factor_applied=factor_applied,
        direct=direct,
        lines=tuple(out),
        subtotals=subtotals,
        pre_tax=pre_tax,
        vat_rate=vat_rate,
        vat=vat,
        tax_inclusive=inclusive,
        total=pre_tax + vat + inclusive,
        options=chosen,
    )
