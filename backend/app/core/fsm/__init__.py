# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠FSM package public API.

Importing from :mod:`app.core.fsm` gives you the engine primitives plus
the six entity-specific FSMs registered in :mod:`app.core.fsm.registry`.

Example::

    from app.core.fsm import BOQ_FSM, InvalidTransition

    await BOQ_FSM.apply(session, boq, "final", actor_id=user_id,
                        actor_role=role, reason="approved by PM")
"""

from app.core.fsm.engine import (
    EntityFSM,
    FSMError,
    GuardFailed,
    InvalidTransition,
    StateTransition,
    TransitionNotPermitted,
    all_fsms,
    get_fsm,
    register_fsm,
)
from app.core.fsm.registry import (
    BOQ_FSM,
    INVOICE_FSM,
    NCR_FSM,
    PROJECT_FSM,
    RFQ_FSM,
    SUBMITTAL_FSM,
)

__all__ = [
    "BOQ_FSM",
    "EntityFSM",
    "FSMError",
    "GuardFailed",
    "INVOICE_FSM",
    "InvalidTransition",
    "NCR_FSM",
    "PROJECT_FSM",
    "RFQ_FSM",
    "SUBMITTAL_FSM",
    "StateTransition",
    "TransitionNotPermitted",
    "all_fsms",
    "get_fsm",
    "register_fsm",
]
