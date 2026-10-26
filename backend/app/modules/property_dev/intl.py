# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""International, database-free helpers for property development appraisal.

This module adds a small set of pure, side-effect-free functions that make
the development-appraisal maths clear, correct, and safe for a worldwide
audience. It is deliberately independent of the database, the ORM, and any
single locale, so it can be reused and unit-tested in isolation.

It complements the residual-appraisal helper already in ``service.py``
(``compute_residual_appraisal``) by exposing the individual building blocks
of a feasibility study as pure, well-guarded Decimal helpers, plus a light
localisation layer for appraisal term and status words.

Design rules that keep the platform international and honest:

* No hardcoded currency, unit, or locale. Currency is data that travels with
  each unit value (or is passed in explicitly); the functions never assume
  one, and never blend two currency codes into a single, meaningless total.
* Money is Decimal-exact. Every numeric input is coerced through ``Decimal``
  built from ``str(value)`` so there is no IEEE-754 drift, and no result is
  ever ``NaN`` or ``Infinity``.
* Percentages are carried as ratios (0.20 means 20 percent), not as points,
  so a caller controls rounding and display for their own locale.
* Every yield, rate, and profit target is an explicit parameter with a
  documented, worldwide-neutral default; nothing regional is baked in.
* Dates are ISO 8601 strings (YYYY-MM-DD); there is no locale date format.

Concepts, one line each (see also ``explain_figure``):

* gross development value (GDV): the total sales value of every unit in the
  scheme, all expressed in one currency.
* total development cost: every cost of delivering the scheme except the land
  itself: construction, fees, contingency, finance and sales costs.
* residual land value: what is left for the land after the total development
  cost and the target developer profit are taken out of the GDV.
* profit on cost: developer profit divided by total development cost, as a
  ratio.
* profit on GDV: developer profit divided by the gross development value, as a
  ratio.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from app.core.i18n import SUPPORTED_LOCALES as _ALL_LOCALES
from app.core.i18n import lookup

# ── Documented worldwide defaults ─────────────────────────────────────────────
# A developer profit target of zero means "take no profit line". Callers opt
# in to a positive ratio (0.20 for 20 percent) when appraising a real scheme.
DEFAULT_PROFIT_TARGET_RATIO: Decimal = Decimal("0")

# The set of locales this module localises into. English is always the
# fallback, so a missing translation or an unknown locale never breaks a
# display path or leaks a raw key.
SUPPORTED_LOCALES: tuple[str, ...] = tuple(_ALL_LOCALES)
FALLBACK_LOCALE: str = "en"


def normalise_locale(locale: str | None) -> str:
    """Reduce any locale tag to a supported base locale, or the fallback.

    Accepts tags such as ``en``, ``EN``, ``en-US``, ``de_DE`` (case- and
    separator-insensitive) and returns one of ``SUPPORTED_LOCALES``. Anything
    unknown or missing maps to ``FALLBACK_LOCALE`` (English), so a display path
    never fails on an unexpected tag.
    """
    if not locale:
        return FALLBACK_LOCALE
    base = str(locale).strip().lower().replace("_", "-").split("-", 1)[0]
    return base if base in SUPPORTED_LOCALES else FALLBACK_LOCALE


def explain_figure(figure: str | None, locale: str | None = FALLBACK_LOCALE) -> str:
    """Return a one-line, plain-language explanation of an appraisal figure.

    Args:
        figure: A figure key such as ``gross_development_value``,
            ``total_development_cost``, ``residual_land_value``,
            ``profit_on_cost`` or ``profit_on_gdv`` (case-insensitive).
        locale: A locale tag; reduced via ``normalise_locale``.

    Returns:
        The explanation string, or an empty string for an unknown figure.
    """
    key = (figure or "").strip().lower()
    return lookup(f"property_dev.figure.{key}", normalise_locale(locale)) or ""


def localize_term(term: str | None, locale: str | None = FALLBACK_LOCALE) -> str:
    """Return a localised appraisal term word, falling back to English.

    Args:
        term: A term key such as ``residual_land_value`` (case-insensitive).
        locale: A locale tag; reduced via ``normalise_locale``.

    Returns:
        The word in the requested locale, the English word if that locale has
        no translation, or an empty string for an unknown term.
    """
    key = (term or "").strip().lower()
    return lookup(f"property_dev.term.{key}", normalise_locale(locale)) or ""


def localize_status(status: str | None, locale: str | None = FALLBACK_LOCALE) -> str:
    """Return a localised feasibility status word, falling back to English.

    Unknown status codes map to the localised ``pending`` word rather than
    raising, so a display path never breaks on a new or missing code.
    """
    key = (status or "").strip().lower()
    loc = normalise_locale(locale)
    return lookup(f"property_dev.status.{key}", loc) or lookup("property_dev.status.pending", loc) or ""


# ── Numeric coercion helpers (Decimal-exact, never NaN / inf) ─────────────────


def _to_decimal(value: Any, *, field_name: str) -> Decimal:
    """Coerce any numeric-ish input to a finite ``Decimal``.

    Accepts int, float, and numeric strings (including a plain Decimal). A
    ``None``, a bool, a container, non-numeric text, or a non-finite value
    (``NaN`` / ``Infinity``) is a clean input error, so a caller never gets a
    ``NaN`` / ``inf`` back and no 500 escapes to the API.

    Raises:
        ValueError: If the value is missing or cannot be read as a finite
            number.
    """
    if value is None:
        raise ValueError(f"{field_name} is required (missing value)")
    # bool is an int subclass; True / False is almost certainly a mistake here.
    if isinstance(value, bool):
        raise ValueError(f"{field_name} must be a number, not a boolean")
    if isinstance(value, (Mapping, list, tuple, set)):
        raise ValueError(f"{field_name} must be a single number, not a container")
    try:
        dec = value if isinstance(value, Decimal) else Decimal(str(value).strip())
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError(f"{field_name} '{value}' is not a valid number") from exc
    if not dec.is_finite():
        raise ValueError(f"{field_name} must be finite (no NaN or Infinity)")
    return dec


def _non_negative(dec: Decimal, *, field_name: str) -> Decimal:
    """Return ``dec`` unchanged if it is >= 0, else raise ``ValueError``.

    Zero is allowed on purpose: a zero cost line or a scheme with no sales yet
    is well-defined, not an error. A negative value is never meaningful for a
    sale value, a cost, or a profit target.
    """
    if dec < 0:
        raise ValueError(f"{field_name} cannot be negative (got {dec})")
    return dec


def _guard_finite(dec: Decimal, *, field_name: str) -> Decimal:
    """Reject a non-finite computed result, so overflow never leaks out."""
    if not dec.is_finite():
        raise ValueError(f"{field_name} overflowed to a non-finite value")
    return dec


def _normalise_currency(currency: str | None) -> str | None:
    """Normalise a currency code to trimmed upper-case, or ``None`` if absent.

    Currency is data, never assumed. An empty / whitespace string is treated
    as "no currency stated" rather than a distinct code.
    """
    if currency is None:
        return None
    text = str(currency).strip().upper()
    return text or None


def _read_amount(entry: Any, *, index: int) -> Any:
    """Read a money amount from a number or a mapping, tolerating field aliases.

    A plain number (int / float / str / Decimal) is returned as-is. A mapping
    is searched for the first present of the common amount keys used across the
    module's payloads. A missing amount is a clean error keyed to the index.
    """
    if isinstance(entry, Mapping):
        for amount_key in ("value", "amount", "sale_price", "price", "gdv", "unit_value"):
            if amount_key in entry and entry[amount_key] is not None:
                return entry[amount_key]
        raise ValueError(f"item[{index}]: a money amount is required (missing value)")
    return entry


def _read_currency(entry: Any) -> str | None:
    """Read an optional currency code from a mapping entry, else ``None``."""
    if isinstance(entry, Mapping):
        return _normalise_currency(entry.get("currency"))
    return None


def _sum_one_currency(
    amounts: Iterable[Any],
    *,
    expected_currency: str | None,
    label: str,
) -> tuple[Decimal, str | None]:
    """Sum money amounts, enforcing a single currency across the whole set.

    Each item is a number or a mapping carrying an amount plus an optional
    ``currency``. Two different currency codes (or one differing from
    ``expected_currency``) is a clean ``ValueError`` rather than a silent,
    meaningless mixed-currency total. An empty set is a well-defined zero.

    Returns:
        A tuple of ``(total, resolved_currency)`` where the total is exact
        Decimal and the currency may be ``None`` if no item stated one.
    """
    currency = _normalise_currency(expected_currency)
    total = Decimal("0")
    for idx, entry in enumerate(amounts):
        raw = _read_amount(entry, index=idx)
        amount = _non_negative(
            _to_decimal(raw, field_name=f"{label}[{idx}]"),
            field_name=f"{label}[{idx}]",
        )
        item_ccy = _read_currency(entry)
        if item_ccy is not None:
            if currency is None:
                currency = item_ccy
            elif item_ccy != currency:
                raise ValueError(
                    f"cannot sum across currencies: {currency} and {item_ccy} "
                    f"at {label}[{idx}] (convert to one currency first)"
                )
        total += amount
    return _guard_finite(total, field_name=label), currency


# ── Pure Decimal appraisal helpers ────────────────────────────────────────────


def gross_development_value(
    unit_values: Iterable[Any],
    *,
    expected_currency: str | None = None,
) -> Decimal:
    """Return the gross development value: the sum of every unit's sale value.

    The GDV is ``sum(unit sale values)`` in a single currency. Each item may be
    a plain number or a mapping carrying an amount (``value`` / ``amount`` /
    ``sale_price`` / ``price`` / ``unit_value``) plus an optional ``currency``.
    An empty set is a well-defined ``Decimal("0")`` (a scheme with no units
    priced yet), never an error.

    Args:
        unit_values: Iterable of unit sale values (numbers or mappings).
        expected_currency: When given, every item with a stated currency must
            match it; otherwise the currency is inferred and must be consistent.

    Raises:
        ValueError: On a missing / negative / non-numeric amount, or on items
            that mix currency codes.
    """
    total, _currency = _sum_one_currency(unit_values, expected_currency=expected_currency, label="unit_values")
    return total


def total_development_cost(
    cost_components: Iterable[Any] | Mapping[str, Any],
    *,
    expected_currency: str | None = None,
) -> Decimal:
    """Return the total development cost: the sum of all cost components.

    "Total development cost" is every cost of delivering the scheme except the
    land itself (construction, fees, contingency, finance, sales costs). Pass
    either a mapping of named cost lines (``{"construction": 6_000_000, ...}``)
    or an iterable of numbers / mappings. An empty set is a well-defined zero.

    Raises:
        ValueError: On a missing / negative / non-numeric amount, or on items
            that mix currency codes.
    """
    items: Iterable[Any] = cost_components.values() if isinstance(cost_components, Mapping) else cost_components
    total, _currency = _sum_one_currency(items, expected_currency=expected_currency, label="cost_components")
    return total


def residual_land_value(
    gross_development_value_amount: Any,
    total_development_cost_amount: Any,
    developer_profit_amount: Any = Decimal("0"),
) -> Decimal:
    """Return the residual land value: GDV minus total cost minus profit.

    ``residual = GDV - total development cost - developer profit``. The result
    may be negative on purpose: a negative residual means the land cannot be
    afforded at the target profit, which is a real, meaningful outcome (an
    unviable scheme), not an error. The three inputs are each non-negative.

    Raises:
        ValueError: On a missing / negative / non-numeric / non-finite input.
    """
    gdv = _non_negative(
        _to_decimal(gross_development_value_amount, field_name="gross_development_value"),
        field_name="gross_development_value",
    )
    cost = _non_negative(
        _to_decimal(total_development_cost_amount, field_name="total_development_cost"),
        field_name="total_development_cost",
    )
    profit = _non_negative(
        _to_decimal(developer_profit_amount, field_name="developer_profit"),
        field_name="developer_profit",
    )
    return _guard_finite(gdv - cost - profit, field_name="residual land value")


def profit_on_cost(developer_profit_amount: Any, total_development_cost_amount: Any) -> Decimal:
    """Return profit on cost as a ratio: ``developer profit / total cost``.

    The result is a ratio (``0.20`` means 20 percent), left unquantized so the
    caller controls display rounding for their own locale. A total development
    cost of zero is guarded and returns ``Decimal("0")`` rather than dividing
    by zero, so a not-yet-costed scheme never raises.

    Raises:
        ValueError: On a missing / negative / non-numeric / non-finite input.
    """
    profit = _non_negative(
        _to_decimal(developer_profit_amount, field_name="developer_profit"),
        field_name="developer_profit",
    )
    cost = _non_negative(
        _to_decimal(total_development_cost_amount, field_name="total_development_cost"),
        field_name="total_development_cost",
    )
    if cost == 0:
        return Decimal("0")
    return _guard_finite(profit / cost, field_name="profit on cost")


def profit_on_gdv(developer_profit_amount: Any, gross_development_value_amount: Any) -> Decimal:
    """Return profit on GDV as a ratio: ``developer profit / GDV``.

    The result is a ratio (``0.20`` means 20 percent), left unquantized. A GDV
    of zero is guarded and returns ``Decimal("0")`` rather than dividing by
    zero, so a scheme with no sales value yet never raises.

    Raises:
        ValueError: On a missing / negative / non-numeric / non-finite input.
    """
    profit = _non_negative(
        _to_decimal(developer_profit_amount, field_name="developer_profit"),
        field_name="developer_profit",
    )
    gdv = _non_negative(
        _to_decimal(gross_development_value_amount, field_name="gross_development_value"),
        field_name="gross_development_value",
    )
    if gdv == 0:
        return Decimal("0")
    return _guard_finite(profit / gdv, field_name="profit on gdv")


def normalise_iso_date(value: str | date | None) -> str:
    """Return an ISO 8601 date string (YYYY-MM-DD) for a date or ISO string.

    Dates in this module are locale-free ISO 8601 text. A ``date`` is formatted
    with ``isoformat``; a string is validated by parsing it back, so a bad date
    is a clean ``ValueError`` rather than a value that breaks a downstream sort
    or export.

    Raises:
        ValueError: If the value is missing or is not a valid ISO 8601 date.
    """
    if value is None:
        raise ValueError("date is required (missing value)")
    if isinstance(value, date):
        return value.isoformat()
    text = str(value).strip()
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError as exc:
        raise ValueError(f"date '{value}' is not a valid ISO 8601 date (YYYY-MM-DD)") from exc


def build_feasibility_summary(
    unit_values: Iterable[Any],
    cost_components: Iterable[Any] | Mapping[str, Any],
    *,
    developer_profit_target_ratio: Any = DEFAULT_PROFIT_TARGET_RATIO,
    expected_currency: str | None = None,
) -> dict[str, Any]:
    """Build a fully explained, single-currency feasibility summary.

    This is the clear, worldwide-safe pipeline: add up the unit sale values
    into the GDV, add up the cost components into the total development cost,
    take the target developer profit as a ratio of the GDV, then derive the
    residual land value and the two profit ratios. Every component is exposed
    so a user, an auditor, or a validation rule can check the arithmetic.

    The developer profit target is an explicit ratio parameter (``0.20`` for 20
    percent); its documented worldwide default is ``0`` (no profit line taken).

    Returns:
        A dict with the resolved ``currency`` (may be ``None`` if no item stated
        one), the ``gross_development_value``, ``total_development_cost``,
        ``developer_profit_target_ratio``, ``developer_profit``,
        ``residual_land_value``, ``profit_on_cost``, ``profit_on_gdv`` (both
        ratios), and a ``viable`` flag (residual land value >= 0). All money is
        exact Decimal.

    Raises:
        ValueError: On any invalid amount, a mixed-currency set, or a negative
            profit target.
    """
    gdv, gdv_ccy = _sum_one_currency(unit_values, expected_currency=expected_currency, label="unit_values")
    items: Iterable[Any] = cost_components.values() if isinstance(cost_components, Mapping) else cost_components
    cost, cost_ccy = _sum_one_currency(items, expected_currency=expected_currency, label="cost_components")

    if gdv_ccy is not None and cost_ccy is not None and gdv_ccy != cost_ccy:
        raise ValueError(
            f"cannot appraise across currencies: unit values in {gdv_ccy} and costs "
            f"in {cost_ccy} (convert to one currency first)"
        )
    currency = gdv_ccy or cost_ccy or _normalise_currency(expected_currency)

    profit_ratio = _non_negative(
        _to_decimal(developer_profit_target_ratio, field_name="developer_profit_target_ratio"),
        field_name="developer_profit_target_ratio",
    )
    developer_profit = _guard_finite(gdv * profit_ratio, field_name="developer profit")
    residual = residual_land_value(gdv, cost, developer_profit)

    return {
        "currency": currency,
        "gross_development_value": gdv,
        "total_development_cost": cost,
        "developer_profit_target_ratio": profit_ratio,
        "developer_profit": developer_profit,
        "residual_land_value": residual,
        "profit_on_cost": profit_on_cost(developer_profit, cost),
        "profit_on_gdv": profit_on_gdv(developer_profit, gdv),
        "viable": residual >= 0,
    }
