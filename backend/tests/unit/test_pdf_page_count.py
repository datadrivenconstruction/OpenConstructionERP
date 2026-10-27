# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import io

from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate

from app.core.pdf_branding import build_with_page_count


def test_footer_learns_the_total_before_the_real_build():
    seen: list[tuple[int, int]] = []

    def on_page(canvas, doc):
        seen.append((doc.page, getattr(doc, "page_count", 0)))

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf)
    style = getSampleStyleSheet()["Normal"]
    story = [Paragraph("one", style), PageBreak(), Paragraph("two", style), PageBreak(), Paragraph("three", style)]
    build_with_page_count(doc, story, onFirstPage=on_page, onLaterPages=on_page)

    assert seen[-3:] == [(1, 3), (2, 3), (3, 3)]
    assert buf.getvalue().startswith(b"%PDF")
