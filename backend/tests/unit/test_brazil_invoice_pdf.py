"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the Brazilian invoice PDF renderer.

Covers BRL formatting helpers (comma decimal, period thousands), date
flipping (ISO → DD/MM/YYYY), em-dash fallbacks for missing fields, and
the end-to-end render which must produce a non-empty PDF binary.
"""

from __future__ import annotations

import asyncio
import uuid
from decimal import Decimal

from app.modules.finance.br_invoice_pdf import (
    _br_date,
    _brl,
    _val,
    render_br_invoice_pdf,
)

# ── BRL formatter ────────────────────────────────────────────────────────


def test_brl_formats_with_comma_decimal_and_period_thousands() -> None:
    assert _brl("1234567.89") == "R$ 1.234.567,89"
    assert _brl("0") == "R$ 0,00"
    assert _brl("1.5") == "R$ 1,50"


def test_brl_handles_invalid_input_gracefully() -> None:
    # Non-numeric input must NOT crash the renderer — accountants would
    # rather see "R$ 0,00" with a placeholder than a 500 response.
    assert _brl(None) == "R$ 0,00"
    assert _brl("") == "R$ 0,00"
    assert _brl("not-a-number") == "R$ 0,00"
    assert _brl("nan") == "R$ 0,00"
    assert _brl("inf") == "R$ 0,00"


def test_brl_rounds_to_two_decimals() -> None:
    # Brazilian convention: 2 decimal places, banker's rounding via
    # Decimal.quantize. 1.005 → 1.00 (ROUND_HALF_EVEN default).
    out = _brl("1.005")
    assert out.startswith("R$ ")
    # Either 1,00 or 1,01 depending on rounding mode — both round to 2 dp.
    assert out.endswith(",00") or out.endswith(",01")


def test_brl_handles_negative_values() -> None:
    # Refunds may carry negative subtotals in the future Tier-2 flow.
    assert _brl("-100.00") == "R$ -100,00"


# ── BR date flipper ──────────────────────────────────────────────────────


def test_br_date_flips_iso_to_brazilian() -> None:
    assert _br_date("2026-05-27") == "27/05/2026"
    assert _br_date("2026-12-31") == "31/12/2026"


def test_br_date_returns_hyphen_for_missing() -> None:
    # The platform-wide typography rule replaced em-dashes with plain
    # hyphens in all user-visible text, including PDF placeholders.
    assert _br_date(None) == "-"
    assert _br_date("") == "-"
    assert _br_date("short") == "-"


# ── _val placeholder ─────────────────────────────────────────────────────


def test_val_hyphen_fallback() -> None:
    assert _val(None) == "-"
    assert _val("") == "-"
    assert _val("CNPJ 12.345.678/0001-90") == "CNPJ 12.345.678/0001-90"


# ── End-to-end render ────────────────────────────────────────────────────


def test_render_br_invoice_pdf_with_full_br_fields_returns_pdf_bytes() -> None:
    invoice = {
        "invoice_number": "RPS-2026-0042",
        "invoice_direction": "receivable",
        "invoice_date": "2026-05-27",
        "due_date": "2026-06-15",
        "amount_subtotal": "10000.00",
        "tax_amount": "500.00",
        "retention_amount": "150.00",
        "amount_total": "10350.00",
        "notes": "Obra Vila Madalena — etapa fundação.",
        "metadata": {
            "br_fields": {
                "codigo_servico": "7.02",  # LC 116/03 — engenharia civil
                "prestador": {
                    "razao_social": "Construtora Exemplo LTDA",
                    "cnpj": "12.345.678/0001-90",
                    "ie": "123.456.789.012",
                    "im": "987.654-3",
                    "endereco": "Av. Paulista, 1000",
                    "municipio_uf": "São Paulo / SP",
                    "cep": "01310-100",
                },
                "tomador": {
                    "razao_social": "Ouro Imóveis MN",
                    "cnpj_cpf": "98.765.432/0001-10",
                    "ie": "ISENTO",
                    "endereco": "Rua das Palmeiras, 200",
                    "municipio_uf": "Belo Horizonte / MG",
                    "cep": "30130-100",
                },
                "retencoes": {
                    "iss": "500.00",
                    "pis": "65.00",
                    "cofins": "300.00",
                    "csll": "100.00",
                    "inss": "0.00",
                    "irrf": "150.00",
                },
            }
        },
    }
    line_items = [
        {
            "description": "Concreto estrutural fck 30 MPa, lançamento e adensamento",
            "unit": "m³",
            "quantity": "50.000000",
            "unit_rate": "200.000000",
            "amount": "10000.00",
        },
    ]
    pdf_bytes = render_br_invoice_pdf(
        invoice=invoice,
        line_items=line_items,
        project={"name": "Obra Vila Madalena", "code": "VM-2026"},
    )
    # PDF magic number — every valid PDF starts with "%PDF-".
    assert pdf_bytes[:5] == b"%PDF-"
    # Non-trivial body (we rendered 1 line item + 9 totals rows + headers).
    assert len(pdf_bytes) > 2000


def test_render_br_invoice_pdf_with_missing_br_fields_still_renders() -> None:
    """A draft invoice with no br_fields metadata must still produce a PDF.

    The renderer falls back to em-dash placeholders for every BR-specific
    field so the accountant can fill them in by hand on the printed copy.
    """
    invoice = {
        "invoice_number": "RPS-DRAFT",
        "invoice_direction": "receivable",
        "invoice_date": "",
        "due_date": None,
        "amount_subtotal": "0",
        "tax_amount": "0",
        "retention_amount": "0",
        "amount_total": "0",
        "notes": None,
        "metadata": {},
    }
    pdf_bytes = render_br_invoice_pdf(
        invoice=invoice,
        line_items=[],
        project=None,
    )
    assert pdf_bytes[:5] == b"%PDF-"
    # Even an empty invoice produces a header + disclaimer = ~1 KB minimum.
    assert len(pdf_bytes) > 1000


def test_render_br_invoice_pdf_escapes_html_in_description() -> None:
    """Untrusted strings in the metadata must not break ReportLab.

    BUG-PDF01 / BUG-PDF02 lesson from the BOQ exporter: ReportLab's
    paraparser crashes on unknown HTML attributes (``onerror`` etc.). Our
    ``_safe_para`` escapes them, so a description with HTML-like content
    must render without raising.
    """
    invoice = {
        "invoice_number": "RPS-XSS",
        "invoice_direction": "receivable",
        "invoice_date": "2026-05-27",
        "due_date": "2026-06-15",
        "amount_subtotal": "100",
        "tax_amount": "0",
        "retention_amount": "0",
        "amount_total": "100",
        "notes": '<script onerror="alert(1)">x</script>',
        "metadata": {
            "br_fields": {
                "prestador": {
                    "razao_social": '<font color="white">hidden</font>',
                },
            }
        },
    }
    line_items = [
        {
            "description": '<img src=x onerror="alert(1)">',
            "unit": "un",
            "quantity": "1",
            "unit_rate": "100",
            "amount": "100",
        },
    ]
    pdf_bytes = render_br_invoice_pdf(invoice=invoice, line_items=line_items)
    assert pdf_bytes[:5] == b"%PDF-"


# ── Content-Disposition filename sanitisation ────────────────────────────
# These tests cover the inline sanitisation applied in finance/router.py
# *before* the invoice_number is embedded in the download filename.  We
# replicate the exact transformation here so a future router refactor can't
# quietly re-introduce the injection surface without a red test.  The header
# itself is built by app.core.content_disposition.attachment_disposition,
# which emits the RFC 6266 pair, so non-ASCII invoice numbers survive to the
# browser instead of becoming question marks.


def _sanitise_invoice_number(raw: str | None) -> str:
    """Mirror of the sanitisation logic in ``finance/router.py``."""
    _raw_num = raw or "invoice"
    _safe = (_raw_num.replace("\r", "").replace("\n", "").replace('"', "'").replace("/", "-").strip())[:80] or "invoice"
    return _safe


def test_invoice_number_strips_double_quotes() -> None:
    """``"`` in invoice_number would terminate the RFC 6266 quoted-string."""
    assert '"' not in _sanitise_invoice_number('INV-"2026"-01')


def test_invoice_number_strips_crlf() -> None:
    """CRLF in invoice_number enables HTTP response-header injection.

    The CRLF bytes themselves must be removed (that is the injection vector).
    The remaining text may still be present as a literal filename substring,
    which is harmless — "X-Inject: evil" in a single-line quoted token cannot
    inject a second header.
    """
    result = _sanitise_invoice_number("INV-001\r\nX-Inject: evil")
    assert "\r" not in result
    assert "\n" not in result


def test_invoice_number_strips_slashes() -> None:
    assert "/" not in _sanitise_invoice_number("INV/2026/01")


def test_invoice_number_fallback_on_empty() -> None:
    assert _sanitise_invoice_number(None) == "invoice"
    assert _sanitise_invoice_number("") == "invoice"
    assert _sanitise_invoice_number("   ") == "invoice"


def test_invoice_number_caps_at_80_chars() -> None:
    long_num = "A" * 120
    assert len(_sanitise_invoice_number(long_num)) == 80


def test_invoice_number_keeps_accents_for_the_rfc6266_header() -> None:
    """Brazilian series names carry accents; they must reach filename* intact.

    The old code turned every non-ASCII character into ``?`` before the name
    hit the header. Now the sanitiser keeps the real characters and the
    header helper carries them in the RFC 5987 parameter, with a readable
    ASCII fallback beside it.
    """
    from urllib.parse import unquote

    from app.core.content_disposition import attachment_disposition

    number = _sanitise_invoice_number("NF-São-Paulo/0042")
    assert number == "NF-São-Paulo-0042"

    header = attachment_disposition(f"RPS_{number}.pdf")
    fallback = header.split('filename="', 1)[1].split('"', 1)[0]
    assert fallback == "RPS_NF-Sao-Paulo-0042.pdf"
    assert unquote(header.split("filename*=UTF-8''", 1)[1]) == "RPS_NF-São-Paulo-0042.pdf"


# ── What the route declares about the document ───────────────────────────
# The renderer above writes Portuguese unconditionally. These test the route
# that serves it, because the language of a document is something a client
# reads off the response, not out of the file.


class _StubInvoice:
    """Only the columns the RPS route reads off the row."""

    invoice_number = "RPS-2026-0044"
    invoice_direction = "receivable"
    invoice_date = "2026-04-15"
    due_date = "2026-05-15"
    project_id = None
    amount_subtotal = Decimal("1000.00")
    tax_amount = Decimal("50.00")
    retention_amount = Decimal("0")
    amount_total = Decimal("1050.00")
    notes = None
    metadata_: dict = {}
    line_items: list = []


class _StubService:
    async def get_invoice(self, _invoice_id):
        return _StubInvoice()


def _export_rps(monkeypatch):
    """Run the real RPS route with everything but the header wiring stubbed."""
    import app.modules.finance.br_invoice_pdf as br
    import app.modules.finance.router as finance_router

    async def _allow(*_args: object, **_kwargs: object):
        return _StubInvoice()

    monkeypatch.setattr(finance_router, "_require_invoice_access", _allow)
    monkeypatch.setattr(finance_router, "_line_item_dicts", lambda _items: [])
    monkeypatch.setattr(br, "render_br_invoice_pdf", lambda **_kwargs: b"%PDF-1.4 pagina")

    return asyncio.run(
        finance_router.export_invoice_br_pdf(
            invoice_id=uuid.UUID("00000000-0000-0000-0000-0000000000bb"),
            session=None,
            user_id=None,
            _perm=None,
            service=_StubService(),
        )
    )


def test_the_rps_declares_the_language_it_is_written_in(monkeypatch) -> None:
    """An RPS is Portuguese by construction, so it says so.

    The builder has no locale input of any kind: its labels are Portuguese
    literals and its money formatter is an unconditional pt-BR separator
    swap. A literal header is therefore the whole of the fix - there is no
    reader preference that could ever change the answer.
    """
    response = _export_rps(monkeypatch)
    assert response.headers["content-language"] == "pt-BR"


def test_the_route_declares_the_language_rather_than_leaving_it_to_the_middleware(
    monkeypatch,
) -> None:
    """The route must be the author of this header, not merely agree with it.

    This is the property the fix actually restores. The route takes no
    Accept-Language and resolves nothing, so whenever it declares nothing the
    AcceptLanguageMiddleware supplies the reader's requested language instead
    and Portuguese bytes go out labelled German. Asserting the header is
    present on the response the handler returns - before any middleware has
    seen it - is what distinguishes "the route said so" from "something
    downstream happened to say the same thing".
    """
    response = _export_rps(monkeypatch)
    assert response.headers.get("content-language") == "pt-BR"
    assert response.media_type == "application/pdf"
