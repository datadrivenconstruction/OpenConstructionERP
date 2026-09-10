# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Measurement sheet model: formula-based quantity determination.

A measurement sheet belongs to one BoQ item and holds the take-off lines that
build its quantity. Each line carries a formula, an optional repeat factor and
a sign (add or deduct, for openings and voids), so the total quantity is fully
auditable. This is the neutral core; REB 23.003 (DA11/DA12) and OENORM A 2063
are presentation and interchange conventions over the same data (see
``presets.py``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from app.modules.measurement.formula import MeasurementError, safe_eval

_3P = Decimal("0.001")
_4P = Decimal("0.0001")


def _dec(value: Any, default: str = "0") -> Decimal:
    if isinstance(value, Decimal):
        return value
    if value is None or value == "":
        return Decimal(default)
    try:
        return Decimal(str(value))
    except (ArithmeticError, ValueError, TypeError):
        return Decimal(default)


@dataclass
class MeasurementLine:
    """One take-off line contributing a signed partial quantity."""

    description: str
    formula: str
    variables: dict[str, Any] = field(default_factory=dict)
    factor: Decimal = Decimal("1")
    sign: str = "+"  # "+" add, "-" deduct
    ref: str = ""
    unit: str = ""
    error: str = ""

    @property
    def raw_quantity(self) -> Decimal:
        """Signed contribution: sign * factor * formula. 0 if the line errored."""
        if self.error:
            return Decimal("0")
        value = safe_eval(self.formula, self.variables)
        signed = -value if str(self.sign).strip() == "-" else value
        return _dec(self.factor, "1") * signed


@dataclass
class MeasurementSheet:
    """All take-off lines for one BoQ item, totalling its quantity."""

    item_ref: str
    description: str
    unit: str
    lines: list[MeasurementLine]
    currency: str = ""  # unused, kept for symmetry with priced views

    @property
    def total_quantity(self) -> Decimal:
        return sum((ln.raw_quantity for ln in self.lines), Decimal("0"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "item_ref": self.item_ref,
            "description": self.description,
            "unit": self.unit,
            "lines": [
                {
                    "ref": ln.ref,
                    "description": ln.description,
                    "formula": ln.formula,
                    "variables": {k: str(_dec(v)) for k, v in (ln.variables or {}).items()},
                    "factor": str(_dec(ln.factor, "1")),
                    "sign": "-" if str(ln.sign).strip() == "-" else "+",
                    "unit": ln.unit or self.unit,
                    "quantity": _q(ln.raw_quantity, _3P),
                    "error": ln.error,
                }
                for ln in self.lines
            ],
            "total_quantity": _q(self.total_quantity, _3P),
            "line_count": len(self.lines),
            "has_errors": any(ln.error for ln in self.lines),
        }


def _q(value: Decimal, quant: Decimal) -> str:
    return str(_dec(value).quantize(quant, rounding=ROUND_HALF_UP))


def build_line(raw: dict[str, Any], *, strict: bool = True) -> MeasurementLine:
    """Build and validate one measurement line from a plain dict.

    In non-strict mode a bad formula is kept as an error on the line
    (quantity 0) instead of raising, so one typo does not blow up a whole
    sheet in the UI.

    Args:
        raw: Dict with keys ``description``, ``formula``, ``variables``,
            ``factor``, ``sign``, ``ref``, ``unit``.
        strict: If ``True`` (default), an invalid formula raises
            :class:`MeasurementError`. If ``False``, the error is captured
            on the line and its quantity becomes zero.

    Returns:
        A validated :class:`MeasurementLine`.

    Raises:
        MeasurementError: If *strict* and the formula is invalid.
    """
    line = MeasurementLine(
        description=str(raw.get("description") or "").strip(),
        formula=str(raw.get("formula") or "").strip(),
        variables=dict(raw.get("variables") or {}),
        factor=_dec(raw.get("factor"), "1"),
        sign="-" if str(raw.get("sign") or "+").strip() == "-" else "+",
        ref=str(raw.get("ref") or ""),
        unit=str(raw.get("unit") or ""),
    )
    try:
        safe_eval(line.formula, line.variables)  # validate now
    except MeasurementError as exc:
        if strict:
            raise
        line.error = str(exc)
    return line


def reconcile(sheet: MeasurementSheet, target_quantity: Any, *, tolerance: Any = "0.001") -> dict[str, Any]:
    """Compare the measured total against a target and report the drift.

    Lets a user trust or fix a quantity by showing whether the take-off
    total matches the position quantity within a configurable tolerance.

    Args:
        sheet: The measurement sheet whose total is compared.
        target_quantity: The expected quantity (e.g. position quantity).
            Converted to :class:`~decimal.Decimal` internally.
        tolerance: Maximum acceptable absolute difference. Defaults to
            ``"0.001"``.

    Returns:
        Dict with keys ``measured_quantity``, ``target_quantity``,
        ``difference``, ``tolerance`` and ``matches`` (bool).
    """
    measured = sheet.total_quantity
    target = _dec(target_quantity)
    tol = abs(_dec(tolerance, "0.001"))
    difference = measured - target
    return {
        "measured_quantity": _q(measured, _3P),
        "target_quantity": _q(target, _3P),
        "difference": _q(difference, _3P),
        "tolerance": str(tol),
        "matches": abs(difference) <= tol,
    }


def build_sheet(
    *,
    item_ref: str,
    description: str,
    unit: str,
    lines: list[dict[str, Any] | MeasurementLine],
    strict: bool = True,
) -> MeasurementSheet:
    """Assemble a :class:`MeasurementSheet` from plain dicts or lines.

    Args:
        item_ref: BoQ item reference the sheet belongs to.
        description: Human-readable description of the measured item.
        unit: Unit of measurement (m, m2, m3, etc.).
        lines: Raw dicts or pre-built :class:`MeasurementLine` instances.
        strict: Passed through to :func:`build_line` for dict entries.

    Returns:
        A :class:`MeasurementSheet` with all lines built and validated.

    Raises:
        MeasurementError: If *lines* is empty or *strict* and a formula
            is invalid.
    """
    built: list[MeasurementLine] = []
    for raw in lines or []:
        if isinstance(raw, MeasurementLine):
            built.append(raw)
        else:
            built.append(build_line(raw, strict=strict))
    if not built:
        raise MeasurementError("a measurement sheet needs at least one line")
    return MeasurementSheet(
        item_ref=str(item_ref or "").strip(),
        description=str(description or "").strip(),
        unit=str(unit or ""),
        lines=built,
    )
