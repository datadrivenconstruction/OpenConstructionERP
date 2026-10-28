"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Does the invoice we emit add up, measured the way its receiver adds it up?

BR-CO-10 says the document line total (BT-106) is the sum of the line net
amounts (BT-131), with no tolerance. A receiver checks that against the figures
written in the file, so this test does too: it renders the document, parses it
back, and sums the strings that were actually emitted.

Going through ``check()`` instead would measure the same rounding twice. That
validator rounds both sides of the comparison before comparing them, which is
correct for the object it is handed and blind to a document whose own written
figures disagree. The subject here is the emitted document, not the object.

The four currencies put the one that always worked beside the three that did
not: EUR carries two minor units, JPY, HUF and CLP carry none. Only on a
zero-decimal currency can an amount be written differently from the way it was
added up, and only then does an accumulated total drift away from its own
lines. BR-CO-15 and BR-CO-16 are here for the same reason, at fractions chosen
to sit on the rounding boundary, because a total that reconciles at one value
says nothing about the value next to it.

Nothing here asserts how many minor units a currency has. That is independence
from the question, not a note that the question is open: HUF and IDR are
settled at zero, in ``app.core.money`` and again in
``app.modules.einvoice.rules``, each with its reasoning recorded beside it.
Every assertion below compares the document against itself, so it holds at the
count those two record today and would still hold if either were revisited.
"""

import io
import xml.etree.ElementTree as ET
from decimal import Decimal

import pytest
from pypdf import PdfReader

from app.modules.einvoice import build_einvoice
from app.modules.einvoice.cii import RAM, EInvoice, build_cii_xml
from app.modules.einvoice.pdf_embed import build_facturx_pdf
from app.modules.einvoice.pdf_translations import DEFAULT_PDF_LOCALE, fmt_money
from app.modules.einvoice.ubl import CAC, CBC, build_ubl_xml

# EUR is the control: two minor units, so nothing is ever trimmed off a line.
CURRENCIES = ("EUR", "JPY", "HUF", "CLP")
LINE_COUNT = 3


def _party(**over: object) -> dict:
    party = {
        "name": "Bau GmbH",
        "vat_id": "DE123456789",
        "line1": "Baustrasse 1",
        "postcode": "10115",
        "city": "Berlin",
        "country_code": "DE",
    }
    party.update(over)
    return party


def _document(
    currency: str,
    *,
    profile: str = "zugferd",
    line_amount: str = "100.40",
    line_rate: str | None = "19",
    tax_amount: str = "0",
    retention: str = "0",
) -> EInvoice:
    """One invoice with ``LINE_COUNT`` identical lines, built the normal way.

    ``line_rate`` of None leaves every line without a rate of its own, which is
    the branch where the stored header VAT total stays authoritative instead of
    being recomputed from the lines.
    """
    line: dict = {
        "description": "Concrete C30/37",
        "unit": "m3",
        "quantity": Decimal("1"),
        "amount": Decimal(line_amount),
    }
    if line_rate is not None:
        line["vat_rate"] = Decimal(line_rate)
        # A rate without a category would inherit the zero-rated default and
        # fail BR-Z-5 before this test could measure anything.
        line["vat_category"] = "S"
    lines = [dict(line, line_id=str(i)) for i in range(1, LINE_COUNT + 1)]
    invoice = {
        "invoice_number": "RE-2026-0421",
        "invoice_date": "2026-08-21",
        "due_date": "2026-09-20",
        "currency_code": currency,
        "amount_subtotal": Decimal(line_amount) * LINE_COUNT,
        "tax_amount": Decimal(tax_amount),
        "retention_amount": Decimal(retention),
        "metadata": {
            "einvoice": {
                "seller": _party(),
                "buyer": _party(name="Stadt Beispiel", vat_id=None, city="Cork"),
                "buyer_reference": "PO-77",
            }
        },
    }
    return build_einvoice(invoice=invoice, line_items=lines, profile=profile)


# --- Reading the emitted document back, as a receiver would ---------------


def _cii(inv: EInvoice) -> ET.Element:
    return ET.fromstring(build_cii_xml(inv))


def _cii_amount(root: ET.Element, term: str) -> Decimal:
    """One header total (BG-22), read as the string that was written."""
    summation = root.find(f".//{{{RAM}}}SpecifiedTradeSettlementHeaderMonetarySummation")
    assert summation is not None, "the document carries no header monetary summation"
    text = summation.findtext(f"{{{RAM}}}{term}")
    assert text is not None, f"the header summation carries no {term}"
    return Decimal(text)


def _cii_line_amounts(root: ET.Element) -> list[Decimal]:
    return [
        Decimal(el.findtext(f"{{{RAM}}}LineTotalAmount") or "")
        for el in root.iter(f"{{{RAM}}}SpecifiedTradeSettlementLineMonetarySummation")
    ]


def _ubl_line_amounts(root: ET.Element) -> list[Decimal]:
    return [Decimal(el.findtext(f"{{{CBC}}}LineExtensionAmount") or "") for el in root.iter(f"{{{CAC}}}InvoiceLine")]


def _ubl_total(root: ET.Element, term: str) -> Decimal:
    total = root.find(f".//{{{CAC}}}LegalMonetaryTotal")
    assert total is not None, "the document carries no legal monetary total"
    text = total.findtext(f"{{{CBC}}}{term}")
    assert text is not None, f"the monetary total carries no {term}"
    return Decimal(text)


def _pdf_text(inv: EInvoice) -> str:
    pdf = build_facturx_pdf(inv)
    return "\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(pdf)).pages)


# --- BR-CO-10: the line total is the sum of the lines ---------------------


@pytest.mark.parametrize("currency", CURRENCIES)
def test_cii_line_amounts_sum_to_the_line_total_we_wrote(currency: str) -> None:
    root = _cii(_document(currency))
    amounts = _cii_line_amounts(root)
    assert len(amounts) == LINE_COUNT, "the parser did not find every line"
    assert sum(amounts) == _cii_amount(root, "LineTotalAmount")


@pytest.mark.parametrize("currency", CURRENCIES)
def test_ubl_line_amounts_sum_to_the_line_total_we_wrote(currency: str) -> None:
    root = ET.fromstring(build_ubl_xml(_document(currency, profile="peppol")))
    amounts = _ubl_line_amounts(root)
    assert len(amounts) == LINE_COUNT, "the parser did not find every line"
    assert sum(amounts) == _ubl_total(root, "LineExtensionAmount")


@pytest.mark.parametrize("currency", CURRENCIES)
def test_the_pdf_page_shows_a_net_total_its_own_line_column_adds_up_to(currency: str) -> None:
    """The page a person reads has to survive the same addition.

    The PDF prints no BT-106 of its own: its net total is BT-109, which the
    writer sets from the same accumulation. So the reader's check is the line
    column against the net total, and both are rendered by ``fmt_money``.
    """
    inv = _document(currency)
    rendered_lines = [fmt_money(line.line_net_amount, currency, DEFAULT_PDF_LOCALE) for line in inv.lines]
    rendered_total = fmt_money(inv.tax_basis_total, currency, DEFAULT_PDF_LOCALE)

    text = _pdf_text(inv)
    # Bind the arithmetic to the page: the total row is drawn with the currency
    # after it, which is distinctive enough that its presence is a real check.
    assert f"{rendered_total} {currency}" in text, f"the page does not show a net total of {rendered_total}"
    for shown in set(rendered_lines):
        assert shown in text, f"the page does not show a line amount of {shown}"

    assert sum(Decimal(shown.replace(",", "")) for shown in rendered_lines) == Decimal(rendered_total.replace(",", ""))


# --- The same defect, further down the summation --------------------------


@pytest.mark.parametrize("currency", CURRENCIES)
def test_cii_grand_total_is_the_two_totals_we_wrote_above_it(currency: str) -> None:
    """BR-CO-15: BT-112 = BT-109 + BT-110, on the header-rate branch.

    No line carries a rate here, so the VAT total is the stored header figure
    and never passes through the line arithmetic. The basis still does, which
    is why this reconciles or fails for the same reason BR-CO-10 does.

    The VAT figure is not free: it has to be the one the invoice-level rate
    derives, or BR-CO-17 rejects the document before this can measure it. This
    pair is legal at two decimals and lands on the boundary at zero.
    """
    root = _cii(_document(currency, line_rate=None, tax_amount="55.30"))
    basis = _cii_amount(root, "TaxBasisTotalAmount")
    tax = _cii_amount(root, "TaxTotalAmount")
    assert basis + tax == _cii_amount(root, "GrandTotalAmount")


@pytest.mark.parametrize("currency", CURRENCIES)
@pytest.mark.parametrize("retention", ["15.20", "15.50"])
def test_cii_amount_due_is_the_grand_total_less_the_prepaid_we_wrote(currency: str, retention: str) -> None:
    """BR-CO-16: BT-115 = BT-112 - BT-113, with retention held back.

    Exactly half a unit is its own case and not a spare value. Everywhere else
    rounding the subtrahend and rounding the difference agree; at a half they
    diverge, because each is rounded away from zero independently and the two
    decisions no longer describe one subtraction. It is also the case that a
    correct line total makes reachable: while the basis still carried a
    fraction of its own, that fraction was cancelling the half by accident.
    """
    root = _cii(_document(currency, line_amount="100.20", retention=retention))
    grand = _cii_amount(root, "GrandTotalAmount")
    prepaid = _cii_amount(root, "TotalPrepaidAmount")
    assert prepaid > 0, "the fixture withheld nothing, so this proves nothing"
    assert grand - prepaid == _cii_amount(root, "DuePayableAmount")


def test_the_reader_of_a_two_decimal_currency_sees_the_cents_it_expects() -> None:
    """A control, so a test that trimmed everything to whole units cannot pass.

    If some later change quantised every currency to zero decimals, every
    assertion above would still hold - each compares a document against itself.
    This one says the EUR document is still written in cents.
    """
    root = _cii(_document("EUR"))
    summation = root.find(f".//{{{RAM}}}SpecifiedTradeSettlementHeaderMonetarySummation")
    assert summation is not None
    assert summation.findtext(f"{{{RAM}}}LineTotalAmount") == "301.20"
    assert _cii_line_amounts(root) == [Decimal("100.40")] * LINE_COUNT
