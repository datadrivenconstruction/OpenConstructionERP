# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠``normalize_standard`` matches by substring, and that is a hazard with no victim yet.

The function recognises a contract family anywhere in a free-text hint, which is
what lets ``"NEC4 ECC Option A"`` and ``"nec3"`` both resolve to NEC. The cost of
that generosity is that an ordinary word containing the same letters resolves
too: ``"connecticut"`` contains ``nec``.

Nothing shipped trips it today - the sweep below checks every contract form the
demo packs declare - so this file exists to keep it that way and to make the
behaviour deliberate rather than discovered. A test is the right size for a
defect with no victim: it costs nothing now and it fails loudly the day someone
writes a project description that reads as a standard it is not.
"""

from __future__ import annotations

import re

from app.core.demo_packs import PACK_TEMPLATES
from app.modules.change_intelligence.time_bar import (
    STANDARD_AIA,
    STANDARD_CCDC,
    STANDARD_CONSENSUSDOCS,
    STANDARD_FIDIC,
    STANDARD_JCT,
    STANDARD_NEC,
    STANDARD_UNKNOWN,
    normalize_standard,
)

#: The literal each standard is recognised by, mirroring ``normalize_standard``.
_FAMILY_TOKENS = {
    STANDARD_FIDIC: "fidic",
    STANDARD_NEC: "nec",
    STANDARD_JCT: "jct",
    STANDARD_AIA: "aia",
    STANDARD_CONSENSUSDOCS: "consensus",
    STANDARD_CCDC: "ccdc",
}


def _has_standalone_occurrence(text: str, token: str) -> bool:
    """True when *token* appears at least once not buried inside a longer word.

    A letter on both sides means the match is an accident of spelling. A digit
    or a separator on either side is a real designation, which is why ``NEC4``
    counts and ``connecticut`` does not.
    """
    low = text.lower()
    for match in re.finditer(re.escape(token), low):
        before = low[match.start() - 1] if match.start() else ""
        after = low[match.end()] if match.end() < len(low) else ""
        if not (before.isalpha() and after.isalpha()):
            return True
    return False


def _declared_forms() -> dict[str, str]:
    """Every form of contract the shipped packs declare, by demo id."""
    forms = {}
    for template in PACK_TEMPLATES:
        form = str(template.project_metadata.get("general_contractor_form") or "").strip()
        if form:
            forms[template.demo_id] = form
    return forms


def test_no_shipped_contract_description_matches_a_standard_by_accident() -> None:
    """The live guard. Every declared form that resolves must resolve on purpose."""
    forms = _declared_forms()
    assert forms, "no pack declares a form of contract; this sweep proves nothing"

    swept = 0
    for demo_id, form in forms.items():
        resolved = normalize_standard(form)
        if resolved == STANDARD_UNKNOWN:
            continue
        token = _FAMILY_TOKENS.get(resolved)
        assert token is not None, (
            f"{demo_id} resolves to {resolved}, which has no entry in _FAMILY_TOKENS; "
            f"the mirror has drifted from normalize_standard and this sweep cannot judge it"
        )
        assert _has_standalone_occurrence(form, token), (
            f"{demo_id} declares {form!r}, which resolves to {resolved} only because "
            f"the letters {token!r} appear inside a longer word"
        )
        swept += 1
    assert swept >= 1, "no declared form resolved to a known standard; the guard swept nothing"


def test_a_word_that_merely_contains_the_letters_still_resolves_today() -> None:
    """Characterisation, not endorsement. Pins the hazard so a change is deliberate.

    If someone tightens the matcher to word boundaries this test fails, which is
    the point: it should fail, be read, and be updated by the person making that
    choice rather than silently changing what every free-text hint resolves to.
    """
    assert normalize_standard("Connecticut general conditions") == STANDARD_NEC
    assert not _has_standalone_occurrence("Connecticut general conditions", "nec")


def test_a_real_designation_is_recognised_and_is_not_an_accident() -> None:
    """The other half of the pair: generosity is load-bearing, not incidental."""
    for hint, expected in (
        ("NEC4 ECC Option A", STANDARD_NEC),
        ("nec3", STANDARD_NEC),
        ("fidic_red_1999", STANDARD_FIDIC),
        ("FIDIC Red Book (1999) - lump-sum contract", STANDARD_FIDIC),
        ("JCT SBC 2016", STANDARD_JCT),
        ("AIA A201-2017", STANDARD_AIA),
        ("ConsensusDocs 200", STANDARD_CONSENSUSDOCS),
    ):
        assert normalize_standard(hint) == expected
        assert _has_standalone_occurrence(hint, _FAMILY_TOKENS[expected]), (
            f"{hint!r} resolves to {expected} by accident rather than by designation"
        )


def test_the_token_mirror_still_agrees_with_the_normaliser() -> None:
    """A row whose token does not resolve to its own family judges nothing.

    The sweep above decides whether a match was a designation or an accident by
    looking up the token for the family the normaliser returned. If a row here
    carried the wrong literal, that verdict would be about some other family's
    spelling and would still come back green.
    """
    for family, token in _FAMILY_TOKENS.items():
        assert normalize_standard(token) == family, f"{token!r} does not resolve to {family}"


def test_the_canadian_forms_resolve_by_designation_and_not_by_a_stray_substring() -> None:
    """CCDC is recognised, and these strings must reach it by its own acronym.

    The hazard this file guards is a form being captured by a family it has
    nothing to do with, because the letters happened to line up. That is what
    ``contrat a forfait`` and ``stipulated price`` are doing here: the two
    descriptive tails in the tree most likely to collide by accident, named
    rather than left to the sweep.

    Until CCDC was recognised the only way to state "did not collide" was
    "resolved to nothing", and that is what this test used to assert. Now that
    the family is in the normaliser, the collision is measured directly: of the
    six family tokens, exactly one occurs anywhere in each hint, that one is
    ``ccdc``, and it stands alone rather than sitting inside a longer word. A
    hint dragged into NEC or AIA by its tail still fails, which is the property
    that was being protected.
    """
    for hint in (
        "CCDC 2 (2020) - stipulated price",
        "CCDC 2 (2020) - contrat à forfait",
        "CCDC 5B (2010) - construction management",
    ):
        present = {family for family, token in _FAMILY_TOKENS.items() if token in hint.lower()}
        assert present == {STANDARD_CCDC}, f"{hint!r} contains the token of {sorted(present)}, expected CCDC alone"
        assert _has_standalone_occurrence(hint, _FAMILY_TOKENS[STANDARD_CCDC]), (
            f"{hint!r} would reach CCDC only by the letters appearing inside a longer word"
        )
        assert normalize_standard(hint) == STANDARD_CCDC, f"{hint!r} should resolve to its own family"
