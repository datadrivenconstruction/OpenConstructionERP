# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""MoneyValue utility for multi-currency monetary values.

Core utility used by all financial modules. Stores amounts as strings
to avoid floating-point precision issues and ensure SQLite compatibility.
All arithmetic uses ``decimal.Decimal`` with ``ROUND_HALF_UP``.

Usage::

    from app.core.money import MoneyValue, parse_money, format_money, money_columns

    mv = MoneyValue(amount="1500.00", currency_code="EUR")
    assert mv.to_decimal() == Decimal("1500.00")

    converted = mv.convert("USD", "1.08")
    assert converted.currency_code == "USD"

    total = mv + MoneyValue(amount="500.00")
    assert total.to_decimal() == Decimal("2000.00")
"""

# Copyright 2024-2026 OpenEstimate Contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from pydantic import BaseModel, field_validator, model_validator
from sqlalchemy import String
from sqlalchemy.orm import mapped_column

__all__ = [
    "CURRENCIES",
    "MoneyValue",
    "WrittenAmount",
    "format_money",
    "minor_units",
    "money_columns",
    "money_quantum",
    "parse_money",
    "read_written_amount",
]

# ── Currency registry ─────────────────────────────────────────────────────────
#
# The table, the per-currency decimal count and the rounding quantum moved to
# ``app.core.currency_registry`` so that the standard-library-only validator
# modules can reach them; this module imports them straight back, so every
# caller of ``from app.core.money import CURRENCIES, minor_units, money_quantum``
# is unchanged. The explanation of which layer governs how many decimals -- value
# here, document in the einvoice rules, screen in the frontend -- travelled with
# them and sits above ``minor_units`` in that module.

from app.core.currency_registry import CURRENCIES, minor_units, money_quantum

_CURRENCY_CODE_RE = re.compile(r"^[A-Z]{3}$")


# ── MoneyValue model ──────────────────────────────────────────────────────────


class MoneyValue(BaseModel):
    """Immutable representation of a monetary value with multi-currency support.

    All amounts are stored as strings to avoid floating-point precision loss
    and to maintain SQLite compatibility. Arithmetic is performed via
    ``decimal.Decimal`` with ``ROUND_HALF_UP`` rounding.

    Attributes:
        amount: Original amount as a decimal string.
        currency_code: ISO 4217 currency code (3 uppercase letters).
        amount_base: Amount converted to the project's base currency.
        base_currency_code: The project's base currency code.
        exchange_rate: Exchange rate applied for the conversion.
    """

    amount: str = "0"
    currency_code: str = "EUR"
    amount_base: str = "0"
    base_currency_code: str = "EUR"
    exchange_rate: str = "1"

    model_config = {"frozen": True}

    # ── Validators ────────────────────────────────────────────────────────

    @field_validator("currency_code", "base_currency_code")
    @classmethod
    def _validate_currency_code(cls, v: str) -> str:
        """Ensure currency code is exactly 3 uppercase ASCII letters."""
        if not _CURRENCY_CODE_RE.match(v):
            raise ValueError(f"Currency code must be 3 uppercase letters, got {v!r}")
        return v

    @field_validator("amount", "amount_base", "exchange_rate")
    @classmethod
    def _validate_decimal_string(cls, v: str) -> str:
        """Ensure the value is parseable as a Decimal."""
        try:
            Decimal(v)
        except (InvalidOperation, ValueError, TypeError) as exc:
            raise ValueError(f"Cannot parse {v!r} as Decimal") from exc
        return v

    @model_validator(mode="after")
    def _normalise_amounts(self) -> MoneyValue:
        """Strip trailing zeros for consistent representation.

        Uses ``object.__setattr__`` because the model is frozen.
        """
        object.__setattr__(self, "amount", _normalise(self.amount))
        object.__setattr__(self, "amount_base", _normalise(self.amount_base))
        object.__setattr__(self, "exchange_rate", _normalise(self.exchange_rate))
        return self

    # ── Conversions ───────────────────────────────────────────────────────

    def to_decimal(self) -> Decimal:
        """Return ``amount`` as a ``Decimal``."""
        return Decimal(self.amount)

    def to_base_decimal(self) -> Decimal:
        """Return ``amount_base`` as a ``Decimal``."""
        return Decimal(self.amount_base)

    # ── Currency conversion ───────────────────────────────────────────────

    def convert(self, target_currency: str, rate: str | Decimal) -> MoneyValue:
        """Create a new ``MoneyValue`` converted to *target_currency*.

        Args:
            target_currency: ISO 4217 code of the target currency.
            rate: Exchange rate from the current currency to *target_currency*.

        Returns:
            A new ``MoneyValue`` with the converted amount.  The original
            amount is preserved as the base amount.

        Audit I1 - quantises to the target currency's own minor unit via
        :func:`money_quantum` instead of the previous hardcoded
        ``Decimal("0.01")``. The old behaviour silently introduced a
        fractional fil/yen/won on every JPY/KWD conversion (e.g.
        100 USD * 142.5 = 14250.00 JPY, but the JPY value should be an
        integer). Falls back to 2 decimals when the target currency
        isn't in our registry.
        """
        rate_dec = Decimal(str(rate))
        quantum = money_quantum(target_currency)
        converted = (self.to_decimal() * rate_dec).quantize(quantum, rounding=ROUND_HALF_UP)
        return MoneyValue(
            amount=str(converted),
            currency_code=target_currency,
            amount_base=self.amount,
            base_currency_code=self.currency_code,
            exchange_rate=str(rate_dec),
        )

    # ── Arithmetic ────────────────────────────────────────────────────────

    def __add__(self, other: object) -> MoneyValue:
        """Add two ``MoneyValue`` objects with the same currency."""
        if not isinstance(other, MoneyValue):
            return NotImplemented
        _assert_same_currency(self, other, "+")
        result = self.to_decimal() + other.to_decimal()
        result_base = self.to_base_decimal() + other.to_base_decimal()
        return MoneyValue(
            amount=str(result),
            currency_code=self.currency_code,
            amount_base=str(result_base),
            base_currency_code=self.base_currency_code,
            exchange_rate=self.exchange_rate,
        )

    def __sub__(self, other: object) -> MoneyValue:
        """Subtract two ``MoneyValue`` objects with the same currency."""
        if not isinstance(other, MoneyValue):
            return NotImplemented
        _assert_same_currency(self, other, "-")
        result = self.to_decimal() - other.to_decimal()
        result_base = self.to_base_decimal() - other.to_base_decimal()
        return MoneyValue(
            amount=str(result),
            currency_code=self.currency_code,
            amount_base=str(result_base),
            base_currency_code=self.base_currency_code,
            exchange_rate=self.exchange_rate,
        )

    # ── Helpers ───────────────────────────────────────────────────────────

    def is_zero(self) -> bool:
        """Return ``True`` if the amount is zero."""
        return self.to_decimal() == Decimal("0")

    def negate(self) -> MoneyValue:
        """Return a new ``MoneyValue`` with the sign of the amount flipped."""
        return MoneyValue(
            amount=str(-self.to_decimal()),
            currency_code=self.currency_code,
            amount_base=str(-self.to_base_decimal()),
            base_currency_code=self.base_currency_code,
            exchange_rate=self.exchange_rate,
        )

    def __repr__(self) -> str:  # noqa: D105
        return f"MoneyValue({self.amount} {self.currency_code})"


# ── Private helpers ───────────────────────────────────────────────────────────


def _normalise(value: str) -> str:
    """Normalise a decimal string: remove trailing zeros, keep ``0``."""
    d = Decimal(value).normalize()
    # Decimal("0E+2").normalize() == Decimal("0E+2"); ensure plain "0".
    if d == 0:
        return "0"
    # Ensure no scientific notation (e.g. 1E+3 → 1000).
    return format(d, "f")


def _assert_same_currency(a: MoneyValue, b: MoneyValue, op: str) -> None:
    """Raise ``ValueError`` if two MoneyValues have different currencies."""
    if a.currency_code != b.currency_code:
        raise ValueError(
            f"Cannot {op} MoneyValue with currency {a.currency_code!r} and {b.currency_code!r}; convert first"
        )


# ── SQLAlchemy column helper ──────────────────────────────────────────────────


def money_columns(prefix: str = "amount") -> dict[str, Any]:
    """Return a dict of SQLAlchemy ``mapped_column`` definitions for money fields.

    Embed these into any ORM model via ``__table_args__`` or by unpacking
    into class attributes.  All columns use ``String`` types for SQLite
    compatibility.

    Args:
        prefix: Column name prefix (default ``"amount"``).

    Returns:
        A dict mapping attribute names to ``mapped_column`` instances::

            {
                "{prefix}":               String(50), default "0",
                "{prefix}_currency":      String(10), default "EUR",
                "{prefix}_base":          String(50), default "0",
                "{prefix}_base_currency": String(10), default "EUR",
                "{prefix}_exchange_rate": String(50), default "1",
            }

    Example::

        class LineItem(Base):
            __tablename__ = "oe_line_items"
            id = mapped_column(GUID(), primary_key=True)
            # Unpack money columns
            cost = money_columns("cost")  # yields cost, cost_currency, ...
    """
    return {
        f"{prefix}": mapped_column(String(50), default="0", server_default="0"),
        f"{prefix}_currency": mapped_column(String(10), default="EUR", server_default="EUR"),
        f"{prefix}_base": mapped_column(String(50), default="0", server_default="0"),
        f"{prefix}_base_currency": mapped_column(String(10), default="EUR", server_default="EUR"),
        f"{prefix}_exchange_rate": mapped_column(String(50), default="1", server_default="1"),
    }


# ── Parsing and formatting ────────────────────────────────────────────────────


def parse_money(value: str | int | float | Decimal) -> str:
    """Safely convert any numeric input to a plain decimal string.

    Handles ``str``, ``int``, ``float``, and ``Decimal``.  The result
    never contains scientific notation or thousands separators.

    Args:
        value: The numeric value to convert.

    Returns:
        A normalised decimal string suitable for storing in a money field.

    Raises:
        ValueError: If the value cannot be parsed as a decimal number.
    """
    try:
        if isinstance(value, float):
            # Convert via string first to preserve the user-visible digits,
            # then let Decimal normalise.
            d = Decimal(str(value))
        elif isinstance(value, Decimal):
            d = value
        else:
            d = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError(f"Cannot parse {value!r} as a monetary value") from exc

    return _normalise(str(d))


def format_money(
    amount: str,
    currency_code: str = "EUR",
    locale: str = "en",
) -> str:
    """Format a monetary amount for display.

    Uses ``Decimal`` internally - never ``float`` - to preserve precision.
    Applies thousands separators and the currency symbol where known.

    Args:
        amount: Decimal string amount (e.g. ``"1234.56"``).
        currency_code: ISO 4217 currency code.
        locale: Display locale hint (``"en"`` or ``"de"``).

    Returns:
        A human-readable string such as ``"€ 1,234.56"`` (en) or
        ``"1.234,56 €"`` (de).
    """
    d = Decimal(amount)
    code = (currency_code or "").strip().upper()
    info = CURRENCIES.get(code)
    decimals = minor_units(code)
    symbol = info["symbol"] if info else code

    # Quantise to the expected number of decimal places.
    quantised = d.quantize(money_quantum(code), rounding=ROUND_HALF_UP)

    if locale == "de":
        formatted = _format_de(quantised, decimals)
        return f"{formatted} {symbol}"

    formatted = _format_en(quantised, decimals)
    return f"{symbol} {formatted}"


def _format_en(d: Decimal, decimals: int) -> str:
    """Format a Decimal in English style: ``1,234.56``."""
    sign = "-" if d < 0 else ""
    d = abs(d)
    int_part = int(d)
    frac_part = d - int_part

    int_str = f"{int_part:,}"

    if decimals == 0:
        return f"{sign}{int_str}"

    frac_str = str(frac_part.quantize(Decimal(10) ** -decimals, rounding=ROUND_HALF_UP))
    # frac_str is like "0.56"; take the part after the dot.
    frac_digits = frac_str.split(".")[1] if "." in frac_str else "0" * decimals
    return f"{sign}{int_str}.{frac_digits}"


def _format_de(d: Decimal, decimals: int) -> str:
    """Format a Decimal in German style: ``1.234,56``."""
    en = _format_en(d, decimals)
    # Swap: comma → TEMP, dot → comma, TEMP → dot.
    return en.replace(",", "\x00").replace(".", ",").replace("\x00", ".")


# ── Reading an amount a person typed as text ──────────────────────────────────

#: Currency symbols that name one currency. ``$`` and ``¥`` name several, so
#: they are stripped without deciding the currency. Longest first, so ``R$``
#: is not read as ``$``.
_WRITTEN_SYMBOLS: tuple[tuple[str, str | None], ...] = (
    ("R$", "BRL"),
    ("€", "EUR"),
    ("£", "GBP"),
    ("₽", "RUB"),
    ("₹", "INR"),
    ("₺", "TRY"),
    ("$", None),
    ("¥", None),
)

#: Characters people put between digit groups: space, no-break space, narrow
#: no-break space, thin space and the Swiss apostrophes.
_WRITTEN_GROUP_SPACES = "    '’"

_WRITTEN_LEADING_CODE_RE = re.compile(r"^([A-Za-z]{3})(?![A-Za-z])\s*")
_WRITTEN_TRAILING_CODE_RE = re.compile(r"(?<![A-Za-z])\s*([A-Za-z]{3})$")
_WRITTEN_BODY_RE = re.compile(r"\d+(?:[.,]\d+)*")
_WRITTEN_SPACED_RE = re.compile(r"\d{1,3}(?: \d{3})+(?:[.,]\d+)?")


@dataclass(frozen=True)
class WrittenAmount:
    """What :func:`read_written_amount` made of a piece of text.

    ``status`` is one of:

    * ``"read"``: ``amount`` holds the one amount the text can mean.
    * ``"ambiguous"``: the text is a number but could mean two amounts, for
      instance ``"12.500"`` in a currency with three decimals. ``amount`` is
      ``None``; a person has to say which.
    * ``"unreadable"``: there are digits, but not one clear amount
      (``"approx. 5000"``, ``"5000-6000"``, ``"12.34.5"``).
    * ``"blank"``: no digit at all, so no amount was written.

    ``currency`` is the ISO code written with the amount, as a code or as a
    symbol that names one currency. It is never the hint passed in.
    """

    amount: Decimal | None
    currency: str | None
    status: str


def _valid_groups(parts: list[str], separator: str) -> bool:
    """Whether ``parts`` (an integer split on ``separator``) are digit groups.

    A lead of one to three digits followed by groups of three, or, for a
    comma, the Indian layout: a lead of one or two digits, groups of two and a
    final group of three.
    """
    if len(parts) < 2:
        return False
    lead, rest = parts[0], parts[1:]
    if 1 <= len(lead) <= 3 and all(len(p) == 3 for p in rest):
        return True
    return separator == "," and 1 <= len(lead) <= 2 and len(rest[-1]) == 3 and all(len(p) == 2 for p in rest[:-1])


def read_written_amount(raw: object, *, currency_hint: str | None = None) -> WrittenAmount:
    """Read an amount a person typed as free text, in the convention they used.

    Accepts an optional ISO code before or after the number (``"BRL 12.000,00"``,
    ``"12000 EUR"``), a currency symbol, digit groups of dots, commas, spaces
    or apostrophes, and a leading minus or accounting brackets.

    The decimal separator is decided by the text, not by a locale guess:

    * When both ``.`` and ``,`` appear, the last one is the decimal point and
      the other must form proper digit groups.
    * When one of them appears more than once, it is the group separator.
    * When one of them appears once, it is the decimal point unless exactly
      three digits follow and the part before could lead a group. Then it is a
      group separator in a currency with fewer than three decimals
      (``"12.000"`` euro is twelve thousand; nobody writes euro to the tenth of
      a cent) and ``"ambiguous"`` in one with three (``"12.500"`` dinar).

    The currency deciding that is the one written with the amount, else
    ``currency_hint`` (typically the project currency), else the two-decimal
    default.

    Never raises. See :class:`WrittenAmount` for what comes back.
    """
    if isinstance(raw, Decimal | int) and not isinstance(raw, bool):
        value = Decimal(raw)
        if value.is_finite():
            return WrittenAmount(amount=value, currency=None, status="read")
        return WrittenAmount(amount=None, currency=None, status="unreadable")

    text = str(raw if raw is not None else "").strip()
    if not any(ch.isdigit() for ch in text):
        return WrittenAmount(amount=None, currency=None, status="blank")

    codes: list[str] = []
    for pattern in (_WRITTEN_LEADING_CODE_RE, _WRITTEN_TRAILING_CODE_RE):
        match = pattern.search(text)
        if match is not None:
            codes.append(match.group(1).upper())
            text = (text[: match.start()] + text[match.end() :]).strip()
    for symbol, code in _WRITTEN_SYMBOLS:
        if text.startswith(symbol):
            text = text[len(symbol) :].strip()
        elif text.endswith(symbol):
            text = text[: -len(symbol)].strip()
        else:
            continue
        if code is not None:
            codes.append(code)
        break
    if len(set(codes)) > 1 or any(code not in CURRENCIES for code in codes):
        return WrittenAmount(amount=None, currency=None, status="unreadable")
    currency = codes[0] if codes else None
    unreadable = WrittenAmount(amount=None, currency=currency, status="unreadable")

    negative = False
    if text.startswith("(") and text.endswith(")"):
        negative, text = True, text[1:-1].strip()
    if text[:1] in ("+", "-"):
        negative, text = text[0] == "-", text[1:].strip()

    body = "".join(" " if ch in _WRITTEN_GROUP_SPACES else ch for ch in text)
    if " " in body:
        if not _WRITTEN_SPACED_RE.fullmatch(body):
            return unreadable
        body = body.replace(" ", "")
    if not _WRITTEN_BODY_RE.fullmatch(body):
        return unreadable

    separators = [ch for ch in body if ch in ".,"]
    if not separators:
        digits = body
    elif len(set(separators)) == 2:
        decimal_sep = separators[-1]
        group_sep = "," if decimal_sep == "." else "."
        whole, fraction = body.rsplit(decimal_sep, 1)
        if separators.count(decimal_sep) != 1 or not _valid_groups(whole.split(group_sep), group_sep):
            return unreadable
        digits = f"{whole.replace(group_sep, '')}.{fraction}"
    elif len(separators) > 1:
        if not _valid_groups(body.split(separators[0]), separators[0]):
            return unreadable
        digits = body.replace(separators[0], "")
    else:
        whole, fraction = body.split(separators[0])
        could_be_group = len(fraction) == 3 and len(whole) <= 3 and whole.strip("0") != ""
        if not could_be_group:
            digits = f"{whole}.{fraction}"
        elif minor_units(currency or currency_hint) >= 3:
            return WrittenAmount(amount=None, currency=currency, status="ambiguous")
        else:
            digits = whole + fraction

    try:
        value = Decimal(digits)
    except InvalidOperation:
        return unreadable
    return WrittenAmount(amount=-value if negative else value, currency=currency, status="read")
