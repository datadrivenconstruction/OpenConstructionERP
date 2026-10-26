# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Optimistic concurrency helpers for offline-first field records​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠.

A phone that worked offline edits a copy of a record. When it syncs, the server
row may have moved on. Every versioned row carries an integer ``version``; the
client states the version it edited (``If-Match`` header or ``version`` in the
body) and the server answers 409 with the current row when that is stale.

Everything here is pure: no session, no I/O. The merge helper works on plain
dicts so the same rules serve a diary note, a punch description and an
inspection checklist.
"""

from __future__ import annotations

import re
from collections.abc import Collection, Iterable
from typing import Any

from fastapi import HTTPException, status

VERSION_CONFLICT_CODE = "version_conflict"
RESOLUTION_SIDES = frozenset({"mine", "theirs", "manual"})
CLIENT_OP_ID_PATTERN = r"^[A-Za-z0-9._:-]{1,64}$"

_IF_MATCH_RE = re.compile(r'^(?:W/)?"?\s*(\d+)\s*"?$')


def parse_if_match(header: str | None) -> int | None:
    """Read a version from an ``If-Match`` header.

    Accepts ``"3"``, ``3`` and ``W/"3"``. ``*`` and an empty header mean "no
    precondition" and give ``None``.

    Raises:
        HTTPException: 400 when the header is present but is not a version.
    """
    if header is None:
        return None
    text = header.strip()
    if not text or text == "*":
        return None
    match = _IF_MATCH_RE.match(text)
    if match is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "invalid_if_match",
                "message": f'If-Match must be a record version such as "3", got {header!r}.',
            },
        )
    return int(match.group(1))


def resolve_expected_version(if_match: str | None, body_version: int | None) -> int | None:
    """Pick the version the client edited: the header, else the body.

    Raises:
        HTTPException: 400 when both are given and disagree.
    """
    from_header = parse_if_match(if_match)
    if from_header is not None and body_version is not None and from_header != body_version:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "invalid_if_match",
                "message": "The If-Match header and the body version name different versions.",
            },
        )
    return from_header if from_header is not None else body_version


def check_version(current: int, expected: int | None, current_payload: dict[str, Any]) -> None:
    """Raise 409 when the client edited a version that is no longer current.

    ``expected=None`` means the client sent no precondition: today's
    last-writer-wins behaviour is kept for older clients.

    Raises:
        HTTPException: 409 with ``code``, ``message``, ``current_version`` and
            the serialized ``current`` row so the client can merge offline.
    """
    if expected is None or expected == current:
        return
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "code": VERSION_CONFLICT_CODE,
            "message": (
                f"This record was changed by someone else (you edited version {expected}, "
                f"the current version is {current}). Review the current values and merge your changes."
            ),
            "current_version": current,
            "current": current_payload,
        },
    )


def bump(obj: Any) -> int:
    """Increment ``obj.version`` and return the new value."""
    new_version = int(getattr(obj, "version", None) or 1) + 1
    obj.version = new_version
    return new_version


def three_way_merge(
    base: dict[str, Any],
    mine: dict[str, Any],
    theirs: dict[str, Any],
    long_text_fields: Collection[str] = frozenset(),
    list_fields: Collection[str] = frozenset(),
) -> dict[str, Any]:
    """Merge two edits of the same record against their common ancestor.

    Per field: when only one side changed it, that change is taken; when both
    changed it to the same value nothing is lost; when both changed a simple
    field differently the last writer (``mine``, the device that syncs now)
    wins. Long-text and list fields changed differently on both sides are not
    guessed: they are reported as conflicts and ``merged`` keeps ``theirs``
    until the person resolves them.

    Returns:
        ``{"merged": dict, "auto_fields": [...], "conflicts": [...]}``.
        ``auto_fields`` lists every field that changed on either side and was
        settled without asking.
    """
    guarded = set(long_text_fields) | set(list_fields)
    merged: dict[str, Any] = {}
    auto: list[str] = []
    conflicts: list[str] = []
    for name in sorted(set(base) | set(mine) | set(theirs)):
        b, m, t = base.get(name), mine.get(name), theirs.get(name)
        mine_changed = m != b
        theirs_changed = t != b
        if not mine_changed and not theirs_changed:
            merged[name] = b
        elif mine_changed and not theirs_changed:
            merged[name] = m
            auto.append(name)
        elif theirs_changed and not mine_changed:
            merged[name] = t
            auto.append(name)
        elif m == t:
            merged[name] = m
            auto.append(name)
        elif name in guarded:
            merged[name] = t
            conflicts.append(name)
        else:
            merged[name] = m
            auto.append(name)
    return {"merged": merged, "auto_fields": auto, "conflicts": conflicts}


def unresolved_conflicts(conflicts: Iterable[str], resolutions: dict[str, str]) -> list[str]:
    """Conflicted fields that have no valid resolution (mine, theirs or manual)."""
    return [name for name in conflicts if resolutions.get(name) not in RESOLUTION_SIDES]
