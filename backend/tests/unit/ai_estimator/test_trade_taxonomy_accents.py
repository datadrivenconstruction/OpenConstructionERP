# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠A diacritic must not decide which trade a line item lands in.

The classifier matches keyword substrings, so before accents were folded the
answer depended on whether the export that produced the text kept its marks:
``Rückbau`` was demolition and ``Ruckbau`` was other, ``Serviços`` and
``Servicos`` were two different strings. Folding one side alone only moves
which spelling gets missed, so both sides are folded.

The fold is not free, which is why ``ACCENT_IS_LOAD_BEARING`` exists, and the
last test here is what keeps that list from outliving its reason.
"""

from __future__ import annotations

import pytest

from app.modules.ai_estimator.taxonomy import (
    ACCENT_IS_LOAD_BEARING,
    TRADE_KEYWORDS,
    classify_trade,
    fold_accents,
)

# Words a real bill of quantities carries, in the spelling their own language
# uses. Each has to reach the named trade from the accented spelling and from
# the stripped one alike. None of them may be ``other``: two strings that both
# fall through to the default agree about nothing.
ACCENTED_WORDS: tuple[tuple[str, str], ...] = (
    ("Rückbau der Innenwände", "demolition"),
    ("Démolition et préparation du site", "demolition"),
    ("Gründungsarbeiten Bohrpfähle", "foundations"),
    ("Stützenschalung Untergeschoss", "structure"),
    ("Dämmung der Fassade", "envelope"),
    ("Réfection de la façade", "envelope"),
    ("Dächer und Abdichtung", "envelope"),
    ("Bodenbeläge und Sockelleisten", "finishes"),
    ("Lüftungsanlage mit Wärmerückgewinnung", "mep_mechanical"),
    ("Sanitärinstallation Steigstränge", "mep_plumbing"),
    ("Instalações hidrossanitárias e elétricas", "mep_plumbing"),
    ("Instalación hidrosanitaria y eléctrica", "mep_plumbing"),
    ("Благоустройство территории", "sitework"),
)

# Ordinary words of the other languages in the corpus that no keyword should
# reach. They are the reason the fold cannot simply be applied to everything:
# strip the umlaut off ``tür`` and ``tur`` turns up inside every one of them.
CONTROL_WORDS: tuple[tuple[str, str], ...] = (
    ("Structure", "other"),
    ("Substructure", "other"),
    ("Superstructure frame and cores", "other"),
    ("Architectural drawing set", "other"),
    ("Furniture and loose fittings", "other"),
    ("Moisture protection", "other"),
    ("Temperature control instrumentation", "other"),
    ("Absturzsicherung Attika Geländer", "other"),
    ("Armaturen und Zubehör", "other"),
    ("Natural stone paving", "sitework"),
)


@pytest.mark.parametrize(("text", "expected"), ACCENTED_WORDS)
def test_a_missing_accent_does_not_change_the_trade(text: str, expected: str) -> None:
    stripped = fold_accents(text)
    assert stripped != text, f"{text!r} carries no mark, so it proves nothing about folding"
    assert classify_trade(text) == expected
    assert classify_trade(stripped) == expected, (
        f"{text!r} is {expected} but its stripped form {stripped!r} is {classify_trade(stripped)}"
    )


def test_the_swiss_and_the_german_spelling_reach_the_same_trade() -> None:
    # Eszett has no combining mark to drop, so it needs a fold of its own.
    assert classify_trade("Außenanlagen Hartbelag") == "sitework"
    assert classify_trade("Aussenanlagen Hartbelag") == "sitework"


@pytest.mark.parametrize(("text", "expected"), CONTROL_WORDS)
def test_folding_does_not_hand_a_keyword_a_word_it_never_had(text: str, expected: str) -> None:
    assert classify_trade(text) == expected


def test_the_load_bearing_list_is_exactly_the_keywords_the_fold_would_ruin() -> None:
    """Read the exemption backwards, so it cannot survive being unnecessary.

    A keyword belongs in ``ACCENT_IS_LOAD_BEARING`` when folding it makes it
    match a control word it does not match today, and only then. Respell that
    keyword long enough to be unambiguous and this test asks for it to leave
    the list; add another short accented keyword and it asks for it to join.

    Its reach is ``CONTROL_WORDS`` and no further: a future keyword that folds
    into a collision with some word not listed there is not something this can
    see. Adding a keyword with a mark is the moment to add the ordinary words
    it might swallow.
    """
    every_keyword = {kw for _, keywords in TRADE_KEYWORDS for kw in keywords}
    assert every_keyword >= ACCENT_IS_LOAD_BEARING, (
        f"the list names something that is not a keyword: {sorted(ACCENT_IS_LOAD_BEARING - every_keyword)}"
    )

    would_swallow = {
        kw
        for kw in every_keyword
        if any(fold_accents(kw) in fold_accents(word.lower()) and kw not in word.lower() for word, _ in CONTROL_WORDS)
    }
    assert would_swallow == set(ACCENT_IS_LOAD_BEARING), (
        f"folding newly matches {sorted(would_swallow)} against the control words, "
        f"and the list says {sorted(ACCENT_IS_LOAD_BEARING)}"
    )


def test_the_load_bearing_keyword_still_does_its_own_job() -> None:
    # Kept literal, it goes on matching the spelling that has the mark.
    assert classify_trade("Innentüren Holz mit Stahlzarge") == "openings"
    assert classify_trade("Türen und Fenster") == "openings"
