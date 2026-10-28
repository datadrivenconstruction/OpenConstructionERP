# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Data access for per-user inbox item states.

Every read takes the owner's id as a required argument rather than inferring
it. A state row is private by construction: it says what one person did with
one row of their own list, and there is no query here that can return anybody
else's.

Reads use ``select()`` with an explicit owner predicate rather than
``session.get()``, which answers from the identity map and cannot express the
owner filter at all.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.dashboard.models import InboxItemState


class InboxItemStateRepository:
    """Read and write what one user did with their inbox rows."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def states_for_user(self, user_id: uuid.UUID) -> dict[str, str]:
        """Map item id to state for everything this user has acted on.

        Returned as a plain dict so the pure inbox logic can filter without
        touching the ORM.
        """
        stmt = select(InboxItemState.item_id, InboxItemState.state).where(InboxItemState.user_id == user_id)
        rows = (await self.session.execute(stmt)).all()
        return {item_id: state for item_id, state in rows}

    async def get(self, user_id: uuid.UUID, item_id: str) -> InboxItemState | None:
        """The state this user recorded for one item, or None."""
        stmt = select(InboxItemState).where(InboxItemState.user_id == user_id).where(InboxItemState.item_id == item_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list_for_user(self, user_id: uuid.UUID) -> Sequence[InboxItemState]:
        """Every state row this user holds, newest first."""
        stmt = (
            select(InboxItemState).where(InboxItemState.user_id == user_id).order_by(InboxItemState.updated_at.desc())
        )
        return (await self.session.execute(stmt)).scalars().all()

    async def upsert(
        self,
        user_id: uuid.UUID,
        item_id: str,
        *,
        source: str,
        source_id: str,
        state: str,
        findings: list[dict],
    ) -> InboxItemState:
        """Record (or replace) what the user did with one item.

        Acting twice on the same row overwrites the state rather than adding a
        second row, so acknowledging something and then dismissing it leaves
        one unambiguous answer to "what did they do with this?".
        """
        existing = await self.get(user_id, item_id)
        if existing is not None:
            existing.state = state
            existing.findings = findings
            await self.session.flush()
            return existing

        row = InboxItemState(
            user_id=user_id,
            item_id=item_id,
            source=source,
            source_id=source_id,
            state=state,
            findings=findings,
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def clear(self, user_id: uuid.UUID, item_id: str) -> bool:
        """Forget the state for one item, putting it back on the list.

        Returns True when a row was actually removed.
        """
        result = await self.session.execute(
            delete(InboxItemState).where(InboxItemState.user_id == user_id).where(InboxItemState.item_id == item_id)
        )
        await self.session.flush()
        return bool(result.rowcount)


__all__ = ["InboxItemStateRepository"]
