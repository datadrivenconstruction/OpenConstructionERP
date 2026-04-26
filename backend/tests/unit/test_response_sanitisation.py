"""Response-layer sanitisation (BUG-MATH04 fix).

The PDF export path is already hardened via ``html.escape`` in
``app.modules.boq.pdf_export._safe_para`` (covered by
``test_pdf_export_safety``). The remaining XSS surface is the JSON API:
``GET /boq/boqs/{id}`` and ``GET /projects/{id}`` returned free-text
fields verbatim, so any frontend that wraps a description in
``dangerouslySetInnerHTML`` could execute attacker-controlled markup
even though the input validators block the *most* dangerous tags.

These unit tests pin the contract of :func:`sanitise_text` and
:func:`strip_all_html_tags` and verify that the response models built
on top of them strip residual HTML.

Storage stays untouched — the strip is purely on serialisation.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from app.core.sanitize import sanitise_text, strip_all_html_tags
from app.modules.boq.schemas import (
    BOQResponse,
    PositionResponse,
    SectionResponse,
)
from app.modules.projects.schemas import ProjectResponse

# ─────────────────────────────────────────────────────────────────────────
# strip_all_html_tags / sanitise_text — unit-level contract
# ─────────────────────────────────────────────────────────────────────────


def test_script_tag_and_body_dropped():
    """``<script>`` block + payload body must be removed entirely.

    Document the choice: destructive blocks (script/iframe/style/svg/etc.)
    have their *content* dropped along with the tags. Benign tags below
    only have the *tags* dropped; their text content survives.
    """
    assert strip_all_html_tags("<script>alert(1)</script>foo") == "foo"
    assert strip_all_html_tags("before<script>alert(1)</script>after") == "beforeafter"


def test_nested_destructive_block_drops_inner_text():
    """``<div><script>x</script></div>`` → empty string after both passes.

    The inner ``<script>x</script>`` block drops its body. The outer
    ``<div>`` tags then strip via the generic tag stripper. Result is
    empty, NOT the literal ``x``. Documented choice — see module docstring.
    """
    assert strip_all_html_tags("<div><script>x</script></div>") == ""


def test_benign_inline_tags_keep_text_content():
    """``<b>Bold</b> text`` → ``Bold text`` — text survives, tags removed."""
    assert strip_all_html_tags("<b>Bold</b> text") == "Bold text"
    assert strip_all_html_tags("<i>italic</i> and <u>underline</u>") == "italic and underline"


def test_plain_text_passes_through_unchanged():
    """Vanilla construction text must round-trip exactly."""
    text = "Concrete C30/37 — 240mm wall, F90 fire rating"
    assert strip_all_html_tags(text) == text


def test_empty_and_none_inputs_are_safe():
    """Empty / None / falsy inputs return empty string (or None for sanitise_text)."""
    assert strip_all_html_tags("") == ""
    assert strip_all_html_tags(None) == ""  # type: ignore[arg-type]
    # sanitise_text preserves None to distinguish "unset" from "set to empty"
    assert sanitise_text(None) is None
    assert sanitise_text("") == ""


def test_unicode_preserved_across_scripts():
    """CJK / Arabic / Cyrillic / Greek text must survive the strip."""
    samples = [
        "钢筋混凝土 C30/37",                # Chinese
        "خرسانة مسلحة",                       # Arabic
        "Железобетон C30/37",               # Cyrillic
        "Σκυρόδεμα C30/37",                  # Greek
        "コンクリート C30/37",                # Japanese (mixed scripts)
    ]
    for s in samples:
        assert strip_all_html_tags(f"<b>{s}</b>") == s
        assert strip_all_html_tags(s) == s


def test_literal_angle_brackets_in_dimensions_survive():
    """``"beam <200mm"`` is NOT a tag — the leading char after ``<`` is a digit.

    This is the property that distinguishes us from a ``bleach.clean`` call;
    construction text legitimately uses ``<`` for "less than" comparisons.
    """
    assert strip_all_html_tags("beam <200mm section") == "beam <200mm section"
    assert strip_all_html_tags("a < b > c") == "a < b > c"


def test_html_entities_decoded():
    """``&amp;`` → ``&``, ``&nbsp;`` → NBSP, numeric entities decoded."""
    assert strip_all_html_tags("Smith &amp; Sons") == "Smith & Sons"
    # Nbsp decoded but kept as a real char
    assert strip_all_html_tags("a&nbsp;b") == "a\u00a0b"
    # Numeric entity for space-comma-style
    assert strip_all_html_tags("a&#65;b") == "aAb"
    assert strip_all_html_tags("a&#x41;b") == "aAb"


def test_event_handler_attribute_payload_neutralised():
    """``<img src=x onerror=alert(1)>`` becomes empty — the whole tag is gone."""
    assert strip_all_html_tags("<img src=x onerror=alert(1)>") == ""
    # Embedded inside text — surrounding text survives.
    assert strip_all_html_tags("hello<img onerror=alert(1)>world") == "helloworld"


def test_strip_is_idempotent():
    """Running the strip twice gives the same result as once."""
    samples = [
        "<b>Bold</b> text",
        "<script>x</script>plain",
        "no tags here",
        "Smith &amp; Sons",
    ]
    for s in samples:
        once = strip_all_html_tags(s)
        twice = strip_all_html_tags(once)
        assert once == twice, f"not idempotent for {s!r}: {once!r} vs {twice!r}"


# ─────────────────────────────────────────────────────────────────────────
# Response models apply the strip via @field_validator
# ─────────────────────────────────────────────────────────────────────────


def _now() -> datetime:
    return datetime.now(UTC)


def _make_position_kwargs(description: str) -> dict:
    """Minimal valid kwargs for PositionResponse construction."""
    return {
        "id": uuid.uuid4(),
        "boq_id": uuid.uuid4(),
        "parent_id": None,
        "ordinal": "01.001",
        "description": description,
        "unit": "m3",
        "quantity": 10.0,
        "unit_rate": 100.0,
        "total": 1000.0,
        "classification": {},
        "source": "manual",
        "confidence": None,
        "cad_element_ids": [],
        "validation_status": "pending",
        "metadata": {},
        "sort_order": 0,
        "created_at": _now(),
        "updated_at": _now(),
    }


@pytest.mark.parametrize(
    ("stored", "expected"),
    [
        ("<script>alert(1)</script>foo", "foo"),
        ("<b>Bold</b> text", "Bold text"),
        ("<img src=x onerror=alert(1)>", ""),
        ("Concrete C30/37 — 240mm wall", "Concrete C30/37 — 240mm wall"),
        ("beam <200mm", "beam <200mm"),  # literal math survives
        ("", ""),
    ],
)
def test_position_response_strips_description(stored: str, expected: str):
    pos = PositionResponse(**_make_position_kwargs(stored))
    assert pos.description == expected


def test_section_response_strips_description():
    sect = SectionResponse(
        id=uuid.uuid4(),
        ordinal="01",
        description="<script>alert(1)</script>Foundations",
        positions=[],
        subtotal=0.0,
    )
    assert sect.description == "Foundations"


def test_boq_response_strips_name_and_description():
    boq = BOQResponse(
        id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        name="<b>Phase 1</b>",
        description="<img onerror=alert(1)>scope notes",
        status="draft",
        metadata={},
        created_at=_now(),
        updated_at=_now(),
    )
    assert boq.name == "Phase 1"
    assert boq.description == "scope notes"


def test_project_response_strips_name_and_description():
    proj = ProjectResponse(
        id=uuid.uuid4(),
        name="<b>Mitte Tower</b>",
        description="<script>alert(1)</script>5-story residential",
        region="DACH",
        classification_standard="din276",
        currency="EUR",
        locale="en",
        validation_rule_sets=["boq_quality"],
        status="active",
        owner_id=uuid.uuid4(),
        metadata={},
        created_at=_now(),
        updated_at=_now(),
    )
    assert proj.name == "Mitte Tower"
    assert proj.description == "5-story residential"


def test_response_models_preserve_unicode():
    """Multi-script text must round-trip through Pydantic + sanitiser."""
    pos = PositionResponse(**_make_position_kwargs("钢筋混凝土 — Железобетон — خرسانة"))
    assert pos.description == "钢筋混凝土 — Железобетон — خرسانة"


def test_response_models_strip_is_idempotent():
    """Re-validating a sanitised response produces the same output.

    Re-construction is a real concern: the response is sometimes round
    -tripped through ``model_dump()`` → ``MyResponse(**dump)`` (e.g. in
    snapshot tests, in the cache layer). The strip must not eat real
    content on the second pass.
    """
    pos = PositionResponse(**_make_position_kwargs("<b>Bold</b> text"))
    second = PositionResponse(**{**_make_position_kwargs(pos.description)})
    assert pos.description == second.description == "Bold text"
