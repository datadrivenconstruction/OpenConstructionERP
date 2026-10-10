# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Boot-path data repairs owned by the BOQ module.

Imported by :func:`app.core.data_repairs.discover_data_repairs`, which is what
makes the registration below take effect. Nothing else imports this file, and
nothing needs to.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from app.core.data_repairs import DataRepair, register_data_repair

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

#: Proposal status -> the ``Position.source`` the copilot writes for it today.
_SOURCE_FOR_STATUS = {
    "auto_applied": "ai_copilot_auto",
    "applied": "ai_copilot_accepted",
}


def copilot_provenance(actions_in_order: list[Any]) -> tuple[str, float | None] | None:
    """Return the source and confidence of the last proposal written to a line.

    ``actions_in_order`` is every ``actions`` list of the line's copilot
    thread, oldest message first. Only proposals that were actually written
    count; a dismissed or failed one left the line as it was.
    """
    found: tuple[str, float | None] | None = None
    for actions in actions_in_order:
        if not isinstance(actions, list):
            continue
        for action in actions:
            if not isinstance(action, dict):
                continue
            source = _SOURCE_FOR_STATUS.get(str(action.get("status") or ""))
            if source is None:
                continue
            raw = action.get("confidence")
            try:
                confidence = float(raw) if raw is not None else None
            except (TypeError, ValueError):
                confidence = None
            if confidence is not None and not 0.0 <= confidence <= 1.0:
                confidence = None
            found = (source, confidence)
    return found


async def _run_copilot_provenance(session: AsyncSession) -> int:
    """Restore the copilot as the author of lines it wrote as "manual".

    Until 16.3.0 a copilot edit went through the ordinary position update and
    kept the default ``source="manual"``, so a line the model wrote read as
    typed by the estimator. The copilot thread of each line still holds every
    proposal with its status and confidence, which is what this reads.
    Imported inside the function so that importing this module costs only the
    registration.
    """
    from sqlalchemy import select, update

    from app.modules.boq.copilot_models import PositionCopilotMessage
    from app.modules.boq.models import Position

    rows = (
        await session.execute(
            select(PositionCopilotMessage.position_id, PositionCopilotMessage.actions)
            .join(Position, Position.id == PositionCopilotMessage.position_id)
            .where(Position.source == "manual", PositionCopilotMessage.actions.is_not(None))
            .order_by(PositionCopilotMessage.position_id, PositionCopilotMessage.created_at)
        )
    ).all()

    threads: dict[Any, list[Any]] = {}
    for position_id, actions in rows:
        threads.setdefault(position_id, []).append(actions)

    changed = 0
    for position_id, actions_in_order in threads.items():
        provenance = copilot_provenance(actions_in_order)
        if provenance is None:
            continue
        source, confidence = provenance
        values: dict[str, Any] = {"source": source}
        if confidence is not None:
            # The column is String(10); the model's figure can carry many
            # digits, and three say all a reviewer needs.
            values["confidence"] = str(round(confidence, 3))
        # The "manual" guard lets a concurrent write win and makes a second
        # pass find nothing to do.
        result = await session.execute(
            update(Position)
            .where(Position.id == position_id, Position.source == "manual")
            .values(**values)
            .execution_options(synchronize_session=False)
        )
        changed += result.rowcount or 0

    if changed:
        logger.info("Marked %d BOQ line(s) written by the copilot before 16.3.0 as AI-written.", changed)
    return changed


#: Nature ``always_wrong``: ``source="manual"`` claims a person typed the
#: line, and for these lines the copilot's own thread records that the model
#: wrote it. That was never a true state, only the one the old write path
#: left. Lines without such a record are not touched: every other AI path in
#: the BOQ writes its own source value, the copilot was the one that wrote
#: under "manual", and its thread is deleted only together with the line, so
#: a line still standing with no thread was not written by it. No edit path
#: writes "manual" back onto an existing line (only new lines start with it),
#: so a marked line is not marked again after a person edits it. One limit, stated rather than hidden: a line a person
#: rewrote after the copilot also gets the AI mark, because nothing recorded
#: that later edit apart from an ordinary one. Idempotent: it rewrites only
#: rows still on "manual".
BOQ_COPILOT_PROVENANCE = register_data_repair(
    DataRepair(
        repair_id="boq_copilot_provenance",
        revision="",
        summary="Mark BOQ lines the copilot wrote before 16.3.0, which still read as typed by hand, as AI-written",
        run=_run_copilot_provenance,
        nature="always_wrong",
    )
)
