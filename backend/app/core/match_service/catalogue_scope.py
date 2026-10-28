# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The catalogue a match run was told to use, scoped to that run.

The /match-elements wizard lets the user pick a catalogue for a session.
The ranker reads the project's match settings, so without this scope the
pick was stored on the session and never reached the search. A
``ContextVar`` carries it down the awaited call chain for the length of
one run, the same way :mod:`app.core.match_service.boosts.prior_pick`
carries the prior-pick context, and leaves the project's binding alone.
"""

from __future__ import annotations

import uuid
from contextvars import ContextVar, Token

_ACTIVE: ContextVar[str | None] = ContextVar("match_catalogue_scope", default=None)
# The user a run matches for. Decides which imported catalogues (user-owned
# price lists indexed for Match) the ranker may search; ``None`` searches none.
_CALLER: ContextVar[uuid.UUID | None] = ContextVar("match_caller", default=None)


def bind(catalogue_id: str | None) -> Token[str | None]:
    """Make ``catalogue_id`` the catalogue for the current run."""
    value = (catalogue_id or "").strip() or None
    return _ACTIVE.set(value)


def reset(token: Token[str | None]) -> None:
    """Restore the scope that was active before :func:`bind`."""
    _ACTIVE.reset(token)


def current() -> str | None:
    """The catalogue bound for this run, or ``None`` to use the project's."""
    return _ACTIVE.get()


def bind_caller(user_id: uuid.UUID | None) -> Token[uuid.UUID | None]:
    """Make ``user_id`` the user the current run matches for."""
    return _CALLER.set(user_id)


def reset_caller(token: Token[uuid.UUID | None]) -> None:
    """Restore the caller that was active before :func:`bind_caller`."""
    _CALLER.reset(token)


def caller() -> uuid.UUID | None:
    """The user the current run matches for, ``None`` when nobody bound one."""
    return _CALLER.get()


__all__ = ["bind", "bind_caller", "caller", "current", "reset", "reset_caller"]
