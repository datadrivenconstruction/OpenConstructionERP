# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Demo rows that show offline capture and a resolved sync conflict​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠.

``seed_offline_conflict_demo`` is called by the demo seeder. It is idempotent:
every row carries a fixed ``client_op_id`` and is looked up before it is made.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit_log import log_activity
from app.core.offline_merge import MERGE_ACTION, find_by_client_op_id
from app.modules.daily_diary.models import DailyDiary, DiaryEntry

logger = logging.getLogger(__name__)

DEVICE_ID = "demo-tablet-01"
OP_ENTRY = "demo-offline-entry-001"
OP_PUNCH = "demo-offline-punch-001"
OP_PUNCH_CONFLICT = "demo-offline-punch-conflict-001"
OFFLINE_META = {"captured_offline": True, "device_id": DEVICE_ID}


async def _diary_for_today(session: AsyncSession, project_id: uuid.UUID) -> DailyDiary:
    day = datetime.now(UTC).date().isoformat()
    found = (
        await session.execute(
            select(DailyDiary).where(DailyDiary.project_id == project_id, DailyDiary.diary_date == day)
        )
    ).scalar_one_or_none()
    if found is not None:
        return found
    diary = DailyDiary(project_id=project_id, diary_date=day, status="open", metadata_={})
    session.add(diary)
    await session.flush()
    return diary


async def seed_offline_conflict_demo(session: AsyncSession, project_id: uuid.UUID) -> dict[str, Any]:
    """Create one offline diary entry, one offline punch item and one resolved conflict.

    Args:
        session: Session of the seeding transaction (flushed, not committed).
        project_id: Project that receives the rows.

    Returns:
        ``{"entry_id", "punch_id", "conflict_punch_id"}`` (strings), whether the
        rows were just created or already existed.
    """
    from app.modules.punchlist.models import PunchItem  # lazy: punchlist is an optional module

    diary = await _diary_for_today(session, project_id)
    now = datetime.now(UTC)

    entry = await find_by_client_op_id(session, DiaryEntry, OP_ENTRY, DiaryEntry.diary_id == diary.id)
    if entry is None:
        entry = DiaryEntry(
            diary_id=diary.id,
            entry_type="general",
            entry_time=now,
            title="Level 2 slab pour started (captured without signal)",
            description="Pour began 07:40, 18 m3 placed before the first truck left. Written in the basement, synced later.",
            photo_ids=[],
            metadata_={"client_op_id": OP_ENTRY, **OFFLINE_META},
        )
        session.add(entry)

    punch = await find_by_client_op_id(session, PunchItem, OP_PUNCH, PunchItem.project_id == project_id)
    if punch is None:
        punch = PunchItem(
            project_id=project_id,
            title="Chipped edge on stair landing, level 1",
            description="Corner of the landing is chipped, about 4 cm. Raised from the stairwell where there is no reception.",
            priority="medium",
            status="open",
            metadata_={"client_op_id": OP_PUNCH, **OFFLINE_META},
        )
        session.add(punch)

    conflict = await find_by_client_op_id(session, PunchItem, OP_PUNCH_CONFLICT, PunchItem.project_id == project_id)
    created_conflict = conflict is None
    if conflict is None:
        conflict = PunchItem(
            project_id=project_id,
            title="Paint run on corridor wall, level 3",
            description="Paint run on the north corridor wall. Repainted after the site manager's walk. Confirmed by both.",
            priority="low",
            status="open",
            version=3,
            metadata_={"client_op_id": OP_PUNCH_CONFLICT, **OFFLINE_META, "offline_conflict_resolved": True},
        )
        session.add(conflict)
    await session.flush()

    if created_conflict:
        before = "Paint run on the north corridor wall."
        after = conflict.description
        await log_activity(
            session,
            actor_id=None,
            entity_type="punchlist_item",
            entity_id=str(conflict.id),
            action=MERGE_ACTION,
            reason="Offline merge of description (manual)",
            module="punchlist",
            parent_entity_type="project",
            parent_entity_id=str(project_id),
            before_state={"description": before},
            after_state={"description": after},
            metadata={
                "field": "description",
                "side": "manual",
                "device_id": DEVICE_ID,
                "base_version": 1,
                "version": 3,
            },
        )
    return {"entry_id": str(entry.id), "punch_id": str(punch.id), "conflict_punch_id": str(conflict.id)}
