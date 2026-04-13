"""Unit tests for :class:`FieldReportService`.

Scope:
    CRUD, status transitions (draft -> submitted -> approved), document
    linking with deduplication, summary aggregation, and edit guards.
    Repositories are stubbed so the suite doesn't need a live database.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from app.modules.fieldreports.schemas import (
    FieldReportCreate,
    FieldReportUpdate,
    WorkforceEntry,
)
from app.modules.fieldreports.service import FieldReportService

# ── Helpers / stubs ───────────────────────────────────────────────────────


def _make_service() -> FieldReportService:
    service = FieldReportService.__new__(FieldReportService)
    service.session = _StubSession()
    service.repo = _StubFieldReportRepo()
    return service


class _StubSession:
    async def refresh(self, obj: Any) -> None:
        pass


class _StubFieldReportRepo:
    def __init__(self) -> None:
        self.rows: dict[uuid.UUID, Any] = {}

    async def create(self, report: Any) -> Any:
        if getattr(report, "id", None) is None:
            report.id = uuid.uuid4()
        now = datetime.now(UTC)
        report.created_at = now
        report.updated_at = now
        # Ensure document_ids exists
        if not hasattr(report, "document_ids") or report.document_ids is None:
            report.document_ids = []
        self.rows[report.id] = report
        return report

    async def get_by_id(self, report_id: uuid.UUID) -> Any:
        return self.rows.get(report_id)

    async def list_for_project(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
        date_from: date | None = None,
        date_to: date | None = None,
        report_type: str | None = None,
        status: str | None = None,
    ) -> tuple[list[Any], int]:
        rows = [r for r in self.rows.values() if r.project_id == project_id]
        if report_type is not None:
            rows = [r for r in rows if r.report_type == report_type]
        if status is not None:
            rows = [r for r in rows if r.status == status]
        return rows[offset : offset + limit], len(rows)

    async def update_fields(self, report_id: uuid.UUID, **fields: Any) -> None:
        obj = self.rows.get(report_id)
        if obj is not None:
            for k, v in fields.items():
                setattr(obj, k, v)

    async def delete(self, report_id: uuid.UUID) -> None:
        self.rows.pop(report_id, None)

    async def all_for_project(self, project_id: uuid.UUID) -> list[Any]:
        return [r for r in self.rows.values() if r.project_id == project_id]

    async def get_by_date(self, project_id: uuid.UUID, report_date: date) -> Any:
        for r in self.rows.values():
            if r.project_id == project_id and r.report_date == report_date:
                return r
        return None

    async def get_for_month(self, project_id: uuid.UUID, year: int, month: int) -> list[Any]:
        return [
            r for r in self.rows.values()
            if r.project_id == project_id
        ]


# ── Create ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_report_with_workforce_data() -> None:
    service = _make_service()
    pid = uuid.uuid4()
    data = FieldReportCreate(
        project_id=pid,
        report_date=date(2026, 4, 13),
        report_type="daily",
        weather_condition="clear",
        workforce=[
            WorkforceEntry(trade="Carpenter", count=5, hours=8.0),
            WorkforceEntry(trade="Electrician", count=3, hours=6.5),
        ],
        work_performed="Foundation formwork installation",
    )
    report = await service.create_report(data, user_id="user-1")

    assert report.id is not None
    assert report.status == "draft"
    assert report.report_type == "daily"
    assert len(report.workforce) == 2
    assert report.workforce[0]["trade"] == "Carpenter"


@pytest.mark.asyncio
async def test_create_report_defaults_to_draft_status() -> None:
    service = _make_service()
    data = FieldReportCreate(
        project_id=uuid.uuid4(),
        report_date=date(2026, 4, 13),
    )
    report = await service.create_report(data)
    assert report.status == "draft"


# ── List ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_reports_project_scoped() -> None:
    service = _make_service()
    pid = uuid.uuid4()
    await service.create_report(
        FieldReportCreate(project_id=pid, report_date=date(2026, 4, 10))
    )
    await service.create_report(
        FieldReportCreate(project_id=uuid.uuid4(), report_date=date(2026, 4, 10))
    )

    rows, total = await service.list_reports(pid)
    assert total == 1


# ── Status transitions ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_submit_draft_report_succeeds() -> None:
    service = _make_service()
    report = await service.create_report(
        FieldReportCreate(project_id=uuid.uuid4(), report_date=date(2026, 4, 13))
    )
    result = await service.submit_report(report.id)
    assert result.status == "submitted"


@pytest.mark.asyncio
async def test_submit_non_draft_raises_400() -> None:
    from fastapi import HTTPException

    service = _make_service()
    report = await service.create_report(
        FieldReportCreate(project_id=uuid.uuid4(), report_date=date(2026, 4, 13))
    )
    report.status = "submitted"

    with pytest.raises(HTTPException) as exc_info:
        await service.submit_report(report.id)
    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_approve_submitted_report_succeeds() -> None:
    service = _make_service()
    report = await service.create_report(
        FieldReportCreate(project_id=uuid.uuid4(), report_date=date(2026, 4, 13))
    )
    report.status = "submitted"

    result = await service.approve_report(report.id, user_id="mgr-1")
    assert result.status == "approved"
    assert result.approved_by == "mgr-1"


@pytest.mark.asyncio
async def test_approve_non_submitted_raises_400() -> None:
    from fastapi import HTTPException

    service = _make_service()
    report = await service.create_report(
        FieldReportCreate(project_id=uuid.uuid4(), report_date=date(2026, 4, 13))
    )
    # still draft

    with pytest.raises(HTTPException) as exc_info:
        await service.approve_report(report.id, user_id="mgr-1")
    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_update_approved_report_raises_400() -> None:
    from fastapi import HTTPException

    service = _make_service()
    report = await service.create_report(
        FieldReportCreate(project_id=uuid.uuid4(), report_date=date(2026, 4, 13))
    )
    report.status = "approved"

    with pytest.raises(HTTPException) as exc_info:
        await service.update_report(report.id, FieldReportUpdate(notes="Change"))
    assert exc_info.value.status_code == 400


# ── Document linking ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_link_documents_merges_and_deduplicates() -> None:
    service = _make_service()
    report = await service.create_report(
        FieldReportCreate(project_id=uuid.uuid4(), report_date=date(2026, 4, 13))
    )
    report.document_ids = ["doc-1", "doc-2"]

    result = await service.link_documents(report.id, ["doc-2", "doc-3"])
    assert result.document_ids == ["doc-1", "doc-2", "doc-3"]


# ── Summary ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_summary_aggregates_workforce_and_delays() -> None:
    service = _make_service()
    pid = uuid.uuid4()
    await service.create_report(
        FieldReportCreate(
            project_id=pid,
            report_date=date(2026, 4, 10),
            workforce=[
                WorkforceEntry(trade="Carpenter", count=5, hours=8.0),
            ],
            delay_hours=2.0,
        )
    )
    await service.create_report(
        FieldReportCreate(
            project_id=pid,
            report_date=date(2026, 4, 11),
            workforce=[
                WorkforceEntry(trade="Electrician", count=3, hours=10.0),
            ],
            delay_hours=1.5,
        )
    )

    summary = await service.get_summary(pid)
    assert summary["total"] == 2
    # Carpenter: 5 * 8 = 40, Electrician: 3 * 10 = 30
    assert summary["total_workforce_hours"] == 70.0
    assert summary["total_delay_hours"] == 3.5


# ── Delete ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_delete_report_removes_from_repo() -> None:
    from fastapi import HTTPException

    service = _make_service()
    report = await service.create_report(
        FieldReportCreate(project_id=uuid.uuid4(), report_date=date(2026, 4, 13))
    )
    await service.delete_report(report.id)

    with pytest.raises(HTTPException) as exc_info:
        await service.get_report(report.id)
    assert exc_info.value.status_code == 404
