"""Tests for the automated progress report (item 15).

Covers the bounded increment shipped under reporting + progress:

1. The ``progress_report`` value is accepted by the report-type enums on
   ``GenerateReportRequest`` and ``ReportTemplateCreate``.
2. The progress module's two new reporting queries
   (``get_latest_project_entry`` / ``get_entries_for_period``) return the
   right rows against PostgreSQL.
3. ``ReportingService._build_default_snapshot`` assembles a ``progress``
   section (and a ``photos`` section when photos exist) for the
   ``progress_report`` type.
4. The renderer emits a completion block and an image gallery for the
   ``progress`` / ``photos`` sections.
5. ``ReportingService.dispatch_report_email`` sends the rendered body to
   the template recipients via the email service (memory backend).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.progress.models import ProgressEntry
from app.modules.progress.repository import ProgressRepository
from app.modules.reporting.renderer import ReportRenderer
from app.modules.reporting.schemas import GenerateReportRequest, ReportTemplateCreate
from app.modules.reporting.service import ReportingService
from tests._pg import transactional_session

# ── Enum validation ────────────────────────────────────────────────────────


def test_generate_request_accepts_progress_report() -> None:
    req = GenerateReportRequest(
        project_id=uuid.uuid4(),
        report_type="progress_report",
        title="Weekly Progress",
        format="html",
    )
    assert req.report_type == "progress_report"


def test_template_create_accepts_progress_report() -> None:
    tmpl = ReportTemplateCreate(
        name="Weekly Progress",
        report_type="progress_report",
    )
    assert tmpl.report_type == "progress_report"


def test_generate_request_rejects_unknown_report_type() -> None:
    with pytest.raises(ValueError):  # noqa: PT011 (pydantic raises ValidationError <: ValueError)
        GenerateReportRequest(
            project_id=uuid.uuid4(),
            report_type="bogus_type",
            title="x",
            format="html",
        )


# ── Renderer: progress + photos blocks ─────────────────────────────────────


def test_renderer_progress_block_shows_overall_and_milestones() -> None:
    html_out = ReportRenderer().render_html(
        report_type="progress_report",
        title="Weekly Progress",
        project_name="Skyline Tower",
        template_data=None,
        data_snapshot={
            "progress": {
                "overall_pct": 45.0,
                "as_of_date": "2026-06-01T08:00:00+00:00",
                "recorded_by": "Field Team",
                "milestone_status": [
                    {"period": "2026-W22", "percent": 45.0, "entry_count": 3},
                ],
            },
        },
        generated_at="2026-06-01T10:00:00Z",
    )
    assert "<h2>Field Progress</h2>" in html_out
    assert "45.0%" in html_out
    assert "2026-W22" in html_out
    assert "3 entries" in html_out


def test_renderer_photo_gallery_emits_escaped_img_tags() -> None:
    html_out = ReportRenderer().render_html(
        report_type="progress_report",
        title="Weekly Progress",
        project_name="Skyline Tower",
        template_data=None,
        data_snapshot={
            "photos": {
                "photo_gallery": [
                    "/files/photo1.jpg",
                    '/files/"evil".jpg',
                ],
            },
        },
        generated_at="2026-06-01T10:00:00Z",
    )
    assert "<h2>Site Photos</h2>" in html_out
    assert 'src="/files/photo1.jpg"' in html_out
    # The quote in the second URL must be attribute-escaped, never raw.
    assert '/files/"evil".jpg' not in html_out
    assert "&quot;evil&quot;" in html_out


def test_renderer_photo_gallery_skips_section_when_no_photos() -> None:
    html_out = ReportRenderer().render_html(
        report_type="progress_report",
        title="Weekly Progress",
        project_name="Skyline Tower",
        template_data=None,
        data_snapshot={"photos": {"photo_gallery": []}},
        generated_at="2026-06-01T10:00:00Z",
    )
    # Empty gallery → the section is skipped entirely.
    assert "<h2>Site Photos</h2>" not in html_out


# ── Progress repository queries ────────────────────────────────────────────


@pytest_asyncio.fixture
async def fk_free_session() -> AsyncSession:
    """Session with FK triggers disabled so we can insert progress rows
    without provisioning a full project / BOQ position graph."""
    async with transactional_session(disable_fks=True) as s:
        yield s


@pytest.mark.asyncio
async def test_get_latest_project_entry_returns_newest_project_level(fk_free_session: AsyncSession) -> None:
    repo = ProgressRepository(fk_free_session)
    project_id = uuid.uuid4()
    now = datetime.now(UTC)

    # Older project-level reading.
    fk_free_session.add(
        ProgressEntry(
            project_id=project_id,
            boq_position_id=None,
            period_label="2026-W21",
            percent_complete=30.0,
            recorded_at=now - timedelta(days=7),
        )
    )
    # Newer project-level reading.
    fk_free_session.add(
        ProgressEntry(
            project_id=project_id,
            boq_position_id=None,
            period_label="2026-W22",
            percent_complete=45.0,
            recorded_by="Maria",
            recorded_at=now,
        )
    )
    # A position-level reading must be ignored by get_latest_project_entry.
    fk_free_session.add(
        ProgressEntry(
            project_id=project_id,
            boq_position_id=uuid.uuid4(),
            period_label="2026-W22",
            percent_complete=99.0,
            recorded_at=now + timedelta(hours=1),
        )
    )
    await fk_free_session.flush()

    latest = await repo.get_latest_project_entry(project_id)
    assert latest is not None
    assert float(latest.percent_complete) == 45.0
    assert latest.recorded_by == "Maria"


@pytest.mark.asyncio
async def test_get_entries_for_period_filters_and_orders(fk_free_session: AsyncSession) -> None:
    repo = ProgressRepository(fk_free_session)
    project_id = uuid.uuid4()
    now = datetime.now(UTC)

    fk_free_session.add(
        ProgressEntry(
            project_id=project_id,
            boq_position_id=None,
            period_label="2026-W22",
            percent_complete=40.0,
            recorded_at=now - timedelta(hours=2),
        )
    )
    fk_free_session.add(
        ProgressEntry(
            project_id=project_id,
            boq_position_id=None,
            period_label="2026-W22",
            percent_complete=45.0,
            recorded_at=now,
        )
    )
    fk_free_session.add(
        ProgressEntry(
            project_id=project_id,
            boq_position_id=None,
            period_label="2026-W21",
            percent_complete=10.0,
            recorded_at=now - timedelta(days=7),
        )
    )
    await fk_free_session.flush()

    entries = await repo.get_entries_for_period(project_id, "2026-W22")
    assert len(entries) == 2
    # Newest-first ordering.
    assert float(entries[0].percent_complete) == 45.0


# ── Snapshot assembly (service) ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_build_default_snapshot_includes_progress(fk_free_session: AsyncSession) -> None:
    project_id = uuid.uuid4()
    period_label = datetime.now(UTC).strftime("%Y-W%V")

    fk_free_session.add(
        ProgressEntry(
            project_id=project_id,
            boq_position_id=None,
            period_label=period_label,
            percent_complete=62.5,
            recorded_by="Worker",
            recorded_at=datetime.now(UTC),
            photos=["/files/a.jpg", "/files/b.jpg"],
        )
    )
    await fk_free_session.flush()

    service = ReportingService(fk_free_session)
    snapshot = await service._build_default_snapshot(
        project_id,
        "progress_report",
        currency="USD",
    )
    assert snapshot is not None
    assert snapshot["progress"]["overall_pct"] == 62.5
    assert snapshot["progress"]["recorded_by"] == "Worker"
    assert snapshot["photos"]["photo_gallery"] == ["/files/a.jpg", "/files/b.jpg"]
    # The current period milestone summary is present.
    assert snapshot["progress"]["milestone_status"][0]["period"] == period_label


# ── Email dispatch ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_dispatch_report_email_sends_to_addresses(monkeypatch: pytest.MonkeyPatch) -> None:
    """``dispatch_report_email`` fetches the rendered body and sends one
    message per resolved recipient via the email service."""
    from app.core.email.memory import MemoryEmailBackend
    from app.core.email.service import EmailService

    backend = MemoryEmailBackend()
    # The method imports get_email_service lazily from app.core.email.service;
    # patch it there so the memory backend is used.
    import app.core.email.service as email_svc_mod

    monkeypatch.setattr(email_svc_mod, "get_email_service", lambda: EmailService(backend))

    svc = ReportingService.__new__(ReportingService)
    svc.session = SimpleNamespace()

    report = SimpleNamespace(id=uuid.uuid4(), title="Weekly Progress")

    async def _fake_content(_rid: uuid.UUID) -> tuple[Any, str]:
        return report, "<html><body>rendered</body></html>"

    svc.get_report_content = _fake_content  # type: ignore[assignment]

    sent = await svc.dispatch_report_email(report, ["a@example.com", "b@example.com"])
    assert sent == 2
    assert len(backend.sent) == 2
    assert {m.to for m in backend.sent} == {"a@example.com", "b@example.com"}
    assert backend.sent[0].subject == "Progress Report: Weekly Progress - OpenConstructionERP"
    assert "<body><p" in backend.sent[0].html_body  # the brand line opens the body
    assert "rendered" in backend.sent[0].html_body


@pytest.mark.asyncio
async def test_dispatch_report_email_no_recipients_is_noop() -> None:
    svc = ReportingService.__new__(ReportingService)
    svc.session = SimpleNamespace()
    sent = await svc.dispatch_report_email(SimpleNamespace(id=uuid.uuid4(), title="x"), [])
    assert sent == 0
