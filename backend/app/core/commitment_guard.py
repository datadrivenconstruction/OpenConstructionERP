# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The commitment guard: one call a document module makes before it binds money.

A module that creates or increases a commitment (award, contract activation or
value change, PO approval or issue, change or variation approval, contingency
drawdown) calls::

    verdict = await commitment_guard.enforce(
        session, project_id=..., kind="purchase_order", document_id=po.id,
        new_amount=Decimal(...), currency="EUR", actor_id=user_id,
    )

and attaches ``verdict.as_dict()`` to its response when ``verdict.result ==
"warn"``. ``enforce`` raises a 409 with code ``commitment_not_released`` (or
``commitment_not_in_matrix``) when the project's matrix is set to ``block``.

A change that is not linked itself but adds to a document that is (a change
order or variation on a contract) passes ``parent_kind`` / ``parent_id``: its
``new_amount`` is then checked as an addition on top of what the parent's item
already commits. ``gross_amount`` is passed where a document knows both and the
schedule may count gross.

The same owner may also answer :func:`change_threshold`: the amount above which
a change needs more than the lowest approval tier. A module with its own fixed
"high value" constant asks it and keeps the constant when the answer is None
(no matrix on the project).

The module that owns the matrix registers the checker on startup, together
with a provider of the project's enforcement mode. When the module is absent or
disabled, nothing is registered and every check answers ``ok``: no behaviour
change for an install without the matrix.

A checker that raises does not answer ``ok``. The mode provider is asked what
the project enforces: under ``block`` the answer is ``block`` with the code
``commitment_guard_unavailable`` (a project that refuses unreleased commitments
must not bind money because the check itself broke), under ``warn`` it is a
``warn`` with the same code, and a project with enforcement off or without a
matrix gets ``ok``. When the mode cannot be read either, the answer is
``block``: nothing is known about the project, and letting the write through
would be a guess.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

logger = logging.getLogger(__name__)

RESULTS = ("ok", "warn", "block")


@dataclass(frozen=True)
class GuardVerdict:
    """The answer for one document: ``ok``, ``warn`` or ``block``, with coded reasons."""

    result: str = "ok"
    reasons: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    item_id: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {"result": self.result, "reasons": list(self.reasons), "item_id": self.item_id}


Checker = Callable[..., Awaitable[GuardVerdict]]
_CHECKER: dict[str, Checker] = {}
ThresholdProvider = Callable[..., Awaitable["Decimal | None"]]
_THRESHOLD: dict[str, ThresholdProvider] = {}
ModeProvider = Callable[..., Awaitable["str | None"]]
_MODE: dict[str, ModeProvider] = {}

UNAVAILABLE = "commitment_guard_unavailable"


def register_commitment_guard(checker: Checker, mode_of: ModeProvider | None = None) -> None:
    """Install the checker (idempotent; the last registration wins).

    ``mode_of(session, project_id=...)`` answers the project's enforcement (``off``, ``warn``,
    ``block``, or None without a matrix). It is asked only when the checker raises.
    """
    _CHECKER["default"] = checker
    if mode_of is None:
        _MODE.pop("default", None)
    else:
        _MODE["default"] = mode_of


def unregister_commitment_guard() -> None:
    """Remove the checker (tests, module disabled)."""
    _CHECKER.pop("default", None)
    _MODE.pop("default", None)


@asynccontextmanager
async def _savepoint(session: Any) -> AsyncIterator[None]:
    """A savepoint around a question to the matrix, where the session has savepoints.

    The savepoint keeps a failed question from poisoning the caller's transaction. A session
    without them (the in-memory doubles other modules' unit tests bind money on) has no
    transaction to protect, so the question is simply asked: a project without a matrix then
    answers ``ok`` exactly as it did before the guard existed, where failing to open a savepoint
    used to read as a broken check and refuse.
    """
    begin = getattr(session, "begin_nested", None)
    if begin is None:
        yield
        return
    async with begin():
        yield


async def _when_the_checker_failed(session: Any, project_id: uuid.UUID) -> GuardVerdict:
    """The verdict for a check that could not be made, by what the project enforces."""
    reasons = ({"code": UNAVAILABLE},)
    provider = _MODE.get("default")
    if provider is None:
        return GuardVerdict(result="block", reasons=reasons)
    try:
        async with _savepoint(session):
            mode = await provider(session, project_id=project_id)
    except Exception:
        logger.exception("commitment guard: enforcement of project %s could not be read; refusing", project_id)
        return GuardVerdict(result="block", reasons=reasons)
    if mode == "block":
        return GuardVerdict(result="block", reasons=reasons)
    if mode == "warn":
        return GuardVerdict(result="warn", reasons=reasons)
    return GuardVerdict()


def register_change_threshold(provider: ThresholdProvider) -> None:
    """Install the change-threshold provider (idempotent; the last registration wins)."""
    _THRESHOLD["default"] = provider


def unregister_change_threshold() -> None:
    _THRESHOLD.pop("default", None)


async def change_threshold(session: Any, *, project_id: uuid.UUID, currency: str) -> Decimal | None:
    """The project's change threshold in ``currency``; None when there is no provider, no matrix or no rate."""
    provider = _THRESHOLD.get("default")
    if provider is None:
        return None
    try:
        async with _savepoint(session):
            return await provider(session, project_id=project_id, currency=currency)
    except Exception:
        logger.exception("change threshold failed for project %s; the module constant applies", project_id)
        return None


async def check(
    session: Any,
    *,
    project_id: uuid.UUID,
    kind: str,
    document_id: uuid.UUID | None,
    new_amount: Decimal,
    currency: str,
    actor_id: uuid.UUID | str | None = None,
    parent_kind: str | None = None,
    parent_id: uuid.UUID | None = None,
    gross_amount: Decimal | None = None,
) -> GuardVerdict:
    """Ask the registered checker; ``ok`` when there is none. A failing checker never reads as ``ok``
    on a project that enforces: see the module docstring."""
    checker = _CHECKER.get("default")
    if checker is None:
        return GuardVerdict()
    try:
        async with _savepoint(session):
            return await checker(
                session,
                project_id=project_id,
                kind=kind,
                document_id=document_id,
                new_amount=new_amount,
                currency=currency,
                actor_id=actor_id,
                parent_kind=parent_kind,
                parent_id=parent_id,
                gross_amount=gross_amount,
            )
    except Exception:
        logger.exception("commitment guard failed for %s %s", kind, document_id)
        return await _when_the_checker_failed(session, project_id)


async def enforce(session: Any, **kwargs: Any) -> GuardVerdict:
    """:func:`check`, raising HTTP 409 on ``block``."""
    verdict = await check(session, **kwargs)
    if verdict.result == "block":
        from fastapi import HTTPException

        code = verdict.reasons[0]["code"] if verdict.reasons else "commitment_not_released"
        raise HTTPException(
            status_code=409,
            detail={"code": code, "message_key": f"commitment.errors.{code}", "guard": verdict.as_dict()},
        )
    return verdict
