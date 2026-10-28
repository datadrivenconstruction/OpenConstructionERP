# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the pure change-request clarifier engine (runs on py3.11)."""

from __future__ import annotations

import pytest

from app.modules.change_intelligence.clarifier import (
    CLIENT_REQUEST,
    DESIGN_CHANGE,
    ERROR_OMISSION,
    ROUTE_COMMERCIAL_APPROVAL,
    ROUTE_STANDARD_CHANGE_REVIEW,
    ROUTE_TECHNICAL_THEN_COMMERCIAL,
    SCOPE_CHANGE,
    SEVERITY_RECOMMENDED,
    SEVERITY_REQUIRED,
    SITE_CONDITION,
    ClarificationGap,
    ClarifiedRequest,
    ClauseSuggestion,
    analyze_change_note,
)

# A deliberately complete note: it states a cost, a duration, a clause, and a
# responsible party, and is comfortably longer than the short-note threshold.
COMPLETE_NOTE = (
    "Client requested an upgrade to the lobby cladding to natural stone. "
    "The estimated cost impact is EUR 45,000 and it adds 10 days to the "
    "programme. Governed by clause 13.3. Responsible party is the contractor."
)


def _gap_fields(req: ClarifiedRequest) -> set[str]:
    return {g.field for g in req.missing}


def _gap_by_field(req: ClarifiedRequest, field: str) -> ClarificationGap:
    return next(g for g in req.missing if g.field == field)


# --- classification --------------------------------------------------------


@pytest.mark.parametrize(
    ("note", "expected"),
    [
        ("There is an error in the structural drawings that needs fixing here.", ERROR_OMISSION),
        ("A detail was omitted from the tender package for the roof parapet.", ERROR_OMISSION),
        ("Excavation revealed unforeseen ground conditions with rock at depth.", SITE_CONDITION),
        ("We hit contaminated soil and a buried obstruction near grid line C.", SITE_CONDITION),
        ("The engineer issued a design change with revised drawings for level 2.", DESIGN_CHANGE),
        ("Client wants the lobby finished in marble instead of the tendered tile.", CLIENT_REQUEST),
        ("The employer request is to add a green roof to the east wing.", CLIENT_REQUEST),
        ("This is additional work beyond the agreed scope for extra drainage.", SCOPE_CHANGE),
    ],
)
def test_classification_detection(note: str, expected: str) -> None:
    assert analyze_change_note(note).detected_classification == expected


def test_classification_defaults_to_scope_change() -> None:
    note = "Please review the attached note about the works near the entrance."
    assert analyze_change_note(note).detected_classification == SCOPE_CHANGE


def test_classification_precedence_error_over_design() -> None:
    # Mentions both a design change and an error; error/omission is checked
    # first and should win.
    note = "The design change introduced an error and a clash in the drawings."
    assert analyze_change_note(note).detected_classification == ERROR_OMISSION


# --- gaps ------------------------------------------------------------------


def test_missing_cost_schedule_clause_party_gaps() -> None:
    # A bare scope note with none of the key pieces present. It is also long
    # enough to avoid the short-note description gap.
    note = (
        "Additional work is required to relocate the partition walls on the "
        "third floor following the layout rework discussed at the meeting."
    )
    req = analyze_change_note(note)

    assert _gap_fields(req) == {
        "cost_impact",
        "schedule_impact",
        "contract_clause",
        "responsible_party",
    }
    assert _gap_by_field(req, "cost_impact").severity == SEVERITY_REQUIRED
    assert _gap_by_field(req, "responsible_party").severity == SEVERITY_REQUIRED
    assert _gap_by_field(req, "schedule_impact").severity == SEVERITY_RECOMMENDED
    assert _gap_by_field(req, "contract_clause").severity == SEVERITY_RECOMMENDED


def test_short_note_adds_description_gap() -> None:
    req = analyze_change_note("Move the door.")
    assert "description" in _gap_fields(req)
    assert _gap_by_field(req, "description").severity == SEVERITY_RECOMMENDED


def test_long_note_has_no_description_gap() -> None:
    note = (
        "Additional work is required to relocate the partition walls on the "
        "third floor following the layout rework discussed at the meeting."
    )
    assert "description" not in _gap_fields(analyze_change_note(note))


def test_complete_note_has_few_gaps_and_full_completeness() -> None:
    req = analyze_change_note(COMPLETE_NOTE, contract_standard="FIDIC")
    # All four key pieces detected -> no key-piece gaps, and the note is long.
    assert req.missing == []
    assert req.completeness == 1.0


def test_cost_detected_by_symbol_and_figure() -> None:
    # Symbol attached to a number, no cost vocabulary word.
    assert "cost_impact" not in _gap_fields(
        analyze_change_note("Relocate the partition walls on level three for an extra $12,500 of builder work.")
    )
    # Bare grouped figure with a magnitude word.
    assert "cost_impact" not in _gap_fields(
        analyze_change_note("Relocate the partition walls on level three; rough order is 15k for the builder.")
    )


def test_schedule_detected_by_eot_and_programme() -> None:
    assert "schedule_impact" not in _gap_fields(
        analyze_change_note("The contractor seeks an EOT for the additional drainage works at the south boundary.")
    )
    assert "schedule_impact" not in _gap_fields(
        analyze_change_note("This affects the programme for the additional drainage works at the south boundary.")
    )


def test_clause_detected_by_reference_forms() -> None:
    for note in (
        "Additional drainage works to the south boundary under clause 13.3 of the contract.",
        "Additional drainage works to the south boundary under cl. 60.1 as notified.",
        "Additional drainage works to the south boundary, see FIDIC 13.3 for the procedure.",
        "Additional drainage works to the south boundary per section 5 of the agreement.",
    ):
        assert "contract_clause" not in _gap_fields(analyze_change_note(note))


def test_responsible_party_detected_by_role_and_assignment() -> None:
    assert "responsible_party" not in _gap_fields(
        analyze_change_note("Relocate the partition walls on level three; the contractor will carry this out.")
    )
    assert "responsible_party" not in _gap_fields(
        analyze_change_note("Relocate the partition walls on level three. Responsible: the design team lead.")
    )


# --- clause suggestions ----------------------------------------------------


def test_clause_suggestions_fidic_without_schedule() -> None:
    # No schedule signal -> only the base variation clause.
    req = analyze_change_note("Client wants a stone lobby for an extra cost.", contract_standard="FIDIC")
    assert req.clause_suggestions == [
        ClauseSuggestion("FIDIC", "13.3", "Variation procedure - Engineer instruction and quotation")
    ]


def test_clause_suggestions_fidic_with_schedule_adds_time_bar() -> None:
    req = analyze_change_note(
        "Client wants a stone lobby for an extra cost; it adds 10 days delay.",
        contract_standard="fidic",  # case-insensitive
    )
    assert req.clause_suggestions == [
        ClauseSuggestion("FIDIC", "13.3", "Variation procedure - Engineer instruction and quotation"),
        ClauseSuggestion("FIDIC", "20.1", "Notice of claim time-bar"),
    ]


def test_clause_suggestions_nec4_with_and_without_schedule() -> None:
    base = ClauseSuggestion("NEC4", "60.1", "Compensation event")
    time_bar = ClauseSuggestion("NEC4", "61.3", "Notification time-bar")

    no_time = analyze_change_note("Client wants a stone lobby for an extra cost.", contract_standard="NEC4")
    assert no_time.clause_suggestions == [base]

    with_time = analyze_change_note(
        "Client wants a stone lobby; it delays completion by weeks.", contract_standard="NEC4"
    )
    assert with_time.clause_suggestions == [base, time_bar]


def test_clause_suggestions_jct_with_and_without_schedule() -> None:
    base = ClauseSuggestion("JCT", "5.1", "Variation definition")
    delay = ClauseSuggestion("JCT", "2.27", "Notice of delay")

    no_time = analyze_change_note("Client wants a stone lobby for an extra cost.", contract_standard="JCT")
    assert no_time.clause_suggestions == [base]

    with_time = analyze_change_note(
        "Client wants a stone lobby; programme slips by two weeks.", contract_standard="JCT"
    )
    assert with_time.clause_suggestions == [base, delay]


def test_clause_suggestions_unknown_standard_is_generic_single() -> None:
    for std in ("", "made-up-form", "iso9001"):
        req = analyze_change_note("Client wants a stone lobby; it adds 10 days delay.", contract_standard=std)
        assert len(req.clause_suggestions) == 1
        only = req.clause_suggestions[0]
        assert only.standard == ""
        assert only.clause_ref == ""
        assert "govern" in only.rationale.lower()


def test_time_bar_clause_absent_without_schedule_signal_for_known_standard() -> None:
    # Re-assert the schedule gate explicitly: known standard, no time words.
    req = analyze_change_note("Client wants a stone lobby for an extra cost.", contract_standard="FIDIC")
    refs = {c.clause_ref for c in req.clause_suggestions}
    assert refs == {"13.3"}


# --- suggested route -------------------------------------------------------


def test_route_error_omission_goes_technical_first() -> None:
    # Even with a cost present, an error/omission routes through technical
    # review first.
    note = "There is an error in the rebar drawings; rectification cost is EUR 8,000."
    assert analyze_change_note(note).suggested_route == ROUTE_TECHNICAL_THEN_COMMERCIAL


def test_route_no_cost_goes_technical_first() -> None:
    # A client request with no cost figure or cost vocabulary at all.
    note = "Client wants the lobby cladding swapped to natural stone instead of the tendered tile."
    req = analyze_change_note(note)
    assert req.detected_classification == CLIENT_REQUEST
    assert "cost_impact" in _gap_fields(req)
    assert req.suggested_route == ROUTE_TECHNICAL_THEN_COMMERCIAL


def test_route_with_cost_goes_commercial_approval() -> None:
    note = "Client wants the lobby cladding swapped to stone for an extra EUR 45,000 of work."
    req = analyze_change_note(note)
    assert req.detected_classification != ERROR_OMISSION
    assert req.suggested_route == ROUTE_COMMERCIAL_APPROVAL


def test_standard_change_review_token_is_vendor_neutral_snake_case() -> None:
    # The token exists and is snake_case even if the simple rules rarely emit
    # it; guard the contract.
    assert ROUTE_STANDARD_CHANGE_REVIEW == "standard_change_review"
    assert ROUTE_STANDARD_CHANGE_REVIEW.islower()
    assert " " not in ROUTE_STANDARD_CHANGE_REVIEW


# --- title and summary -----------------------------------------------------


def test_title_first_non_empty_line() -> None:
    note = "\n\n  Swap lobby cladding to stone  \nMore detail on the next line about cost.\n"
    assert analyze_change_note(note).title == "Swap lobby cladding to stone"


def test_title_truncated_to_about_80_chars() -> None:
    long_line = "X" * 200
    title = analyze_change_note(long_line).title
    assert len(title) <= 80
    assert title == "X" * 80


def test_title_empty_note_fallback() -> None:
    assert analyze_change_note("").title == "Untitled change"
    assert analyze_change_note("    \n\t  \n").title == "Untitled change"


def test_normalized_summary_collapses_whitespace() -> None:
    note = "  Swap   cladding\n\n  to    stone\t now  "
    assert analyze_change_note(note).normalized_summary == "Swap cladding to stone now"


# --- completeness arithmetic ----------------------------------------------


@pytest.mark.parametrize(
    ("note", "expected"),
    [
        # None of the four key pieces present -> 0.0.
        ("Relocate the partition walls on the third floor following the rework.", 0.0),
        # Cost only -> 1/4 = 0.25.
        ("Relocate the partition walls on the third floor for an extra EUR 5,000.", 0.25),
        # Cost + schedule -> 2/4 = 0.5.
        (
            "Relocate the partition walls for an extra EUR 5,000; it adds 10 days to the programme.",
            0.5,
        ),
        # Cost + schedule + clause -> 3/4 = 0.75.
        (
            "Relocate the partition walls for an extra EUR 5,000; adds 10 days delay under clause 13.3.",
            0.75,
        ),
    ],
)
def test_completeness_arithmetic(note: str, expected: float) -> None:
    assert analyze_change_note(note).completeness == expected


def test_completeness_full_when_all_present() -> None:
    assert analyze_change_note(COMPLETE_NOTE).completeness == 1.0


def test_completeness_is_rounded_two_dp() -> None:
    # 1/4 and 3/4 are exact; assert the value is a clean 2-dp float either way.
    c = analyze_change_note("Relocate the partition walls for an extra EUR 5,000.").completeness
    assert c == round(c, 2)


# --- result shape ----------------------------------------------------------


def test_result_is_frozen_dataclass_with_expected_types() -> None:
    req = analyze_change_note(COMPLETE_NOTE, contract_standard="FIDIC")
    assert isinstance(req, ClarifiedRequest)
    assert isinstance(req.title, str)
    assert isinstance(req.normalized_summary, str)
    assert isinstance(req.detected_classification, str)
    assert isinstance(req.missing, list)
    assert all(isinstance(g, ClarificationGap) for g in req.missing)
    assert all(isinstance(c, ClauseSuggestion) for c in req.clause_suggestions)
    assert isinstance(req.completeness, float)
    with pytest.raises(AttributeError):
        req.title = "mutated"  # type: ignore[misc]


def test_gap_severities_are_valid_tokens() -> None:
    # Pick a note that yields all gap kinds.
    req = analyze_change_note("Move it.")
    valid = {SEVERITY_REQUIRED, SEVERITY_RECOMMENDED}
    assert {g.severity for g in req.missing} <= valid
