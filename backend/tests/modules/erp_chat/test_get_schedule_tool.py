# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The chat schedule tool has to read the fields ``GanttActivity`` actually has.

``handle_get_schedule`` read ``act.progress`` while the schema's field is
``progress_pct``. Pydantic v2 raises on an undeclared attribute, the handler
catches ``Exception`` and returns an error card, so the tool answered "Error:
'GanttActivity' object has no attribute 'progress'" for every project with a
schedule - never a Gantt.

The test builds a real :class:`GanttActivity`, which is the part that matters:
a duck-typed stub would answer any attribute name and prove nothing.
"""

from __future__ import annotations

import logging
import uuid

from app.modules.schedule.schemas import GanttActivity, GanttData, GanttSummary

_PROJECT_ID = uuid.uuid4()
_SCHEDULE_ID = uuid.uuid4()
_ACTIVITY_ID = uuid.uuid4()


def _gantt_data() -> GanttData:
    activity = GanttActivity(
        id=_ACTIVITY_ID,
        name="Erect formwork to core walls",
        start_date="2026-03-02",
        end_date="2026-03-20",
        duration_days=15,
        progress_pct=42.5,
        dependencies=[],
        parent_id=None,
        color="#3b82f6",
        boq_position_ids=[],
        wbs_code="1.2.3",
        activity_type="task",
        status="in_progress",
    )
    summary = GanttSummary(total_activities=1, completed=0, in_progress=1, delayed=0, not_started=0)
    return GanttData(activities=[activity], summary=summary)


class _StubScheduleService:
    """Stands in for ``ScheduleService``; returns the real Gantt schema objects."""

    def __init__(self, session) -> None:  # noqa: ANN001
        self.session = session

    async def list_schedules_for_project(self, project_id, limit=5):  # noqa: ANN001, ARG002
        from types import SimpleNamespace

        return [SimpleNamespace(id=_SCHEDULE_ID, name="Main construction programme")], 1

    async def get_gantt_data(self, schedule_id):  # noqa: ANN001, ARG002
        return _gantt_data()


def _patch(monkeypatch) -> None:
    """``ScheduleService`` is imported inside the handler, so patch it on its own module."""
    import app.modules.erp_chat.tools as tools_module
    import app.modules.schedule.service as schedule_service_module

    monkeypatch.setattr(schedule_service_module, "ScheduleService", _StubScheduleService)

    async def _allow(session, project_id, user_id):  # noqa: ANN001, ARG001
        return None

    monkeypatch.setattr(tools_module, "_require_project_access", _allow)


async def test_the_schedule_tool_renders_a_gantt_rather_than_an_error(monkeypatch, caplog) -> None:
    from app.modules.erp_chat.tools import handle_get_schedule

    _patch(monkeypatch)
    with caplog.at_level(logging.ERROR):
        result = await handle_get_schedule(None, {"project_id": str(_PROJECT_ID)}, "user-1")

    assert result["renderer"] == "schedule_gantt", f"{result['summary']} | {caplog.text}"
    assert result["data"]["schedule_name"] == "Main construction programme"


async def test_the_activity_progress_comes_from_progress_pct(monkeypatch) -> None:
    from app.modules.erp_chat.tools import handle_get_schedule

    _patch(monkeypatch)
    result = await handle_get_schedule(None, {"project_id": str(_PROJECT_ID)}, "user-1")

    activity = result["data"]["activities"][0]
    assert activity["progress"] == 42.5


async def test_the_declared_activity_fields_are_read_straight_off_the_schema(monkeypatch) -> None:
    """``wbs_code`` and ``status`` are required fields, so they need no getattr default."""
    from app.modules.erp_chat.tools import handle_get_schedule

    _patch(monkeypatch)
    result = await handle_get_schedule(None, {"project_id": str(_PROJECT_ID)}, "user-1")

    activity = result["data"]["activities"][0]
    assert activity["wbs_code"] == "1.2.3"
    assert activity["status"] == "in_progress"
    assert {"progress_pct", "wbs_code", "status"} <= set(GanttActivity.model_fields)
