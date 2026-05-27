"""Unit tests for Notifications preferences + digest queue (Wave 3 / T9).

Covers the four behavioural contracts of the new
``NotificationService.enqueue_or_dispatch`` + ``flush_digest_queue`` pair:

* realtime pref → in-app sink is called immediately, queue stays empty.
* hourly  pref → queue row created, sink is NOT called.
* flush at scheduled time → all queued rows marked sent, one combined
  notification per (user, channel) group.
* default (no pref row) → realtime via the in-app channel.

Per ``feedback_test_isolation.md`` every test uses an isolated temp
SQLite — never ``backend/openestimate.db``.
"""

from __future__ import annotations

import tempfile
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.database import Base
from app.modules.notifications.models import (
    Notification,
    NotificationDigestQueue,
    NotificationPreference,
)
from app.modules.notifications.service import NotificationService

USER_ID = uuid.uuid4()


def _register_models() -> None:
    import app.modules.notifications.models  # noqa: F401
    import app.modules.users.models  # noqa: F401


@pytest_asyncio.fixture
async def session():
    tmp_db = Path(tempfile.mkdtemp()) / "notif_prefs.db"
    url = f"sqlite+aiosqlite:///{tmp_db.as_posix()}"
    engine = create_async_engine(url, future=True)
    _register_models()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
        from app.modules.users.models import User

        owner = User(
            id=USER_ID,
            email=f"u-{uuid.uuid4().hex[:6]}@test.io",
            hashed_password="x",
            full_name="U",
        )
        s.add(owner)
        await s.commit()
        yield s
    await engine.dispose()
    try:
        tmp_db.unlink(missing_ok=True)
        tmp_db.parent.rmdir()
    except OSError:
        pass


# ── set_preference / get_preferences ──────────────────────────────────────


@pytest.mark.asyncio
async def test_set_preference_creates_then_updates(session):
    """Upserting the same (user, event_type, channel) replaces digest."""
    svc = NotificationService(session)
    p1 = await svc.set_preference(
        USER_ID,
        "boq.position.created",
        "email",
        enabled=True,
        digest="hourly",
    )
    assert p1.digest == "hourly"
    assert p1.enabled is True

    p2 = await svc.set_preference(
        USER_ID,
        "boq.position.created",
        "email",
        enabled=False,
        digest="daily",
    )
    # Same row, updated in place.
    assert p2.id == p1.id
    assert p2.digest == "daily"
    assert p2.enabled is False

    prefs = await svc.get_preferences(USER_ID)
    assert len(prefs) == 1


# ── realtime → immediate dispatch ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_realtime_pref_dispatches_immediately(session):
    """realtime pref → in-app row, no digest queue row."""
    svc = NotificationService(session)
    await svc.set_preference(
        USER_ID,
        "boq.position.created",
        "inapp",
        enabled=True,
        digest="realtime",
    )

    outcome = await svc.enqueue_or_dispatch(
        "boq.position.created",
        USER_ID,
        {
            "title_key": "notifications.boq.position.created.title",
            "body_context": {"ordinal": "01.02.003"},
        },
        channel="inapp",
    )
    assert outcome == "dispatched"

    # Notification row exists.
    rows = list(
        (
            await session.execute(
                select(Notification).where(Notification.user_id == USER_ID),
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].notification_type == "boq.position.created"

    # Digest queue empty.
    queued = list((await session.execute(select(NotificationDigestQueue))).scalars().all())
    assert queued == []


# ── default (no pref) → realtime via inapp ─────────────────────────────────


@pytest.mark.asyncio
async def test_default_no_pref_dispatches_realtime_inapp(session):
    """Absent any pref row, the default is realtime in-app."""
    svc = NotificationService(session)
    # No set_preference call.
    outcome = await svc.enqueue_or_dispatch(
        "risk.simulated",
        USER_ID,
        {"title_key": "notifications.risk.simulated.title"},
        channel="inapp",
    )
    assert outcome == "dispatched"

    notif_count = len(
        list(
            (
                await session.execute(
                    select(Notification).where(Notification.user_id == USER_ID),
                )
            )
            .scalars()
            .all()
        )
    )
    assert notif_count == 1


# ── hourly pref → queued, not dispatched ───────────────────────────────────


@pytest.mark.asyncio
async def test_hourly_pref_queues_no_immediate_dispatch(session):
    """hourly digest pref → row appended, in-app store stays empty."""
    svc = NotificationService(session)
    await svc.set_preference(
        USER_ID,
        "changeorders.approval.advanced",
        "email",
        enabled=True,
        digest="hourly",
    )

    outcome = await svc.enqueue_or_dispatch(
        "changeorders.approval.advanced",
        USER_ID,
        {"co_id": "co-001", "stage": 2},
        channel="email",
    )
    assert outcome == "queued"

    queue_rows = list((await session.execute(select(NotificationDigestQueue))).scalars().all())
    assert len(queue_rows) == 1
    row = queue_rows[0]
    assert row.event_type == "changeorders.approval.advanced"
    assert row.channel == "email"
    assert row.sent_at is None
    # scheduled_for is roughly now + 1h.  SQLite hands back a naive
    # datetime even though we wrote a tz-aware one — compare in UTC.
    sched = row.scheduled_for
    if sched.tzinfo is None:
        sched = sched.replace(tzinfo=UTC)
    delta = sched - datetime.now(UTC)
    assert timedelta(minutes=50) < delta < timedelta(minutes=70)

    # No in-app notification persisted because email channel ≠ inapp.
    notifs = list(
        (
            await session.execute(
                select(Notification).where(Notification.user_id == USER_ID),
            )
        )
        .scalars()
        .all()
    )
    assert notifs == []


# ── disabled pref → suppressed ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_disabled_pref_suppresses(session):
    """enabled=False → nothing dispatched, nothing queued."""
    svc = NotificationService(session)
    await svc.set_preference(
        USER_ID,
        "rfi.assigned",
        "email",
        enabled=False,
        digest="realtime",
    )

    outcome = await svc.enqueue_or_dispatch(
        "rfi.assigned",
        USER_ID,
        {"rfi_id": "r-1"},
        channel="email",
    )
    assert outcome == "suppressed"

    assert list((await session.execute(select(NotificationDigestQueue))).scalars().all()) == []


# ── flush_digest_queue → marks rows sent + one combined per user/channel ───


@pytest.mark.asyncio
async def test_flush_digest_queue_marks_sent_and_groups(session):
    """At scheduled time, every queued row is sent + grouped per user."""
    svc = NotificationService(session)
    await svc.set_preference(
        USER_ID,
        "boq.position.created",
        "inapp",
        enabled=True,
        digest="hourly",
    )
    await svc.set_preference(
        USER_ID,
        "boq.position.updated",
        "inapp",
        enabled=True,
        digest="hourly",
    )

    # Enqueue three events.
    for event in (
        "boq.position.created",
        "boq.position.updated",
        "boq.position.created",
    ):
        outcome = await svc.enqueue_or_dispatch(
            event,
            USER_ID,
            {"position_id": uuid.uuid4().hex},
            channel="inapp",
        )
        assert outcome == "queued"

    # Pre-flush state.
    pending = list(
        (
            await session.execute(
                select(NotificationDigestQueue).where(
                    NotificationDigestQueue.sent_at.is_(None),
                ),
            )
        )
        .scalars()
        .all()
    )
    assert len(pending) == 3

    # Move the cutoff well past scheduled_for so all rows are eligible.
    future = datetime.now(UTC) + timedelta(hours=2)
    sent = await svc.flush_digest_queue("inapp", before=future)
    assert sent == 3

    # Every row stamped sent_at.
    still_pending = list(
        (
            await session.execute(
                select(NotificationDigestQueue).where(
                    NotificationDigestQueue.sent_at.is_(None),
                ),
            )
        )
        .scalars()
        .all()
    )
    assert still_pending == []

    # One combined notifications.digest row for the user.
    digest_notifs = list(
        (
            await session.execute(
                select(Notification).where(
                    Notification.notification_type == "notifications.digest",
                ),
            )
        )
        .scalars()
        .all()
    )
    assert len(digest_notifs) == 1
    n = digest_notifs[0]
    assert n.user_id == USER_ID
    # The metadata payload captures the underlying event list.
    payload = n.metadata_ or {}
    assert payload.get("count") == 3
    assert len(payload.get("events", [])) == 3


@pytest.mark.asyncio
async def test_flush_skips_rows_with_future_schedule(session):
    """Rows whose scheduled_for > cutoff are not flushed."""
    svc = NotificationService(session)
    await svc.set_preference(
        USER_ID,
        "risk.simulated",
        "email",
        enabled=True,
        digest="daily",
    )

    await svc.enqueue_or_dispatch(
        "risk.simulated",
        USER_ID,
        {"run_id": "r-1"},
        channel="email",
    )

    # Cutoff well before the scheduled time — nothing should be sent.
    past = datetime.now(UTC) - timedelta(hours=1)
    sent = await svc.flush_digest_queue("email", before=past)
    assert sent == 0

    # Row still pending.
    pending = list(
        (
            await session.execute(
                select(NotificationDigestQueue).where(
                    NotificationDigestQueue.sent_at.is_(None),
                ),
            )
        )
        .scalars()
        .all()
    )
    assert len(pending) == 1


@pytest.mark.asyncio
async def test_set_preference_unique_per_user_event_channel(session):
    """Same (user, event_type) on different channels → two rows."""
    svc = NotificationService(session)
    await svc.set_preference(
        USER_ID,
        "boq.position.created",
        "email",
        enabled=True,
        digest="hourly",
    )
    await svc.set_preference(
        USER_ID,
        "boq.position.created",
        "inapp",
        enabled=True,
        digest="realtime",
    )
    prefs = await svc.get_preferences(USER_ID)
    assert len(prefs) == 2
    channels = sorted({p.channel for p in prefs})
    assert channels == ["email", "inapp"]


# ── KNOWN_EVENT_TYPES catalogue ────────────────────────────────────────────


def test_known_event_types_catalogue_has_boq_and_co():
    """The catalogue surfaced by GET /event-types includes the major modules."""
    from app.modules.notifications.service import KNOWN_EVENT_TYPES

    keys = {e["event_type"] for e in KNOWN_EVENT_TYPES}
    assert "boq.position.created" in keys
    assert "changeorders.approval.advanced" in keys
    assert "risk.simulated" in keys
    # Every entry has the required shape.
    for entry in KNOWN_EVENT_TYPES:
        assert set(entry.keys()) == {"event_type", "module", "description"}


# ── Sanity: NotificationPreference schema round-trip ───────────────────────


@pytest.mark.asyncio
async def test_preference_pydantic_response_serialises(session):
    """The Pydantic PreferenceResponse hydrates from the ORM row."""
    from app.modules.notifications.schemas import PreferenceResponse

    svc = NotificationService(session)
    pref = await svc.set_preference(
        USER_ID,
        "boq.position.created",
        "email",
        enabled=True,
        digest="hourly",
    )
    resp = PreferenceResponse.model_validate(pref)
    assert resp.event_type == "boq.position.created"
    assert resp.channel == "email"
    assert resp.digest == "hourly"
    assert resp.enabled is True
    assert isinstance(resp.id, uuid.UUID)


# ── Channel "none" suppresses without queue or sink ────────────────────────


@pytest.mark.asyncio
async def test_channel_none_suppresses(session):
    """Passing channel='none' short-circuits everything."""
    svc = NotificationService(session)
    outcome = await svc.enqueue_or_dispatch(
        "rfi.assigned",
        USER_ID,
        {},
        channel="none",
    )
    assert outcome == "suppressed"
    assert list((await session.execute(select(Notification))).scalars().all()) == []
    assert list((await session.execute(select(NotificationDigestQueue))).scalars().all()) == []


# ── Ensure NotificationPreference can be filtered (Index sanity) ───────────


@pytest.mark.asyncio
async def test_get_preferences_filters_by_user(session):
    """Two users with different prefs are isolated."""
    svc = NotificationService(session)
    other_user_id = uuid.uuid4()
    # Insert a sibling User row so the FK constraint holds.
    from app.modules.users.models import User

    session.add(
        User(
            id=other_user_id,
            email=f"o2-{uuid.uuid4().hex[:6]}@test.io",
            hashed_password="x",
            full_name="O2",
        )
    )
    await session.flush()

    await svc.set_preference(USER_ID, "rfi.assigned", "email")
    await svc.set_preference(other_user_id, "rfi.assigned", "email")
    await svc.set_preference(other_user_id, "risk.simulated", "inapp")

    prefs_a = await svc.get_preferences(USER_ID)
    prefs_b = await svc.get_preferences(other_user_id)
    assert len(prefs_a) == 1
    assert len(prefs_b) == 2


# Avoid leaking the catalogue test into module-level import side effects.
_ = NotificationPreference  # silence ruff unused-import for the model symbol
