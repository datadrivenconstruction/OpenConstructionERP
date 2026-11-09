# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Plan moving one schedule activity, with its subtree, to a new place in the outline.

A scheduler reorders a programme by moving a line up or down among its siblings
or into another section. The move is planned here on the outline alone (ids,
parents, order, codes), so every rule is tested without a database:

* the activity takes its whole subtree along;
* a section cannot go under itself or one of its own descendants;
* ``sort_order`` is rewritten as the position in the new depth-first order, so
  the shown order is exactly the planned one;
* WBS codes follow the move. Moving into another section gives the activity the
  next free code of that section, and the codes of the siblings of the target
  section are permuted to match the new order when they share one numbering
  stem (``2.1``, ``2.2``, ``2.3``). Descendants keep their prefix relation to
  their section. Siblings with mixed or missing codes are left alone, because
  inventing a format for them would rewrite codes people already quote.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field

from app.modules.schedule.wbs_numbering import (
    Outline,
    _natural_key,
    order_with_block_under,
    subtree_ids,
    suggest_code,
    tree_order,
)

_TRAILING = re.compile(r"^(.*?)(\d+)$")
_SEPARATORS = ".-/"


class MoveError(Exception):
    """A move that is not allowed; ``status`` is the HTTP status the API answers."""

    def __init__(self, message: str, status: int = 422) -> None:
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class MovePlan:
    """The result of planning a move."""

    parent_id: uuid.UUID | None
    order: list[uuid.UUID]
    codes: dict[uuid.UUID, str] = field(default_factory=dict)
    changed: bool = True


def _retag(code: str, old: str, new: str) -> str | None:
    """Rewrite ``code`` from the ``old`` section prefix to ``new``; None when unrelated."""
    if old and code.startswith(old) and len(code) > len(old) and code[len(old)] in _SEPARATORS:
        return new + code[len(old) :]
    return None


def _renumber_siblings(
    siblings: list[uuid.UUID],
    codes: dict[uuid.UUID, str],
) -> dict[uuid.UUID, str]:
    """Permute the siblings' own codes into the new order, or {} when they share no stem."""
    own = [(codes.get(aid) or "").strip() for aid in siblings]
    if len(siblings) < 2 or not all(own) or len(set(own)) != len(own):
        return {}
    stems = set()
    for code in own:
        match = _TRAILING.match(code)
        if match is None:
            return {}
        stems.add(match.group(1))
    if len(stems) != 1:
        return {}
    ascending = sorted(own, key=_natural_key)
    return {aid: new for aid, new in zip(siblings, ascending, strict=True) if new != codes.get(aid)}


def plan_move(
    activity_id: uuid.UUID,
    outline: Outline,
    *,
    target_id: uuid.UUID | None = None,
    position: str | None = None,
    parent_id: uuid.UUID | None = None,
    to_top_level: bool = False,
) -> MovePlan:
    """Plan moving ``activity_id`` next to ``target_id`` or into section ``parent_id``.

    Args:
        activity_id: The activity to move, with everything below it.
        outline: ``(id, parent_id, sort_order, wbs_code)`` of every activity of the schedule.
        target_id: Sibling to place the activity beside (with ``position``).
        position: ``"before"`` or ``"after"`` the target.
        parent_id: Section to move into; the activity becomes its last child.
        to_top_level: Move to the end of the top level instead.

    Returns:
        The new parent, the new depth-first order and the codes that change.

    Raises:
        MoveError: Unknown ids (404), a move under itself or a descendant, or a
            request that names no destination or more than one (422).
    """
    by_id = {row[0]: row for row in outline}
    if activity_id not in by_id:
        raise MoveError("Activity not found in this schedule", 404)
    modes = sum([target_id is not None, parent_id is not None, to_top_level])
    if modes != 1:
        raise MoveError("Give exactly one destination: a target sibling, a section, or the top level")
    if target_id is not None and position not in ("before", "after"):
        raise MoveError("position must be 'before' or 'after' when a target is given")

    block = subtree_ids(activity_id, outline)
    new_parent: uuid.UUID | None
    if target_id is not None:
        if target_id not in by_id:
            raise MoveError("Target activity not found in this schedule", 404)
        if target_id in block:
            raise MoveError("An activity cannot be moved next to itself or one of its own children")
        tparent = by_id[target_id][1]
        new_parent = tparent if tparent in by_id and tparent != target_id else None
    elif parent_id is not None:
        if parent_id not in by_id:
            raise MoveError("Parent activity not found in this schedule", 404)
        if parent_id in block:
            raise MoveError("An activity cannot be moved under itself or one of its own children")
        new_parent = parent_id
    else:
        new_parent = None

    planned: Outline = [(aid, new_parent if aid == activity_id else pid, o, c) for aid, pid, o, c in outline]
    rest = [row for row in planned if row[0] not in block]
    rest_order = tree_order(rest)
    block_rows = [row for row in planned if row[0] in block]
    block_order = tree_order(block_rows)
    block_order.sort(key=lambda aid: aid != activity_id)

    if target_id is None:
        order = order_with_block_under(activity_id, new_parent, planned)
    else:
        if position == "before":
            at = rest_order.index(target_id)
        else:
            section = subtree_ids(target_id, rest)
            at = max(i for i, aid in enumerate(rest_order) if aid in section) + 1
        order = rest_order[:at] + block_order + rest_order[at:]

    current_order = tree_order(list(outline))
    if order == current_order and new_parent == by_id[activity_id][1]:
        return MovePlan(parent_id=new_parent, order=order, changed=False)

    codes = _plan_codes(activity_id, new_parent, by_id, planned, rest, order)
    return MovePlan(parent_id=new_parent, order=order, codes=codes)


def _plan_codes(
    activity_id: uuid.UUID,
    new_parent: uuid.UUID | None,
    by_id: dict[uuid.UUID, tuple[uuid.UUID, uuid.UUID | None, int, str]],
    planned: Outline,
    rest: Outline,
    order: list[uuid.UUID],
) -> dict[uuid.UUID, str]:
    working = {aid: (row[3] or "").strip() for aid, row in by_id.items()}
    original = dict(working)

    def retag_subtree(root: uuid.UUID, new: str) -> None:
        old = working[root]
        if old == new:
            return
        for aid in subtree_ids(root, planned):
            if aid == root:
                continue
            moved = _retag(working[aid], old, new)
            if moved is not None:
                working[aid] = moved
        working[root] = new

    old_parent = by_id[activity_id][1]
    if new_parent != old_parent:
        fresh = suggest_code(new_parent, rest)
        if fresh:
            retag_subtree(activity_id, fresh)

    position = {aid: i for i, aid in enumerate(order)}
    siblings = sorted((row[0] for row in planned if row[1] == new_parent), key=lambda aid: position[aid])
    for aid, new in _renumber_siblings(siblings, working).items():
        retag_subtree(aid, new)

    return {aid: code for aid, code in working.items() if code != original[aid]}
