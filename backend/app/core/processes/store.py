# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Persistence of the desired on/off state of every background process.

One row per process id in ``oe_process_settings``. Two reserved keys carry
installation-level facts: :data:`FRESH_KEY` (this installation started with
the processes center, so heavy processes default off) and :data:`FIRST_RUN_KEY`
(the first-run wizard was answered).
"""

from __future__ import annotations

import logging
from typing import Protocol

from sqlalchemy import Boolean, String, select
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

logger = logging.getLogger(__name__)

FRESH_KEY = "__fresh_install__"
FIRST_RUN_KEY = "__first_run_done__"


class ProcessSetting(Base):
    """Desired state of one background process for this installation."""

    __tablename__ = "oe_process_settings"

    process_id: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    updated_by: Mapped[str | None] = mapped_column(String(100), nullable=True, default=None)


class ProcessStore(Protocol):
    """Where the registry keeps desired state."""

    async def load(self) -> dict[str, bool]:
        """Return every persisted ``process_id -> enabled`` pair."""
        ...

    async def save(self, process_id: str, enabled: bool, updated_by: str | None = None) -> None:
        """Persist one desired state."""
        ...


class InMemoryProcessStore:
    """Store for tests and for runs without a database.

    Args:
        rows: Initial persisted state.
    """

    def __init__(self, rows: dict[str, bool] | None = None) -> None:
        self.rows: dict[str, bool] = dict(rows or {})

    async def load(self) -> dict[str, bool]:
        return dict(self.rows)

    async def save(self, process_id: str, enabled: bool, updated_by: str | None = None) -> None:
        self.rows[process_id] = enabled


class DbProcessStore:
    """Store backed by ``oe_process_settings``.

    A database failure is logged and treated as "nothing persisted": the
    platform must still boot with defaults when the table is unreachable.
    """

    async def load(self) -> dict[str, bool]:
        from app.database import async_session_factory

        try:
            async with async_session_factory() as session:
                rows = (await session.execute(select(ProcessSetting.process_id, ProcessSetting.enabled))).all()
        except Exception:
            logger.warning("Could not read process settings, using defaults", exc_info=True)
            return {}
        return {pid: bool(enabled) for pid, enabled in rows}

    async def save(self, process_id: str, enabled: bool, updated_by: str | None = None) -> None:
        from app.database import async_session_factory

        async with async_session_factory() as session:
            row = (
                await session.execute(select(ProcessSetting).where(ProcessSetting.process_id == process_id))
            ).scalar_one_or_none()
            if row is None:
                session.add(ProcessSetting(process_id=process_id, enabled=enabled, updated_by=updated_by))
            else:
                row.enabled = enabled
                row.updated_by = updated_by
            await session.commit()
