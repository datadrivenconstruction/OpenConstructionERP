"""Event-emission tests for the Reporting service (slice E)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from app.core.events import Event, event_bus
from app.modules.reporting.schemas import (
    GenerateReportRequest,
    KPISnapshotCreate,
    ReportScheduleRequest,
    ReportTemplateCreate,
)
from app.modules.reporting.service import ReportingService

PROJECT_ID = uuid.uuid4()


# ── Stub repositories ──────────────────────────────────────────────────────


class _StubKpiRepo:
    def __init__(self) -> None:
        self.rows: dict[uuid.UUID, Any] = {}

    async def create(self, snapshot: Any) -> Any:
        if getattr(snapshot, "id", None) is None:
            snapshot.id = uuid.uuid4()
        now = datetime.now(UTC)
        snapshot.created_at = now
        snapshot.updated_at = now
        self.rows[snapshot.id] = snapshot
        return snapshot


class _StubTemplateRepo:
    def __init__(self) -> None:
        self.rows: dict[uuid.UUID, Any] = {}

    async def create(self, template: Any) -> Any:
        if getattr(template, "id", None) is None:
            template.id = uuid.uuid4()
        now = datetime.now(UTC)
        template.created_at = now
        template.updated_at = now
        self.rows[template.id] = template
        return template

    async def get_by_id(self, template_id: uuid.UUID) -> Any:
        return self.rows.get(template_id)

    async def update(self, template: Any) -> Any:
        self.rows[template.id] = template
        return template


class _StubReportRepo:
    def __init__(self) -> None:
        self.rows: dict[uuid.UUID, Any] = {}

    async def create(self, report: Any) -> Any:
        if getattr(report, "id", None) is None:
            report.id = uuid.uuid4()
        now = datetime.now(UTC)
        report.created_at = now
        report.updated_at = now
        self.rows[report.id] = report
        return report


def _make_service() -> ReportingService:
    svc = ReportingService.__new__(ReportingService)
    svc.session = SimpleNamespace()
    svc.kpi_repo = _StubKpiRepo()
    svc.template_repo = _StubTemplateRepo()
    svc.report_repo = _StubReportRepo()
    return svc


@pytest.fixture
def captured_events():
    captured: list[Event] = []

    async def _capture(event: Event) -> None:
        captured.append(event)

    event_bus.subscribe("*", _capture)
    try:
        yield captured
    finally:
        event_bus.unsubscribe("*", _capture)


# ── Tests ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_kpi_snapshot_emits_event(captured_events: list[Event]) -> None:
    svc = _make_service()

    snapshot = await svc.create_kpi_snapshot(
        KPISnapshotCreate(
            project_id=PROJECT_ID,
            snapshot_date="2026-04-26",
            cpi="1.05",
            spi="0.98",
        )
    )

    matches = [e for e in captured_events if e.name == "reporting.kpi_snapshot.created"]
    assert len(matches) == 1
    payload = matches[0].data
    assert payload["snapshot_id"] == str(snapshot.id)
    assert payload["project_id"] == str(PROJECT_ID)
    assert payload["cpi"] == "1.05"
    assert payload["spi"] == "0.98"
    assert matches[0].source_module == "oe_reporting"


@pytest.mark.asyncio
async def test_create_template_emits_event(captured_events: list[Event]) -> None:
    svc = _make_service()
    user_id = str(uuid.uuid4())

    template = await svc.create_template(
        ReportTemplateCreate(name="Custom", report_type="cost_report"),
        user_id=user_id,
    )

    matches = [e for e in captured_events if e.name == "reporting.template.created"]
    assert len(matches) == 1
    payload = matches[0].data
    assert payload["template_id"] == str(template.id)
    assert payload["report_type"] == "cost_report"
    assert payload["is_system"] is False
    assert payload["created_by"] == user_id


@pytest.mark.asyncio
async def test_schedule_template_emits_event(captured_events: list[Event]) -> None:
    svc = _make_service()
    template = await svc.create_template(
        ReportTemplateCreate(name="Custom", report_type="cost_report")
    )
    captured_events.clear()

    await svc.schedule_template(
        template.id,
        ReportScheduleRequest(schedule_cron="0 9 * * 1", recipients=["a@b.com"]),
    )

    matches = [e for e in captured_events if e.name == "reporting.template.scheduled"]
    assert len(matches) == 1
    payload = matches[0].data
    assert payload["template_id"] == str(template.id)
    assert payload["schedule_cron"] == "0 9 * * 1"
    assert payload["is_scheduled"] is True
    assert payload["next_run_at"] is not None


@pytest.mark.asyncio
async def test_generate_report_emits_event(captured_events: list[Event]) -> None:
    svc = _make_service()
    user_id = str(uuid.uuid4())

    report = await svc.generate_report(
        GenerateReportRequest(
            project_id=PROJECT_ID,
            report_type="project_status",
            title="Q1 Status",
            format="pdf",
        ),
        user_id=user_id,
    )

    matches = [e for e in captured_events if e.name == "reporting.report.generated"]
    assert len(matches) == 1
    payload = matches[0].data
    assert payload["report_id"] == str(report.id)
    assert payload["project_id"] == str(PROJECT_ID)
    assert payload["report_type"] == "project_status"
    assert payload["format"] == "pdf"
    assert payload["generated_by"] == user_id
