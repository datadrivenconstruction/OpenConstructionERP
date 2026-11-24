# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Domain model and math for a unit-price breakdown.

Everything here is pure and Decimal-exact so it is trivially testable and can
be driven from a stored assembly, a BoQ position, or an ad-hoc dict.

Markup convention (explicit on purpose, because standards word it differently):

    direct        = sum of all component amounts (per one unit of the position)
    overhead      = direct * overhead_pct / 100
    risk          = (direct + overhead) * risk_pct / 100
    profit        = (direct + overhead + risk) * profit_pct / 100
    unit_rate     = direct + overhead + risk + profit
    position_total = unit_rate * position_quantity

Overhead, risk and profit are applied in that order and each on the running
subtotal, which matches how site overhead, contingency and profit stack in a
detailed rate build-up. All percentages are optional and default to zero, so a
plain material-plus-labour rate works with no markup configured.

Markup percentages are clamped when a breakdown is assembled via
:func:`build_breakdown`: a negative percentage (which would reduce the rate
below direct cost, a nonsense in a build-up) is treated as zero, and a value
above :data:`MAX_MARKUP_PCT` is capped there so a stray "800" typed as a
fraction or a runaway import cannot silently produce an absurd unit rate. The
clamp is deliberate and documented rather than raising, so a bulk import of
many positions never fails on one bad markup cell.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum

from app.core.money import money_quantum as core_money_quantum

_2P = Decimal("0.01")
_4P = Decimal("0.0001")


def money_quantum(currency: str | None) -> Decimal:
    """Rounding step for one unit of ``currency``.

    A unit price analysis in a currency with no minor unit was printing cents:
    a Chilean peso rate read ``82000.00 CLP``, which is not a number anyone in
    Chile writes and reads as false precision on a tendered rate. The registry
    in ``app.core.money`` already knows CLP has no cents, JPY and KRW likewise;
    nothing on this path was asking it.

    Kept as this module's own name because its callers read better for it, but
    it is a straight alias now: the quantum comes from
    :func:`app.core.money.money_quantum`, which is where the value layer's
    minor-unit rule lives. It used to be a local ``{0, 2, 3} -> quantum`` table
    that silently returned two decimals for any digit count it did not list -
    a second registry agreeing with the first only for as long as nobody added
    a row to either.

    Falls back to two decimals for a currency the registry does not carry,
    which is the historical behaviour and the right guess for most codes.
    """
    return core_money_quantum(currency)


# A markup above this many percent is treated as a data error and capped. Real
# site overhead + risk + profit almost never exceeds a few tens of percent;
# 1000% is a generous ceiling that still blocks obviously broken values.
MAX_MARKUP_PCT = Decimal("1000")


class PriceBreakdownError(ValueError):
    """Raised when a breakdown cannot be assembled or is inconsistent."""


class ResourceKind(StrEnum):
    """Cost categories shared by detailed-rate standards worldwide.

    The string values match the vocabulary the rest of the platform already
    stores (``Component.resource_type`` and the BoQ cost breakdown), so a
    breakdown reads and writes the same tokens: labor, material, machinery,
    equipment, subcontractor, other. Machinery (plant that performs work) is
    kept distinct from equipment (installed or hired), matching the platform's
    methodology; a preset can merge them under one "plant" heading for display.
    """

    LABOUR = "labor"
    MATERIAL = "material"
    MACHINERY = "machinery"
    EQUIPMENT = "equipment"
    SUBCONTRACT = "subcontractor"
    OTHER = "other"


# Accept common synonyms so callers/imports do not have to pre-normalise.
# Keys are lower-cased. International terms (German, French, Spanish, Italian,
# Russian) are included so cost data exported from local estimating software in
# those languages maps onto the shared vocabulary without a manual pass.
_KIND_ALIASES = {
    # English
    "labor": ResourceKind.LABOUR,
    "labour": ResourceKind.LABOUR,
    "wage": ResourceKind.LABOUR,
    "wages": ResourceKind.LABOUR,
    "operator": ResourceKind.LABOUR,
    "crew": ResourceKind.LABOUR,
    "material": ResourceKind.MATERIAL,
    "materials": ResourceKind.MATERIAL,
    "machinery": ResourceKind.MACHINERY,
    "machine": ResourceKind.MACHINERY,
    "plant": ResourceKind.MACHINERY,
    "equipment": ResourceKind.EQUIPMENT,
    "subcontractor": ResourceKind.SUBCONTRACT,
    "subcontract": ResourceKind.SUBCONTRACT,
    "sub": ResourceKind.SUBCONTRACT,
    "overhead": ResourceKind.OTHER,
    "other": ResourceKind.OTHER,
    "misc": ResourceKind.OTHER,
    # German
    "lohn": ResourceKind.LABOUR,
    "lohnkosten": ResourceKind.LABOUR,
    "arbeit": ResourceKind.LABOUR,
    "arbeitskosten": ResourceKind.LABOUR,
    "stoffkosten": ResourceKind.MATERIAL,
    "baustoff": ResourceKind.MATERIAL,
    "baustoffe": ResourceKind.MATERIAL,
    "maschine": ResourceKind.MACHINERY,
    "maschinen": ResourceKind.MACHINERY,
    "geraet": ResourceKind.EQUIPMENT,
    "geraete": ResourceKind.EQUIPMENT,
    "vorhaltekosten": ResourceKind.EQUIPMENT,
    "nachunternehmer": ResourceKind.SUBCONTRACT,
    "nachunternehmerleistung": ResourceKind.SUBCONTRACT,
    "sonstiges": ResourceKind.OTHER,
    "sonstige": ResourceKind.OTHER,
    # French
    "main d'oeuvre": ResourceKind.LABOUR,
    "main-d'oeuvre": ResourceKind.LABOUR,
    "mo": ResourceKind.LABOUR,
    "materiau": ResourceKind.MATERIAL,
    "materiaux": ResourceKind.MATERIAL,
    "fourniture": ResourceKind.MATERIAL,
    "fournitures": ResourceKind.MATERIAL,
    "engin": ResourceKind.MACHINERY,
    "engins": ResourceKind.MACHINERY,
    "materiel": ResourceKind.EQUIPMENT,
    "sous-traitant": ResourceKind.SUBCONTRACT,
    "sous-traitance": ResourceKind.SUBCONTRACT,
    "divers": ResourceKind.OTHER,
    # Spanish
    "mano de obra": ResourceKind.LABOUR,
    "materiales": ResourceKind.MATERIAL,
    "maquinaria": ResourceKind.MACHINERY,
    "equipo": ResourceKind.EQUIPMENT,
    "equipos": ResourceKind.EQUIPMENT,
    "subcontrata": ResourceKind.SUBCONTRACT,
    "subcontratista": ResourceKind.SUBCONTRACT,
    "otros": ResourceKind.OTHER,
    # Italian
    "manodopera": ResourceKind.LABOUR,
    "mano d'opera": ResourceKind.LABOUR,
    "materiale": ResourceKind.MATERIAL,
    "materiali": ResourceKind.MATERIAL,
    "macchina": ResourceKind.MACHINERY,
    "macchinari": ResourceKind.MACHINERY,
    "noli": ResourceKind.MACHINERY,
    "attrezzatura": ResourceKind.EQUIPMENT,
    "attrezzature": ResourceKind.EQUIPMENT,
    "subappalto": ResourceKind.SUBCONTRACT,
    "subappaltatore": ResourceKind.SUBCONTRACT,
    "altro": ResourceKind.OTHER,
    # Russian
    "труд": ResourceKind.LABOUR,
    "рабочие": ResourceKind.LABOUR,
    "зарплата": ResourceKind.LABOUR,
    "оплата труда": ResourceKind.LABOUR,
    "трудозатраты": ResourceKind.LABOUR,
    "материал": ResourceKind.MATERIAL,
    "материалы": ResourceKind.MATERIAL,
    "машины": ResourceKind.MACHINERY,
    "механизмы": ResourceKind.MACHINERY,
    "оборудование": ResourceKind.EQUIPMENT,
    "субподряд": ResourceKind.SUBCONTRACT,
    "субподрядчик": ResourceKind.SUBCONTRACT,
    "прочее": ResourceKind.OTHER,
    "прочие": ResourceKind.OTHER,
}


def kind_i18n_key(kind: str | ResourceKind) -> str:
    """Return the stable i18n key for a resource kind.

    The key form is ``price_breakdown.kind.<value>`` where ``<value>`` is the
    canonical ResourceKind string (labor, material, machinery, equipment,
    subcontractor, other). These keys are data only: they let a frontend
    translate the labels later without any shared locale file being edited
    here, and they never change even as English defaults are re-worded.
    """
    return f"price_breakdown.kind.{coerce_kind(kind).value}"


# Stable i18n keys for the summary (markup) lines of a price analysis. Data
# only, same contract as kind_i18n_key: a UI may translate them, nothing here
# depends on a locale file existing.
LINE_I18N_KEYS: dict[str, str] = {
    "direct": "price_breakdown.line.direct",
    "overhead": "price_breakdown.line.overhead",
    "risk": "price_breakdown.line.risk",
    "profit": "price_breakdown.line.profit",
    "unit_rate": "price_breakdown.line.unit_rate",
    "position_total": "price_breakdown.line.position_total",
}


def _clamp_pct(value: Decimal) -> Decimal:
    """Clamp a markup percentage into a sensible range (see module docstring)."""
    if value < 0:
        return Decimal("0")
    if value > MAX_MARKUP_PCT:
        return MAX_MARKUP_PCT
    return value


def coerce_kind(value: str | ResourceKind | None) -> ResourceKind:
    """Map a free-text resource type onto a :class:`ResourceKind`."""
    if isinstance(value, ResourceKind):
        return value
    return _KIND_ALIASES.get(str(value or "").strip().lower(), ResourceKind.OTHER)


def _dec(value: object, default: str = "0") -> Decimal:
    if isinstance(value, Decimal):
        return value
    if value is None or value == "":
        return Decimal(default)
    try:
        return Decimal(str(value))
    except (ArithmeticError, ValueError, TypeError):
        return Decimal(default)


@dataclass
class CostComponent:
    """One resource line in the rate build-up, costed per position unit.

    ``amount`` is the contribution to the unit rate (quantity x unit_cost). For
    example, 0.12 t of rebar per m3 of wall at 900/t contributes 108 to the m3
    rate: quantity=0.12, unit_cost=900, amount=108.
    """

    kind: ResourceKind
    description: str
    quantity: Decimal
    unit_cost: Decimal
    unit: str = ""
    amount: Decimal = Decimal("0")

    def normalised(self) -> CostComponent:
        qty = _dec(self.quantity, "1")
        unit_cost = _dec(self.unit_cost)
        amount = _dec(self.amount) if self.amount else qty * unit_cost
        return CostComponent(
            kind=coerce_kind(self.kind),
            description=str(self.description or "").strip() or "-",
            quantity=qty,
            unit_cost=unit_cost,
            unit=str(self.unit or ""),
            amount=amount,
        )


@dataclass
class PriceBreakdown:
    """A costed unit rate broken into resources and markup."""

    position_ref: str
    description: str
    unit: str
    position_quantity: Decimal
    components: list[CostComponent]
    overhead_pct: Decimal = Decimal("0")
    risk_pct: Decimal = Decimal("0")
    profit_pct: Decimal = Decimal("0")
    currency: str = "EUR"

    # ---- derived totals (per one unit unless noted) -------------------------
    @property
    def direct_unit_cost(self) -> Decimal:
        return sum((c.amount for c in self.components), Decimal("0"))

    @property
    def kind_totals(self) -> dict[ResourceKind, Decimal]:
        totals = {k: Decimal("0") for k in ResourceKind}
        for c in self.components:
            totals[c.kind] += c.amount
        return totals

    @property
    def overhead_amount(self) -> Decimal:
        return self.direct_unit_cost * self.overhead_pct / 100

    @property
    def risk_amount(self) -> Decimal:
        return (self.direct_unit_cost + self.overhead_amount) * self.risk_pct / 100

    @property
    def profit_amount(self) -> Decimal:
        base = self.direct_unit_cost + self.overhead_amount + self.risk_amount
        return base * self.profit_pct / 100

    @property
    def unit_rate(self) -> Decimal:
        return self.direct_unit_cost + self.overhead_amount + self.risk_amount + self.profit_amount

    @property
    def position_total(self) -> Decimal:
        return self.unit_rate * self.position_quantity

    def to_dict(self) -> dict:
        """JSON-ready view (money at the currency's own precision, quantities to 4dp).

        Percentages keep two decimals whatever the currency, because a markup
        of 12.5% is 12.5% in Santiago and in Frankfurt. Only the amounts follow
        the currency.
        """
        money = money_quantum(self.currency)
        r = self.rounded_lines()
        return {
            "position_ref": self.position_ref,
            "description": self.description,
            "unit": self.unit,
            "currency": self.currency,
            "position_quantity": _q(self.position_quantity, _4P),
            "components": [
                {
                    "kind": c.kind.value,
                    "kind_i18n_key": kind_i18n_key(c.kind),
                    "description": c.description,
                    "unit": c.unit,
                    "quantity": _q(c.quantity, _4P),
                    "unit_cost": _q(c.unit_cost, money),
                    "amount": str(amount),
                }
                for c, amount in zip(self.components, r["amounts"], strict=True)
            ],
            "kind_totals": {k.value: str(v) for k, v in r["kind_totals"].items()},
            "kind_i18n_keys": {k.value: kind_i18n_key(k) for k in ResourceKind},
            "i18n_keys": dict(LINE_I18N_KEYS),
            "direct_unit_cost": str(r["direct"]),
            "overhead_pct": _q(self.overhead_pct, _2P),
            "overhead_amount": str(r["overhead"]),
            "risk_pct": _q(self.risk_pct, _2P),
            "risk_amount": str(r["risk"]),
            "profit_pct": _q(self.profit_pct, _2P),
            "profit_amount": str(r["profit"]),
            "unit_rate": str(r["unit_rate"]),
            "position_total": str(r["position_total"]),
        }

    def rounded_lines(self) -> dict:
        """Every printed line at the currency's precision, built so the sheet adds up.

        Rounding each exact figure on its own lets the printed labour, material and
        plant amounts miss the printed rate by a cent. Here each component is rounded
        once, the kind totals and direct cost are sums of those, each markup is taken
        on the rounded running subtotal, and the position total is the rounded rate
        times the quantity, as a tendered rate is priced.
        """
        money = money_quantum(self.currency)

        def rnd(value: Decimal) -> Decimal:
            return value.quantize(money, rounding=ROUND_HALF_UP)

        amounts = [rnd(c.amount) for c in self.components]
        kind_totals = {k: Decimal("0").quantize(money) for k in ResourceKind}
        for c, amount in zip(self.components, amounts, strict=True):
            kind_totals[c.kind] += amount
        direct = sum(amounts, Decimal("0").quantize(money))
        overhead = rnd(direct * self.overhead_pct / 100)
        risk = rnd((direct + overhead) * self.risk_pct / 100)
        profit = rnd((direct + overhead + risk) * self.profit_pct / 100)
        unit_rate = direct + overhead + risk + profit
        return {
            "amounts": amounts,
            "kind_totals": kind_totals,
            "direct": direct,
            "overhead": overhead,
            "risk": risk,
            "profit": profit,
            "unit_rate": unit_rate,
            "position_total": rnd(unit_rate * self.position_quantity),
        }


def _q(value: Decimal, quant: Decimal) -> str:
    return str(_dec(value).quantize(quant, rounding=ROUND_HALF_UP))


def _first(raw: dict, *keys: str) -> object:
    """First key with a value; an explicit 0 counts (a zero quantity is not one unit)."""
    for key in keys:
        if raw.get(key) not in (None, ""):
            return raw[key]
    return None


def build_breakdown(
    *,
    position_ref: str,
    description: str,
    unit: str,
    position_quantity: object,
    components: list[dict | CostComponent],
    overhead_pct: object = 0,
    risk_pct: object = 0,
    profit_pct: object = 0,
    currency: str = "EUR",
) -> PriceBreakdown:
    """Assemble a :class:`PriceBreakdown` from plain dicts or components.

    Markup percentages are clamped via :func:`_clamp_pct` (negatives become 0,
    values above :data:`MAX_MARKUP_PCT` are capped) so one bad cell in an import
    cannot produce an absurd unit rate or a rate below direct cost.
    """
    comps: list[CostComponent] = []
    for raw in components or []:
        if isinstance(raw, CostComponent):
            comps.append(raw.normalised())
            continue
        comps.append(
            CostComponent(
                kind=coerce_kind(raw.get("kind") or raw.get("resource_type")),
                description=raw.get("description") or raw.get("name") or "-",
                quantity=_dec(_first(raw, "quantity", "factor"), "1"),
                unit_cost=_dec(_first(raw, "unit_cost", "unit_rate", "price")),
                unit=raw.get("unit") or "",
                amount=_dec(raw.get("amount")) if raw.get("amount") not in (None, "") else Decimal("0"),
            ).normalised()
        )
    if not comps:
        raise PriceBreakdownError("a price breakdown needs at least one cost component")
    return PriceBreakdown(
        position_ref=str(position_ref or "").strip(),
        description=str(description or "").strip(),
        unit=str(unit or ""),
        position_quantity=_dec(position_quantity, "1"),
        components=comps,
        overhead_pct=_clamp_pct(_dec(overhead_pct)),
        risk_pct=_clamp_pct(_dec(risk_pct)),
        profit_pct=_clamp_pct(_dec(profit_pct)),
        currency=str(currency or "EUR").strip() or "EUR",
    )
