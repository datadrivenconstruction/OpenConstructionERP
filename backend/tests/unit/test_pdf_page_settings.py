# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The page, header, footer and watermark settings of the document appearance.

Each setting is read back off the generated PDF rather than off a stub canvas,
because the shared page furniture guards every draw: a stub that refuses a call
would only lose the setting silently, and the assertion would have nothing
behind it. The first group pins that the defaults print what the platform
printed before the settings existed; the rest pin that every setting moves the
page, and that the server refuses a value it would otherwise save as the default.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import ValidationError
from pypdf import PdfReader

from app.core import pdf_branding
from app.core.pdf_appearance import (
    DEFAULT_APPEARANCE,
    MAX_WATERMARK_OPACITY,
    MIN_WATERMARK_OPACITY,
    PAGE_NUMBER_FORMATS,
    PAGE_ORIENTATIONS,
    PRINT_STAMPS,
    WATERMARK_LAYOUTS,
    read_appearance,
    resolve_page_size,
    sanitise,
    write_appearance,
)

FIXED_NOW = datetime(2026, 9, 1, 14, 5, tzinfo=UTC)
LEGAL_NAME = "Bau GmbH Mueller"
REGISTRATION = "HRB 123456 B, VAT DE123456789"
ADDRESS_LINE = "Hauptstrasse 12"

NEW_FIELDS = (
    "watermark_opacity",
    "watermark_layout",
    "page_orientation",
    "header_show_contact",
    "header_rule",
    "page_number_format",
    "print_stamp",
    "footer_show_registration",
)


class _FrozenDatetime(datetime):
    @classmethod
    def now(cls, tz: Any = None) -> datetime:  # type: ignore[override]
        return FIXED_NOW


@pytest.fixture
def data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A throwaway data dir with a company profile that has no logo."""
    import json

    monkeypatch.setenv("OE_DATA_DIR", str(tmp_path))
    profile = {
        "legal_name": LEGAL_NAME,
        "address": f"{ADDRESS_LINE}\n10115 Berlin",
        "registration_line": REGISTRATION,
        "phone": "+49 30 1234567",
        "email": "office@example.com",
    }
    (tmp_path / "company_profile.json").write_text(json.dumps(profile), encoding="utf-8")
    monkeypatch.setattr(pdf_branding, "datetime", _FrozenDatetime)
    return tmp_path


def _save(data_dir: Path, **fields: Any) -> None:
    write_appearance({**read_appearance(data_dir), **fields}, data_dir)


def _text(pdf: bytes) -> str:
    return "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(pdf)).pages)


def _content(pdf: bytes) -> bytes:
    return b"\n".join(page.get_contents().get_data() for page in PdfReader(BytesIO(pdf)).pages)


def _sample(data_dir: Path, **fields: Any) -> bytes:
    """The workspace sample with the letterhead off, so the header band and footer draw."""
    _save(data_dir, show_letterhead=False, **fields)
    return pdf_branding.render_sample_pdf()


def _furniture(appearance: dict[str, Any], *, page: int = 2, total: int = 5) -> bytes:
    """One page of footer drawn by the shared callback for a document of ``total`` pages."""
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen.canvas import Canvas

    buffer = BytesIO()
    canvas = Canvas(buffer, pagesize=A4)
    doc = SimpleNamespace(page=page, page_count=total, pagesize=A4, leftMargin=56.0, rightMargin=56.0)
    pdf_branding.branded_footer(canvas, doc)
    canvas.showPage()
    canvas.save()
    return buffer.getvalue()


# -- Defaults print what was printed before -----------------------------------------


def test_the_new_fields_default_to_the_former_behaviour() -> None:
    assert DEFAULT_APPEARANCE["page_orientation"] == "portrait"
    assert DEFAULT_APPEARANCE["page_number_format"] == "page_of"
    assert DEFAULT_APPEARANCE["print_stamp"] == "auto"
    assert DEFAULT_APPEARANCE["header_rule"] is True
    assert DEFAULT_APPEARANCE["header_show_contact"] is False
    assert DEFAULT_APPEARANCE["footer_show_registration"] is False
    assert DEFAULT_APPEARANCE["watermark_layout"] == "diagonal"
    # The opacity is the alpha the watermark has always printed with.
    assert DEFAULT_APPEARANCE["watermark_opacity"] / 100 == pdf_branding._WATERMARK_ALPHA


def test_a_file_saved_before_the_settings_existed_reads_the_defaults(data_dir: Path) -> None:
    import json

    (data_dir / "pdf_appearance.json").write_text(json.dumps({"accent_color": "#123456"}), encoding="utf-8")
    look = read_appearance(data_dir)
    assert look["accent_color"] == "#123456"
    assert all(look[field] == DEFAULT_APPEARANCE[field] for field in NEW_FIELDS)


def test_the_default_footer_prints_the_page_line_and_the_generated_date(data_dir: Path) -> None:
    pdf = _furniture(dict(DEFAULT_APPEARANCE))
    text = _text(pdf)
    assert "Page 2 of 5" in text
    assert "Generated: 2026-09-01" in text
    assert "Printed:" not in text


def test_the_default_sample_has_the_header_rule_and_no_second_footer_line(data_dir: Path) -> None:
    pdf = _sample(data_dir)
    text = _text(pdf)
    assert "Generated: 2026-09-01" in text
    assert "Printed:" not in text
    assert REGISTRATION not in text
    assert ADDRESS_LINE not in text
    assert PdfReader(BytesIO(pdf)).pages[0].mediabox.width < PdfReader(BytesIO(pdf)).pages[0].mediabox.height


# -- Every setting moves the page ----------------------------------------------------


@pytest.mark.parametrize(
    ("fmt", "expected"),
    [("page_of", "Page 2 of 5"), ("page", "Page 2"), ("short", "2 / 5"), ("number", "2")],
)
def test_the_page_number_format_changes_the_footer(data_dir: Path, fmt: str, expected: str) -> None:
    _save(data_dir, page_number_format=fmt)
    text = _text(_furniture(read_appearance(data_dir)))
    assert expected in text.split("\n")


def test_the_page_number_falls_back_when_the_count_is_unknown() -> None:
    assert pdf_branding.page_number_text("page_of", page=3, total=0) == "Page 3"
    assert pdf_branding.page_number_text("short", page=3, total=0) == "3"
    assert pdf_branding.page_number_text("nonsense", page=3, total=7) == "Page 3 of 7"


def test_turning_the_page_numbers_off_still_wins(data_dir: Path) -> None:
    _save(data_dir, show_page_numbers=False, page_number_format="short")
    assert "2 / 5" not in _text(_furniture(read_appearance(data_dir)))


@pytest.mark.parametrize(
    ("mode", "expected", "absent"),
    [
        ("date", "Printed: 2026-09-01", "14:05"),
        ("datetime", "Printed: 2026-09-01 14:05 UTC", "Generated:"),
    ],
)
def test_the_print_stamp_moves_to_its_own_line(data_dir: Path, mode: str, expected: str, absent: str) -> None:
    _save(data_dir, print_stamp=mode)
    text = _text(_furniture(read_appearance(data_dir)))
    assert expected in text
    assert absent not in text
    # The date is not printed twice: the default line gives it up.
    assert "Generated:" not in text


def test_the_print_stamp_none_prints_no_date_at_all(data_dir: Path) -> None:
    _save(data_dir, print_stamp="none")
    text = _text(_furniture(read_appearance(data_dir)))
    assert "2026" not in text
    assert "Page 2 of 5" in text


def test_the_registration_line_joins_the_footer_when_asked(data_dir: Path) -> None:
    assert REGISTRATION not in _text(_furniture(read_appearance(data_dir)))
    _save(data_dir, footer_show_registration=True)
    assert REGISTRATION in _text(_furniture(read_appearance(data_dir)))


def test_an_empty_registration_line_prints_nothing(data_dir: Path) -> None:
    import json

    (data_dir / "company_profile.json").write_text(json.dumps({"legal_name": LEGAL_NAME}), encoding="utf-8")
    _save(data_dir, footer_show_registration=True)
    before = _furniture(dict(DEFAULT_APPEARANCE))
    assert _text(_furniture(read_appearance(data_dir))) == _text(before)


def test_the_header_contact_block_prints_the_address_and_contact_line(data_dir: Path) -> None:
    plain = _text(_sample(data_dir))
    with_block = _text(_sample(data_dir, header_show_contact=True))
    assert ADDRESS_LINE not in plain
    assert f"{ADDRESS_LINE}, 10115 Berlin" in with_block
    assert "+49 30 1234567 · office@example.com" in with_block


@pytest.mark.parametrize("align", ["left", "center", "right"])
def test_the_header_contact_block_follows_the_logo_side(data_dir: Path, align: str) -> None:
    assert ADDRESS_LINE in _text(_sample(data_dir, header_show_contact=True, logo_align=align))


def test_the_header_rule_can_be_switched_off(data_dir: Path) -> None:
    with_rule = _content(_sample(data_dir))
    without_rule = _content(_sample(data_dir, header_rule=False))
    assert with_rule != without_rule
    # The rule is the only stroked line in the sample's header.
    assert len(re.findall(rb" l\b", with_rule)) == len(re.findall(rb" l\b", without_rule)) + 1


def test_the_orientation_turns_the_sheet(data_dir: Path) -> None:
    portrait = PdfReader(BytesIO(_sample(data_dir))).pages[0].mediabox
    landscape = PdfReader(BytesIO(_sample(data_dir, page_orientation="landscape"))).pages[0].mediabox
    assert float(landscape.width) == pytest.approx(float(portrait.height), abs=0.1)
    assert float(landscape.height) == pytest.approx(float(portrait.width), abs=0.1)
    assert resolve_page_size({"page_size": "LETTER", "page_orientation": "landscape"}) == (792.0, 612.0)
    assert resolve_page_size({"page_size": "LETTER"}) == (612.0, 792.0)


def test_the_watermark_opacity_is_the_graphics_state(data_dir: Path) -> None:
    default = _sample(data_dir, watermark_text="DRAFT")
    strong = _sample(data_dir, watermark_text="DRAFT", watermark_opacity=30)
    assert b"/ca .14" in default
    assert b"/ca .3" in strong
    assert b"/ca .14" not in strong


def test_the_level_watermark_is_not_rotated(data_dir: Path) -> None:
    diagonal = _content(_sample(data_dir, watermark_text="DRAFT"))
    level = _content(_sample(data_dir, watermark_text="DRAFT", watermark_layout="horizontal"))
    assert diagonal != level
    # A rotation is a ``cm`` whose matrix is not a pure translation.
    rotated = re.compile(rb"(-?[\d.]+) (-?[\d.]+) (-?[\d.]+) (-?[\d.]+) -?[\d.]+ -?[\d.]+ cm")

    def has_rotation(stream: bytes) -> bool:
        return any(abs(float(m.group(2))) > 1e-6 for m in rotated.finditer(stream))

    assert has_rotation(diagonal)
    assert not has_rotation(level)
    assert "DRAFT" in _text(_sample(data_dir, watermark_text="DRAFT", watermark_layout="horizontal"))


# -- Validation ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("page_orientation", "sideways"),
        ("page_number_format", "roman"),
        ("print_stamp", "always"),
        ("watermark_layout", "spiral"),
        ("watermark_opacity", "strong"),
        ("watermark_opacity", True),
        ("header_rule", "yes"),
        ("footer_show_registration", 1),
    ],
)
def test_the_sanitiser_keeps_the_default_for_an_unusable_value(field: str, value: object) -> None:
    assert sanitise({field: value})[field] == DEFAULT_APPEARANCE[field]


def test_the_opacity_is_clamped_like_the_other_bounded_numbers() -> None:
    assert sanitise({"watermark_opacity": 99})["watermark_opacity"] == MAX_WATERMARK_OPACITY
    assert sanitise({"watermark_opacity": 1})["watermark_opacity"] == MIN_WATERMARK_OPACITY


def test_the_sanitiser_accepts_every_offered_choice() -> None:
    for fmt in PAGE_NUMBER_FORMATS:
        assert sanitise({"page_number_format": fmt})["page_number_format"] == fmt
    for stamp in PRINT_STAMPS:
        assert sanitise({"print_stamp": stamp})["print_stamp"] == stamp
    for layout in WATERMARK_LAYOUTS:
        assert sanitise({"watermark_layout": layout})["watermark_layout"] == layout
    for orientation in PAGE_ORIENTATIONS:
        assert sanitise({"page_orientation": f" {orientation.upper()} "})["page_orientation"] == orientation


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("page_orientation", "sideways"),
        ("page_number_format", "roman"),
        ("print_stamp", "always"),
        ("watermark_layout", "spiral"),
        ("watermark_opacity", 99),
        ("watermark_opacity", 4),
        ("watermark_opacity", 14.5),
        ("header_rule", "maybe"),
    ],
)
def test_the_save_endpoint_model_refuses_what_it_would_not_keep(field: str, value: object) -> None:
    from app.core.branding_router import DocumentAppearanceUpdate

    with pytest.raises(ValidationError):
        DocumentAppearanceUpdate(**{field: value})


def test_the_save_endpoint_model_accepts_every_offered_value() -> None:
    from app.core.branding_router import DocumentAppearanceUpdate

    body = DocumentAppearanceUpdate(
        page_orientation="landscape",
        page_number_format="short",
        print_stamp="datetime",
        watermark_layout="horizontal",
        watermark_opacity=25,
        header_show_contact=True,
        header_rule=False,
        footer_show_registration=True,
    )
    assert body.model_dump(exclude_none=True)["watermark_opacity"] == 25


def test_the_options_and_the_response_describe_the_new_fields() -> None:
    import asyncio

    from app.core.branding_router import DocumentAppearanceResponse, get_document_appearance_options

    options = asyncio.run(get_document_appearance_options())
    assert options.page_orientations == list(PAGE_ORIENTATIONS)
    assert options.page_number_formats == list(PAGE_NUMBER_FORMATS)
    assert options.print_stamps == list(PRINT_STAMPS)
    assert options.watermark_layouts == list(WATERMARK_LAYOUTS)
    assert (options.min_watermark_opacity, options.max_watermark_opacity) == (5, 40)
    assert DocumentAppearanceResponse().model_dump() == DEFAULT_APPEARANCE


def test_a_saved_value_round_trips_through_the_file(data_dir: Path) -> None:
    _save(data_dir, print_stamp="date", page_number_format="number", watermark_opacity=22)
    look = read_appearance(data_dir)
    assert (look["print_stamp"], look["page_number_format"], look["watermark_opacity"]) == ("date", "number", 22)
    write_appearance(dict(DEFAULT_APPEARANCE), data_dir)
    assert read_appearance(data_dir) == DEFAULT_APPEARANCE
