# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""Quote-extraction rules (pure, no DB).

Each test encodes a way a real quote was once read wrong in production;
the rule it proves exists because of that failure. If one of these goes
red, a wrong figure can reach the quote gate - treat as a money bug, not
a nit.
"""

from __future__ import annotations

from app.modules.comms_intelligence.heuristics import (
    analyze_text,
    reply_kind,
    scan_lead_time,
    scan_package_price,
    scan_quote_number,
)

# ── Percentages are never money ──────────────────────────────────────────


def test_percentage_never_reads_as_money() -> None:
    # '10% GST included, total $36,468.60' once returned $10 and switched
    # the quote gate OFF on a $36,000 package.
    got = scan_package_price("10% GST included in the total $36,468.60 for supply")
    assert got is not None
    assert got["amount"] == "36468.60"


# ── The Australian totals block ──────────────────────────────────────────


def test_totals_block_takes_ex_gst_when_reconciling() -> None:
    got = scan_package_price("Total Ex 36,468.60  GST 3,646.86  Total 40,115.46")
    assert got is not None
    assert got["amount"] == "36468.60"
    assert got["basis"] == "ex gst"
    assert "36,468.60" in got["evidence"]


def test_totals_block_that_does_not_reconcile_is_not_trusted() -> None:
    # ex + gst != inc → the block is ignored; the loose labelled figure wins
    # with the basis read from BESIDE it, never document-wide.
    got = scan_package_price("Total Ex 30,000.00  GST 999.00  Total 40,115.46 inc GST")
    assert got is not None
    assert got["amount"] == "40115.46"
    assert got["basis"] == "inc gst"


def test_biggest_reconciling_block_beats_page_one_subtotal() -> None:
    # A page-1 'Sub Total' block reconciles on its own; taking the FIRST
    # match once badged half the quote as the proven price.
    text = "Sub Total 18,234.30 GST 1,823.43 Total 20,057.73 ... Total Ex 36,468.60 GST 3,646.86 Total 40,115.46"
    got = scan_package_price(text)
    assert got is not None
    assert got["amount"] == "36468.60"


# ── Unit rates, k-suffix, labelled totals ───────────────────────────────


def test_unit_rate_is_not_the_package_price() -> None:
    got = scan_package_price("Labour charged at $85.00/hr. Supply total $4,120.00 ex GST.")
    assert got is not None
    assert got["amount"] == "4120.00"
    assert got["basis"] == "ex gst"


def test_k_suffix_is_thousands() -> None:
    got = scan_package_price("budget circa $4.12k for the lot")
    assert got is not None
    assert got["amount"] == "4120.00"


def test_labelled_pdf_style_total_with_no_dollar_sign() -> None:
    # What real PDF text extraction gives back.
    got = scan_package_price("Total (ex GST)    4,120.00")
    assert got is not None
    assert got["amount"] == "4120.00"
    assert got["basis"] == "ex gst"


def test_gst_basis_is_the_nearest_marker() -> None:
    # Boilerplate 'plus GST' further away must not stamp the wrong basis.
    got = scan_package_price("All prices plus GST unless noted. ... Grand amount due 9,900.00 inc GST")
    assert got is not None
    assert got["basis"] == "inc gst"


# ── Quote numbers ────────────────────────────────────────────────────────


def test_labelled_quote_no_beats_passing_mention() -> None:
    # 'Further to quote 274119, please find Quote No: 100042' once returned
    # the SUPERSEDED number - which then went on the PO.
    t = "Further to quote 274119, please find Quote No: 100042 attached."
    assert scan_quote_number(t) == "100042"


def test_two_unlabelled_quote_numbers_say_nothing() -> None:
    assert scan_quote_number("see quote 274119 and quote 100042") is None


def test_quote_number_equal_to_price_digits_is_discarded() -> None:
    assert scan_quote_number("ref 36468 for this", price_amount="36468.60") is None


# ── Reply kind: the counting rule behind "2 of 3 quoted" ────────────────


def test_price_beats_question() -> None:
    # "here's our price, can you confirm delivery?" is a QUOTE.
    assert reply_kind("Our price is $4,120.00 ex GST. Can you confirm delivery dates?") == "quote"


def test_question_without_price_is_a_query() -> None:
    assert reply_kind("Can you confirm which switchboard drawing revision applies?") == "query"


def test_signature_logo_is_not_a_quote_document() -> None:
    # Counting image001.png as a document once let a supplier's question
    # satisfy the compare gate on a package with no prices at all.
    assert reply_kind("Do you have the latest spec?", ["image001.png"]) == "query"
    assert reply_kind("See attached.", ["image001.png"]) == "other"


def test_real_document_makes_it_a_quote() -> None:
    assert reply_kind("Please find our offer attached.", ["MCF-quote-100042.pdf"]) == "quote"


# ── Lead time ────────────────────────────────────────────────────────────


def test_lead_time_range_and_ex_stock() -> None:
    assert scan_lead_time("Lead time 6-8 weeks from order") == "6-8 weeks"
    assert scan_lead_time("These are ex stock, same day dispatch") == "ex stock"


# ── End-to-end verdict wiring ────────────────────────────────────────────


def test_verdict_carries_package_price_and_kind() -> None:
    v = analyze_text(
        "Quotation MSB-01",
        "Quote No: 100042. Total Ex 36,468.60 GST 3,646.86 Total 40,115.46. Lead time 6-8 weeks.",
    )
    facts = v["extracted"]
    assert facts["package_price"]["amount"] == "36468.60"
    assert facts["package_price"]["basis"] == "ex gst"
    assert facts["lead_time"] == "6-8 weeks"
    assert facts["reply_kind"] == "quote"
    assert facts["quote_number"] == "100042"
    assert v["category"] == "quote"


def test_priced_reply_without_keyword_still_reads_as_quote() -> None:
    # The price test is the stronger signal - same precedence as the
    # reply classifier itself.
    v = analyze_text("RE: fasteners", "Supply the lot for $4,120.00 ex GST, 3 weeks delivery.")
    assert v["category"] == "quote"
    assert v["extracted"]["reply_kind"] == "quote"
