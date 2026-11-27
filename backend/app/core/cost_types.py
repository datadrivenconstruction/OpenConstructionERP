# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Cost types: the one vocabulary for splitting a cost code by the kind of cost.

Estimators everywhere split a cost code by what the money buys: labour,
material, equipment, subcontract and other ("1.01 Mobilization" becomes one
budget line per type). This module is that vocabulary and the only place that
translates the many resource spellings into it.

Stored values are the long words below (``labor``, ``material``, ``equipment``,
``subcontractor``, ``other``), the same values budget lines already carried, so
nothing stored before changes meaning. The short codes L / M / E / S / O are
display labels the frontend translates; they are never stored.

``overhead`` and ``contingency`` stay valid budget categories for lines written
before this vocabulary existed. They are not cost types: a resource never maps
to them, and :func:`normalize_cost_type` returns ``None`` for them.

The bill keeps its finer resource kinds (``machinery`` apart from installed
``equipment``, ``operator`` apart from ``labor``) because methodologies price
them on different bases. They meet cost control only through
:func:`to_cost_type`, which folds machinery into equipment and operators into
labour.

Everything here is pure: standard library and :class:`~decimal.Decimal` only.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

LABOR = "labor"
MATERIAL = "material"
EQUIPMENT = "equipment"
SUBCONTRACTOR = "subcontractor"
OTHER = "other"

#: The cost types in display order (L, M, E, S, O).
COST_TYPES: tuple[str, ...] = (LABOR, MATERIAL, EQUIPMENT, SUBCONTRACTOR, OTHER)

#: Budget categories kept valid for lines written before the vocabulary existed.
LEGACY_BUDGET_CATEGORIES: tuple[str, ...] = ("overhead", "contingency")

#: Every value a budget line may carry in ``category``.
BUDGET_CATEGORIES: frozenset[str] = frozenset(COST_TYPES + LEGACY_BUDGET_CATEGORIES)

# Resource and import spellings, lower-cased, mapped to a cost type.
_ALIASES: dict[str, str] = {
    **dict.fromkeys(
        ("labor", "labour", "work", "worker", "workers", "crew", "operator", "operators"),
        LABOR,
    ),
    **dict.fromkeys(("material", "materials", "mat"), MATERIAL),
    **dict.fromkeys(
        (
            "equipment",
            "machinery",
            "machine",
            "machines",
            "mechanism",
            "mechanisms",
            "plant",
            "tool",
            "tools",
        ),
        EQUIPMENT,
    ),
    **dict.fromkeys(
        ("subcontractor", "subcontractors", "subcontract", "sub"),
        SUBCONTRACTOR,
    ),
    **dict.fromkeys(("other", "electricity", "misc", "miscellaneous"), OTHER),
}

_SYNONYMS_PATH = Path(__file__).resolve().parent / "country_data" / "cost_type_synonyms.json"


def _load_language_synonyms() -> dict[str, str]:
    """Language spellings from ``country_data/cost_type_synonyms.json``, folded into the neutral aliases."""
    try:
        data = json.loads(_SYNONYMS_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    out: dict[str, str] = {}
    for language, rows in data.items():
        if language.startswith("_") or not isinstance(rows, dict):
            continue
        for cost_type, spellings in rows.items():
            if cost_type in COST_TYPES and isinstance(spellings, list):
                out.update({str(sp).strip().lower(): cost_type for sp in spellings})
    return out


_ALIASES.update(_load_language_synonyms())

_CENT = Decimal("0.01")


def _key(raw: object) -> str:
    return str(raw or "").strip().lower().replace("-", "_").replace(" ", "_")


def normalize_cost_type(raw: object) -> str | None:
    """The cost type a spelling names, or ``None`` when it names none.

    Args:
        raw: A resource type, an import column value or a stored category.

    Returns:
        One of :data:`COST_TYPES`, or ``None`` for an empty, unknown or legacy
        (``overhead`` / ``contingency``) value.
    """
    return _ALIASES.get(_key(raw))


def to_cost_type(raw: object) -> str:
    """The cost type for a resource row, ``other`` when the spelling is unknown."""
    return normalize_cost_type(raw) or OTHER


def is_budget_category(raw: object) -> bool:
    """Whether ``raw`` is a value a budget line may store in ``category``."""
    return _key(raw) in BUDGET_CATEGORIES


def _dec(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool) or value == "":
        return None
    try:
        out = Decimal(repr(value)) if isinstance(value, float) else Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        return None
    return out if out.is_finite() else None


def resource_weight(resource: Mapping[str, Any]) -> Decimal:
    """A resource row's per-unit cost: ``quantity x unit_rate``, else its stored ``total``, else 0."""
    qty = _dec(resource.get("quantity"))
    rate = _dec(resource.get("unit_rate"))
    if qty is not None and rate is not None:
        return qty * rate
    return _dec(resource.get("total")) or Decimal("0")


@dataclass(frozen=True)
class CostTypeShare:
    """The part of a position's total that belongs to one cost type.

    ``weight`` is the per-unit resource cost the share was cut by and
    ``resource_count`` the rows behind it, so every amount is traceable to the
    resources it came from.
    """

    cost_type: str
    amount: Decimal
    weight: Decimal
    resource_count: int


def split_by_cost_type(
    total: Decimal,
    resources: Iterable[Any] | None,
    *,
    fx_factor: Callable[[str], Decimal | None] | None = None,
    unpriced: list[Mapping[str, Any]] | None = None,
) -> list[CostTypeShare]:
    """Split a position total over its resources' cost types.

    Each type takes ``total x (its resources' weight / all resources' weight)``
    in whole cents, and the last type (display order) takes the remainder, so
    the shares always add up to ``total`` exactly. Nothing is invented: with no
    resource rows, or rows whose weights add up to zero or less, the result is
    empty and the caller decides what an unsplit position means.

    Args:
        total: The position total (quantity x unit rate) to split.
        resources: The position's resource rows (dicts with ``type``,
            ``quantity``, ``unit_rate`` and optionally ``total`` and ``currency``).
        fx_factor: Converts a row's ``currency`` into the position's, so rows
            priced in different currencies weigh in one; a row it returns
            ``None`` for (no usable rate) is left out of the split.
        unpriced: When given, receives every row left out for want of a rate,
            so the caller can say so instead of dropping it silently.

    Returns:
        One share per cost type present, in :data:`COST_TYPES` order.
    """
    weights: dict[str, Decimal] = {}
    counts: dict[str, int] = {}
    for row in resources or ():
        if not isinstance(row, Mapping):
            continue
        weight = resource_weight(row)
        if fx_factor is not None:
            factor = fx_factor(str(row.get("currency") or "").strip().upper())
            if factor is None:
                if unpriced is not None:
                    unpriced.append(row)
                continue
            weight *= factor
        cost_type = to_cost_type(row.get("type"))
        weights[cost_type] = weights.get(cost_type, Decimal("0")) + weight
        counts[cost_type] = counts.get(cost_type, 0) + 1
    weight_sum = sum(weights.values(), Decimal("0"))
    if not weights or weight_sum <= 0:
        return []
    present = [ct for ct in COST_TYPES if ct in weights]
    shares: list[CostTypeShare] = []
    allotted = Decimal("0")
    for idx, cost_type in enumerate(present):
        if idx == len(present) - 1:
            amount = total - allotted
        else:
            amount = (total * weights[cost_type] / weight_sum).quantize(_CENT)
            allotted += amount
        shares.append(CostTypeShare(cost_type, amount, weights[cost_type], counts[cost_type]))
    return shares
