# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Deciding which bill of quantities a project-scoped operation acts on.

A bill of quantities is not unique per project. Nothing in the schema
constrains ``project_id`` to one row, the listing endpoint returns a page, and
markups hang off the bill, so two bills on one project are fully independent
records that hold different money. A module that needs "the project's BOQ" is
therefore asking a question that may have no answer, one answer, or several.

Several modules answered it the same wrong way: ``SELECT ... ORDER BY
created_at LIMIT 1``, the oldest bill wins, recorded at most in a log line.
On a project with a single bill that guess is always right, which is why it
survived. On a project with two it is a coin toss that writes real money into
a bill nobody named.

The rule, in one line: an explicit id decides; zero candidates refuses; one
candidate is the answer; several is a question, and a question is refused
rather than guessed.

Two decisions live in that rule and they belong to different people. The
ambiguity part is universal - nothing may guess between two bills. The
candidate *predicate* is the caller's, because "may I use this bill" depends
on what the caller is about to do:

* A caller that mutates the bill passes ``writable=True``, and only unlocked
  bills count. Writing into a locked, approved estimate is itself the defect.
* A caller that only reads the bill passes ``writable=False``, and every bill
  counts. Validating or scheduling from a locked, approved estimate is the
  normal case, not an error, and filtering it out would break every project
  whose only bill has been approved.

This module is deliberately free of module imports at import time: the BOQ
models are pulled in inside the functions, the way ``core.global_search`` and
``core.event_handlers`` already do it, so core does not hard-depend on a
plugin being installed.
"""

import logging
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

#: How many bills a refusal may name back to the caller. The resolver reads
#: two rows because two rows already settle "one candidate or several"; this
#: wider read runs only when a human is about to be asked which bill they
#: meant. Capped so a project carrying a hundred bills turns one error message
#: into a picker rather than a hundred-line wall of text.
MAX_NAMED_BOQ_CANDIDATES = 10

#: Why an operation could not decide which bill it acts on, in the words the
#: API answers with. Every key is something the caller can act on - name a
#: different bill, unlock the one they meant, or choose between the ones they
#: have. The vocabulary matches what the change-order write-back already
#: answers with, so a client that learned these codes on one endpoint reads
#: them the same way on the next.
BOQ_TARGET_REFUSALS: dict[str, str] = {
    "ambiguous_boq": (
        "This project has more than one bill of quantities that could receive this, so it cannot be "
        "placed without guessing which one it belongs in. Try again naming the bill."
    ),
    "no_active_boq": "This project has no bill of quantities to work with. Create one first.",
    "boq_not_found": "The bill of quantities named for this operation does not exist.",
    "boq_project_mismatch": "The bill of quantities named for this operation belongs to a different project.",
    "boq_locked": (
        "The bill of quantities this would be written into is locked, so it cannot receive the change. "
        "Unlock it or name another bill."
    ),
}


class BOQTargetRefused(Exception):
    """A project-scoped operation could not decide which bill it acts on.

    Raised by :func:`require_project_boq` so a caller that has no natural
    ``(value, reason)`` return shape can still refuse loudly instead of
    guessing. ``detail`` is the structured body an API layer answers with.

    Attributes:
        reason: One of the keys of :data:`BOQ_TARGET_REFUSALS`.
        message: The English sentence a person ends up reading.
        candidates: The bills that could have received the operation, as
            ``{"id": ..., "name": ...}`` dicts. Possibly empty - a refusal
            stands with or without a picker.
    """

    def __init__(self, reason: str, candidates: list[dict[str, str]] | None = None) -> None:
        self.reason = reason
        self.message = BOQ_TARGET_REFUSALS.get(reason, BOQ_TARGET_REFUSALS["ambiguous_boq"])
        self.candidates = candidates or []
        super().__init__(self.message)

    @property
    def detail(self) -> dict[str, Any]:
        """Structured refusal body: ``error``, ``message``, ``candidates``.

        ``message`` is what a person ends up reading (the frontend's error
        normaliser lifts ``message`` out of a structured ``detail``) and
        ``error`` is what a client branches on to show its own translated
        wording instead.
        """
        return {"error": self.reason, "message": self.message, "candidates": self.candidates}


async def list_project_boqs(
    session: AsyncSession,
    project_id: uuid.UUID,
    *,
    writable: bool = True,
    limit: int = 2,
) -> list[Any]:
    """Up to ``limit`` bills on ``project_id``, oldest first.

    Args:
        session: Async DB session.
        project_id: Project whose bills are being counted.
        writable: When True, only unlocked bills count - the caller intends
            to mutate whatever comes back. When False, every bill counts.
        limit: Row cap. Two rows already settle "one candidate or several",
            so resolvers pass 2; only the refusal path pays for a wider read.

    Returns:
        The matching ``BOQ`` rows, oldest first.
    """
    from sqlalchemy import select

    from app.modules.boq.models import BOQ

    stmt = select(BOQ).where(BOQ.project_id == project_id)
    # A bill raised for one variation request is not a bill of the project at
    # large, so it is never a candidate for an operation that asked the
    # project which bill it means. Without this a single variation bill turns
    # every previously unambiguous project into ``ambiguous_boq``, which is a
    # refusal where there used to be an answer. Every bill written before
    # Issue #435 has NULL here, so this predicate removes nothing that exists.
    stmt = stmt.where(BOQ.variation_request_id.is_(None), BOQ.branch_of_id.is_(None))
    if writable:
        stmt = stmt.where(BOQ.is_locked.is_(False))
    stmt = stmt.order_by(BOQ.created_at).limit(limit)
    return list((await session.execute(stmt)).scalars().all())


async def resolve_project_boq(
    session: AsyncSession,
    project_id: uuid.UUID,
    boq_id: uuid.UUID | None = None,
    *,
    writable: bool = True,
) -> tuple[Any | None, str | None]:
    """Decide which bill of a project an operation acts on.

    An explicit ``boq_id`` is the whole answer: it is checked against the
    project, and against the lock when the caller intends to write, and then
    used. Without one the project's bills are counted, and the count decides:
    none refuses, one answers, several refuses.

    Args:
        session: Async DB session.
        project_id: Project the operation is scoped to.
        boq_id: Explicitly named bill, or None to let the project decide.
        writable: Whether the caller intends to mutate the bill. See the
            module docstring - this is the caller's decision, not the rule's.

    Returns:
        ``(boq, None)`` when the target is unambiguous and ``(None, reason)``
        when it is not, where ``reason`` is a key of
        :data:`BOQ_TARGET_REFUSALS`. Exactly one of the two is ever set.
    """
    from sqlalchemy import select

    from app.modules.boq.models import BOQ

    if boq_id is not None:
        boq = (await session.execute(select(BOQ).where(BOQ.id == boq_id))).scalar_one_or_none()
        if boq is None:
            return None, "boq_not_found"
        if boq.project_id != project_id:
            return None, "boq_project_mismatch"
        if writable and boq.is_locked:
            return None, "boq_locked"
        return boq, None

    candidates = await list_project_boqs(session, project_id, writable=writable, limit=2)
    if not candidates:
        if writable:
            # "No unlocked bill" and "no bill at all" are different facts and
            # the caller can act on only one of them. Pay for the second query
            # on the refusal path so the answer can say which it is.
            if await list_project_boqs(session, project_id, writable=False, limit=1):
                return None, "boq_locked"
        return None, "no_active_boq"
    if len(candidates) > 1:
        # Deliberately not a count: the query is capped at two rows, so the
        # only honest statement about the population is "more than one".
        logger.warning(
            "Project %s has more than one %s bill of quantities; an operation that names none of them "
            "cannot be placed without guessing",
            project_id,
            "unlocked" if writable else "candidate",
        )
        return None, "ambiguous_boq"
    return candidates[0], None


async def describe_boq_candidates(
    session: AsyncSession,
    project_id: uuid.UUID,
    *,
    writable: bool = True,
    limit: int = MAX_NAMED_BOQ_CANDIDATES,
) -> list[dict[str, str]]:
    """Name the bills that could have received an operation.

    Used to turn a refusal into a picker, so the question can be answered in
    the screen that asked it rather than by looking the ids up elsewhere.
    Failing to build the list is not itself a failure: a refusal stands with
    or without a picker, so a broken read comes back empty rather than
    turning a clear 409 into a 500.
    """
    try:
        rows = await list_project_boqs(session, project_id, writable=writable, limit=limit)
    except Exception:
        logger.warning("Could not list the bills of project %s for a refusal", project_id, exc_info=True)
        return []
    return [{"id": str(row.id), "name": str(getattr(row, "name", "") or "")} for row in rows]


async def require_project_boq(
    session: AsyncSession,
    project_id: uuid.UUID,
    boq_id: uuid.UUID | None = None,
    *,
    writable: bool = True,
    allow_missing: bool = False,
) -> Any | None:
    """Resolve the target bill or raise :class:`BOQTargetRefused`.

    The raising twin of :func:`resolve_project_boq`, for callers whose return
    shape has no room for a reason.

    Args:
        session: Async DB session.
        project_id: Project the operation is scoped to.
        boq_id: Explicitly named bill, or None to let the project decide.
        writable: Whether the caller intends to mutate the bill.
        allow_missing: When True, a project that holds no usable bill returns
            None instead of raising, so a caller whose answer to "no bill" is
            to create one, or to skip quietly, keeps that answer. Ambiguity
            still raises: it is a question, not an absence.

    Returns:
        The resolved ``BOQ``, or None when ``allow_missing`` is set and the
        project holds no usable bill.

    Raises:
        BOQTargetRefused: The target could not be decided.
    """
    boq, reason = await resolve_project_boq(session, project_id, boq_id, writable=writable)
    if boq is not None:
        return boq
    if allow_missing and reason == "no_active_boq":
        return None
    # A lock refusal has to name the locked bill, so the picker for that one
    # reason ignores the writable filter that would hide the only candidate.
    describe_writable = writable and reason != "boq_locked"
    candidates = await describe_boq_candidates(session, project_id, writable=describe_writable)
    raise BOQTargetRefused(reason or "ambiguous_boq", candidates)
