# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠A stored appearance must reach the page, not just the store.

``test_pdf_appearance`` proves the settings file round-trips and that the
defaults still equal the literals the drawing code used to hold. Neither of
those would notice if a consumer stopped reading the file: the defaults would
keep agreeing with themselves and every assertion would stay green while the
settings page saved values that changed nothing. So these tests set a value no
default could produce and then look at what was actually drawn.

Both consumers are guarded - ``branded_header_footer`` wraps its whole body in
``except Exception`` so a bad settings file can never lose a document a buyer
is waiting for. That guard is also how a test like this goes vacuously green:
a stub canvas missing one method raises, the guard swallows it, nothing is
drawn and every "is the wrong colour absent" assertion passes. The assertions
below are therefore positive - they name the value that must be present - and
:func:`test_the_guard_does_not_hide_a_dead_consumer` states the trap directly.
"""

from __future__ import annotations

import re
from io import BytesIO
from pathlib import Path
from typing import Any

import pytest

from app.core.pdf_appearance import DEFAULT_APPEARANCE, PAGE_SIZES, write_appearance

MM = 72.0 / 25.4
_MEDIABOX = re.compile(rb"/MediaBox\s*\[\s*([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s*\]")


@pytest.fixture
def data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point every no-argument appearance read at a throwaway directory.

    The company profile too: the header draws its document logo in place of
    the text brand these tests look for.
    """
    from app.core import company_profile, pdf_appearance

    monkeypatch.setattr(pdf_appearance, "resolve_data_dir", lambda: tmp_path)
    monkeypatch.setattr(company_profile, "resolve_data_dir", lambda: tmp_path)
    return tmp_path


class RecordingCanvas:
    """A canvas that records the calls the branding code makes on it.

    Every method the drawing path uses is spelled out rather than caught by
    ``__getattr__``: a permissive stub would answer calls that do not exist,
    and the point of this class is to fail when the drawing code reaches for
    something it should not.
    """

    def __init__(self) -> None:
        self.strings: list[tuple[str, float, float, str]] = []
        self.fills: list[Any] = []
        self.strokes: list[Any] = []
        self.fonts: list[tuple[str, float]] = []
        self.saves = 0
        self.restores = 0

    def saveState(self) -> None:  # noqa: N802 - reportlab's spelling
        self.saves += 1

    def restoreState(self) -> None:  # noqa: N802 - reportlab's spelling
        self.restores += 1

    def setFont(self, name: str, size: float) -> None:  # noqa: N802
        self.fonts.append((name, size))

    def setFillColor(self, colour: Any) -> None:  # noqa: N802
        self.fills.append(colour)

    def setStrokeColor(self, colour: Any) -> None:  # noqa: N802
        self.strokes.append(colour)

    def setLineWidth(self, width: float) -> None:  # noqa: N802
        self.width = width

    def line(self, x1: float, y1: float, x2: float, y2: float) -> None:
        self.rule = (x1, y1, x2, y2)

    def drawString(self, x: float, y: float, text: str) -> None:  # noqa: N802
        self.strings.append(("left", x, y, text))

    def drawRightString(self, x: float, y: float, text: str) -> None:  # noqa: N802
        self.strings.append(("right", x, y, text))

    def drawCentredString(self, x: float, y: float, text: str) -> None:  # noqa: N802
        self.strings.append(("centre", x, y, text))

    def drawImage(self, *a: Any, **kw: Any) -> None:  # noqa: N802
        self.strings.append(("image", 0.0, 0.0, ""))

    # -- helpers the assertions read ------------------------------------
    def texts(self) -> list[str]:
        return [t for _, _, _, t in self.strings]

    def aligned(self, text_fragment: str) -> str:
        for align, _, _, text in self.strings:
            if text_fragment in text:
                return align
        raise AssertionError(f"nothing drawn containing {text_fragment!r}; drew {self.texts()!r}")


class FakeDoc:
    """The handful of attributes ``branded_header_footer`` reads off a doc."""

    def __init__(self, *, pagesize: tuple[float, float], page: int = 1, page_count: int = 0) -> None:
        self.pagesize = pagesize
        self.leftMargin = 56.0  # noqa: N815 - reportlab's spelling
        self.rightMargin = 56.0  # noqa: N815 - reportlab's spelling
        self.page = page
        self.page_count = page_count


def _draw(doc: FakeDoc) -> RecordingCanvas:
    from app.core.pdf_branding import branded_header_footer

    canvas = RecordingCanvas()
    branded_header_footer(canvas, doc)
    return canvas


# ── the guard, stated as its own test ──────────────────────────────────


def test_the_guard_does_not_hide_a_dead_consumer(data_dir: Path) -> None:
    """A completed draw must be observable, or nothing below means anything.

    ``branded_header_footer`` returns quietly on any exception. If the recording
    canvas were missing a method, or the consumer stopped reading the settings
    file, the body would abort early and the rest of this module would pass
    while proving nothing. The footer line is the last thing the happy path
    draws before the page number, so seeing it is the evidence that the whole
    body ran.
    """
    write_appearance({"footer_text": "ran to the end"}, data_dir)
    canvas = _draw(FakeDoc(pagesize=(595.27, 841.89)))
    assert "ran to the end" in canvas.texts()
    assert canvas.saves == 1
    assert canvas.restores == 1


# ── pdf_branding: the header and footer of every export ────────────────


def test_a_stored_footer_line_replaces_the_generated_date(data_dir: Path) -> None:
    write_appearance({"footer_text": "Acme Ltd, registered in Ireland 123456"}, data_dir)
    texts = _draw(FakeDoc(pagesize=(595.27, 841.89))).texts()
    assert "Acme Ltd, registered in Ireland 123456" in texts
    # The date is dropped rather than appended: a signed contract carrying an
    # unexpected generation date is a support ticket.
    assert not [t for t in texts if "Generated:" in t]


def test_a_stored_accent_colour_is_the_one_the_header_is_painted_with(data_dir: Path) -> None:
    from reportlab.lib import colors

    write_appearance({"accent_color": "#aa0044", "footer_color": "#00aa44"}, data_dir)
    canvas = _draw(FakeDoc(pagesize=(595.27, 841.89)))
    used = [c.hexval() for c in canvas.fills]
    assert colors.HexColor("#aa0044").hexval() in used
    assert colors.HexColor("#00aa44").hexval() in used


@pytest.mark.parametrize(("align", "expected"), [("left", "left"), ("center", "centre"), ("right", "right")])
def test_the_header_alignment_setting_moves_the_brand(data_dir: Path, align: str, expected: str) -> None:
    """With no logo uploaded the brand is text, and it must follow the setting.

    A control that only moves an image nobody has uploaded looks broken to the
    workspace that has not uploaded one, which is most of them on day one.
    """
    write_appearance({"logo_align": align, "footer_text": "f"}, data_dir)
    assert _draw(FakeDoc(pagesize=(595.27, 841.89))).aligned("OpenConstructionERP") == expected


def test_page_numbers_can_be_turned_off(data_dir: Path) -> None:
    write_appearance({"show_page_numbers": True, "footer_text": "f"}, data_dir)
    on = _draw(FakeDoc(pagesize=(595.27, 841.89), page=2, page_count=7)).texts()
    assert "Page 2 of 7" in on

    write_appearance({"show_page_numbers": False, "footer_text": "f"}, data_dir)
    off = _draw(FakeDoc(pagesize=(595.27, 841.89), page=2, page_count=7)).texts()
    assert "f" in off, "the footer must still be drawn; only the number goes"
    assert not [t for t in off if t.startswith("Page ")]


# ── document_templates: the generated property documents ───────────────


def _build_and_render(locale: str = "en") -> tuple[Any, bytes]:
    from app.modules.property_dev import document_templates as dt

    buf = BytesIO()
    doc, frame = dt._build_doc(buf, title="t", author="a", subject="s", keywords=["k"])
    ctx = dt._PageContext(
        developer_name="Acme",
        developer_logo_url=None,
        unit_code="A-1",
        doc_ref="REF-1",
        locale=locale,
        watermark=False,
    )
    story = [dt._p("Body text", dt._styles(locale)["body"])]
    return doc, dt._render(doc, frame, story, ctx, buf)


def _media_box(pdf: bytes) -> tuple[float, float]:
    m = _MEDIABOX.search(pdf)
    assert m is not None, "no /MediaBox in the produced PDF; the page size cannot be read"
    return (round(float(m.group(3))), round(float(m.group(4))))


def test_an_untouched_workspace_still_gets_an_a4_page(data_dir: Path) -> None:
    doc, pdf = _build_and_render()
    assert round(doc.pagesize[0]) == round(PAGE_SIZES["A4"][0])
    assert _media_box(pdf) == (round(PAGE_SIZES["A4"][0]), round(PAGE_SIZES["A4"][1]))


def test_a_stored_page_size_reaches_the_produced_pdf(data_dir: Path) -> None:
    """The strongest assertion in this file: the bytes carry the setting.

    Everything in between - the store, the helper, the doc template - could be
    correct while the renderer still built an A4 page, and only the file a
    customer opens would show it.
    """
    write_appearance({"page_size": "LETTER"}, data_dir)
    doc, pdf = _build_and_render()
    assert round(doc.pagesize[0]) == round(PAGE_SIZES["LETTER"][0])
    assert _media_box(pdf) == (round(PAGE_SIZES["LETTER"][0]), round(PAGE_SIZES["LETTER"][1]))
    assert _media_box(pdf) != (round(PAGE_SIZES["A4"][0]), round(PAGE_SIZES["A4"][1]))


def test_a_stored_margin_reaches_the_frame(data_dir: Path) -> None:
    write_appearance({"margin_mm": 12}, data_dir)
    doc, _ = _build_and_render()
    assert doc.leftMargin == pytest.approx(12 * MM)
    assert doc.rightMargin == pytest.approx(12 * MM)


def test_a_stored_body_size_scales_the_whole_family(data_dir: Path) -> None:
    """Raising the body size must move the headings with it.

    Scaling only the body would leave a 14 pt paragraph under a heading set for
    a 10 pt one, which reads as a broken document rather than a larger one.
    """
    from app.modules.property_dev import document_templates as dt

    base = dt._styles("en")
    before = {name: style.fontSize for name, style in base.items()}

    write_appearance({"base_font_size": 14}, data_dir)
    after = dt._styles("en")

    assert dt._base_font_size() == 14.0
    assert after["body"].fontSize == pytest.approx(before["body"] * 1.4)
    for name, style in after.items():
        assert style.fontSize == pytest.approx(before[name] * 1.4), f"{name} did not scale"


def test_the_defaults_render_the_same_page_they_always_did(data_dir: Path) -> None:
    """Writing the defaults explicitly must be indistinguishable from never saving."""
    _, untouched = _build_and_render()
    write_appearance(dict(DEFAULT_APPEARANCE), data_dir)
    _, explicit = _build_and_render()
    assert _media_box(untouched) == _media_box(explicit)
