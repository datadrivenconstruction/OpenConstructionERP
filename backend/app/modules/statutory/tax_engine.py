# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Sales and use tax treatment of a construction bid - pure, no I/O.

Where a market taxes the sale of goods rather than value added, the question a
bid asks is not the rate but who owes the tax on each line and on what measure.
A contractor may be the consumer of what it installs (it pays tax to its
supplier, and the tax is a cost inside the bid), the retailer of it (it charges
the customer and reports the tax), or the seller of a taxable service where the
whole charge, labor included, is taxed. A single invoice can mix treatments.

The engine applies a treatment profile a market pack ships. A profile names
contract forms, and each form maps every line kind to one treatment:

* ``consumer`` - tax on the line's cost, paid to the supplier, a cost in the bid.
* ``retailer_in_price`` - the contractor reports the tax as retailer on the
  line's cost (or price), but the bid states no tax line; the tax sits inside
  the lump sum.
* ``retailer_collected`` - tax on the line's price, stated and collected from
  the customer.
* ``untaxed`` - outside the base.
* ``exempt`` - would be taxed but an exemption certificate takes it out.

An optional per-item surtax cap taxes only the first ``item_cap`` of the price
of any single item; a line that states its quantity is treated as that many
equal items. The rate is always an input: it belongs to the jobsite address and
the period, and the platform never ships one.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

CONSUMER = "consumer"
RETAILER_IN_PRICE = "retailer_in_price"
RETAILER_COLLECTED = "retailer_collected"
UNTAXED = "untaxed"
EXEMPT = "exempt"
TREATMENTS: frozenset[str] = frozenset({CONSUMER, RETAILER_IN_PRICE, RETAILER_COLLECTED, UNTAXED, EXEMPT})

LINE_KINDS: tuple[str, ...] = ("material", "fixture", "labor", "equipment", "other")
UNCLASSIFIED = "unclassified"

_CENT = Decimal("0.01")
_HUNDRED = Decimal("100")
_ZERO = Decimal("0")


class TaxProfileError(ValueError):
    """A pack's treatment profile cannot be applied."""


@dataclass
class TaxLine:
    """One priced line of the bid."""

    id: str
    kind: str
    cost: Decimal
    price: Decimal | None = None
    quantity: Decimal | None = None
    description: str = ""
    priced_tax: Decimal | None = None
    priced_surtax: Decimal | None = None

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> TaxLine:
        """Build a line from a request payload."""
        return cls(
            id=str(raw.get("id") or ""),
            kind=str(raw.get("kind") or UNCLASSIFIED),
            cost=_dec(raw.get("cost")) or _ZERO,
            price=_dec(raw.get("price")),
            quantity=_dec(raw.get("quantity")),
            description=str(raw.get("description") or ""),
            priced_tax=_dec(raw.get("priced_tax")),
            priced_surtax=_dec(raw.get("priced_surtax")),
        )


@dataclass
class LineResult:
    """The treatment applied to one line and the tax it carries."""

    id: str
    kind: str
    treatment: str
    measure: Decimal
    tax: Decimal
    surtax_base: Decimal
    surtax: Decimal

    def as_dict(self) -> dict[str, Any]:
        """JSON-ready form."""
        return {
            "id": self.id,
            "kind": self.kind,
            "treatment": self.treatment,
            "measure": _s(self.measure),
            "tax": _s(self.tax),
            "surtax_base": _s(self.surtax_base),
            "surtax": _s(self.surtax),
        }


@dataclass
class TaxResult:
    """Totals for the bid, split by who bears the tax."""

    contract_form: str | None
    rate_pct: Decimal | None
    surtax_pct: Decimal | None
    lines: list[LineResult] = field(default_factory=list)
    paid_to_suppliers: Decimal = _ZERO
    reported_as_retailer: Decimal = _ZERO
    charged_to_customer: Decimal = _ZERO

    @property
    def tax_in_bid(self) -> Decimal:
        """Tax the contractor carries as cost inside its price."""
        return self.paid_to_suppliers + self.reported_as_retailer

    def as_dict(self) -> dict[str, Any]:
        """JSON-ready form, money as strings."""
        return {
            "contract_form": self.contract_form,
            "rate_pct": _s(self.rate_pct),
            "surtax_pct": _s(self.surtax_pct),
            "lines": [line.as_dict() for line in self.lines],
            "paid_to_suppliers": _s(self.paid_to_suppliers),
            "reported_as_retailer": _s(self.reported_as_retailer),
            "tax_in_bid": _s(self.tax_in_bid),
            "charged_to_customer": _s(self.charged_to_customer),
        }


def _dec(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    return Decimal(str(value))


def _s(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return format(value.quantize(_CENT, rounding=ROUND_HALF_UP), "f")


def _money(value: Decimal) -> Decimal:
    return value.quantize(_CENT, rounding=ROUND_HALF_UP)


def validate_profile(profile: dict[str, Any]) -> None:
    """Raise :class:`TaxProfileError` when a profile names an unknown treatment."""
    forms = profile.get("contract_forms")
    if not isinstance(forms, dict) or not forms:
        raise TaxProfileError("a tax profile needs at least one contract form")
    for code, form in forms.items():
        treatment = form.get("treatment") if isinstance(form, dict) else None
        if not isinstance(treatment, dict):
            raise TaxProfileError(f"{code}: contract form has no treatment map")
        for kind, value in treatment.items():
            if kind not in LINE_KINDS:
                raise TaxProfileError(f"{code}: unknown line kind {kind!r}")
            if value not in TREATMENTS:
                raise TaxProfileError(f"{code}: unknown treatment {value!r} for {kind}")
        if not str(form.get("source") or "").strip():
            raise TaxProfileError(f"{code}: a tax treatment must name its source")


def surtax_base(line: TaxLine, measure: Decimal, item_cap: Decimal | None) -> Decimal:
    """The part of ``measure`` a per-item surtax reaches."""
    if item_cap is None:
        return measure
    if line.quantity and line.quantity > 0:
        unit = measure / line.quantity
        return min(unit, item_cap) * line.quantity
    return measure


def compute(
    profile: dict[str, Any],
    lines: list[TaxLine],
    *,
    contract_form: str | None,
    rate_pct: Decimal | None,
    surtax_pct: Decimal | None = None,
    exemption_certificate_on_file: bool = False,
) -> TaxResult:
    """Apply ``profile`` to ``lines`` under ``contract_form``.

    An unknown or missing form, or a missing rate, produces a result with no
    tax rather than a guess; the validators report why.
    """
    result = TaxResult(contract_form=contract_form, rate_pct=rate_pct, surtax_pct=surtax_pct)
    form = (profile.get("contract_forms") or {}).get(contract_form or "")
    if not isinstance(form, dict) or rate_pct is None:
        return result
    treatment_map: dict[str, str] = form.get("treatment") or {}
    item_cap = _dec((profile.get("surtax") or {}).get("item_cap"))
    certificate_form = form.get("exemption_certificate")
    rate = rate_pct / _HUNDRED
    surrate = (surtax_pct or _ZERO) / _HUNDRED

    for line in lines:
        treatment = treatment_map.get(line.kind) or treatment_map.get("other") or UNTAXED
        if treatment == EXEMPT and certificate_form and not exemption_certificate_on_file:
            # Without the certificate the exemption is not earned: the charge is taxed as collected.
            treatment = RETAILER_COLLECTED
        if treatment in (UNTAXED, EXEMPT):
            result.lines.append(LineResult(line.id, line.kind, treatment, _ZERO, _ZERO, _ZERO, _ZERO))
            continue
        measure = line.cost if treatment == CONSUMER else (line.price if line.price is not None else line.cost)
        base = surtax_base(line, measure, item_cap)
        tax = _money(measure * rate)
        surtax = _money(base * surrate)
        result.lines.append(LineResult(line.id, line.kind, treatment, measure, tax, base, surtax))
        if treatment == CONSUMER:
            result.paid_to_suppliers += tax + surtax
        elif treatment == RETAILER_IN_PRICE:
            result.reported_as_retailer += tax + surtax
        else:
            result.charged_to_customer += tax + surtax
    return result


__all__ = [
    "CONSUMER",
    "EXEMPT",
    "LINE_KINDS",
    "RETAILER_COLLECTED",
    "RETAILER_IN_PRICE",
    "TREATMENTS",
    "UNCLASSIFIED",
    "UNTAXED",
    "LineResult",
    "TaxLine",
    "TaxProfileError",
    "TaxResult",
    "compute",
    "surtax_base",
    "validate_profile",
]
