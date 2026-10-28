# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The readable page of the hybrid PDF speaks the reader's language.

The embedded CII is standard-prescribed (ISO dates, decimal points) and must
never vary with the locale; the page exists for a human and follows their
conventions - German labels, DD.MM.YYYY, decimal comma, thousands dot. These
tests read the page the way a person does (extracted text) and the XML the way
a machine does, and hold the two to their different contracts.
"""

import asyncio
import io
import uuid
from decimal import Decimal

from pypdf import PdfReader

from app.modules.einvoice import build_einvoice
from app.modules.einvoice.pdf_embed import build_facturx_pdf
from app.modules.einvoice.pdf_translations import fmt_date, fmt_money, resolve_pdf_locale


def _invoice() -> dict:
    return {
        "invoice_number": "AR-2026-014",
        "invoice_direction": "receivable",
        "invoice_date": "2026-04-15",
        "due_date": "2026-05-15",
        "currency_code": "EUR",
        "amount_subtotal": Decimal("1850000.00"),
        "tax_amount": Decimal("351500.00"),
        "retention_amount": Decimal("0"),
        "amount_total": Decimal("2201500.00"),
        "notes": None,
        "metadata": {
            "einvoice": {
                "vat_rate": "19",
                "buyer_reference": "06-4300251-83",
                "payee_iban": "DE89370400440532013000",
                "payee_account_name": "Hochbau Rhein-Main GmbH",
                "seller": {
                    "name": "Hochbau Rhein-Main GmbH",
                    "vat_id": "DE812345678",
                    "city": "Frankfurt am Main",
                    "postcode": "60327",
                    "country_code": "DE",
                },
                "buyer": {
                    "name": "PVG Projektentwicklung Europaviertel GmbH",
                    "city": "Frankfurt am Main",
                    "postcode": "60308",
                    "country_code": "DE",
                },
            }
        },
    }


def _lines() -> list[dict]:
    return [
        {
            "description": "Rohbauarbeiten UG2-UG1 gem. Aufmaß",
            "unit": "psch",
            "quantity": Decimal("1"),
            "unit_rate": Decimal("1240000.00"),
            "amount": Decimal("1240000.00"),
        },
        {
            "description": "Rohbauarbeiten EG-3.OG gem. Aufmaß",
            "unit": "psch",
            "quantity": Decimal("1"),
            "unit_rate": Decimal("610000.00"),
            "amount": Decimal("610000.00"),
        },
    ]


def _page_text(pdf_bytes: bytes) -> str:
    reader = PdfReader(io.BytesIO(pdf_bytes))
    return "\n".join((page.extract_text() or "") for page in reader.pages)


def _build(locale: str) -> bytes:
    ei = build_einvoice(invoice=_invoice(), line_items=_lines(), profile="zugferd")
    return build_facturx_pdf(ei, locale=locale)


def test_the_german_page_is_german_end_to_end():
    text = _page_text(_build("de"))
    assert "RECHNUNG" in text
    assert "Datum: 15.04.2026" in text
    assert "Fällig: 15.05.2026" in text
    assert "Rechnung an" in text
    assert "Käuferreferenz: 06-4300251-83" in text
    assert "USt-IdNr.: DE812345678" in text
    # de-DE money: thousands dot, decimal comma.
    assert "1.240.000,00" in text
    assert "2.201.500,00 EUR" in text
    assert "Nettobetrag" in text
    assert "Gesamtbetrag" in text
    assert "Zahlbetrag" in text
    assert "Kontoinhaber" in text
    # None of the English frame survives.
    for english in ("INVOICE", "Bill to", "Net total", "Grand total", "Amount due", "Account holder"):
        assert english not in text, english


def test_the_english_page_keeps_its_labels_and_gains_grouping():
    text = _page_text(_build("en"))
    assert "INVOICE" in text
    assert "Date: 2026-04-15" in text
    assert "Bill to" in text
    assert "1,240,000.00" in text
    assert "2,201,500.00 EUR" in text


def test_the_embedded_xml_does_not_vary_with_the_page_language():
    """ISO dates and decimal points in the XML are the standard, not a locale."""
    de_reader = PdfReader(io.BytesIO(_build("de")))
    en_reader = PdfReader(io.BytesIO(_build("en")))
    de_xml = de_reader.attachments["factur-x.xml"][0]
    assert de_xml == en_reader.attachments["factur-x.xml"][0]
    assert b"20260415" in de_xml  # CII format 102 date, untouched
    assert b"2201500.00" in de_xml  # decimal point, untouched


def test_a_locale_the_catalogue_lacks_degrades_to_an_english_page():
    """Not a decision - a degradation, and the route has to declare it.

    The catalogue holds two languages while the interface offers forty, so a
    reader can ask for one the page cannot be written in. Serving English is
    the chosen behaviour; serving it *silently* was the defect. The route
    pairs this with ``Content-Language: en`` so the client can tell.

    Pinned with ``zz`` rather than a real language: a test that spells the
    unsupported case as ``fr`` stops describing the mechanism the day French
    is added, and reads until then as though English were the right answer
    for a French reader.
    """
    text = _page_text(_build("zz"))
    assert "INVOICE" in text


def test_locale_resolution_prefers_the_query_then_the_header():
    assert resolve_pdf_locale("de", None) == "de"
    assert resolve_pdf_locale("de-DE", "en") == "de"
    assert resolve_pdf_locale(None, "de-DE,de;q=0.9,en;q=0.8") == "de"
    assert resolve_pdf_locale(None, "zz-ZZ,zz;q=0.9") == "en"
    assert resolve_pdf_locale(None, None) == "en"


def test_the_de_formatters_alone():
    assert fmt_money(Decimal("1234567.5"), "EUR", "de") == "1.234.567,50"
    assert fmt_money(Decimal("1234567.5"), "EUR", "en") == "1,234,567.50"
    assert fmt_money(Decimal("1000"), "JPY", "de") == "1.000"
    assert fmt_date("2026-04-15", "de") == "15.04.2026"
    assert fmt_date("2026-04-15", "en") == "2026-04-15"
    assert fmt_date("not-a-date", "de") == "not-a-date"


# ── What reaches the wire ────────────────────────────────────────────────
# Everything above tests the resolver and the page. These test the export
# route: that the language it resolved is stated on the response, which is
# the only part of the answer a client can read without opening the file.


class _StubInvoice:
    """Only the columns the export route reads off the row."""

    id = uuid.UUID("00000000-0000-0000-0000-0000000000aa")
    contact_id = None
    invoice_number = "AR-2026-014"
    invoice_direction = "receivable"
    invoice_date = "2026-04-15"
    due_date = "2026-05-15"
    currency_code = "EUR"
    amount_subtotal = Decimal("1000.00")
    tax_amount = Decimal("190.00")
    retention_amount = Decimal("0")
    amount_total = Decimal("1190.00")
    notes = None
    metadata_: dict = {}
    line_items: list = []


class _StubService:
    async def get_invoice(self, _invoice_id):
        return _StubInvoice()


def _export(monkeypatch, *, embed: bool, accept_language: str | None, locale: str | None = None):
    """Run the real route body with everything but the header wiring stubbed.

    Access control, the row fetch, the party defaults and the renderers are
    stubbed because none of them is under test and each is covered elsewhere.
    What is not stubbed is the part that was wrong: the route resolving a
    language and putting it on the response.
    """
    import app.modules.einvoice as einvoice_pkg
    import app.modules.finance.einvoice_parties as parties
    import app.modules.finance.router as finance_router

    async def _allow(*_args: object, **_kwargs: object) -> None:
        return None

    async def _defaults(*_args: object, **_kwargs: object) -> dict:
        return {}

    def _pdf(*, locale: str, **_kwargs: object) -> tuple[str, str, bytes]:
        return (f"invoice-{locale}.pdf", "application/pdf", b"%PDF-1.4 page")

    def _xml(**_kwargs: object) -> tuple[str, str, bytes]:
        return ("invoice.xml", "application/xml", b"<CrossIndustryInvoice/>")

    monkeypatch.setattr(finance_router, "_require_invoice_access", _allow)
    monkeypatch.setattr(finance_router, "_line_item_dicts", lambda _items: [])
    monkeypatch.setattr(parties, "einvoice_defaults_for_invoice", _defaults)
    monkeypatch.setattr(einvoice_pkg, "render_einvoice_pdf", _pdf)
    monkeypatch.setattr(einvoice_pkg, "render_einvoice", _xml)

    return asyncio.run(
        finance_router.export_invoice_einvoice(
            invoice_id=_StubInvoice.id,
            session=None,
            fmt="xrechnung",
            dry_run=False,
            embed=embed,
            locale=locale,
            accept_language=accept_language,
            user_id=None,
            _perm=None,
            service=_StubService(),
        )
    )


def test_the_hybrid_pdf_declares_the_language_it_was_written_in(monkeypatch):
    response = _export(monkeypatch, embed=True, accept_language="de-DE,de;q=0.9")
    assert response.headers["content-language"] == "de"


def test_a_pdf_the_catalogue_cannot_write_declares_english_not_the_request(monkeypatch):
    """The header states the page, not the wish.

    ``zz`` is unassigned and stays unassigned, so this keeps describing the
    degradation after any language is added. Without the route saying ``en``,
    the Accept-Language middleware labels these English bytes with whatever
    was asked for, which is a false statement in a header receivers act on.
    """
    response = _export(monkeypatch, embed=True, accept_language="zz-ZZ,zz;q=0.9")
    assert response.headers["content-language"] == "en"


def test_an_explicit_locale_query_beats_the_header_on_the_response_too(monkeypatch):
    response = _export(monkeypatch, embed=True, accept_language="de-DE,de;q=0.9", locale="en")
    assert response.headers["content-language"] == "en"


def test_the_bare_xml_branch_declares_nothing(monkeypatch):
    """The route makes no language claim for a machine document.

    Not the same as the response carrying none: the middleware still stamps
    the reader's language on this branch. Whether a CII stream should carry
    a language at all is a separate decision from the page's, and this pins
    that the route currently leaves it alone.
    """
    response = _export(monkeypatch, embed=False, accept_language="zz-ZZ,zz;q=0.9")
    assert "content-language" not in response.headers
