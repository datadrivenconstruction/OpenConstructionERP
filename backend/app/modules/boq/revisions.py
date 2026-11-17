# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Formal BOQ revisions (R0, R1, R2, ...) as one navigable lineage.

A formal revision is an ordinary bill raised from another with "Create
revision": a deep copy linked back through ``parent_estimate_id``. This module
adds what the link alone does not give: a stable number per revision and the
whole transitive chain, so any revision can show R0 to Rn with totals.

The number lives in ``metadata_["revision"]`` of the new bill; no column, no
backfill. A bill raised before numbering existed reads with its place in time
as a derived number and is never rewritten. The lineage root reads as R0.

What-if scenarios and estimate branches also hang off ``parent_estimate_id``
but are alternatives, not successive issues of the same bill: they and
everything raised from them are left out of a lineage, and each one opened on
its own heads its own.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Iterable, Sequence
from datetime import datetime
from decimal import Decimal
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.boq.models import BOQ
from app.modules.boq.repository import BOQRepository
from app.modules.boq.schemas import BOQRevisionEntry, BOQRevisionLineage

#: ``metadata_`` key of a numbered revision: ``{"number": int, "root_id": str}``.
REVISION_KEY = "revision"

#: Safety cap on a lineage walk; a real chain is a handful of bills.
_MAX_LINEAGE = 500

_SUFFIX = re.compile(r"\s*\((?:R\d+|Copy)\)\s*$")

_HEADER = (
    BOQ.id,
    BOQ.project_id,
    BOQ.name,
    BOQ.status,
    BOQ.is_locked,
    BOQ.created_at,
    BOQ.created_by,
    BOQ.parent_estimate_id,
    BOQ.branch_of_id,
    BOQ.metadata_,
)


def revision_label(number: int) -> str:
    """The human label of a revision number."""
    return f"R{number}"


def revision_name(source_name: str, number: int) -> str:
    """Name a new revision after its bill, replacing a previous ``(Rn)`` or ``(Copy)`` suffix."""
    base = _SUFFIX.sub("", (source_name or "").strip()).strip()
    label = f"({revision_label(number)})"
    return f"{base} {label}" if base else label


def stored_number(metadata: Any) -> int | None:
    """The revision number written on a bill, or None for a root or a legacy revision."""
    block = metadata.get(REVISION_KEY) if isinstance(metadata, dict) else None
    number = block.get("number") if isinstance(block, dict) else None
    return number if isinstance(number, int) and not isinstance(number, bool) and number >= 0 else None


def next_revision_number(numbers: Sequence[int | None]) -> int:
    """The number for a new revision of a lineage whose members carry ``numbers`` (oldest first).

    A member without a stored number reads as its place in time, so the next
    number is past both every stored number and every place; a gap left by a
    deleted revision is never filled again.
    """
    highest = max([n for n in numbers if n is not None] + [len(numbers) - 1, 0])
    return highest + 1


def is_alternative(branch_of_id: Any, metadata: Any) -> bool:
    """An estimate branch or a what-if scenario: an alternative, not a chronological revision."""
    return branch_of_id is not None or (isinstance(metadata, dict) and isinstance(metadata.get("scenario"), dict))


async def display_names(session: AsyncSession, user_ids: Iterable[Any]) -> dict[uuid.UUID, str]:
    """Resolve user ids to display names (full name, else email). Unknown ids are left out."""
    ids: set[uuid.UUID] = set()
    for raw in user_ids:
        if raw is None:
            continue
        try:
            ids.add(raw if isinstance(raw, uuid.UUID) else uuid.UUID(str(raw)))
        except (TypeError, ValueError):
            continue
    if not ids:
        return {}
    try:
        from app.modules.users.models import User
    except ImportError:
        return {}
    rows = (await session.execute(select(User.id, User.full_name, User.email).where(User.id.in_(ids)))).all()
    return {r.id: (r.full_name or r.email or "") for r in rows if (r.full_name or r.email)}


def _money(value: float | None) -> Decimal:
    return Decimal(str(value if value is not None else 0)).quantize(Decimal("0.01"))


class RevisionService:
    """Numbering and lineage of formal revisions. Stateless apart from the session."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _header(self, boq_id: uuid.UUID) -> Any:
        return (await self.session.execute(select(*_HEADER).where(BOQ.id == boq_id))).first()

    async def _root(self, boq_id: uuid.UUID) -> Any:
        """Walk up ``parent_estimate_id`` within the project until the lineage root."""
        node = await self._header(boq_id)
        if node is None:
            return None
        seen = {node.id}
        while node.parent_estimate_id is not None and not is_alternative(node.branch_of_id, node.metadata_):
            parent = await self._header(node.parent_estimate_id)
            if parent is None or parent.project_id != node.project_id or parent.id in seen or len(seen) > _MAX_LINEAGE:
                break
            if is_alternative(parent.branch_of_id, parent.metadata_):
                break
            seen.add(parent.id)
            node = parent
        return node

    async def _members(self, root: Any) -> list[Any]:
        """The root and every formal revision below it, oldest first."""
        members = [root]
        frontier = [root.id]
        seen = {root.id}
        while frontier and len(members) < _MAX_LINEAGE:
            stmt = select(*_HEADER).where(BOQ.parent_estimate_id.in_(frontier), BOQ.project_id == root.project_id)
            children = [
                row
                for row in (await self.session.execute(stmt)).all()
                if row.id not in seen and not is_alternative(row.branch_of_id, row.metadata_)
            ]
            seen.update(row.id for row in children)
            members.extend(children)
            frontier = [row.id for row in children]
        # Same-instant rows (one transaction) fall back to their stored number.
        members.sort(
            key=lambda r: (
                r.id != root.id,
                r.created_at or datetime.min,
                stored_number(r.metadata_) if stored_number(r.metadata_) is not None else -1,
                str(r.id),
            )
        )
        return members

    @staticmethod
    def _numbers(members: list[Any], root_id: uuid.UUID) -> list[tuple[int, bool]]:
        """``(number, derived)`` per member, in the members' order."""
        out: list[tuple[int, bool]] = []
        for place, row in enumerate(members):
            if row.id == root_id:
                out.append((0, False))
                continue
            stored = stored_number(row.metadata_)
            out.append((stored, False) if stored is not None else (place, True))
        return out

    async def lineage(self, boq_id: uuid.UUID) -> BOQRevisionLineage:
        """The full formal revision lineage of ``boq_id``, oldest first, with totals and deltas.

        Raises:
            HTTPException 404: the bill does not exist.
        """
        root = await self._root(boq_id)
        if root is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="BOQ not found")
        members = await self._members(root)
        numbers = self._numbers(members, root.id)
        ids = [row.id for row in members]
        totals = await BOQRepository(self.session).grand_totals_for_boqs(ids)
        names = await display_names(self.session, (row.created_by for row in members))
        by_id = {row.id: _money(totals.get(row.id)) for row in members}

        entries: list[BOQRevisionEntry] = []
        for row, (number, derived) in zip(members, numbers, strict=True):
            parent = row.parent_estimate_id if row.id != root.id else None
            total = by_id[row.id]
            entries.append(
                BOQRevisionEntry(
                    boq_id=row.id,
                    number=number,
                    label=revision_label(number),
                    number_is_derived=derived,
                    name=row.name,
                    status=row.status,
                    is_locked=bool(row.is_locked),
                    parent_id=parent,
                    created_at=row.created_at,
                    created_by=row.created_by,
                    created_by_name=names.get(row.created_by) if row.created_by else None,
                    grand_total=total,
                    delta_vs_parent=(total - by_id[parent]) if parent in by_id else None,
                    is_current=row.id == boq_id,
                )
            )
        position = ids.index(boq_id) if boq_id in ids else None
        return BOQRevisionLineage(
            boq_id=boq_id,
            root_id=root.id,
            current_in_lineage=position is not None,
            previous_id=ids[position - 1] if position else None,
            next_id=ids[position + 1] if position is not None and position + 1 < len(ids) else None,
            revisions=entries,
        )

    async def create_revision(self, source_id: uuid.UUID, *, user_id: uuid.UUID | None) -> BOQ:
        """Raise the next formal revision of ``source_id``: deep copy, link, number, name.

        The lineage root row is locked first so two revisions raised at the
        same moment are numbered one after the other, never the same.

        Raises:
            HTTPException 404: the source bill does not exist.
        """
        from app.modules.boq.service import BOQService

        root = await self._root(source_id)
        if root is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="BOQ not found")
        await self.session.execute(select(BOQ.id).where(BOQ.id == root.id).with_for_update())
        source = await self._header(source_id)
        service = BOQService(self.session)
        new_boq = await service.duplicate_boq(source_id)
        new_id = new_boq.id

        members = await self._members(root)
        numbers = [n for n, _ in self._numbers([m for m in members if m.id != new_id], root.id)]
        number = next_revision_number(numbers)
        metadata = dict(new_boq.metadata_) if isinstance(new_boq.metadata_, dict) else {}
        metadata[REVISION_KEY] = {"number": number, "root_id": str(root.id)}
        await service.boq_repo.update_fields(
            new_id,
            name=revision_name(source.name, number),
            parent_estimate_id=source_id,
            status="draft",
            is_locked=False,
            created_by=user_id,
            metadata_=metadata,
        )
        return await service.get_boq(new_id)

    async def rule_block(self, boq_id: uuid.UUID) -> dict[str, Any] | None:
        """The ``revision`` block the validate endpoint hands the boq.revision rules.

        None when the bill does not exist or stands alone (no revision before or after it).
        """
        try:
            lineage = await self.lineage(boq_id)
        except HTTPException:
            return None
        if not lineage.current_in_lineage or len(lineage.revisions) < 2:
            return None
        current = next(e for e in lineage.revisions if e.boq_id == boq_id)
        descendants = self._descendant_labels(lineage, boq_id)
        return {
            "label": current.label,
            "is_locked": current.is_locked,
            "later_labels": [e.label for e in lineage.revisions if e.label in descendants],
        }

    @staticmethod
    def _descendant_labels(lineage: BOQRevisionLineage, boq_id: uuid.UUID) -> set[str]:
        children: dict[uuid.UUID, list[BOQRevisionEntry]] = {}
        for entry in lineage.revisions:
            if entry.parent_id is not None:
                children.setdefault(entry.parent_id, []).append(entry)
        out: set[str] = set()
        stack = [boq_id]
        while stack:
            for child in children.get(stack.pop(), []):
                if child.label not in out:
                    out.add(child.label)
                    stack.append(child.boq_id)
        return out
