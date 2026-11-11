# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Input tax on one assembly component, in exact decimal arithmetic.

This is the optional, per-project component-tax layer. It never runs unless the
project switches ``component_tax_enabled`` on, and a component that carries no
``tax_status`` (its own or its catalog resource's) is left exactly as it was.
It is independent of the BOQ tax markup (output tax on a bill): nothing here
reads or writes a markup.

Per line, with ``r`` the rate as a fraction:

* ``net  = price / (1 + r)`` when the entered price already includes tax,
  otherwise ``price``;
* ``tax  = net * r`` (taken as ``price - net`` for an inclusive price, so
  ``net + tax`` equals the entered price to the cent);
* ``cost = net + tax`` when the tax is cost-incorporated, otherwise ``net``.

Rounding happens once per line, in :func:`compute_line_tax`, to the currency's
minor unit, half up. Totals are plain sums of rounded lines.

No rate is ever assumed: an unresolved rate is reported, never defaulted.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from app.core.currency_registry import money_quantum
from app.modules.i18n_foundation.tax_rules import TaxRateRow, TaxRuleError, active_rows, resolve

TAX_STATUSES = ("taxable", "exempt", "out_of_scope")
TAX_TREATMENTS = ("recoverable", "cost_incorporated")
#: Used when neither the component, its resource nor the project says. A project states it explicitly
#: in its settings; this is only the value a project is created with.
DEFAULT_TREATMENT = "recoverable"

_HUNDRED = Decimal("100")
_ONE = Decimal("1")
_ZERO = Decimal("0")

#: Rate-resolution outcomes besides a resolved rate.
UNRESOLVED_REASONS = ("no_rate", "invalid_rate", "no_country", "unknown_code", "outside_validity", "unresolved")


def to_decimal(value: object) -> Decimal | None:
    """A finite Decimal, or ``None`` for blank, malformed or non-finite input."""
    if value is None or value == "":
        return None
    try:
        out = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        return None
    return out if out.is_finite() else None


@dataclass(frozen=True)
class EffectiveTax:
    """A component's tax classification after the resource defaults are merged in."""

    status: str | None
    code: str | None
    includes_tax: bool
    treatment: str | None


@dataclass(frozen=True)
class RateResult:
    """The rate for one component and where it came from."""

    rate_pct: Decimal | None
    #: ``component`` | ``component_code`` | ``resource`` | ``resource_code`` | ``None`` when unresolved.
    source: str | None
    #: One of :data:`UNRESOLVED_REASONS` when ``rate_pct`` is ``None``.
    reason: str | None = None
    #: ``False`` when the code is on file but no row of it is in force on the date.
    in_force: bool = True


@dataclass(frozen=True)
class LineTax:
    """The tax breakdown of one component line, every figure rounded."""

    status: str
    rate_pct: Decimal
    includes_tax: bool
    treatment: str
    net: Decimal
    tax: Decimal
    tax_in_cost: Decimal
    tax_recoverable: Decimal
    cost: Decimal
    gross_outlay: Decimal

    def as_dict(self) -> dict[str, Any]:
        """JSON-safe form, stored on the component metadata."""
        return {
            "status": self.status,
            "rate_pct": str(self.rate_pct),
            "price_includes_tax": self.includes_tax,
            "treatment": self.treatment,
            "net": str(self.net),
            "tax": str(self.tax),
            "tax_in_cost": str(self.tax_in_cost),
            "tax_recoverable": str(self.tax_recoverable),
            "cost": str(self.cost),
            "gross_outlay": str(self.gross_outlay),
        }


def _clean(value: object) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None


def effective_tax(component: Any, resource: Any | None, project_treatment: str | None) -> EffectiveTax:
    """Merge a component's own tax fields over its catalog resource's defaults.

    A field the component leaves ``None`` is read from the resource; ``price_includes_tax`` is a
    plain boolean on both, so the component's value wins only when it is explicitly set on the
    component (``None`` means inherit).
    """

    def pick(name: str) -> object:
        own = getattr(component, name, None)
        if own is not None and own != "":
            return own
        return getattr(resource, name, None) if resource is not None else None

    includes = pick("price_includes_tax")
    return EffectiveTax(
        status=_clean(pick("tax_status")),
        code=_clean(pick("tax_code")),
        includes_tax=bool(includes),
        treatment=_clean(pick("input_tax_treatment")) or _clean(project_treatment),
    )


def _code_rate(
    code: str, rows: Sequence[TaxRateRow], country: str | None, subdivision: str | None, on_date: str
) -> tuple[Decimal | None, str | None, bool]:
    """Rate of a registry ``tax_code``: ``(rate, reason, in_force)``."""
    if not country:
        return None, "no_country", True
    wanted = code.strip().upper()
    code_rows = [
        r
        for r in rows
        if r.country_code.strip().upper() == country.strip().upper() and (r.tax_code or "").strip().upper() == wanted
    ]
    if not code_rows:
        return None, "unknown_code", True
    in_force = active_rows(code_rows, country, on_date)
    if not in_force:
        return None, "outside_validity", False
    try:
        if len(in_force) == 1 and in_force[0].combination in ("national", "federal"):
            return Decimal(in_force[0].rate_pct), None, True
        resolution = resolve(in_force, country, subdivision, on_date)
    except (TaxRuleError, InvalidOperation):
        return None, "unresolved", True
    rate = to_decimal(resolution.combined_rate_pct) if resolution.resolved else None
    if rate is None:
        return None, "unresolved", True
    return rate, None, True


def resolve_rate(
    component: Any,
    resource: Any | None,
    *,
    rows: Sequence[TaxRateRow],
    country: str | None,
    subdivision: str | None,
    on_date: str,
) -> RateResult:
    """Component rate, then component code, then the resource's rate, then the resource's code."""
    for owner, label in ((component, "component"), (resource, "resource")):
        if owner is None:
            continue
        explicit = to_decimal(getattr(owner, "tax_rate", None))
        if explicit is not None:
            if not _ZERO <= explicit <= _HUNDRED:
                return RateResult(None, None, "invalid_rate")
            return RateResult(explicit, label)
        code = _clean(getattr(owner, "tax_code", None))
        if code:
            rate, reason, in_force = _code_rate(code, rows, country, subdivision, on_date)
            if rate is not None:
                return RateResult(rate, f"{label}_code")
            return RateResult(None, None, reason, in_force)
    return RateResult(None, None, "no_rate")


def compute_line_tax(
    price: Decimal,
    *,
    status: str,
    rate_pct: Decimal | None,
    includes_tax: bool,
    treatment: str,
    currency: str | None,
) -> LineTax:
    """Split one entered line price into net, tax, cost and outlay.

    ``exempt`` and ``out_of_scope`` lines carry no tax whatever rate or inclusive flag they hold.
    """
    quantum = money_quantum(currency)

    def q(value: Decimal) -> Decimal:
        return value.quantize(quantum, rounding=ROUND_HALF_UP)

    taxable = status == "taxable" and rate_pct is not None
    rate = rate_pct if taxable and rate_pct is not None else _ZERO
    fraction = rate / _HUNDRED
    if taxable and includes_tax:
        net = q(price / (_ONE + fraction))
        tax = q(price) - net
    else:
        net = q(price)
        tax = q(net * fraction)
    in_cost = tax if treatment == "cost_incorporated" else _ZERO
    recoverable = tax if treatment == "recoverable" else _ZERO
    return LineTax(
        status=status,
        rate_pct=rate,
        includes_tax=bool(includes_tax and taxable),
        treatment=treatment,
        net=net,
        tax=tax,
        tax_in_cost=in_cost,
        tax_recoverable=recoverable,
        cost=net + in_cost,
        gross_outlay=net + tax,
    )


def sum_lines(lines: Sequence[dict[str, Any]], bid_factor: Decimal) -> dict[str, str]:
    """Assembly totals from stored line breakdowns, scaled by the bid factor like ``total_rate``."""
    keys = ("net", "tax", "tax_in_cost", "tax_recoverable", "cost", "gross_outlay")
    out = dict.fromkeys(keys, _ZERO)
    for line in lines:
        for k in keys:
            out[k] += to_decimal(line.get(k)) or _ZERO
    return {k: str(v * bid_factor) for k, v in out.items()}
