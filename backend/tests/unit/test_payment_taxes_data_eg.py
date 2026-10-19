# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Egyptian withholding on account of tax, and the data-file registry that serves it.

Egypt is the second country with payment tax rows, and the first one added
as a data file only: ``rows_for`` used to name Türkiye in code. These tests
pin both sides of that change. Türkiye still gets the very same tuple, and
Egypt gets its rows without a line of code that names it.

Every amount case is chosen so the wrong rule gives a different answer: a
payment of exactly EGP 300 separates "exceeding 300" from "300 or more", the
four payee classes differ in rate, and a small-business payee is exempt only
when the exemption is the one the row names.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from app.core.payment_taxes import (
    Choice,
    Override,
    PaymentTaxInput,
    categories,
    compute_payment_taxes,
    data_eg,
    data_tr,
    rows_for,
    validate_rows,
)
from app.core.payment_taxes.tables import RateRow, countries_with_rows

D = Decimal
ON = date(2026, 10, 19)
NA = Choice("not_applicable", reason="not used here")


def _inp(net: str, code: str = "W001", **changes: object) -> PaymentTaxInput:
    base = PaymentTaxInput(
        country_code="EG",
        currency="EGP",
        on=ON,
        net_amount=D(net),
        vat_rate_pct=D("14"),
        vat_withholding=NA,
        income_withholding=Choice("selected", code),
        stamp_duty=NA,
    )
    return replace(base, **changes)


def _withheld(net: str, code: str = "W001", **changes: object):
    return compute_payment_taxes(_inp(net, code, **changes), rows_for("EG")).income_withheld


# ── The registry is data, and Türkiye is unchanged ───────────────────────────


def test_turkey_still_gets_the_very_same_rows() -> None:
    assert rows_for("TR") is data_tr.ROWS
    assert rows_for(" tr ") is data_tr.ROWS


def test_egypt_is_served_from_its_data_file() -> None:
    assert rows_for("EG") is data_eg.ROWS
    assert rows_for("eg") is data_eg.ROWS


def test_a_country_without_a_data_file_has_no_rows() -> None:
    assert rows_for("DE") == ()
    assert rows_for("") == ()


@pytest.mark.parametrize("weird", ["../x", "E G", "EGY", "e1", "_t"])
def test_a_code_that_is_not_a_country_never_reaches_the_import_system(weird: str) -> None:
    assert rows_for(weird) == ()


def test_the_countries_with_rows_are_read_off_the_data_files() -> None:
    assert {"EG", "TR"} <= set(countries_with_rows())
    for country in countries_with_rows():
        assert rows_for(country), country


def test_a_data_file_whose_rows_are_not_rows_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(data_eg, "ROWS", [object()])
    with pytest.raises(TypeError, match="ROWS"):
        rows_for("EG")


def test_turkey_computes_exactly_as_before_the_registry_changed() -> None:
    """Same input, same five figures: the refactor moved where the rows come from, nothing else."""
    inp = PaymentTaxInput(
        country_code="TR",
        currency="TRY",
        on=date(2026, 10, 10),
        net_amount=D("100000.00"),
        vat_rate_pct=D("20"),
        vat_withholding=Choice("selected", "601"),
        income_withholding=Choice("selected", "construction_multi_year"),
        stamp_duty=NA,
        buyer_is_designated=True,
    )
    result = compute_payment_taxes(inp, rows_for("TR"))

    assert result.vat_computed.amount == D("20000.00")
    assert result.vat_withheld.amount == D("8000.00")
    assert result.vat_payable.amount == D("12000.00")
    assert result.income_withheld.amount == D("5000.00")


# ── The Egyptian table ───────────────────────────────────────────────────────


def test_the_egyptian_table_is_well_formed() -> None:
    assert validate_rows(data_eg.ROWS) == []
    assert all(row.country_code == "EG" for row in data_eg.ROWS)


def test_every_row_says_where_it_was_read_and_that_it_awaits_the_decree() -> None:
    for row in data_eg.ROWS:
        assert row.source_url.startswith("https://"), row.code
        assert "91 of 2005" in row.legal_reference
        # Read in professional summaries, not in the decision itself.
        assert row.review_status == "unconfirmed"
        assert set(row.labels) == {"en", "ar"}
        assert set(row.conditions) == {"en", "ar"}


def test_no_row_is_a_vat_rate() -> None:
    assert {row.kind for row in data_eg.ROWS} == {"income_withholding"}
    assert all(row.base == "net" for row in data_eg.ROWS)


def test_the_picker_offers_the_four_payee_classes_by_their_e_invoice_subtype() -> None:
    offered = categories(data_eg.ROWS, country="EG", kind="income_withholding", on=ON)
    assert [(row.code, row.rate_pct) for row in offered] == [
        ("W001", D("1")),
        ("W002", D("1")),
        ("W004", D("3")),
        ("W006", D("5")),
    ]


@pytest.mark.parametrize(
    ("code", "expected"),
    [("W001", "100.00"), ("W002", "100.00"), ("W004", "300.00"), ("W006", "500.00")],
)
def test_each_payee_class_is_withheld_at_its_own_rate(code: str, expected: str) -> None:
    figure = _withheld("10000.00", code)
    assert (figure.status, figure.amount) == ("value", D(expected))
    assert figure.review_status == "unconfirmed"


def test_a_payment_of_exactly_300_is_not_withheld() -> None:
    """The law says payments exceeding EGP 300. A rule of "300 or more" would withhold 3.00 here."""
    figure = _withheld("300.00")
    assert figure.status == "not_applicable"
    assert figure.reason_key == "not_above_threshold"
    assert figure.reason_params["threshold"] == "300"


def test_a_payment_one_piastre_over_300_is_withheld() -> None:
    figure = _withheld("300.01")
    assert (figure.status, figure.amount) == ("value", D("3.00"))


def test_the_threshold_is_measured_before_vat() -> None:
    """280 plus 14 percent VAT is 319.20; only the net amount is compared."""
    figure = _withheld("280.00")
    assert figure.status == "not_applicable"


def test_a_small_business_payee_is_not_withheld() -> None:
    figure = _withheld("10000.00", payee_exemptions=frozenset({data_eg.SMALL_BUSINESS_EXEMPTION}))
    assert figure.status == "not_applicable"
    assert figure.reason_key == "payee_exempt"
    assert figure.reason_params == {"exemption": data_eg.SMALL_BUSINESS_EXEMPTION}


def test_an_exemption_the_row_does_not_name_changes_nothing() -> None:
    figure = _withheld("10000.00", payee_exemptions=frozenset({"SOME_OTHER_SCHEME"}))
    assert (figure.status, figure.amount) == ("value", D("100.00"))


def _entered(amount: str) -> dict[str, Override]:
    return {"income_withheld": Override(amount=D(amount), reason="Agreed with the payee", by="user-1")}


def test_an_amount_entered_on_a_payment_of_300_says_the_threshold_was_not_reached() -> None:
    figure = _withheld("300.00", overrides=_entered("3.00"))
    assert (figure.status, figure.amount, figure.overridden) == ("value", D("3.00"), True)
    assert figure.reason_params["waived"] == "not_above_threshold"


def test_an_amount_entered_for_an_exempt_payee_says_so() -> None:
    exempt = frozenset({data_eg.SMALL_BUSINESS_EXEMPTION})
    figure = _withheld("10000.00", overrides=_entered("100.00"), payee_exemptions=exempt)
    assert figure.reason_params["waived"] == "payee_exempt"


def test_an_amount_entered_where_the_tax_arises_waives_nothing() -> None:
    figure = _withheld("300.01", overrides=_entered("3.00"))
    assert "waived" not in figure.reason_params


def test_a_payee_class_nobody_chose_is_held_not_zero() -> None:
    figure = compute_payment_taxes(_inp("10000.00", income_withholding=Choice("unset")), rows_for("EG")).income_withheld
    assert (figure.status, figure.reason_key, figure.amount) == ("held", "not_chosen", None)


def test_a_document_before_the_rows_begin_is_held() -> None:
    figure = _withheld("10000.00", on=date(2025, 2, 28))
    assert (figure.status, figure.reason_key) == ("held", "no_rate_on_date")
    assert _withheld("10000.00", on=date(2025, 3, 1)).status == "value"


def test_a_threshold_in_pounds_is_not_compared_with_a_dollar_document() -> None:
    figure = _withheld("10000.00", currency="USD")
    assert (figure.status, figure.reason_key) == ("held", "threshold_currency_mismatch")


def test_a_credit_note_reverses_the_withholding_whatever_its_size() -> None:
    assert _withheld("-100.00").amount == D("-1.00")


# ── The two new row fields are checked like the others ───────────────────────


def _base_row(**changes: object) -> RateRow:
    return replace(data_eg.ROWS[0], **changes)


def test_threshold_applies_must_be_a_known_word() -> None:
    assert any("threshold_applies" in p for p in validate_rows((_base_row(threshold_applies="over"),)))


def test_above_without_a_threshold_is_refused() -> None:
    row = _base_row(threshold_amount=None, threshold_currency="", threshold_scope="", threshold_measure="")
    assert any("only meaningful with a threshold" in p for p in validate_rows((row,)))


def test_a_blank_exemption_code_is_refused() -> None:
    assert any("payee_exemption_codes" in p for p in validate_rows((_base_row(payee_exemption_codes=(" ",)),)))


def test_payee_exemptions_must_be_a_frozenset() -> None:
    with pytest.raises(TypeError, match="payee_exemptions"):
        compute_payment_taxes(_inp("10.00", payee_exemptions={"X"}), rows_for("EG"))  # type: ignore[arg-type]
