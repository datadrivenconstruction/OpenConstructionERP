# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Suggest the next WBS code under a section and place a new activity inside it.

A scheduler who adds an activity to a section expects it to carry on that
section's numbering: the third child of ``2.1`` is ``2.1.3``, the next line of
a BOQ-generated section ``01.002`` is ``01.003``. Typing that by hand is where
duplicates and gaps come from, so the create dialog asks for a suggestion and
the service fills the code in when the client leaves it blank.

The rule reads the codes that are already there rather than imposing a
format, because the codes in the wild are not uniform (dotted, zero-padded,
DIN 276 groups, alphanumeric):

* the last sibling by natural order that ends in a number is incremented in
  its trailing number, keeping that number's zero padding;
* with no numbered sibling, the first child of section ``P`` is ``P.1``;
* at the top level with no numbered sibling, the first code is ``1``;
* a section without a code of its own has no sequence to continue, so no
  suggestion is made;
* the result never collides with a code already used in the schedule.

Everything here is pure, so the numbering and the placement are tested
without a database.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Iterable

_TRAILING_NUMBER = re.compile(r"^(.*?)(\d+)$")
_DIGITS = re.compile(r"(\d+)")

# Upper bound on the collision loop. A schedule has at most a few thousand
# codes, so this is never reached in practice; it keeps a pathological input
# from spinning.
_MAX_PROBES = 100_000


def _natural_key(code: str) -> tuple[tuple[int, int | str], ...]:
    """Order codes the way a person reads them: ``2.10`` after ``2.9``."""
    parts: list[tuple[int, int | str]] = []
    for chunk in _DIGITS.split(code):
        if not chunk:
            continue
        parts.append((0, int(chunk)) if chunk.isdigit() else (1, chunk))
    return tuple(parts)


def _bump(code: str) -> str | None:
    """Increment the trailing number of ``code``, keeping its padding."""
    match = _TRAILING_NUMBER.match(code)
    if match is None:
        return None
    head, digits = match.group(1), match.group(2)
    return f"{head}{int(digits) + 1:0{len(digits)}d}"


def next_wbs_code(
    parent_code: str | None,
    sibling_codes: Iterable[str],
    taken: Iterable[str],
    *,
    has_parent: bool,
) -> str:
    """Return the code that continues a section's numbering, or ``""``.

    Args:
        parent_code: The section's own WBS code. Ignored when ``has_parent``
            is false.
        sibling_codes: Codes of the activities already directly under the
            same parent (or at the top level).
        taken: Every code already used in the schedule.
        has_parent: Whether the new activity goes under a section.

    Returns:
        The suggested code, or ``""`` when the section has no code to
        continue from.
    """
    prefix = (parent_code or "").strip()
    if has_parent and not prefix:
        return ""
    used = {c.strip() for c in taken if c and c.strip()}

    numbered = [c.strip() for c in sibling_codes if c and _TRAILING_NUMBER.match(c.strip())]
    if has_parent:
        # Siblings written under the section's own prefix are the sequence to
        # continue; a stray sibling with an unrelated code is not.
        # ``20.1`` starts with ``2`` but is not in section ``2``, hence the
        # check that the prefix ends where a separator begins.
        in_sequence = [
            c for c in numbered if c.startswith(prefix) and len(c) > len(prefix) and not c[len(prefix)].isdigit()
        ]
        numbered = in_sequence or numbered

    if numbered:
        candidate = _bump(max(numbered, key=_natural_key))
    elif has_parent:
        candidate = f"{prefix}.1"
    else:
        candidate = "1"
    if candidate is None:  # pragma: no cover - numbered codes always match
        return ""

    for _ in range(_MAX_PROBES):
        if candidate not in used:
            return candidate
        bumped = _bump(candidate)
        if bumped is None:  # pragma: no cover - candidate always ends in a digit
            return ""
        candidate = bumped
    return ""


Outline = list[tuple[uuid.UUID, uuid.UUID | None, int, str]]
"""``(id, parent_id, sort_order, wbs_code)`` for every activity of a schedule."""


def subtree_ids(root_id: uuid.UUID, outline: Iterable[tuple[uuid.UUID, uuid.UUID | None, int, str]]) -> set[uuid.UUID]:
    """Return ``root_id`` and every activity below it, at any depth."""
    children: dict[uuid.UUID, list[uuid.UUID]] = {}
    for act_id, parent_id, _order, _code in outline:
        if parent_id is not None:
            children.setdefault(parent_id, []).append(act_id)
    seen = {root_id}
    stack = [root_id]
    while stack:
        for child in children.get(stack.pop(), []):
            if child not in seen:
                seen.add(child)
                stack.append(child)
    return seen


def tree_order(outline: Outline) -> list[uuid.UUID]:
    """Return the ids depth first: every activity followed by its children.

    Siblings keep the order every list query uses (``sort_order``, then the
    WBS code read naturally, then the id). A row whose parent is missing is
    a root; rows caught in a parent cycle are appended rather than lost.
    """
    present = {row[0] for row in outline}
    children: dict[uuid.UUID | None, list[tuple[uuid.UUID, uuid.UUID | None, int, str]]] = {}
    for row in outline:
        act_id, parent_id = row[0], row[1]
        key = parent_id if parent_id in present and parent_id != act_id else None
        children.setdefault(key, []).append(row)
    for rows in children.values():
        rows.sort(key=lambda r: (r[2], _natural_key((r[3] or "").strip()), str(r[0])))

    out: list[uuid.UUID] = []
    seen: set[uuid.UUID] = set()

    def visit(act_id: uuid.UUID) -> None:
        stack = [act_id]
        while stack:
            cur = stack.pop()
            if cur in seen:
                continue
            seen.add(cur)
            out.append(cur)
            stack.extend(r[0] for r in reversed(children.get(cur, [])))

    for root in children.get(None, []):
        visit(root[0])
    for row in sorted(outline, key=lambda r: (r[2], str(r[0]))):
        visit(row[0])
    return out


def effective_codes(outline: Outline) -> dict[uuid.UUID, str]:
    """Every activity's own code, or its position in the tree when it has none.

    A section typed without a code still has a place in the outline (the
    third top-level section, the second child of it), and that position is
    the implicit WBS number a scheduler reads off the screen: ``3``, ``3.2``.
    It lets a codeless section hand its children a sequence.
    """
    by_id = {row[0]: row for row in outline}
    siblings: dict[uuid.UUID | None, list[uuid.UUID]] = {}
    for aid in tree_order(outline):
        row = by_id[aid]
        parent = row[1] if row[1] in by_id and row[1] != aid else None
        siblings.setdefault(parent, []).append(aid)
    position = {aid: i + 1 for ids in siblings.values() for i, aid in enumerate(ids)}

    codes: dict[uuid.UUID, str] = {}
    for aid in tree_order(outline):
        row = by_id[aid]
        own = (row[3] or "").strip()
        if own:
            codes[aid] = own
            continue
        parent = row[1] if row[1] in by_id and row[1] != aid else None
        # Tree order visits a parent before its children, so its code is known;
        # a row in a parent cycle falls back to its bare position.
        head = codes.get(parent, "") if parent is not None else ""
        codes[aid] = f"{head}.{position[aid]}" if head else str(position[aid])
    return codes


def effective_code(act_id: uuid.UUID, outline: Outline) -> str:
    """One activity's code as :func:`effective_codes` reads it."""
    return effective_codes(outline).get(act_id, "")


def suggest_code(parent_id: uuid.UUID | None, outline: Outline) -> str:
    """The code a new activity under ``parent_id`` (or at the top) should get.

    Siblings without a code count at their implicit position, so the next
    child after an uncoded ``2.1`` is ``2.2``, not a second ``2.1``.
    """
    codes = effective_codes(outline)
    parent_code = codes.get(parent_id, "") if parent_id is not None else ""
    siblings = [codes[aid] for aid, pid, _o, _c in outline if pid == parent_id]
    return next_wbs_code(
        parent_code,
        siblings,
        [code for _i, _p, _o, code in outline],
        has_parent=parent_id is not None,
    )


def order_with_block_under(block_root: uuid.UUID, new_parent: uuid.UUID | None, outline: Outline) -> list[uuid.UUID]:
    """Return the tree order with ``block_root`` and its subtree last under ``new_parent``.

    Used both for a new activity (a block of one) and for an activity moved
    to another section, which takes its own children along. ``new_parent``
    of None puts the block at the very end of the schedule.

    ``outline`` must already carry ``block_root`` with ``new_parent`` as its
    parent; the caller rejects a parent inside the block beforehand.
    """
    block = subtree_ids(block_root, outline)
    rest = [row for row in outline if row[0] not in block]
    order = tree_order(rest)
    block_order = [aid for aid in tree_order([row for row in outline if row[0] in block]) if aid in block]
    # The block's own root comes first inside it.
    block_order.sort(key=lambda aid: aid != block_root)
    if new_parent is None or new_parent not in {row[0] for row in rest}:
        return order + block_order
    section = subtree_ids(new_parent, rest)
    last = max(i for i, aid in enumerate(order) if aid in section)
    return order[: last + 1] + block_order + order[last + 1 :]


def sort_order_changes(order: list[uuid.UUID], outline: Outline) -> dict[uuid.UUID, int]:
    """Map every id whose ``sort_order`` must change to its new value.

    The new value is the position in ``order``, so a schedule whose rows all
    carry the column default of 0 (older imports and seeds) is renumbered
    once, and after that only the rows that actually moved are written.
    """
    current = {row[0]: row[2] for row in outline}
    return {aid: i for i, aid in enumerate(order) if current.get(aid) != i}
