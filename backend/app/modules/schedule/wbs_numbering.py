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


def subtree_ids(
    root_id: uuid.UUID,
    outline: Iterable[tuple[uuid.UUID, uuid.UUID | None, int, str]],
) -> set[uuid.UUID]:
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


def insert_position_under(
    parent_id: uuid.UUID,
    outline: Iterable[tuple[uuid.UUID, uuid.UUID | None, int, str]],
) -> int:
    """Return the ``sort_order`` that puts a new child last inside its section.

    That is one past the highest ``sort_order`` in the section's subtree, so
    the new row lands after the section's last descendant and before whatever
    follows the section.
    """
    rows = list(outline)
    block = subtree_ids(parent_id, rows)
    return max((order for act_id, _p, order, _c in rows if act_id in block), default=-1) + 1
