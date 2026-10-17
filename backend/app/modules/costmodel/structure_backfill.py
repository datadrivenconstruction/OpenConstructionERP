# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Turn the flat account lists of earlier releases into trees, with no database in sight.

Until 18.7 the spine generator wrote one flat list of accounts per project.
Revision ``v92_costmodel_cost_structure`` adds ``title`` and ``level`` and nests
those lists; the boot repair in :mod:`app.modules.costmodel.repairs` does the
same on installs that heal their schema at boot and never run alembic. Both
call :func:`plan_structure_backfill`, so the two routes cannot disagree about
what an upgraded tree looks like.

Which accounts are nested
-------------------------
Only a group (one project, one standard whose codes nest by shape) in which
every account has no parent AND no title. That is exactly the state an
upgraded install is left in: the four new columns arrive empty, and the old
generator never set a parent. A group in which anybody has set a parent or a
title is a structure somebody already shaped, and the repair runs on every
boot, so guessing into it would undo, at every restart, an account a user put
at the top on purpose. Such a group keeps its parents as they are.

Inside a nested group an account goes under the most specific other account
that covers its code, so ``330`` goes under ``300`` when both exist. Its title
is its name when the name says more than the code, else the title of the code
in the shipped list of that standard, else it stays empty.

Every account, in every group, gets ``level`` recomputed from its parent
chain: the level is derived data and has no other correct value.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

#: Standards whose codes nest by their shape, so a parent can be read off the code.
SHAPE_STANDARDS = frozenset({"din276", "nrm", "masterformat", "uniformat"})


@dataclass(frozen=True, slots=True)
class AccountRow:
    """One stored account, as far as the backfill reads it."""

    id: Any
    project_id: Any
    parent_id: Any
    code: str
    name: str
    title: str
    level: int
    standard: str


def plan_structure_backfill(rows: Iterable[AccountRow]) -> dict[Any, dict[str, object]]:
    """The column values to write, per account id. An empty answer means nothing to do.

    The plan is idempotent by construction: once a group is nested it has
    parents, so it no longer qualifies, and levels already equal to their chain
    produce no update.
    """
    from app.core.code_lists import get_code_list, parent_for, same_code

    rows = list(rows)
    if not rows:
        return {}
    parent_of = {r.id: r.parent_id for r in rows}
    updates: dict[Any, dict[str, object]] = {}

    groups: dict[tuple[Any, str], list[AccountRow]] = {}
    for r in rows:
        std = (r.standard or "").strip().lower()
        if std in SHAPE_STANDARDS:
            groups.setdefault((r.project_id, std), []).append(r)
    for (_, std), members in groups.items():
        if any(m.parent_id is not None or (m.title or "").strip() for m in members):
            continue
        by_code = {m.code: m.id for m in members}
        codes = list(by_code)
        code_list = get_code_list(std)
        for m in members:
            parent_code = parent_for(m.code, codes)
            if parent_code is not None and by_code[parent_code] != m.id:
                parent_of[m.id] = by_code[parent_code]
                updates.setdefault(m.id, {})["parent_id"] = by_code[parent_code]
            name = (m.name or "").strip()
            title = ""
            if name and not same_code(name, m.code):
                title = name
            else:
                entry = code_list.find(m.code) if code_list is not None else None
                title = entry.title if entry is not None else ""
            if title:
                updates.setdefault(m.id, {})["title"] = title[:255]

    for r in rows:
        depth, current, seen = 1, parent_of.get(r.id), {r.id}
        while current is not None and current not in seen and current in parent_of:
            seen.add(current)
            depth += 1
            current = parent_of.get(current)
        if r.level != depth:
            updates.setdefault(r.id, {})["level"] = depth
    return updates
