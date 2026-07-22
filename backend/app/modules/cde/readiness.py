# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Pure CDE go-live readiness checklist + readiness score.

Standing up a common data environment is not "switch it on"; ISO 19650 asks a
team to agree a handful of things up front and then actually exercise the
workflow before the CDE can be trusted as the single source of truth. Teams that
skip that end up with a shared folder wearing a CDE badge: containers all stuck
in WIP, no suitability discipline, no signed approvals, no version history. This
engine answers one concrete question for a single project - given what the
project has ACTUALLY done in its CDE, how ready is it to go live, and what are
the next few things to fix?

The model is a transparent, ordered checklist, not a black box. There is a
built-in catalogue of readiness signals (:data:`READINESS_SIGNALS`), each naming
a milestone on the "stand up a CDE properly" path: containers exist, structured
naming is in use, suitability codes are assigned, work has moved out of WIP into
the shared area, at least one container has been approved into the published
state, gate crossings carry a sign-off, and revisions are being versioned. The
integrator observes the project's real container/transition state, projects it
onto the SET of signal keys that are satisfied, and this engine reports which
signals are met, a weighted readiness score, a coarse readiness level, and the
leading unmet signals as a "do these next" nudge.

Honesty rules, same spirit as :mod:`app.modules.value.adoption_checklist`:

* A signal is met only when the integrator observed its key; an unrecognised key
  matches nothing, so readiness is never invented.
* The score is a weighted percent of met signals out of ALL catalogue signals -
  readiness is measured against the whole go-live path, so a project cannot look
  "ready" by doing only the two cheapest steps.
* Weights lean towards the milestones that actually prove the workflow runs
  (a container reaching the published state, a signed gate crossing) rather than
  metadata hygiene, without letting any single signal dominate.

No database, no ORM, no ``app.*`` imports - stdlib only, so this runs on the
local Python 3.11 test runner exactly like the other pure engines. The thin
service layer (written separately) reads the CDE tables, derives the observed
signal keys, and calls in here. Nothing here is money, so there is no Decimal
arithmetic; the only number produced is an integer percent in ``[0, 100]``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

# --------------------------------------------------------------------------- #
# How many unmet signals :func:`evaluate` surfaces as "do these next". Three is
# enough to give direction without dumping the whole remaining backlog on a team
# that has only just created its first container.
# --------------------------------------------------------------------------- #

#: Default cap on the next-actions nudge.
DEFAULT_NEXT_ACTIONS = 3


@dataclass(frozen=True)
class ReadinessSignal:
    """One milestone on the CDE go-live path.

    ``key`` is a stable, opaque identifier the service uses to line a signal up
    with whether the project has satisfied it. ``label`` is a short human
    description. ``weight`` is the signal's contribution to the readiness score
    (a heavier signal proves more of the workflow); it is floored at zero when
    scoring. ``hint`` is the concrete next step shown when the signal is unmet.
    """

    key: str
    label: str
    weight: int
    hint: str


@dataclass(frozen=True)
class ReadinessSignalStatus:
    """A signal paired with whether the project has satisfied it."""

    signal: ReadinessSignal
    done: bool


@dataclass(frozen=True)
class CdeReadiness:
    """One project's CDE readiness picture.

    ``signals`` is one :class:`ReadinessSignalStatus` per catalogue signal, in
    catalogue order. ``score`` is the weighted percent of met signals, an integer
    in ``[0, 100]``. ``level`` is a coarse band derived from the score (see
    :func:`readiness_level`). ``next_actions`` is the leading unmet signals in
    catalogue order, capped (see :data:`DEFAULT_NEXT_ACTIONS`).
    """

    signals: tuple[ReadinessSignalStatus, ...]
    score: int
    level: str
    next_actions: tuple[ReadinessSignal, ...]


# --------------------------------------------------------------------------- #
# The built-in readiness catalogue. Ordered as a team naturally stands a CDE up:
# create containers, apply a structured naming scheme, add status/purpose
# discipline (suitability + classification), then exercise the workflow itself -
# move work out of WIP, approve something into the published state, sign the gate
# crossings, and keep revisions versioned - finishing with the full lifecycle.
# Weights sit heaviest on the signals that prove the workflow actually runs
# (a published container, a signed gate) rather than on metadata being present.
# --------------------------------------------------------------------------- #

READINESS_SIGNALS: tuple[ReadinessSignal, ...] = (
    ReadinessSignal(
        key="containers_created",
        label="Information containers created",
        weight=2,
        hint="Add your first document containers so the CDE holds real work.",
    ),
    ReadinessSignal(
        key="structured_naming",
        label="Structured naming in use",
        weight=2,
        hint="Give containers an originator and breakdown code, not just a free-text title.",
    ),
    ReadinessSignal(
        key="suitability_assigned",
        label="Suitability codes assigned",
        weight=2,
        hint="Tag containers with a suitability code so their status and purpose are explicit.",
    ),
    ReadinessSignal(
        key="classification_used",
        label="Classification applied",
        weight=1,
        hint="Classify containers so information can be found and reported by system.",
    ),
    ReadinessSignal(
        key="shared_reached",
        label="Work shared beyond WIP",
        weight=2,
        hint="Move a checked container out of WIP into the shared area (Gate A).",
    ),
    ReadinessSignal(
        key="published_reached",
        label="A container published",
        weight=3,
        hint="Approve a shared container into the published state (Gate B).",
    ),
    ReadinessSignal(
        key="gate_signed",
        label="Gate crossings signed off",
        weight=2,
        hint="Record an approver signature when promoting a container so sign-off is accountable.",
    ),
    ReadinessSignal(
        key="revision_controlled",
        label="Revisions versioned",
        weight=2,
        hint="Issue more than one revision of a container so change history is kept.",
    ),
    ReadinessSignal(
        key="lifecycle_archived",
        label="Full lifecycle exercised",
        weight=1,
        hint="Archive a superseded container so the whole WIP-to-archive path is proven.",
    ),
)


def signal_keys(catalogue: Sequence[ReadinessSignal] = READINESS_SIGNALS) -> tuple[str, ...]:
    """The keys of *catalogue*, in order. Handy for the service and tests."""
    return tuple(s.key for s in catalogue)


def readiness_level(score: int) -> str:
    """Coarse band for *score*.

    ``not_started`` when nothing is met, then ``forming`` / ``operational`` /
    ``mature`` as the workflow is progressively exercised. Bands are deliberately
    wide so the level is a stable headline while the score moves.
    """
    if score <= 0:
        return "not_started"
    if score < 50:
        return "forming"
    if score < 85:
        return "operational"
    return "mature"


def _weighted_score(statuses: Sequence[ReadinessSignalStatus]) -> int:
    """Weighted percent of *statuses* that are met, an int in ``[0, 100]``.

    The denominator is the total weight of every catalogue signal and the
    numerator is the weight of the met ones, so a heavier milestone moves the
    score more. Each weight is floored at zero (a negative weight would be a
    misconfiguration and must never subtract from readiness). With zero total
    weight the score is 0 rather than a divide-by-zero. Rounded to the nearest
    integer.
    """
    total = 0
    done = 0
    for status in statuses:
        w = status.signal.weight if status.signal.weight > 0 else 0
        total += w
        if status.done:
            done += w
    if total <= 0:
        return 0
    return round(done * 100 / total)


def evaluate(
    observed_keys: frozenset[str],
    catalogue: Sequence[ReadinessSignal] = READINESS_SIGNALS,
    *,
    next_actions_limit: int = DEFAULT_NEXT_ACTIONS,
) -> CdeReadiness:
    """Evaluate one project's CDE readiness against *observed_keys*.

    Marks each catalogue signal met when its key is in *observed_keys*, computes
    the weighted readiness score and its level, and collects the leading unmet
    signals - in catalogue order - as the next-actions nudge, capped at
    *next_actions_limit*.

    A key outside the catalogue matches nothing, so unrelated state never
    inflates readiness. The computation is pure and deterministic: identical
    inputs always yield an identical result.
    """
    statuses = tuple(
        ReadinessSignalStatus(signal=s, done=s.key in observed_keys) for s in catalogue
    )
    score = _weighted_score(statuses)
    level = readiness_level(score)

    limit = next_actions_limit if next_actions_limit > 0 else 0
    unmet = tuple(status.signal for status in statuses if not status.done)
    next_actions = unmet[:limit]

    return CdeReadiness(
        signals=statuses,
        score=score,
        level=level,
        next_actions=next_actions,
    )


__all__ = [
    "DEFAULT_NEXT_ACTIONS",
    "READINESS_SIGNALS",
    "ReadinessSignal",
    "ReadinessSignalStatus",
    "CdeReadiness",
    "signal_keys",
    "readiness_level",
    "evaluate",
]
