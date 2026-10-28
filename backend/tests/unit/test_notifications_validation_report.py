# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Tests for the validation-report -> notification bridge (Lane A).

The notifications module subscribes to ``validation.report.created`` and
rolls a failing validation report up into ONE summary notification per
recipient (the project owner + the user who ran the validation). Clean
``passed`` reports stay silent; a report with N failing rules still
produces a single notification, never one-per-rule.

The handler loads the ``ValidationReport`` row, resolves the project owner,
and calls ``NotificationService.notify_users``. We drive it with a DB-free
fake session and a recording notification service, mirroring
``test_procurement_events.py`` so the suite runs without booting
PostgreSQL.

The tests are written as files only; per the parallel-run rules they are
not executed here.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from app.modules.notifications import events as notif_events

# ── Fakes ───────────────────────────────────────────────────────────────────


class _FakeReport:
    def __init__(
        self,
        *,
        report_id: uuid.UUID,
        project_id: uuid.UUID,
        status: str,
        error_count: int,
        warning_count: int,
        created_by: uuid.UUID | None,
        target_type: str = "boq",
        target_id: str = "",
    ) -> None:
        self.id = report_id
        self.project_id = project_id
        self.status = status
        self.error_count = error_count
        self.warning_count = warning_count
        self.created_by = created_by
        self.target_type = target_type
        self.target_id = target_id or str(uuid.uuid4())


class _FakeSession:
    def __init__(self, report: _FakeReport | None) -> None:
        self._report = report
        self.committed = False

    async def __aenter__(self) -> _FakeSession:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def get(self, _model: Any, _pk: Any) -> Any:
        return self._report

    async def commit(self) -> None:
        self.committed = True


class _RecordingNotificationService:
    """Captures notify_users / create calls across instances."""

    calls: list[dict[str, Any]] = []

    def __init__(self, _session: Any) -> None:
        pass

    async def notify_users(self, user_ids: list[Any], **kwargs: Any) -> list[Any]:
        type(self).calls.append({"recipients": [str(u) for u in user_ids], **kwargs})
        return []

    async def create(self, user_id: Any, **kwargs: Any) -> Any:
        type(self).calls.append({"recipients": [str(user_id)], **kwargs})
        return None


@pytest.fixture
def harness(monkeypatch: pytest.MonkeyPatch):
    """Patch the notifications handler's collaborators with recorders."""
    _RecordingNotificationService.calls = []

    owner_id = uuid.uuid4()

    async def _resolve_owner(_session: Any, _project_id: str) -> str:
        return str(owner_id)

    monkeypatch.setattr(notif_events, "NotificationService", _RecordingNotificationService)
    monkeypatch.setattr(notif_events, "_resolve_project_owner", _resolve_owner)

    state: dict[str, Any] = {"owner_id": owner_id, "report": None}

    def _install(report: _FakeReport | None) -> None:
        state["report"] = report
        monkeypatch.setattr(notif_events, "async_session_factory", lambda: _FakeSession(report))

    state["install"] = _install
    return state


def _event(report_id: uuid.UUID, project_id: uuid.UUID) -> notif_events.Event:
    return notif_events.Event(
        name="validation.report.created",
        data={
            "report_id": str(report_id),
            "project_id": str(project_id),
            "target_type": "boq",
            "target_id": str(uuid.uuid4()),
            "status": "errors",
        },
        source_module="oe_validation",
    )


# ── Tests ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_errors_report_notifies_owner_and_creator_once(harness) -> None:
    project_id = uuid.uuid4()
    report_id = uuid.uuid4()
    creator_id = uuid.uuid4()
    report = _FakeReport(
        report_id=report_id,
        project_id=project_id,
        status="errors",
        error_count=12,
        warning_count=3,
        created_by=creator_id,
    )
    harness["install"](report)

    await notif_events._on_validation_report_created(_event(report_id, project_id))

    calls = _RecordingNotificationService.calls
    # ONE rollup call (notify_users), not one-per-rule.
    assert len(calls) == 1
    call = calls[0]
    assert call["notification_type"] == "validation_errors"
    assert call["entity_type"] == "validation_report"
    assert call["entity_id"] == str(report_id)
    # Both the owner and the run-creator are recipients, de-duplicated.
    assert set(call["recipients"]) == {str(harness["owner_id"]), str(creator_id)}
    assert call["body_context"]["error_count"] == 12
    assert call["body_context"]["warning_count"] == 3


@pytest.mark.asyncio
async def test_warnings_report_uses_warning_type(harness) -> None:
    project_id = uuid.uuid4()
    report_id = uuid.uuid4()
    report = _FakeReport(
        report_id=report_id,
        project_id=project_id,
        status="warnings",
        error_count=0,
        warning_count=5,
        created_by=None,
    )
    harness["install"](report)

    await notif_events._on_validation_report_created(_event(report_id, project_id))

    calls = _RecordingNotificationService.calls
    assert len(calls) == 1
    assert calls[0]["notification_type"] == "validation_warnings"
    # No creator -> only the owner is notified.
    assert calls[0]["recipients"] == [str(harness["owner_id"])]


@pytest.mark.asyncio
async def test_passed_report_is_silent(harness) -> None:
    project_id = uuid.uuid4()
    report_id = uuid.uuid4()
    report = _FakeReport(
        report_id=report_id,
        project_id=project_id,
        status="passed",
        error_count=0,
        warning_count=0,
        created_by=uuid.uuid4(),
    )
    harness["install"](report)

    await notif_events._on_validation_report_created(_event(report_id, project_id))

    assert _RecordingNotificationService.calls == []


@pytest.mark.asyncio
async def test_missing_report_is_noop(harness) -> None:
    harness["install"](None)
    await notif_events._on_validation_report_created(_event(uuid.uuid4(), uuid.uuid4()))
    assert _RecordingNotificationService.calls == []
