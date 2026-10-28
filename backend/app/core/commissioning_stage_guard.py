# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Hook that lets a staged commissioning model veto ``commission_system``.

commissioning never imports the module that owns the stage model. That module
registers one async callable ``(session, project_id, system_id) -> list[str]``
returning blocking reasons (empty = allowed). With nothing registered, or when
the project has no stage model, commissioning behaves exactly as before.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from typing import Any

Guard = Callable[[Any, uuid.UUID, uuid.UUID], Awaitable[list[str]]]

_GUARD: list[Guard] = []


def register_commissioning_stage_guard(guard: Guard) -> None:
    """Register (replace) the guard."""
    _GUARD.clear()
    _GUARD.append(guard)


def unregister_commissioning_stage_guard() -> None:
    _GUARD.clear()


async def commissioning_blockers(session: Any, project_id: uuid.UUID, system_id: uuid.UUID) -> list[str]:
    """Blocking reasons from the registered guard; ``[]`` when none is registered."""
    if not _GUARD:
        return []
    return list(await _GUARD[0](session, project_id, system_id))
