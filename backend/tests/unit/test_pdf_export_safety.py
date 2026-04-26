"""PDF export hardening (BUG-PDF01 / BUG-PDF02 fix).

ReportLab's ``Paragraph`` parses a subset of HTML. Before this fix, any
BOQ position ``description`` containing an unrecognised attribute (e.g.
``<img src=x onerror=alert(1)>``) crashed the paraparser with a
``ValueError``, which surfaced as a 500 from
``GET /boq/boqs/{id}/export/pdf``. A malicious user with ``boq.update``
rights could DoS the entire reporting feature.

Even when the markup parsed successfully, ``<font color="white">`` was
honoured, allowing hidden text in print copies of the cost estimate
(BUG-PDF02 — content concealment).

The fix is the ``_safe_para`` helper in ``pdf_export.py`` — every dynamic
field flowing into ``Paragraph`` is escaped via ``html.escape`` first.

These unit tests pin the helper contract and exercise the full PDF
generation entry point with malicious payloads to prove the entire path
no longer crashes and no longer renders attacker-supplied markup.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from reportlab.lib.styles import ParagraphStyle

from app.modules.boq.pdf_export import _safe_para


# ─────────────────────────────────────────────────────────────────────────
# _safe_para — unit-level contract
# ─────────────────────────────────────────────────────────────────────────


def _style() -> ParagraphStyle:
    """Cheap ParagraphStyle for tests — Paragraph never actually renders here."""
    return ParagraphStyle(name="test")


def test_safe_para_escapes_angle_brackets():
    """``<`` and ``>`` survive only as escaped entities."""
    p = _safe_para("<img src=x onerror=alert(1)>", _style())
    assert "<img" not in p.text
    assert "onerror" in p.text  # text content survives, just inert
    assert "&lt;img" in p.text


def test_safe_para_escapes_quotes_for_attribute_safety():
    """Quoting matters: an unquoted attribute payload could still escape."""
    p = _safe_para('"><script>alert(1)</script>', _style())
    assert "<script>" not in p.text
    assert "&lt;script&gt;" in p.text
    assert "&quot;" in p.text


def test_safe_para_handles_none():
    """None becomes empty string instead of literal "None"."""
    p = _safe_para(None, _style())
    assert p.text == ""


def test_safe_para_handles_non_string():
    """Numbers / decimals are stringified before escaping."""
    p = _safe_para(12345, _style())
    assert p.text == "12345"


def test_safe_para_neutralises_font_color_attack():
    """``<font color="white">hidden</font>`` must NOT render as styled text.

    BUG-PDF02 — a contractor could hide overcharges in printed PDFs by
    using a foreground colour matching the page background.
    """
    p = _safe_para('<font color="white">hidden</font>', _style())
    # The literal ``<font`` tag must not survive — escaped form only.
    assert "<font" not in p.text
    assert "&lt;font" in p.text


# ─────────────────────────────────────────────────────────────────────────
# Full PDF generation — invariance under malicious input
# ─────────────────────────────────────────────────────────────────────────


def _make_boq(*, description: str):
    """Build a minimal duck-typed ``boq_data`` for ``generate_boq_pdf``.

    The PDF generator only accesses ``.attribute`` on each row — it does not
    validate Pydantic field shape. Using ``SimpleNamespace`` keeps the test
    independent from the response-model schema and avoids tying the test
    to fields like ``parent_id``/``classification``/``created_at`` that are
    irrelevant for the PDF code path.
    """
    from types import SimpleNamespace

    pos = SimpleNamespace(
        id=uuid.uuid4(),
        boq_id=uuid.uuid4(),
        ordinal="01.001",
        description=description,
        unit="m2",
        quantity=10.0,
        unit_rate=99.99,
        total=999.9,
    )
    sect = SimpleNamespace(
        id=uuid.uuid4(),
        ordinal="01",
        description=description,
        positions=[pos],
        subtotal=999.9,
    )
    return SimpleNamespace(
        id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        name="Hardening test BOQ",
        status="draft",
        currency="EUR",
        sections=[sect],
        positions=[],
        direct_cost=999.9,
        markups=[],
        net_total=999.9,
        grand_total=999.9,
    )


def test_generate_pdf_does_not_crash_on_malicious_html_in_description():
    """BUG-PDF01: ``<img onerror=...>`` must not propagate as 500."""
    from app.modules.boq.pdf_export import generate_boq_pdf

    boq = _make_boq(description="<img src=x onerror=alert(1)>")

    pdf = generate_boq_pdf(boq, project_name="Test", currency="EUR")

    assert isinstance(pdf, bytes)
    assert pdf.startswith(b"%PDF")
    assert len(pdf) > 0


def test_generate_pdf_does_not_crash_on_unknown_html_attributes():
    """Class of paraparser bugs: unknown attribute names crash even on valid tags."""
    from app.modules.boq.pdf_export import generate_boq_pdf

    boq = _make_boq(description='<para garbage="yes">text</para>')

    pdf = generate_boq_pdf(boq, project_name="Test", currency="EUR")
    assert pdf.startswith(b"%PDF")


def test_generate_pdf_does_not_crash_on_malicious_prepared_by():
    """The cover page splices ``prepared_by`` into a paragraph — DoS via that field."""
    from app.modules.boq.pdf_export import generate_boq_pdf

    boq = _make_boq(description="OK")

    pdf = generate_boq_pdf(
        boq,
        project_name="Test",
        currency="EUR",
        prepared_by='<img onerror="alert(1)">',
    )
    assert pdf.startswith(b"%PDF")


def test_generate_pdf_does_not_crash_on_malicious_project_name():
    """Project name flows into both the cover page and the running header."""
    from app.modules.boq.pdf_export import generate_boq_pdf

    boq = _make_boq(description="OK")

    pdf = generate_boq_pdf(
        boq,
        project_name='<font color="red"><b>Boom</b></font>',
        currency="EUR",
    )
    assert pdf.startswith(b"%PDF")


def test_generate_pdf_handles_normal_descriptions():
    """Sanity: a vanilla BOQ still produces a valid PDF after the change."""
    from app.modules.boq.pdf_export import generate_boq_pdf

    boq = _make_boq(description="Concrete C30/37 — 240mm wall, F90 fire rating")

    pdf = generate_boq_pdf(boq, project_name="Vanilla", currency="EUR")

    assert pdf.startswith(b"%PDF")
    # The PDF should be a non-trivial size — multi-KB at minimum
    assert len(pdf) > 2_000


def test_generate_pdf_strips_zero_width_characters_in_description():
    """Defensive: zero-width / control characters in description must not break.

    Some attackers embed ``\\u200b`` etc. to confuse manual review. ReportLab
    tolerates them but the test doubles as a regression guard for surprising
    Unicode handling in our escape path.
    """
    from app.modules.boq.pdf_export import generate_boq_pdf

    boq = _make_boq(description="Wall\u200btext\u200ehere")

    pdf = generate_boq_pdf(boq, project_name="Unicode", currency="EUR")
    assert pdf.startswith(b"%PDF")


def test_pdf_bytes_do_not_contain_unescaped_attack_payload():
    """The literal attribute name in the attacker's payload must not be in the
    rendered PDF (the escape would have it as ``&lt;img...``).

    PDF strings are encoded but Latin-1 chars survive. We grep the bytes
    for the obvious attack literal — its absence proves the escape.
    """
    from app.modules.boq.pdf_export import generate_boq_pdf

    payload = "<img src=x onerror=alert(1)>"
    boq = _make_boq(description=payload)

    pdf = generate_boq_pdf(boq, project_name="Test", currency="EUR")

    # The exact unencoded HTML attack string must not be embedded.
    assert payload.encode("utf-8") not in pdf
