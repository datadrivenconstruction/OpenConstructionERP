"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Tests for the reporting renderer wired into ReportingService.

Pinned by W23 P0 audit (task #252): before the renderer existed,
``ReportingService.generate_report`` persisted a metadata row but the
``storage_key`` was always ``None`` and there was no endpoint to fetch
the rendered body. The history panels in /reporting and /reports listed
rows that couldn't be opened. These tests assert that:

1. The pure ``ReportRenderer`` emits a complete HTML document that
   contains the report title, project name, section headings, and the
   data-snapshot values (HTML-escaped).
2. ``ReportingService.generate_report`` invokes the renderer, persists
   the body via the storage backend, and writes the resulting key onto
   the ``GeneratedReport`` row so the ``/reports/{id}/content`` endpoint
   can find it.
3. ``ReportingService.get_report_content`` returns the previously stored
   body byte-for-byte.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from app.modules.reporting.renderer import ReportRenderer
from app.modules.reporting.schemas import GenerateReportRequest
from app.modules.reporting.service import ReportingService

PROJECT_ID = uuid.uuid4()


# ── In-memory stubs (no DB, no real storage backend) ───────────────────────


class _InMemoryStorage:
    """Stub StorageBackend — just records puts in a dict."""

    def __init__(self) -> None:
        self.blobs: dict[str, bytes] = {}

    async def put(self, key: str, content: bytes) -> None:
        self.blobs[key] = content

    async def get(self, key: str) -> bytes:
        if key not in self.blobs:
            raise FileNotFoundError(key)
        return self.blobs[key]


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

    async def update(self, report: Any) -> Any:
        self.rows[report.id] = report
        return report

    async def get_by_id(self, report_id: uuid.UUID) -> Any:
        return self.rows.get(report_id)


class _StubTemplateRepo:
    async def get_by_id(self, _tid: uuid.UUID) -> None:
        return None


def _make_service(storage: _InMemoryStorage) -> ReportingService:
    """Build a service wired to the in-memory storage stub.

    The service uses ``app.core.storage.get_storage_backend`` via local
    imports inside ``generate_report`` / ``get_report_content``. We patch
    that symbol per-test through monkeypatch (see the fixture below).
    """
    svc = ReportingService.__new__(ReportingService)
    # Session needs an ``execute`` for the project-name lookup fallback —
    # we make it raise so the renderer falls back to the UUID, which keeps
    # the renderer happy without bringing the projects module into the
    # test surface.
    svc.session = SimpleNamespace(get=_raise_anything, execute=_raise_anything)
    svc.report_repo = _StubReportRepo()
    svc.template_repo = _StubTemplateRepo()
    svc.kpi_repo = SimpleNamespace()
    return svc


async def _raise_anything(*_args: Any, **_kwargs: Any) -> Any:
    raise RuntimeError("session not wired in this unit test")


@pytest.fixture
def storage(monkeypatch: pytest.MonkeyPatch) -> _InMemoryStorage:
    """Provide an in-memory storage backend and patch the factory.

    The service imports ``get_storage_backend`` lazily inside
    ``generate_report`` / ``get_report_content`` so we patch the
    underlying ``app.core.storage`` module — patching the lazy import
    site directly would race with module evaluation.
    """
    backend = _InMemoryStorage()
    import app.core.storage as storage_mod

    monkeypatch.setattr(storage_mod, "get_storage_backend", lambda: backend)
    return backend


# ── Pure renderer tests ───────────────────────────────────────────────────


def test_renderer_emits_html_document_with_title_and_sections() -> None:
    """The renderer must produce a complete HTML doc that includes the
    title, the project name, and at least one section heading sourced
    from the template_data.sections list."""
    html_out = ReportRenderer().render_html(
        report_type="project_status",
        title="Q1 Status",
        project_name="Skyline Tower",
        template_data={
            "sections": [
                {"id": "header", "title": "Project Overview"},
                {"id": "kpi", "title": "Key Performance Indicators"},
            ]
        },
        data_snapshot={
            "header": {"name": "Skyline Tower", "status": "active"},
            "kpi": {"cpi": "1.02", "spi": "0.95"},
        },
        generated_at="2026-05-27T10:00:00Z",
    )

    assert html_out.startswith("<!DOCTYPE html>")
    assert "</html>" in html_out
    assert "<title>Q1 Status</title>" in html_out
    assert "Skyline Tower" in html_out
    # Section headings rendered
    assert "<h2>Project Overview</h2>" in html_out
    assert "<h2>Key Performance Indicators</h2>" in html_out
    # Data-snapshot scalar values surface inside the table cells
    assert "1.02" in html_out
    assert "0.95" in html_out


def test_renderer_html_escapes_untrusted_strings() -> None:
    """Raw HTML tags inside titles / values must not survive the render —
    same threat model the schema-layer ``_strip_html`` guard articulates."""
    html_out = ReportRenderer().render_html(
        report_type="project_status",
        title="Q1 <script>alert(1)</script> Status",
        project_name='<img src=x onerror="alert(1)">',
        template_data=None,
        data_snapshot={"header": {"note": "<b>bold</b>"}},
        generated_at="2026-05-27T10:00:00Z",
    )

    # The raw tag must be gone from the body output.
    assert "<script>alert(1)</script>" not in html_out
    assert '<img src=x onerror="alert(1)">' not in html_out
    # And the escaped form must be present (proving the value was preserved
    # for display, just neutralised).
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html_out


def test_renderer_handles_empty_snapshot_with_explicit_notice() -> None:
    """An empty data_snapshot must NOT yield a body-less <main>. The
    renderer should surface a "no data available" notice so cron-worker
    failures (every module returned nothing) are diagnosable."""
    html_out = ReportRenderer().render_html(
        report_type="project_status",
        title="Empty",
        project_name="Phantom",
        template_data=None,
        data_snapshot=None,
        generated_at="2026-05-27T10:00:00Z",
    )
    assert "No data available" in html_out


def test_renderer_renders_list_of_dicts_as_table() -> None:
    """A list-of-dicts payload (e.g. recent_incidents) should render as a
    multi-column table, not a flat <ul>."""
    html_out = ReportRenderer().render_html(
        report_type="safety_report",
        title="Safety",
        project_name="Skyline",
        template_data=None,
        data_snapshot={
            "incidents": [
                {"date": "2026-05-01", "type": "near-miss"},
                {"date": "2026-05-15", "type": "first-aid"},
            ]
        },
        generated_at="2026-05-27T10:00:00Z",
    )
    assert "<th>Date</th>" in html_out
    assert "<th>Type</th>" in html_out
    assert "near-miss" in html_out
    assert "first-aid" in html_out


# ── Service-level integration tests ───────────────────────────────────────


@pytest.mark.asyncio
async def test_generate_report_stores_rendered_html_under_storage_key(
    storage: _InMemoryStorage,
) -> None:
    """End-to-end: ``generate_report`` must invoke the renderer, persist
    the HTML body via the storage backend, and write the resulting
    ``storage_key`` onto the report row. This was the W23 P0 fix —
    previously ``storage_key`` was always None."""
    svc = _make_service(storage)

    report = await svc.generate_report(
        GenerateReportRequest(
            project_id=PROJECT_ID,
            report_type="project_status",
            title="Q1 Status",
            format="html",
            data_snapshot={"header": {"name": "Skyline"}, "kpi": {"cpi": "1.05"}},
        ),
        user_id=str(uuid.uuid4()),
    )

    # The row was persisted with a non-null storage_key pointing into the
    # storage backend, and the backend now holds matching bytes.
    assert report.storage_key is not None
    assert report.storage_key in storage.blobs
    body = storage.blobs[report.storage_key].decode("utf-8")
    assert "<!DOCTYPE html>" in body
    assert "Q1 Status" in body
    assert "1.05" in body


@pytest.mark.asyncio
async def test_get_report_content_returns_stored_body(
    storage: _InMemoryStorage,
) -> None:
    """``get_report_content`` round-trips the previously stored HTML."""
    svc = _make_service(storage)

    report = await svc.generate_report(
        GenerateReportRequest(
            project_id=PROJECT_ID,
            report_type="project_status",
            title="Round-Trip",
            format="html",
            data_snapshot={"header": {"name": "Skyline"}},
        ),
    )

    fetched_report, fetched_html = await svc.get_report_content(report.id)
    assert fetched_report.id == report.id
    assert "<!DOCTYPE html>" in fetched_html
    assert "Round-Trip" in fetched_html
    # Byte-equal to what the backend persisted.
    assert fetched_html.encode("utf-8") == storage.blobs[report.storage_key]


@pytest.mark.asyncio
async def test_generate_report_survives_storage_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If the storage backend errors during ``put``, the metadata row
    must still be returned with ``storage_key=None``. Losing the audit
    trail because the renderer failed would be worse than a degraded
    "couldn't render" history row."""

    class _BrokenStorage:
        async def put(self, *_a: Any, **_kw: Any) -> None:
            raise RuntimeError("disk full")

        async def get(self, *_a: Any, **_kw: Any) -> bytes:
            raise RuntimeError("disk full")

    import app.core.storage as storage_mod

    monkeypatch.setattr(storage_mod, "get_storage_backend", lambda: _BrokenStorage())

    svc = _make_service(_InMemoryStorage())  # storage stub is unused here

    report = await svc.generate_report(
        GenerateReportRequest(
            project_id=PROJECT_ID,
            report_type="project_status",
            title="Resilient",
            format="html",
            data_snapshot={"header": {"name": "Skyline"}},
        ),
    )

    # Row persisted, but storage_key never made it on.
    assert report.id is not None
    assert report.storage_key is None
