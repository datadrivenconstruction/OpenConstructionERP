# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the pure multi-source intake normalizer.

Stdlib + pytest only - mirrors the engine's constraint so it runs on the local
Python 3.11 test runner without app.* or SQLAlchemy on the path. Money is
exercised exclusively with Decimal, and the parsers are asserted to never raise
on garbage (they collect a warning instead).
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.modules.change_intelligence.intake_normalizer import (
    BUILTIN_PROFILES,
    CANONICAL_FIELDS,
    EMAIL_FORM_PROFILE,
    FIELD_COST_IMPACT,
    FIELD_DESCRIPTION,
    FIELD_REQUESTED_BY,
    FIELD_TITLE,
    SPREADSHEET_PROFILE,
    IntakeMapping,
    NormalizationResult,
    NormalizedChangeDraft,
    normalize,
    parse_duration_days,
    parse_money,
)

# Currency symbols built from code points so this test file stays pure ASCII.
EURO = chr(0x20AC)
POUND = chr(0x00A3)
YEN = chr(0x00A5)
RUPEE = chr(0x20B9)


# ---------------------------------------------------------------------------
# parse_money - thousands separators, symbols, codes, signs
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw, expected_amount, expected_currency",
    [
        # Plain integer, no currency.
        ("1200", Decimal("1200"), None),
        # Anglo grouping with a dollar symbol.
        ("$1,200.00", Decimal("1200.00"), "USD"),
        # Anglo grouping, larger, dollar symbol with a space.
        ("$ 1,234,567.89", Decimal("1234567.89"), "USD"),
        # Euro symbol, European grouping (dot groups, comma decimal).
        (EURO + "4.500,00", Decimal("4500.00"), "EUR"),
        # Euro symbol, European grouping, millions.
        (EURO + "1.234.567,89", Decimal("1234567.89"), "EUR"),
        # Pound symbol, lone comma as a thousands group.
        (POUND + "12,000", Decimal("12000"), "GBP"),
        # ISO code trailing the figure.
        ("1,200 EUR", Decimal("1200"), "EUR"),
        # ISO code leading the figure.
        ("USD 4,500.50", Decimal("4500.50"), "USD"),
        # Lone comma as a decimal separator (European, no symbol).
        ("12,50", Decimal("12.50"), None),
        # Lone dot as a decimal separator.
        ("1200.5", Decimal("1200.5"), None),
        # Space as a thousands separator.
        ("1 200 000", Decimal("1200000"), None),
        # Negative via leading minus.
        ("-500.00", Decimal("-500.00"), None),
        # Negative via accounting parentheses, with a symbol.
        ("(" + EURO + "1,200.00)", Decimal("-1200.00"), "EUR"),
        # Yen symbol.
        (YEN + "10000", Decimal("10000"), "JPY"),
        # Rupee symbol with Indian-style grouping read as plain grouping.
        (RUPEE + "1,00,000", Decimal("100000"), "INR"),
        # ZAR (Africa pack) code.
        ("ZAR 15,000.00", Decimal("15000.00"), "ZAR"),
        # Zero.
        ("0", Decimal("0"), None),
        ("$0.00", Decimal("0.00"), "USD"),
    ],
)
def test_parse_money_table(raw: str, expected_amount: Decimal, expected_currency: str | None) -> None:
    amount, currency, warning = parse_money(raw)
    assert amount == expected_amount
    assert currency == expected_currency
    assert warning is None


def test_parse_money_indian_grouping_value() -> None:
    # 1,00,000 (one lakh) under generic grouping logic still yields 100000.
    amount, _currency, warning = parse_money("1,00,000")
    assert amount == Decimal("100000")
    assert warning is None


def test_parse_money_empty_is_not_an_error() -> None:
    for blank in ("", "   ", None):
        amount, currency, warning = parse_money(blank)  # type: ignore[arg-type]
        assert amount is None
        assert currency is None
        assert warning is None


@pytest.mark.parametrize(
    "garbage",
    [
        "n/a",
        "to be confirmed",
        "lots",
        "abc",
        "$",  # symbol alone, no figure
        "1,2,3 forty",
        "--5",
        "1-2",
    ],
)
def test_parse_money_garbage_warns_not_raises(garbage: str) -> None:
    amount, _currency, warning = parse_money(garbage)
    assert amount is None
    assert warning is not None


def test_parse_money_symbol_only_detects_currency_but_no_amount() -> None:
    # A lone symbol records the currency it implies but cannot yield an amount.
    amount, currency, warning = parse_money(POUND)
    assert amount is None
    assert currency == "GBP"
    assert warning is not None


def test_parse_money_code_takes_precedence_over_stray_symbol() -> None:
    # Explicit EUR code wins even with a stray dollar sign present.
    amount, currency, _warning = parse_money("EUR 1,000 $")
    assert amount == Decimal("1000")
    assert currency == "EUR"


def test_parse_money_accepts_numeric_types() -> None:
    assert parse_money("1200.0")[0] == Decimal("1200.0")


# ---------------------------------------------------------------------------
# parse_duration_days - unit coercion and synonyms
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw, expected_days",
    [
        ("5", Decimal("5")),
        ("5 days", Decimal("5")),
        ("5 day", Decimal("5")),
        ("5d", Decimal("5")),
        ("10 working days", Decimal("10")),
        ("3 business days", Decimal("3")),
        ("2 calendar days", Decimal("2")),
        ("1 week", Decimal("7")),
        ("3 weeks", Decimal("21")),
        ("2 wk", Decimal("14")),
        ("1 month", Decimal("30")),
        ("2 months", Decimal("60")),
        ("1,5 days", Decimal("1.5")),
        ("0 days", Decimal("0")),
        ("-3 days", Decimal("-3")),
        ("  4   weeks  ", Decimal("28")),
        ("10 WD", Decimal("10")),
    ],
)
def test_parse_duration_table(raw: str, expected_days: Decimal) -> None:
    days, warning = parse_duration_days(raw)
    assert days == expected_days
    assert warning is None


def test_parse_duration_profile_unit_synonym() -> None:
    # A profile that aliases an in-house unit word resolves through to days.
    days, warning = parse_duration_days("2 sprints", {"sprints": "weeks"})
    assert days == Decimal("14")
    assert warning is None


def test_parse_duration_empty_is_not_an_error() -> None:
    for blank in ("", "   ", None):
        days, warning = parse_duration_days(blank)  # type: ignore[arg-type]
        assert days is None
        assert warning is None


@pytest.mark.parametrize(
    "garbage",
    [
        "soon",
        "a while",
        "5 fortnights",
        "two days",
        "tbd",
    ],
)
def test_parse_duration_garbage_warns_not_raises(garbage: str) -> None:
    days, warning = parse_duration_days(garbage)
    assert days is None
    assert warning is not None


def test_parse_duration_unrecognised_unit_warns() -> None:
    days, warning = parse_duration_days("3 furlongs")
    assert days is None
    assert "unrecognised schedule unit" in warning


# ---------------------------------------------------------------------------
# normalize - alias mapping (case / whitespace tolerant)
# ---------------------------------------------------------------------------


def test_normalize_basic_spreadsheet_row() -> None:
    raw = {
        "Change Title": "Lobby cladding swap",
        "Cost Impact": "$12,500.00",
        "Schedule Impact (days)": "5",
        "Raised By": "Owner",
        "Change No": "CO-014",
    }
    result = normalize(raw, SPREADSHEET_PROFILE)
    draft = result.draft
    assert draft.title == "Lobby cladding swap"
    assert draft.cost_impact == Decimal("12500.00")
    assert draft.currency == "USD"
    assert draft.schedule_impact_days == Decimal("5")
    assert draft.requested_by == "Owner"
    assert draft.source_ref == "CO-014"
    assert result.unmapped_fields == ()
    assert result.missing_required == ()
    assert result.completeness == 1.0


def test_normalize_alias_keys_case_and_whitespace_insensitive() -> None:
    # Wildly different casing / spacing / trailing punctuation still maps.
    raw = {
        "  CHANGE   TITLE :": "Title here",
        "cost impact": "100",
        "RAISED BY*": "Jane",
    }
    result = normalize(raw, SPREADSHEET_PROFILE)
    assert result.draft.title == "Title here"
    assert result.draft.cost_impact == Decimal("100")
    assert result.draft.requested_by == "Jane"
    assert result.unmapped_fields == ()


def test_normalize_email_form_separate_currency_and_unit_schedule() -> None:
    raw = {
        "Subject": "Add fire dampers",
        "Body": "Client wants additional dampers in the riser.",
        "Cost Impact": "4500",
        "Currency": "EUR",
        "Time Impact": "2 weeks",
        "From": "Project Manager",
        "Ticket ID": "T-2231",
    }
    result = normalize(raw, EMAIL_FORM_PROFILE)
    draft = result.draft
    assert draft.title == "Add fire dampers"
    assert draft.description.startswith("Client wants")
    assert draft.cost_impact == Decimal("4500")
    assert draft.currency == "EUR"
    assert draft.schedule_impact_days == Decimal("14")
    assert draft.requested_by == "Project Manager"
    assert draft.source_ref == "T-2231"
    assert result.completeness == 1.0
    assert result.missing_required == ()


# ---------------------------------------------------------------------------
# normalize - unmapped field collection
# ---------------------------------------------------------------------------


def test_normalize_collects_unmapped_fields_sorted() -> None:
    raw = {
        "Change Title": "X",
        "Cost Impact": "10",
        "Weather": "rainy",
        "Approved By": "nobody",
        "Random Column": "junk",
    }
    result = normalize(raw, SPREADSHEET_PROFILE)
    assert result.unmapped_fields == ("Approved By", "Random Column", "Weather")
    # The mapped fields still came through.
    assert result.draft.title == "X"
    assert result.draft.cost_impact == Decimal("10")


# ---------------------------------------------------------------------------
# normalize - missing required + completeness fraction
# ---------------------------------------------------------------------------


def test_normalize_missing_required_reported_in_canonical_order() -> None:
    # Email-form requires title, description, cost_impact. Supply only title.
    raw = {"Subject": "Only a subject"}
    result = normalize(raw, EMAIL_FORM_PROFILE)
    assert result.draft.title == "Only a subject"
    assert result.missing_required == (FIELD_DESCRIPTION, FIELD_COST_IMPACT)
    assert result.completeness == round(1 / 3, 2)


def test_normalize_completeness_half() -> None:
    # Spreadsheet requires title + cost_impact. Supply title only -> 0.5.
    raw = {"Change Title": "Half complete"}
    result = normalize(raw, SPREADSHEET_PROFILE)
    assert result.completeness == 0.5
    assert result.missing_required == (FIELD_COST_IMPACT,)


def test_normalize_completeness_zero_when_nothing_required_present() -> None:
    raw = {"Notes": "just a note"}  # description is not required for spreadsheet
    result = normalize(raw, SPREADSHEET_PROFILE)
    assert result.completeness == 0.0
    assert result.missing_required == (FIELD_TITLE, FIELD_COST_IMPACT)


def test_normalize_unparseable_required_money_counts_as_missing() -> None:
    raw = {"Change Title": "T", "Cost Impact": "to be confirmed"}
    result = normalize(raw, SPREADSHEET_PROFILE)
    assert result.draft.cost_impact is None
    assert FIELD_COST_IMPACT in result.missing_required
    assert result.completeness == 0.5
    # The unparseable money produced a warning, not an exception.
    assert any("could not parse money" in w for w in result.warnings)


def test_normalize_no_required_fields_is_always_complete() -> None:
    mapping = IntakeMapping(
        profile_name="lax",
        field_aliases={"t": FIELD_TITLE},
        unit_synonyms={},
        value_synonyms={},
        required_fields=(),
    )
    result = normalize({"x": "y"}, mapping)
    assert result.completeness == 1.0
    assert result.missing_required == ()


# ---------------------------------------------------------------------------
# normalize - value synonyms
# ---------------------------------------------------------------------------


def test_normalize_applies_value_synonyms_to_text_fields() -> None:
    mapping = IntakeMapping(
        profile_name="status",
        field_aliases={"raised by": FIELD_REQUESTED_BY},
        unit_synonyms={},
        value_synonyms={"pm": "Project Manager", "qs": "Quantity Surveyor"},
        required_fields=(),
    )
    result = normalize({"Raised By": "PM"}, mapping)
    assert result.draft.requested_by == "Project Manager"


def test_normalize_value_synonym_case_insensitive_preserves_unmapped_casing() -> None:
    mapping = IntakeMapping(
        profile_name="status",
        field_aliases={"raised by": FIELD_REQUESTED_BY},
        unit_synonyms={},
        value_synonyms={"client": "Employer"},
        required_fields=(),
    )
    # Mapped value normalised regardless of input case.
    assert normalize({"Raised By": "CLIENT"}, mapping).draft.requested_by == "Employer"
    # Unmapped value keeps its original casing.
    assert normalize({"Raised By": "AcmeCorp"}, mapping).draft.requested_by == "AcmeCorp"


# ---------------------------------------------------------------------------
# normalize - currency handling edge cases
# ---------------------------------------------------------------------------


def test_normalize_explicit_currency_field_used_when_money_has_no_symbol() -> None:
    raw = {"Subject": "x", "Body": "y", "Cost Impact": "1000", "Currency": "gbp"}
    result = normalize(raw, EMAIL_FORM_PROFILE)
    assert result.draft.currency == "GBP"


def test_normalize_money_symbol_currency_wins_and_conflict_warns() -> None:
    # Money cell says USD via symbol; a separate Currency field says EUR.
    raw = {"Subject": "x", "Body": "y", "Cost Impact": "$1,000", "Currency": "EUR"}
    result = normalize(raw, EMAIL_FORM_PROFILE)
    assert result.draft.currency == "USD"  # first detected (from the money cell) wins
    assert any("conflicting currency" in w for w in result.warnings)


def test_normalize_currency_field_normalises_full_name_to_code_when_recognised() -> None:
    # A Currency field carrying a code-bearing string resolves to the code.
    raw = {"Subject": "x", "Body": "y", "Cost Impact": "1000", "Currency": "in EUR please"}
    result = normalize(raw, EMAIL_FORM_PROFILE)
    assert result.draft.currency == "EUR"


# ---------------------------------------------------------------------------
# normalize - duplicate canonical targets
# ---------------------------------------------------------------------------


def test_normalize_duplicate_canonical_keeps_first_and_warns() -> None:
    # Both "title" and "summary" map to title in the spreadsheet profile.
    raw = {"Title": "First", "Summary": "Second", "Cost Impact": "10"}
    result = normalize(raw, SPREADSHEET_PROFILE)
    assert result.draft.title == "First"
    assert any("duplicate value" in w for w in result.warnings)


def test_normalize_duplicate_money_keeps_first_and_warns() -> None:
    raw = {"Title": "t", "Cost": "$100", "Amount": "$200"}
    result = normalize(raw, SPREADSHEET_PROFILE)
    assert result.draft.cost_impact == Decimal("100")
    assert any("duplicate value" in w for w in result.warnings)


# ---------------------------------------------------------------------------
# normalize - empty / garbage input
# ---------------------------------------------------------------------------


def test_normalize_empty_dict_yields_empty_draft_all_required_missing() -> None:
    result = normalize({}, SPREADSHEET_PROFILE)
    assert result.draft == NormalizedChangeDraft()
    assert result.missing_required == (FIELD_TITLE, FIELD_COST_IMPACT)
    assert result.unmapped_fields == ()
    assert result.completeness == 0.0


@pytest.mark.parametrize("garbage", [None, [], "a string", 42, ("tuple",)])
def test_normalize_non_dict_input_degrades_gracefully(garbage: object) -> None:
    result = normalize(garbage, SPREADSHEET_PROFILE)  # type: ignore[arg-type]
    assert result.draft == NormalizedChangeDraft()
    assert result.missing_required == (FIELD_TITLE, FIELD_COST_IMPACT)
    assert result.completeness == 0.0


def test_normalize_blank_values_treated_as_absent() -> None:
    raw = {"Change Title": "   ", "Cost Impact": "", "Raised By": None}
    result = normalize(raw, SPREADSHEET_PROFILE)
    assert result.draft.title is None
    assert result.draft.cost_impact is None
    assert result.draft.requested_by is None
    assert result.missing_required == (FIELD_TITLE, FIELD_COST_IMPACT)


def test_normalize_garbage_money_and_schedule_collect_warnings_no_raise() -> None:
    raw = {
        "Change Title": "Has bad numbers",
        "Cost Impact": "lots of money",
        "Schedule Impact (days)": "ages",
    }
    result = normalize(raw, SPREADSHEET_PROFILE)
    assert result.draft.title == "Has bad numbers"
    assert result.draft.cost_impact is None
    assert result.draft.schedule_impact_days is None
    assert len(result.warnings) >= 2


# ---------------------------------------------------------------------------
# normalize - numeric (non-string) cell values
# ---------------------------------------------------------------------------


def test_normalize_numeric_cells_parse_like_strings() -> None:
    # A spreadsheet library may hand us floats / ints rather than strings.
    raw = {"Change Title": "Numeric cells", "Cost Impact": 12500.0, "Schedule Impact (days)": 5}
    result = normalize(raw, SPREADSHEET_PROFILE)
    assert result.draft.cost_impact == Decimal("12500.0")
    assert result.draft.schedule_impact_days == Decimal("5")


# ---------------------------------------------------------------------------
# built-in profiles
# ---------------------------------------------------------------------------


def test_builtin_profiles_registered() -> None:
    assert set(BUILTIN_PROFILES) == {"generic_spreadsheet", "generic_email_form"}
    assert BUILTIN_PROFILES["generic_spreadsheet"] is SPREADSHEET_PROFILE
    assert BUILTIN_PROFILES["generic_email_form"] is EMAIL_FORM_PROFILE


def test_builtin_profile_alias_targets_are_canonical() -> None:
    for profile in BUILTIN_PROFILES.values():
        for canonical in profile.field_aliases.values():
            assert canonical in CANONICAL_FIELDS
        for required in profile.required_fields:
            assert required in CANONICAL_FIELDS


def test_canonical_fields_cover_all_draft_slots() -> None:
    # Every canonical field name has a matching attribute on the draft.
    draft = NormalizedChangeDraft()
    for field_name in CANONICAL_FIELDS:
        assert hasattr(draft, field_name)


# ---------------------------------------------------------------------------
# IntakeMapping helpers
# ---------------------------------------------------------------------------


def test_intake_mapping_canonical_for_normalises_lookup() -> None:
    mapping = IntakeMapping(
        profile_name="p",
        field_aliases={"Change Title": FIELD_TITLE},
        unit_synonyms={},
        value_synonyms={},
        required_fields=(),
    )
    assert mapping.canonical_for("change  title") == FIELD_TITLE
    assert mapping.canonical_for("CHANGE TITLE:") == FIELD_TITLE
    assert mapping.canonical_for("unknown") is None


def test_intake_mapping_value_synonym_passthrough() -> None:
    mapping = IntakeMapping(
        profile_name="p",
        field_aliases={},
        unit_synonyms={},
        value_synonyms={"hi": "hello"},
        required_fields=(),
    )
    assert mapping.value_synonym("HI") == "hello"
    assert mapping.value_synonym("bye") == "bye"


def test_alias_for_unknown_canonical_target_warns_and_parks_in_extra() -> None:
    mapping = IntakeMapping(
        profile_name="buggy",
        field_aliases={"weird": "not_a_real_field"},
        unit_synonyms={},
        value_synonyms={},
        required_fields=(),
    )
    result = normalize({"weird": "value"}, mapping)
    assert result.draft.extra == {"not_a_real_field": "value"}
    assert any("unknown canonical field" in w for w in result.warnings)
    assert result.unmapped_fields == ()


# ---------------------------------------------------------------------------
# result types
# ---------------------------------------------------------------------------


def test_result_is_dataclass_with_expected_shape() -> None:
    result = normalize({"Change Title": "t", "Cost Impact": "5"}, SPREADSHEET_PROFILE)
    assert isinstance(result, NormalizationResult)
    assert isinstance(result.draft, NormalizedChangeDraft)
    assert isinstance(result.unmapped_fields, tuple)
    assert isinstance(result.missing_required, tuple)
    assert isinstance(result.warnings, tuple)
    assert isinstance(result.completeness, float)


def test_draft_money_is_decimal_not_float() -> None:
    result = normalize({"Change Title": "t", "Cost Impact": "12.50"}, SPREADSHEET_PROFILE)
    assert isinstance(result.draft.cost_impact, Decimal)


def test_normalize_is_deterministic() -> None:
    raw = {
        "Change Title": "Repeatable",
        "Cost Impact": EURO + "1.234,56",
        "Schedule Impact (days)": "3 days",
        "Weather": "sunny",
    }
    a = normalize(raw, SPREADSHEET_PROFILE)
    b = normalize(raw, SPREADSHEET_PROFILE)
    assert a == b
