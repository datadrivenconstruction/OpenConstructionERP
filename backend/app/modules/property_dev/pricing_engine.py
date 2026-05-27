"""Property-dev pricing engine — rule-driven, versioned, Decimal-exact.

Computes a final sale price for a plot by:

    1. Looking up the per-plot ``base_price`` from a :class:`PriceListEntry`.
    2. Iterating the active :class:`PricingRule` objects on the price list
       in ``priority`` order (lower first).
    3. For each rule, checking match conditions against
       (plot, buyer, quote_date, promo_code, bulk basket).
    4. Applying the matched rule's ``adjustment_pct`` then
       ``adjustment_fixed`` to the running subtotal, recording the change
       on a :class:`PriceQuoteLine` so the UI can render the waterfall.
    5. Returning a :class:`PriceQuote` (lines + total + currency +
       price_list_id + computed_at).

Decimal arithmetic throughout — never float (a single 0.1 round-trip can
shift the final price by cents). Quantize to 2dp on emit to keep the
wire format predictable.

Rule types and their ``condition_json`` shapes:

    early_bird     {"before": "2026-08-01"}
    view_premium   {"plot_attribute": "view", "values": ["sea", "park"]}
    floor_premium  {"min_floor": 10}  OR  {"floor": 12}
    corner_premium {"plot_attribute": "is_corner", "value": true}
    size_premium   {"min_area_m2": "100"}  (or "max_area_m2")
    promo_code     {"code": "LAUNCH25"}    (case-insensitive)
    friends_family {"buyer_tag": "ff"}
    loyalty        {"prior_purchases_min": 1}
    bulk_buy       {"min_plots": 3}

The matcher reads plot attributes from ``Plot`` columns first (``view_type``,
``level_in_block``, ``area_m2``) and falls back to ``Plot.metadata_`` for
custom flags (``is_corner``, custom view tags). Buyer tags come from
``Buyer.metadata_["tags"]`` (list of strings). Prior-purchases lookup
counts the buyer's existing reservations against this engine — caller
supplies the count to keep the engine stateless and testable.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Iterable

from pydantic import BaseModel, ConfigDict, Field, field_serializer

# Public rule-type tokens. Kept module-level so router, schema, UI and
# tests share one source of truth.
RULE_TYPES = (
    "early_bird",
    "view_premium",
    "floor_premium",
    "corner_premium",
    "size_premium",
    "promo_code",
    "friends_family",
    "loyalty",
    "bulk_buy",
)


# ── Quote DTOs ──────────────────────────────────────────────────────────


def _serialize_money(value: Decimal | None) -> str | None:
    """Plain-decimal string serializer for wire format (mirrors schemas.py)."""
    if value is None:
        return None
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    if not value.is_finite():
        return "0"
    return format(value, "f")


class PriceQuoteLine(BaseModel):
    """One line in a price-quote waterfall.

    ``rule_id`` is None for the synthetic base-price line. ``amount`` is
    the **absolute change** applied to the running subtotal (negative
    for a discount, positive for a premium); the base-price line uses
    its absolute price as ``amount`` so a sum(lines.amount) reproduces
    the total.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    rule_id: uuid.UUID | None = None
    rule_name: str = ""
    rule_type: str = "base"
    pct: Decimal | None = None
    fixed: Decimal | None = None
    amount: Decimal = Decimal("0")

    @field_serializer("amount", "pct", "fixed", when_used="json")
    @classmethod
    def _ser_money(cls, v: Decimal | None) -> str | None:
        return _serialize_money(v)


class PriceQuote(BaseModel):
    """A computed sale-price breakdown for a plot.

    Captured as JSON onto :class:`Reservation.price_breakdown_snapshot`
    when a reservation is created, so the Quote History tab can prove
    which exact discounts the buyer received.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    plot_id: uuid.UUID
    base_price: Decimal = Decimal("0")
    lines: list[PriceQuoteLine] = Field(default_factory=list)
    total: Decimal = Decimal("0")
    currency: str = ""
    computed_at: datetime
    price_list_id: uuid.UUID | None = None

    @field_serializer("base_price", "total", when_used="json")
    @classmethod
    def _ser_money(cls, v: Decimal) -> str:
        return _serialize_money(v) or "0"


# ── Helpers ─────────────────────────────────────────────────────────────


_TWO_DP = Decimal("0.01")


def _q(value: Decimal | int | str) -> Decimal:
    """Quantize a Decimal-ish to 2 dp using HALF_UP (banker's rounding off)."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    if not value.is_finite():
        value = Decimal("0")
    return value.quantize(_TWO_DP, rounding=ROUND_HALF_UP)


def _parse_iso_date(s: str | None) -> date | None:
    if not s:
        return None
    try:
        return date.fromisoformat(s[:10])
    except (ValueError, TypeError):
        return None


def _plot_attr(plot: Any, attr: str) -> Any:
    """Read a named attribute from a Plot, falling back to metadata_."""
    if hasattr(plot, attr):
        v = getattr(plot, attr)
        if v is not None:
            return v
    meta = getattr(plot, "metadata_", None) or {}
    if isinstance(meta, dict) and attr in meta:
        return meta[attr]
    return None


def _buyer_tags(buyer: Any) -> set[str]:
    if buyer is None:
        return set()
    meta = getattr(buyer, "metadata_", None) or {}
    tags = meta.get("tags") if isinstance(meta, dict) else None
    if isinstance(tags, list):
        return {str(t).strip().lower() for t in tags if t}
    return set()


# ── Rule matchers ───────────────────────────────────────────────────────
#
# Each matcher returns True/False. Matchers are PURE — they never read
# the database; everything they need is passed in. This keeps the engine
# trivially unit-testable.


def _match_early_bird(cond: dict, quote_date: date) -> bool:
    before = _parse_iso_date(cond.get("before"))
    return before is not None and quote_date < before


def _match_view_premium(cond: dict, plot: Any) -> bool:
    attr = cond.get("plot_attribute", "view")
    values = cond.get("values") or []
    if not values:
        return False
    plot_attr = "view_type" if attr == "view" else attr
    actual = _plot_attr(plot, plot_attr)
    if actual is None:
        return False
    actual_norm = str(actual).strip().lower()
    return any(str(v).strip().lower() == actual_norm for v in values)


def _match_floor_premium(cond: dict, plot: Any) -> bool:
    floor = _plot_attr(plot, "level_in_block")
    if floor is None:
        # Fall back to metadata.floor in case the plot uses a custom key.
        floor = _plot_attr(plot, "floor")
    if floor is None:
        return False
    try:
        floor_int = int(floor)
    except (TypeError, ValueError):
        return False
    if "floor" in cond:
        try:
            return floor_int == int(cond["floor"])
        except (TypeError, ValueError):
            return False
    if "min_floor" in cond:
        try:
            return floor_int >= int(cond["min_floor"])
        except (TypeError, ValueError):
            return False
    return False


def _match_corner_premium(cond: dict, plot: Any) -> bool:
    attr = cond.get("plot_attribute", "is_corner")
    expected = cond.get("value", True)
    actual = _plot_attr(plot, attr)
    if actual is None:
        return False
    if isinstance(actual, str):
        actual = actual.strip().lower() in {"1", "true", "yes", "y"}
    return bool(actual) == bool(expected)


def _match_size_premium(cond: dict, plot: Any) -> bool:
    area = getattr(plot, "area_m2", None) or _plot_attr(plot, "area_m2")
    if area is None:
        return False
    try:
        area_dec = Decimal(str(area))
    except Exception:  # noqa: BLE001
        return False
    if "min_area_m2" in cond:
        try:
            if area_dec < Decimal(str(cond["min_area_m2"])):
                return False
        except Exception:  # noqa: BLE001
            return False
    if "max_area_m2" in cond:
        try:
            if area_dec > Decimal(str(cond["max_area_m2"])):
                return False
        except Exception:  # noqa: BLE001
            return False
    # If neither bound supplied, never match (avoid accidental apply-all).
    return "min_area_m2" in cond or "max_area_m2" in cond


def _match_promo_code(cond: dict, promo_code: str | None) -> bool:
    if not promo_code:
        return False
    expected = str(cond.get("code", "")).strip().lower()
    return expected != "" and expected == promo_code.strip().lower()


def _match_friends_family(cond: dict, buyer: Any) -> bool:
    expected = str(cond.get("buyer_tag", "ff")).strip().lower()
    return expected in _buyer_tags(buyer)


def _match_loyalty(cond: dict, prior_purchases: int) -> bool:
    try:
        threshold = int(cond.get("prior_purchases_min", 1))
    except (TypeError, ValueError):
        return False
    return prior_purchases >= threshold


def _match_bulk_buy(cond: dict, basket_size: int) -> bool:
    try:
        threshold = int(cond.get("min_plots", 2))
    except (TypeError, ValueError):
        return False
    return basket_size >= threshold


def _rule_matches(
    rule: Any,
    *,
    plot: Any,
    buyer: Any,
    quote_date: date,
    promo_code: str | None,
    basket_size: int,
    prior_purchases: int,
) -> bool:
    """Dispatch a rule to its type-specific matcher."""
    rt = (rule.rule_type or "").strip().lower()
    cond = rule.condition_json or {}
    if not isinstance(cond, dict):
        return False

    # Effective-date window
    eff_from = _parse_iso_date(getattr(rule, "effective_from", None))
    eff_to = _parse_iso_date(getattr(rule, "effective_to", None))
    if eff_from is not None and quote_date < eff_from:
        return False
    if eff_to is not None and quote_date > eff_to:
        return False

    # max_uses cap
    max_uses = getattr(rule, "max_uses", None)
    times_used = getattr(rule, "times_used", 0) or 0
    if max_uses is not None and times_used >= max_uses:
        return False

    if rt == "early_bird":
        return _match_early_bird(cond, quote_date)
    if rt == "view_premium":
        return _match_view_premium(cond, plot)
    if rt == "floor_premium":
        return _match_floor_premium(cond, plot)
    if rt == "corner_premium":
        return _match_corner_premium(cond, plot)
    if rt == "size_premium":
        return _match_size_premium(cond, plot)
    if rt == "promo_code":
        return _match_promo_code(cond, promo_code)
    if rt == "friends_family":
        return _match_friends_family(cond, buyer)
    if rt == "loyalty":
        return _match_loyalty(cond, prior_purchases)
    if rt == "bulk_buy":
        return _match_bulk_buy(cond, basket_size)
    return False


# ── Pure engine (sync, side-effect-free) ────────────────────────────────


def compute_quote_pure(
    *,
    plot: Any,
    price_list: Any,
    base_price: Decimal,
    rules: Iterable[Any],
    buyer: Any | None = None,
    promo_code: str | None = None,
    quote_date: date | None = None,
    basket_size: int = 1,
    prior_purchases: int = 0,
    computed_at: datetime | None = None,
) -> PriceQuote:
    """Pure pricing computation — no I/O, fully testable.

    Caller resolves ``base_price`` (from PriceListEntry or fallback) and
    passes the list of candidate ``rules`` (already filtered by
    ``active=True``; we re-check effective dates and max_uses here so
    test fixtures don't need to). Rules are sorted by ``priority`` ASC.
    """
    if quote_date is None:
        quote_date = datetime.now(UTC).date()
    if computed_at is None:
        computed_at = datetime.now(UTC)

    base = _q(base_price)
    lines: list[PriceQuoteLine] = [
        PriceQuoteLine(
            rule_id=None,
            rule_name="Base price",
            rule_type="base",
            pct=None,
            fixed=None,
            amount=base,
        )
    ]
    subtotal = base

    sorted_rules = sorted(
        (r for r in rules if getattr(r, "active", True)),
        key=lambda r: (int(getattr(r, "priority", 100) or 100), str(getattr(r, "name", ""))),
    )
    for rule in sorted_rules:
        if not _rule_matches(
            rule,
            plot=plot,
            buyer=buyer,
            quote_date=quote_date,
            promo_code=promo_code,
            basket_size=basket_size,
            prior_purchases=prior_purchases,
        ):
            continue
        pct = Decimal(str(getattr(rule, "adjustment_pct", 0) or 0))
        fixed_raw = getattr(rule, "adjustment_fixed", None)
        fixed = Decimal(str(fixed_raw)) if fixed_raw is not None else None
        delta = Decimal("0")
        if pct != 0:
            delta += subtotal * (pct / Decimal("100"))
        if fixed is not None:
            delta += fixed
        delta_q = _q(delta)
        new_subtotal = _q(subtotal + delta_q)
        lines.append(
            PriceQuoteLine(
                rule_id=getattr(rule, "id", None),
                rule_name=str(getattr(rule, "name", "")) or rule.rule_type,
                rule_type=str(getattr(rule, "rule_type", "custom")),
                pct=pct if pct != 0 else None,
                fixed=fixed,
                amount=delta_q,
            )
        )
        subtotal = new_subtotal

    return PriceQuote(
        plot_id=plot.id,
        base_price=base,
        lines=lines,
        total=_q(subtotal),
        currency=getattr(price_list, "currency", "") or getattr(plot, "currency", "") or "",
        computed_at=computed_at,
        price_list_id=getattr(price_list, "id", None),
    )


# ── Async DB-aware wrapper ──────────────────────────────────────────────


async def compute_final_price(
    *,
    plot: Any,
    price_list: Any,
    buyer: Any | None,
    promo_code: str | None,
    quote_date: date,
    bulk_basket: list[Any] | None = None,
    rules: Iterable[Any] | None = None,
    base_price: Decimal | None = None,
    prior_purchases: int = 0,
) -> PriceQuote:
    """High-level helper used by the router.

    The service layer pre-loads ``rules`` (the price list's active
    PricingRule rows ordered by priority) and ``base_price`` (from the
    PriceListEntry for ``plot``, falling back to ``plot.price_base``).
    Passing both as kwargs keeps this function trivially testable: the
    test suite calls it with hand-rolled fixture objects, no DB needed.
    """
    if rules is None:
        rules = getattr(price_list, "_rules_cache", []) or []
    if base_price is None:
        base_price = Decimal(str(getattr(plot, "price_base", 0) or 0))
    basket_size = len(bulk_basket) if bulk_basket else 1
    return compute_quote_pure(
        plot=plot,
        price_list=price_list,
        base_price=base_price,
        rules=rules,
        buyer=buyer,
        promo_code=promo_code,
        quote_date=quote_date,
        basket_size=basket_size,
        prior_purchases=prior_purchases,
    )


__all__ = [
    "PriceQuote",
    "PriceQuoteLine",
    "RULE_TYPES",
    "compute_final_price",
    "compute_quote_pure",
]
