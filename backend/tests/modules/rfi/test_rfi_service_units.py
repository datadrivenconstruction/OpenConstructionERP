"""Wave 8 (Tests) - pure unit coverage for under-tested RFI service logic.

These tests need no database: they drive ``RFIService`` against the same
in-memory stub family the other RFI unit suites use, so they run locally and
in CI alike. They fill genuine gaps left by the prior waves:

* ``_add_business_days`` - the due-date generator skips weekends. Nothing
  pinned that Mon-Fri arithmetic before, yet every auto-due-date depends on it.
* ``update_rfi`` invalid FSM transition - the service raises 400 for a
  disallowed status jump (e.g. ``closed`` is terminal). Prior tests covered the
  role gates and the reopen gate but not a plain illegal transition.
* ``update_rfi`` auto due-date on ``open`` - moving draft -> open with no
  ``response_due_date`` auto-fills one; the service-level behaviour was untested.
* ``update_rfi`` no-op short-circuit - an empty patch returns the row unchanged.
* ``delete_rfi`` - publishes ``rfi.deleted`` and 404s on a missing row.
* ``add_attachment`` - appends to the JSON column and is order-preserving.
* ``respond_to_rfi`` flips ball-in-court back to the originator.
* ``get_stats`` is exercised against a stub session for the empty-project and
  avg-response-time branches that the DB suite does not assert.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi import HTTPException

from app.modules.rfi.schemas import RFICreate, RFIUpdate
from app.modules.rfi.service import (
    _RFI_RESPONSE_DUE_DAYS,
    RFIService,
    _add_business_days,
)

# ── Stubs (same family as test_rfi_state_fsm) ────────────────────────────


class _StubSession:
    def __init__(self, rows: dict[uuid.UUID, Any] | None = None) -> None:
        self._rows = rows

    async def refresh(self, obj: Any) -> None:
        pass

    async def rollback(self) -> None:
        pass

    async def execute(self, stmt: Any) -> Any:  # only get_stats uses this
        rows = list(self._rows.values()) if self._rows is not None else []

        class _Scalars:
            def all(self) -> list[Any]:
                return rows

        class _Result:
            def scalars(self) -> _Scalars:
                return _Scalars()

        return _Result()


class _StubRFIRepo:
    def __init__(self) -> None:
        self.rows: dict[uuid.UUID, Any] = {}
        self._counter = 0

    async def create(self, rfi: Any) -> Any:
        if getattr(rfi, "id", None) is None:
            rfi.id = uuid.uuid4()
        now = datetime.now(UTC)
        rfi.created_at = now
        rfi.updated_at = now
        if getattr(rfi, "attachments", None) is None:
            rfi.attachments = []
        self.rows[rfi.id] = rfi
        return rfi

    async def get_by_id(self, rfi_id: uuid.UUID) -> Any:
        return self.rows.get(rfi_id)

    async def next_rfi_number(self, project_id: uuid.UUID, *, prefix: str = "RFI", digits: int = 3) -> str:
        self._counter += 1
        return f"{prefix}-{self._counter:0{digits}d}"

    async def list_for_project(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
        status: str | None = None,
        search: str | None = None,
        with_total: bool = True,
        request_type: str | None = None,
    ) -> tuple[list[Any], int]:
        rows = [r for r in self.rows.values() if r.project_id == project_id]
        if status is not None:
            rows = [r for r in rows if r.status == status]
        return rows[offset : offset + limit], len(rows)

    async def update_fields(self, rfi_id: uuid.UUID, **fields: Any) -> None:
        obj = self.rows.get(rfi_id)
        if obj is None:
            return
        for k, v in fields.items():
            setattr(obj, k, v)

    async def delete(self, rfi_id: uuid.UUID) -> None:
        self.rows.pop(rfi_id, None)


def _make_service() -> RFIService:
    service = RFIService.__new__(RFIService)
    repo = _StubRFIRepo()
    service.repo = repo
    service.session = _StubSession(repo.rows)
    return service


# ── _add_business_days ───────────────────────────────────────────────────


class TestAddBusinessDays:
    def test_skips_weekend(self) -> None:
        """From a Friday, +1 business day lands on the following Monday."""
        # 2026-06-19 is a Friday.
        friday = datetime(2026, 6, 19, 12, 0, tzinfo=UTC)
        assert friday.weekday() == 4
        assert _add_business_days(friday, 1) == "2026-06-22"  # Monday

    def test_full_week_is_seven_calendar_days(self) -> None:
        """5 business days from a Monday is the next Monday (skips one
        weekend), i.e. 7 calendar days later."""
        monday = datetime(2026, 6, 15, 9, 0, tzinfo=UTC)
        assert monday.weekday() == 0
        assert _add_business_days(monday, 5) == "2026-06-22"

    def test_zero_days_returns_same_date(self) -> None:
        start = datetime(2026, 6, 17, 9, 0, tzinfo=UTC)
        assert _add_business_days(start, 0) == "2026-06-17"

    def test_result_is_always_a_weekday(self) -> None:
        start = datetime(2026, 6, 17, 9, 0, tzinfo=UTC)
        for n in range(1, 25):
            out = datetime.strptime(_add_business_days(start, n), "%Y-%m-%d")
            assert out.weekday() < 5, f"{n} business days landed on a weekend: {out}"


# ── create_rfi: auto due-date only when status == open ───────────────────


class TestCreateAutoDueDate:
    @pytest.mark.asyncio
    async def test_open_without_due_date_gets_one(self) -> None:
        service = _make_service()
        rfi = await service.create_rfi(
            RFICreate(project_id=uuid.uuid4(), subject="x", question="y", status="open"),
        )
        assert rfi.response_due_date is not None
        out = datetime.strptime(rfi.response_due_date, "%Y-%m-%d")
        assert out.weekday() < 5  # business-day result

    @pytest.mark.asyncio
    async def test_draft_does_not_get_due_date(self) -> None:
        service = _make_service()
        rfi = await service.create_rfi(
            RFICreate(project_id=uuid.uuid4(), subject="x", question="y", status="draft"),
        )
        assert rfi.response_due_date is None

    @pytest.mark.asyncio
    async def test_explicit_due_date_is_preserved(self) -> None:
        service = _make_service()
        rfi = await service.create_rfi(
            RFICreate(
                project_id=uuid.uuid4(),
                subject="x",
                question="y",
                status="open",
                response_due_date="2099-01-01",
            ),
        )
        assert rfi.response_due_date == "2099-01-01"


# ── update_rfi: FSM + no-op + auto due-date + ball-in-court ──────────────


class TestUpdateRFIFSM:
    @pytest.mark.asyncio
    async def test_invalid_transition_raises_400(self) -> None:
        """draft -> answered is not in the FSM table (must go via open)."""
        service = _make_service()
        rfi = await service.create_rfi(
            RFICreate(project_id=uuid.uuid4(), subject="x", question="y", status="draft"),
        )
        with pytest.raises(HTTPException) as exc:
            await service.update_rfi(rfi.id, RFIUpdate(status="answered"), actor_role="manager")
        assert exc.value.status_code == 400
        assert "transition" in exc.value.detail.lower()

    @pytest.mark.asyncio
    async def test_cannot_edit_terminal_void(self) -> None:
        service = _make_service()
        rfi = await service.create_rfi(
            RFICreate(project_id=uuid.uuid4(), subject="x", question="y", status="draft"),
        )
        rfi.status = "void"
        with pytest.raises(HTTPException) as exc:
            await service.update_rfi(rfi.id, RFIUpdate(subject="new"), actor_role="manager")
        assert exc.value.status_code == 400
        assert "void" in exc.value.detail.lower()

    @pytest.mark.asyncio
    async def test_draft_to_open_autofills_due_date(self) -> None:
        service = _make_service()
        rfi = await service.create_rfi(
            RFICreate(project_id=uuid.uuid4(), subject="x", question="y", status="draft"),
        )
        assert rfi.response_due_date is None
        updated = await service.update_rfi(rfi.id, RFIUpdate(status="open"), actor_role="manager")
        assert updated.status == "open"
        assert updated.response_due_date is not None

    @pytest.mark.asyncio
    async def test_empty_patch_is_a_noop_returning_the_row(self) -> None:
        """An update whose model_dump(exclude_unset) is empty returns the row
        unchanged - never an error, never a spurious write."""
        service = _make_service()
        rfi = await service.create_rfi(
            RFICreate(project_id=uuid.uuid4(), subject="keep", question="y", status="open"),
        )
        same = await service.update_rfi(rfi.id, RFIUpdate(), actor_role="editor")
        assert same.id == rfi.id
        assert same.subject == "keep"

    @pytest.mark.asyncio
    async def test_manager_reassign_syncs_ball_in_court(self) -> None:
        """Changing assigned_to without an explicit ball_in_court re-points
        the ball to the new assignee."""
        service = _make_service()
        rfi = await service.create_rfi(
            RFICreate(project_id=uuid.uuid4(), subject="x", question="y", status="open"),
        )
        new_assignee = str(uuid.uuid4())
        updated = await service.update_rfi(rfi.id, RFIUpdate(assigned_to=new_assignee), actor_role="manager")
        assert str(updated.assigned_to) == new_assignee
        assert str(updated.ball_in_court) == new_assignee


# ── respond_to_rfi: ball-in-court flips back to originator ───────────────


class TestRespondBallInCourt:
    @pytest.mark.asyncio
    async def test_answer_returns_ball_to_raiser(self) -> None:
        service = _make_service()
        raiser = str(uuid.uuid4())
        assignee = str(uuid.uuid4())
        rfi = await service.create_rfi(
            RFICreate(
                project_id=uuid.uuid4(),
                subject="x",
                question="y",
                status="open",
                assigned_to=assignee,
            ),
            user_id=raiser,
        )
        # The ball starts with the assignee.
        assert str(rfi.ball_in_court) == assignee
        answered = await service.respond_to_rfi(
            rfi.id, "Here is the answer.", responded_by=assignee, actor_role="editor"
        )
        assert answered.status == "answered"
        # ... and flips back to the originator for review.
        assert str(answered.ball_in_court) == raiser

    @pytest.mark.asyncio
    async def test_respond_to_answered_rfi_is_rejected(self) -> None:
        """A second respond on an already-answered RFI is a 400 (answered is
        not an allowed source state for the answer transition)."""
        service = _make_service()
        assignee = str(uuid.uuid4())
        rfi = await service.create_rfi(
            RFICreate(
                project_id=uuid.uuid4(),
                subject="x",
                question="y",
                status="open",
                assigned_to=assignee,
            ),
        )
        await service.respond_to_rfi(rfi.id, "First.", responded_by=assignee, actor_role="editor")
        with pytest.raises(HTTPException) as exc:
            await service.respond_to_rfi(rfi.id, "Second.", responded_by=assignee, actor_role="editor")
        assert exc.value.status_code == 400


# ── delete_rfi ───────────────────────────────────────────────────────────


class TestDeleteRFI:
    @pytest.mark.asyncio
    async def test_delete_removes_row_and_publishes(self, monkeypatch) -> None:
        from app.modules.rfi import service as svc_mod

        published: list[str] = []

        async def _capture(name: str, data: dict, source_module: str = "") -> None:
            published.append(name)

        service = _make_service()
        rfi = await service.create_rfi(
            RFICreate(project_id=uuid.uuid4(), subject="x", question="y"),
            user_id=str(uuid.uuid4()),
        )
        # Patch the module-level publisher so we assert the lifecycle event
        # without standing up the real event bus.
        monkeypatch.setattr(svc_mod, "_safe_publish", _capture)
        await service.delete_rfi(rfi.id, actor_id="op-1")

        assert await service.repo.get_by_id(rfi.id) is None
        assert "rfi.deleted" in published

    @pytest.mark.asyncio
    async def test_delete_missing_rfi_raises_404(self) -> None:
        service = _make_service()
        with pytest.raises(HTTPException) as exc:
            await service.delete_rfi(uuid.uuid4(), actor_id="op-1")
        assert exc.value.status_code == 404


# ── add_attachment ───────────────────────────────────────────────────────


class TestAddAttachment:
    @pytest.mark.asyncio
    async def test_appends_in_order(self) -> None:
        service = _make_service()
        rfi = await service.create_rfi(
            RFICreate(project_id=uuid.uuid4(), subject="x", question="y"),
        )
        await service.add_attachment(rfi.id, "rfi/attachments/a.pdf")
        out = await service.add_attachment(rfi.id, "rfi/attachments/b.pdf")
        assert out.attachments == ["rfi/attachments/a.pdf", "rfi/attachments/b.pdf"]

    @pytest.mark.asyncio
    async def test_first_attachment_on_empty_column(self) -> None:
        service = _make_service()
        rfi = await service.create_rfi(
            RFICreate(project_id=uuid.uuid4(), subject="x", question="y"),
        )
        assert rfi.attachments == []
        out = await service.add_attachment(rfi.id, "rfi/attachments/only.png")
        assert out.attachments == ["rfi/attachments/only.png"]


# ── get_stats (stub-session branches) ────────────────────────────────────


class TestGetStatsUnit:
    @pytest.mark.asyncio
    async def test_empty_project_returns_zeros(self) -> None:
        service = _make_service()
        stats = await service.get_stats(uuid.uuid4())
        assert stats.total == 0
        assert stats.open == 0
        assert stats.overdue == 0
        assert stats.avg_days_to_response is None
        assert stats.by_status == {}

    @pytest.mark.asyncio
    async def test_avg_days_to_response_is_computed(self) -> None:
        """An answered RFI with created_at and responded_at 10 days apart
        contributes ~10.0 to the average."""
        service = _make_service()
        pid = uuid.uuid4()
        rfi = await service.create_rfi(
            RFICreate(project_id=pid, subject="x", question="y", status="open"),
        )
        created = datetime.now(UTC) - timedelta(days=10)
        rfi.created_at = created
        rfi.status = "answered"
        rfi.official_response = "done"
        rfi.responded_at = datetime.now(UTC).isoformat()

        stats = await service.get_stats(pid)
        assert stats.total == 1
        assert stats.by_status.get("answered") == 1
        assert stats.avg_days_to_response is not None
        assert 9.0 <= stats.avg_days_to_response <= 11.0

    @pytest.mark.asyncio
    async def test_cost_and_schedule_impact_counts(self) -> None:
        service = _make_service()
        pid = uuid.uuid4()
        await service.create_rfi(
            RFICreate(
                project_id=pid,
                subject="cost",
                question="y",
                cost_impact=True,
                cost_impact_value="100.00",
            ),
        )
        await service.create_rfi(
            RFICreate(
                project_id=pid,
                subject="sched",
                question="y",
                schedule_impact=True,
                schedule_impact_days=3,
            ),
        )
        stats = await service.get_stats(pid)
        assert stats.cost_impact_count == 1
        assert stats.schedule_impact_count == 1


# ── sanity: the scan cap constant is consistent with the response due days ──


def test_response_due_days_is_a_sane_constant() -> None:
    assert isinstance(_RFI_RESPONSE_DUE_DAYS, int)
    assert _RFI_RESPONSE_DUE_DAYS > 0
