# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Port: what other modules do when a legal effect of an acceptance is confirmed.

The quality concept records that a person confirmed an effect of an accepted
unit (the final account becomes due, a retention is released, the risk passes).
The module that owns the consequence (commitments, payments, insurance)
registers a handler here; the quality concept calls :func:`apply_effect` inside
the confirming transaction and stores which handlers acted. Neither side
imports the other.

A handler returns a short dict describing what it wrote (ids, never prose), or
``None`` when the effect is not its business. With no handler registered the
confirmation is still recorded, with an empty ``handled_by``: nobody is told
that a notification went out when none did.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from typing import Any

EffectHandler = Callable[[Any, uuid.UUID, dict[str, Any]], Awaitable[dict[str, Any] | None]]

_HANDLERS: dict[str, EffectHandler] = {}


def register_effect_handler(name: str, handler: EffectHandler) -> None:
    """Register (or replace, by name) a handler for confirmed acceptance effects."""
    _HANDLERS[name] = handler


def unregister_effect_handler(name: str) -> None:
    _HANDLERS.pop(name, None)


async def apply_effect(session: Any, project_id: uuid.UUID, effect: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Ask every handler; returns ``{handler name: what it wrote}`` for those that acted.

    ``effect`` carries ``effect``, ``unit_id``, ``effective_date`` (ISO) and ``package_refs``.
    A handler that raises aborts the confirmation: an effect half applied is worse than one refused.
    """
    out: dict[str, dict[str, Any]] = {}
    for name, handler in list(_HANDLERS.items()):
        result = await handler(session, project_id, dict(effect))
        if result is not None:
            out[name] = result
    return out
