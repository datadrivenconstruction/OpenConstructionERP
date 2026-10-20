# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Unit tests for the PDF source: parser (``pdf_import``) + adapter.

Two layers under test:

* :func:`app.modules.match_elements.pdf_import.parse_boq_pdf` - extracts
  line items from a real (in-memory) PDF. We build the fixtures with
  ``reportlab`` (a base dependency) so no test asset files are needed and
  the parser exercises its pdfplumber-then-pypdfium2 path.
* :class:`app.modules.match_elements.sources.pdf_adapter.PdfAdapter` -
  the thin session-scoped reader over ``MatchSession.metadata_["pdf_rows"]``.
  Mirrors the Text/BoQ adapter unit tests: a duck-typed session stub, a
  fresh-event-loop runner, no DB.

Run:
    cd backend
    python -m pytest tests/unit/test_match_elements_pdf_source.py -q
"""

from __future__ import annotations

import asyncio
import io
import uuid
from types import SimpleNamespace

import pytest

from app.modules.match_elements.pdf_import import parse_boq_pdf
from app.modules.match_elements.sources.pdf_adapter import PdfAdapter

PROJECT_ID = uuid.uuid4()


# ── Helpers ─────────────────────────────────────────────────────────────


def _fake_session(metadata: dict | None) -> SimpleNamespace:
    """Duck-typed MatchSession stub - only ``metadata_`` + ``id`` matter."""
    return SimpleNamespace(id=uuid.uuid4(), metadata_=metadata)


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _pdf_with_lines(lines: list[str]) -> bytes:
    """Render text lines into a one-page PDF and return the bytes.

    Uses reportlab to build the fixture; the parser then reconstructs the
    lines via its text path (a drawn page carries no extractable table grid).
    """
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(595, 842))
    c.setFont("Helvetica", 11)
    y = 842 - 100
    for line in lines:
        c.drawString(72, y, line)
        y -= 20
    c.save()
    return buf.getvalue()


# ── parse_boq_pdf ────────────────────────────────────────────────────────


class TestParseBoqPdf:
    def test_extracts_description_qty_unit(self):
        pdf = _pdf_with_lines(
            [
                "Reinforced concrete wall C30/37 240mm   125.50 m3",
                "Wood formwork for slabs   340 m2",
                "Structural steel beams   12 t",
            ]
        )
        rows = parse_boq_pdf(pdf)
        assert len(rows) == 3
        assert rows[0]["description"].startswith("Reinforced concrete wall")
        assert rows[0]["qty"] == 125.5
        assert rows[0]["unit"] == "m3"
        assert rows[1]["unit"] == "m2"
        assert rows[2]["qty"] == 12.0
        assert rows[2]["unit"] == "t"

    def test_description_without_qty_still_extracted(self):
        pdf = _pdf_with_lines(["Excavation and disposal of spoil to licensed tip"])
        rows = parse_boq_pdf(pdf)
        assert len(rows) == 1
        assert "qty" not in rows[0]
        assert rows[0]["description"].startswith("Excavation")

    def test_leading_position_code_is_peeled_off(self):
        pdf = _pdf_with_lines(["01.02.003 Masonry blockwork 140mm   88 m2"])
        rows = parse_boq_pdf(pdf)
        assert len(rows) == 1
        assert rows[0]["code"] == "01.02.003"
        assert rows[0]["description"].startswith("Masonry blockwork")
        assert rows[0]["qty"] == 88.0
        assert rows[0]["unit"] == "m2"

    def test_page_furniture_lines_are_dropped(self):
        pdf = _pdf_with_lines(
            [
                "Concrete slab C25/30 200mm   85 m3",
                "Page 1 of 3",
                "Subtotal   12345.00",
            ]
        )
        rows = parse_boq_pdf(pdf)
        # Only the real line item survives; "Page ..." and "Subtotal ..."
        # are filtered as page furniture.
        descriptions = [r["description"] for r in rows]
        assert any("Concrete slab" in d for d in descriptions)
        assert not any("Page" in d for d in descriptions)
        assert not any(d.lower().startswith("subtotal") for d in descriptions)

    def test_empty_bytes_raises(self):
        with pytest.raises(ValueError):
            parse_boq_pdf(b"")

    def test_garbage_bytes_raise_clean_valueerror(self):
        # Not a PDF - both backends fail; the parser surfaces a ValueError
        # (the upload route turns that into a 400) rather than crashing.
        with pytest.raises(ValueError):
            parse_boq_pdf(b"this is plainly not a pdf document at all")

    def test_decimal_comma_quantity(self):
        pdf = _pdf_with_lines(["Plaster render to walls   12,5 m2"])
        rows = parse_boq_pdf(pdf)
        assert len(rows) == 1
        assert rows[0]["qty"] == 12.5
        assert rows[0]["unit"] == "m2"


# ── PdfAdapter ─────────────────────────────────────────────────────────────


class TestPdfAdapter:
    def test_no_session_returns_empty(self):
        adapter = PdfAdapter(session=None, match_session=None)
        assert _run(adapter.iter_elements(project_id=PROJECT_ID)) == []
        assert _run(adapter.list_categories(PROJECT_ID)) == []

    def test_iter_elements_maps_units_to_quantities(self):
        sess = _fake_session(
            {
                "pdf_rows": [
                    {"description": "Concrete wall C30/37", "qty": 25.0, "unit": "m3"},
                    {"description": "Plaster work", "qty": 100, "unit": "m2"},
                    {"description": "Skirting", "qty": 40, "unit": "m"},
                ]
            }
        )
        adapter = PdfAdapter(session=None, match_session=sess)
        elements = _run(adapter.iter_elements(project_id=PROJECT_ID))
        assert len(elements) == 3
        assert elements[0].quantities["volume_m3"] == 25.0
        assert elements[1].quantities["area_m2"] == 100.0
        assert elements[2].quantities["length_m"] == 40.0
        # Default category for a PDF row is "PDF".
        assert all(e.category == "PDF" for e in elements)
        # Element ids are namespaced so they don't collide with other
        # sources in the same session universe.
        assert elements[0].id.startswith("pdf:")

    def test_exact_code_shortcut_forwarded(self):
        sess = _fake_session(
            {
                "pdf_rows": [
                    {"description": "Wall", "qty": 5, "unit": "m3", "code": "FER46-001-1"},
                    {"description": "No code", "qty": 1, "unit": "m"},
                ]
            }
        )
        adapter = PdfAdapter(session=None, match_session=sess)
        elements = _run(adapter.iter_elements(project_id=PROJECT_ID))
        assert elements[0].attributes["exact_code"] == "FER46-001-1"
        assert "exact_code" not in elements[1].attributes

    def test_synthetic_category_not_promoted_to_ifc_class(self):
        # The "PDF" / category label is operator free-text, not an IFC
        # class - promoting it would poison the Qdrant hard filter and
        # zero out every CWICR candidate (same guard as the BoQ adapter).
        sess = _fake_session(
            {
                "pdf_rows": [
                    {"description": "x", "qty": 1, "unit": "m3", "category": "Walls"},
                    {"description": "y", "qty": 1, "unit": "m3"},
                ]
            }
        )
        adapter = PdfAdapter(session=None, match_session=sess)
        elements = _run(adapter.iter_elements(project_id=PROJECT_ID))
        assert elements[0].attributes["category"] == "Walls"
        assert "ifc_class" not in elements[0].attributes
        assert elements[1].attributes["category"] == "PDF"
        assert "ifc_class" not in elements[1].attributes

    def test_real_ifc_class_is_forwarded(self):
        sess = _fake_session(
            {
                "pdf_rows": [
                    {"description": "Cast wall", "qty": 25, "unit": "m3", "ifc_class": "IfcWall"},
                    {"description": "garbage", "qty": 1, "unit": "m", "ifc_class": "PDF"},
                ]
            }
        )
        adapter = PdfAdapter(session=None, match_session=sess)
        elements = _run(adapter.iter_elements(project_id=PROJECT_ID))
        assert elements[0].attributes["ifc_class"] == "IfcWall"
        assert "ifc_class" not in elements[1].attributes

    def test_filters_and_excluded_categories(self):
        sess = _fake_session(
            {
                "pdf_rows": [
                    {"description": "Keep DE", "qty": 1, "unit": "m", "category": "Walls", "source_lang": "de"},
                    {"description": "Drop site", "qty": 1, "unit": "m", "category": "Site"},
                    {"description": "Drop RU", "qty": 1, "unit": "m", "category": "Walls", "source_lang": "ru"},
                ]
            }
        )
        adapter = PdfAdapter(session=None, match_session=sess)
        elements = _run(
            adapter.iter_elements(
                project_id=PROJECT_ID,
                filters={"source_lang": ["de"]},
                excluded_categories=["Site"],
            )
        )
        assert len(elements) == 1
        assert elements[0].attributes["description"] == "Keep DE"

    def test_list_categories_and_attribute_keys(self):
        sess = _fake_session(
            {
                "pdf_rows": [
                    {"description": "a", "qty": 1, "unit": "m3", "category": "Walls", "supplier": "Acme"},
                    {"description": "b", "qty": 1, "unit": "m3", "section": "Floors"},
                    {"description": "c", "qty": 1, "unit": "m3"},
                ]
            }
        )
        adapter = PdfAdapter(session=None, match_session=sess)
        cats = dict(_run(adapter.list_categories(PROJECT_ID)))
        assert cats == {"Walls": 1, "Floors": 1, "PDF": 1}
        keys = _run(adapter.list_attribute_keys(PROJECT_ID))
        assert "qty" not in keys
        assert "supplier" in keys
        assert "description" in keys

    def test_malformed_rows_skipped(self):
        sess = _fake_session({"pdf_rows": [{"description": "good", "qty": 1, "unit": "m3"}, "nope", None, 7]})
        adapter = PdfAdapter(session=None, match_session=sess)
        elements = _run(adapter.iter_elements(project_id=PROJECT_ID))
        assert len(elements) == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
