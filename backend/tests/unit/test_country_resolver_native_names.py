# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A country written the way its own speakers write it resolves to its code.

The resolver lowers a name and looks it up, nothing more. It carried
"magyarorszag", "espana" and "turkiye" without their accents, so the spelling
an address is really written in, "Magyarország", "España", "Türkiye", resolved
to nothing, and a project whose address said Hungary in Hungarian took the
country of whichever pack was active instead.

The cases are one contractor's three countries, each under its own name and
under the names the other two languages give it.
"""

from __future__ import annotations

import pytest

from app.core.country_resolver import _LOOKUP, _RAW_NAME_TO_CODE, resolve_country_code


@pytest.mark.parametrize(
    ("name", "code"),
    [
        # Hungary
        ("Magyarország", "HU"),
        ("magyarország", "HU"),
        ("MAGYARORSZÁG", "HU"),
        ("Magyarorszag", "HU"),
        ("Hungary", "HU"),
        ("Ungarn", "HU"),
        ("Hungría", "HU"),
        ("Macaristan", "HU"),
        # Spain
        ("España", "ES"),
        ("ESPAÑA", "ES"),
        ("Espana", "ES"),
        ("Spain", "ES"),
        ("Spanien", "ES"),
        ("Spanyolország", "ES"),
        ("İspanya", "ES"),
        ("Ispanya", "ES"),
        # Türkiye
        ("Türkiye", "TR"),
        ("TÜRKİYE", "TR"),
        ("TÜRKIYE", "TR"),
        ("Turkiye", "TR"),
        ("Turkey", "TR"),
        ("Törökország", "TR"),
        ("Turquía", "TR"),
        ("Turquia", "TR"),
        ("Türkei", "TR"),
        ("  Türkiye  ", "TR"),
    ],
)
def test_a_native_or_neighbouring_name_resolves(name: str, code: str) -> None:
    assert resolve_country_code(name) == code


def test_the_dotted_capital_i_is_a_spelling_of_its_own() -> None:
    """Why "TÜRKİYE" needs its own key.

    Turkish capitalises "i" to "İ" (U+0130). Python lowers that to "i" plus a
    combining dot (U+0307), two characters, which is not the plain "i" in
    "türkiye". Without the second key the name fails only when it is typed in
    capitals on a Turkish keyboard, which is how a company letterhead writes it.
    """
    assert "TÜRKİYE".lower() != "türkiye"
    assert "TÜRKİYE".lower() in _LOOKUP
    assert "türkiye" in _LOOKUP


def test_no_two_spellings_of_one_lowered_name_disagree() -> None:
    """Lowering merges keys; a merge that changed a code would be silent."""
    seen: dict[str, str] = {}
    for name, code in _RAW_NAME_TO_CODE.items():
        key = name.lower()
        assert seen.setdefault(key, code) == code, f"{name!r} lowers onto a key that means {seen[key]}"


def test_the_fix_is_three_countries_names_and_not_a_change_to_the_lookup() -> None:
    """The control: an accented name nobody added still resolves to nothing.

    The lookup still does not fold accents. If it ever does, this fails, and
    the accented keys added for Hungary, Spain and Türkiye can go; until then
    every other country with an accented endonym has the gap these three had.
    """
    assert resolve_country_code("Osterreich") == "AT"
    assert resolve_country_code("Österreich") is None
    assert resolve_country_code("România") is None


@pytest.mark.parametrize("code", ["HU", "ES", "TR", "hu"])
def test_a_bare_iso_code_is_not_a_country_name(code: str) -> None:
    """The resolver maps names. A caller holding a code already has its answer."""
    assert resolve_country_code(code) is None


@pytest.mark.parametrize("name", ["", "   ", "Atlantis", "Magyar"])
def test_an_unknown_or_empty_name_resolves_to_nothing(name: str) -> None:
    assert resolve_country_code(name) is None
