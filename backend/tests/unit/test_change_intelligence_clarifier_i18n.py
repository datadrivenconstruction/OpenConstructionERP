# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠International-robustness tests for the change-request clarifier (py3.11 pure).

Covers the widened, currency-agnostic cost signal (so a note written anywhere in
the world is read the same way, not only one priced in euros / dollars / pounds)
and the conservative input-size guard on the clarifier request schema.
"""

from __future__ import annotations

import pytest

from app.modules.change_intelligence.clarifier import analyze_change_note


def _gap_fields(note: str) -> set[str]:
    return {g.field for g in analyze_change_note(note).missing}


def _cost_detected(note: str) -> bool:
    """A note whose cost signal fired has no ``cost_impact`` gap."""
    return "cost_impact" not in _gap_fields(note)


# --- international currency words / codes -----------------------------------


@pytest.mark.parametrize(
    "note",
    [
        # ISO code plus a figure.
        "Add CHF 12,000 for the extra insulation works to the plant room.",
        "Budget increase of 200000 INR for the additional rebar on level two.",
        "Provide AED 30,000 for the additional facade cleaning cradle rigging.",
        "Allow SAR 45,000 for the extra mechanical plant on the roof deck.",
        "Add ZAR 60,000 for the additional site hoarding along the boundary.",
        "Allow AUD 18,000 for the extra temporary works to the basement.",
        "Provide NGN 2,000,000 for the additional block work to the east wing.",
        "Allow KES 500,000 for the extra drainage runs across the car park.",
        "Add PLN 25,000 for the additional screed to the ground floor slab.",
        # Currency name, no figure needed.
        "The client will settle in yen for the imported fittings and fixtures.",
        "Payment for the extra joinery will be made in yuan by the supplier.",
        "The subcontractor quoted the works in rupees for the imported tiles.",
        "The extra plant will be invoiced in dirhams by the hire company here.",
        "The imported steel will be paid for in krona by the fabricator abroad.",
    ],
)
def test_international_currency_words_trip_cost_signal(note: str) -> None:
    assert _cost_detected(note)


# --- international currency symbols -----------------------------------------


@pytest.mark.parametrize(
    "note",
    [
        # A symbol attached to a figure, with no cost vocabulary word present.
        "Extra works billed at ¥500,000 for the facade panels near the atrium.",
        "Additional ₹250,000 for the drainage upgrade works to the yard here.",
        "Provide ₩1,500,000 for the imported switchgear to the plant room.",
        "Allow ₦2,000,000 for the additional block work across the site here.",
        "Add ₺80,000 for the extra steelwork to the canopy over the entrance.",
    ],
)
def test_international_currency_symbols_trip_cost_signal(note: str) -> None:
    assert _cost_detected(note)


# --- deliberate exclusions (no false positives) ----------------------------


def test_cad_software_mention_does_not_trip_cost() -> None:
    # "CAD" (computer-aided design) is an everyday construction abbreviation and
    # is deliberately NOT read as the Canadian-dollar currency code. With no
    # figure and no cost word, the note still owes a cost-impact answer.
    note = "The engineer updated the CAD model of the lobby and reissued the drawings for review."
    assert not _cost_detected(note)


def test_common_english_homograph_won_does_not_trip_cost() -> None:
    # "won" (past tense of win) collides with the Korean currency name, so the
    # word is excluded from the cost vocabulary; it must not be read as money.
    note = "The subcontractor won the tender for the facade package on the north elevation."
    assert not _cost_detected(note)


# --- the three Western majors still work -----------------------------------


@pytest.mark.parametrize(
    "note",
    [
        "Client wants a stone lobby for an extra EUR 45,000 of finishing work.",
        "Relocate the partition walls on level three for an extra $12,500 of work.",
        "Allow GBP 8,000 for the additional balustrade to the main stair core.",
    ],
)
def test_western_majors_still_trip_cost_signal(note: str) -> None:
    assert _cost_detected(note)


# --- schema input-size guard -----------------------------------------------


def test_clarify_in_accepts_normal_and_empty_notes() -> None:
    from app.modules.change_intelligence.schemas import ClarifyIn

    assert ClarifyIn(note="Swap the cladding to stone.").note
    # An empty note is allowed (the engine returns an "Untitled change" draft).
    assert ClarifyIn(note="").note == ""
    assert ClarifyIn(note="ok", contract_standard="FIDIC").contract_standard == "FIDIC"


def test_clarify_in_rejects_oversized_input() -> None:
    from pydantic import ValidationError

    from app.modules.change_intelligence.schemas import ClarifyIn

    with pytest.raises(ValidationError):
        ClarifyIn(note="x" * 20_001)
    with pytest.raises(ValidationError):
        ClarifyIn(note="ok", contract_standard="y" * 101)
