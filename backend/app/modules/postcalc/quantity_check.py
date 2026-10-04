# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Quantity check: contract quantity against measured quantity, per bill position.

The question a cost controller asks of every position once the site measures:
the bill was let at this quantity, the site measured that one, what is the
difference and what does it cost at the contract rate.

Three sources, and why each was chosen:

* **Contract quantity and rate** come from the bill's quantity baseline, a
  snapshot (:mod:`app.modules.boq.quantity_baseline`). The live bill is not a
  safe source: saving a measurement sheet in the editor writes the sheet's
  total into the bill quantity. Without a baseline the live bill is used and
  every line says so.
* **Measured quantity** is the position's measurement sheet
  (``metadata.measurement``), typed in by hand or written by a GAEB X31 apply;
  the sheet's own ``source`` tells the two apart. A sheet that is exactly the
  one the baseline already carried is the estimating take-off the bill
  quantity was derived from, not a site measurement, and the line reads as not
  measured yet.
* Progress-claim quantities are deliberately NOT a measured source: a claim
  line's quantity is the contract quantity times a percent clamped to 100, so
  it can never show an overrun and a part-claimed line would read as a saving.

The top half is pure (plain values in, dataclasses out); the loader at the
bottom reads the rows.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy.ext.asyncio import AsyncSession

_Q3 = Decimal("0.001")
_C2 = Decimal("0.01")
_P1 = Decimal("0.1")
_HUNDRED = Decimal("100")
_ZERO = Decimal("0")

SOURCE_SHEET = "measurement_sheet"
SOURCE_X31 = "gaeb_x31"

STATUS_OVER = "over"
STATUS_UNDER = "under"
STATUS_MATCHES = "matches"
STATUS_NOT_MEASURED = "not_measured"

BASELINE_SNAPSHOT = "snapshot"
BASELINE_CURRENT = "current"


def _dec(value: object) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        out = value if isinstance(value, Decimal) else Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        return None
    return out if out.is_finite() else None


def _q3(value: Decimal) -> Decimal:
    return value.quantize(_Q3, rounding=ROUND_HALF_UP)


def _c2(value: Decimal) -> Decimal:
    return value.quantize(_C2, rounding=ROUND_HALF_UP)


def _s(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


def _sheet_of(meta: object) -> dict[str, Any] | None:
    """The stored measurement sheet of a metadata dict, when it has lines."""
    if not isinstance(meta, dict):
        return None
    sheet = meta.get("measurement")
    if not isinstance(sheet, dict):
        return None
    lines = [ln for ln in (sheet.get("lines") or []) if isinstance(ln, dict)]
    return sheet if lines else None


def _same_sheet(a: dict[str, Any] | None, b: dict[str, Any] | None) -> bool:
    if a is None or b is None:
        return False
    return (a.get("lines") or []) == (b.get("lines") or []) and str(a.get("unit") or "") == str(b.get("unit") or "")


@dataclass(slots=True)
class BaselineLine:
    """One position as the baseline froze it."""

    position_id: str
    ordinal: str
    description: str
    unit: str
    quantity: Decimal
    unit_rate: Decimal
    sheet: dict[str, Any] | None


@dataclass(slots=True)
class CurrentLine:
    """One position as the bill holds it now."""

    position_id: str
    ordinal: str
    description: str
    unit: str
    quantity: Decimal
    unit_rate: Decimal
    sheet: dict[str, Any] | None
    measured: Decimal | None


@dataclass(slots=True)
class QuantityCheckLine:
    position_id: str
    ordinal: str
    description: str
    unit: str
    contract_quantity: Decimal | None
    contract_unit_rate: Decimal | None
    contract_value: Decimal | None
    measured_quantity: Decimal | None
    measured_source: str | None
    difference: Decimal | None
    difference_pct: Decimal | None
    cost_effect: Decimal | None
    status: str
    in_baseline: bool
    in_bill: bool
    sheet_unchanged_since_baseline: bool = False
    contract_quantity_may_be_measured: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "position_id": self.position_id,
            "ordinal": self.ordinal,
            "description": self.description,
            "unit": self.unit,
            "contract_quantity": _s(self.contract_quantity),
            "contract_unit_rate": _s(self.contract_unit_rate),
            "contract_value": _s(self.contract_value),
            "measured_quantity": _s(self.measured_quantity),
            "measured_source": self.measured_source,
            "difference": _s(self.difference),
            "difference_pct": _s(self.difference_pct),
            "cost_effect": _s(self.cost_effect),
            "status": self.status,
            "in_baseline": self.in_baseline,
            "in_bill": self.in_bill,
            "sheet_unchanged_since_baseline": self.sheet_unchanged_since_baseline,
            "contract_quantity_may_be_measured": self.contract_quantity_may_be_measured,
        }


@dataclass(slots=True)
class QuantityCheckTotals:
    line_count: int = 0
    measured_count: int = 0
    not_measured_count: int = 0
    over_count: int = 0
    under_count: int = 0
    matches_count: int = 0
    contract_value: Decimal = _ZERO
    measured_contract_value: Decimal = _ZERO
    cost_effect_over: Decimal = _ZERO
    cost_effect_under: Decimal = _ZERO
    cost_effect_net: Decimal = _ZERO

    def to_dict(self) -> dict[str, Any]:
        return {
            "line_count": self.line_count,
            "measured_count": self.measured_count,
            "not_measured_count": self.not_measured_count,
            "over_count": self.over_count,
            "under_count": self.under_count,
            "matches_count": self.matches_count,
            "contract_value": str(_c2(self.contract_value)),
            "measured_contract_value": str(_c2(self.measured_contract_value)),
            "cost_effect_over": str(_c2(self.cost_effect_over)),
            "cost_effect_under": str(_c2(self.cost_effect_under)),
            "cost_effect_net": str(_c2(self.cost_effect_net)),
        }


@dataclass(slots=True)
class QuantityCheck:
    lines: list[QuantityCheckLine] = field(default_factory=list)
    totals: QuantityCheckTotals = field(default_factory=QuantityCheckTotals)


def _measured_source(sheet: dict[str, Any] | None) -> str:
    return SOURCE_X31 if isinstance(sheet, dict) and sheet.get("source") == SOURCE_X31 else SOURCE_SHEET


def compare_line(
    base: BaselineLine | None,
    cur: CurrentLine | None,
    *,
    baseline_kind: str,
) -> QuantityCheckLine:
    """Compare one position's contract side against its measured side.

    ``base`` is ``None`` for a position added since the baseline, ``cur`` is
    ``None`` for one removed from the bill since. The percent is ``None`` when
    the contract quantity is zero or unknown: any measured quantity on such a
    line is entirely beyond the contract and has no meaningful ratio.
    """
    ref = cur if cur is not None else base
    if ref is None:
        raise ValueError("compare_line needs a baseline line, a bill line or both")
    contract_qty = base.quantity if base is not None else None
    contract_rate = base.unit_rate if base is not None else None
    contract_value = _c2(contract_qty * contract_rate) if base is not None else None

    measured: Decimal | None = None
    source: str | None = None
    unchanged = False
    may_be_measured = False
    if cur is not None and cur.measured is not None and cur.sheet is not None:
        if baseline_kind == BASELINE_SNAPSHOT and base is not None and _same_sheet(base.sheet, cur.sheet):
            # The sheet the bill was let with: the estimating take-off, not a
            # site measurement.
            unchanged = True
        else:
            measured = _q3(cur.measured)
            source = _measured_source(cur.sheet)
    if (
        baseline_kind == BASELINE_CURRENT
        and measured is not None
        and source == SOURCE_SHEET
        and contract_qty is not None
        and _q3(contract_qty) == measured
    ):
        # Saving a sheet in the editor writes its total into the bill quantity,
        # so with no baseline this "contract" figure may be the measurement.
        may_be_measured = True

    difference: Decimal | None = None
    pct: Decimal | None = None
    cost: Decimal | None = None
    if measured is None:
        status = STATUS_NOT_MEASURED
    else:
        base_qty = contract_qty if contract_qty is not None else _ZERO
        difference = _q3(measured - base_qty)
        if base_qty != _ZERO:
            pct = (difference / base_qty * _HUNDRED).quantize(_P1, rounding=ROUND_HALF_UP)
        # A position added since the baseline has no contract rate; its whole
        # measured quantity is extra, priced at the rate the bill carries now.
        rate = contract_rate if contract_rate is not None else (cur.unit_rate if cur is not None else _ZERO)
        cost = _c2(difference * rate)
        status = STATUS_OVER if difference > 0 else STATUS_UNDER if difference < 0 else STATUS_MATCHES

    return QuantityCheckLine(
        position_id=ref.position_id,
        ordinal=ref.ordinal,
        description=ref.description,
        unit=ref.unit,
        contract_quantity=_q3(contract_qty) if contract_qty is not None else None,
        contract_unit_rate=contract_rate,
        contract_value=contract_value,
        measured_quantity=measured,
        measured_source=source,
        difference=difference,
        difference_pct=pct,
        cost_effect=cost,
        status=status,
        in_baseline=base is not None,
        in_bill=cur is not None,
        sheet_unchanged_since_baseline=unchanged,
        contract_quantity_may_be_measured=may_be_measured,
    )


def build_quantity_check(
    baseline: Sequence[BaselineLine],
    current: Sequence[CurrentLine],
    *,
    baseline_kind: str,
) -> QuantityCheck:
    """Pair baseline and bill lines by position id, in bill order, and total them."""
    base_by_id = {b.position_id: b for b in baseline}
    seen: set[str] = set()
    lines: list[QuantityCheckLine] = []
    for cur in current:
        seen.add(cur.position_id)
        lines.append(compare_line(base_by_id.get(cur.position_id), cur, baseline_kind=baseline_kind))
    for base in baseline:
        if base.position_id not in seen:
            lines.append(compare_line(base, None, baseline_kind=baseline_kind))

    totals = QuantityCheckTotals(line_count=len(lines))
    for ln in lines:
        if ln.contract_value is not None:
            totals.contract_value += ln.contract_value
        if ln.status == STATUS_NOT_MEASURED:
            totals.not_measured_count += 1
            continue
        totals.measured_count += 1
        if ln.contract_value is not None:
            totals.measured_contract_value += ln.contract_value
        cost = ln.cost_effect or _ZERO
        if ln.status == STATUS_OVER:
            totals.over_count += 1
            totals.cost_effect_over += cost
        elif ln.status == STATUS_UNDER:
            totals.under_count += 1
            totals.cost_effect_under += cost
        else:
            totals.matches_count += 1
        totals.cost_effect_net += cost
    return QuantityCheck(lines=lines, totals=totals)


# ── Loader ───────────────────────────────────────────────────────────────


def _is_section_like(row: Any) -> bool:
    from app.modules.boq.service import _is_section

    return _is_section(row)


def baseline_lines_from_snapshot(snapshot_data: object) -> list[BaselineLine]:
    """The position rows a ``BOQSnapshot.snapshot_data`` froze, sections left out."""
    rows = snapshot_data.get("positions") if isinstance(snapshot_data, dict) else None
    out: list[BaselineLine] = []
    for row in rows or []:
        if not isinstance(row, dict) or not row.get("id"):
            continue
        ns = SimpleNamespace(unit=row.get("unit"), quantity=row.get("quantity"), unit_rate=row.get("unit_rate"))
        if _is_section_like(ns):
            continue
        out.append(
            BaselineLine(
                position_id=str(row["id"]),
                ordinal=str(row.get("ordinal") or ""),
                description=str(row.get("description") or ""),
                unit=str(row.get("unit") or ""),
                quantity=_dec(row.get("quantity")) or _ZERO,
                unit_rate=_dec(row.get("unit_rate")) or _ZERO,
                sheet=_sheet_of(row.get("metadata")),
            )
        )
    return out


def current_lines(positions: Sequence[Any]) -> list[CurrentLine]:
    """The bill's positions as they stand, sections left out."""
    from app.modules.boq.gaeb_x31 import measured_quantity_of

    out: list[CurrentLine] = []
    for pos in positions:
        if _is_section_like(pos):
            continue
        meta = pos.metadata_ if isinstance(pos.metadata_, dict) else {}
        sheet = _sheet_of(meta)
        out.append(
            CurrentLine(
                position_id=str(pos.id),
                ordinal=str(pos.ordinal or ""),
                description=str(pos.description or ""),
                unit=str(pos.unit or ""),
                quantity=_dec(pos.quantity) or _ZERO,
                unit_rate=_dec(pos.unit_rate) or _ZERO,
                sheet=sheet,
                measured=measured_quantity_of(pos) if sheet is not None else None,
            )
        )
    return out


class QuantityCheckError(LookupError):
    """A bill or snapshot the caller named is not part of the project."""


async def load_quantity_check(
    session: AsyncSession,
    project_id: uuid.UUID,
    *,
    boq_id: uuid.UUID | None,
    snapshot_id: uuid.UUID | None,
) -> dict[str, Any]:
    """The quantity check of one bill of ``project_id``, as the endpoint returns it.

    ``boq_id`` defaults to the project's first bill. ``snapshot_id`` overrides
    the bill's designated baseline for this read only. The caller has already
    checked project access; a bill or snapshot outside the project raises
    :class:`QuantityCheckError`, which the router answers as 404.
    """
    from sqlalchemy import select

    from app.modules.boq.models import BOQ, BOQSnapshot
    from app.modules.boq.quantity_baseline import baseline_entry, designated_baseline_id
    from app.modules.boq.repository import PositionRepository
    from app.modules.projects.repository import ProjectRepository

    project = await ProjectRepository(session).get_by_id(project_id)
    bills = list(
        (await session.execute(select(BOQ).where(BOQ.project_id == project_id).order_by(BOQ.created_at, BOQ.name)))
        .scalars()
        .all()
    )
    project_currency = str(getattr(project, "currency", "") or "")

    def bill_currency(b: Any) -> str:
        meta = b.metadata_ if isinstance(b.metadata_, dict) else {}
        return str(meta.get("currency") or project_currency or "")

    base_payload: dict[str, Any] = {
        "project_id": str(project_id),
        "country_code": str(getattr(project, "country_code", "") or "").upper(),
        "boqs": [
            {
                "id": str(b.id),
                "name": str(b.name or ""),
                "is_locked": bool(b.is_locked),
                "currency": bill_currency(b),
            }
            for b in bills
        ],
    }
    if boq_id is None:
        if not bills:
            return {**base_payload, "boq_id": None, "lines": [], "totals": QuantityCheckTotals().to_dict()}
        boq = bills[0]
    else:
        found = next((b for b in bills if b.id == boq_id), None)
        if found is None:
            raise QuantityCheckError("boq")
        boq = found

    snapshots = list(
        (
            await session.execute(
                select(BOQSnapshot.id, BOQSnapshot.name, BOQSnapshot.created_at, BOQSnapshot.position_count)
                .where(BOQSnapshot.boq_id == boq.id)
                .order_by(BOQSnapshot.created_at.desc())
            )
        ).all()
    )
    snapshot_ids = {row[0] for row in snapshots}
    designated = designated_baseline_id(boq)
    warnings: list[str] = []

    chosen: uuid.UUID | None
    if snapshot_id is not None:
        if snapshot_id not in snapshot_ids:
            raise QuantityCheckError("snapshot")
        chosen = snapshot_id
    elif designated is not None and designated in snapshot_ids:
        chosen = designated
    else:
        if designated is not None:
            # The snapshot the bill named was deleted from the version history.
            warnings.append("baseline_snapshot_missing")
        chosen = None

    positions = await PositionRepository(session).list_all_for_boq(boq.id)
    current = current_lines(positions)
    if chosen is not None:
        snap = (await session.execute(select(BOQSnapshot).where(BOQSnapshot.id == chosen))).scalar_one()
        baseline = baseline_lines_from_snapshot(snap.snapshot_data)
        kind = BASELINE_SNAPSHOT
        baseline_info: dict[str, Any] = {
            "kind": kind,
            "snapshot_id": str(snap.id),
            "name": snap.name,
            "created_at": snap.created_at.isoformat() if snap.created_at else None,
            "designated": chosen == designated,
        }
    else:
        # No snapshot: the bill as it stands is the contract side.
        baseline = [
            BaselineLine(
                position_id=c.position_id,
                ordinal=c.ordinal,
                description=c.description,
                unit=c.unit,
                quantity=c.quantity,
                unit_rate=c.unit_rate,
                sheet=c.sheet,
            )
            for c in current
        ]
        kind = BASELINE_CURRENT
        baseline_info = {"kind": kind, "snapshot_id": None, "name": None, "created_at": None, "designated": False}
        warnings.append("no_baseline")

    report = build_quantity_check(baseline, current, baseline_kind=kind)
    entry = baseline_entry(boq)
    baseline_info["designated_reason"] = entry.get("reason") if chosen == designated else None
    return {
        **base_payload,
        "boq_id": str(boq.id),
        "boq_name": str(boq.name or ""),
        "currency": bill_currency(boq),
        "is_locked": bool(boq.is_locked),
        "baseline": baseline_info,
        "designated_snapshot_id": str(designated) if designated is not None and designated in snapshot_ids else None,
        "snapshots": [
            {
                "id": str(sid),
                "name": str(name or ""),
                "created_at": created.isoformat() if created else None,
                "position_count": count,
            }
            for sid, name, created, count in snapshots
        ],
        "warnings": warnings,
        "lines": [ln.to_dict() for ln in report.lines],
        "totals": report.totals.to_dict(),
    }


__all__ = [
    "BASELINE_CURRENT",
    "BASELINE_SNAPSHOT",
    "SOURCE_SHEET",
    "SOURCE_X31",
    "STATUS_MATCHES",
    "STATUS_NOT_MEASURED",
    "STATUS_OVER",
    "STATUS_UNDER",
    "BaselineLine",
    "CurrentLine",
    "QuantityCheck",
    "QuantityCheckError",
    "QuantityCheckLine",
    "QuantityCheckTotals",
    "baseline_lines_from_snapshot",
    "build_quantity_check",
    "compare_line",
    "current_lines",
    "load_quantity_check",
]
