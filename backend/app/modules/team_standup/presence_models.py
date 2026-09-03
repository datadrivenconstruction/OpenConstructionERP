# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Team Standup presence ORM model.

Table:
    oe_team_standup_presence - one row per (person, day, ERP module, job)
    holding the seconds that person spent there that day.

Kept in its own file so the delivery-board models stay untouched: the
package ``__init__`` imports this module, and the module loader imports
the package before ``models.py``, so the table joins ``Base.metadata``
ahead of the startup auto-create. No ALTER to any existing table.

``day`` is an ISO ``YYYY-MM-DD`` string like every other day column in
this module (a calendar label, not an instant). ``project_id`` is a plain
GUID string or NULL - same reasoning as ``StandupTask.project_id``: a
row must outlive the project it names.
"""

from datetime import datetime

from sqlalchemy import JSON, DateTime, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

#: Path segment -> module key length cap (also enforced in the service).
MAX_MODULE_KEY_CHARS = 60

#: The session-event kinds the service will store.
SESSION_EVENTS = ("login", "logout", "start", "end")
#: Where an event came from: the auth flow, the presence beacon, or the
#: window (pagehide / tab close).
SESSION_SOURCES = ("auth", "beacon", "window")


class SessionEvent(Base):
    """One thing that happened to a person's session on one day.

    ``login`` / ``logout`` come from the sign-in flow; ``start`` is minted
    server-side by the first presence ping of a day (its ``meta`` carries
    ``last_seen``, refreshed by every later ping); ``end`` is the tab's
    pagehide beacon. ``at`` is the instant (UTC); ``day`` is the module's
    calendar label so the rollup can group without timezone maths.
    """

    __tablename__ = "oe_team_standup_session_event"
    __table_args__ = (
        Index("ix_team_standup_session_event_user_day", "user_id", "day", "event"),
        Index("ix_team_standup_session_event_day", "day"),
    )

    user_id: Mapped[str] = mapped_column(String(36), nullable=False)
    event: Mapped[str] = mapped_column(String(12), nullable=False)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    day: Mapped[str] = mapped_column(String(10), nullable=False)
    source: Mapped[str] = mapped_column(String(12), nullable=False, default="auth")
    meta: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"<SessionEvent {self.user_id} {self.day} {self.event} {self.at:%H:%M:%S}>"


class PresenceSlot(Base):
    """Seconds one person spent in one module (and job) on one day."""

    __tablename__ = "oe_team_standup_presence"
    __table_args__ = (
        # The upsert key (project_id may be NULL, so this is a lookup
        # index rather than a UNIQUE - Postgres treats NULLs as distinct).
        Index(
            "ix_team_standup_presence_slot",
            "user_id",
            "day",
            "module_key",
            "project_id",
        ),
        # The metrics window scan.
        Index("ix_team_standup_presence_day", "day"),
    )

    user_id: Mapped[str] = mapped_column(String(36), nullable=False)
    day: Mapped[str] = mapped_column(String(10), nullable=False)
    module_key: Mapped[str] = mapped_column(String(MAX_MODULE_KEY_CHARS), nullable=False, default="")
    project_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"<PresenceSlot {self.user_id} {self.day} {self.module_key} {self.project_id or '-'} {self.seconds}s>"
