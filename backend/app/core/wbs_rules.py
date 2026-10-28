# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠WBS tree check hook: ``projects`` stores the tree, a rules module answers, neither imports the other.

``projects`` brackets a WBS node create or update that does not go through
the design module's own endpoints: :func:`wbs_violations` before the write,
:func:`check_wbs_tree` with that list after it. Only violations the write
introduced refuse it (422, each one listed, the caller's transaction rolled
back by the exception). A tree that already breaks a rule stays editable, so
pinning a design setup on a project with legacy data never locks its editor.

Copy and restore are not checked: they reproduce a tree, they do not introduce
anything into it. With no checker registered nothing changes.

A checker returns the violations of the stored tree, each with ``code``,
``node_id`` and ``value``; that triple is the identity used for the diff.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import HTTPException, status

WbsTreeChecker = Callable[[Any, uuid.UUID], Awaitable[list[dict[str, Any]] | None]]

_CHECKERS: dict[str, WbsTreeChecker] = {}


def register_wbs_checker(name: str, checker: WbsTreeChecker) -> None:
    """Register (or replace, by name) a checker."""
    _CHECKERS[name] = checker


def unregister_wbs_checker(name: str) -> None:
    _CHECKERS.pop(name, None)


def _identity(violation: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(violation.get("code") or ""),
        str(violation.get("node_id") or ""),
        str(violation.get("value") or "").strip().casefold(),
    )


async def wbs_violations(session: Any, project_id: uuid.UUID) -> list[dict[str, Any]]:
    """Every violation the registered checkers find in the stored tree; take it BEFORE a write."""
    out: list[dict[str, Any]] = []
    for checker in list(_CHECKERS.values()):
        out.extend(await checker(session, project_id) or [])
    return out


async def check_wbs_tree(session: Any, project_id: uuid.UUID, *, before: list[dict[str, Any]]) -> None:
    """Refuse a write that added a violation to the tree; raise 422 listing the added ones."""
    known = {_identity(v) for v in before}
    violations = [v for v in await wbs_violations(session, project_id) if _identity(v) not in known]
    if violations:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "code": "wbs_invalid",
                "message_key": "design.errors.wbs_invalid",
                "message": "The work breakdown structure breaks the project's WBS rules",
                "violations": violations,
            },
        )


__all__ = ["WbsTreeChecker", "check_wbs_tree", "register_wbs_checker", "unregister_wbs_checker", "wbs_violations"]
