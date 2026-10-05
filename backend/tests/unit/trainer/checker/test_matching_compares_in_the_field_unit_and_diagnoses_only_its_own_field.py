# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Tolerance compare, also_accepted and diagnosis matching (pure).

Each red case is one step off a green one, so a test fails for the reason it
names: a hair inside the tolerance passes, a hair outside fails; the same wrong
value is diagnosed in its own field and ignored in another.
"""

from __future__ import annotations

from decimal import Decimal

from app.modules.trainer.checker.matching import (
    Expectation,
    compare,
    is_unit_slip,
    match_diagnosis,
    scoped_diagnoses,
)
from app.modules.trainer.spec import DiagnosisSpec

MONEY = Expectation(value=Decimal("606.90"), kind="money", tolerance=Decimal("0.01"), currency="GBP")


def _diag(diag_id: str, applies_to: str, wrong: object, kind: str = "error") -> DiagnosisSpec:
    return DiagnosisSpec(id=diag_id, applies_to=applies_to, kind=kind, wrong_value=wrong, message=f"msg {diag_id}")


# ── compare ──────────────────────────────────────────────────────────────────


def test_within_tolerance_matches() -> None:
    assert compare(Decimal("606.91"), MONEY) == "match"
    assert compare(Decimal("606.89"), MONEY) == "match"


def test_just_outside_tolerance_does_not_match() -> None:
    assert compare(Decimal("606.92"), MONEY) == "mismatch"
    assert compare(Decimal("606.88"), MONEY) == "mismatch"


def test_money_is_compared_after_quantising_to_the_currency() -> None:
    # The ERP stores Numeric(18, 4); 606.9049 is the document's 606.90.
    assert compare(Decimal("606.9049"), MONEY) == "match"
    zero_tol = Expectation(value=Decimal("606.90"), kind="money", tolerance=Decimal(0), currency="GBP")
    assert compare(Decimal("606.9049"), zero_tol) == "match"
    assert compare(Decimal("606.9050"), zero_tol) == "mismatch"


def test_a_missing_or_unreadable_value_is_never_a_match() -> None:
    assert compare(None, MONEY) == "unknown"
    assert compare("not a number", MONEY) == "unknown"
    assert compare(True, MONEY) == "unknown"


def test_a_fraction_answer_is_compared_in_percent_with_its_tolerance_scaled() -> None:
    rate = Expectation(value=Decimal("0.05"), kind="percent", tolerance=Decimal("0.0001"), unit="fraction")
    # Tolerance 0.0001 as a fraction is 0.01 percentage points: 5.009 in, 5.011 out.
    assert compare(Decimal("5.011"), rate) == "mismatch"
    assert compare(Decimal("5.0"), rate) == "match"
    assert compare(Decimal("5.009"), rate) == "match"
    assert compare(Decimal("5.02"), rate) == "mismatch"
    # The ERP column is percent: a fraction typed into it is 0.05 %, not 5 %.
    assert compare(Decimal("0.05"), rate) == "mismatch"


def test_a_value_read_back_from_a_stored_spec_is_parsed_by_kind() -> None:
    stored = Expectation(value="606.90", kind="money", tolerance=Decimal("0.01"), also_accepted=("610.00",))
    assert compare("606.90", stored) == "match"
    assert compare(Decimal("610"), stored) == "match"


def test_also_accepted_uses_the_answers_tolerance() -> None:
    alt = Expectation(
        value=Decimal("11780.00"),
        kind="money",
        tolerance=Decimal("0.01"),
        also_accepted=(Decimal("11788.00"),),
        currency="GBP",
    )
    assert compare(Decimal("11788.01"), alt) == "match"
    assert compare(Decimal("11788.02"), alt) == "mismatch"


def test_text_compares_exactly_case_folded() -> None:
    name = Expectation(value="Brackenfold Roofs", kind="text")
    assert compare(" brackenfold roofs ", name) == "match"
    assert compare("Brackenfold Roof", name) == "mismatch"


def test_a_boolean_compares_as_a_boolean() -> None:
    valid = Expectation(value=True, kind="bool")
    assert compare(True, valid) == "match"
    assert compare(False, valid) == "mismatch"
    assert compare("true", valid) == "match"


# ── diagnoses ────────────────────────────────────────────────────────────────


def test_diagnoses_are_scoped_to_their_field() -> None:
    mine = _diag("mine", "retention_amount", Decimal("364.14"))
    other = _diag("other", "net_due", Decimal("364.14"))
    scoped = scoped_diagnoses([mine, other], {"retention_amount", "fx_v1_retention"})
    assert scoped == [mine]


def test_a_wrong_value_of_another_field_is_not_diagnosed() -> None:
    other = _diag("other", "net_due", Decimal("12138.00"))
    candidates = scoped_diagnoses([other], {"retention_amount"})
    assert match_diagnosis(Decimal("12138.00"), candidates, MONEY) is None


def test_an_exact_wrong_value_wins_over_one_within_tolerance() -> None:
    near = _diag("near", "f", Decimal("100.01"))
    exact = _diag("exact", "f", Decimal("100.00"))
    exp = Expectation(value=Decimal("200"), kind="money", tolerance=Decimal("0.01"), currency="GBP")
    assert match_diagnosis(Decimal("100.00"), [near, exact], exp) is exact
    assert match_diagnosis(Decimal("100.02"), [near, exact], exp) is near
    assert match_diagnosis(Decimal("100.05"), [near, exact], exp) is None


def test_a_convention_without_a_wrong_value_is_never_matched() -> None:
    convention = DiagnosisSpec(id="c", applies_to="f", kind="convention", when="always", message="m")
    assert match_diagnosis(Decimal("1"), [convention], MONEY) is None


def test_a_wrong_value_in_a_fraction_field_is_converted_like_the_answer() -> None:
    rate = Expectation(value=Decimal("0.05"), kind="percent", tolerance=Decimal("0.0001"), unit="fraction")
    compounded = _diag("compounded", "profit_rate", Decimal("0.03"))
    assert match_diagnosis(Decimal("3"), [compounded], rate) is compounded


def test_a_fraction_typed_for_a_percent_field_is_a_unit_slip() -> None:
    rate = Expectation(value=Decimal("5"), kind="percent", tolerance=Decimal("0.01"), unit="percent")
    assert is_unit_slip(Decimal("0.05"), rate)
    assert not is_unit_slip(Decimal("0.04"), rate)
    assert not is_unit_slip(Decimal("0"), rate)
    assert not is_unit_slip(Decimal("0.05"), MONEY)


def test_a_text_diagnosis_matches_case_folded() -> None:
    name = Expectation(value="Brackenfold Roofs", kind="text")
    raw_lowest = _diag("raw", "rb2", "Alderby Roofing")
    assert match_diagnosis("alderby roofing", [raw_lowest], name) is raw_lowest
    assert match_diagnosis("Corrow and Sons", [raw_lowest], name) is None
