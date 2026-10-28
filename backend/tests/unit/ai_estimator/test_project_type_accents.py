# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠A missing diacritic must not decide which project type a request lands in.

The offline detector matches synonym substrings against the raw request, so
before accents were folded the answer depended on the writer's keyboard.
``Küchenumbau`` reached the kitchen and ``kuchenumbau`` reached nothing;
``пристройка`` reached the extension and ``пристроика`` reached nothing. Seven
of the twelve marked synonyms detected no type at all when typed flat, which
sends a request that named its own type onto the manual tiles.

The fold is not free, and here it is expensive in exactly one place: ``küche``
folds to ``kuche``, which sits inside ``Kuchen``. German for cake and German
for kitchen differ by the umlaut alone, so folding that one synonym reads a
bakery fit-out as a kitchen renovation. It stays literal, and the last test is
what keeps that exemption from outliving its reason.
"""

from __future__ import annotations

import pytest

from app.modules.ai_estimator.project_types import (
    _TYPES,
    ACCENT_IS_LOAD_BEARING,
    _synonyms,
    detect_project_type,
)
from app.modules.ai_estimator.taxonomy import fold_accents

# Requests in the spelling their own language uses. Each has to reach the named
# type from the marked spelling and from the stripped one alike. None may
# detect nothing: two requests that both fall through agree about nothing.
MARKED_REQUESTS: tuple[tuple[str, str], ...] = (
    ("Küchenumbau in der Altbauwohnung", "kitchen_reno"),
    ("Ремонт ванной под ключ", "bathroom_reno"),
    ("Пристройка к дому 30 м2", "extension"),
    ("Пристройку утеплить и подвести отопление", "extension"),
    ("Büroausbau im dritten Obergeschoss", "commercial_fitout"),
    ("Благоустройство территории вокруг дома", "landscaping"),
    ("Благоустройства двора смета", "landscaping"),
    ("Außenanlagen und Wege pflastern", "landscaping"),
    ("Gebäudetechnik komplett erneuern", "mep_retrofit"),
    ("Замена коммуникаций в подвале", "mep_retrofit"),
)

# Ordinary requests that name no project type, or name a different one. They
# are the reason the fold cannot simply be applied to every synonym: strip the
# umlaut off ``küche`` and ``kuche`` turns up inside the first four.
CONTROL_REQUESTS: tuple[tuple[str, str | None], ...] = (
    ("Kuchen und Torten, Ladenlokal 60 qm", None),
    ("Wir brauchen eine Kuchentheke im Verkaufsraum", None),
    ("Kuchenmaschine für die Konditorei aufstellen", None),
    ("Bäckerei mit Kuchentheke und Kühlvitrine ausbauen", "commercial_fitout"),
    ("Buchhaltung im Büro digitalisieren", None),
    ("Aussenwerbung und Beschilderung erneuern", None),
    ("Buroklammern und Papier bestellen", None),
    ("Aussenspiegel am Firmenwagen tauschen", None),
    ("Ремонт ванны в чугуне, реставрация покрытия", None),
)


@pytest.mark.parametrize(("text", "expected"), MARKED_REQUESTS)
def test_a_missing_mark_does_not_change_the_detected_type(text: str, expected: str) -> None:
    stripped = fold_accents(text)
    # Guard the case itself: a request with no marks would pass vacuously.
    assert stripped != text, f"{text!r} carries no mark, so it proves nothing here"
    assert detect_project_type(text)[0] == expected
    assert detect_project_type(stripped)[0] == expected


def test_the_swiss_and_the_german_spelling_reach_the_same_type() -> None:
    # The eszett has no decomposition, so it needs the explicit fold map.
    assert detect_project_type("Außenanlagen neu gestalten")[0] == "landscaping"
    assert detect_project_type("Aussenanlagen neu gestalten")[0] == "landscaping"


@pytest.mark.parametrize(("text", "expected"), CONTROL_REQUESTS)
def test_folding_does_not_hand_a_synonym_a_word_it_never_had(text: str, expected: str | None) -> None:
    assert detect_project_type(text)[0] == expected


def test_the_load_bearing_list_is_exactly_the_synonyms_the_fold_would_ruin() -> None:
    """The exemption is the inclusion read backwards, so it expires by itself.

    A synonym earns its place iff folding gives it a match it did not have
    against one of the control requests. Reach is ``CONTROL_REQUESTS`` and no
    further: this cannot testify about words nobody wrote down here. When a
    synonym stops being dangerous, or the control set grows to catch another,
    this fails until the list is corrected.
    """
    every_synonym = {syn for pt in _TYPES for syn in _synonyms(pt)}
    assert every_synonym >= ACCENT_IS_LOAD_BEARING, "the list names a synonym no type carries"

    would_swallow = {
        syn
        for syn in every_synonym
        if any(
            fold_accents(syn) in fold_accents(text.lower()) and syn not in text.lower() for text, _ in CONTROL_REQUESTS
        )
    }
    assert would_swallow == set(ACCENT_IS_LOAD_BEARING)


@pytest.mark.parametrize(
    "text",
    ["Küche renovieren", "Küchenumbau in der Altbauwohnung", "Küchenrenovierung beauftragen"],
)
def test_the_load_bearing_synonym_still_does_its_own_job(text: str) -> None:
    # Kept literal, so it has to keep working in its own spelling, including
    # inside the German compounds the substring match exists for.
    assert detect_project_type(text)[0] == "kitchen_reno"


def test_the_price_of_the_exemption_is_written_down() -> None:
    """``Kuche`` alone detects nothing, and that is the deliberate cost.

    Every other marked synonym is rescued by the fold. This one cannot be,
    because the rescue is what would swallow ``Kuchen``. Detecting nothing is
    the designed path onto the manual type tiles, not a wrong answer, and the
    longer compound still carries the flat spelling home.
    """
    assert detect_project_type("Kuche renovieren, 12 qm") == (None, 0)
    assert detect_project_type("Küche renovieren, 12 qm")[0] == "kitchen_reno"
    assert detect_project_type("Kuchenumbau, 12 qm")[0] == "kitchen_reno"


def test_the_fold_decides_what_matches_and_not_what_wins() -> None:
    """Weighing by the synonym as written keeps the tie-break where it was.

    ``außenanlagen`` is the one synonym the fold lengthens, 12 to 13, and the
    tie-break between types reads exactly that number. Weighing the unfolded
    spelling is what stops a fold from quietly promoting a type.
    """
    lengthened = [syn for pt in _TYPES for syn in _synonyms(pt) if len(fold_accents(syn)) != len(syn)]
    assert lengthened == ["außenanlagen"], "a new length-changing synonym needs its tie-break re-measured"
    assert detect_project_type("Außenanlagen und Wege") == detect_project_type("Aussenanlagen und Wege")
