# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Per-line VAT and the payment account, from the finance dicts outward.

The mapper is where a mixed-rate invoice is either represented or flattened,
so these drive it through the same dict shape the finance router builds.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.modules.einvoice import build_einvoice, problems_for, render_einvoice, violations_for
from app.modules.einvoice.cii import EInvoiceError
from app.modules.einvoice.rules import FATAL, WARNING, check, violation_ids


def _invoice(**over: object) -> dict:
    base: dict[str, object] = {
        "invoice_number": "RE-2026-77",
        "invoice_date": "2026-08-11",
        "currency_code": "EUR",
        "amount_subtotal": Decimal("1500.00"),
        "tax_amount": Decimal("225.00"),
        "metadata": {
            "einvoice": {
                # City and post code on both sides because these render under
                # the German profile, and XRechnung makes them mandatory
                # (BR-DE-3/4 on the seller, BR-DE-8/9 on the buyer).
                "seller": {
                    "name": "Hochbau Nord GmbH",
                    "vat_id": "DE123456789",
                    "country_code": "DE",
                    "postcode": "24103",
                    "city": "Kiel",
                    # BG-6, mandatory on the seller under XRechnung (BR-DE-2).
                    "contact_name": "Anke Reimann",
                    "contact_phone": "+49 431 1234560",
                    "contact_email": "rechnung@hochbau-nord.example",
                },
                "buyer": {
                    "name": "Stadtwerke Kiel",
                    "country_code": "DE",
                    "postcode": "24143",
                    "city": "Kiel",
                },
                "buyer_reference": "991-01234-56",
            }
        },
    }
    base.update(over)
    return base


def _mixed_lines() -> list[dict]:
    """Standard-rated works at 19% plus a reduced-rate line at 7%."""
    return [
        {
            "description": "Concrete works",
            "unit": "m3",
            "quantity": Decimal("10"),
            "unit_rate": Decimal("100"),
            "amount": Decimal("1000.00"),
            "vat_rate": Decimal("19"),
            "vat_category": "S",
        },
        {
            "description": "Reduced rate supply",
            "unit": "pcs",
            "quantity": Decimal("5"),
            "unit_rate": Decimal("100"),
            "amount": Decimal("500.00"),
            "vat_rate": Decimal("7"),
            "vat_category": "S",
        },
    ]


def _single_lines() -> list[dict]:
    """Lines carrying no VAT of their own, as every pre-existing invoice does."""
    return [
        {
            "description": "Works",
            "unit": "m2",
            "quantity": Decimal("10"),
            "unit_rate": Decimal("150"),
            "amount": Decimal("1500.00"),
        }
    ]


# ── per-line VAT reaches the document ─────────────────────────────────────────


def test_each_line_keeps_its_own_rate():
    ei = build_einvoice(invoice=_invoice(), line_items=_mixed_lines(), profile="xrechnung")
    assert [(ln.vat_rate, ln.vat_category) for ln in ei.lines] == [
        (Decimal("19"), "S"),
        (Decimal("7"), "S"),
    ]


def test_the_breakdown_gets_one_group_per_rate():
    ei = build_einvoice(invoice=_invoice(), line_items=_mixed_lines(), profile="xrechnung")
    assert [(g.rate, g.basis, g.tax_amount) for g in ei.tax_subtotals] == [
        (Decimal("19"), Decimal("1000.00"), Decimal("190.00")),
        (Decimal("7"), Decimal("500.00"), Decimal("35.00")),
    ]


def test_a_mixed_rate_invoice_reconciles_and_passes_the_rules():
    ei = build_einvoice(invoice=_invoice(), line_items=_mixed_lines(), profile="xrechnung")
    assert ei.tax_total == Decimal("225.00")
    assert ei.grand_total == Decimal("1725.00")
    assert [v for v in check(ei) if v.severity == FATAL] == []


def test_the_mixed_rates_are_written_into_the_xml():
    _, _, xml = render_einvoice(invoice=_invoice(), line_items=_mixed_lines(), profile="xrechnung")
    text = xml.decode("utf-8")
    assert "<ram:RateApplicablePercent>19.00</ram:RateApplicablePercent>" in text
    assert "<ram:RateApplicablePercent>7.00</ram:RateApplicablePercent>" in text


def test_mixed_rates_survive_the_ubl_syntax_too():
    _, _, xml = render_einvoice(invoice=_invoice(), line_items=_mixed_lines(), profile="peppol")
    text = xml.decode("utf-8")
    assert "<cbc:Percent>19.00</cbc:Percent>" in text
    assert "<cbc:Percent>7.00</cbc:Percent>" in text


def test_a_reverse_charged_line_sits_beside_a_taxed_one():
    """The construction case: a subcontract under reverse charge, works at 19%.

    The reverse-charged group must say why no VAT is charged (BR-AE-10), so
    the invoice declares the reason; it lands on the AE group only, and the
    standard-rated group stays clean as BR-S-10 demands.
    """
    lines = [
        {
            "description": "Own works",
            "unit": "m2",
            "quantity": Decimal("1"),
            "unit_rate": Decimal("1000"),
            "amount": Decimal("1000.00"),
            "vat_rate": Decimal("19"),
            "vat_category": "S",
        },
        {
            "description": "Subcontracted works, reverse charge",
            "unit": "m2",
            "quantity": Decimal("1"),
            "unit_rate": Decimal("500"),
            "amount": Decimal("500.00"),
            "vat_rate": Decimal("0"),
            "vat_category": "AE",
        },
    ]
    inv = _invoice()
    inv["metadata"]["einvoice"]["vat_exemption_reason"] = "Reverse charge"
    ei = build_einvoice(invoice=inv, line_items=lines, profile="xrechnung")
    assert {(g.category, g.rate) for g in ei.tax_subtotals} == {("AE", Decimal("0")), ("S", Decimal("19"))}
    assert ei.tax_total == Decimal("190.00")
    reasons = {g.category: g.exemption_reason for g in ei.tax_subtotals}
    assert reasons == {"AE": "Reverse charge", "S": None}
    assert [v for v in check(ei) if v.severity == FATAL] == []


# ── the fallback keeps old invoices identical ─────────────────────────────────


def test_lines_without_vat_fall_back_to_the_invoice_rate():
    ei = build_einvoice(invoice=_invoice(), line_items=_single_lines(), profile="xrechnung")
    assert len(ei.tax_subtotals) == 1
    assert ei.lines[0].vat_rate == Decimal("15.00")  # 225 / 1500


def test_the_stored_header_vat_still_wins_when_no_line_names_a_rate():
    """A single-rate invoice must render the figure the user approved."""
    ei = build_einvoice(invoice=_invoice(), line_items=_single_lines(), profile="xrechnung")
    assert ei.tax_total == Decimal("225.00")
    assert ei.grand_total == Decimal("1725.00")


def test_a_line_without_a_rate_borrows_the_document_rate_beside_one_that_has_it():
    lines = _mixed_lines()
    del lines[1]["vat_rate"]
    del lines[1]["vat_category"]
    ei = build_einvoice(invoice=_invoice(), line_items=lines, profile="xrechnung")
    assert ei.lines[1].vat_rate == Decimal("15.00")


# ── the payment account ───────────────────────────────────────────────────────


def test_an_iban_in_the_settings_reaches_both_syntaxes():
    inv = _invoice()
    inv["metadata"]["einvoice"]["payee_iban"] = "DE02120300000000202051"
    inv["metadata"]["einvoice"]["payee_bic"] = "BYLADEM1001"
    for profile, needle in (("xrechnung", "ram:IBANID"), ("peppol", "cac:PayeeFinancialAccount")):
        _, _, xml = render_einvoice(invoice=inv, line_items=_mixed_lines(), profile=profile)
        text = xml.decode("utf-8")
        assert needle in text, profile
        assert "DE02120300000000202051" in text, profile


def test_an_iban_promotes_the_payment_means_to_a_credit_transfer():
    inv = _invoice()
    inv["metadata"]["einvoice"]["payee_iban"] = "DE02120300000000202051"
    ei = build_einvoice(invoice=inv, line_items=_mixed_lines(), profile="xrechnung")
    assert ei.payment_means_code == "30"
    assert "BR-61" not in violation_ids(check(ei))


def test_without_an_iban_no_credit_transfer_is_claimed():
    ei = build_einvoice(invoice=_invoice(), line_items=_mixed_lines(), profile="xrechnung")
    assert ei.payment_means_code == "1"
    assert "BR-61" not in violation_ids(check(ei))


def test_a_missing_account_advises_without_blocking_the_export():
    """The advisory is raised, and it is not among the problems that block."""
    ei = build_einvoice(invoice=_invoice(), line_items=_mixed_lines(), profile="xrechnung")
    advisories = [v for v in check(ei) if v.severity != FATAL]
    assert "OCE-PAY-01" in {v.rule_id for v in advisories}
    assert problems_for(invoice=_invoice(), line_items=_mixed_lines(), profile="xrechnung") == []


# ── what a screen is given to show ────────────────────────────────────────────


def _dry_run(**over: object) -> list:
    kwargs: dict = {"invoice": _invoice(), "line_items": _mixed_lines(), "profile": "xrechnung"}
    kwargs.update(over)
    return violations_for(**kwargs)


def test_the_dry_run_keeps_the_rule_id_a_receiver_would_quote():
    """Prose alone cannot be searched for; the identifier can."""
    found = _dry_run()
    assert found, "the sample invoice raises at least the missing-account advisory"
    assert all(v.rule_id for v in found)
    assert {v.severity for v in found} <= {FATAL, WARNING}


def test_an_advisory_is_visible_to_a_screen_but_absent_from_the_blockers():
    """The distinction the endpoint exists to make.

    A screen that cannot tell these apart shows a red list for an invoice
    that exports perfectly well, and the user stops believing the panel.
    """
    found = _dry_run()
    advisory_ids = {v.rule_id for v in found if v.severity != FATAL}
    fatal_messages = [v.message for v in found if v.severity == FATAL]

    assert "OCE-PAY-01" in advisory_ids
    assert fatal_messages == []
    assert problems_for(invoice=_invoice(), line_items=_mixed_lines(), profile="xrechnung") == []


def test_problems_for_is_exactly_the_fatal_messages_of_violations_for():
    """One evaluation, two readings of it, so they cannot drift apart."""
    inv = _invoice()
    del inv["metadata"]["einvoice"]["buyer_reference"]  # BR-DE-15 for XRechnung

    found = violations_for(invoice=inv, line_items=_mixed_lines(), profile="xrechnung")
    problems = problems_for(invoice=inv, line_items=_mixed_lines(), profile="xrechnung")

    assert problems == [v.message for v in found if v.severity == FATAL]
    assert problems, "a missing buyer reference blocks an XRechnung"


def test_a_blocked_invoice_still_reports_its_advisories():
    """A fatal problem must not swallow the advice sitting beside it."""
    inv = _invoice()
    del inv["metadata"]["einvoice"]["buyer_reference"]

    found = violations_for(invoice=inv, line_items=_mixed_lines(), profile="xrechnung")
    assert any(v.severity == FATAL for v in found)
    assert any(v.severity == WARNING for v in found)


# ── the tax accounting currency ───────────────────────────────────────────────


def test_a_vat_accounting_currency_without_its_total_is_refused():
    inv = _invoice()
    inv["metadata"]["einvoice"]["tax_currency"] = "USD"
    with pytest.raises(EInvoiceError, match="USD"):
        render_einvoice(invoice=inv, line_items=_mixed_lines(), profile="xrechnung")


def test_both_vat_totals_are_written_each_with_its_own_currency():
    inv = _invoice()
    inv["metadata"]["einvoice"]["tax_currency"] = "USD"
    inv["metadata"]["einvoice"]["tax_total_in_tax_currency"] = "243.00"
    _, _, xml = render_einvoice(invoice=inv, line_items=_mixed_lines(), profile="xrechnung")
    text = xml.decode("utf-8")
    assert '<ram:TaxTotalAmount currencyID="EUR">225.00</ram:TaxTotalAmount>' in text
    assert '<ram:TaxTotalAmount currencyID="USD">243.00</ram:TaxTotalAmount>' in text
