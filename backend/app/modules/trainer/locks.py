# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The lock ids a course may name in ``tasks[].opens``.

This is the single list both sides share. The frontend mirror is
``frontend/src/features/trainer/lockRegistry.ts``; a parity test on each side
reads the other file and fails when the two lists differ, so a lock id added
here and not there (or the reverse) is caught before it ships.

A lock id says which part of the ERP a passed task opens:

* ``module`` - a whole module route (``/bid-management``, ``/variations``);
* ``panel`` - one panel inside a page that stays open (the BOQ markups panel);
* ``tab`` - one tab of a module page (contract progress claims);
* ``badge`` - no screen at all, the course badge earned by the last task.

Badge ids are not listed one by one: any ``badge:<course id>`` is valid. Any
other value in a course's ``opens`` is a loader ERROR, never a silent pass.

Data only. Nothing here reads the database or the request.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

LockKind = Literal["module", "panel", "tab", "badge"]

#: Prefix of the one open-ended family of lock ids: ``badge:<course id>``.
BADGE_PREFIX = "badge:"


@dataclass(frozen=True, slots=True)
class LockSpec:
    """One lock id and what it closes.

    Attributes:
        lock_id: The value a course writes in ``tasks[].opens``.
        kind: What the lock hides in the UI.
        module: The backend manifest name whose screens the lock covers.
            Module APIs are never blocked by a lock; the name is used to map
            ERP events back to the lock and for the course map labels.
    """

    lock_id: str
    kind: LockKind
    module: str


#: Every fixed lock id, in the order the courses open them.
LOCKS: tuple[LockSpec, ...] = (
    LockSpec("boq.markups_panel", "panel", "oe_boq"),
    LockSpec("bid_management", "module", "oe_bid_management"),
    LockSpec("contracts.progress_claims", "tab", "oe_contracts"),
    LockSpec("contracts", "module", "oe_contracts"),
    LockSpec("variations", "module", "oe_variations"),
)

#: The fixed lock ids alone, for membership checks.
LOCK_IDS: frozenset[str] = frozenset(spec.lock_id for spec in LOCKS)

_BY_ID: dict[str, LockSpec] = {spec.lock_id: spec for spec in LOCKS}


def is_badge_lock_id(value: str) -> bool:
    """True for ``badge:<course id>`` with a non-empty course id."""
    return value.startswith(BADGE_PREFIX) and len(value) > len(BADGE_PREFIX)


def is_known_lock_id(value: str) -> bool:
    """True when a course may write ``value`` in ``tasks[].opens``."""
    return value in LOCK_IDS or is_badge_lock_id(value)


def lock_kind(value: str) -> LockKind | None:
    """The kind of a lock id, or None when the id is not known."""
    if is_badge_lock_id(value):
        return "badge"
    spec = _BY_ID.get(value)
    return spec.kind if spec is not None else None
