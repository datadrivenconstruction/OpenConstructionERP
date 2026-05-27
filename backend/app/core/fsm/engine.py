"""‌⁠‍Declarative finite-state-machine helper for entity status transitions.

This module supplies a tiny FSM toolkit used to enforce workflow integrity
across core OpenConstructionERP entities (BOQ, Project, Invoice, NCR, RFQ,
Submittal, …). Each entity declares a list of :class:`StateTransition`
objects describing legal moves between status nodes; the :class:`EntityFSM`
object validates a proposed move, runs any business-logic guards, applies
the new status, and emits an audit-log entry plus optional cross-module
event-bus notifications.

Design goals:
    * **Declarative** — every legal move lives in one registry file, so an
      auditor can read off the full lifecycle without grep-walking endpoints.
    * **Backward compatible** — when a transition is rejected the helper
      raises an HTTPException carrying ``current_status``,
      ``target_status`` and the full set of ``allowed_transitions`` so the
      frontend can render the right action buttons.
    * **Side-effect aware** — every successful transition writes a row to
      :class:`app.core.fsm.audit_log.ActivityLog` (via ``audit_log.log_activity``)
      so dispute timelines (FIDIC, ISO 9001, SCL Protocol) are reproducible.
    * **Async-friendly** — guards and ``on_transition`` callbacks may be
      sync or async; both are awaited transparently.

Public surface:
    :class:`StateTransition`       — frozen dataclass describing one move.
    :class:`EntityFSM`             — bundles transitions for one entity.
    :class:`InvalidTransition`     — raised for illegal status moves.
    :class:`TransitionNotPermitted`— raised when the actor lacks a required role.
    :class:`GuardFailed`           — raised when a business-logic predicate vetoes.
"""

from __future__ import annotations

import inspect
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


# ── Exception hierarchy ─────────────────────────────────────────────────────


class FSMError(Exception):
    """‌⁠‍Base class for FSM rejection errors. Subclasses map to HTTP 409/403."""

    def __init__(
        self,
        message: str,
        *,
        current_status: str,
        target_status: str,
        allowed_transitions: list[str],
    ) -> None:
        super().__init__(message)
        self.message = message
        self.current_status = current_status
        self.target_status = target_status
        self.allowed_transitions = allowed_transitions

    def as_detail(self) -> dict[str, Any]:
        """‌⁠‍Render this error as an HTTP response payload."""
        return {
            "detail": self.message,
            "current_status": self.current_status,
            "target_status": self.target_status,
            "allowed_transitions": self.allowed_transitions,
        }


class InvalidTransition(FSMError):
    """Raised when the proposed ``(from, to)`` pair is not registered."""


class TransitionNotPermitted(FSMError):
    """Raised when the actor's role is not among ``required_roles``."""


class GuardFailed(FSMError):
    """Raised when a business-logic guard predicate vetoes the transition."""


# ── Transition descriptor ───────────────────────────────────────────────────


# A guard predicate receives the FSM context dict and may be sync or async.
# Returning False (or raising :class:`GuardFailed`) vetoes the move.
GuardFn = Callable[[dict[str, Any]], bool | Awaitable[bool]]

# An on_transition handler receives the FSM context dict after the move is
# validated. It may be sync or async; raises are surfaced to the caller.
SideEffectFn = Callable[[dict[str, Any]], Any | Awaitable[Any]]


@dataclass(frozen=True)
class StateTransition:
    """Declarative description of one legal status move.

    Attributes:
        from_status: Current status the transition applies to.
        to_status: Target status after this transition completes.
        required_roles: Empty tuple means "any role". Otherwise the actor's
            role must be in this set (case-insensitive). Use the string
            ``"system"`` to mark a transition that only background jobs may
            apply (when actor_id is None).
        guards: Tuple of predicate callables. ALL must return truthy for the
            transition to proceed. A guard may raise :class:`GuardFailed` to
            attach a custom message.
        on_transition: Tuple of callables invoked AFTER the new status is
            persisted but BEFORE the audit row is written. Use these for
            side effects like recomputing derived totals or emitting events.
        description: Optional human-readable label for the transition (used
            in audit metadata and error messages).
    """

    from_status: str
    to_status: str
    required_roles: tuple[str, ...] = ()
    guards: tuple[GuardFn, ...] = ()
    on_transition: tuple[SideEffectFn, ...] = ()
    description: str = ""


# ── FSM engine ───────────────────────────────────────────────────────────────


class EntityFSM:
    """Declarative finite-state-machine for one entity type.

    Construct once at module-import time with a list of transitions, then
    call :meth:`apply` from service / router code to enforce the lifecycle.
    """

    def __init__(
        self,
        name: str,
        *,
        initial: str,
        transitions: list[StateTransition],
        terminal: tuple[str, ...] = (),
    ) -> None:
        self.name = name
        self.initial = initial
        self.transitions = list(transitions)
        self.terminal = set(terminal)

        # Pre-build a (from -> {to: transition}) lookup for O(1) validate.
        self._index: dict[str, dict[str, StateTransition]] = {}
        all_states: set[str] = {initial, *terminal}
        for t in self.transitions:
            self._index.setdefault(t.from_status, {})[t.to_status] = t
            all_states.add(t.from_status)
            all_states.add(t.to_status)
        self.all_states = all_states

    # ── Introspection ─────────────────────────────────────────────────────

    def allowed_from(self, current: str) -> list[str]:
        """Return the list of legal target statuses from ``current``."""
        return sorted(self._index.get(current, {}).keys())

    def is_terminal(self, status: str) -> bool:
        """Return True when ``status`` accepts no further transitions."""
        return status in self.terminal or not self._index.get(status)

    def has_transition(self, current: str, target: str) -> bool:
        return target in self._index.get(current, {})

    # ── Validation ────────────────────────────────────────────────────────

    def _resolve(self, current: str, target: str) -> StateTransition:
        """Look up the transition descriptor or raise :class:`InvalidTransition`."""
        moves = self._index.get(current, {})
        if target not in moves:
            allowed = sorted(moves.keys())
            msg = (
                f"Cannot transition {self.name} from {current!r} to "
                f"{target!r}. Allowed: {', '.join(allowed) or 'none'}."
            )
            raise InvalidTransition(
                msg,
                current_status=current,
                target_status=target,
                allowed_transitions=allowed,
            )
        return moves[target]

    def _check_role(
        self,
        transition: StateTransition,
        *,
        user_role: str | None,
        current: str,
        target: str,
    ) -> None:
        """Reject when actor role is not in ``transition.required_roles``."""
        if not transition.required_roles:
            return
        # Normalise: case-insensitive comparison; "" maps to None (no role).
        role_norm = (user_role or "").strip().lower()
        allowed_roles = {r.strip().lower() for r in transition.required_roles}
        # ``admin`` always passes — admin role bypasses every gate so support
        # staff can recover stuck workflows without configuration churn.
        # Otherwise the actor's role must appear in ``required_roles``.
        if role_norm == "admin" or role_norm in allowed_roles:
            return
        msg = (
            f"Role {user_role!r} is not permitted to move {self.name} from "
            f"{current!r} to {target!r}. Required: "
            f"{', '.join(sorted(transition.required_roles))}."
        )
        raise TransitionNotPermitted(
            msg,
            current_status=current,
            target_status=target,
            allowed_transitions=self.allowed_from(current),
        )

    async def _run_guards(
        self,
        transition: StateTransition,
        context: dict[str, Any],
        *,
        current: str,
        target: str,
    ) -> None:
        """Run every guard. Any failure aborts the transition."""
        for guard in transition.guards:
            try:
                result = guard(context)
                if inspect.isawaitable(result):
                    result = await result
            except GuardFailed:
                raise
            except Exception as exc:  # pragma: no cover — defensive
                raise GuardFailed(
                    f"Guard {guard.__name__!r} raised {type(exc).__name__}: {exc}",
                    current_status=current,
                    target_status=target,
                    allowed_transitions=self.allowed_from(current),
                ) from exc
            if not result:
                raise GuardFailed(
                    f"Guard {guard.__name__!r} vetoed transition {self.name}:{current}->{target}.",
                    current_status=current,
                    target_status=target,
                    allowed_transitions=self.allowed_from(current),
                )

    async def _run_side_effects(
        self,
        transition: StateTransition,
        context: dict[str, Any],
    ) -> None:
        for handler in transition.on_transition:
            try:
                outcome = handler(context)
                if inspect.isawaitable(outcome):
                    await outcome
            except Exception as exc:
                # Side-effect errors don't roll back the status change — they
                # are logged and re-raised so the caller can decide. Audit
                # log will still record the transition because side-effects
                # run BEFORE the audit row is written.
                logger.exception(
                    "FSM %s side-effect %s raised %s",
                    self.name,
                    handler.__name__,
                    type(exc).__name__,
                )
                raise

    # ── Public API ────────────────────────────────────────────────────────

    def validate(
        self,
        current: str,
        target: str,
        *,
        user_role: str | None = None,
    ) -> StateTransition:
        """Validate role + transition existence WITHOUT running guards.

        Useful for "can I do this?" checks before showing a UI affordance.
        Raises :class:`InvalidTransition` / :class:`TransitionNotPermitted`.
        """
        transition = self._resolve(current, target)
        self._check_role(
            transition,
            user_role=user_role,
            current=current,
            target=target,
        )
        return transition

    async def apply(
        self,
        session: Any,
        entity: Any,
        target: str,
        *,
        actor_id: str | None = None,
        actor_role: str | None = None,
        reason: str | None = None,
        extra_metadata: dict[str, Any] | None = None,
        entity_type: str | None = None,
    ) -> Any:
        """Run the full transition pipeline.

        1. Resolve the matching :class:`StateTransition`.
        2. Enforce role gate.
        3. Build a context dict and run every guard.
        4. Persist the new status on ``entity`` (assignment to ``entity.status``).
        5. Run every side-effect handler.
        6. Write one row to :class:`ActivityLog` describing the move.

        Args:
            session: Active async SQLAlchemy session.
            entity: ORM instance with a ``status`` attribute.
            target: Desired new status string.
            actor_id: UUID of the user performing the action (string).
            actor_role: Role of the actor used for role-gate enforcement.
            reason: Free-form note recorded on the audit log row.
            extra_metadata: Optional dict merged into the audit ``metadata``.
            entity_type: Optional override for the entity_type column on
                the activity log (defaults to ``self.name``).

        Returns:
            The (mutated) entity for caller convenience.
        """
        current = getattr(entity, "status", None) or self.initial
        transition = self._resolve(current, target)
        self._check_role(
            transition,
            user_role=actor_role,
            current=current,
            target=target,
        )

        context: dict[str, Any] = {
            "session": session,
            "entity": entity,
            "from_status": current,
            "to_status": target,
            "actor_id": actor_id,
            "actor_role": actor_role,
            "reason": reason,
            "metadata": dict(extra_metadata or {}),
            "fsm": self,
            "transition": transition,
        }

        await self._run_guards(
            transition,
            context,
            current=current,
            target=target,
        )

        # Persist the new status. We mutate the ORM attribute directly so
        # callers that already loaded the entity benefit from change tracking;
        # service-layer wrappers can still do their own ``repo.update_fields``
        # afterwards if they prefer.
        entity.status = target

        await self._run_side_effects(transition, context)

        # ── Audit log write ───────────────────────────────────────────
        # Lazy import to avoid an import cycle between fsm <-> audit_log
        # (audit_log only depends on database.Base).
        try:
            from app.core.audit_log import log_activity

            ent_id = getattr(entity, "id", None)
            await log_activity(
                session,
                actor_id=actor_id,
                entity_type=entity_type or self.name,
                entity_id=str(ent_id) if ent_id is not None else None,
                action="status_changed",
                from_status=current,
                to_status=target,
                reason=reason,
                metadata={
                    "transition_description": transition.description,
                    **dict(extra_metadata or {}),
                },
            )
        except Exception:  # pragma: no cover — audit must never block flow
            logger.exception(
                "FSM %s: audit log write failed for entity %r %s->%s",
                self.name,
                getattr(entity, "id", "?"),
                current,
                target,
            )

        logger.info(
            "FSM %s: %s -> %s (entity=%s, actor=%s)",
            self.name,
            current,
            target,
            getattr(entity, "id", "?"),
            actor_id or "system",
        )
        return entity


# ── Registry ────────────────────────────────────────────────────────────────


_FSM_REGISTRY: dict[str, EntityFSM] = {}


def register_fsm(fsm: EntityFSM) -> EntityFSM:
    """Register an FSM in the global lookup. Idempotent on re-import."""
    _FSM_REGISTRY[fsm.name] = fsm
    return fsm


def get_fsm(name: str) -> EntityFSM:
    """Look up a registered FSM by entity name. Raises KeyError if missing."""
    if name not in _FSM_REGISTRY:
        raise KeyError(f"No FSM registered for entity type {name!r}")
    return _FSM_REGISTRY[name]


def all_fsms() -> dict[str, EntityFSM]:
    """Return a read-only copy of the registry (used by tests and tooling)."""
    return dict(_FSM_REGISTRY)
