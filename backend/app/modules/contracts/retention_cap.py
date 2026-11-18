# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Statutory retention limits read from a table - pure, no I/O.

Several markets limit the retention an owner or contractor may hold, and a few
require a minimum to be held. The shape of the law is the same everywhere: a
percentage, which reaches some contracts and not others by sector (public or
private), contract value, agreement date and kind of building. This module
evaluates exactly that shape against a table a market pack ships; it carries no
percentage of its own.

Row kinds:

* ``cap`` - retention above ``pct`` of the payment is over the statutory limit.
* ``floor`` - retention below ``pct`` is under the reserve the statute requires
  the owner to hold.

A row reaches a contract when every condition it states holds. Conditions it
does not state do not narrow it. When several cap rows reach one contract the
lowest cap governs, and when several floors do the highest governs, because the
stricter limit is the one a payment can break.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

KIND_CAP = "cap"
KIND_FLOOR = "floor"
_CENT = Decimal("0.01")
_HUNDRED = Decimal("100")


class RetentionTableError(ValueError):
    """A pack's retention table carries a row this engine cannot read."""


@dataclass(frozen=True)
class RetentionRow:
    """One statutory retention limit."""

    code: str
    kind: str
    pct: Decimal
    source: str
    sectors: tuple[str, ...] = ()
    project_types: tuple[str, ...] = ()
    excluded_project_types: tuple[str, ...] = ()
    min_contract_value: Decimal | None = None
    min_inclusive: bool = True
    max_contract_value: Decimal | None = None
    agreement_date_from: date | None = None
    note: str = ""

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> RetentionRow:
        """Build a row from a pack table entry."""
        kind = str(raw.get("kind") or KIND_CAP)
        if kind not in (KIND_CAP, KIND_FLOOR):
            raise RetentionTableError(f"{raw.get('code')}: unknown kind {kind!r}")
        source = str(raw.get("source") or "")
        if not source.strip():
            raise RetentionTableError(f"{raw.get('code')}: a statutory limit must name its source")
        start = raw.get("agreement_date_from")
        return cls(
            code=str(raw["code"]),
            kind=kind,
            pct=Decimal(str(raw["pct"])),
            source=source,
            sectors=tuple(raw.get("sectors") or ()),
            project_types=tuple(raw.get("project_types") or ()),
            excluded_project_types=tuple(raw.get("excluded_project_types") or ()),
            min_contract_value=_opt_dec(raw.get("min_contract_value")),
            min_inclusive=bool(raw.get("min_inclusive", True)),
            max_contract_value=_opt_dec(raw.get("max_contract_value")),
            agreement_date_from=date.fromisoformat(str(start)) if start else None,
            note=str(raw.get("note") or ""),
        )

    def reaches(
        self,
        *,
        sector: str | None,
        project_type: str | None,
        contract_value: Decimal | None,
        agreement_date: date | None,
    ) -> bool:
        """Whether this limit applies to the contract described."""
        if self.sectors and sector not in self.sectors:
            return False
        if self.project_types and project_type not in self.project_types:
            return False
        if project_type and project_type in self.excluded_project_types:
            return False
        if self.min_contract_value is not None:
            if contract_value is None:
                return False
            if self.min_inclusive and contract_value < self.min_contract_value:
                return False
            if not self.min_inclusive and contract_value <= self.min_contract_value:
                return False
        if self.max_contract_value is not None and (
            contract_value is None or contract_value >= self.max_contract_value
        ):
            return False
        # A date-gated limit with no agreement date on file cannot be assumed
        # to apply; the caller is told the date is needed instead.
        return not (self.agreement_date_from and (agreement_date is None or agreement_date < self.agreement_date_from))


@dataclass(frozen=True)
class RetentionCheck:
    """The verdict on one payment's retention."""

    retention_pct: Decimal | None
    cap: RetentionRow | None
    floor: RetentionRow | None
    cap_amount: Decimal | None
    floor_amount: Decimal | None
    over_cap: bool
    below_floor: bool
    needs_agreement_date: bool

    def as_dict(self) -> dict[str, Any]:
        """JSON-ready form, money and percentages as strings."""
        return {
            "retention_pct": _s(self.retention_pct),
            "cap_pct": _s(self.cap.pct) if self.cap else None,
            "cap_code": self.cap.code if self.cap else None,
            "cap_source": self.cap.source if self.cap else None,
            "cap_amount": _s(self.cap_amount),
            "floor_pct": _s(self.floor.pct) if self.floor else None,
            "floor_code": self.floor.code if self.floor else None,
            "floor_source": self.floor.source if self.floor else None,
            "floor_amount": _s(self.floor_amount),
            "over_cap": self.over_cap,
            "below_floor": self.below_floor,
            "needs_agreement_date": self.needs_agreement_date,
        }


def _opt_dec(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    return Decimal(str(value))


def _s(value: Decimal | None) -> str | None:
    return None if value is None else format(value.normalize(), "f")


def parse_table(table: list[dict[str, Any]]) -> list[RetentionRow]:
    """Parse a pack's retention table."""
    return [RetentionRow.from_dict(raw) for raw in table]


def check_retention(
    rows: list[RetentionRow],
    *,
    sector: str | None,
    contract_value: Decimal | None,
    agreement_date: date | None = None,
    project_type: str | None = None,
    payment_amount: Decimal | None = None,
    retention_amount: Decimal | None = None,
    retention_pct: Decimal | None = None,
) -> RetentionCheck:
    """Compare the retention held on one payment with the limits that reach it.

    Args:
        rows: The jurisdiction's limits.
        sector: ``public`` or ``private``.
        contract_value: The contract sum, for value thresholds.
        agreement_date: When the contract was entered into, for date-gated limits.
        project_type: The kind of building, for limits that exclude or target one.
        payment_amount: The gross amount of the payment retention is taken from.
        retention_amount: The money held; with ``payment_amount`` gives the percentage.
        retention_pct: The percentage held, when the amount is not known.
    """
    pct = retention_pct
    if pct is None and retention_amount is not None and payment_amount:
        pct = (retention_amount / payment_amount * _HUNDRED).quantize(_CENT, rounding=ROUND_HALF_UP)

    reached = [
        r
        for r in rows
        if r.reaches(
            sector=sector, project_type=project_type, contract_value=contract_value, agreement_date=agreement_date
        )
    ]
    needs_date = agreement_date is None and any(
        r.agreement_date_from
        and r.reaches(
            sector=sector,
            project_type=project_type,
            contract_value=contract_value,
            agreement_date=r.agreement_date_from,
        )
        for r in rows
    )
    caps = [r for r in reached if r.kind == KIND_CAP]
    floors = [r for r in reached if r.kind == KIND_FLOOR]
    cap = min(caps, key=lambda r: r.pct) if caps else None
    floor = max(floors, key=lambda r: r.pct) if floors else None

    def _amount(row: RetentionRow | None) -> Decimal | None:
        if row is None or payment_amount is None:
            return None
        return (payment_amount * row.pct / _HUNDRED).quantize(_CENT, rounding=ROUND_HALF_UP)

    return RetentionCheck(
        retention_pct=pct,
        cap=cap,
        floor=floor,
        cap_amount=_amount(cap),
        floor_amount=_amount(floor),
        over_cap=bool(cap is not None and pct is not None and pct > cap.pct),
        below_floor=bool(floor is not None and pct is not None and pct < floor.pct),
        needs_agreement_date=needs_date,
    )


__all__ = [
    "KIND_CAP",
    "KIND_FLOOR",
    "RetentionCheck",
    "RetentionRow",
    "RetentionTableError",
    "check_retention",
    "parse_table",
]
