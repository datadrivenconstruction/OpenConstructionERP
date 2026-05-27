"""‌⁠‍Unit tests for the meetings recurring-series + attendance check-in service.

Scope:
    - create_series with FREQ=WEEKLY;COUNT=4 → 1 master + 4 occurrences
      (master + 3 future = total 4 with shared series_id).
    - generate_occurrences is idempotent — re-materialising doesn't dupe.
    - check_in: first call creates a row, second call updates the same row.
    - record_external_attendee: name-only walk-in row.
    - RRULE expander supports DAILY, WEEKLY, MONTHLY with COUNT terminator.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from app.modules.meetings.schemas import (
    MeetingCreate,
    MeetingSeriesCreate,
)
from app.modules.meetings.service import (
    MeetingService,
    _expand_rrule,
    _RRuleError,
)

# ── Helpers / stubs ───────────────────────────────────────────────────────


class _StubRepo:
    """Minimal repo stub that backs both Meeting and MeetingAttendance rows."""

    def __init__(self) -> None:
        self.meetings: dict[uuid.UUID, Any] = {}
        self._counter = 0

    async def create(self, meeting: Any) -> Any:
        if getattr(meeting, "id", None) is None:
            meeting.id = uuid.uuid4()
        now = datetime.now(UTC)
        meeting.created_at = now
        meeting.updated_at = now
        # Defaults the model would normally fill from server_default.
        if not hasattr(meeting, "series_id") or meeting.series_id is None:
            meeting.series_id = None
        if not hasattr(meeting, "recurrence_rule") or meeting.recurrence_rule is None:
            meeting.recurrence_rule = None
        if not hasattr(meeting, "is_series_master") or meeting.is_series_master is None:
            meeting.is_series_master = False
        self.meetings[meeting.id] = meeting
        return meeting

    async def get_by_id(self, meeting_id: uuid.UUID) -> Any:
        return self.meetings.get(meeting_id)

    async def next_meeting_number(self, project_id: uuid.UUID) -> str:
        self._counter += 1
        return f"MTG-{self._counter:03d}"

    async def update_fields(self, meeting_id: uuid.UUID, **fields: Any) -> None:
        obj = self.meetings.get(meeting_id)
        if obj is not None:
            for k, v in fields.items():
                setattr(obj, k, v)

    async def list_for_project(
        self,
        project_id: uuid.UUID,
        **_kwargs: Any,
    ) -> tuple[list[Any], int]:
        rows = [r for r in self.meetings.values() if r.project_id == project_id]
        return rows, len(rows)

    async def delete(self, meeting_id: uuid.UUID) -> None:
        self.meetings.pop(meeting_id, None)


class _StubSession:
    """Session stub that backs MeetingAttendance via an in-memory list and
    answers select(MeetingAttendance / Meeting) queries the service makes.
    """

    def __init__(self, repo: _StubRepo) -> None:
        self._repo = repo
        self.attendance: list[Any] = []
        self._pending: list[Any] = []

    def add(self, obj: Any) -> None:
        if getattr(obj, "id", None) is None:
            obj.id = uuid.uuid4()
        now = datetime.now(UTC)
        if not hasattr(obj, "created_at") or obj.created_at is None:
            obj.created_at = now
        obj.updated_at = now
        # Only track MeetingAttendance rows in our in-memory store. The
        # service also adds AuditEntry / Task rows through _safe_audit and
        # complete_meeting; those are irrelevant to attendance assertions.
        from app.modules.meetings.models import MeetingAttendance

        if isinstance(obj, MeetingAttendance):
            self._pending.append(obj)

    async def flush(self) -> None:
        # Commit pending into the in-memory attendance store.
        for obj in self._pending:
            # Replace if a row with the same id is already present
            # (covers refresh-after-update flows).
            self.attendance = [a for a in self.attendance if a.id != obj.id]
            self.attendance.append(obj)
        self._pending.clear()

    async def refresh(self, obj: Any) -> None:
        # No-op for our purposes — fields are already set on the live object.
        return None

    async def execute(self, stmt: Any) -> SimpleNamespace:
        # We only need to satisfy:
        #   select(MeetingAttendance).where(meeting_id==X, user_id==Y)
        #   select(MeetingAttendance).where(meeting_id==X).order_by(...)
        #   select(Meeting).where(series_id==X)
        from app.modules.meetings.models import Meeting, MeetingAttendance

        col_desc = getattr(stmt, "column_descriptions", None)
        if col_desc:
            entity = col_desc[0].get("entity")
        else:
            entity = None

        # Best-effort: inspect compiled WHERE clauses from the stmt to extract
        # bind parameters. For our stubs we can use the simpler trick of
        # reading params off the compiled statement.
        compiled = stmt.compile(compile_kwargs={"literal_binds": False})
        params = dict(compiled.params)

        if entity is MeetingAttendance:
            rows = list(self.attendance)
            if "meeting_id_1" in params:
                # filter by meeting_id (first WHERE clause)
                wanted_meeting = params["meeting_id_1"]
                rows = [r for r in rows if str(r.meeting_id) == str(wanted_meeting)]
            if "user_id_1" in params and params["user_id_1"] is not None:
                wanted_user = params["user_id_1"]
                rows = [r for r in rows if str(r.user_id) == str(wanted_user)]
            return _Scalars(rows)

        if entity is Meeting:
            rows = list(self._repo.meetings.values())
            if "series_id_1" in params:
                wanted = params["series_id_1"]
                rows = [r for r in rows if str(r.series_id) == str(wanted)]
            return _Scalars(rows)

        return _Scalars([])


class _Scalars:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def scalars(self) -> _Scalars:
        return self

    def all(self) -> list[Any]:
        return list(self._rows)

    def scalar_one_or_none(self) -> Any:
        return self._rows[0] if self._rows else None


def _make_service() -> MeetingService:
    service = MeetingService.__new__(MeetingService)
    service.repo = _StubRepo()
    service.session = _StubSession(service.repo)  # type: ignore[arg-type]
    return service


# ── RRULE expander ────────────────────────────────────────────────────────


def test_expand_rrule_weekly_count_yields_four_occurrences() -> None:
    start = datetime(2026, 5, 4, tzinfo=UTC)  # Monday
    horizon = datetime(2027, 1, 1, tzinfo=UTC)
    out = _expand_rrule("FREQ=WEEKLY;BYDAY=MO;COUNT=4", start, horizon)
    assert len(out) == 4
    # All four must fall on a Monday.
    assert all(d.weekday() == 0 for d in out)


def test_expand_rrule_daily_count() -> None:
    start = datetime(2026, 5, 4, tzinfo=UTC)
    horizon = datetime(2026, 6, 1, tzinfo=UTC)
    out = _expand_rrule("FREQ=DAILY;COUNT=3", start, horizon)
    assert len(out) == 3


def test_expand_rrule_monthly_count() -> None:
    start = datetime(2026, 5, 4, tzinfo=UTC)
    horizon = datetime(2027, 12, 1, tzinfo=UTC)
    out = _expand_rrule("FREQ=MONTHLY;COUNT=3", start, horizon)
    assert len(out) == 3
    assert out[0].month == 5
    assert out[1].month == 6
    assert out[2].month == 7


def test_expand_rrule_unsupported_freq_raises() -> None:
    start = datetime(2026, 5, 4, tzinfo=UTC)
    horizon = datetime(2027, 1, 1, tzinfo=UTC)
    # dateutil is installed in the dev env, so this must still raise
    # (dateutil rejects FREQ=YEARLY without BYMONTH+BYDAY combos differently,
    # but FREQ=FOO definitely errors). Either way the service wraps the
    # underlying error into _RRuleError.
    with pytest.raises((_RRuleError, ValueError)):
        _expand_rrule("FREQ=FOO;COUNT=3", start, horizon)


# ── create_series ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_series_weekly_count4_makes_one_master_three_occurrences() -> None:
    """FREQ=WEEKLY;COUNT=4 + materialize_until far in the future →
    master (1) + 3 fresh occurrences = 4 rows sharing the same series_id.

    (RFC 5545 COUNT counts the master itself, so 4 total — master + 3 new.)
    """
    service = _make_service()
    pid = uuid.uuid4()
    data = MeetingSeriesCreate(
        project_id=pid,
        meeting_type="progress",
        title="Weekly Stand-up",
        meeting_date="2026-05-04",  # Monday
        recurrence_rule="FREQ=WEEKLY;BYDAY=MO;COUNT=4",
        materialize_until="2026-12-31",
    )
    master, occurrences = await service.create_series(data, user_id="u1")

    assert master.is_series_master is True
    assert master.series_id == str(master.id)
    # The master date itself is the 1st occurrence; expander returns 4 dates;
    # 3 brand-new occurrences should be created.
    assert len(occurrences) == 3
    series_rows = [m for m in service.repo.meetings.values() if m.series_id == str(master.id)]
    assert len(series_rows) == 4
    # Only one master in the set.
    assert sum(1 for m in series_rows if m.is_series_master) == 1


@pytest.mark.asyncio
async def test_generate_occurrences_is_idempotent() -> None:
    """Re-materialising the same series produces zero new rows."""
    service = _make_service()
    pid = uuid.uuid4()
    data = MeetingSeriesCreate(
        project_id=pid,
        meeting_type="progress",
        title="Weekly Stand-up",
        meeting_date="2026-05-04",
        recurrence_rule="FREQ=WEEKLY;BYDAY=MO;COUNT=4",
        materialize_until="2026-12-31",
    )
    master, first_round = await service.create_series(data, user_id="u1")
    assert len(first_round) == 3

    horizon = datetime(2026, 12, 31, tzinfo=UTC)
    second_round = await service.generate_occurrences(
        str(master.id),
        horizon,
        user_id="u1",
    )
    assert second_round == []
    # Total rows in the series is still 4 (master + 3).
    series_rows = [m for m in service.repo.meetings.values() if m.series_id == str(master.id)]
    assert len(series_rows) == 4


# ── check_in ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_check_in_first_call_creates_row_second_call_updates_same_row() -> None:
    service = _make_service()
    pid = uuid.uuid4()
    meeting = await service.create_meeting(
        MeetingCreate(
            project_id=pid,
            meeting_type="progress",
            title="Stand-up",
            meeting_date="2026-05-04",
        )
    )
    user_id = str(uuid.uuid4())

    row1 = await service.check_in(meeting.id, user_id)
    assert row1.user_id == user_id
    assert row1.checked_in_at is not None
    first_id = row1.id

    # Re-check-in must update the same row, not create a duplicate.
    row2 = await service.check_in(meeting.id, user_id)
    assert row2.id == first_id

    all_rows = [
        a
        for a in service.session.attendance  # type: ignore[attr-defined]
        if a.meeting_id == meeting.id
    ]
    assert len(all_rows) == 1


@pytest.mark.asyncio
async def test_record_external_attendee_creates_row_with_external_name() -> None:
    service = _make_service()
    pid = uuid.uuid4()
    meeting = await service.create_meeting(
        MeetingCreate(
            project_id=pid,
            meeting_type="progress",
            title="Stand-up",
            meeting_date="2026-05-04",
        )
    )

    row = await service.record_external_attendee(meeting.id, "Jane Walker")
    assert row.user_id is None
    assert row.external_name == "Jane Walker"
    assert row.checked_in_at is not None

    # Multiple "Jane Walker" rows are allowed (unique only on user_id).
    row2 = await service.record_external_attendee(meeting.id, "Jane Walker")
    assert row2.id != row.id
    all_rows = [
        a
        for a in service.session.attendance  # type: ignore[attr-defined]
        if a.meeting_id == meeting.id
    ]
    assert len(all_rows) == 2
