# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Pure-logic unit tests for the invoice-approval DMS.

These tests touch no database, no HTTP client, no OCR engine and no LLM. They
pin the deterministic behaviour the whole feature relies on:

* heuristic field extraction from an invoice's text layer (the no-AI fallback);
* the booking proposal maps a payable to real chart accounts;
* balanced double-entry lines (net + tax = gross);
* first-class validation (amount tie-out, booking completeness, approver,
  duplicate detection);
* the tamper-evident archive seal is stable and change-sensitive.

Money is asserted as exact Decimal (never float).
"""

from __future__ import annotations

from decimal import Decimal

from app.modules.finance import invoice_capture_logic as logic

# ── Extraction ────────────────────────────────────────────────────────────────


def test_extract_fields_from_realistic_invoice_text() -> None:
    text = (
        "ACME Formwork GmbH\n"
        "Musterstrasse 5, 10115 Berlin\n"
        "VAT: DE123456789\n"
        "Invoice No: INV-2026-0042\n"
        "Date: 2026-03-14\n"
        "Net 1000.00\n"
        "VAT 19% 190.00\n"
        "Total 1190.00\n"
    )
    fields, conf = logic.extract_fields_from_text(text)
    assert fields["invoice_number"] == "INV-2026-0042"
    assert fields["supplier_tax_id"] == "DE123456789"
    assert fields["invoice_date"] == "2026-03-14"
    assert fields["amount_net"] == "1000.00"
    assert fields["amount_tax"] == "190.00"
    assert fields["amount_gross"] == "1190.00"
    # Every populated field carries a confidence in (0, 1].
    assert all(0.0 < c <= 1.0 for c in conf.values())


def test_extract_derives_missing_third_amount() -> None:
    # Only net + gross present -> tax is derived.
    text = "Subtotal 500.00\nAmount due 595.00\n"
    fields, _ = logic.extract_fields_from_text(text)
    assert fields["amount_net"] == "500.00"
    assert fields["amount_gross"] == "595.00"
    assert fields["amount_tax"] == "95.00"


def test_extract_handles_european_decimal_comma() -> None:
    text = "Netto 1.234,56\nMwSt 234,56\nGesamt 1.469,12\n"
    fields, _ = logic.extract_fields_from_text(text)
    assert fields["amount_net"] == "1234.56"
    assert fields["amount_gross"] == "1469.12"


def test_extract_empty_text_returns_nothing() -> None:
    fields, conf = logic.extract_fields_from_text("")
    assert fields == {}
    assert conf == {}


# ── Booking proposal ──────────────────────────────────────────────────────────


def _default_chart() -> list[logic.ChartAccount]:
    return [
        logic.ChartAccount("2000", "Accounts Payable", "liability"),
        logic.ChartAccount("2300", "Taxes Payable", "liability"),
        logic.ChartAccount("5000", "Cost of Construction (COGS)", "expense"),
        logic.ChartAccount("5020", "Direct Materials", "expense"),
        logic.ChartAccount("5030", "Subcontractor Costs", "expense"),
    ]


def test_propose_booking_generic_expense_and_payable() -> None:
    p = logic.propose_booking(accounts=_default_chart(), supplier_name="Generic Co", has_tax=True)
    assert p.expense_account == "5000"
    assert p.payable_account == "2000"
    assert p.tax_account == "2300"
    assert p.confidence > 0.5


def test_propose_booking_matches_subcontractor() -> None:
    p = logic.propose_booking(accounts=_default_chart(), supplier_name="Bravo Subcontractor Ltd", has_tax=False)
    assert p.expense_account == "5030"
    # No tax on the invoice -> no tax account proposed.
    assert p.tax_account is None


def test_propose_booking_matches_materials() -> None:
    p = logic.propose_booking(
        accounts=_default_chart(), supplier_name="Steel Supply", description_text="material delivery"
    )
    assert p.expense_account == "5020"


def test_propose_booking_empty_chart_is_safe() -> None:
    p = logic.propose_booking(accounts=[], supplier_name="X", has_tax=True)
    assert p.expense_account is None
    assert p.payable_account is None
    assert p.confidence == 0.0
    assert p.rationale  # explains that the chart must be seeded


# ── Journal lines ─────────────────────────────────────────────────────────────


def test_build_journal_lines_balances_with_tax() -> None:
    lines = logic.build_journal_lines(
        net=Decimal("1000.00"),
        tax=Decimal("190.00"),
        expense_account="5000",
        payable_account="2000",
        tax_account="2300",
        description="Supplier invoice INV-1",
    )
    assert len(lines) == 3
    debit = sum(logic.to_decimal(ln["debit"]) for ln in lines)
    credit = sum(logic.to_decimal(ln["credit"]) for ln in lines)
    assert debit == credit == Decimal("1190.00")
    # Payable is the sole credit and equals gross.
    payable = [ln for ln in lines if ln["account_code"] == "2000"][0]
    assert payable["credit"] == "1190.00"


def test_build_journal_lines_folds_tax_when_no_tax_account() -> None:
    # Tax present but no tax account -> tax folds into the expense so the entry
    # still balances (2 legs), matching the validation warning.
    lines = logic.build_journal_lines(
        net=Decimal("1000.00"),
        tax=Decimal("190.00"),
        expense_account="5000",
        payable_account="2000",
        tax_account=None,
        description="d",
    )
    assert len(lines) == 2
    debit = sum(logic.to_decimal(ln["debit"]) for ln in lines)
    credit = sum(logic.to_decimal(ln["credit"]) for ln in lines)
    assert debit == credit == Decimal("1190.00")
    expense = [ln for ln in lines if ln["account_code"] == "5000"][0]
    assert expense["debit"] == "1190.00"


def test_build_journal_lines_no_tax_two_legs() -> None:
    lines = logic.build_journal_lines(
        net=Decimal("500.00"),
        tax=Decimal("0"),
        expense_account="5000",
        payable_account="2000",
        tax_account=None,
        description="d",
    )
    assert len(lines) == 2
    debit = sum(logic.to_decimal(ln["debit"]) for ln in lines)
    credit = sum(logic.to_decimal(ln["credit"]) for ln in lines)
    assert debit == credit == Decimal("500.00")


# ── Validation ────────────────────────────────────────────────────────────────


def test_validate_amounts_tie_out_within_tolerance() -> None:
    # 1000 + 190.01 vs 1190.00 -> within 2c tolerance, passes.
    findings = logic.validate_amounts(Decimal("1000"), Decimal("190.01"), Decimal("1190.00"))
    assert not logic.has_errors(findings)


def test_validate_amounts_mismatch_is_error() -> None:
    findings = logic.validate_amounts(Decimal("1000"), Decimal("190"), Decimal("1500.00"))
    codes = {f.code for f in findings if f.is_error}
    assert "amount_mismatch" in codes


def test_validate_gross_must_be_positive() -> None:
    findings = logic.validate_amounts(Decimal("0"), Decimal("0"), Decimal("0"))
    assert "gross_required" in {f.code for f in findings}


def test_validate_capture_requires_booking_when_coding() -> None:
    findings = logic.validate_capture(
        status="captured",
        net=Decimal("100"),
        tax=Decimal("0"),
        gross=Decimal("100"),
        expense_account=None,
        payable_account=None,
        tax_account=None,
        invoice_number="INV-9",
        supplier_name="ACME",
        has_approver=False,
        require_booking=True,
    )
    codes = {f.code for f in findings if f.is_error}
    assert "no_expense_account" in codes
    assert "no_payable_account" in codes


def test_validate_capture_requires_approver_before_post() -> None:
    findings = logic.validate_capture(
        status="approved",
        net=Decimal("100"),
        tax=Decimal("0"),
        gross=Decimal("100"),
        expense_account="5000",
        payable_account="2000",
        tax_account=None,
        invoice_number="INV-9",
        supplier_name="ACME",
        has_approver=False,
        require_approval=True,
    )
    assert "no_approver" in {f.code for f in findings if f.is_error}


def test_validate_capture_clean_invoice_passes() -> None:
    findings = logic.validate_capture(
        status="approved",
        net=Decimal("1000"),
        tax=Decimal("190"),
        gross=Decimal("1190"),
        expense_account="5000",
        payable_account="2000",
        tax_account="2300",
        invoice_number="INV-9",
        supplier_name="ACME",
        has_approver=True,
        require_booking=True,
        require_approval=True,
    )
    assert not logic.has_errors(findings)


# ── Duplicate detection ───────────────────────────────────────────────────────


def test_find_duplicate_same_supplier_and_number() -> None:
    candidates = [{"id": "a", "supplier_name": "ACME GmbH", "invoice_number": "INV-1"}]
    dup = logic.find_duplicate(supplier_name="acme gmbh", invoice_number="inv-1", candidates=candidates)
    assert dup is not None and dup["id"] == "a"


def test_find_duplicate_blank_number_never_matches() -> None:
    candidates = [{"id": "a", "supplier_name": "ACME", "invoice_number": ""}]
    assert logic.find_duplicate(supplier_name="ACME", invoice_number="", candidates=candidates) is None


def test_find_duplicate_different_supplier_not_matched() -> None:
    candidates = [{"id": "a", "supplier_name": "ACME", "invoice_number": "INV-1"}]
    assert logic.find_duplicate(supplier_name="OTHER", invoice_number="INV-1", candidates=candidates) is None


# ── Archive seal ──────────────────────────────────────────────────────────────


def _seal(**overrides) -> str:
    base = dict(
        content_hash="abc123",
        supplier_name="ACME",
        invoice_number="INV-1",
        invoice_date="2026-03-14",
        currency_code="EUR",
        net=Decimal("1000"),
        tax=Decimal("190"),
        gross=Decimal("1190"),
        expense_account="5000",
        tax_account="2300",
        payable_account="2000",
        cost_code=None,
        transaction_ref="AP-CAP-1",
    )
    base.update(overrides)
    return logic.compute_archive_hash(**base)


def test_content_sha256_matches_hashlib() -> None:
    import hashlib

    data = b"an original invoice PDF's bytes"
    assert logic.content_sha256(data) == hashlib.sha256(data).hexdigest()


def test_archive_hash_is_deterministic() -> None:
    assert _seal() == _seal()
    assert len(_seal()) == 64


def test_archive_hash_changes_when_amount_changes() -> None:
    # Altering the booked gross after sealing must break the seal.
    assert _seal() != _seal(gross=Decimal("1191"))


def test_archive_hash_changes_when_account_changes() -> None:
    assert _seal() != _seal(expense_account="5030")


def test_archive_hash_changes_when_document_hash_changes() -> None:
    assert _seal() != _seal(content_hash="tampered")
