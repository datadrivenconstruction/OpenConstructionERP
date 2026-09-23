# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""BOQ lookups shared by the BOQ actions.

Everything here reads columns, never whole ``BOQ`` objects: loading a bill
loads every position and markup it has (both collections are ``selectin``),
and a preview needs a handful of values. Reads go past the identity map, so a
drift or undo check sees what the database holds now, not what this session
happened to load earlier.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from fastapi import HTTPException
from sqlalchemy import func, select

from app.modules.erp_chat.actions.base import (
    ActionContext,
    ActionNotFoundError,
    ActionValidationError,
    coerce_uuid,
    decimal_str,
    to_decimal,
)

# Marks a line the assistant proposed and a person applied. It is one of the
# values ``PositionCreate`` accepts, the one ``ai_agents`` already writes for
# the same human-confirmed flow, and the BOQ grid treats every source
# containing "ai" as AI-sourced: the "AI" filter finds the line and the
# ordinal carries the confidence chip.
AI_SOURCE = "ai_match"


@dataclass(frozen=True)
class BillRef:
    """The bill facts a proposal needs."""

    id: uuid.UUID
    name: str
    project_id: uuid.UUID
    is_locked: bool


@dataclass(frozen=True)
class LineRow:
    """One position of a bill, as columns."""

    id: uuid.UUID
    boq_id: uuid.UUID
    parent_id: uuid.UUID | None
    ordinal: str
    description: str
    unit: str
    quantity: str
    unit_rate: str
    total: str
    sort_order: int
    link_role: str | None
    link_group_id: uuid.UUID | None

    @property
    def is_section(self) -> bool:
        """The BOQ module's own rule for a section heading (``_is_section``)."""
        from app.modules.boq.service import _is_section

        return bool(_is_section(self))  # type: ignore[arg-type]

    @property
    def label(self) -> str:
        """``"03.012 Concrete wall C30/37"``, cut to a card-sized length."""
        text = (self.description or "").strip()
        if len(text) > 60:
            text = text[:59].rstrip() + "…"
        return f"{self.ordinal} {text}".strip()

    def state(self) -> dict[str, Any]:
        """The values an edit or an undo compares."""
        return {
            "ordinal": self.ordinal,
            "description": self.description,
            "unit": self.unit,
            "quantity": decimal_str(self.quantity) or "0",
            "unit_rate": decimal_str(self.unit_rate) or "0",
            "total": decimal_str(self.total) or "0",
        }


def position_url(boq_id: Any, position_id: Any) -> str:
    """Deep link the BOQ editor understands (scrolls to and flashes the row)."""
    return f"/boq/{boq_id}?highlight={position_id}"


def line_total(quantity: Any, unit_rate: Any) -> Decimal:
    """``quantity * unit_rate`` at the 4-decimal precision the BOQ stores."""
    q = to_decimal(quantity) or Decimal("0")
    r = to_decimal(unit_rate) or Decimal("0")
    return (q * r).quantize(Decimal("0.0001"))


def position_state(position: Any) -> dict[str, Any]:
    """The compared values of a Position ORM object right after a write."""
    return {
        "ordinal": position.ordinal,
        "description": position.description,
        "unit": position.unit,
        "quantity": decimal_str(position.quantity) or "0",
        "unit_rate": decimal_str(position.unit_rate) or "0",
        "total": decimal_str(position.total) or "0",
    }


def _line_columns() -> list[Any]:
    from app.modules.boq.models import Position

    return [
        Position.id,
        Position.boq_id,
        Position.parent_id,
        Position.ordinal,
        Position.description,
        Position.unit,
        Position.quantity,
        Position.unit_rate,
        Position.total,
        Position.sort_order,
        Position.link_role,
        Position.link_group_id,
    ]


def _to_line(row: Any) -> LineRow:
    return LineRow(
        id=row[0],
        boq_id=row[1],
        parent_id=row[2],
        ordinal=str(row[3] or ""),
        description=str(row[4] or ""),
        unit=str(row[5] or ""),
        quantity=str(row[6] or "0"),
        unit_rate=str(row[7] or "0"),
        total=str(row[8] or "0"),
        sort_order=int(row[9] or 0),
        link_role=row[10],
        link_group_id=row[11],
    )


async def bill_lines(ctx: ActionContext, boq_id: uuid.UUID) -> list[LineRow]:
    """Every position of a bill in grid order."""
    from app.modules.boq.models import Position

    stmt = select(*_line_columns()).where(Position.boq_id == boq_id).order_by(Position.sort_order, Position.ordinal)
    return [_to_line(row) for row in (await ctx.session.execute(stmt)).all()]


async def get_line(ctx: ActionContext, position_id: uuid.UUID) -> LineRow | None:
    """One position, read from the database now."""
    from app.modules.boq.models import Position

    row = (await ctx.session.execute(select(*_line_columns()).where(Position.id == position_id))).one_or_none()
    return _to_line(row) if row is not None else None


async def linked_count(ctx: ActionContext, line: LineRow) -> int:
    """How many other positions share the line's link group."""
    from app.modules.boq.models import Position

    if line.link_group_id is None:
        return 0
    stmt = select(func.count(Position.id)).where(
        Position.link_group_id == line.link_group_id,
        Position.id != line.id,
    )
    return int((await ctx.session.execute(stmt)).scalar_one() or 0)


def _bill_columns() -> list[Any]:
    from app.modules.boq.models import BOQ

    return [BOQ.id, BOQ.name, BOQ.project_id, BOQ.is_locked]


def _to_bill(row: Any) -> BillRef:
    return BillRef(id=row[0], name=str(row[1] or ""), project_id=row[2], is_locked=bool(row[3]))


async def get_bill(ctx: ActionContext, boq_id: uuid.UUID) -> BillRef | None:
    """One bill's facts, or None."""
    from app.modules.boq.models import BOQ

    row = (await ctx.session.execute(select(*_bill_columns()).where(BOQ.id == boq_id))).one_or_none()
    return _to_bill(row) if row is not None else None


async def project_bills(ctx: ActionContext, project_id: uuid.UUID) -> list[BillRef]:
    """The project's bill register, oldest first; variation bills excluded as the register does."""
    from app.modules.boq.models import BOQ

    stmt = (
        select(*_bill_columns())
        .where(BOQ.project_id == project_id, BOQ.variation_request_id.is_(None))
        .order_by(BOQ.created_at)
    )
    return [_to_bill(row) for row in (await ctx.session.execute(stmt)).all()]


def bill_options(bills: list[BillRef]) -> list[dict[str, Any]]:
    """Bills as options the model can offer the person."""
    return [{"id": str(b.id), "name": b.name, "locked": b.is_locked} for b in bills]


async def resolve_bill(ctx: ActionContext, project_id: uuid.UUID, args: dict[str, Any]) -> BillRef:
    """The bill a change goes into.

    ``boq_id`` wins when given. Otherwise a project with exactly one bill uses
    it, and ``boq`` (a name) picks one of several when it matches exactly one.
    Anything else is a 422 listing the bills, so the model can ask the person.
    """
    bills: list[BillRef] | None = None
    raw_id = args.get("boq_id")
    if raw_id not in (None, ""):
        bill_id = coerce_uuid(raw_id)
        bill = await get_bill(ctx, bill_id) if bill_id is not None else None
        if bill is None or bill.project_id != project_id:
            bills = await project_bills(ctx, project_id)
            raise ActionValidationError(code="boq_not_found", options=bill_options(bills))
        return bill
    bills = await project_bills(ctx, project_id)
    if not bills:
        raise ActionValidationError(code="no_boq")
    if len(bills) == 1:
        return bills[0]
    wanted = str(args.get("boq") or "").strip().casefold()
    if wanted:
        exact = [b for b in bills if b.name.strip().casefold() == wanted]
        partial = exact or [b for b in bills if wanted in b.name.casefold()]
        if len(partial) == 1:
            return partial[0]
    raise ActionValidationError(code="boq_ambiguous", options=bill_options(bills))


async def verify_bill_access(ctx: ActionContext, boq_id: uuid.UUID) -> None:
    """The BOQ router's ``_verify_boq_owner`` for this person: admin, owner or member, else 404."""
    from app.modules.boq.router import _verify_boq_owner

    try:
        await _verify_boq_owner(ctx.session, boq_id, str(ctx.user_id), ctx.auth_payload)
    except HTTPException as exc:
        raise ActionNotFoundError(code="boq_not_found") from exc


_LEADING_INT = re.compile(r"^\s*(\d+)")


def _leading_int(text: str) -> int | None:
    """``parseInt`` semantics: the leading digits of ``text``, or None."""
    match = _LEADING_INT.match(text or "")
    return int(match.group(1)) if match else None


def next_ordinal(section: LineRow | None, taken: set[str]) -> str:
    """The number the BOQ editor would give a new line, never one already taken.

    Same rule as the editor's "Add position": inside a section, the largest
    numeric suffix under ``<section>.`` plus 10 (``01.10``, ``01.20``); with no
    section, the next multiple of 10 above the largest leading number, padded
    to four digits (``0010``). ``taken`` holds the bill's ordinals and those
    other pending proposals already claimed, so proposals made in one turn
    number themselves one after another instead of colliding on apply.
    """
    if section is not None:
        prefix = f"{section.ordinal.strip()}."
        suffixes = [_leading_int(o[len(prefix) :]) for o in taken if o.startswith(prefix)]
        step = max([s for s in suffixes if s is not None], default=0) + 10
        candidate = f"{prefix}{step:02d}"
        while candidate in taken:
            step += 10
            candidate = f"{prefix}{step:02d}"
        return candidate
    tops = [_leading_int(o) for o in taken]
    step = (max([t for t in tops if t is not None], default=0) // 10 + 1) * 10
    candidate = f"{step:04d}"
    while candidate in taken:
        step += 10
        candidate = f"{step:04d}"
    return candidate
