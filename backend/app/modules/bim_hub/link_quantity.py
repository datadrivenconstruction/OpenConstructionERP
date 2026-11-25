# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Quantity of a BOQ position from its linked model elements, with provenance.

One function, :func:`link_quantity`, decides the figure a position takes from
the elements linked to it and records how it got there: which quantity key of
the elements was read, the factor from the model's SI unit to the position's
unit, how many elements contributed and which ones carried no usable value.

Model quantities arrive in SI (``volume_m3``, ``area_m2``, ``length_m``,
``weight_kg`` and the converter's ``Volume`` / ``Area`` / ``Length`` /
``Weight``). A position in another unit of the same dimension is converted by
an exact Decimal factor (the international yard and pound are defined exactly
in metres and kilograms). A unit of no known dimension gets no figure at all:
``status`` says so and the caller leaves the quantity alone, so a mismatch is
reported, never summed into a wrong number.

Both the link-time sync in :mod:`app.modules.bim_hub.service` and the
new-version proposals in :mod:`app.modules.boq.change_review` call this, so a
position never reads one way when linked and another way when re-proposed.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

QTY_QUANTUM = Decimal("0.0001")

#: Element ids listed in a provenance record before the rest are only counted.
MAX_LISTED_IDS = 50

_FT = Decimal("0.3048")
_YD = Decimal("0.9144")
_LB = Decimal("0.45359237")

_VOLUME = ("volume_m3", "Volume", "volume")
_AREA = ("area_m2", "Area", "area")
_LENGTH = ("length_m", "Length", "length")
_WEIGHT = ("weight_kg", "Weight", "weight")

#: Position unit token -> (element quantity keys in SI, SI unit, factor SI -> position unit).
UNIT_DIMENSIONS: dict[str, tuple[tuple[str, ...], str, Decimal]] = {
    "m3": (_VOLUME, "m3", Decimal(1)),
    "cbm": (_VOLUME, "m3", Decimal(1)),
    "l": (_VOLUME, "m3", Decimal(1000)),
    "ft3": (_VOLUME, "m3", 1 / _FT**3),
    "cf": (_VOLUME, "m3", 1 / _FT**3),
    "cu ft": (_VOLUME, "m3", 1 / _FT**3),
    "yd3": (_VOLUME, "m3", 1 / _YD**3),
    "cy": (_VOLUME, "m3", 1 / _YD**3),
    "cu yd": (_VOLUME, "m3", 1 / _YD**3),
    "m2": (_AREA, "m2", Decimal(1)),
    "qm": (_AREA, "m2", Decimal(1)),
    "sqm": (_AREA, "m2", Decimal(1)),
    "ft2": (_AREA, "m2", 1 / _FT**2),
    "sf": (_AREA, "m2", 1 / _FT**2),
    "sq ft": (_AREA, "m2", 1 / _FT**2),
    "sqft": (_AREA, "m2", 1 / _FT**2),
    "yd2": (_AREA, "m2", 1 / _YD**2),
    "sy": (_AREA, "m2", 1 / _YD**2),
    "m": (_LENGTH, "m", Decimal(1)),
    "lfm": (_LENGTH, "m", Decimal(1)),
    "lm": (_LENGTH, "m", Decimal(1)),
    "mm": (_LENGTH, "m", Decimal(1000)),
    "cm": (_LENGTH, "m", Decimal(100)),
    "km": (_LENGTH, "m", Decimal("0.001")),
    "ft": (_LENGTH, "m", 1 / _FT),
    "lf": (_LENGTH, "m", 1 / _FT),
    "yd": (_LENGTH, "m", 1 / _YD),
    "kg": (_WEIGHT, "kg", Decimal(1)),
    "t": (_WEIGHT, "kg", Decimal("0.001")),
    "to": (_WEIGHT, "kg", Decimal("0.001")),
    "lb": (_WEIGHT, "kg", 1 / _LB),
    "lbs": (_WEIGHT, "kg", 1 / _LB),
}

STATUS_OK = "ok"
STATUS_NO_QUANTITY = "no_quantity"
STATUS_UNIT_UNSUPPORTED = "unit_unsupported"


@dataclass
class LinkQuantity:
    """The figure a position takes from its elements, and how it was reached."""

    unit: str
    method: str  # "count" | "sum" | "none"
    status: str
    quantity: Decimal | None
    source_unit: str = ""
    factor: Decimal = Decimal(1)
    keys: tuple[str, ...] = ()
    element_count: int = 0
    contributing: int = 0
    missing_ids: list[str] = field(default_factory=list)
    missing_count: int = 0
    key_counts: dict[str, int] = field(default_factory=dict)

    @property
    def formula(self) -> str:
        """Human-readable formula, e.g. ``sum(volume_m3) x 1 [m3 -> m3]``."""
        if self.method == "count":
            return f"count(elements) = {self.element_count}"
        if self.method != "sum":
            return ""
        used = "+".join(k for k in self.key_counts) or "/".join(self.keys[:1])
        return f"sum({used}) x {_plain(self.factor)} [{self.source_unit} -> {self.unit}]"

    def as_record(self) -> dict[str, Any]:
        """JSON-safe provenance record (Decimals as strings)."""
        return {
            "unit": self.unit,
            "method": self.method,
            "status": self.status,
            "quantity": None if self.quantity is None else str(self.quantity),
            "source_unit": self.source_unit,
            "factor": _plain(self.factor),
            "keys": list(self.keys),
            "key_counts": dict(self.key_counts),
            "formula": self.formula,
            "element_count": self.element_count,
            "contributing": self.contributing,
            "missing_count": self.missing_count,
            "missing_ids": list(self.missing_ids),
        }


def _plain(value: Decimal) -> str:
    text = format(value.normalize(), "f") if value == value.to_integral() else format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def _value(quantities: Mapping[str, Any], keys: Iterable[str]) -> tuple[str, Decimal] | None:
    for key in keys:
        raw = quantities.get(key)
        if raw is None or isinstance(raw, bool):
            continue
        try:
            value = Decimal(str(raw))
        except (InvalidOperation, TypeError, ValueError):
            continue
        if value.is_finite():
            return key, value
    return None


def link_quantity(
    unit_token: str,
    elements: Iterable[tuple[str, Mapping[str, Any] | None]],
    *,
    count_units: frozenset[str],
) -> LinkQuantity:
    """Quantity of a position in ``unit_token`` from ``(stable_id, quantities)`` pairs.

    Args:
        unit_token: Position unit already folded by ``normalize_unit_token``.
        elements: One pair per linked element.
        count_units: Units that count elements one for one.

    Returns:
        The figure with its provenance. ``quantity`` is ``None`` when the unit
        has no dimension the model can supply or no element carried a value.
    """
    items = list(elements)
    if unit_token in count_units:
        n = len(items)
        return LinkQuantity(
            unit=unit_token,
            method="count",
            status=STATUS_OK if n else STATUS_NO_QUANTITY,
            quantity=Decimal(n) if n else None,
            element_count=n,
            contributing=n,
        )
    dim = UNIT_DIMENSIONS.get(unit_token)
    if dim is None:
        return LinkQuantity(
            unit=unit_token,
            method="none",
            status=STATUS_UNIT_UNSUPPORTED,
            quantity=None,
            element_count=len(items),
        )
    keys, source_unit, factor = dim
    total = Decimal(0)
    contributing = 0
    missing: list[str] = []
    missing_count = 0
    key_counts: dict[str, int] = {}
    for stable_id, quantities in items:
        hit = _value(quantities or {}, keys)
        if hit is None or hit[1] <= 0:
            missing_count += 1
            if len(missing) < MAX_LISTED_IDS:
                missing.append(str(stable_id))
            continue
        key, value = hit
        total += value
        contributing += 1
        key_counts[key] = key_counts.get(key, 0) + 1
    quantity = (total * factor).quantize(QTY_QUANTUM) if contributing else None
    return LinkQuantity(
        unit=unit_token,
        method="sum",
        status=STATUS_OK if contributing else STATUS_NO_QUANTITY,
        quantity=quantity,
        source_unit=source_unit,
        factor=factor,
        keys=keys,
        element_count=len(items),
        contributing=contributing,
        missing_ids=missing,
        missing_count=missing_count,
        key_counts=key_counts,
    )
