# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Factur-X / ZUGFeRD hybrid PDF builder.

A hybrid e-invoice is a human-readable PDF that carries the machine-readable
EN 16931 CII XML embedded inside it as an associated file, with the Factur-X
XMP metadata that lets a receiver find and trust the XML. ZUGFeRD 2.1 (Germany)
and Factur-X 1.0 (France) are the same thing under two names, and the hybrid
concept is used internationally.

This module renders the readable page with reportlab (already a dependency)
and embeds the CII with pypdf (already a dependency), setting the associated
-file relationship (/AF + /AFRelationship) and the Factur-X XMP that a hybrid
invoice needs. The embedded CII is the legally operative content and is fully
EN 16931 valid (see ``cii.py``).

Note on strict PDF/A-3b: full PDF/A-3b conformance (OutputIntent + ICC colour
profile) is not asserted here. The file is a correct Factur-X hybrid carrying
the XML with the right relationship and metadata; if a receiver demands strict
PDF/A-3b, run the output through a PDF/A post-processor. The XML path (used by
every automated receiver) is unaffected.
"""

from __future__ import annotations

import io
from decimal import Decimal

from pypdf import PdfReader, PdfWriter
from pypdf.generic import (
    ArrayObject,
    DecodedStreamObject,
    DictionaryObject,
    NameObject,
    StreamObject,
    create_string_object,
)
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfgen import canvas

from app.core.pdf_fonts import pdf_font_for_text
from app.modules.einvoice.cii import EInvoice, Party, build_cii_xml
from app.modules.einvoice.pdf_translations import (
    DEFAULT_PDF_LOCALE,
    fmt_date,
    fmt_money,
    fmt_number,
    normalize_pdf_locale,
    tr,
)
from app.modules.einvoice.profiles import get_profile

# Factur-X / ZUGFeRD attachment filename (2.1 uses factur-x.xml for both).
_ATTACHMENT_NAME = "factur-x.xml"

# Conformance level written into the XMP per profile.
_CONFORMANCE = {
    "en16931": "EN 16931",
    "zugferd": "EN 16931",
    "facturx": "EN 16931",
    "xrechnung": "XRECHNUNG",
}


def party_address_lines(p: Party) -> list[str]:
    """The address block of one party, as the readable page should print it.

    The page carried the post code and the city and nothing else, so BT-35 and
    BT-50 reached the receiver's software inside the embedded CII and never
    reached the person reading the page. A hybrid invoice is one document in two
    representations, and the two stated different addresses for the same party
    on every invoice this product has issued, in every country.

    A field the party does not answer produces no line, which is what keeps the
    invoices that carry no street byte-identical to the pages they were before.

    Args:
        p: the seller or buyer trade party.

    Returns:
        The address lines, top to bottom, with nothing empty in them.
    """
    lines = [p.line1, " ".join(x for x in (p.postcode, p.city) if x)]
    return [text.strip() for text in lines if text and text.strip()]


def _readable_pdf(inv: EInvoice, locale: str = DEFAULT_PDF_LOCALE) -> bytes:
    """Render the compact one-page invoice PDF (reportlab) in ``locale``.

    Only the page is localised - labels, date shape, decimal separators and
    thousands grouping. The embedded CII is standard-prescribed and never
    changes with the reader's language.
    """
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    width, height = A4
    left = 20 * mm
    top = height - 25 * mm

    def put(x: float, y: float, text: str, *, base: str, size: int, align_right: bool = False) -> None:
        """Draw one string, in another face only if this one cannot draw it.

        The page is set in Helvetica and stays set in Helvetica. When a string
        needs a different face - a Chinese company name, a squared-metre unit -
        that face is selected for the one string and the Helvetica state is put
        back straight away, so the next string is unaffected.

        The test is which face can draw the characters, not which script they
        belong to, so an invoice that was already all-Latin takes the early
        return on every string and emits exactly the operators it emitted
        before any of this existed. That matters more than it looks: reportlab
        writes a Tf operator for every setFont call without checking whether
        the font actually changed, so selecting a face per string
        unconditionally would move the bytes of every invoice we have ever
        issued, and the two faces do not share a width table.
        """
        draw = c.drawRightString if align_right else c.drawString
        face = pdf_font_for_text(text, base=base)
        if face == base:
            draw(x, y, text)
            return
        c.setFont(face, size)
        draw(x, y, text)
        c.setFont(base, size)

    def fit(text: str, *, base: str, size: int, budget: float, cap: int | None = None) -> str:
        """Clip a string to the narrower of its character cap and its width.

        The character cap is applied first, so this can only ever shorten what
        the page drew before and never lengthen it. A Latin string that fits
        its column comes back untouched, byte for byte; one that already
        overran is now cut at the column edge instead of running across the
        columns to its right.

        The width is measured in the face that will actually draw the string,
        which is the whole point: the two faces do not share a width table, and
        a Han character is close to a full em where a Latin one is about half.
        Measuring in Helvetica would under-count a Chinese name by nearly half
        and clip it in the wrong place.

        No ellipsis is appended. Adding one would move the bytes of any Latin
        invoice whose description is cut at the character cap but still fits
        its column, and that is exactly the case that has to stay identical.

        Args:
            text: the string as it would be drawn.
            base: the face the page is currently set in.
            size: point size the string is drawn at.
            budget: horizontal space to the next fixed offset, in points.
            cap: existing character cap, applied before the width test.

        Returns:
            ``text`` unchanged, or the longest leading run of it that fits.
        """
        clipped = text[:cap] if cap is not None else text
        face = pdf_font_for_text(clipped, base=base)
        if pdfmetrics.stringWidth(clipped, face, size) <= budget:
            return clipped
        # Narrow from the right; the face can change as characters leave, so
        # it is re-asked rather than assumed to stay what it started as.
        while clipped:
            clipped = clipped[:-1]
            if pdfmetrics.stringWidth(clipped, pdf_font_for_text(clipped, base=base), size) <= budget:
                break
        return clipped

    def line(y: float, text: str, *, size: int = 9, bold: bool = False) -> None:
        base = "Helvetica-Bold" if bold else "Helvetica"
        c.setFont(base, size)
        put(left, y, text, base=base, size=size)

    def right(y: float, text: str, *, size: int = 9, bold: bool = False) -> None:
        base = "Helvetica-Bold" if bold else "Helvetica"
        c.setFont(base, size)
        put(width - 20 * mm, y, text, base=base, size=size, align_right=True)

    line(top, tr(locale, "doc_title"), size=16, bold=True)
    right(top, f"{inv.invoice_number}", size=12, bold=True)
    y = top - 8 * mm
    right(y, tr(locale, "date", value=fmt_date(inv.issue_date, locale)))
    if inv.due_date:
        right(y - 5 * mm, tr(locale, "due", value=fmt_date(inv.due_date, locale)))

    # Parties
    y = top - 20 * mm
    line(y, tr(locale, "from"), bold=True)
    # The seller block runs to the bill-to column at left + 90mm, the buyer
    # block from there to the right margin, and the description column to the
    # quantity figure at left + 95mm. Those are the three strings a party can
    # make arbitrarily long, so each is clipped at the offset that follows it.
    seller_budget = 90 * mm
    sy = y - 5 * mm
    line(sy, fit(inv.seller.name, base="Helvetica", size=9, budget=seller_budget))
    for text in party_address_lines(inv.seller):
        sy -= 5 * mm
        line(sy, fit(text, base="Helvetica", size=9, budget=seller_budget))
    if inv.seller.vat_id:
        sy -= 5 * mm
        line(sy, tr(locale, "vat_id", value=inv.seller.vat_id))

    c.setFont("Helvetica-Bold", 9)
    put(left + 90 * mm, y, tr(locale, "bill_to"), base="Helvetica-Bold", size=9)
    c.setFont("Helvetica", 9)
    buyer_budget = (width - 20 * mm) - (left + 90 * mm)
    by = y - 5 * mm
    put(
        left + 90 * mm,
        by,
        fit(inv.buyer.name, base="Helvetica", size=9, budget=buyer_budget),
        base="Helvetica",
        size=9,
    )
    for text in party_address_lines(inv.buyer):
        by -= 5 * mm
        put(
            left + 90 * mm,
            by,
            fit(text, base="Helvetica", size=9, budget=buyer_budget),
            base="Helvetica",
            size=9,
        )
    if inv.buyer_reference:
        by -= 5 * mm
        put(left + 90 * mm, by, tr(locale, "ref", value=inv.buyer_reference), base="Helvetica", size=9)

    # Line table header. The party blocks used to be three lines each and the
    # header sat at a fixed offset below them; an address is as many lines as
    # its country writes, so the header takes whichever is lower, its old place
    # or one line under the deeper of the two blocks. A party that answers what
    # it answered before puts the header back exactly where it was.
    ty = min(y - 30 * mm, min(sy, by) - 5 * mm)
    c.setFont("Helvetica-Bold", 8)
    put(left, ty, tr(locale, "th_description"), base="Helvetica-Bold", size=8)
    put(left + 95 * mm, ty, tr(locale, "th_qty"), base="Helvetica-Bold", size=8, align_right=True)
    put(left + 100 * mm, ty, tr(locale, "th_unit"), base="Helvetica-Bold", size=8)
    put(left + 140 * mm, ty, tr(locale, "th_unit_price"), base="Helvetica-Bold", size=8, align_right=True)
    put(
        width - 20 * mm,
        ty,
        tr(locale, "th_net", currency=inv.currency),
        base="Helvetica-Bold",
        size=8,
        align_right=True,
    )
    c.setLineWidth(0.4)
    c.line(left, ty - 2 * mm, width - 20 * mm, ty - 2 * mm)

    c.setFont("Helvetica", 8)
    ry = ty - 7 * mm
    for ln in inv.lines:
        put(
            left,
            ry,
            fit(ln.name or "-", base="Helvetica", size=8, budget=95 * mm, cap=60),
            base="Helvetica",
            size=8,
        )
        put(left + 95 * mm, ry, fmt_number(ln.quantity, locale), base="Helvetica", size=8, align_right=True)
        put(left + 100 * mm, ry, (ln.unit or "")[:8], base="Helvetica", size=8)
        put(
            left + 140 * mm,
            ry,
            fmt_money(ln.net_unit_price, inv.currency, locale),
            base="Helvetica",
            size=8,
            align_right=True,
        )
        put(
            width - 20 * mm,
            ry,
            fmt_money(ln.line_net_amount, inv.currency, locale),
            base="Helvetica",
            size=8,
            align_right=True,
        )
        ry -= 5 * mm
        if ry < 40 * mm:  # keep it one page for the v1 layout
            break

    # Totals
    c.setLineWidth(0.4)
    c.line(left + 100 * mm, ry - 1 * mm, width - 20 * mm, ry - 1 * mm)
    ry -= 6 * mm

    def total_row(label: str, amount: Decimal, *, bold: bool = False) -> None:
        nonlocal ry
        base = "Helvetica-Bold" if bold else "Helvetica"
        c.setFont(base, 9)
        put(left + 140 * mm, ry, label, base=base, size=9, align_right=True)
        amount_text = f"{fmt_money(amount, inv.currency, locale)} {inv.currency}"
        put(width - 20 * mm, ry, amount_text, base=base, size=9, align_right=True)
        ry -= 5 * mm

    total_row(tr(locale, "net_total"), inv.tax_basis_total)
    total_row(tr(locale, "vat_total"), inv.tax_total)
    total_row(tr(locale, "grand_total"), inv.grand_total, bold=True)
    if inv.prepaid_amount:
        total_row(tr(locale, "retention_prepaid"), inv.prepaid_amount)
    total_row(tr(locale, "amount_due"), inv.due_payable, bold=True)

    # Where to pay. The embedded XML carries BT-84 for the buyer's software;
    # a person reading the page needs to see the same account.
    if inv.payee_iban:
        ry -= 4 * mm
        c.setFont("Helvetica-Bold", 8)
        put(left, ry, tr(locale, "payment"), base="Helvetica-Bold", size=8)
        c.setFont("Helvetica", 8)
        ry -= 5 * mm
        put(left, ry, tr(locale, "iban", value=inv.payee_iban), base="Helvetica", size=8)
        if inv.payee_bic:
            put(left + 70 * mm, ry, tr(locale, "bic", value=inv.payee_bic), base="Helvetica", size=8)
        if inv.payee_account_name:
            ry -= 5 * mm
            # The fourth party-controlled string, and the widest budget on the
            # page: this row is alone, so it runs from the left margin to the
            # right one. The label is ours and stays whole, only the name the
            # payee supplied is clipped.
            holder_budget = (width - 20 * mm) - left
            put(
                left,
                ry,
                fit(
                    tr(locale, "account_holder", value=inv.payee_account_name),
                    base="Helvetica",
                    size=8,
                    budget=holder_budget,
                ),
                base="Helvetica",
                size=8,
            )

    c.setFont("Helvetica-Oblique", 7)
    c.setFillColor(colors.grey)
    put(left, 20 * mm, tr(locale, "footer"), base="Helvetica-Oblique", size=7)
    c.showPage()
    c.save()
    return buf.getvalue()


def _xmp(profile_name: str) -> bytes:
    """Factur-X XMP metadata packet (identifies the embedded CII)."""
    conformance = _CONFORMANCE.get(profile_name, "EN 16931")
    return (
        """<?xpacket begin="﻿" id="W5M0MpCehiHzreSzNTczkc9d"?>
<x:xmpmeta xmlns:x="adobe:ns:meta/">
 <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
  <rdf:Description rdf:about="" xmlns:pdfaid="http://www.aiim.org/pdfa/ns/id/">
   <pdfaid:part>3</pdfaid:part>
   <pdfaid:conformance>B</pdfaid:conformance>
  </rdf:Description>
  <rdf:Description rdf:about=""
      xmlns:fx="urn:factur-x:pdfa:CrossIndustryDocument:invoice:1p0#">
   <fx:DocumentType>INVOICE</fx:DocumentType>
   <fx:DocumentFileName>"""
        + _ATTACHMENT_NAME
        + """</fx:DocumentFileName>
   <fx:Version>1.0</fx:Version>
   <fx:ConformanceLevel>"""
        + conformance
        + """</fx:ConformanceLevel>
  </rdf:Description>
 </rdf:RDF>
</x:xmpmeta>
<?xpacket end="w"?>"""
    ).encode("utf-8")


def _embed_cii(pdf_bytes: bytes, xml_bytes: bytes, profile_name: str) -> bytes:
    """Embed the CII XML as a Factur-X associated file and add the XMP."""
    reader = PdfReader(io.BytesIO(pdf_bytes))
    writer = PdfWriter()
    writer.append(reader)

    # Embedded file stream.
    ef = DecodedStreamObject()
    ef.set_data(xml_bytes)
    ef[NameObject("/Type")] = NameObject("/EmbeddedFile")
    ef[NameObject("/Subtype")] = NameObject("/text#2Fxml")
    ef_ref = writer._add_object(ef)

    filespec = DictionaryObject()
    filespec[NameObject("/Type")] = NameObject("/Filespec")
    filespec[NameObject("/F")] = create_string_object(_ATTACHMENT_NAME)
    filespec[NameObject("/UF")] = create_string_object(_ATTACHMENT_NAME)
    # /Alternative, not /Data: Factur-X 1.0 and ZUGFeRD 2.1 both require it,
    # because the XML is another rendering of the same invoice rather than a
    # supplement to it. A receiver that selects associated files by
    # relationship finds nothing under /Data, and the failure is silent: the
    # attachment is still present, still named correctly, and still parses.
    filespec[NameObject("/AFRelationship")] = NameObject("/Alternative")
    filespec[NameObject("/Desc")] = create_string_object("Factur-X/ZUGFeRD invoice")
    ef_dict = DictionaryObject()
    ef_dict[NameObject("/F")] = ef_ref
    ef_dict[NameObject("/UF")] = ef_ref
    filespec[NameObject("/EF")] = ef_dict
    filespec_ref = writer._add_object(filespec)

    # Catalog: /Names /EmbeddedFiles and /AF (associated files).
    root = writer._root_object
    names_arr = ArrayObject([create_string_object(_ATTACHMENT_NAME), filespec_ref])
    ef_tree = DictionaryObject()
    ef_tree[NameObject("/Names")] = names_arr
    names_dict = DictionaryObject()
    names_dict[NameObject("/EmbeddedFiles")] = ef_tree
    root[NameObject("/Names")] = names_dict
    root[NameObject("/AF")] = ArrayObject([filespec_ref])

    # XMP metadata stream on the catalog.
    meta = StreamObject()
    meta.set_data(_xmp(profile_name))
    meta[NameObject("/Type")] = NameObject("/Metadata")
    meta[NameObject("/Subtype")] = NameObject("/XML")
    root[NameObject("/Metadata")] = writer._add_object(meta)

    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def build_facturx_pdf(inv: EInvoice, *, strict: bool = True, locale: str = DEFAULT_PDF_LOCALE) -> bytes:
    """Build a Factur-X / ZUGFeRD hybrid PDF for a CII-profile invoice.

    Args:
        inv: the fully populated invoice.
        strict: refuse to render an invoice that fails validation.
        locale: language of the readable page (``"en"`` or ``"de"``); the
            embedded CII XML is locale-independent by design.
    """
    profile = get_profile(inv.profile)
    if profile is None or profile.syntax != "cii":
        from app.modules.einvoice.cii import EInvoiceError

        raise EInvoiceError(f"hybrid PDF needs a CII profile (zugferd/facturx/xrechnung/en16931), got {inv.profile!r}")
    xml_bytes = build_cii_xml(inv, strict=strict)
    pdf_bytes = _readable_pdf(inv, normalize_pdf_locale(locale))
    return _embed_cii(pdf_bytes, xml_bytes, inv.profile)
