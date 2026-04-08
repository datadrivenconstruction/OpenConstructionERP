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
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from pydantic import BaseModel, field_validator, model_validator
from sqlalchemy import String
from sqlalchemy.orm import mapped_column

__all__ = [
    "CURRENCIES",
    "MoneyValue",
    "format_money",
    "money_columns",
    "parse_money",
]

# ── Currency registry ─────────────────────────────────────────────────────────

CURRENCIES: dict[str, dict[str, Any]] = {
    # Europe
    "EUR": {"symbol": "€", "name": "Euro", "decimals": 2},
    "GBP": {"symbol": "£", "name": "British Pound", "decimals": 2},
    "CHF": {"symbol": "CHF", "name": "Swiss Franc", "decimals": 2},
    "SEK": {"symbol": "kr", "name": "Swedish Krona", "decimals": 2},
    "NOK": {"symbol": "kr", "name": "Norwegian Krone", "decimals": 2},
    "DKK": {"symbol": "kr", "name": "Danish Krone", "decimals": 2},
    "PLN": {"symbol": "zł", "name": "Polish Zloty", "decimals": 2},
    "CZK": {"symbol": "Kč", "name": "Czech Koruna", "decimals": 2},
    "HUF": {"symbol": "Ft", "name": "Hungarian Forint", "decimals": 0},
    "RON": {"symbol": "lei", "name": "Romanian Leu", "decimals": 2},
    "BGN": {"symbol": "лв", "name": "Bulgarian Lev", "decimals": 2},
    "HRK": {"symbol": "kn", "name": "Croatian Kuna", "decimals": 2},
    "TRY": {"symbol": "₺", "name": "Turkish Lira", "decimals": 2},
    "RUB": {"symbol": "₽", "name": "Russian Ruble", "decimals": 2},
    "UAH": {"symbol": "₴", "name": "Ukrainian Hryvnia", "decimals": 2},
    # Americas
    "USD": {"symbol": "$", "name": "US Dollar", "decimals": 2},
    "CAD": {"symbol": "C$", "name": "Canadian Dollar", "decimals": 2},
    "MXN": {"symbol": "MX$", "name": "Mexican Peso", "decimals": 2},
    "BRL": {"symbol": "R$", "name": "Brazilian Real", "decimals": 2},
    # Middle East & Africa
    "AED": {"symbol": "د.إ", "name": "UAE Dirham", "decimals": 2},
    "SAR": {"symbol": "﷼", "name": "Saudi Riyal", "decimals": 2},
    "QAR": {"symbol": "﷼", "name": "Qatari Riyal", "decimals": 2},
    "ZAR": {"symbol": "R", "name": "South African Rand", "decimals": 2},
    "EGP": {"symbol": "E£", "name": "Egyptian Pound", "decimals": 2},
    # Asia-Pacific
    "JPY": {"symbol": "¥", "name": "Japanese Yen", "decimals": 0},
    "CNY": {"symbol": "¥", "name": "Chinese Yuan", "decimals": 2},
    "KRW": {"symbol": "₩", "name": "South Korean Won", "decimals": 0},
    "INR": {"symbol": "₹", "name": "Indian Rupee", "decimals": 2},
    "AUD": {"symbol": "A$", "name": "Australian Dollar", "decimals": 2},
    "NZD": {"symbol": "NZ$", "name": "New Zealand Dollar", "decimals": 2},
    "SGD": {"symbol": "S$", "name": "Singapore Dollar", "decimals": 2},
    "HKD": {"symbol": "HK$", "name": "Hong Kong Dollar", "decimals": 2},
    "MYR": {"symbol": "RM", "name": "Malaysian Ringgit", "decimals": 2},
    "THB": {"symbol": "฿", "name": "Thai Baht", "decimals": 2},
    "IDR": {"symbol": "Rp", "name": "Indonesian Rupiah", "decimals": 0},
    "PHP": {"symbol": "₱", "name": "Philippine Peso", "decimals": 2},
}

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
            raise ValueError(
                f"Currency code must be 3 uppercase letters, got {v!r}"
            )
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
        """
        rate_dec = Decimal(str(rate))
        converted = (self.to_decimal() * rate_dec).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
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
            f"Cannot {op} MoneyValue with currency {a.currency_code!r} "
            f"and {b.currency_code!r}; convert first"
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
        f"{prefix}_currency": mapped_column(
            String(10), default="EUR", server_default="EUR"
        ),
        f"{prefix}_base": mapped_column(String(50), default="0", server_default="0"),
        f"{prefix}_base_currency": mapped_column(
            String(10), default="EUR", server_default="EUR"
        ),
        f"{prefix}_exchange_rate": mapped_column(
            String(50), default="1", server_default="1"
        ),
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

    Uses ``Decimal`` internally — never ``float`` — to preserve precision.
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
    info = CURRENCIES.get(currency_code)
    decimals = info["decimals"] if info else 2
    symbol = info["symbol"] if info else currency_code

    # Quantise to the expected number of decimal places.
    quantised = d.quantize(Decimal(10) ** -decimals, rounding=ROUND_HALF_UP)

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
