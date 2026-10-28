# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Dashboard ORM models.

One table, ``oe_dashboard_inbox_item_state``: what one person did with one
inbox row. The inbox itself still owns no data - it aggregates approvals and
notifications that live in their own modules - but until now that meant the
list was read-only and nobody could clear anything from it. This table is the
smallest thing that fixes that without pretending to decide an approval.

Two states, and the difference matters:

* ``acknowledged`` - "I have seen this". The row stays in the list, flagged, so
  it can recede without disappearing.
* ``dismissed``    - "take this off my list". The row stops being returned. For
  an alert that is the whole truth, because the same action marks the
  underlying notification read. For an approval it is triage only: the step
  stays ``pending`` and stays visible in the module that owns it. Hiding an
  obligation is not the same as discharging one, and the API, the UI copy and
  the ``inbox_action`` validation rules all say so in the same words.

Deliberately carries no ``relationship()``. The one foreign key is read as an
id and nothing traverses from a state row to its owner, so there is no
collection to eager-load and no back-reference that could fire a lazy SELECT
out of the async greenlet.
"""

from __future__ import annotations

import uuid

from sqlalchemy import JSON, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base


class InboxItemState(Base):
    """What one user did with one aggregated inbox row."""

    __tablename__ = "oe_dashboard_inbox_item_state"
    __table_args__ = (
        UniqueConstraint("user_id", "item_id", name="uq_dashboard_inbox_state_item"),
        Index("ix_dashboard_inbox_state_user_state", "user_id", "state"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_users_user.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        doc="Whose inbox this state applies to. States are per-person, never shared.",
    )
    item_id: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        doc="The aggregated inbox id, e.g. 'notification:<uuid>'. Not a foreign key: "
        "the row it names lives in whichever module produced it.",
    )
    source: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        doc="Parsed prefix of item_id: file_approval / change_order_approval / notification.",
    )
    source_id: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        doc="Parsed suffix of item_id: the id of the row in the owning module.",
    )
    state: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        doc="acknowledged (seen, still listed) or dismissed (off the list).",
    )
    findings: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=list,
        server_default="[]",
        doc="Validation findings recorded when the action was taken, so an audit "
        "of who cleared what can tell a hidden approval from a decided one.",
    )

    def __repr__(self) -> str:
        return f"<InboxItemState {self.item_id!r} {self.state} user={self.user_id}>"


__all__ = ["InboxItemState"]
