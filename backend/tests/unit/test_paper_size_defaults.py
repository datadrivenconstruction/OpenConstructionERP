# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The unset paper size follows the country, and the country list is not invented.

``app.core.paper_size`` exists because ``oe_users_user.paper_size`` was offered,
stored and read by nothing. The interesting half of the fix is not the wiring
but the default: an unset preference has to pick a sheet, and both obvious
answers are wrong in one direction each.

The second block here is the one worth reading. ``LETTER_COUNTRIES`` is a
three-entry set, and a three-entry set is exactly the kind of constant that
drifts from the tree it was copied out of without anything going red. The
regional packs already declare a ``paper_size`` next to the ``countries`` each
covers, so those declarations are the tree's own answer and this asserts the
constant against them rather than against a second copy of itself. A pack added
later that says Letter fails these tests until someone decides whether the
country belongs in the set.

The two places the derivation is not clean are asserted as themselves, not
skipped: MX is declared twice in conflict, and CA is in the set with no pack
backing it at all. Asserting the CA gap looks perverse until you notice that it
is what turns "adding a Canada pack" into a red test instead of a silent second
opinion.
"""

from __future__ import annotations

import importlib
import pkgutil
from typing import Any

import pytest

import app.modules
from app.core.paper_size import (
    AUTO,
    DEFAULT_PAPER_SIZE,
    LETTER_COUNTRIES,
    LETTER_PAPER_SIZE,
    PAPER_SIZES,
    resolve_paper_size,
    resolve_paper_size_name,
)

# The four spellings the Settings toggle stores, exactly as it stores them.
# Written out rather than derived from PAPER_SIZES so that a size renamed on
# one side of the wire has to be renamed on the other.
TOGGLE_VALUES = ("A4", "A3", "Letter", "Legal")


def _pack_configs() -> dict[str, dict[str, Any]]:
    """Every ``PACK_CONFIG`` in the module tree, keyed by module name.

    Walked rather than listed for the reason ``app.core.country_registries``
    gives at length about its own denominator: a list of packs written here is
    a measurement of the list, and a pack nobody added to it is reported
    neither as agreeing nor as disagreeing.
    """
    configs: dict[str, dict[str, Any]] = {}
    for module in pkgutil.iter_modules(app.modules.__path__):
        if not module.name.endswith("_pack"):
            continue
        try:
            config_module = importlib.import_module(f"app.modules.{module.name}.config")
        except Exception:  # noqa: BLE001 - a pack that will not import is not evidence
            continue
        config = getattr(config_module, "PACK_CONFIG", None)
        if isinstance(config, dict):
            configs[module.name] = config
    return configs


def _declared_letter_countries() -> dict[str, set[str]]:
    """Countries each pack declares, split by the paper size the pack declares."""
    by_size: dict[str, set[str]] = {"letter": set(), "other": set()}
    for config in _pack_configs().values():
        countries = config.get("countries")
        paper = config.get("paper_size")
        if not isinstance(countries, list) or not isinstance(paper, str):
            continue
        bucket = "letter" if paper.strip().upper() == LETTER_PAPER_SIZE else "other"
        by_size[bucket].update(str(c).strip().upper() for c in countries)
    return by_size


# ── The default ───────────────────────────────────────────────────────────


@pytest.mark.parametrize("country", sorted(LETTER_COUNTRIES))
def test_an_unset_preference_follows_a_letter_country_to_letter(country: str) -> None:
    assert resolve_paper_size_name(AUTO, country) == LETTER_PAPER_SIZE


@pytest.mark.parametrize("country", ["DE", "GB", "JP", "BR", "IN", "RU", "CN", "ZA", "AU"])
def test_an_unset_preference_leaves_the_rest_of_the_world_on_a4(country: str) -> None:
    """The half of ``'auto'`` that is inert.

    Every one of these rendered A4 before the preference was wired to anything,
    and renders A4 now. The Letter countries above are the whole of the change.
    """
    assert resolve_paper_size_name(AUTO, country) == DEFAULT_PAPER_SIZE


def test_an_unknown_country_is_not_read_as_a_country() -> None:
    """NULL means unknown, per the column's own comment, so nothing is inferred.

    A4 here is the platform's metric-first default and not a guess that the
    project is European: the point of the assertion is that the answer for
    ``None`` is the same as the answer for a country that stated itself and is
    not on Letter, so no reader can tell "unknown" from "said A4" and be wrong
    about it in the Letter direction.
    """
    assert resolve_paper_size_name(AUTO, None) == DEFAULT_PAPER_SIZE


@pytest.mark.parametrize("value", TOGGLE_VALUES)
def test_an_explicit_choice_beats_the_country(value: str) -> None:
    """Picked A4 on a US project means A4. The setting does not overrule itself."""
    assert resolve_paper_size(value, "US") == PAPER_SIZES[value.upper()]
    assert resolve_paper_size(value, None) == PAPER_SIZES[value.upper()]


@pytest.mark.parametrize("value", ["", "  ", "letter-ish", "1.234,56", "Ledger", None])
def test_a_value_this_toggle_never_wrote_is_treated_as_unset(value: str | None) -> None:
    """The column is free-form ``String(10)`` with no validator, and the packs
    seed it in their own vocabulary. Nonsense degrades to the country default
    rather than raising, because a document a recipient is waiting for must not
    be lost to a settings value."""
    assert resolve_paper_size_name(value, "US") == LETTER_PAPER_SIZE
    assert resolve_paper_size_name(value, "DE") == DEFAULT_PAPER_SIZE


def test_every_size_the_toggle_offers_resolves_to_its_own_size() -> None:
    """Including A3, which the toggle has always offered and which resolved
    nowhere before this module: a value a user can pick that silently becomes a
    different value is the same defect as one that is read by nothing."""
    resolved = {value: resolve_paper_size(value, None) for value in TOGGLE_VALUES}
    assert len(set(resolved.values())) == len(TOGGLE_VALUES), resolved


# ── The country list, against the packs that already declare it ───────────


def test_the_packs_declaring_letter_are_the_packs_this_set_was_built_from() -> None:
    declared = _declared_letter_countries()["letter"]
    assert declared, "no pack declares Letter; the derivation below has no source"
    assert declared <= LETTER_COUNTRIES, (
        f"a pack declares Letter for {sorted(declared - LETTER_COUNTRIES)}, "
        "which app.core.paper_size does not treat as a Letter country"
    )


def test_mexico_is_the_one_country_two_packs_disagree_about() -> None:
    """``mexico_pack`` says Letter for MX; ``latam_pack`` lists MX under A4.

    Asserted rather than resolved quietly, because the resolution is a
    judgement (the country-specific pack outranks the continental one) and a
    judgement that is not written down gets re-made differently next time. If a
    second country ever lands in both buckets, this fails and someone decides.
    """
    declared = _declared_letter_countries()
    contested = declared["letter"] & declared["other"]
    assert contested == {"MX"}, f"packs now disagree about {sorted(contested)}"
    assert "MX" in LETTER_COUNTRIES


def test_canada_is_in_the_set_and_no_pack_backs_it() -> None:
    """The one entry the tree does not corroborate, asserted as a gap.

    There is no Canada pack - ``us_ca_pack`` is the state of California - so CA
    is in ``LETTER_COUNTRIES`` on the strength of Canada's business standard
    alone. When a Canada pack does arrive this test fails, which is the point:
    it forces whoever writes it to look at this set rather than to add a second,
    quieter opinion about Canadian paper.
    """
    declared = _declared_letter_countries()
    assert "CA" in LETTER_COUNTRIES
    assert "CA" not in declared["letter"] | declared["other"]


def test_the_set_holds_iso_alpha_2_codes_and_nothing_else() -> None:
    """``region_code`` is not a country: the packs spell regions ``DACH``,
    ``LATAM``, ``APAC``, ``US_CA``. This set is keyed by
    ``oe_projects_project.country_code``, which is ISO 3166-1 alpha-2, so a
    region code landing here would match no project and fail silently."""
    assert all(len(c) == 2 and c.isalpha() and c.isupper() for c in LETTER_COUNTRIES), sorted(LETTER_COUNTRIES)
