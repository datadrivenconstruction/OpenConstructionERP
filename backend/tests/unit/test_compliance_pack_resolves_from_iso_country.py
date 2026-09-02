# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Compliance pack resolution keys off the ISO country column, not free text.

A project carries both ``country_code`` (ISO 3166-1 alpha-2, a controlled
value) and ``region`` (free text somebody types). Pack selection used to read
only ``region``, and it read it by substring, so the pack a project enforced
depended on how its region label happened to be spelled. Two two-letter tokens
did the damage: ``de`` matched the Spanish and French preposition, so "Ciudad
de Mexico" and "Ile-de-France" both enforced the German pack, and ``us``
matched inside "Russia" and "Australia", which both enforced the American one.

The fix is the same shape as the one in the schedule calendars: two keyspaces
that cannot overlap. ISO codes are matched exactly against a country table,
human labels are matched whole-word against a label table, and no two-letter
token is ever substring-matched again.
"""

from __future__ import annotations

import pytest

from app.modules.contracts.compliance_packs import (
    DEFAULT_PACK_ID,
    PACK_BY_COUNTRY,
    PACK_BY_LABEL,
    PACK_BY_LEGACY_CODE,
    RULE_PACKS,
    resolve_pack,
    suggest_pack_for_country,
    suggest_pack_for_region,
)

# ── The two keyspaces cannot overlap ─────────────────────────────────────


def test_country_keyspace_holds_only_iso_alpha2_codes() -> None:
    """Every country key is exactly two uppercase letters."""
    for code in PACK_BY_COUNTRY:
        assert len(code) == 2, f"{code!r} is not an alpha-2 code"
        assert code.isupper(), f"{code!r} is not uppercase"
        assert code.isalpha(), f"{code!r} is not alphabetic"


def test_label_keyspace_never_holds_a_two_letter_token() -> None:
    """No label may be two characters long.

    This is the invariant that makes the defect unrepresentable. "de" and "us"
    lived in the label table, where they meant Germany and the United States,
    and matched the Spanish preposition and the inside of "Russia". Because the
    two tables below cannot overlap, the order they are consulted in does not
    decide any answer.
    """
    for label in PACK_BY_LABEL:
        assert len(label) > 2, f"{label!r} is short enough to collide as a substring"
        assert label == label.lower(), f"{label!r} is not normalised to lowercase"


def test_legacy_codes_are_not_iso_codes() -> None:
    """The non-ISO short codes may not collide with the ISO keyspace."""
    for code in PACK_BY_LEGACY_CODE:
        assert code == code.lower()
        assert code.upper() not in PACK_BY_COUNTRY, f"{code!r} is already an ISO code"


def test_every_pack_id_referenced_by_any_table_exists() -> None:
    for pack_id in {
        *PACK_BY_COUNTRY.values(),
        *PACK_BY_LEGACY_CODE.values(),
        *PACK_BY_LABEL.values(),
    }:
        assert pack_id in RULE_PACKS, f"{pack_id!r} is not a registered pack"


def test_the_legacy_uk_tag_still_resolves() -> None:
    assert suggest_pack_for_region("UK") == "uk_compliance"
    assert suggest_pack_for_region("uk") == "uk_compliance"


# ── The labels that used to resolve to the wrong jurisdiction ────────────


@pytest.mark.parametrize(
    ("region", "expected"),
    [
        # ── the "de" token, which matched any label containing those two
        # letters. Every one of these resolved to de_compliance before.
        # Two American places given the German pack.
        ("Denver", DEFAULT_PACK_ID),
        ("Delaware", DEFAULT_PACK_ID),
        # Four more countries, none of them Germany.
        ("Sweden", DEFAULT_PACK_ID),
        ("Denmark", DEFAULT_PACK_ID),
        ("Nederland", DEFAULT_PACK_ID),
        ("Odesa", DEFAULT_PACK_ID),
        # ── the "us" token. Every one of these resolved to us_compliance.
        ("Australia", DEFAULT_PACK_ID),
        ("Belarus", DEFAULT_PACK_ID),
        ("Cyprus", DEFAULT_PACK_ID),
        ("Brussels", DEFAULT_PACK_ID),
        ("Mauritius", DEFAULT_PACK_ID),
    ],
)
def test_a_region_label_is_not_matched_by_substring(region: str, expected: str) -> None:
    assert suggest_pack_for_region(region) == expected


@pytest.mark.parametrize(
    ("region", "expected", "what_the_substring_bug_gave"),
    [
        # A Spanish and a French preposition, both of which used to be read as
        # the German "de". These three carry the proof now that the labels
        # above cannot: each one is claimed by a country pack, and the pack it
        # is claimed by is not the one the substring defect handed it.
        ("Ciudad de Mexico", "mx_compliance", "de_compliance"),
        ("Ciudad de México", "mx_compliance", "de_compliance"),
        ("Île-de-France", "fr_compliance", "de_compliance"),
        # "Russia" contains "us" and used to enforce the American pack. It now
        # resolves to the Russian one, by a whole-word match on "russia"
        # rather than by a fragment of a different word.
        ("Russia", "ru_compliance", "us_compliance"),
    ],
)
def test_a_label_claimed_by_a_country_is_claimed_by_the_right_one(
    region: str,
    expected: str,
    what_the_substring_bug_gave: str,
) -> None:
    """The right pack has to arrive by the right mechanism.

    These four labels used to resolve to a pack that was wrong about the
    country, because a two-letter token was matched inside a longer word. They
    resolve to a pack now too, so a test that only asserted "not the default"
    would pass on the old defect as well. Asserting the specific pack, and
    naming the one the defect produced, is what makes this a regression test
    rather than a restatement of current behaviour.
    """
    assert suggest_pack_for_region(region) == expected
    assert suggest_pack_for_region(region) != what_the_substring_bug_gave


@pytest.mark.parametrize("region", ["Houston", "Baden-Württemberg", "Baden-Wuerttemberg"])
def test_a_label_that_was_right_by_accident_no_longer_answers_at_all(region: str) -> None:
    """The cases a test built on the intended countries would have missed.

    "Houston" used to resolve to us_compliance by containing "us", and
    "Baden-Wurttemberg" to de_compliance by containing "de" inside "Baden".
    Both were the right pack reached for no reason, which is why a suite built
    only on American and German inputs would have gone green over this defect.
    Neither is matched now: a sub-national label carries no pack, and the ISO
    column is what decides for these projects.
    """
    assert suggest_pack_for_region(region) == DEFAULT_PACK_ID
    assert resolve_pack("US", "Houston") == "us_compliance"
    assert resolve_pack("DE", "Baden-Württemberg") == "de_compliance"


def test_the_labels_that_were_always_right_stay_right() -> None:
    assert suggest_pack_for_region("DACH") == "de_compliance"
    assert suggest_pack_for_region("Germany") == "de_compliance"
    assert suggest_pack_for_region("United Kingdom") == "uk_compliance"
    assert suggest_pack_for_region("USA") == "us_compliance"
    assert suggest_pack_for_region("Mexico") == "mx_compliance"
    assert suggest_pack_for_region("Mars") == DEFAULT_PACK_ID
    assert suggest_pack_for_region(None) == DEFAULT_PACK_ID


# ── The ISO column decides, the free text is only a fallback ─────────────


def test_the_iso_country_outranks_a_contradicting_region_label() -> None:
    """The controlled value wins over the typed one, both ways round."""
    assert resolve_pack("MX", "Germany") == "mx_compliance"
    assert resolve_pack("DE", "Mexico") == "de_compliance"
    assert resolve_pack("GB", "USA") == "uk_compliance"


def test_the_region_label_is_consulted_only_when_no_country_is_known() -> None:
    assert resolve_pack(None, "DACH") == "de_compliance"
    assert resolve_pack("", "United Kingdom") == "uk_compliance"


def test_an_unknown_country_code_does_not_silently_borrow_the_region() -> None:
    """A country we have a code for but no pack for lands on the default.

    Not on whatever the region label happens to spell: a project that says it
    is in Italy is not a Mexican project because its region reads "Ciudad de
    Mexico". This used to be written with Canada, which has a pack now; Italy
    is the country that ships a demo and still has no rule set of its own.
    """
    assert resolve_pack("IT", "Ciudad de Mexico") == DEFAULT_PACK_ID


# ── The empty string is unknown; "DE" is taken at face value ─────────────


def test_the_empty_country_code_reads_as_unknown_not_as_a_country() -> None:
    """``country_code`` is NOT NULL, so absence is spelled as the empty string.

    The demo path writes ``""`` because an empty string does not trigger a
    server default. That is not a country and must not resolve to one.
    """
    assert suggest_pack_for_country("") is None
    assert suggest_pack_for_country("   ") is None
    assert suggest_pack_for_country(None) is None
    assert resolve_pack("", None) == DEFAULT_PACK_ID


def test_germany_is_resolved_at_face_value() -> None:
    """The code "DE" means Germany here; the ambiguity is documented, not resolved.

    A project created through the API with no country chosen also holds "DE",
    from the column's server default, and is indistinguishable in the row from
    a project whose owner really did choose Germany. Demoting "DE" would break
    the real German projects to protect the never-chose ones, so it is read at
    face value. See the note on PACK_BY_COUNTRY.
    """
    assert suggest_pack_for_country("DE") == "de_compliance"
    assert resolve_pack("DE", None) == "de_compliance"


def test_a_country_code_is_normalised_before_it_is_matched() -> None:
    assert suggest_pack_for_country("de") == "de_compliance"
    assert suggest_pack_for_country(" mx ") == "mx_compliance"


# ── The gap this fix makes visible ───────────────────────────────────────


@pytest.mark.parametrize("code", ["IT"])
def test_countries_with_no_pack_resolve_to_the_default(code: str) -> None:
    """Documents a gap rather than asserting a desired state.

    Resolving from the ISO column is correct and still gives an Italian project
    the universal pack, because no Italian pack is registered and there is
    nothing for one to point at: no rule set in the engine reads a DEI or
    computo metrico code. Writing a pack here would be a claim, not a check.

    This list used to read CA, CN, ES, and then JP and TR alongside Italy.
    All of them now have packs, added after confirming the three conditions
    below: their sets are registered ("masterformat", "gbt50500", "bc3",
    "sekisan", "birimfiyat"), each set tests the jurisdiction's own
    classification rather than only that some code exists, and a project in
    those countries that cannot produce its national codes should not reach
    signature unnoticed. Italy is the one kind that never satisfies the first
    condition, which is why it is alone here rather than next in line.

    THIS TEST IS MEANT TO GO RED when a pack is added. It is not an obstacle,
    it is the checklist. Before deleting a code from this list, confirm:

    1. The pack's ``rule_sets`` name sets the engine actually registers.
       ``rule_registry.has_rules(name)`` is the check, and it lives on the
       registry rather than on the engine; an unregistered set does not run
       and must never read as "ran and passed".
    2. Those rules test something the jurisdiction is about, not only that a
       classification code is present and shaped like a code. A gate that
       passes everything is worse than no gate, because an absent pack reads
       as absent while an empty one reads as coverage.
    3. A country added here is one whose projects should be *blocked* at
       contract signature by those rules, not merely one the product supports.

    If all three hold, add the ISO code to PACK_BY_COUNTRY and drop it here.
    """
    assert code not in PACK_BY_COUNTRY
    assert resolve_pack(code, None) == DEFAULT_PACK_ID
