# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Off-site / Prefab / DfMA production stage machine.

Pure, database-free rules for the linear off-site production lifecycle::

    design -> approved_for_production -> in_production -> qa
           -[QA gate]-> dispatched -> delivered -> installed

The machine encodes only the *rules*; persistence of a unit's current stage is
the caller's responsibility (see ``PrefabService.advance_stage``). It mirrors
the stateless design of :class:`app.core.cde_states.CDEStateMachine`.

The one hard gate is quality: a unit may not be dispatched, delivered or
installed until it has reached the ``qa`` stage. Off-site manufacturing lives
or dies on that check - shipping a volumetric module that never cleared factory
QA is the exact failure this guard exists to prevent.
"""

from __future__ import annotations

from enum import StrEnum


class PrefabStage(StrEnum):
    """Ordered off-site production stages (declaration order == lifecycle order)."""

    DESIGN = "design"
    APPROVED_FOR_PRODUCTION = "approved_for_production"
    IN_PRODUCTION = "in_production"
    QA = "qa"
    DISPATCHED = "dispatched"
    DELIVERED = "delivered"
    INSTALLED = "installed"


class PrefabUnitType(StrEnum):
    """Kind of off-site element a unit represents."""

    POD = "pod"
    PANEL = "panel"
    MODULE = "module"
    SKID = "skid"
    REBAR_CAGE = "rebar_cage"
    VOLUMETRIC = "volumetric"
    OTHER = "other"


# Canonical lifecycle order - the single source of truth for indexing,
# "next stage" and the API-validation regex patterns in schemas.py.
STAGE_ORDER: tuple[str, ...] = tuple(s.value for s in PrefabStage)

# Every recognised unit type, in declaration order.
UNIT_TYPES: tuple[str, ...] = tuple(t.value for t in PrefabUnitType)

# Index of the quality gate. Any stage strictly after QA requires the unit to
# have already reached QA.
_QA_INDEX: int = STAGE_ORDER.index(PrefabStage.QA.value)

# Stages that may only be entered once QA has been passed.
POST_QA_STAGES: frozenset[str] = frozenset(STAGE_ORDER[_QA_INDEX + 1 :])


def stage_index(stage: str) -> int:
    """Return the 0-based lifecycle index of ``stage``, or ``-1`` if unknown."""
    if not isinstance(stage, str):
        return -1
    try:
        return STAGE_ORDER.index(stage.strip().lower())
    except ValueError:
        return -1


def is_known_stage(stage: str) -> bool:
    """Return ``True`` when ``stage`` is one of the seven canonical stages."""
    return isinstance(stage, str) and stage.strip().lower() in STAGE_ORDER


def has_passed_qa(stage: str) -> bool:
    """Return ``True`` when ``stage`` is QA or any later stage (unit cleared QA)."""
    idx = stage_index(stage)
    return idx >= _QA_INDEX


def next_stage(current: str) -> str | None:
    """Return the immediate next stage after ``current``, or ``None`` at the end.

    ``installed`` is terminal, so it yields ``None``. An unknown stage also
    yields ``None`` rather than raising, so this is safe on arbitrary data.
    """
    idx = stage_index(current)
    if idx < 0 or idx >= len(STAGE_ORDER) - 1:
        return None
    return STAGE_ORDER[idx + 1]


def stage_completion_fraction(stage: str) -> float:
    """Return how far through the production lifecycle ``stage`` sits, in ``0..1``.

    Linear over the ordered stages: ``design`` is ``0.0`` (nothing produced yet)
    and ``installed`` is ``1.0`` (fully done), with the intermediate stages
    spaced evenly (``qa`` = ``0.5`` in the seven-stage lifecycle). Used as the
    earned-value multiplier for a unit linked to a BOQ position or assembly - a
    simple, explainable progress proxy rather than a claimed-percent field.

    An unknown stage yields ``0.0`` rather than raising, so this is safe on
    arbitrary data.

    Args:
        stage: The unit's current production stage (case-insensitive).

    Returns:
        A progress fraction in the inclusive range ``0.0`` to ``1.0``.
    """
    idx = stage_index(stage)
    last = len(STAGE_ORDER) - 1
    if idx < 0 or last <= 0:
        return 0.0
    return idx / last


class PrefabStageMachine:
    """Linear, forward-only production stage machine with a QA gate.

    Stateless; encodes the ordering rules only. Two rules are enforced:

    1. **Forward only** - a unit advances to a strictly later stage; backward
       moves and no-op moves are rejected. (Rework loops - QA fail sending a
       unit back to production - are intentionally out of scope for this first
       cut and can be added later as an explicit action.)
    2. **QA gate** - ``dispatched`` / ``delivered`` / ``installed`` can only be
       entered once the unit has reached ``qa``. This is the first-class
       validation the module exists to guarantee.
    """

    def can_advance(self, from_stage: str, to_stage: str) -> tuple[bool, str]:
        """Validate a stage advance.

        Args:
            from_stage: The unit's current stage (case-insensitive).
            to_stage: The desired target stage.

        Returns:
            ``(True, "ok")`` when the advance is allowed, otherwise
            ``(False, "<reason>")`` with a clear, user-facing reason so the
            caller can surface a clean 400 rather than a 500.
        """
        if not is_known_stage(from_stage) or not is_known_stage(to_stage):
            return False, (
                f"Unknown production stage: {from_stage!r} or {to_stage!r}. Allowed stages: {', '.join(STAGE_ORDER)}"
            )

        src = from_stage.strip().lower()
        dst = to_stage.strip().lower()
        src_idx = stage_index(src)
        dst_idx = stage_index(dst)

        if dst_idx == src_idx:
            return False, f"Unit is already at the {src!r} stage"
        if dst_idx < src_idx:
            return False, (
                f"Cannot move a unit backwards from {src!r} to {dst!r}; production stages only advance forward"
            )

        # The quality gate: nothing ships or installs before it clears QA.
        if dst in POST_QA_STAGES and not has_passed_qa(src):
            return False, (
                f"Unit cannot move to {dst!r} before it has passed QA. Advance it to '{PrefabStage.QA.value}' first."
            )

        return True, "ok"

    def allowed_targets(self, from_stage: str) -> list[str]:
        """Return every stage reachable from ``from_stage`` under the rules."""
        return [s for s in STAGE_ORDER if self.can_advance(from_stage, s)[0]]

    def __repr__(self) -> str:
        return "PrefabStageMachine(design -> ... -> qa -[gate]-> dispatched -> delivered -> installed)"


def receipt_allowed(current_stage: str) -> tuple[bool, str]:
    """Whether a unit at ``current_stage`` may be booked in on site by its QR code.

    Only a dispatched unit is on its way; anything earlier has not left the
    yard (or has not passed QA), anything later was already received.
    """
    if current_stage == PrefabStage.DISPATCHED.value:
        return True, ""
    return False, f"Only a dispatched unit can be received; this one is '{current_stage}'"
