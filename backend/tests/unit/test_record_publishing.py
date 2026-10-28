# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Database-free unit tests for the record-publishing pure helpers.

These cover the deterministic pieces of the publish-and-distribute flow -
storage key derivation, the forwarded URLs, filename sanitisation and the
record-source registry - without touching a database or the storage backend.
"""

from __future__ import annotations

import uuid

from app.modules.record_publishing.service import (
    _RECORD_SOURCES,
    RenderedRecord,
    ack_url,
    record_storage_key,
    record_url,
    safe_filename,
    supported_kinds,
)


def test_record_storage_key_is_deterministic_and_scoped() -> None:
    project_id = uuid.UUID("11111111-1111-1111-1111-111111111111")
    transmittal_id = uuid.UUID("22222222-2222-2222-2222-222222222222")
    key = record_storage_key(project_id, transmittal_id)
    assert key == f"published_records/{project_id}/{transmittal_id}.pdf"
    # Stable across calls and independent of argument type (uuid vs str).
    assert key == record_storage_key(str(project_id), str(transmittal_id))
    # POSIX, relative, no backslashes - satisfies the storage key contract.
    assert not key.startswith("/")
    assert "\\" not in key
    assert ".." not in key.split("/")


def test_urls_embed_the_token() -> None:
    token = "abc-DEF_123"
    assert ack_url(token) == "/api/v1/file-transmittals/ack/abc-DEF_123/"
    assert record_url(token) == "/api/v1/record-publishing/record/abc-DEF_123"


def test_safe_filename_sanitises_and_forces_pdf() -> None:
    # Slashes, quotes and spaces cannot break a Content-Disposition header.
    out = safe_filename('Daily Site Diary - 2026/07/17 "final"')
    assert out.lower().endswith(".pdf")
    assert "/" not in out
    assert '"' not in out
    assert " " not in out
    # Already-good names keep their extension without doubling it.
    assert safe_filename("report.pdf") == "report.pdf"
    # Runs of separators collapse rather than pile up.
    assert "--" not in safe_filename("a///b\\\\c")


def test_safe_filename_falls_back_when_empty() -> None:
    assert safe_filename("") == "record.pdf"
    assert safe_filename("   ") == "record.pdf"
    assert safe_filename("!!!", fallback="x.pdf") == "x.pdf"


def test_supported_kinds_lists_daily_diary() -> None:
    kinds = supported_kinds()
    assert "daily_diary" in kinds
    # Sorted + no duplicates so the surface is stable for the UI.
    assert kinds == sorted(set(kinds))


def test_registry_wires_renderer_and_after_hook() -> None:
    source = _RECORD_SOURCES["daily_diary"]
    assert source.kind == "daily_diary"
    assert callable(source.render)
    # The diary source wires the after-hook that makes pdf_export_ref live.
    assert source.on_published is not None
    assert callable(source.on_published)


def test_supported_kinds_includes_meeting() -> None:
    kinds = supported_kinds()
    assert "daily_diary" in kinds
    assert "meeting" in kinds
    # Sorted + no duplicates so the surface is stable for the UI.
    assert kinds == sorted(set(kinds))


def test_meeting_source_wires_renderer() -> None:
    source = _RECORD_SOURCES["meeting"]
    assert source.kind == "meeting"
    assert callable(source.render)
    # Publishing minutes does not mutate the meeting, so there is no after-hook.
    assert source.on_published is None


def test_build_minutes_pdf_returns_pdf_bytes() -> None:
    # The minutes renderer is shared with the meetings export endpoint; exercise
    # it directly with stand-in rows so a regression in the extracted helper is
    # caught without a database or the full request stack.
    from types import SimpleNamespace

    from app.modules.meetings.pdf import build_minutes_pdf, minutes_pdf_filename

    meeting = SimpleNamespace(
        title="Weekly site coordination",
        meeting_number="007",
        meeting_date="2026-07-17",
        project_id=uuid.uuid4(),
    )
    minutes = SimpleNamespace(
        content={
            "title": "Weekly site coordination",
            "attendees_present": [{"name": "A. Boiko"}],
            "attendees_absent": [],
            "agenda": [{"number": 1, "topic": "Foundations", "decision": "Proceed"}],
            "action_items": [{"description": "Order rebar", "owner": "GC", "status": "open"}],
            "summary": "All on track.",
        },
        status="issued",
        issued_at=None,
    )
    pdf = build_minutes_pdf(meeting, minutes, "Demo Project")
    assert pdf.startswith(b"%PDF")
    assert len(pdf) > 500
    fname = minutes_pdf_filename(meeting, minutes.content)
    assert fname.startswith("minutes_007_")
    assert fname.endswith(".pdf")


def test_rendered_record_is_frozen() -> None:
    rendered = RenderedRecord(
        project_id=uuid.uuid4(),
        subject="Daily Site Diary - 2026-07-17",
        canonical_name="daily-site-diary-2026-07-17.pdf",
        pdf_bytes=b"%PDF-1.4 test",
        source_kind="daily_diary",
        source_id="abc",
    )
    assert rendered.pdf_bytes.startswith(b"%PDF")
    # Frozen dataclass: publish payload built from it cannot be mutated by hooks.
    raised = False
    try:
        rendered.subject = "changed"  # type: ignore[misc]
    except Exception:  # noqa: BLE001 - FrozenInstanceError is what we expect
        raised = True
    assert raised
