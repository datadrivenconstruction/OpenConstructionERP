# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Per-document-type overrides of the document appearance.

Three promises, each checked on what the generators actually print rather than
on the code path:

* With no override stored, every wired generator prints byte for byte what it
  printed when it read the workspace look alone. Compared against a render in
  which the generator's letterhead and appearance reads are forced back onto
  the workspace-only path, with reportlab in invariant mode and the clocks
  frozen, so the only thing that can differ is the look.
* An override changes its own type and nothing else.
* Every field the registry offers for a type changes that type's document.
  This is the gate on "never offer a knob the generator ignores": a field
  listed for a type whose generator does not read it fails here, and so does a
  generator that passes a key the registry does not know.
"""

from __future__ import annotations

import base64
import io
import json
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pypdf
import pytest
from reportlab import rl_config

from app.core import pdf_branding
from app.core.pdf_appearance import (
    DEFAULT_APPEARANCE,
    DOCUMENT_TYPES,
    appearance_path,
    read_appearance,
    read_overrides,
    reset_appearance,
    reset_override,
    resolve_appearance,
    sanitise_override,
    sanitise_overrides,
    write_appearance,
    write_override,
)
from tests.unit import _record_pdf_samples as record_pdf_samples

LEGAL_NAME = "Bau GmbH Müller"
FIXED_NOW = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
PROJECT_ID = uuid.UUID("11111111-2222-3333-4444-555555555555")

#: A workspace look that differs from the platform default, so "the type
#: inherits the workspace" and "the type fell back to the platform default"
#: cannot be mistaken for each other.
WORKSPACE = {"accent_color": "#123456", "footer_text": "Workspace footer"}

#: One value per overridable field, each different from both the platform
#: default and :data:`WORKSPACE`.
OVERRIDE_VALUES: dict[str, Any] = {
    "show_letterhead": False,
    "logo_align": "right",
    "accent_color": "#b22222",
    "footer_text": "Per-type footer",
    "footer_color": "#00aa44",
    "show_page_numbers": False,
    "watermark_text": "PER-TYPE MARK",
}

CONFIGURABLE = [key for key, kind in DOCUMENT_TYPES.items() if kind.configurable]


# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture
def data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """An empty data dir every no-argument read resolves to."""
    monkeypatch.setenv("OE_DATA_DIR", str(tmp_path))
    return tmp_path


def _png() -> str:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (120, 40), "#0b5394").save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


@pytest.fixture
def branded(data_dir: Path) -> Path:
    """A company profile with a logo, and a customised workspace look."""
    record = {
        "legal_name": LEGAL_NAME,
        "address": "Hauptstraße 12\n10115 Berlin",
        "registration_line": "HRB 123456 B",
        "phone": "+49 30 1234567",
        "document_logo_data_url": _png(),
    }
    (data_dir / "company_profile.json").write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
    write_appearance(WORKSPACE, data_dir)
    return data_dir


class _FrozenDatetime(datetime):
    @classmethod
    def now(cls, tz: Any = None) -> datetime:  # type: ignore[override]
        return FIXED_NOW if tz is not None else FIXED_NOW.replace(tzinfo=None)


@pytest.fixture
def deterministic(monkeypatch: pytest.MonkeyPatch) -> None:
    """Two renders of the same input give the same bytes.

    Invariant mode fixes reportlab's creation date and document id; the RFI
    footer, the punch list cover, the diary footer and both minutes renderers
    print the time of generation.
    """
    import app.modules.daily_diary.pdf_export as diary_pdf
    import app.modules.meetings.pdf as minutes_pdf
    import app.modules.meetings.router as meetings_router
    import app.modules.punchlist.service as punchlist_service
    import app.modules.rfi.pdf_export as rfi_pdf

    monkeypatch.setattr(rl_config, "invariant", 1)
    for module in (rfi_pdf, punchlist_service, diary_pdf, minutes_pdf, meetings_router):
        monkeypatch.setattr(module, "datetime", _FrozenDatetime)
    # The shared footer on the sample page prints the date of generation.
    monkeypatch.setattr(pdf_branding, "datetime", _FrozenDatetime)


# ── Documents ─────────────────────────────────────────────────────────────


def _rfi() -> bytes:
    from app.modules.rfi.pdf_export import build_rfi_pdf

    row = SimpleNamespace(
        id=PROJECT_ID,
        rfi_number="RFI-007",
        subject="Lintel detail at grid C/4",
        question="Drawing A-201 shows a precast lintel. Which governs?",
        raised_by=None,
        assigned_to=None,
        ball_in_court=None,
        status="open",
        official_response=None,
        responded_by=None,
        responded_at=None,
        cost_impact=False,
        cost_impact_value=None,
        schedule_impact=False,
        schedule_impact_days=None,
        date_required=None,
        response_due_date=None,
        attachments=[],
        priority="high",
        discipline="structural",
        created_at=FIXED_NOW,
    )
    return build_rfi_pdf(row, project_name="Residential House", currency="USD")


def _pay_application() -> bytes:
    from app.modules.contracts.aia_pdf import render_aia_application_pdf

    line = {
        "item_number": "01",
        "description": "Substructure and foundations",
        "scheduled_value": "1000.00",
        "previous_value": "0.00",
        "this_period_value": "1000.00",
        "materials_stored": "0.00",
        "total_completed_stored": "1000.00",
        "percent_complete": "100",
        "balance_to_finish": "0.00",
        "retainage": "0.00",
    }
    return render_aia_application_pdf(
        {
            "application_number": "APP-014",
            "claim_date": "2026-04-15",
            "period_end": "2026-04-30",
            "currency": "USD",
            "certification": {},
            "summary": {"contract_sum_to_date": "1000.00", "total_completed_stored": "1000.00"},
            "lines": [line],
        }
    )


def _closeout_cover() -> bytes:
    from app.modules.closeout.cover_pdf import render_cover_pdf

    return render_cover_pdf(
        {
            "project_name": "Harbour Tower",
            "project_type": "commercial",
            "completeness_pct": 60,
            "gaps": ["Fire certificate"],
            "slots": [],
            "built_at": "2026-04-15 09:00 UTC",
        }
    )


def _punch_list() -> bytes:
    from app.modules.punchlist.service import _build_reportlab_pdf

    item = SimpleNamespace(
        title="Cracked tile",
        status="open",
        priority="high",
        category="finishes",
        trade="tiling",
        assigned_to=None,
        due_date=None,
        description="Crack in sector B",
        metadata_={},
        document_id=None,
        location_x=None,
        location_y=None,
        page=None,
        photos=[],
        resolution_notes=None,
        reopen_history=[],
    )
    return _build_reportlab_pdf(PROJECT_ID, [item], {})


def _transmittal(paper: str = "A4") -> bytes:
    from app.core.paper_size import PAPER_SIZES
    from app.modules.file_transmittals.models import (
        FileTransmittal,
        FileTransmittalItem,
        FileTransmittalRecipient,
    )
    from app.modules.file_transmittals.service import _build_cover_pdf

    transmittal = FileTransmittal(
        id=PROJECT_ID,
        project_id=PROJECT_ID,
        number="TR-2026-0041",
        subject="Issue for construction",
        reason_code="for_construction",
        sent_at=FIXED_NOW,
        status="sent",
    )
    transmittal.items = [
        FileTransmittalItem(
            file_kind="drawing",
            file_id="file-1",
            file_version_snapshot="C",
            canonical_name_snapshot="A-101 Ground floor plan.pdf",
            sort_order=0,
        )
    ]
    transmittal.recipients = [
        FileTransmittalRecipient(email="site@example.com", display_name="Site", role="contractor")
    ]
    pdf = _build_cover_pdf(transmittal, PAPER_SIZES[paper])
    assert pdf is not None, "the cover sheet fell back to text"
    return pdf


def _action_items(long: bool) -> list[dict[str, Any]]:
    return [
        {"description": f"Issue revised facade drawings, sheet {index}", "owner": "Tom Ortega", "status": "open"}
        for index in range(60 if long else 2)
    ]


def _meeting_minutes(long: bool = False) -> bytes:
    from app.modules.meetings.pdf import build_minutes_pdf

    content = {
        "title": "Site coordination meeting 14",
        "meeting_date": "2026-09-18",
        "location": "Site office",
        "meeting_type": "site_meeting",
        "meeting_number": "014",
        "attendees_present": [{"name": "Maria Keller"}],
        "action_items": _action_items(long),
        "summary": "Programme on track.",
    }
    meeting = SimpleNamespace(title=content["title"], meeting_number="014", meeting_date="2026-09-18")
    minutes = SimpleNamespace(content=content, status="issued", issued_at=FIXED_NOW)
    return build_minutes_pdf(meeting, minutes, "Harbour Tower")


class _Result:
    def __init__(self, value: Any) -> None:
        self._value = value

    def scalar_one_or_none(self) -> Any:
        return self._value


class _Session:
    """Answers the two reads the export makes: the meeting, then the project name."""

    def __init__(self, *answers: Any) -> None:
        self._answers = list(answers)

    async def execute(self, _statement: Any) -> _Result:
        return _Result(self._answers.pop(0))


def _meeting_export(monkeypatch: pytest.MonkeyPatch, long: bool = False) -> bytes:
    """The minutes as the meeting page exports them, from the router's own renderer."""
    import asyncio

    import app.modules.meetings.router as meetings_router

    async def _allowed(*_args: Any, **_kwargs: Any) -> None:
        return None

    monkeypatch.setattr(meetings_router, "verify_project_access", _allowed)
    meeting = SimpleNamespace(
        id=PROJECT_ID,
        project_id=PROJECT_ID,
        title="Site coordination meeting 14",
        meeting_date="2026-09-18",
        location="Site office",
        meeting_type="site_meeting",
        meeting_number="014",
        status="completed",
        attendees=[{"name": "Maria Keller", "company": "Harbour Estates", "status": "present"}],
        agenda_items=[{"topic": "Programme"}],
        action_items=_action_items(long),
    )

    async def _export() -> bytes:
        response = await meetings_router.export_meeting_pdf(
            meeting.id, session=_Session(meeting, "Harbour Tower"), _user=uuid.uuid4()
        )
        return b"".join([chunk async for chunk in response.body_iterator])

    return asyncio.run(_export())


def _daily_report(long: bool = False) -> bytes:
    from app.modules.daily_diary.pdf_export import generate_diary_pdf

    diary = SimpleNamespace(
        diary_date="2026-09-21",
        status="approved",
        labour_count=14,
        equipment_count=3,
        weather_summary={"temp_c": 18, "conditions": "clear"},
        notes="Crane operated without restriction.",
    )
    entries = [
        SimpleNamespace(
            entry_type="work",
            entry_time=FIXED_NOW,
            title=f"Level {index} slab poured",
            description="C30/37, 55 m3, pump from grid A to D.",
        )
        for index in range(60 if long else 2)
    ]
    return generate_diary_pdf(diary, project_name="Harbour Tower", entries=entries, supervisor_name="Maria Keller")


RENDERERS: dict[str, Callable[[], bytes]] = {
    "rfi": _rfi,
    "pay_application": _pay_application,
    "closeout_cover": _closeout_cover,
    "punch_list": _punch_list,
    "transmittal": _transmittal,
    "meeting_minutes": _meeting_minutes,
    "daily_report": _daily_report,
    # The record forms of app.core.register_export.build_record_pdf.
    "purchase_order": record_pdf_samples.render_purchase_order,
    "goods_receipt": record_pdf_samples.render_goods_receipt,
    "invoice": record_pdf_samples.render_invoice,
    "payment": record_pdf_samples.render_payment,
}


@pytest.fixture
def workspace_only_reads(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force every generator's appearance reads back onto the workspace-only path.

    That path is what each generator called before overrides existed:
    ``branded_letterhead(width)`` and ``branded_appearance()``. Patched where
    each generator looks the name up: the module global for the ones that
    import at module level, and ``app.core.pdf_branding`` itself for the ones
    that import inside the function.
    """
    import app.core.register_export as register_export
    import app.modules.closeout.cover_pdf as cover_pdf
    import app.modules.contracts.aia_pdf as aia_pdf
    import app.modules.daily_diary.pdf_export as diary_pdf
    import app.modules.rfi.pdf_export as rfi_pdf

    letterhead = pdf_branding.branded_letterhead
    appearance = pdf_branding.branded_appearance

    def workspace_letterhead(width: float, doc_type: str | None = None) -> Any:
        return letterhead(width)

    def workspace_appearance(doc_type: str | None = None) -> dict[str, Any]:
        return appearance()

    for module in (pdf_branding, rfi_pdf, aia_pdf, cover_pdf, diary_pdf, register_export):
        monkeypatch.setattr(module, "branded_letterhead", workspace_letterhead)
    for module in (pdf_branding, rfi_pdf, diary_pdf, register_export):
        monkeypatch.setattr(module, "branded_appearance", workspace_appearance)


def _stable(render: Callable[[], bytes]) -> bytes:
    """Render twice and insist on the same bytes, so a later difference means something."""
    first = render()
    assert render() == first, "the render is not deterministic, so a byte comparison proves nothing"
    return first


def _text(pdf: bytes) -> str:
    return "\n".join(page.extract_text() or "" for page in pypdf.PdfReader(io.BytesIO(pdf)).pages)


# ── The registry ──────────────────────────────────────────────────────────


def test_every_wired_type_has_a_renderer_in_this_file() -> None:
    """A type made configurable without a render here would skip every gate below."""
    assert set(RENDERERS) == set(CONFIGURABLE)


def test_the_reserved_types_exist_and_offer_nothing() -> None:
    for key in ("submittal", "change_order"):
        assert key in DOCUMENT_TYPES
        assert DOCUMENT_TYPES[key].fields == ()
        assert not DOCUMENT_TYPES[key].configurable


def test_every_offered_field_is_an_appearance_field_and_every_type_is_labelled() -> None:
    for key, kind in DOCUMENT_TYPES.items():
        assert kind.key == key
        assert kind.label
        assert kind.label_key == f"settings.document_templates.types.{key}"
        assert set(kind.fields) <= set(DEFAULT_APPEARANCE), f"{key}: offers a field the appearance does not have"
        assert len(set(kind.fields)) == len(kind.fields)


def test_no_type_offers_the_sheet_the_generator_fixes() -> None:
    """Every wired generator lays its form out on its own fixed sheet, so page
    size, margin and body size would be controls that change nothing."""
    for kind in DOCUMENT_TYPES.values():
        assert not {"page_size", "margin_mm", "base_font_size"} & set(kind.fields), kind.key


# ── Sanitising ────────────────────────────────────────────────────────────


def test_an_unknown_or_unhonoured_field_is_dropped() -> None:
    clean = sanitise_override("punch_list", {"show_letterhead": False, "footer_text": "x", "colour": "#fff"})
    assert clean == {"show_letterhead": False}
    assert sanitise_override("rfi", {"page_size": "LETTER", "margin_mm": 12}) == {}


def test_an_unusable_value_is_dropped_not_replaced_by_the_platform_default() -> None:
    """An override is sparse. Replacing a bad colour with the platform default
    would pin the type to a look the workspace never chose; dropping it lets
    the type keep inheriting the workspace colour."""
    assert sanitise_override("rfi", {"accent_color": "red", "logo_align": "middle", "show_page_numbers": "no"}) == {}
    assert sanitise_override("rfi", {"accent_color": " #ABCDEF ", "footer_text": "  kept  "}) == {
        "accent_color": "#abcdef",
        "footer_text": "kept",
    }


def test_an_empty_footer_line_is_a_legal_override() -> None:
    """The type prints the standard footer line while the workspace has its own."""
    assert sanitise_override("rfi", {"footer_text": ""}) == {"footer_text": ""}


@pytest.mark.parametrize("key", ["nonsense", "submittal", "", None, 7])
def test_an_unknown_or_reserved_type_yields_nothing(key: Any) -> None:
    assert sanitise_override(key, {"show_letterhead": False}) == {}


def test_the_overrides_map_drops_unknown_types_and_empty_entries() -> None:
    clean = sanitise_overrides(
        {
            "rfi": {"show_letterhead": False},
            "quotation": {"show_letterhead": False},
            "punch_list": {"page_size": "A4"},
            "transmittal": "not a dict",
        }
    )
    assert clean == {"rfi": {"show_letterhead": False}}
    assert sanitise_overrides(["rfi"]) == {}


# ── Storage ───────────────────────────────────────────────────────────────


def test_with_nothing_stored_every_type_resolves_to_the_workspace_look(data_dir: Path) -> None:
    for key in DOCUMENT_TYPES:
        assert resolve_appearance(key, data_dir) == read_appearance(data_dir) == DEFAULT_APPEARANCE
    write_appearance(WORKSPACE, data_dir)
    for key in DOCUMENT_TYPES:
        assert resolve_appearance(key, data_dir) == read_appearance(data_dir)
    assert resolve_appearance(None, data_dir) == read_appearance(data_dir)


def test_an_override_applies_only_to_its_type(data_dir: Path) -> None:
    write_appearance(WORKSPACE, data_dir)
    write_override("punch_list", {"show_letterhead": False, "accent_color": "#b22222"}, data_dir)

    punch_list = resolve_appearance("punch_list", data_dir)
    assert punch_list["show_letterhead"] is False
    assert punch_list["accent_color"] == "#b22222"
    # Everything the override does not pin is the workspace's.
    assert punch_list["footer_text"] == WORKSPACE["footer_text"]
    for key in DOCUMENT_TYPES:
        if key != "punch_list":
            assert resolve_appearance(key, data_dir) == read_appearance(data_dir), key
    assert read_appearance(data_dir)["show_letterhead"] is True


def test_an_unpinned_field_follows_a_later_workspace_change(data_dir: Path) -> None:
    write_override("rfi", {"show_letterhead": False}, data_dir)
    write_appearance({"accent_color": "#654321"}, data_dir)
    assert resolve_appearance("rfi", data_dir)["accent_color"] == "#654321"


def test_writing_an_override_replaces_it(data_dir: Path) -> None:
    """Leaving a field out is how an admin stops pinning it."""
    write_override("rfi", {"show_letterhead": False, "footer_text": "x"}, data_dir)
    write_override("rfi", {"footer_text": "y"}, data_dir)
    assert read_overrides(data_dir) == {"rfi": {"footer_text": "y"}}
    assert resolve_appearance("rfi", data_dir)["show_letterhead"] is True


def test_reset_removes_the_override_and_then_the_file(data_dir: Path) -> None:
    write_override("rfi", {"show_letterhead": False}, data_dir)
    assert appearance_path(data_dir).exists()
    reset_override("rfi", data_dir)
    assert read_overrides(data_dir) == {}
    assert resolve_appearance("rfi", data_dir) == DEFAULT_APPEARANCE
    assert not appearance_path(data_dir).exists()


def test_the_workspace_writers_keep_the_overrides(data_dir: Path) -> None:
    """Both workspace writers rewrite the whole file. Saving a colour, saving
    the platform look and resetting must each carry the overrides through."""
    write_override("transmittal", {"logo_align": "center"}, data_dir)
    expected = {"transmittal": {"logo_align": "center"}}

    write_appearance({"accent_color": "#abcdef"}, data_dir)
    assert read_overrides(data_dir) == expected
    write_appearance(dict(DEFAULT_APPEARANCE), data_dir)
    assert read_overrides(data_dir) == expected
    reset_appearance(data_dir)
    assert read_overrides(data_dir) == expected
    assert read_appearance(data_dir) == DEFAULT_APPEARANCE


def test_a_file_of_overrides_alone_does_not_freeze_the_workspace_look(data_dir: Path) -> None:
    """With the workspace at the platform default, only the overrides are
    written, so a later platform restyle still reaches the workspace."""
    write_override("rfi", {"show_letterhead": False}, data_dir)
    stored = json.loads(appearance_path(data_dir).read_text(encoding="utf-8"))
    assert stored == {"overrides": {"rfi": {"show_letterhead": False}}}


def test_without_overrides_the_file_is_what_it_always_was(data_dir: Path) -> None:
    written = write_appearance(WORKSPACE, data_dir)
    stored = json.loads(appearance_path(data_dir).read_text(encoding="utf-8"))
    assert stored == written
    assert "overrides" not in stored


def test_writing_to_an_unknown_type_stores_nothing(data_dir: Path) -> None:
    assert write_override("quotation", {"show_letterhead": False}, data_dir) == {}
    assert write_override("submittal", {"show_letterhead": False}, data_dir) == {}
    assert read_overrides(data_dir) == {}
    assert not appearance_path(data_dir).exists()


def test_a_hand_edited_file_is_cleaned_on_read_and_never_raises(data_dir: Path) -> None:
    appearance_path(data_dir).write_text(
        '{"margin_mm": NaN, "base_font_size": Infinity, "accent_color": "#010203", "overrides": '
        '{"rfi": {"show_letterhead": false, "page_size": "LETTER", "accent_color": "red"},'
        ' "quotation": {"show_letterhead": false}, "punch_list": []}}',
        encoding="utf-8",
    )
    assert read_appearance(data_dir)["margin_mm"] == DEFAULT_APPEARANCE["margin_mm"]
    assert read_appearance(data_dir)["base_font_size"] == DEFAULT_APPEARANCE["base_font_size"]
    assert read_appearance(data_dir)["accent_color"] == "#010203"
    assert read_overrides(data_dir) == {"rfi": {"show_letterhead": False}}
    assert resolve_appearance("rfi", data_dir)["accent_color"] == "#010203"


def test_an_unknown_type_resolves_to_the_workspace_look(data_dir: Path) -> None:
    write_appearance(WORKSPACE, data_dir)
    assert resolve_appearance("quotation", data_dir) == read_appearance(data_dir)


def test_the_resolved_look_cannot_mutate_the_cache(data_dir: Path) -> None:
    write_override("rfi", {"show_letterhead": False}, data_dir)
    resolve_appearance("rfi", data_dir)["show_letterhead"] = True
    read_overrides(data_dir)["rfi"]["show_letterhead"] = True
    assert resolve_appearance("rfi", data_dir)["show_letterhead"] is False


# ── What the generators print ─────────────────────────────────────────────


@pytest.mark.parametrize("key", CONFIGURABLE)
@pytest.mark.usefixtures("deterministic")
def test_with_no_override_the_document_is_byte_identical_to_the_workspace_only_render(
    key: str, branded: Path, request: pytest.FixtureRequest
) -> None:
    """RFI and G702 among them. The workspace look is customised and the
    letterhead is on, so the comparison covers the fields an override reads."""
    per_type = _stable(RENDERERS[key])
    request.getfixturevalue("workspace_only_reads")
    assert _stable(RENDERERS[key]) == per_type


@pytest.mark.parametrize("key", CONFIGURABLE)
@pytest.mark.usefixtures("deterministic")
def test_overrides_on_every_other_type_leave_this_one_alone(key: str, branded: Path) -> None:
    before = _stable(RENDERERS[key])
    for other in CONFIGURABLE:
        if other != key:
            write_override(other, {field: OVERRIDE_VALUES[field] for field in DOCUMENT_TYPES[other].fields}, branded)
    assert RENDERERS[key]() == before


@pytest.mark.parametrize(
    ("key", "field"),
    [(key, field) for key in CONFIGURABLE for field in DOCUMENT_TYPES[key].fields],
)
@pytest.mark.usefixtures("deterministic")
def test_every_offered_field_changes_the_document(key: str, field: str, branded: Path) -> None:
    """The gate on the registry. A field offered for a type whose generator
    never reads it, or a generator passing a key the registry does not know,
    leaves the bytes unchanged and fails here."""
    before = _stable(RENDERERS[key])
    write_override(key, {field: OVERRIDE_VALUES[field]}, branded)
    assert RENDERERS[key]() != before, f"{key}: the {field} override changed nothing on the page"


def test_the_letterhead_switch_takes_the_letterhead_off_one_type(branded: Path) -> None:
    """Read off the page: the address is printed by the letterhead and nothing else."""
    assert "Hauptstraße 12" in _text(_punch_list())
    write_override("punch_list", {"show_letterhead": False}, branded)
    assert "Hauptstraße 12" not in _text(_punch_list())
    assert "Hauptstraße 12" in _text(_closeout_cover())


# ── The minutes and the daily report ──────────────────────────────────────

#: Every renderer of the two types, the meeting page's own export among them:
#: it shares the minutes' key but is not in :data:`RENDERERS`, so the registry
#: gates above never reach it.
MINUTES_AND_DIARY: dict[str, tuple[str, Callable[..., bytes]]] = {
    "minutes": ("meeting_minutes", lambda _monkeypatch, long=False: _meeting_minutes(long)),
    "meeting export": ("meeting_minutes", _meeting_export),
    "daily report": ("daily_report", lambda _monkeypatch, long=False: _daily_report(long)),
}


@pytest.mark.parametrize("name", list(MINUTES_AND_DIARY))
def test_the_letterhead_switch_takes_the_letterhead_off_the_minutes_or_the_diary(
    name: str, branded: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    key, render = MINUTES_AND_DIARY[name]
    other = "daily_report" if key == "meeting_minutes" else "meeting_minutes"
    assert "Hauptstraße 12" in _text(render(monkeypatch))

    write_override(other, {"show_letterhead": False}, branded)
    assert "Hauptstraße 12" in _text(render(monkeypatch)), f"{name}: the other type's switch reached it"

    write_override(key, {"show_letterhead": False}, branded)
    assert "Hauptstraße 12" not in _text(render(monkeypatch))


@pytest.mark.parametrize("name", list(MINUTES_AND_DIARY))
def test_a_footer_override_reaches_every_page_of_the_minutes_or_the_diary(
    name: str, branded: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The footer line and the page-number switch, read off each page. Before
    the override the workspace's own footer line is printed, which is the
    other half of the promise: an unset type follows the workspace."""
    key, render = MINUTES_AND_DIARY[name]

    def pages() -> list[str]:
        pdf = render(monkeypatch, long=True)
        return [page.extract_text() or "" for page in pypdf.PdfReader(io.BytesIO(pdf)).pages]

    before = pages()
    assert len(before) > 1, "expected a second page to look at"
    for number, page in enumerate(before, start=1):
        assert WORKSPACE["footer_text"] in page, f"{name}: page {number} lacks the workspace footer line"
        assert f"Page {number}" in page

    write_override(key, {"footer_text": "Per-type footer", "show_page_numbers": False}, branded)
    after = pages()
    assert len(after) == len(before)
    for number, page in enumerate(after, start=1):
        assert "Per-type footer" in page, f"{name}: page {number} lacks the type's footer line"
        assert WORKSPACE["footer_text"] not in page
        assert f"Page {number}" not in page, f"{name}: page {number} still prints its number"


def _header_logo_box(pdf: bytes) -> list[float]:
    """Page one's size and the box of the one image on it."""
    import pymupdf

    with pymupdf.open(stream=pdf, filetype="pdf") as doc:
        page = doc[0]
        images = [info["bbox"] for info in page.get_image_info()]
        assert len(images) == 1, f"expected the one header logo on page one, found {len(images)}"
        return [page.rect.width, page.rect.height, *images[0]]


@pytest.mark.parametrize("name", list(MINUTES_AND_DIARY))
def test_without_a_letterhead_the_header_logo_sits_where_the_sample_puts_it(
    name: str, data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With an app logo and no company profile both print the small header logo
    at the right margin. The minutes placed it from reportlab's default one inch
    margin, 15pt left of the text column under it and of the sample's logo."""
    from app.core.pdf_branding import render_sample_pdf

    key, render = MINUTES_AND_DIARY[name]
    (data_dir / "app_branding.json").write_text(json.dumps({"mode": "logo", "logo_data_url": _png()}), encoding="utf-8")
    assert _header_logo_box(render_sample_pdf(key)) == pytest.approx(_header_logo_box(render(monkeypatch)), abs=0.05)


# ── The sample ────────────────────────────────────────────────────────────


def test_the_sample_follows_the_types_override(branded: Path) -> None:
    from app.core.pdf_branding import render_sample_pdf

    write_override("punch_list", {"show_letterhead": False}, branded)
    assert "Hauptstraße 12" in _text(render_sample_pdf())
    assert "Hauptstraße 12" not in _text(render_sample_pdf("punch_list"))
    assert "Hauptstraße 12" in _text(render_sample_pdf("rfi"))


@pytest.mark.parametrize(
    ("key", "field"),
    [(key, field) for key in CONFIGURABLE for field in DOCUMENT_TYPES[key].fields],
)
@pytest.mark.usefixtures("deterministic")
def test_every_offered_field_changes_the_types_sample(key: str, field: str, branded: Path) -> None:
    """The preview moves with every knob the document moves with."""
    from app.core.pdf_branding import render_sample_pdf

    before = _stable(lambda: render_sample_pdf(key))
    write_override(key, {field: OVERRIDE_VALUES[field]}, branded)
    assert render_sample_pdf(key) != before, f"{key}: the {field} override changed nothing in the sample"


@pytest.mark.parametrize("key", CONFIGURABLE)
@pytest.mark.usefixtures("deterministic")
def test_without_a_company_profile_the_letterhead_fields_move_neither_document_nor_sample(
    key: str, data_dir: Path
) -> None:
    """The letterhead is the only reader of these fields, and there is none to
    draw. The header logo a generator draws instead always sits top right, so
    a preview that moved here (the shared header band would) promises a change
    the document never makes."""
    from app.core.pdf_branding import render_sample_pdf

    (data_dir / "app_branding.json").write_text(json.dumps({"mode": "logo", "logo_data_url": _png()}), encoding="utf-8")
    document = _stable(RENDERERS[key])
    sample = _stable(lambda: render_sample_pdf(key))
    write_override(key, {"show_letterhead": False, "logo_align": "center", "accent_color": "#b22222"}, data_dir)
    assert RENDERERS[key]() == document
    assert render_sample_pdf(key) == sample


def _layout(pdf: bytes) -> list[float]:
    """Page one's size, the logo's box and the registration line's box, flattened.

    The registration line is printed by the letterhead and nothing else, and it
    is ASCII, so the text search finds it whatever face the name is set in.
    """
    import pymupdf

    with pymupdf.open(stream=pdf, filetype="pdf") as doc:
        page = doc[0]
        images = [info["bbox"] for info in page.get_image_info()]
        lines = page.search_for("HRB 123456 B")
        assert len(images) == 1, f"expected the one letterhead logo on page one, found {len(images)}"
        assert len(lines) == 1, "the letterhead's registration line is not on page one"
        return [page.rect.width, page.rect.height, *images[0], *lines[0]]


@pytest.mark.parametrize(
    ("key", "paper"),
    [(key, "A4") for key in CONFIGURABLE] + [("transmittal", "LETTER")],
)
def test_the_sample_is_laid_out_on_the_documents_own_sheet(key: str, paper: str, branded: Path) -> None:
    """The preview is what prints: same paper and orientation, and the
    letterhead's logo and lines land on the same points of the page. A form
    whose margins or sheet change without its registry entry fails here."""
    from app.core.paper_size import PAPER_SIZES
    from app.core.pdf_branding import render_sample_pdf

    document = _transmittal(paper) if key == "transmittal" else RENDERERS[key]()
    sample = render_sample_pdf(key, paper=PAPER_SIZES[paper])
    assert _layout(sample) == pytest.approx(_layout(document), abs=0.05)


def test_the_sheet_is_not_the_workspace_page_size(branded: Path) -> None:
    """A workspace set to Legal with wide margins still previews its G702 on
    landscape Letter, because that is what the form prints on."""
    from app.core.pdf_branding import render_sample_pdf

    write_appearance({"page_size": "LEGAL", "margin_mm": 40}, branded)
    assert _layout(render_sample_pdf("pay_application")) == pytest.approx(_layout(_pay_application()), abs=0.05)
    width, height = _layout(render_sample_pdf())[:2]
    assert (round(width), round(height)) == (612, 1008)


def test_the_sample_is_titled_with_the_type_and_carries_a_footer_only_where_the_type_prints_one(
    data_dir: Path,
) -> None:
    from app.core.pdf_branding import render_sample_pdf

    write_appearance({"footer_text": "Workspace footer"}, data_dir)
    rfi = _text(render_sample_pdf("rfi"))
    assert "Sample document: Request for information" in rfi
    assert "Workspace footer" in rfi
    punch_list = _text(render_sample_pdf("punch_list"))
    assert "Sample document: Punch list" in punch_list
    assert "Workspace footer" not in punch_list, "the punch list prints no footer, so its sample must not show one"


# ── The API ───────────────────────────────────────────────────────────────


def _client(role: str | None = "admin") -> Any:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.core.branding_router import router
    from app.dependencies import get_current_user_payload

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    if role is not None:
        app.dependency_overrides[get_current_user_payload] = lambda: {"sub": str(uuid.uuid4()), "role": role}
    return TestClient(app)


def test_the_registry_lists_the_configurable_types_with_their_look(data_dir: Path) -> None:
    write_appearance(WORKSPACE, data_dir)
    write_override("rfi", {"footer_text": "RFI footer"}, data_dir)

    response = _client("viewer").get("/api/v1/document-appearance/types/")

    assert response.status_code == 200
    body = response.json()
    assert [entry["key"] for entry in body] == CONFIGURABLE
    rfi = body[0]
    assert rfi["label"] == "Request for information"
    assert rfi["label_key"] == "settings.document_templates.types.rfi"
    assert rfi["fields"] == list(DOCUMENT_TYPES["rfi"].fields)
    assert rfi["override"] == {"footer_text": "RFI footer"}
    assert rfi["effective"]["footer_text"] == "RFI footer"
    assert rfi["effective"]["accent_color"] == WORKSPACE["accent_color"]
    punch_list = next(entry for entry in body if entry["key"] == "punch_list")
    assert punch_list["override"] == {}
    assert punch_list["effective"]["footer_text"] == WORKSPACE["footer_text"]


def test_the_registry_needs_a_signed_in_user(data_dir: Path) -> None:
    assert _client(None).get("/api/v1/document-appearance/types/").status_code == 401


@pytest.mark.parametrize("path", ["/api/v1/document-appearance/types/rfi/", "/api/v1/document-appearance/types/rfi"])
def test_an_admin_sets_and_clears_an_override(data_dir: Path, path: str) -> None:
    client = _client("admin")

    response = client.put(path, json={"show_letterhead": False, "logo_align": "right"})
    assert response.status_code == 200, response.text
    assert response.json()["override"] == {"show_letterhead": False, "logo_align": "right"}
    assert response.json()["effective"]["show_letterhead"] is False
    assert read_overrides(data_dir) == {"rfi": {"show_letterhead": False, "logo_align": "right"}}

    response = client.delete(path)
    assert response.status_code == 200
    assert response.json()["override"] == {}
    assert response.json()["effective"]["show_letterhead"] is True
    assert read_overrides(data_dir) == {}


def test_a_put_replaces_and_null_means_inherit(data_dir: Path) -> None:
    client = _client("admin")
    client.put("/api/v1/document-appearance/types/rfi/", json={"show_letterhead": False, "footer_text": "x"})
    response = client.put("/api/v1/document-appearance/types/rfi/", json={"show_letterhead": None, "footer_text": "y"})
    assert response.json()["override"] == {"footer_text": "y"}


@pytest.mark.parametrize("role", ["editor", "manager", "viewer"])
def test_a_non_admin_cannot_change_an_override(data_dir: Path, role: str) -> None:
    write_override("rfi", {"footer_text": "kept"}, data_dir)
    client = _client(role)

    assert client.put("/api/v1/document-appearance/types/rfi/", json={"show_letterhead": False}).status_code == 403
    assert client.delete("/api/v1/document-appearance/types/rfi/").status_code == 403
    assert read_overrides(data_dir) == {"rfi": {"footer_text": "kept"}}


def test_a_field_the_type_does_not_honour_is_refused_not_dropped(data_dir: Path) -> None:
    """A 200 for a page size the punch list never reads would tell the admin a
    setting was saved that changes nothing."""
    write_override("punch_list", {"accent_color": "#b22222"}, data_dir)

    response = _client("admin").put(
        "/api/v1/document-appearance/types/punch_list/", json={"show_letterhead": False, "footer_text": "x"}
    )

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["error"] == "invalid_document_type_override"
    assert detail["reason"] == "field_not_configurable"
    assert detail["field"] == "footer_text"
    assert detail["allowed_fields"] == list(DOCUMENT_TYPES["punch_list"].fields)
    assert read_overrides(data_dir) == {"punch_list": {"accent_color": "#b22222"}}


def test_an_unusable_value_is_refused(data_dir: Path) -> None:
    response = _client("admin").put("/api/v1/document-appearance/types/rfi/", json={"accent_color": "red"})
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["reason"] == "invalid_value"
    assert detail["field"] == "accent_color"
    assert "hex colour" in detail["message"]
    assert read_overrides(data_dir) == {}


def test_an_unknown_field_name_is_refused(data_dir: Path) -> None:
    response = _client("admin").put("/api/v1/document-appearance/types/rfi/", json={"accent_colour": "#123456"})
    assert response.status_code == 422
    assert read_overrides(data_dir) == {}


def test_unknown_and_reserved_types_are_refused(data_dir: Path) -> None:
    client = _client("admin")

    unknown = client.put("/api/v1/document-appearance/types/quotation/", json={"show_letterhead": False})
    assert unknown.status_code == 404
    assert unknown.json()["detail"]["error"] == "unknown_document_type"
    assert unknown.json()["detail"]["known_types"] == CONFIGURABLE

    reserved = client.put("/api/v1/document-appearance/types/submittal/", json={"show_letterhead": False})
    assert reserved.status_code == 422
    assert reserved.json()["detail"]["error"] == "document_type_not_configurable"
    assert client.get("/api/v1/document-appearance/types/submittal/sample.pdf").status_code == 422
    assert read_overrides(data_dir) == {}


def test_the_type_sample_endpoint_returns_an_inline_pdf(branded: Path) -> None:
    response = _client("viewer").get("/api/v1/document-appearance/types/pay_application/sample.pdf")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["content-disposition"] == 'inline; filename="sample-pay_application.pdf"'
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["content-language"] == "en"
    assert "Sample document: Payment application" in _text(response.content)


def _page_size(pdf: bytes) -> tuple[int, int]:
    box = pypdf.PdfReader(io.BytesIO(pdf)).pages[0].mediabox
    return round(float(box.width)), round(float(box.height))


@pytest.mark.parametrize(("preference", "expected"), [("Letter", (612, 792)), ("auto", (595, 842)), (None, (595, 842))])
def test_the_transmittal_sample_is_on_the_readers_paper(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch, preference: str | None, expected: tuple[int, int]
) -> None:
    """The cover is printed on the sender's paper, and the reader is who would
    send it. With no preference and no project there is no country, so A4."""
    from app.core import branding_router

    asked: list[Any] = []

    async def preference_of(user_id: Any) -> str | None:
        asked.append(user_id)
        return preference

    monkeypatch.setattr(branding_router, "_reader_paper_preference", preference_of)
    response = _client("viewer").get("/api/v1/document-appearance/types/transmittal/sample.pdf")
    assert response.status_code == 200
    assert _page_size(response.content) == expected
    assert len(asked) == 1


def test_a_fixed_sheet_ignores_the_readers_paper(data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core import branding_router

    asked: list[Any] = []

    async def preference_of(user_id: Any) -> str | None:
        asked.append(user_id)
        return "Letter"

    monkeypatch.setattr(branding_router, "_reader_paper_preference", preference_of)
    response = _client("viewer").get("/api/v1/document-appearance/types/rfi/sample.pdf")
    assert _page_size(response.content) == (595, 842)
    assert asked == [], "a form on a fixed sheet looked up the reader's paper"


def test_an_unreadable_preference_falls_back_to_a4(data_dir: Path) -> None:
    """The lookup itself never raises: no user row for this id reads as unset."""
    import asyncio

    from app.core.branding_router import _reader_paper_preference

    assert asyncio.run(_reader_paper_preference("not-a-uuid")) is None
