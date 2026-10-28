# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Names go into a property_dev PDF as text, not as markup.

A reportlab ``Paragraph`` takes a small HTML-like markup, so anything
interpolated into one is parsed rather than printed. A developer called
"Meyer & Sohn" is not an unusual name and the ampersand is not an unusual
character, but it is markup here, and the generator handed it straight to the
parser.

Every way this goes wrong is silent. Nothing raises, the file still opens, it
still looks plausible and it still goes to a regulator. Measured against the
unfixed renderer, the parser does four different things:

* ``<`` starts a tag, so "Baufeld <Nord>" draws as "Baufeld" and the rest of
  the name is gone.
* ``&`` followed by a letter reads as an unterminated entity and a semicolon
  is injected after the next word: "R&D Tower" draws as "R&D; Tower" and
  "AT&T Plaza" draws as "AT&T; Plaza".
* ``&amp;`` in the data decodes, so a name stored as "Haus &amp; Hof" draws as
  "Haus & Hof".
* ``&`` followed by a space is left alone, which is the only reason the
  shipped clause headings have never shown the fault.

That last case is why "Meyer & Sohn" alone is a weak test. It passes against
the unfixed renderer, not because the path is safe but because the input
happens to dodge the parser. The cases that carry the finding are the ones
where an ordinary name is corrupted.

These tests assert on the produced document rather than on the escaping
helper, since the property being defended is that the characters reach the
page.
"""

from __future__ import annotations

import io

import pypdf
import pytest

# Names with markup characters in them. Real developers have all of these.
AMPERSAND = "Meyer & Sohn Bautrager GmbH"
ANGLE_BRACKETS = "Baufeld <Nord>"
LOOKS_LIKE_MARKUP = "Quartier <b>Premium</b>"
LOOKS_LIKE_AN_ENTITY = "Haus &amp; Hof"
AMPERSAND_THEN_LETTER = "R&D Tower"
INITIALS = "AT&T Plaza"
APOSTROPHE = "O'Brien Developments"
QUOTED = 'Villa "Sonnenhof"'

CORRUPTED_BY_THE_PARSER = [
    ("angle brackets", ANGLE_BRACKETS),
    ("looks like markup", LOOKS_LIKE_MARKUP),
    ("looks like an entity", LOOKS_LIKE_AN_ENTITY),
    ("ampersand then letter", AMPERSAND_THEN_LETTER),
    ("initials", INITIALS),
]
SURVIVED_BY_LUCK = [
    ("ampersand then space", AMPERSAND),
    ("apostrophe", APOSTROPHE),
    ("double quotes", QUOTED),
]

# Section headings shipped in the jurisdiction clause packs. Every one of them
# carries a bare ampersand, and every one of them is drawn through the same
# paragraph path, so they are the control for the fix not moving product data.
SHIPPED_CLAUSE_HEADINGS = [
    "Completion & Possession Date",
    "Dispute Resolution & Jurisdiction",
    "Transfer & NOC",
    "Completion & Possession",
    "Governing Law & Jurisdiction",
    "Completion Date & Substantial Performance",
]

CN_DEVELOPMENT = "上海建工集团股份有限公司"


def render(**overrides: object) -> bytes:
    from app.modules.property_dev.service import _render_regulator_pdf

    kwargs: dict[str, object] = {
        "regulator": "RERA",
        "development_name": "Wohnpark Gruenstrasse",
        "development_code": "BA-1",
        "quarter": "2026-Q2",
        "summary": {"currency": "EUR", "Sold units": "42"},
    }
    kwargs.update(overrides)
    return _render_regulator_pdf(**kwargs)  # type: ignore[arg-type]


def page_text(data: bytes) -> str:
    reader = pypdf.PdfReader(io.BytesIO(data))
    return "".join("".join(page.extract_text().split()) for page in reader.pages)


def squash(text: str) -> str:
    return "".join(text.split())


@pytest.mark.parametrize(("label", "name"), CORRUPTED_BY_THE_PARSER + SURVIVED_BY_LUCK)
def test_a_development_name_with_markup_characters_still_produces_a_document(label: str, name: str) -> None:
    """No case raises, before the fix or after it.

    This is not the interesting half. It is here so that the fix is not
    allowed to trade silent corruption for a hard failure: escaping must not
    make a name unrenderable.
    """
    data = render(development_name=name)
    assert data.startswith(b"%PDF"), f"the {label} name did not produce a PDF"


@pytest.mark.parametrize(("label", "name"), CORRUPTED_BY_THE_PARSER)
def test_a_development_name_the_parser_corrupts_arrives_intact(label: str, name: str) -> None:
    """The finding. Each of these was altered on the way to the page.

    A document that renders "Baufeld" where the development is called
    "Baufeld <Nord>", or "R&D; Tower" where it is called "R&D Tower", is worse
    than one that failed to render, because nothing about it looks wrong.
    """
    text = page_text(render(development_name=name))
    assert squash(name) in text, f"the {label} name was altered on its way to the page: {text[:200]!r}"


@pytest.mark.parametrize(("label", "name"), SURVIVED_BY_LUCK)
def test_a_development_name_the_parser_already_tolerated_is_unchanged(label: str, name: str) -> None:
    """These passed before the fix too, because the input dodges the parser.

    They are kept as the other direction of the control: the fix must not
    start corrupting the names that were always fine.
    """
    text = page_text(render(development_name=name))
    assert squash(name) in text, f"the {label} name was altered on its way to the page: {text[:200]!r}"


@pytest.mark.parametrize("heading", SHIPPED_CLAUSE_HEADINGS)
def test_a_shipped_clause_heading_is_unchanged(heading: str) -> None:
    """Product data, not test input.

    These live in the jurisdiction clause packs and are drawn through the same
    escaping funnel. They render the same before and after because an escaped
    ampersand decodes back to an ampersand, and this asserts that.
    """
    from app.core.pdf_fonts import register_pdf_fonts
    from app.modules.property_dev.document_templates import _p, _styles

    register_pdf_fonts()
    from reportlab.lib.pagesizes import A4
    from reportlab.platypus import SimpleDocTemplate

    buf = io.BytesIO()
    SimpleDocTemplate(buf, pagesize=A4).build([_p(heading, _styles("en")["heading"])])
    reader = pypdf.PdfReader(io.BytesIO(buf.getvalue()))
    drawn = "".join(page.extract_text() for page in reader.pages)
    assert squash(heading) in squash(drawn), f"a shipped clause heading moved: {drawn!r}"


def test_the_other_interpolated_fields_are_data_too() -> None:
    """The same fault, one field over. All four go into the same markup."""
    data = render(regulator="RERA & Partners", development_code="BA<1>", quarter="2026 & Q2")
    text = page_text(data)
    assert "RERA&Partners" in text
    assert "BA<1>" in text
    assert "2026&Q2" in text


def test_a_summary_value_with_markup_characters_survives() -> None:
    """Summary rows are bare table cells rather than markup, so these were
    already safe. Asserted rather than assumed, because if the fix for the
    paragraphs is applied here too it would double-escape and print the
    entities literally."""
    text = page_text(render(summary={"currency": "EUR", "Contractor": "Meyer & Sohn", "Note": "<b>urgent</b>"}))
    assert "Meyer&Sohn" in text
    assert "<b>urgent</b>" in text


def test_the_label_markup_is_still_parsed() -> None:
    """Escaping the value must not escape the markup around it.

    The labels on these paragraphs are bold, written as ``<b>`` in the
    generator. If the fix wrapped the whole f-string instead of the
    interpolated value, the tags would print literally.
    """
    text = page_text(render())
    assert "<b>" not in text, f"the label markup was escaped along with the data: {text[:200]!r}"
    assert "Development:" in text


def test_a_chinese_name_still_reaches_the_unicode_face() -> None:
    """Escaping is ASCII-only and must not disturb the face selection.

    The development code goes into a ``<font face>`` attribute whose value is
    our own output, so it stays unescaped; this asserts the attribute still
    names the pack rather than being mangled by the fix.
    """
    data = render(development_name=CN_DEVELOPMENT, development_code=CN_DEVELOPMENT)
    assert data.startswith(b"%PDF")
    assert b"STSong-Light" in data, "the Chinese name no longer resolves to the referenced CID face"
