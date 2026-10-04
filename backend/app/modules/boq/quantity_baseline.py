# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The quantity baseline of a bill: the snapshot its contract quantities are read from.

Saving a measurement sheet in the bill editor writes the sheet's total into
the position's bill quantity, so once a site measurement is saved the quantity
the bill was tendered and awarded at is gone from the live bill. A quantity
check needs that figure, so the bill keeps a pointer to one of its own
snapshots (``BOQSnapshot`` already freezes quantity, unit rate and the stored
measurement sheet per position id) and reads the contract side from there.

The pointer lives in ``BOQ.metadata_["quantity_baseline"]``. It is set
automatically the first time a bill is locked, the moment the bill is
approved, and never moved by a later lock: a bill unlocked to enter
measurements and locked again must not make its measured quantities the
contract. A person may point it at another snapshot, or freeze the bill as it
stands, from the quantity check.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

#: Key under ``BOQ.metadata_`` holding the designated baseline.
BASELINE_META_KEY = "quantity_baseline"

#: Name of the snapshot taken when a bill is locked for the first time. Stored
#: data, shown in the version history like the other automatic snapshot names.
LOCK_SNAPSHOT_NAME = "Contract quantities (captured at lock)"

#: Name of the snapshot a person freezes from the quantity check.
FROZEN_SNAPSHOT_NAME = "Quantity baseline"


def designated_baseline_id(boq: Any) -> uuid.UUID | None:
    """The snapshot id the bill names as its quantity baseline, or ``None``."""
    meta = getattr(boq, "metadata_", None)
    if not isinstance(meta, dict):
        return None
    entry = meta.get(BASELINE_META_KEY)
    if not isinstance(entry, dict):
        return None
    raw = entry.get("snapshot_id")
    if not raw:
        return None
    try:
        return uuid.UUID(str(raw))
    except (ValueError, TypeError):
        return None


def baseline_entry(boq: Any) -> dict[str, Any]:
    """The stored baseline record (``snapshot_id``, ``set_at``, ``set_by``, ``reason``), or ``{}``."""
    meta = getattr(boq, "metadata_", None)
    entry = meta.get(BASELINE_META_KEY) if isinstance(meta, dict) else None
    return dict(entry) if isinstance(entry, dict) else {}


async def designate_baseline(
    session: AsyncSession,
    boq_id: uuid.UUID,
    snapshot_id: uuid.UUID | None,
    *,
    user_id: Any = None,
    reason: str = "chosen",
) -> None:
    """Point the bill's quantity baseline at ``snapshot_id``, or clear it with ``None``.

    The caller checks that the snapshot belongs to the bill. The metadata is
    written as a new dict so the JSON column sees the change.
    """
    from app.modules.boq.repository import BOQRepository

    repo = BOQRepository(session)
    boq = await repo.get_by_id(boq_id)
    if boq is None:
        return
    meta = dict(boq.metadata_) if isinstance(boq.metadata_, dict) else {}
    if snapshot_id is None:
        meta.pop(BASELINE_META_KEY, None)
    else:
        meta[BASELINE_META_KEY] = {
            "snapshot_id": str(snapshot_id),
            "set_at": datetime.now(UTC).isoformat(),
            "set_by": str(user_id) if user_id else None,
            "reason": reason,
        }
    await repo.update_fields(boq_id, metadata_=meta)


async def freeze_baseline(
    session: AsyncSession,
    boq_id: uuid.UUID,
    *,
    user_id: Any = None,
    name: str = FROZEN_SNAPSHOT_NAME,
    reason: str = "frozen",
) -> uuid.UUID:
    """Snapshot the bill as it stands and make that snapshot its quantity baseline."""
    from app.modules.boq.service import BOQService

    user_uuid: uuid.UUID | None
    try:
        user_uuid = uuid.UUID(str(user_id)) if user_id else None
    except (ValueError, TypeError):
        user_uuid = None
    snap = await BOQService(session).create_snapshot(
        boq_id,
        name=name,
        description="Contract quantities the quantity check compares measured quantities against.",
        user_id=user_uuid,
    )
    await designate_baseline(session, boq_id, snap.id, user_id=user_id, reason=reason)
    return snap.id


async def capture_baseline_on_lock(session: AsyncSession, boq_id: uuid.UUID, *, user_id: Any = None) -> bool:
    """Freeze the bill's quantities as its baseline when it is locked and has none yet.

    Returns ``True`` when a baseline was captured. A bill that already names
    one keeps it, so unlocking to measure and locking again does not turn the
    measured quantities into contract quantities. Runs in a savepoint: a
    failed capture must not undo the lock that already succeeded.
    """
    from sqlalchemy import select

    from app.modules.boq.models import BOQSnapshot
    from app.modules.boq.repository import BOQRepository

    try:
        async with session.begin_nested():
            boq = await BOQRepository(session).get_by_id(boq_id)
            if boq is None:
                return False
            named = designated_baseline_id(boq)
            if named is not None:
                # A copied bill carries its source's metadata, pointer included,
                # so a pointer at another bill's snapshot is not a baseline of
                # this one. A pointer at a deleted snapshot still stands: taking
                # one now could freeze measured quantities as the contract, and
                # the quantity check says the baseline is gone instead.
                owner = (
                    await session.execute(select(BOQSnapshot.boq_id).where(BOQSnapshot.id == named))
                ).scalar_one_or_none()
                if owner is None or owner == boq_id:
                    return False
            await freeze_baseline(session, boq_id, user_id=user_id, name=LOCK_SNAPSHOT_NAME, reason="lock")
        return True
    except Exception:
        logger.exception("Quantity baseline capture skipped for BOQ %s lock", boq_id)
        return False


__all__ = [
    "BASELINE_META_KEY",
    "FROZEN_SNAPSHOT_NAME",
    "LOCK_SNAPSHOT_NAME",
    "baseline_entry",
    "capture_baseline_on_lock",
    "designate_baseline",
    "designated_baseline_id",
    "freeze_baseline",
]
