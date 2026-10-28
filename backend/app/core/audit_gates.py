# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Generalised transition-gate registry (Epic H).

The CDE ISO 19650 workflow uses a "Gate B" check on the
SHARED → PUBLISHED transition: the request body MUST carry a non-empty
``approver_signature``. Lots of other FSM transitions in the codebase
want the same shape of precondition (e.g. RFI close with a "resolution
summary", change order approve with a signed PDF reference) - Epic H
extracts the check into a tiny registry so future gates can be added
declaratively without sprinkling more bespoke ``if`` blocks across the
service layer.

The registry is intentionally minimal: each gate is a pure function
``(payload) -> tuple[bool, str | None]`` returning ``(False, "reason")``
when the gate refuses and ``(True, None)`` when it lets the transition
through. The CDE service keeps its existing 400-error contract - the
registry helper raises an ``HTTPException(status_code=400)`` on failure
so caller code paths stay byte-identical.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from fastapi import HTTPException, status

logger = logging.getLogger(__name__)

# A gate is a function that inspects the request payload and decides
# whether the transition should be allowed. ``payload`` is the raw
# (already-validated) request object - typically a Pydantic model. The
# gate returns ``(ok, reason)`` so the caller can raise its own error
# with a precise message in the negative path.
GateFn = Callable[[Any], tuple[bool, str | None]]


class _GateRegistry:
    """In-process registry of named transition gates.

    ``register("gate_code", fn)`` adds a gate; ``enforce("gate_code", payload)``
    raises ``HTTPException(400)`` if the gate refuses. Gates are keyed by
    the ``gate_code`` returned by ``CDEStateMachine.get_gate_requirements``
    (e.g. ``"GATE_B"`` for SHARED → PUBLISHED) so the existing logic can
    be lifted out additively without renaming anything.
    """

    def __init__(self) -> None:
        self._gates: dict[str, GateFn] = {}

    def register(self, gate_code: str, fn: GateFn) -> None:
        """Register or replace a gate. Replacing is allowed for tests."""
        self._gates[gate_code] = fn

    def get(self, gate_code: str) -> GateFn | None:
        return self._gates.get(gate_code)

    def enforce(self, gate_code: str | None, payload: Any) -> None:
        """Run the gate keyed by ``gate_code``; 400 on refusal.

        Unknown gate codes are a no-op - registries are additive, and
        the CDE state-machine emits gate codes (``GATE_A``, ``GATE_C``,
        …) that may not yet have a paired precondition. The current
        contract for CDE Gate B is preserved verbatim: the same
        ``status_code=400`` and the same detail message.
        """
        if not gate_code:
            return
        fn = self._gates.get(gate_code)
        if fn is None:
            return
        ok, reason = fn(payload)
        if not ok:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=reason or f"Gate {gate_code} precondition failed",
            )


# Module-level singleton - register at import time.
gate_registry = _GateRegistry()


# ── Built-in gates ──────────────────────────────────────────────────────


def _cde_gate_b(payload: Any) -> tuple[bool, str | None]:
    """CDE SHARED → PUBLISHED requires a non-empty approver signature.

    ``payload`` is expected to expose ``approver_signature`` (the CDE
    ``StateTransitionRequest`` Pydantic model does). For any other
    payload shape the gate is conservative: it refuses with a generic
    "signature required" message rather than letting the transition
    through, because the only caller is the CDE service.
    """
    signature: str | None = getattr(payload, "approver_signature", None)
    if signature is None and isinstance(payload, dict):
        signature = payload.get("approver_signature")
    if not signature or not str(signature).strip():
        return False, "Gate B (SHARED → PUBLISHED) requires approver_signature"
    return True, None


# CDEStateMachine.get_gate_requirements emits gate codes as plain
# letters ("A" / "B" / "C") via the ``_GATES`` dict in cde_states.py.
# Register the gate under both the short letter (live caller) and the
# explicit "GATE_B" form for tests and future external callers.
gate_registry.register("B", _cde_gate_b)
gate_registry.register("GATE_B", _cde_gate_b)


__all__ = ["GateFn", "gate_registry"]
