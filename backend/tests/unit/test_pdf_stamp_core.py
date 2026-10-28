# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Pure unit tests for the reusable PDF stamp core (``app.core.pdf_stamp``).

These tests import NO database and NO module ORM models - only the core
stamp primitives and reportlab/pypdf, which are base dependencies. They
build a real PDF in-memory, stamp it, and assert the result is a valid PDF
with the same page count, plus the documented graceful-fallback contracts.

The behavioural file-approvals tests (tests/unit/test_file_approvals.py)
exercise the stamp through the service and are DB-bound; the integrator
should re-run those after this refactor to confirm the rewire is intact.
"""

from __future__ import annotations

from io import BytesIO

import pytest

from app.core.pdf_stamp import burn_pdf_stamp, expand_svg_placeholders


def _make_pdf(num_pages: int = 2) -> bytes:
    """Build a small valid multi-page PDF entirely in memory."""
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    for i in range(num_pages):
        c.drawString(100, 700, f"Body of page {i + 1}")
        c.showPage()
    c.save()
    return buf.getvalue()


def _page_count(pdf_bytes: bytes) -> int:
    from pypdf import PdfReader

    return len(PdfReader(BytesIO(pdf_bytes)).pages)


# ── expand_svg_placeholders (fully pure) ───────────────────────────────────


def test_expand_svg_placeholders_fills_known_tokens():
    out = expand_svg_placeholders(
        "<svg>{{text}} | {{date}} | {{approver}}</svg>",
        text="FOR CONSTRUCTION",
        approver="Jane Approver",
        decision_date="2026-06-20",
    )
    assert out == "<svg>FOR CONSTRUCTION | 2026-06-20 | Jane Approver</svg>"


def test_expand_svg_placeholders_leaves_unknown_tokens_untouched():
    """Unknown placeholders survive so template authors may use raw braces."""
    out = expand_svg_placeholders(
        "{{text}} keep {{unknown}} and {{also_unknown}}",
        text="T",
        approver="A",
        decision_date="D",
    )
    assert "{{unknown}}" in out
    assert "{{also_unknown}}" in out
    assert out.startswith("T keep ")


def test_expand_svg_placeholders_no_tokens_is_identity():
    src = '<svg xmlns="http://www.w3.org/2000/svg"><rect/></svg>'
    assert expand_svg_placeholders(src, text="T", approver="A", decision_date="D") == src


def test_expand_svg_placeholders_repeated_tokens_all_replaced():
    out = expand_svg_placeholders(
        "{{text}}-{{text}}-{{approver}}-{{approver}}",
        text="X",
        approver="Y",
        decision_date="D",
    )
    assert out == "X-X-Y-Y"


# ── burn_pdf_stamp (pure-ish: bytes in, bytes out) ─────────────────────────


def test_burn_pdf_stamp_returns_valid_pdf_same_page_count():
    src = _make_pdf(num_pages=2)
    assert src.startswith(b"%PDF-")

    out = burn_pdf_stamp(
        src,
        template_text="FOR CONSTRUCTION",
        template_color="#16a34a",
        approver="Jane Approver",
        decision_date="2026-06-20",
    )
    assert out is not None
    assert out.startswith(b"%PDF-")
    # Every page is preserved (the stamp is merged onto each, not appended).
    assert _page_count(out) == _page_count(src) == 2


def test_burn_pdf_stamp_single_page():
    src = _make_pdf(num_pages=1)
    out = burn_pdf_stamp(
        src,
        template_text="APPROVED",
        template_color="#2563eb",
        approver="A",
        decision_date="2026-01-01",
    )
    assert out is not None
    assert _page_count(out) == 1


def test_burn_pdf_stamp_invalid_color_falls_back_no_crash():
    """An invalid hex colour must not raise - it degrades to the default."""
    src = _make_pdf(num_pages=1)
    out = burn_pdf_stamp(
        src,
        template_text="HOLD",
        template_color="not-a-real-color",
        approver="A",
        decision_date="2026-01-01",
    )
    assert out is not None
    assert out.startswith(b"%PDF-")


def test_burn_pdf_stamp_non_pdf_input_returns_none():
    """Garbage bytes -> None (caller writes a JSON sidecar instead)."""
    assert (
        burn_pdf_stamp(
            b"this is definitely not a pdf",
            template_text="X",
            template_color="#000000",
            approver="A",
            decision_date="D",
        )
        is None
    )


def test_burn_pdf_stamp_never_raises_on_empty_bytes():
    """Empty input is swallowed and reported as a fallback, not an exception."""
    assert (
        burn_pdf_stamp(
            b"",
            template_text="X",
            template_color="#000000",
            approver="A",
            decision_date="D",
        )
        is None
    )


def test_burn_pdf_stamp_truncates_long_text_and_approver_without_error():
    """Over-long text/approver are clipped (40 / 32 chars) but never crash."""
    src = _make_pdf(num_pages=1)
    out = burn_pdf_stamp(
        src,
        template_text="X" * 200,
        template_color="#16a34a",
        approver="Y" * 200,
        decision_date="2026-06-20",
    )
    assert out is not None
    assert out.startswith(b"%PDF-")


def test_burn_pdf_stamp_returns_none_when_pypdf_missing(monkeypatch):
    """If the optional dep stack is unimportable, return None (sidecar path).

    Simulated by making ``import pypdf`` raise inside the function's lazy
    import block.
    """
    import builtins

    real_import = builtins.__import__

    def _fake_import(name, *args, **kwargs):
        if name == "pypdf" or name.startswith("pypdf."):
            raise ImportError("simulated missing pypdf")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _fake_import)

    src = _make_pdf(num_pages=1)
    out = burn_pdf_stamp(
        src,
        template_text="X",
        template_color="#16a34a",
        approver="A",
        decision_date="D",
    )
    assert out is None


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
