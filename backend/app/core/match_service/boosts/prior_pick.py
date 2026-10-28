# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Prior-pick boost - reward codes the team already confirmed for this work.

This closes the match learning loop. When an estimator confirms a
catalogue code for a group (saving a :class:`MatchTemplate` to the
library, or simply picking a suggestion the search logged), that choice
becomes durable signal: the next time a group with the same normalized
signature is matched, the code the team trusted before should surface at
the top instead of being re-litigated by cosine similarity alone.

The boost itself is intentionally dumb and DB-free so it stays a pure,
fast, well-tested function on the ranker's hot path. All the reading of
the persisted signals (``MatchTemplate`` + ``MatchSearchLog`` picks) and
the resolution to a live catalogue row happens in the match-elements
service, which owns those tables and holds the group signature. The
service packages the result into a :class:`PriorPickContext` and binds it
for the duration of one ranker call via :func:`bind` / :func:`applied`.

Two strengths of signal are carried:

* **template** - an explicit "save this mapping" confirmation. Strong.
  Matched by the candidate's ``id`` (real ``CostItem.id``) or ``code``.
* **history** - the code the team keeps picking from the suggestions for
  this signature (``MatchSearchLog.picked_rate_code``). Weaker, matched
  by ``code``.

The ranker registers :func:`boost` in its narrow boost stack, so a prior
code gets its score lifted *before* the confidence band is derived - a
previously-confirmed rate reads as high confidence, not a mid-list guess.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from typing import Any

from app.core.match_service.envelope import ElementEnvelope, MatchCandidate


def _env_float(name: str, default: float) -> float:
    """Read a float knob from the environment, falling back on parse error.

    Mirrors the env-override convention the rest of ``match_service`` uses
    for boost weights so operators can retune the prior-pick lift without
    a code deploy.
    """
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


# Additive deltas on the candidate's score (the ranker clamps the sum to
# [0, 1]). The template weight is deliberately large - an explicit prior
# confirmation should dominate a marginal cosine gap - while the history
# weight only nudges ordering, because a picked code is a softer signal
# than a saved mapping.
PRIOR_PICK_TEMPLATE_WEIGHT: float = _env_float("MATCH_BOOST_PRIOR_PICK_TEMPLATE", 0.35)
PRIOR_PICK_HISTORY_WEIGHT: float = _env_float("MATCH_BOOST_PRIOR_PICK_HISTORY", 0.15)

# Boost key surfaced in ``MatchCandidate.boosts_applied`` so the UI's
# explainability panel can render "previously confirmed".
BOOST_KEY: str = "prior_pick"

# Reasons returned by :meth:`PriorPickContext.reason_for`.
REASON_TEMPLATE: str = "template"
REASON_HISTORY: str = "history"


@dataclass(frozen=True)
class PriorPickContext:
    """Resolved prior-pick signal for one group signature.

    Attributes:
        strong: Identifiers (``CostItem.id`` strings and/or rate codes)
            confirmed for this signature through the template library.
            A candidate matching any of these earns the template weight.
        weak: Rate codes the team repeatedly picked from the suggestions
            for this signature. A candidate matching any earns the
            (smaller) history weight.
        exact_code: The single catalogue code to deterministically
            pre-fill for an identical repeated line, or ``None``. Set by
            the caller only when a live, unambiguous prior confirmation
            exists; drives the exact-repeat short-circuit ahead of the
            vector fan-out.
    """

    strong: frozenset[str] = field(default_factory=frozenset)
    weak: frozenset[str] = field(default_factory=frozenset)
    exact_code: str | None = None

    @property
    def is_empty(self) -> bool:
        """True when there is no prior signal to act on."""
        return not self.strong and not self.weak

    def _identifiers(self, candidate: MatchCandidate) -> set[str]:
        ident = {str(candidate.id or "").strip(), str(candidate.code or "").strip()}
        ident.discard("")
        return ident

    def reason_for(self, candidate: MatchCandidate) -> str | None:
        """Classify a candidate against the prior signal.

        Returns ``"template"`` for a strong (explicitly confirmed) match,
        ``"history"`` for a repeatedly-picked code, or ``None`` when the
        candidate carries no prior signal. Strong wins over weak.
        """
        ident = self._identifiers(candidate)
        if not ident:
            return None
        if ident & self.strong:
            return REASON_TEMPLATE
        if ident & self.weak:
            return REASON_HISTORY
        return None


# One active context per async task. ``run_match`` binds a group's context
# around the single ranker call for that group; every other ranker caller
# (ad-hoc /costs search, eval harness) leaves it unset so the boost is a
# no-op there. ContextVars propagate down the awaited call chain, which is
# how the signal reaches the ranker without threading a new argument
# through ``match_envelope`` / ``MatchRequest``.
_ACTIVE: ContextVar[PriorPickContext | None] = ContextVar(
    "match_prior_pick_context",
    default=None,
)


def bind(context: PriorPickContext | None) -> Token[PriorPickContext | None]:
    """Make ``context`` the active prior-pick context. Returns a reset token."""
    return _ACTIVE.set(context)


def reset(token: Token[PriorPickContext | None]) -> None:
    """Restore the previous active context for the given token."""
    _ACTIVE.reset(token)


def active() -> PriorPickContext | None:
    """Return the active prior-pick context, or ``None`` when unbound."""
    return _ACTIVE.get()


@contextmanager
def applied(context: PriorPickContext | None) -> Iterator[None]:
    """Bind ``context`` for the duration of the ``with`` block.

    Convenience wrapper around :func:`bind` / :func:`reset` for callers
    (and tests) that want scoping without juggling the token.
    """
    token = _ACTIVE.set(context)
    try:
        yield
    finally:
        _ACTIVE.reset(token)


def boost(
    envelope: ElementEnvelope,  # noqa: ARG001 - interface symmetry with the boost stack
    candidate: MatchCandidate,
    settings: Any,  # noqa: ARG001 - interface symmetry with the boost stack
) -> dict[str, float]:
    """Lift a candidate the team already confirmed for this kind of work.

    Reads the active :class:`PriorPickContext` (bound by the caller for
    the current ranker call). Returns a single additive delta keyed
    ``prior_pick`` when the candidate matches a prior confirmation, or an
    empty dict otherwise - so groups with no history pay nothing.
    """
    context = _ACTIVE.get()
    if context is None or context.is_empty:
        return {}
    reason = context.reason_for(candidate)
    if reason == REASON_TEMPLATE:
        return {BOOST_KEY: PRIOR_PICK_TEMPLATE_WEIGHT}
    if reason == REASON_HISTORY:
        return {BOOST_KEY: PRIOR_PICK_HISTORY_WEIGHT}
    return {}


def pin_candidates(
    candidates: list[MatchCandidate],
    context: PriorPickContext | None,
) -> list[MatchCandidate]:
    """Reorder so prior-confirmed candidates come first (stable otherwise).

    The ranker's score boost already nudges a prior code up, but a soft
    history nudge can lose to a large cosine gap. This is the belt-and-
    suspenders step run after ranking: strong (template) matches first,
    then history matches, then everything else - each group preserving its
    original relative order. Returns the input list unchanged when there
    is nothing to pin, so the common "no history" path is a cheap no-op.
    """
    if not candidates or context is None or context.is_empty:
        return candidates
    strong_hits: list[MatchCandidate] = []
    weak_hits: list[MatchCandidate] = []
    rest: list[MatchCandidate] = []
    for candidate in candidates:
        reason = context.reason_for(candidate)
        if reason == REASON_TEMPLATE:
            strong_hits.append(candidate)
        elif reason == REASON_HISTORY:
            weak_hits.append(candidate)
        else:
            rest.append(candidate)
    if not strong_hits and not weak_hits:
        return candidates
    return [*strong_hits, *weak_hits, *rest]


__all__ = [
    "BOOST_KEY",
    "PRIOR_PICK_HISTORY_WEIGHT",
    "PRIOR_PICK_TEMPLATE_WEIGHT",
    "REASON_HISTORY",
    "REASON_TEMPLATE",
    "PriorPickContext",
    "active",
    "applied",
    "bind",
    "boost",
    "pin_candidates",
    "reset",
]
