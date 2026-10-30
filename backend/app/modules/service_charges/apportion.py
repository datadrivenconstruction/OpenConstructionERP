# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Pure apportionment and reconciliation arithmetic, Decimal only.

Every split uses the largest remainder method at the cent, so the parts always add
up to the whole exactly and no cent is created or lost.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import ROUND_DOWN, Decimal
from typing import Any

CENT = Decimal("0.01")
ZERO = Decimal("0")

#: Expected total of the shares per method; ``None`` means any positive total (area) or none (equal).
EXPECTED_TOTAL: dict[str, Decimal | None] = {
    "permille": Decimal("1000"),
    "custom": Decimal("100"),
    "area": None,
    "equal": None,
}

PERIODS_PER_YEAR: dict[str, int] = {"annual": 1, "semiannual": 2, "quarterly": 4, "monthly": 12}

Weights = Sequence[tuple[str, Decimal]]


def q2(value: Decimal) -> Decimal:
    """Quantize to the cent."""
    return Decimal(value).quantize(CENT)


def weights(method: str, shares: Weights) -> list[tuple[str, Decimal]]:
    """Weights of the units under a key; ``equal`` ignores the stored shares."""
    if method == "equal":
        return [(unit, Decimal("1")) for unit, _ in shares]
    return [(unit, Decimal(share)) for unit, share in shares]


def check_shares(method: str, shares: Sequence[Decimal]) -> tuple[bool, Decimal, Decimal | None]:
    """Whether a key's shares are valid: ``(ok, total, expected_total)``.

    Permille must add up to exactly 1000 and custom to exactly 100; area needs every
    share positive; equal needs at least one unit. No share may be negative.
    """
    total = sum((Decimal(s) for s in shares), ZERO)
    expected = EXPECTED_TOTAL.get(method)
    if not shares or any(Decimal(s) < 0 for s in shares):
        return False, total, expected
    if method == "area":
        return all(Decimal(s) > 0 for s in shares), total, expected
    if method == "equal":
        return True, total, expected
    return expected is not None and total == expected, total, expected


def allocate(amount: Decimal, unit_weights: Weights) -> dict[str, Decimal]:
    """Split ``amount`` over the weights; the parts add up to ``q2(amount)`` exactly."""
    amount = q2(Decimal(amount))
    total_w = sum((Decimal(w) for _, w in unit_weights), ZERO)
    if not unit_weights or total_w <= 0:
        return {}
    sign = Decimal("-1") if amount < 0 else Decimal("1")
    whole = abs(amount)
    parts: dict[str, Decimal] = {}
    remainders: list[tuple[Decimal, int, str]] = []
    for idx, (unit, w) in enumerate(unit_weights):
        raw = whole * Decimal(w) / total_w
        floor = raw.quantize(CENT, rounding=ROUND_DOWN)
        parts[unit] = parts.get(unit, ZERO) + floor
        remainders.append((raw - floor, -idx, unit))
    left = int((whole - sum(parts.values(), ZERO)) / CENT)
    for _, _, unit in sorted(remainders, reverse=True)[:left]:
        parts[unit] += CENT
    return {unit: sign * value for unit, value in parts.items()}


def add_into(target: dict[str, Decimal], parts: Mapping[str, Decimal]) -> None:
    """Add per-unit parts into ``target``."""
    for unit, value in parts.items():
        target[unit] = target.get(unit, ZERO) + value


def unit_budget(lines: Sequence[tuple[Decimal, str]], keys: Mapping[str, Weights]) -> dict[str, Decimal]:
    """Yearly charge per unit: each budget line ``(amount, key_id)`` split by its key's weights."""
    out: dict[str, Decimal] = {}
    for amount, key_id in lines:
        add_into(out, allocate(Decimal(amount), keys.get(key_id) or []))
    return out


def period_amount(yearly: Decimal, periods: int, index: int) -> Decimal:
    """The ``index``-th (1-based) instalment of ``yearly`` over ``periods``; instalments add up exactly."""
    split = allocate(yearly, [(str(i), Decimal("1")) for i in range(1, periods + 1)])
    return split.get(str(index), ZERO)


def reconcile(
    actual_by_category: Mapping[str, Decimal],
    key_for_category: Mapping[str, str],
    default_key: str | None,
    keys: Mapping[str, Weights],
    demanded_by_unit: Mapping[str, Decimal],
) -> dict[str, Any]:
    """Year-end balance per unit: ``balance = demanded - actual_share``, exact.

    A category with a budget line uses that line's key; any other category uses
    ``default_key``; with neither it is reported as unallocated and charged to nobody.
    A positive balance is owed back to the owner, a negative one is owed by the owner.
    """
    share: dict[str, Decimal] = {}
    unallocated: dict[str, Decimal] = {}
    for category, amount in sorted(actual_by_category.items()):
        key_id = key_for_category.get(category) or default_key
        unit_w = keys.get(key_id) if key_id else None
        if not unit_w:
            unallocated[category] = q2(Decimal(amount))
            continue
        add_into(share, allocate(Decimal(amount), unit_w))
    rows = []
    for unit in sorted(set(share) | set(demanded_by_unit)):
        demanded = q2(Decimal(demanded_by_unit.get(unit, ZERO)))
        actual = share.get(unit, ZERO)
        rows.append({"unit_ref": unit, "demanded": demanded, "actual_share": actual, "balance": demanded - actual})
    return {"units": rows, "unallocated": unallocated}
