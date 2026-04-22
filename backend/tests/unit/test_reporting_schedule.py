"""Unit tests for scheduled report templates (v2.3.0).

Exercises ``ReportingService.schedule_template``, ``list_due_templates``
and ``mark_template_ran`` against an in-memory SQLite DB so we can
verify the next-run computation, pause semantics and clean-up on
invalid crons without having to spin up the full app lifespan.

Router-level tests live under ``tests/integration/`` because they need
the auth + project fixtures.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.modules.reporting.models import GeneratedReport, KPISnapshot, ReportTemplate
from app.modules.reporting.schemas import ReportScheduleRequest
from app.modules.reporting.service import ReportingService


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    """Fresh in-memory SQLite — per-test isolation.

    Scoped ``create_all(tables=[...])`` so that unrelated modules on
    ``Base.metadata`` (with FKs to tables we don't need) don't break
    the harness.
    """
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(
            Base.metadata.create_all,
            tables=[
                ReportTemplate.__table__,
                KPISnapshot.__table__,
                GeneratedReport.__table__,
            ],
        )
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as s:
        yield s
    await engine.dispose()


async def _make_template(session: AsyncSession, **overrides) -> ReportTemplate:
    template = ReportTemplate(
        name=overrides.pop("name", "Weekly Cost"),
        report_type=overrides.pop("report_type", "cost_report"),
        description="test",
        template_data={},
        is_system=False,
        metadata_={},
        **overrides,
    )
    session.add(template)
    await session.flush()
    await session.refresh(template)
    return template


class TestScheduleTemplate:
    @pytest.mark.asyncio
    async def test_attaches_cron_and_computes_next_run(self, session):
        template = await _make_template(session)
        service = ReportingService(session)

        req = ReportScheduleRequest(
            schedule_cron="0 9 * * 1",  # Mon 09:00 UTC
            recipients=["ops@example.com"],
            project_id_scope=None,
            is_scheduled=True,
        )
        updated = await service.schedule_template(template.id, req)

        assert updated.schedule_cron == "0 9 * * 1"
        assert updated.recipients == ["ops@example.com"]
        assert updated.is_scheduled is True
        # next_run_at is an ISO string ending in Z; it must be strictly
        # in the future.
        assert updated.next_run_at is not None
        assert updated.next_run_at.endswith("Z")
        next_dt = datetime.strptime(
            updated.next_run_at, "%Y-%m-%dT%H:%M:%SZ"
        ).replace(tzinfo=timezone.utc)
        assert next_dt > datetime.now(timezone.utc) - timedelta(seconds=5)
        # And it lands on a Monday at 09:00.
        assert next_dt.weekday() == 0
        assert next_dt.hour == 9
        assert next_dt.minute == 0

    @pytest.mark.asyncio
    async def test_null_cron_clears_schedule(self, session):
        template = await _make_template(
            session,
            schedule_cron="0 9 * * 1",
            is_scheduled=True,
            next_run_at="2026-05-01T09:00:00Z",
            recipients=["ops@example.com"],
        )
        service = ReportingService(session)

        req = ReportScheduleRequest(
            schedule_cron=None,
            recipients=[],
            project_id_scope=None,
            is_scheduled=False,
        )
        updated = await service.schedule_template(template.id, req)

        assert updated.schedule_cron is None
        assert updated.next_run_at is None
        assert updated.is_scheduled is False
        assert updated.recipients == []

    @pytest.mark.asyncio
    async def test_pause_without_clearing_cron(self, session):
        """``is_scheduled=False`` with a cron set keeps the expression
        but stops the worker from picking it up (empty next_run_at list)."""
        template = await _make_template(session)
        service = ReportingService(session)

        req = ReportScheduleRequest(
            schedule_cron="0 9 * * 1",
            recipients=["ops@example.com"],
            is_scheduled=False,
        )
        updated = await service.schedule_template(template.id, req)

        assert updated.schedule_cron == "0 9 * * 1"
        assert updated.is_scheduled is False
        # next_run_at is still populated so a re-enable doesn't force a
        # re-compute — but because is_scheduled is False, list_due won't
        # include it.
        assert updated.next_run_at is not None

    @pytest.mark.asyncio
    async def test_invalid_cron_raises_400(self, session):
        template = await _make_template(session)
        service = ReportingService(session)
        req = ReportScheduleRequest(
            schedule_cron="not a cron",
            recipients=[],
        )
        with pytest.raises(HTTPException) as excinfo:
            await service.schedule_template(template.id, req)
        assert excinfo.value.status_code == 400

    @pytest.mark.asyncio
    async def test_missing_template_raises_404(self, session):
        service = ReportingService(session)
        missing = uuid.uuid4()
        req = ReportScheduleRequest(schedule_cron="0 9 * * *")
        with pytest.raises(HTTPException) as excinfo:
            await service.schedule_template(missing, req)
        assert excinfo.value.status_code == 404


class TestListDueTemplates:
    @pytest.mark.asyncio
    async def test_due_templates_returned_only_when_scheduled(self, session):
        await _make_template(
            session,
            name="Due-Scheduled",
            schedule_cron="0 9 * * 1",
            is_scheduled=True,
            next_run_at="2026-04-01T09:00:00Z",
        )
        await _make_template(
            session,
            name="Due-But-Paused",
            schedule_cron="0 9 * * 1",
            is_scheduled=False,
            next_run_at="2026-04-01T09:00:00Z",
        )
        await _make_template(
            session,
            name="Future-Scheduled",
            schedule_cron="0 9 * * 1",
            is_scheduled=True,
            next_run_at="2099-01-01T09:00:00Z",
        )
        await _make_template(session, name="Never-Scheduled")

        service = ReportingService(session)
        due = await service.list_due_templates(
            as_of=datetime(2026, 5, 1, 0, 0, tzinfo=timezone.utc),
        )
        names = {t.name for t in due}
        assert names == {"Due-Scheduled"}

    @pytest.mark.asyncio
    async def test_empty_when_no_templates_scheduled(self, session):
        await _make_template(session)
        service = ReportingService(session)
        due = await service.list_due_templates(
            as_of=datetime(2026, 5, 1, 0, 0, tzinfo=timezone.utc),
        )
        assert due == []


class TestMarkTemplateRan:
    @pytest.mark.asyncio
    async def test_recomputes_next_run_after_run(self, session):
        template = await _make_template(
            session,
            schedule_cron="0 9 * * 1",
            is_scheduled=True,
            next_run_at="2026-04-20T09:00:00Z",
        )
        service = ReportingService(session)
        ran_at = datetime(2026, 4, 20, 9, 0, 30, tzinfo=timezone.utc)
        updated = await service.mark_template_ran(template, ran_at=ran_at)

        assert updated.last_run_at == "2026-04-20T09:00:30Z"
        # Next Monday is 2026-04-27.
        assert updated.next_run_at == "2026-04-27T09:00:00Z"

    @pytest.mark.asyncio
    async def test_paused_template_clears_next_run(self, session):
        template = await _make_template(
            session,
            schedule_cron="0 9 * * 1",
            is_scheduled=False,
            next_run_at="2026-04-20T09:00:00Z",
        )
        service = ReportingService(session)
        updated = await service.mark_template_ran(
            template, ran_at=datetime(2026, 4, 20, 9, 0, tzinfo=timezone.utc),
        )
        assert updated.next_run_at is None
        assert updated.last_run_at == "2026-04-20T09:00:00Z"

    @pytest.mark.asyncio
    async def test_invalid_cron_pauses_template(self, session):
        """If the stored cron stopped being valid (ops ran a bad
        migration, user force-edited DB), worker must not loop forever.
        ``mark_template_ran`` clears next_run_at and flips off is_scheduled.
        """
        template = await _make_template(
            session,
            schedule_cron="not a cron",  # Saved without validation (simulates a stale row).
            is_scheduled=True,
            next_run_at="2026-04-20T09:00:00Z",
        )
        service = ReportingService(session)
        updated = await service.mark_template_ran(
            template, ran_at=datetime(2026, 4, 20, 9, 0, tzinfo=timezone.utc),
        )
        assert updated.next_run_at is None
        assert updated.is_scheduled is False


class TestListScheduledTemplates:
    @pytest.mark.asyncio
    async def test_includes_paused_but_with_cron(self, session):
        await _make_template(session, name="Active", schedule_cron="0 9 * * 1", is_scheduled=True)
        await _make_template(session, name="Paused", schedule_cron="0 9 * * 1", is_scheduled=False)
        await _make_template(session, name="None", schedule_cron=None)
        service = ReportingService(session)
        templates = await service.list_scheduled_templates()
        names = {t.name for t in templates}
        assert names == {"Active", "Paused"}
