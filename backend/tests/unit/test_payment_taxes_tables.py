# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Rate rows: finding the one in force on a date, and refusing bad tables.

Every row here is synthetic. No statutory value of any country appears in this
file, so a test can never become the place a rate was "filled in".
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from app.core.payment_taxes.tables import (
    OverlappingRowsError,
    RateRow,
    categories,
    find_overlaps,
    lookup,
    rows_for,
    validate_rows,
)


def _row(**changes: object) -> RateRow:
    base = RateRow(
        country_code="XX",
        kind="vat_withholding",
        code="W1",
        labels={"tr": "Deneme işi", "en": "Test work"},
        base="vat",
        rate_pct=None,
        numerator=4,
        denominator=10,
        threshold_amount=None,
        threshold_currency="",
        threshold_scope="",
        threshold_measure="",
        cap_amount=None,
        effective_from=date(2020, 1, 1),
        effective_to=None,
        legal_reference="Synthetic Act art. 1",
        source_url="https://example.invalid/act",
        read_date="2026-01-01",
        review_status="confirmed",
    )
    return replace(base, **changes)


def _pct_row(**changes: object) -> RateRow:
    defaults: dict[str, object] = {
        "kind": "income_withholding",
        "code": "I1",
        "base": "net",
        "rate_pct": Decimal("5"),
        "numerator": None,
        "denominator": None,
    }
    defaults.update(changes)
    return _row(**defaults)


# ── lookup ───────────────────────────────────────────────────────────────────


def test_lookup_returns_the_row_in_force_on_the_date() -> None:
    old = _row(numerator=3, effective_from=date(2020, 1, 1), effective_to=date(2021, 2, 28))
    new = _row(numerator=4, effective_from=date(2021, 3, 1))
    rows = [old, new]

    assert lookup(rows, country="XX", kind="vat_withholding", code="W1", on=date(2020, 6, 1)) is old
    assert lookup(rows, country="XX", kind="vat_withholding", code="W1", on=date(2024, 6, 1)) is new


def test_lookup_bounds_are_inclusive_on_both_ends() -> None:
    row = _row(effective_from=date(2021, 3, 1), effective_to=date(2021, 3, 31))

    def find(on: date) -> RateRow | None:
        return lookup([row], country="XX", kind="vat_withholding", code="W1", on=on)

    assert find(date(2021, 2, 28)) is None
    assert find(date(2021, 3, 1)) is row
    assert find(date(2021, 3, 31)) is row
    assert find(date(2021, 4, 1)) is None


def test_lookup_returns_none_in_a_gap_and_never_the_nearest_row() -> None:
    before = _row(effective_from=date(2020, 1, 1), effective_to=date(2020, 12, 31))
    after = _row(effective_from=date(2022, 1, 1))

    assert lookup([before, after], country="XX", kind="vat_withholding", code="W1", on=date(2021, 6, 1)) is None
    assert lookup([before, after], country="XX", kind="vat_withholding", code="W1", on=date(2019, 12, 31)) is None


def test_lookup_matches_country_kind_and_code_together() -> None:
    row = _row()

    assert lookup([row], country="YY", kind="vat_withholding", code="W1", on=date(2024, 1, 1)) is None
    assert lookup([row], country="XX", kind="stamp_duty", code="W1", on=date(2024, 1, 1)) is None
    assert lookup([row], country="XX", kind="vat_withholding", code="W2", on=date(2024, 1, 1)) is None
    assert lookup([], country="XX", kind="vat_withholding", code="W1", on=date(2024, 1, 1)) is None


def test_lookup_ignores_case_and_padding_of_the_country_but_not_of_the_code() -> None:
    row = _row(code="Ab1")

    assert lookup([row], country=" xx ", kind="vat_withholding", code="Ab1", on=date(2024, 1, 1)) is row
    # A code is an identifier an authority published. "AB1" is a different one.
    assert lookup([row], country="XX", kind="vat_withholding", code="AB1", on=date(2024, 1, 1)) is None


def test_lookup_refuses_to_choose_between_two_rows_in_force_on_one_date() -> None:
    first = _row(numerator=3, effective_from=date(2020, 1, 1), effective_to=date(2021, 3, 1))
    second = _row(numerator=4, effective_from=date(2021, 3, 1))

    # The shared day is the whole overlap. Either row would be a guess.
    with pytest.raises(OverlappingRowsError):
        lookup([first, second], country="XX", kind="vat_withholding", code="W1", on=date(2021, 3, 1))
    # Outside the shared day the table still answers.
    assert lookup([first, second], country="XX", kind="vat_withholding", code="W1", on=date(2021, 3, 2)) is second


def test_overlapping_rows_error_is_a_value_error() -> None:
    assert issubclass(OverlappingRowsError, ValueError)


# ── categories ───────────────────────────────────────────────────────────────


def test_categories_lists_rows_in_force_sorted_by_code() -> None:
    rows = [
        _row(code="W3"),
        _row(code="W1"),
        _row(code="W2", effective_to=date(2022, 12, 31)),
        _row(code="W4", effective_from=date(2030, 1, 1)),
        _pct_row(),
        _row(code="W9", country_code="YY"),
    ]

    found = categories(rows, country="xx", kind="vat_withholding", on=date(2024, 1, 1))

    assert [row.code for row in found] == ["W1", "W3"]
    assert categories(rows, country="XX", kind="vat_withholding", on=date(2022, 12, 31))[1].code == "W2"
    assert categories(rows, country="XX", kind="stamp_duty", on=date(2024, 1, 1)) == []


def test_categories_refuses_a_table_with_two_rows_for_one_code_on_the_date() -> None:
    rows = [_row(numerator=3), _row(numerator=4)]

    with pytest.raises(OverlappingRowsError):
        categories(rows, country="XX", kind="vat_withholding", on=date(2024, 1, 1))


# ── rows_for ─────────────────────────────────────────────────────────────────


def test_rows_for_returns_a_tuple_and_nothing_for_a_country_without_data() -> None:
    assert rows_for("ZZ") == ()
    assert rows_for("") == ()
    assert isinstance(rows_for("TR"), tuple)
    assert rows_for(" tr ") == rows_for("TR")
    assert all(row.country_code == "TR" for row in rows_for("TR"))


# ── find_overlaps ────────────────────────────────────────────────────────────


def test_find_overlaps_reports_each_overlapping_pair_once() -> None:
    a = _row(effective_from=date(2020, 1, 1), effective_to=date(2021, 3, 1))
    b = _row(effective_from=date(2021, 3, 1), effective_to=date(2022, 1, 1))
    c = _row(effective_from=date(2022, 1, 2))

    assert find_overlaps([a, b, c]) == [(a, b)]


def test_find_overlaps_treats_an_open_ended_row_as_running_forever() -> None:
    open_row = _row(effective_from=date(2020, 1, 1))
    later = _row(effective_from=date(2025, 1, 1), effective_to=date(2025, 12, 31))

    assert find_overlaps([open_row, later]) == [(open_row, later)]


def test_find_overlaps_separates_country_kind_and_code() -> None:
    rows = [_row(), _row(code="W2"), _row(country_code="YY"), _pct_row(code="W1")]

    assert find_overlaps(rows) == []


def test_adjacent_ranges_do_not_overlap() -> None:
    a = _row(effective_from=date(2020, 1, 1), effective_to=date(2021, 2, 28))
    b = _row(effective_from=date(2021, 3, 1))

    assert find_overlaps([a, b]) == []


# ── validate_rows ────────────────────────────────────────────────────────────


def test_a_well_formed_table_has_no_problems() -> None:
    rows = [
        _row(),
        _pct_row(),
        _pct_row(
            kind="stamp_duty", code="S1", rate_pct=Decimal("0.5"), cap_amount=Decimal("100"), threshold_currency="EUR"
        ),
        _pct_row(
            code="I2",
            threshold_amount=Decimal("1000"),
            threshold_currency="EUR",
            threshold_scope="per_document",
            threshold_measure="net",
        ),
        _row(code="W2", buyer_scope="any"),
        _row(code="W3", buyer_scope="designated_only", conditions={"tr": "Koşul", "en": "Condition"}),
        _row(
            code="W4",
            buyer_scope="designated_or_work_value",
            work_value_threshold=Decimal("5000"),
            threshold_currency="EUR",
        ),
    ]

    assert validate_rows(rows) == []


def test_the_fields_added_for_buyer_conditions_default_to_no_condition() -> None:
    row = _row()

    assert (row.buyer_scope, row.work_value_threshold, dict(row.conditions)) == ("", None, {})


@pytest.mark.parametrize(
    ("row", "fragment"),
    [
        (_row(numerator=None), "fraction"),
        (_row(denominator=None), "fraction"),
        (_row(denominator=0), "fraction"),
        (_row(numerator=11), "fraction"),
        (_row(numerator=-1), "fraction"),
        (_row(rate_pct=Decimal("40")), "rate_pct"),
        (_row(base="net"), "base"),
        (_pct_row(rate_pct=None), "rate_pct"),
        (_pct_row(rate_pct=Decimal("-1")), "rate_pct"),
        (_pct_row(rate_pct=Decimal("100.01")), "rate_pct"),
        (_pct_row(numerator=1, denominator=2), "fraction"),
        (_pct_row(kind="vat"), "kind"),
        (_pct_row(base="gross"), "base"),
        (_row(code=""), "code"),
        (_row(country_code=""), "country_code"),
        (_row(labels={}), "labels"),
        (_row(labels={"en": "  "}), "labels"),
        (_row(legal_reference=" "), "legal_reference"),
        (_row(read_date="10.10.2026"), "read_date"),
        (_row(read_date=""), "read_date"),
        (_row(review_status="reviewed"), "review_status"),
        (_row(effective_from=date(2021, 1, 1), effective_to=date(2020, 12, 31)), "effective_to"),
        (_pct_row(threshold_amount=Decimal("10")), "threshold"),
        (
            _pct_row(threshold_amount=Decimal("10"), threshold_currency="EUR", threshold_scope="per_document"),
            "threshold",
        ),
        (_pct_row(threshold_scope="per_document", threshold_measure="net"), "threshold"),
        (_pct_row(threshold_currency="EUR"), "threshold_currency"),
        (
            _pct_row(
                threshold_amount=Decimal("-1"),
                threshold_currency="EUR",
                threshold_scope="per_document",
                threshold_measure="net",
            ),
            "threshold",
        ),
        (
            _pct_row(
                threshold_amount=Decimal("1"),
                threshold_currency="EUR",
                threshold_scope="yearly",
                threshold_measure="net",
            ),
            "threshold",
        ),
        (_row(buyer_scope="everyone"), "buyer_scope"),
        (_row(buyer_scope="designated_or_work_value"), "work_value_threshold"),
        (_row(buyer_scope="designated_or_work_value", work_value_threshold=Decimal("5000")), "threshold_currency"),
        (
            _row(buyer_scope="designated_or_work_value", work_value_threshold=Decimal("0"), threshold_currency="EUR"),
            "work_value_threshold",
        ),
        (
            _row(buyer_scope="designated_only", work_value_threshold=Decimal("5000"), threshold_currency="EUR"),
            "work_value_threshold",
        ),
        (_row(work_value_threshold=Decimal("5000"), threshold_currency="EUR"), "work_value_threshold"),
        (_row(conditions={"en": ""}), "conditions"),
        (_pct_row(cap_amount=Decimal("100")), "cap"),
        (_pct_row(cap_amount=Decimal("-100"), threshold_currency="EUR"), "cap"),
    ],
)
def test_a_malformed_row_is_reported(row: RateRow, fragment: str) -> None:
    problems = validate_rows([row])

    assert problems, f"expected a problem mentioning {fragment!r}"
    assert any(fragment in problem for problem in problems), problems


def test_validate_rows_reports_overlaps() -> None:
    problems = validate_rows([_row(numerator=3), _row(numerator=4)])

    assert any("overlap" in problem for problem in problems)


def test_a_problem_names_the_row_it_is_about() -> None:
    problems = validate_rows([_row(code="W7", legal_reference="")])

    assert all("XX/vat_withholding/W7" in problem for problem in problems)
