"""Unit tests for the UBL-TR validation rules.

Every rule id has a passing case (the clean scenarios raise nothing at all,
warnings included) and at least one failing case built by breaking exactly
one thing in a clean scenario. A closing test reads the rule ids out of the
rule module itself and fails when one of them has no failing case here.
"""

from __future__ import annotations

import datetime as dt
import inspect
import re
from collections.abc import Callable
from dataclasses import replace
from decimal import Decimal

import pytest

from app.modules.einvoice import rules_tr
from app.modules.einvoice.rules import FATAL, WARNING
from app.modules.einvoice.rules_tr import (
    EXEMPTION_REASON_CODES,
    ISTISNA_REASON_CODES,
    KNOWN_INVOICE_TYPES,
    KNOWN_PROFILES,
    SUPPORTED_INVOICE_TYPES,
    SUPPORTED_PROFILES,
    WITHHOLDING_CODE_PERCENT_PAIRS,
    WITHHOLDING_CODES,
    check_tr,
    today_in_turkiye,
)
from app.modules.einvoice.ubl_tr import (
    TrAllowanceCharge,
    TrDocumentRef,
    TrInvoice,
    TrPaymentMeans,
)
from tests.unit.test_einvoice_ubl_tr import (
    SCENARIOS,
    TODAY,
    WH_CODE,
    eur_invoice,
    fig,
    held,
    iade_invoice,
    istisna_invoice,
    not_applicable,
    satis_invoice,
    taxes,
    tevkifat_invoice,
    two_rate_invoice,
)

Mutation = Callable[[], TrInvoice]


def ids(inv: TrInvoice, severity: str | None = None) -> list[str]:
    return [v.rule_id for v in check_tr(inv, today=TODAY) if severity is None or v.severity == severity]


# ── small editing helpers ────────────────────────────────────────────────────


def with_line(inv: TrInvoice, index: int = 0, **changes: object) -> TrInvoice:
    lines = list(inv.lines)
    lines[index] = replace(lines[index], **changes)
    return replace(inv, lines=tuple(lines))


def with_group(inv: TrInvoice, index: int = 0, **changes: object) -> TrInvoice:
    groups = list(inv.tax_groups)
    groups[index] = replace(groups[index], **changes)
    return replace(inv, tax_groups=tuple(groups))


def with_taxes(inv: TrInvoice, index: int = 0, **figures: object) -> TrInvoice:
    return with_group(inv, index, taxes=replace(inv.tax_groups[index].taxes, **figures))


def with_totals(inv: TrInvoice, **changes: object) -> TrInvoice:
    return replace(inv, totals=replace(inv.totals, **changes))


def with_supplier(inv: TrInvoice, **changes: object) -> TrInvoice:
    return replace(inv, supplier=replace(inv.supplier, **changes))


def with_customer(inv: TrInvoice, **changes: object) -> TrInvoice:
    return replace(inv, customer=replace(inv.customer, **changes))


def with_supplier_address(inv: TrInvoice, **changes: object) -> TrInvoice:
    return with_supplier(inv, address=replace(inv.supplier.address, **changes))


# ── passing cases ────────────────────────────────────────────────────────────


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_clean_scenarios_raise_nothing_at_all(name: str) -> None:
    assert [str(v) for v in check_tr(SCENARIOS[name](), today=TODAY)] == []


# ── failing cases: one broken thing each ─────────────────────────────────────

S = satis_invoice
T = tevkifat_invoice
WH_FIG = T().tax_groups[0].taxes.vat_withheld

FAILING: dict[str, tuple[str, str, Mutation]] = {
    # name: (rule id, severity, mutation)
    "profile unknown": ("TR-PROFILE-01", FATAL, lambda: replace(S(), profile_id="STANDART")),
    "profile lower case": ("TR-PROFILE-01", FATAL, lambda: replace(S(), profile_id="temelfatura")),
    "profile not supported": ("TR-PROFILE-01", FATAL, lambda: replace(S(), profile_id="KAMU")),
    "profile export": ("TR-PROFILE-01", FATAL, lambda: replace(S(), profile_id="IHRACAT")),
    "return in commercial scenario": (
        "TR-PROFILE-02",
        FATAL,
        lambda: replace(iade_invoice(), profile_id="TICARIFATURA"),
    ),
    "type unknown": ("TR-TYPE-01", FATAL, lambda: replace(S(), invoice_type="CREDIT")),
    "type not supported": ("TR-TYPE-01", FATAL, lambda: replace(S(), invoice_type="OZELMATRAH")),
    "type withholding return": ("TR-TYPE-01", FATAL, lambda: replace(T(), invoice_type="TEVKIFATIADE")),
    "istisna without exemption": (
        "TR-TYPE-02",
        FATAL,
        lambda: replace(S(), invoice_type="ISTISNA"),
    ),
    "customisation": ("TR-HDR-01", FATAL, lambda: replace(S(), customization_id="TR1.0")),
    "document id free text": ("TR-ID-01", FATAL, lambda: replace(S(), document_id="INV-2026-0042")),
    "document id lower case": ("TR-ID-01", FATAL, lambda: replace(S(), document_id="omt2026000000001")),
    "document id left to integrator": ("TR-ID-01", WARNING, lambda: replace(S(), document_id="")),
    "uuid": ("TR-ID-02", FATAL, lambda: replace(S(), uuid="6f1c2d3e4a5b4c6d8e7f001122334455")),
    "uuid empty": ("TR-ID-02", FATAL, lambda: replace(S(), uuid="")),
    "issue date tomorrow": ("TR-DATE-01", FATAL, lambda: replace(S(), issue_date=TODAY + dt.timedelta(days=1))),
    "issue date before 2005": ("TR-DATE-01", FATAL, lambda: replace(S(), issue_date=dt.date(2004, 12, 31))),
    "foreign currency without rate": ("TR-CUR-01", FATAL, lambda: replace(eur_invoice(), exchange_rate=None)),
    "rate zero": ("TR-CUR-01", FATAL, lambda: replace(eur_invoice(), exchange_rate=Decimal("0"))),
    "rate seven decimals": ("TR-CUR-01", FATAL, lambda: replace(eur_invoice(), exchange_rate=Decimal("48.1234567"))),
    "currency unknown": ("TR-CUR-02", FATAL, lambda: replace(S(), currency="TL")),
    "currency three decimals": (
        "TR-CUR-02",
        FATAL,
        lambda: replace(S(), currency="KWD", exchange_rate=Decimal("150")),
    ),
    "negative total": ("TR-AMT-01", FATAL, lambda: with_totals(S(), payable=Decimal("-51000.00"))),
    "negative line": ("TR-AMT-01", FATAL, lambda: with_line(S(), line_amount=Decimal("-30000.00"))),
    "amount too large": ("TR-AMT-01", FATAL, lambda: with_totals(S(), payable=Decimal(10) ** 15)),
    "tax number nine digits": ("TR-PARTY-01", FATAL, lambda: with_supplier(S(), tax_number="111222333")),
    "tax number with prefix": ("TR-PARTY-01", FATAL, lambda: with_customer(S(), tax_number="TR9876543217")),
    "tax number empty": ("TR-PARTY-01", FATAL, lambda: with_customer(S(), tax_number="")),
    "vkn check digit": ("TR-PARTY-02", FATAL, lambda: with_supplier(S(), tax_number="1112223338")),
    "tckn check digit": (
        "TR-PARTY-02",
        FATAL,
        lambda: with_customer(SCENARIOS["person"](), tax_number="10000000147"),
    ),
    "vkn without name": ("TR-PARTY-03", FATAL, lambda: with_customer(S(), name="  ")),
    "tckn without family name": (
        "TR-PARTY-03",
        FATAL,
        lambda: with_customer(SCENARIOS["person"](), family_name=""),
    ),
    "address without district": ("TR-PARTY-04", FATAL, lambda: with_supplier_address(S(), district="")),
    "address without country": ("TR-PARTY-04", FATAL, lambda: with_supplier_address(S(), country_name="")),
    "country code unknown": ("TR-PARTY-04", FATAL, lambda: with_supplier_address(S(), country_code="TUR")),
    "tax office missing": ("TR-PARTY-05", WARNING, lambda: with_supplier(S(), tax_office="")),
    "extra id scheme": ("TR-PARTY-06", FATAL, lambda: with_supplier(S(), extra_ids=(("VATNO", "1"),))),
    "extra id empty": ("TR-PARTY-06", FATAL, lambda: with_supplier(S(), extra_ids=(("MERSISNO", " "),))),
    "reference without number": (
        "TR-REF-01",
        FATAL,
        lambda: replace(S(), contract_references=(TrDocumentRef(id="", issue_date=dt.date(2026, 1, 1)),)),
    ),
    "return without original": ("TR-REF-02", FATAL, lambda: replace(iade_invoice(), billing_references=())),
    "return with free text original": (
        "TR-REF-02",
        FATAL,
        lambda: replace(
            iade_invoice(),
            billing_references=(
                TrDocumentRef(id="INV-42", issue_date=dt.date(2026, 9, 30), document_type_code="IADE"),
            ),
        ),
    ),
    "return without type code": (
        "TR-REF-02",
        FATAL,
        lambda: replace(
            iade_invoice(),
            billing_references=(TrDocumentRef(id="OMT2026000000001", issue_date=dt.date(2026, 9, 30)),),
        ),
    ),
    "no lines": ("TR-LINE-01", FATAL, lambda: replace(S(), lines=())),
    "line without name": ("TR-LINE-01", FATAL, lambda: with_line(S(), name="")),
    "line id twice": ("TR-LINE-01", FATAL, lambda: with_line(S(), 1, line_id="1")),
    "line zero quantity": ("TR-LINE-01", FATAL, lambda: with_line(S(), quantity=Decimal("0"))),
    "line in no group": ("TR-LINE-01", FATAL, lambda: with_line(S(), tax_group="kdv18")),
    "unit unknown": ("TR-UNIT-01", FATAL, lambda: with_line(S(), unit="furlong")),
    "unit empty": ("TR-UNIT-01", FATAL, lambda: with_line(S(), unit="")),
    "payment means code": (
        "TR-PAY-01",
        FATAL,
        lambda: replace(S(), payment_means=(TrPaymentMeans(code="BANK"),)),
    ),
    "payment channel code": (
        "TR-PAY-01",
        FATAL,
        lambda: replace(S(), payment_means=(TrPaymentMeans(code="42", channel_code="WIRE"),)),
    ),
    "withholding not chosen": (
        "TR-HELD-01",
        FATAL,
        lambda: with_taxes(T(), vat_withheld=held("vat_withheld"), vat_payable=held("vat_payable")),
    ),
    "vat rate unknown": (
        "TR-HELD-01",
        FATAL,
        lambda: with_taxes(
            S(),
            vat_computed=held("vat_computed", "vat_rate_unknown"),
            vat_payable=held("vat_payable", "vat_rate_unknown"),
        ),
    ),
    "stamp duty undecided": ("TR-HELD-01", FATAL, lambda: with_taxes(S(), stamp_duty=held("stamp_duty"))),
    "unconfirmed rate": (
        "OCE-TR-01",
        WARNING,
        lambda: with_taxes(T(), vat_withheld=replace(WH_FIG, review_status="unconfirmed", legal_reference="test row")),
    ),
    "no vat block": ("TR-TAX-01", FATAL, lambda: replace(S(), tax_groups=())),
    "vat not applicable": ("TR-TAX-01", FATAL, lambda: with_taxes(S(), vat_computed=not_applicable("vat_computed"))),
    "group rate label": ("TR-TAX-01", FATAL, lambda: with_group(S(), vat_rate_pct=Decimal("10"))),
    "group base differs from figure": (
        "TR-TAX-01",
        FATAL,
        lambda: with_group(S(), taxable_amount=Decimal("42000.00")),
    ),
    "withholding on a plain sale": ("TR-WH-01", FATAL, lambda: replace(T(), invoice_type="SATIS")),
    "tevkifat without withholding": ("TR-WH-02", FATAL, lambda: replace(S(), invoice_type="TEVKIFAT")),
    "withholding code unknown": (
        "TR-WH-03",
        FATAL,
        lambda: with_taxes(with_group(T(), withholding_code="999"), vat_withheld=replace(WH_FIG, code="999")),
    ),
    "withholding percent not allowed for code": (
        "TR-WH-03",
        FATAL,
        lambda: with_taxes(T(), vat_withheld=replace(WH_FIG, numerator=5, denominator=10)),
    ),
    "withholding percent not a whole number": (
        "TR-WH-03",
        FATAL,
        lambda: with_taxes(T(), vat_withheld=replace(WH_FIG, numerator=1, denominator=3)),
    ),
    "withholding without a fraction": (
        "TR-WH-03",
        FATAL,
        lambda: with_taxes(T(), vat_withheld=replace(WH_FIG, numerator=None, denominator=None)),
    ),
    "withholding label differs from figure": ("TR-WH-04", FATAL, lambda: with_group(T(), withholding_code="602")),
    "withholding on another base": (
        "TR-WH-04",
        FATAL,
        lambda: with_taxes(T(), vat_withheld=replace(WH_FIG, base=Decimal("100000.00"))),
    ),
    "code without withheld amount": ("TR-WH-04", FATAL, lambda: with_group(S(), withholding_code=WH_CODE)),
    "zero vat without reason": ("TR-EXM-01", FATAL, lambda: with_group(istisna_invoice(), exemption_reason="")),
    "reason code unknown": ("TR-EXM-02", FATAL, lambda: with_group(istisna_invoice(), exemption_reason_code="999")),
    "reason code of another scenario": (
        "TR-EXM-02",
        FATAL,
        lambda: with_group(istisna_invoice(), exemption_reason_code="308"),
    ),
    "reason without code": ("TR-EXM-02", FATAL, lambda: with_group(istisna_invoice(), exemption_reason_code="")),
    "istisna code on a sale": ("TR-EXM-03", FATAL, lambda: replace(istisna_invoice(), invoice_type="SATIS")),
    "code of unsupported type": (
        "TR-EXM-03",
        FATAL,
        lambda: with_group(istisna_invoice(), exemption_reason_code="801"),
    ),
    "555 with zero vat": (
        "TR-EXM-04",
        FATAL,
        lambda: with_group(replace(istisna_invoice(), invoice_type="SATIS"), exemption_reason_code="555"),
    ),
    "line total": ("TR-SUM-01", FATAL, lambda: with_totals(S(), line_extension=Decimal("42000.00"))),
    "allowance total not stated": ("TR-SUM-01", FATAL, lambda: with_totals(two_rate_invoice(), allowance_total=None)),
    "groups do not cover the taxable total": (
        "TR-SUM-04",
        FATAL,
        lambda: replace(two_rate_invoice(), tax_groups=two_rate_invoice().tax_groups[:1]),
    ),
    "total with tax net of withholding": (
        "TR-SUM-02",
        FATAL,
        lambda: with_totals(T(), tax_inclusive=Decimal("112000.00")),
    ),
    "payable ignores withholding": ("TR-SUM-03", FATAL, lambda: with_totals(T(), payable=Decimal("120000.00"))),
    "payable off by a kuruş": ("TR-SUM-03", FATAL, lambda: with_totals(S(), payable=Decimal("51000.01"))),
    "group does not close": (
        "TR-SUM-05",
        FATAL,
        lambda: with_taxes(T(), vat_payable=fig("vat_payable", Decimal("12000.01"))),
    ),
    "lines do not carry the group vat": ("TR-SUM-06", FATAL, lambda: with_line(T(), vat_amount=Decimal("12000.01"))),
    "line withheld shares do not add up": (
        "TR-SUM-06",
        FATAL,
        lambda: with_line(T(), vat_withheld=Decimal("4800.01"), vat_payable=Decimal("7199.99")),
    ),
    "only some lines state vat": (
        "TR-SUM-06",
        FATAL,
        lambda: with_line(S(), 1, vat_amount=None, vat_payable=None),
    ),
}


@pytest.mark.parametrize("name", sorted(FAILING))
def test_failing_case_reports_its_rule(name: str) -> None:
    rule_id, severity, mutate = FAILING[name]
    found = [v for v in check_tr(mutate(), today=TODAY) if v.rule_id == rule_id]
    assert found, f"{name}: expected {rule_id}, got {ids(mutate())}"
    assert {v.severity for v in found} == {severity}
    for violation in found:
        # A message a person can act on, the field it concerns, and no stray
        # Python reprs of objects.
        assert len(violation.message) > 30
        assert violation.term
        assert "<" not in violation.message
        assert all(isinstance(value, str) for value in violation.params.values())


def test_every_rule_id_has_a_failing_case() -> None:
    declared = set(re.findall(r'"((?:TR|OCE-TR)-[A-Z]*-?\d+)"', inspect.getsource(rules_tr)))
    exercised = {rule_id for rule_id, _, _ in FAILING.values()}
    assert declared == exercised
    # The ids the binding design names are all present.
    designed = {
        "TR-ID-01", "TR-ID-02", "TR-PARTY-01", "TR-PARTY-02", "TR-PARTY-03", "TR-PARTY-04", "TR-PARTY-05",
        "TR-PROFILE-01", "TR-TYPE-01", "TR-WH-01", "TR-WH-02", "TR-WH-03", "TR-WH-04", "TR-SUM-01",
        "TR-SUM-02", "TR-SUM-03", "TR-CUR-01", "TR-DATE-01", "TR-HELD-01", "OCE-TR-01",
    }  # fmt: skip
    assert designed <= declared


# ── cases that need more than "the rule fired" ───────────────────────────────


@pytest.mark.parametrize(
    "name",
    [
        "profile not supported",
        "type not supported",
        "document id free text",
        "uuid",
        "issue date tomorrow",
        "foreign currency without rate",
        "tax number nine digits",
        "vkn check digit",
        "vkn without name",
        "address without district",
        "unit unknown",
        "withholding on a plain sale",
        "tevkifat without withholding",
        "withholding percent not allowed for code",
        "total with tax net of withholding",
        "payable ignores withholding",
        "group does not close",
    ],
)
def test_single_defect_reports_exactly_one_fatal_rule(name: str) -> None:
    """One mistake, one finding: the report must not bury the cause under its consequences."""
    rule_id, _, mutate = FAILING[name]
    assert ids(mutate(), FATAL) == [rule_id]


def test_not_supported_is_said_differently_from_not_valid() -> None:
    unknown = [v for v in check_tr(replace(S(), profile_id="STANDART"), today=TODAY) if v.rule_id == "TR-PROFILE-01"]
    unsupported = [v for v in check_tr(replace(S(), profile_id="KAMU"), today=TODAY) if v.rule_id == "TR-PROFILE-01"]
    assert "not supported yet" in unsupported[0].message
    assert "not supported yet" not in unknown[0].message
    for profile in sorted(KNOWN_PROFILES - SUPPORTED_PROFILES):
        assert "TR-PROFILE-01" in ids(replace(S(), profile_id=profile), FATAL)
    for invoice_type in sorted(KNOWN_INVOICE_TYPES - SUPPORTED_INVOICE_TYPES):
        assert "TR-TYPE-01" in ids(replace(S(), invoice_type=invoice_type), FATAL)


def test_messages_carry_the_values_for_translation() -> None:
    violation = next(v for v in check_tr(with_totals(T(), payable=Decimal("120000.00")), today=TODAY))
    assert violation.rule_id == "TR-SUM-03"
    assert violation.term == "LegalMonetaryTotal/PayableAmount"
    assert violation.params == {"stated": "120000.00", "expected": "112000.00"}
    assert "120000.00 TRY" in violation.message
    assert "112000.00 TRY" in violation.message
    assert str(violation).startswith("TR-SUM-03: ")


def test_held_figure_names_the_figure_and_the_reason() -> None:
    inv = with_taxes(T(), vat_withheld=held("vat_withheld"), vat_payable=held("vat_payable"))
    found = [v for v in check_tr(inv, today=TODAY) if v.rule_id == "TR-HELD-01"]
    assert [(v.params["figure"], v.params["reason"]) for v in found] == [
        ("vat_withheld", "not_chosen"),
        ("vat_payable", "not_chosen"),
    ]
    # A held figure is the whole story: no sum rule piles on with a number it cannot know.
    assert ids(inv, FATAL) == ["TR-HELD-01", "TR-HELD-01"]


def test_issue_date_today_is_accepted_and_the_default_clock_is_turkiye() -> None:
    assert ids(replace(S(), issue_date=TODAY)) == []
    assert ids(replace(S(), issue_date=dt.date(2005, 1, 1))) == []
    now = today_in_turkiye()
    assert abs((now - dt.datetime.now(dt.UTC).date()).days) <= 1
    # Without an injected day the rule still runs, against the real calendar.
    assert "TR-DATE-01" in [v.rule_id for v in check_tr(replace(S(), issue_date=now + dt.timedelta(days=2)))]


def test_withholding_is_allowed_on_a_return() -> None:
    inv = replace(
        T(),
        profile_id="TEMELFATURA",
        invoice_type="IADE",
        billing_references=(
            TrDocumentRef(id="OMT2026000000002", issue_date=dt.date(2026, 9, 30), document_type_code="IADE"),
        ),
    )
    assert ids(inv) == []


def test_exemption_obligations_by_invoice_type() -> None:
    # A return is excused from stating why its VAT is zero, as in the Schematron.
    zero_return = with_group(
        replace(
            iade_invoice(),
            tax_groups=(
                replace(
                    istisna_invoice().tax_groups[0],
                    key="kdv20",
                    taxable_amount=Decimal("12500.00"),
                    taxes=taxes("12500.00", "0"),
                    exemption_reason="",
                    exemption_reason_code="",
                ),
            ),
        ),
    )
    zero_return = with_totals(zero_return, tax_inclusive=Decimal("12500.00"), payable=Decimal("12500.00"))
    assert ids(zero_return) == []
    # A zero rated plain sale may use a code that is not reserved for ISTISNA.
    plain = with_group(replace(istisna_invoice(), invoice_type="SATIS"), exemption_reason_code="351")
    assert ids(plain) == []
    # 555 is fine on a sale that does charge VAT.
    assert (
        ids(with_group(S(), exemption_reason_code="555", exemption_reason="KDV oran kontrolüne tabi olmayan satış"))
        == []
    )
    # ... and never on an ISTISNA invoice.
    assert "TR-EXM-04" in ids(with_group(istisna_invoice(), exemption_reason_code="555"), FATAL)


def test_document_level_allowance_and_charge_enter_the_taxable_total() -> None:
    base = S()
    inv = replace(
        base,
        allowance_charges=(
            TrAllowanceCharge(amount=Decimal("2500.00"), reason="İskonto"),
            TrAllowanceCharge(amount=Decimal("500.00"), is_charge=True, reason="Nakliye"),
        ),
        tax_groups=(replace(base.tax_groups[0], taxable_amount=Decimal("40500.00"), taxes=taxes("40500.00", "20")),),
        lines=tuple(replace(line, vat_amount=None, vat_payable=None) for line in base.lines),
        totals=replace(
            base.totals,
            tax_exclusive=Decimal("40500.00"),
            tax_inclusive=Decimal("48600.00"),
            payable=Decimal("48600.00"),
            allowance_total=Decimal("2500.00"),
            charge_total=Decimal("500.00"),
        ),
    )
    assert ids(inv) == []
    assert ids(with_totals(inv, charge_total=None), FATAL) == ["TR-SUM-01"]


def test_payable_rounding_is_part_of_the_payable_identity() -> None:
    inv = with_totals(S(), payable=Decimal("51000.05"), payable_rounding=Decimal("0.05"))
    assert ids(inv) == []


# ── the code lists are what the rules say they are ───────────────────────────


def test_code_lists_are_internally_consistent() -> None:
    """Shape checks on the copied GİB lists; their content was diffed against the source file."""
    assert len(WITHHOLDING_CODES) == 52
    assert len(WITHHOLDING_CODE_PERCENT_PAIRS) == 64
    assert len(EXEMPTION_REASON_CODES) == 111
    assert len(ISTISNA_REASON_CODES) == 94
    assert SUPPORTED_PROFILES < KNOWN_PROFILES
    assert SUPPORTED_INVOICE_TYPES < KNOWN_INVOICE_TYPES
    # The pair used throughout the tests is in the list, and its neighbour is not.
    assert f"{WH_CODE}40" in WITHHOLDING_CODE_PERCENT_PAIRS
    assert f"{WH_CODE}50" not in WITHHOLDING_CODE_PERCENT_PAIRS
    # Every full withholding code (8xx) goes with 100 percent and nothing else.
    for code in (c for c in WITHHOLDING_CODES if c.startswith("8")):
        assert f"{code}100" in WITHHOLDING_CODE_PERCENT_PAIRS
