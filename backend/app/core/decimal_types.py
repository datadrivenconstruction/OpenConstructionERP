"""Bounded, finite Decimal types for request schemas.

A bare ``Decimal`` field accepts ``NaN``, ``Infinity`` and ``1e400``, and a value wider than
its ``NUMERIC(p, s)`` column fails at flush with a 500. ``finite_decimal(p, s)`` rejects
all of these at validation time (422). Extra fractional digits are not an error: the value is
rounded half-up to the column scale on input, so clients that send 1.125 for a scale-2 column
are accepted and the stored value is what the response shows.

Usage::

    from app.core.decimal_types import Decimal18_2, finite_decimal

    class Create(BaseModel):
        amount: Decimal18_2 = Field(default=Decimal("0"), ge=0)
        rate: finite_decimal(18, 4, non_negative=True) | None = None
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, localcontext
from functools import cache
from typing import Annotated

from pydantic import AfterValidator, Field

__all__ = [
    "FiniteDecimal",
    "finite_decimal",
    "Decimal4_2",
    "Decimal4_3",
    "Decimal5_1",
    "Decimal5_2",
    "Decimal5_4",
    "Decimal6_2",
    "Decimal6_3",
    "Decimal6_4",
    "Decimal7_2",
    "Decimal7_3",
    "Decimal7_4",
    "Decimal8_2",
    "Decimal8_3",
    "Decimal8_4",
    "Decimal9_2",
    "Decimal9_4",
    "Decimal9_6",
    "Decimal10_1",
    "Decimal10_2",
    "Decimal10_4",
    "Decimal10_7",
    "Decimal12_1",
    "Decimal12_2",
    "Decimal12_3",
    "Decimal12_4",
    "Decimal12_6",
    "Decimal14_2",
    "Decimal14_3",
    "Decimal14_4",
    "Decimal15_2",
    "Decimal15_3",
    "Decimal16_3",
    "Decimal18_0",
    "Decimal18_2",
    "Decimal18_3",
    "Decimal18_4",
    "Decimal18_6",
    "Decimal18_8",
    "Decimal20_2",
    "Decimal20_4",
    "Decimal20_6",
    "Decimal20_10",
]


@cache
def finite_decimal(
    max_digits: int = 28,
    decimal_places: int = 6,
    *,
    non_negative: bool = False,
    positive: bool = False,
    quantize: bool = True,
) -> type[Decimal]:
    """Build a Decimal type that is finite and fits ``NUMERIC(max_digits, decimal_places)``.

    Args:
        max_digits: Total digits of the target column (precision).
        decimal_places: Fractional digits of the target column (scale).
        non_negative: Also require ``>= 0``.
        positive: Also require ``> 0`` (wins over ``non_negative``).
        quantize: Round half-up to ``decimal_places`` (off for the column-less generic type).

    Returns:
        An ``Annotated[Decimal, ...]`` usable as a field annotation, alone or in a union.
    """
    if max_digits <= 0 or not 0 <= decimal_places <= max_digits:
        raise ValueError("need 0 <= decimal_places <= max_digits and max_digits > 0")
    limit = Decimal(10) ** (max_digits - decimal_places)
    step = Decimal(1).scaleb(-decimal_places)

    def _check(value: Decimal) -> Decimal:
        if not -limit < value < limit:
            raise ValueError(f"must be below {limit} in absolute value")
        if quantize and -value.as_tuple().exponent > decimal_places:
            with localcontext() as ctx:
                ctx.prec = max_digits + 8
                value = value.quantize(step, rounding=ROUND_HALF_UP)
            if not -limit < value < limit:
                raise ValueError(f"must be below {limit} in absolute value")
        if positive and value <= 0:
            raise ValueError("must be greater than 0")
        if non_negative and not positive and value < 0:
            raise ValueError("must be greater than or equal to 0")
        return value

    # Range is checked in an after-validator, not via gt/lt: a field-level Field(gt=...)
    # with the same key would silently replace the alias's own bound.
    return Annotated[Decimal, Field(allow_inf_nan=False), AfterValidator(_check)]  # type: ignore[return-value]


# Generic bound for fields with no matching column (|v| < 1e22).
FiniteDecimal = finite_decimal(28, 6, quantize=False)

# One alias per NUMERIC(p, s) shape used by module models.
Decimal4_2 = finite_decimal(4, 2)
Decimal4_3 = finite_decimal(4, 3)
Decimal5_1 = finite_decimal(5, 1)
Decimal5_2 = finite_decimal(5, 2)
Decimal5_4 = finite_decimal(5, 4)
Decimal6_2 = finite_decimal(6, 2)
Decimal6_3 = finite_decimal(6, 3)
Decimal6_4 = finite_decimal(6, 4)
Decimal7_2 = finite_decimal(7, 2)
Decimal7_3 = finite_decimal(7, 3)
Decimal7_4 = finite_decimal(7, 4)
Decimal8_2 = finite_decimal(8, 2)
Decimal8_3 = finite_decimal(8, 3)
Decimal8_4 = finite_decimal(8, 4)
Decimal9_2 = finite_decimal(9, 2)
Decimal9_4 = finite_decimal(9, 4)
Decimal9_6 = finite_decimal(9, 6)
Decimal10_1 = finite_decimal(10, 1)
Decimal10_2 = finite_decimal(10, 2)
Decimal10_4 = finite_decimal(10, 4)
Decimal10_7 = finite_decimal(10, 7)
Decimal12_1 = finite_decimal(12, 1)
Decimal12_2 = finite_decimal(12, 2)
Decimal12_3 = finite_decimal(12, 3)
Decimal12_4 = finite_decimal(12, 4)
Decimal12_6 = finite_decimal(12, 6)
Decimal14_2 = finite_decimal(14, 2)
Decimal14_3 = finite_decimal(14, 3)
Decimal14_4 = finite_decimal(14, 4)
Decimal15_2 = finite_decimal(15, 2)
Decimal15_3 = finite_decimal(15, 3)
Decimal16_3 = finite_decimal(16, 3)
Decimal18_0 = finite_decimal(18, 0)
Decimal18_2 = finite_decimal(18, 2)
Decimal18_3 = finite_decimal(18, 3)
Decimal18_4 = finite_decimal(18, 4)
Decimal18_6 = finite_decimal(18, 6)
Decimal18_8 = finite_decimal(18, 8)
Decimal20_2 = finite_decimal(20, 2)
Decimal20_4 = finite_decimal(20, 4)
Decimal20_6 = finite_decimal(20, 6)
Decimal20_10 = finite_decimal(20, 10)
