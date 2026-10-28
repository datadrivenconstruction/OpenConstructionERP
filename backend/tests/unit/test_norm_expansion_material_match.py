# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for resolving a norm material to the cost item that prices it.

These cover :mod:`app.modules.norm_expansion.material_match`, which decides
which catalogue row puts money on a norm-derived line, called directly rather
than through the service.

**Read this before adding a test here.** The outcome of the two-tier design -
an exact normalized-name match beating a higher-scoring fuzzy one, a fuzzy match
surfacing as a reviewable proposal, freshness breaking a tie between two exact
rows, an accented catalogue row still matching, an unmatched material reading as
unpriced rather than priced at zero - is asserted end to end in
``test_norm_expansion_build_assembly.py``, through ``build_assembly_from_norm``
and the router response. Those tests measure their own premise (they check that
the lexical channel really does score the wrong row higher before asserting that
the right one wins), so restating them here would add a weaker copy, not a
second opinion.

This file takes the half that a service-level test cannot reach: the matcher's
own units. The normalizer, the SQL prefilter, ``_candidate_keys`` and the
tie-break are pure functions, exercised with plain values and unattached ORM
instances - which is where the Unicode form, the case fold and the ordering of
the tie-break fields are actually decidable. What genuinely needs candidate rows
- the score floor's boundary, ties, a fuzzy hit that cannot be turned into a
row, and the guarantee that the lexical tier does not merely lose but never runs
- uses the shared ``oe_test_unit`` database via ``tests._pg`` (rolled back on
teardown).

Two of these used to stand as ``xfail(strict=True)`` - a localized product name
that no candidate pass could reach, and a nameless material the lexical tier
priced at full confidence. Both cost real money while they stood (a wrong rate
on a priced line, not a cosmetic gap) and both are now closed; their tests carry
the measurement that made the case, so the reason survives the marker.

One ``xfail(strict=True)`` still stands: a placeholder name that carries a
comparison key (``'n/a'`` reduces to ``'na'``) is not held by either guard and
is still priced off an unrelated row. Closing it needs a placeholder vocabulary
settled across the platform's locales, not a code change here, so it is left
measured rather than guessed at - and a failing XPASS will tell whoever settles
it to drop the marker. Read the reason before assuming it is decoration.
"""

from __future__ import annotations

import itertools
import math
import uuid
from dataclasses import FrozenInstanceError, fields
from datetime import date
from decimal import Decimal

import pytest
import pytest_asyncio

from app.modules.costs.matcher import MatchResult
from app.modules.costs.models import CostItem
from app.modules.norm_expansion.material_match import (
    MaterialMatch,
    _candidate_keys,
    _prefilter_tokens,
    _rows_by_all_tokens,
    _rows_by_literal_description,
    _tie_break,
    find_exact_cost_item,
    normalize_material_name,
    resolve_material_cost_item,
)
from app.modules.norm_expansion.price_math import COST_ITEM_EXACT, COST_ITEM_FUZZY
from tests._pg import transactional_session

D = Decimal


def _item(
    code: str,
    *,
    description: str = "Gypsum plaster",
    unit: str = "m3",
    rate: str = "10.00",
    region: str | None = None,
    price_as_of: date | None = None,
) -> CostItem:
    """An unattached cost item, for the pure ordering helpers.

    Codes are fixed rather than random because ``code`` is the tie-break's
    final discriminator - a random one would make the assertions non-
    deterministic.
    """
    return CostItem(
        code=code,
        description=description,
        unit=unit,
        rate=rate,
        currency="EUR",
        source="custom",
        is_active=True,
        region=region,
        price_as_of=price_as_of,
    )


# ---------------------------------------------------------------------------
# normalize_material_name
# ---------------------------------------------------------------------------


def test_normalize_folds_case_and_drops_whitespace() -> None:
    assert normalize_material_name("  Gypsum   PLASTER ") == "gypsumplaster"
    assert normalize_material_name("Gypsum Plaster") == "gypsumplaster"


def test_normalize_drops_punctuation() -> None:
    key = normalize_material_name("C25/30, ready-mix (pumped)")
    assert key == "c2530readymixpumped"


def test_normalize_folds_accents() -> None:
    accented = normalize_material_name("Lámina de yeso")
    assert accented == normalize_material_name("Lamina de yeso")


def test_normalize_collapses_spacing_inside_a_dimension() -> None:
    assert normalize_material_name("12 mm") == normalize_material_name("12mm")


def test_normalize_keeps_different_dimensions_apart() -> None:
    assert normalize_material_name("12 mm") != normalize_material_name("15 mm")


@pytest.mark.parametrize("raw", [None, "", "   ", "---", "/,.-"])
def test_normalize_yields_no_key_without_letters_or_digits(raw) -> None:
    assert normalize_material_name(raw) == ""


def test_a_digit_free_non_latin_name_keeps_its_own_letters() -> None:
    """A name in another script is a name, not an absence of one.

    The fold used to keep ASCII letters only, so these two reduced to ``""``
    each and were refused up front. That was safe and useless: the products
    exist in the catalogue and could never be matched by their own names.
    """
    assert normalize_material_name("Бетон") == "бетон"
    assert normalize_material_name("Кирпич") == "кирпич"
    assert normalize_material_name("Бетон") != normalize_material_name("Кирпич")


def test_two_different_non_latin_materials_do_not_share_a_key() -> None:
    """Two products of the same grade are two products.

    While the fold kept ASCII only, both of these reduced to the key ``"300"``
    and find_exact_cost_item called that an identity match: confidence 1,
    needs_review False, concrete priced at the brick's rate with nobody told.
    Every script the production norms ship in carried the same defect, and a
    grade number is the normal shape of a GESN / FER material name.
    """
    concrete = normalize_material_name("Бетон М300")
    brick = normalize_material_name("Кирпич 300")
    assert concrete == "бетонм300"
    assert brick == "кирпич300"
    assert concrete != brick


# ---------------------------------------------------------------------------
# _prefilter_tokens
# ---------------------------------------------------------------------------


def test_prefilter_tokens_extracts_lowercased_tokens_in_order() -> None:
    assert _prefilter_tokens("Gypsum Plaster Board") == ["gypsum", "plaster", "board"]


def test_prefilter_tokens_drops_tokens_shorter_than_three() -> None:
    assert _prefilter_tokens("12 mm x steel bar") == ["steel", "bar"]


def test_prefilter_tokens_deduplicates_keeping_first_position() -> None:
    assert _prefilter_tokens("board gypsum board panel gypsum") == [
        "board",
        "gypsum",
        "panel",
    ]


def test_prefilter_tokens_is_empty_when_nothing_is_long_enough() -> None:
    assert _prefilter_tokens("12 mm") == []
    assert _prefilter_tokens("") == []


def test_prefilter_tokens_reads_a_non_latin_name() -> None:
    """A non-Latin name has to produce a prefilter, or two of three passes die.

    Non-Latin letters were not tokens, so such a name got no SQL prefilter at
    all and both token passes returned before touching the database. What that
    cost is measured against real rows in
    ``test_a_digit_free_non_latin_material_is_reached_by_a_token_pass``.
    """
    assert _prefilter_tokens("Бетон М300") == ["бетон", "м300"]
    # Still de-duplicated and still ordered, whatever the script.
    assert _prefilter_tokens("Кирпич кирпич керамический") == ["кирпич", "керамический"]


def test_prefilter_tokens_keeps_an_accented_word_whole() -> None:
    """The prefilter reads the RAW name, not the folded key.

    ``Lámina`` used to split at the accent into ``l`` and ``mina``, and the
    ``l`` was then dropped for being too short, so the SQL scan went looking for
    ``%mina%`` - a fragment that matches the right row by luck and a great many
    wrong ones by design. It is one token now, accent included. ILIKE is not
    accent-insensitive, so this token finds an accented catalogue row and misses
    an unaccented one, which is what the last-resort window is for; the key
    comparison still decides every match.
    """
    assert _prefilter_tokens("Lámina de yeso") == ["lámina", "yeso"]


# ---------------------------------------------------------------------------
# _candidate_keys
# ---------------------------------------------------------------------------


def test_candidate_keys_cover_the_primary_description() -> None:
    assert _candidate_keys(_item("AAA-001")) == {"gypsumplaster"}


def test_candidate_keys_include_localized_descriptions() -> None:
    item = _item("AAA-001")
    item.descriptions = {"es": "Yeso", "de": "Gipsputz"}
    assert _candidate_keys(item) == {"gypsumplaster", "yeso", "gipsputz"}


def test_candidate_keys_tolerate_an_unset_descriptions_column() -> None:
    """The JSON default fires at flush, so an unattached row has ``None``."""
    item = _item("AAA-001")
    assert item.descriptions is None
    assert _candidate_keys(item) == {"gypsumplaster"}


def test_candidate_keys_never_contain_the_empty_key() -> None:
    # Every value here carries no letter and no digit. This case used to use a
    # Cyrillic unit for one of them, which was keyless only because the fold
    # kept ASCII; it now has a key of its own, so the case says what it means
    # with punctuation instead.
    item = _item("AAA-001", description="---")
    item.descriptions = {"ru": "- / -", "es": ""}
    assert _candidate_keys(item) == set()


# ---------------------------------------------------------------------------
# _tie_break
# ---------------------------------------------------------------------------


def _ranked(items: list[CostItem], *, unit=None, region=None) -> list[str]:
    ordered = sorted(items, key=lambda row: _tie_break(row, unit=unit, region=region))
    return [row.code for row in ordered]


def test_tie_break_prefers_the_candidate_whose_unit_agrees() -> None:
    wrong = _item("AAA-001", unit="kg")
    right = _item("ZZZ-999", unit="m3")
    assert _ranked([wrong, right], unit="m3") == ["ZZZ-999", "AAA-001"]


def test_tie_break_prefers_the_requested_region_once_units_agree() -> None:
    other = _item("AAA-001", region="DE_BERLIN")
    wanted = _item("ZZZ-999", region="ES_MADRID")
    assert _ranked([other, wanted], unit="m3", region="ES_MADRID") == [
        "ZZZ-999",
        "AAA-001",
    ]


def test_unit_agreement_outranks_the_requested_region() -> None:
    right_region = _item("AAA-001", unit="kg", region="ES_MADRID")
    right_unit = _item("ZZZ-999", unit="m3", region="DE_BERLIN")
    ranked = _ranked([right_region, right_unit], unit="m3", region="ES_MADRID")
    assert ranked == ["ZZZ-999", "AAA-001"]


def test_tie_break_prefers_the_most_recently_priced_row() -> None:
    stale = _item("AAA-001", price_as_of=date(2024, 1, 1))
    fresh = _item("ZZZ-999", price_as_of=date(2026, 6, 1))
    assert _ranked([stale, fresh], unit="m3") == ["ZZZ-999", "AAA-001"]


def test_tie_break_puts_an_undated_row_last() -> None:
    undated = _item("AAA-001", price_as_of=None)
    dated = _item("ZZZ-999", price_as_of=date(2020, 1, 1))
    assert _ranked([undated, dated], unit="m3") == ["ZZZ-999", "AAA-001"]


def test_code_is_the_final_discriminator() -> None:
    assert _ranked([_item("BBB-002"), _item("AAA-001")], unit="m3") == [
        "AAA-001",
        "BBB-002",
    ]


def test_tie_break_expresses_no_unit_preference_when_none_is_requested() -> None:
    """An absent unit must not become a filter - it falls through to code."""
    kilos = _item("AAA-001", unit="kg")
    cubes = _item("ZZZ-999", unit="m3")
    assert _ranked([cubes, kilos]) == ["AAA-001", "ZZZ-999"]


def test_tie_break_picks_the_same_winner_whatever_the_input_order() -> None:
    """The property that silently moves money if it ever stops holding.

    Rows arrive from SQL in no guaranteed order, so an unstable tie-break would
    price the same material differently between two identical runs.
    """
    items = [_item("CCC-003"), _item("AAA-001"), _item("BBB-002")]
    shuffles = itertools.permutations(items)
    winners = {_ranked(list(order), unit="m3")[0] for order in shuffles}
    assert winners == {"AAA-001"}


def test_tie_break_orders_a_fully_mixed_field_deterministically() -> None:
    items = [
        _item("AAA-001", unit="kg", price_as_of=date(2026, 1, 1)),
        _item("BBB-002", unit="m3", region="ES_MADRID"),
        _item("CCC-003", unit="m3", region="ES_MADRID", price_as_of=date(2025, 1, 1)),
        _item("DDD-004", unit="m3"),
    ]

    def order_of(candidates) -> tuple[str, ...]:
        return tuple(_ranked(list(candidates), unit="m3", region="ES_MADRID"))

    orders = {order_of(p) for p in itertools.permutations(items)}
    assert orders == {("CCC-003", "BBB-002", "DDD-004", "AAA-001")}


# ---------------------------------------------------------------------------
# MaterialMatch
# ---------------------------------------------------------------------------


def _material_match(**overrides) -> MaterialMatch:
    kwargs = {
        "item": _item("AAA-001"),
        "method": COST_ITEM_EXACT,
        "confidence": D("1"),
        "needs_review": False,
    }
    kwargs.update(overrides)
    return MaterialMatch(**kwargs)


def test_material_match_carries_exactly_the_fields_the_caller_reads() -> None:
    """The provenance record is the audit trail behind a priced line.

    Naming the field set means a field renamed or quietly dropped fails here, in
    one obvious place, instead of surfacing as a missing key in the ``metadata_``
    the service writes onto the component.
    """
    assert [f.name for f in fields(MaterialMatch)] == [
        "item",
        "method",
        "confidence",
        "needs_review",
    ]
    assert MaterialMatch.__dataclass_params__.frozen is True


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("item", None),
        ("method", COST_ITEM_FUZZY),
        ("confidence", D("0.5")),
        ("needs_review", True),
    ],
)
def test_no_field_of_a_material_match_can_be_reassigned(field_name, value) -> None:
    """Frozen on every field, not just the one a spot check happened to pick.

    The record travels to the code that writes the rate and the review flag. If
    any single field could be rewritten on the way, the provenance would stop
    describing the decision that was actually taken - and ``needs_review`` is
    the field where that costs the most, because flipping it silently retires a
    human check.
    """
    match = _material_match()
    with pytest.raises(FrozenInstanceError):
        setattr(match, field_name, value)


def test_two_material_matches_describing_the_same_decision_are_equal() -> None:
    """Frozen means it is a value, so two identical records compare equal."""
    item = _item("AAA-001")
    assert _material_match(item=item) == _material_match(item=item)
    assert _material_match(item=item) != _material_match(item=item, needs_review=True)


# ---------------------------------------------------------------------------
# Database-backed tiers
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def session():
    async with transactional_session() as s:
        yield s


async def _seed(
    s,
    *,
    code: str,
    description: str,
    unit: str = "m3",
    rate: str = "10.00",
    region: str | None = None,
    price_as_of: date | None = None,
    is_active: bool = True,
    descriptions: dict | None = None,
) -> CostItem:
    item = CostItem(
        code=code,
        description=description,
        unit=unit,
        rate=rate,
        currency="EUR",
        source="custom",
        is_active=is_active,
        region=region,
        price_as_of=price_as_of,
        descriptions=descriptions or {},
    )
    s.add(item)
    await s.flush()
    return item


@pytest.mark.asyncio
async def test_exact_match_finds_the_row_named_verbatim(session) -> None:
    item = await _seed(session, code="EX-001", description="Gypsum plaster")
    found = await find_exact_cost_item(session, "Gypsum plaster", unit="m3")
    assert found is not None
    assert found.id == item.id


@pytest.mark.asyncio
async def test_exact_match_ignores_case_punctuation_and_spacing(session) -> None:
    """Reached through the widest pass: ILIKE '%12mm%' misses '12 mm'."""
    item = await _seed(session, code="EX-001", description="Gypsum Plaster, 12 mm")
    found = await find_exact_cost_item(session, "  gypsum plaster 12mm  ")
    assert found is not None
    assert found.id == item.id


@pytest.mark.asyncio
async def test_no_candidates_at_all_returns_none(session) -> None:
    await _seed(session, code="EX-001", description="Structural steel beam")
    assert await find_exact_cost_item(session, "Gypsum plaster") is None


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["", "   ", "---"])
async def test_a_keyless_name_never_matches_anything(session, name) -> None:
    await _seed(session, code="EX-001", description="Gypsum plaster")
    assert await find_exact_cost_item(session, name) is None


@pytest.mark.asyncio
async def test_an_inactive_row_is_never_matched(session) -> None:
    await _seed(session, code="EX-001", description="Gypsum plaster", is_active=False)
    assert await find_exact_cost_item(session, "Gypsum plaster") is None


@pytest.mark.asyncio
async def test_exactly_one_candidate_is_returned_despite_a_unit_mismatch(
    session,
) -> None:
    """Unit is a tie-break, not a filter - one exact match still resolves."""
    item = await _seed(session, code="ONE-001", description="Gypsum plaster", unit="kg")
    found = await find_exact_cost_item(session, "Gypsum plaster", unit="m3")
    assert found is not None
    assert found.id == item.id


@pytest.mark.asyncio
async def test_a_localized_description_can_carry_the_match(session) -> None:
    """The Spanish key resolves a row whose primary description is English."""
    item = await _seed(
        session,
        code="LOC-001",
        description="Gypsum plasterboard yeso",
        descriptions={"es": "Yeso"},
    )
    found = await find_exact_cost_item(session, "Yeso")
    assert found is not None
    assert found.id == item.id
    # The primary description alone would not have matched this key.
    assert normalize_material_name(item.description) != normalize_material_name("Yeso")


@pytest.mark.asyncio
async def test_a_localized_description_matches_with_no_shared_token(session) -> None:
    """The localized name alone reaches the row - no shared token needed.

    The row before this one shares the token ``yeso`` between its primary
    description and its Spanish one, so the description-only passes could reach
    it by accident. Here nothing is shared: the row is reachable only because
    the candidate passes search the localized names too.
    """
    item = await _seed(
        session,
        code="LOC-002",
        description="Gypsum plasterboard",
        descriptions={"es": "Yeso laminado"},
    )
    found = await find_exact_cost_item(session, "Yeso laminado")
    assert found is not None
    assert found.id == item.id


@pytest.mark.asyncio
async def test_duplicate_rows_resolve_to_the_same_row_every_time(session) -> None:
    """Three indistinguishable rows must not price the line three ways."""
    for code in ("CCC-003", "AAA-001", "BBB-002"):
        await _seed(session, code=code, description="Gypsum plaster")
    seen = []
    for _ in range(3):
        found = await find_exact_cost_item(session, "Gypsum plaster")
        assert found is not None
        seen.append(found.code)
    assert seen == ["AAA-001", "AAA-001", "AAA-001"]


@pytest.mark.asyncio
async def test_a_wrong_unit_row_loses_to_a_right_unit_row_of_the_same_name(
    session,
) -> None:
    await _seed(session, code="AAA-001", description="Gypsum plaster", unit="kg")
    right = await _seed(
        session,
        code="ZZZ-999",
        description="Gypsum plaster",
        unit="m3",
    )
    found = await find_exact_cost_item(session, "Gypsum plaster", unit="m3")
    assert found is not None
    assert found.id == right.id


@pytest.mark.asyncio
async def test_a_non_latin_material_does_not_match_a_row_sharing_only_its_digits(
    session,
) -> None:
    """The normalizer defect as it reached the database.

    While the fold kept ASCII only, 'Бетон М300' and this brick row both
    normalized to '300' and this call returned the brick as an identity match
    for concrete.
    """
    await _seed(
        session,
        code="BRK-001",
        description="Кирпич 300",
        unit="шт",
        rate="0.45",
    )
    assert await find_exact_cost_item(session, "Бетон М300", unit="м3") is None


@pytest.mark.asyncio
async def test_a_digit_free_non_latin_material_is_reached_by_a_token_pass(session) -> None:
    """Widening the key is not enough on its own: the prefilter has to widen too.

    ``_rows_by_all_tokens`` and ``_rows_by_any_token`` both return early on an
    empty token list, so a name that yields no tokens is reachable only by the
    byte-exact literal pass. A Cyrillic name carrying no grade number yielded
    exactly that, which meant a spacing difference between the norm and the
    catalogue was enough to leave the material unpriced while the row sat in the
    table. The assertions below are in the order the loaders run, so the one
    that fails names the pass that is dead.
    """
    item = await _seed(
        session,
        code="CYR-010",
        description="кирпич керамический одинарный",
        unit="шт",
        rate="0.45",
    )
    # The norm spells it with the doubled spacing an import leaves behind, so
    # the literal pass cannot see the row and only a token pass can.
    material = "кирпич  керамический  одинарный"

    assert _prefilter_tokens(material) == ["кирпич", "керамический", "одинарный"]
    assert await _rows_by_literal_description(session, material) == []
    assert [row.id for row in await _rows_by_all_tokens(session, _prefilter_tokens(material))] == [item.id]

    found = await find_exact_cost_item(session, material, unit="шт")
    assert found is not None
    assert found.id == item.id


@pytest.mark.asyncio
async def test_a_non_latin_material_carrying_a_grade_finds_its_own_row(session) -> None:
    """The positive half of the collision test, on the common ГЭСН/ФЕР shape.

    Refusing the brick is only half an answer: the concrete still has to reach
    its own row. The grade is now part of a letter token (``м300``, not the bare
    ``300`` it used to be), which narrows the all-token pass onto the grade as
    the norm spells it, so this asserts through the loaders and not only through
    the result.

    Two deliberate choices here, neither of them cosmetic. The catalogue row is
    seeded lower case because ``ILIKE`` folds case through the database's own
    ctype, and a cluster initialised under the C locale folds ASCII only: a
    ``Бетон`` on disk is not found by ``'%бетон%'`` there, so a title-cased seed
    would assert the cluster's locale rather than this module's behaviour. The
    material is then spelt with a doubled space so the literal pass cannot
    answer first and leave the all-token assertion proving nothing.
    """
    concrete = await _seed(session, code="CNC-300", description="бетон м300", unit="м3", rate="95.00")
    await _seed(session, code="BRK-300", description="кирпич 300", unit="шт", rate="0.45")

    material = "бетон  м300"
    tokens = _prefilter_tokens(material)
    assert tokens == ["бетон", "м300"]
    assert await _rows_by_literal_description(session, material) == []
    assert [row.id for row in await _rows_by_all_tokens(session, tokens)] == [concrete.id]

    found = await find_exact_cost_item(session, material, unit="м3")
    assert found is not None
    assert found.id == concrete.id


# ---------------------------------------------------------------------------
# Tier behaviour that the service-level tests cannot see
# ---------------------------------------------------------------------------
#
# That the exact tier WINS is asserted end to end in
# test_norm_expansion_build_assembly.py and is not repeated here. What follows
# is what that assertion cannot distinguish: whether the exact tier won because
# it ran first, or because it happened to outscore the rival.

# The exact row and the rival share every distinctive token, so both are
# candidates for the same query, but only the exact row shares its key.
_MATERIAL = "Gypsum plaster board 12mm"


async def _seed_fuzzy_rival(s) -> CostItem:
    return await _seed(
        s,
        code="FUZ-001",
        description="Gypsum plaster board 12mm heavy duty",
        unit="m2",
        rate="9.00",
    )


async def _seed_exact_row(s) -> CostItem:
    return await _seed(
        s,
        code="EXA-001",
        description="gypsum   plaster board 12 mm",
        unit="m2",
        rate="4.00",
    )


@pytest.mark.asyncio
async def test_an_exact_match_is_never_flagged_for_review(session) -> None:
    item = await _seed(session, code="EX-001", description="Gypsum plaster", unit="m3")
    match = await resolve_material_cost_item(
        session,
        "gypsum plaster",
        unit="m3",
        min_fuzzy_score=0.9,
    )
    assert match is not None
    assert match.item.id == item.id
    assert match.method == COST_ITEM_EXACT
    assert match.needs_review is False


@pytest.mark.asyncio
async def test_a_fuzzy_candidate_below_the_floor_leaves_the_material_unpriced(
    session,
) -> None:
    await _seed_fuzzy_rival(session)
    scored = await resolve_material_cost_item(
        session,
        _MATERIAL,
        unit="m2",
        min_fuzzy_score=0.0,
    )
    assert scored is not None
    floor = float(scored.confidence) + 0.01
    refused = await resolve_material_cost_item(
        session,
        _MATERIAL,
        unit="m2",
        min_fuzzy_score=floor,
    )
    assert refused is None


@pytest.mark.asyncio
async def test_nothing_resolves_against_an_empty_catalogue(session) -> None:
    match = await resolve_material_cost_item(
        session,
        _MATERIAL,
        unit="m2",
        min_fuzzy_score=0.1,
    )
    assert match is None


# ---------------------------------------------------------------------------
# Which Unicode fold, and which case fold
# ---------------------------------------------------------------------------
#
# The two tests below are the ones that fail if the normalizer's *form* is
# changed while its behaviour on the plain examples stays identical. Every
# other normalizer test above passes under NFD and under ``lower()`` too, so
# without these a silent swap of either would ship.


def test_normalize_folds_compatibility_forms_of_a_unit() -> None:
    """NFKD, not NFD: catalogues type units both ways and mean one thing.

    ``m³`` and ``㎡`` are compatibility characters. Only the K-form decomposes
    them to ``m3`` / ``m2``; under NFD the superscript survives the decomposition
    intact, so ``m³`` would keep its raised three and stop matching the ``m3``
    spelling of its own unit.
    """
    assert normalize_material_name("m³") == "m3"
    assert normalize_material_name("㎡") == "m2"
    assert normalize_material_name("Concrete C25/30 m³") == normalize_material_name("Concrete C25/30 m3")
    # Full-width digits arrive from CJK exports of the same catalogues.
    assert normalize_material_name("１２ mm") == normalize_material_name("12 mm")


def test_normalize_case_folds_rather_than_lower_casing() -> None:
    """``casefold``, not ``lower``: German is a first-class market here.

    ``lower()`` leaves ``ß`` alone, so ``Straße`` would keep it and stop
    matching the ``Strasse`` spelling of the same product. ``casefold`` maps it
    to ``ss`` first.
    """
    assert normalize_material_name("Straße") == "strasse"
    assert normalize_material_name("Straßenbeton") == normalize_material_name("Strassenbeton")


# ---------------------------------------------------------------------------
# The dimension string from the report, and what dropping separators costs
# ---------------------------------------------------------------------------

# The material as an estimator types it into a norm, and the same product as a
# catalogue exported it: comma decimals against period decimals, spaced units
# against joined ones, title case against sentence case.
_DIM_AS_TYPED = "Lamina gypsum blanca 12 mm x 1,22 x 2,44 m"
_DIM_AS_EXPORTED = "Lamina Gypsum Blanca 12mm X 1.22 X 2.44 M"


def test_normalize_reconciles_the_two_ways_a_sheet_size_is_written() -> None:
    """The whole point of the key, on the string shape the report was about.

    Neither spelling is wrong and no import can be told to stop producing one of
    them, so the comparison key has to make them the same value.
    """
    assert normalize_material_name(_DIM_AS_TYPED) == normalize_material_name(_DIM_AS_EXPORTED)
    # The separator survives as a mark rather than vanishing, which is what
    # keeps "1,22" apart from "122" while still agreeing with "1.22".
    assert normalize_material_name(_DIM_AS_TYPED) == "laminagypsumblanca12mmx1·22x2·44m"


def test_normalize_keeps_a_different_sheet_size_apart() -> None:
    """Folding the separators must not fold the numbers they separate."""
    assert normalize_material_name(_DIM_AS_TYPED) != normalize_material_name(
        "Lamina gypsum blanca 12 mm x 1,20 x 2,40 m"
    )
    assert normalize_material_name(_DIM_AS_TYPED) != normalize_material_name(
        "Lamina gypsum blanca 15 mm x 1,22 x 2,44 m"
    )


def test_the_key_carries_the_unit_because_nothing_is_stripped() -> None:
    """There is no unit or qualifier stripping - the key keeps every character.

    Worth stating explicitly because the tier is called an identity match: a
    catalogue that appends its unit to the description (``"Gypsum plaster m3"``)
    is a DIFFERENT key from the bare material name and will not match exactly.
    That is a matching limit, not a bug, but it is invisible unless asserted -
    every other normalizer test here uses strings that carry no trailing unit.
    """
    assert normalize_material_name("Gypsum plaster m3") != normalize_material_name("Gypsum plaster")
    assert normalize_material_name("Gypsum plaster (pumped)") != normalize_material_name("Gypsum plaster")


def test_a_thickness_and_its_decimal_neighbour_do_not_share_a_key() -> None:
    """Deleting the separator is what made these pairs collide.

    A 1.2 mm steel stud and a 12 mm plasterboard are both stocked items, so
    while the separator was deleted find_exact_cost_item handed back the wrong
    one as an IDENTITY match: confidence 1, needs_review False, no reviewer
    ever saw it. Folding the separator to a mark keeps them apart without
    costing the agreement the tier was built for, asserted last.
    """
    assert normalize_material_name("Lamina acero 1,2 mm") != normalize_material_name("Lamina acero 12 mm")
    assert normalize_material_name("Lamina yeso 12,5 mm") != normalize_material_name("Lamina yeso 125 mm")
    assert normalize_material_name("Tubo PVC 0,5 mm") != normalize_material_name("Tubo PVC 05 mm")
    # A period and a comma are still the same separator, which is the property
    # the whole exact tier rests on.
    assert normalize_material_name("Lamina acero 1,2 mm") == normalize_material_name("Lamina acero 1.2 mm")


def test_a_thousands_separator_is_the_price_of_keeping_the_decimal_one() -> None:
    """The known cost of the fold above, recorded rather than discovered later.

    Nothing in a bare name says whether a comma separates a decimal or a
    thousand, so keeping the mark means ``1,000 kg`` and ``1000 kg`` stop being
    the same key. That is the survivable direction: a missed exact match falls
    through to the fuzzy tier and arrives priced but flagged for review, while
    the collision it replaces arrived as a settled price.
    """
    assert normalize_material_name("Cemento 1,000 kg") != normalize_material_name("Cemento 1000 kg")


def test_a_cyrillic_norm_material_keeps_its_words() -> None:
    """The reach of the fold, on real ГЭСН/ФЕР material names.

    Not a second copy of the collision test above - this measures the shape of
    the key across a whole catalogue rather than one pair. Every one of these
    used to be stripped down to the digits of its grade, or to nothing at all
    when it carried no grade, which is how two unrelated materials of the same
    grade became one key.
    """
    assert normalize_material_name("Раствор готовый кладочный цементный М100") == "растворготовыикладочныицементныим100"
    assert normalize_material_name("Кирпич керамический одинарный М150") == "кирпичкерамическииодинарныим150"
    assert normalize_material_name("Смесь бетонная тяжелого бетона В15 (М200)") == "смесьбетоннаятяжелогобетонав15м200"
    # й and ё decompose under NFKD and lose their mark, exactly as an acute
    # accent does on Latin, so a name spelt either way lands on one key.
    assert normalize_material_name("Раствор готовый") == normalize_material_name("Раствор готовыи")
    # A name with no grade number is now a key like any other, rather than the
    # empty string that could never match its own row.
    assert normalize_material_name("Песок природный для строительных работ") == "песокприродныидлястроительныхработ"


# ---------------------------------------------------------------------------
# _candidate_keys against a descriptions column that is not what it claims
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("localized", [[], ["Yeso"], "Yeso", 5, 0])
def test_candidate_keys_ignore_a_descriptions_column_that_is_not_a_mapping(localized) -> None:
    """The column is JSON, so an import can put anything in it.

    A key set is used to price a line; a non-mapping value must cost the extra
    keys, never raise on the way to the tie-break.
    """
    item = _item("AAA-001")
    item.descriptions = localized
    assert _candidate_keys(item) == {"gypsumplaster"}


def test_candidate_keys_ignore_non_string_localized_values() -> None:
    item = _item("AAA-001")
    item.descriptions = {"es": None, "de": 12, "fr": ["Platre"], "it": "Gesso"}
    assert _candidate_keys(item) == {"gypsumplaster", "gesso"}


# ---------------------------------------------------------------------------
# _tie_break: what "agrees" means on each field
# ---------------------------------------------------------------------------


def test_tie_break_compares_units_case_and_space_insensitively() -> None:
    """``m3``, ``M3`` and `` m3 `` are one unit, however the catalogue typed it."""
    padded = _item("ZZZ-999", unit=" M3 ")
    mismatched = _item("AAA-001", unit="kg")
    assert _ranked([mismatched, padded], unit="m3") == ["ZZZ-999", "AAA-001"]


def test_tie_break_treats_a_row_carrying_no_unit_as_a_mismatch() -> None:
    unitless = _item("AAA-001", unit=None)
    agreeing = _item("ZZZ-999", unit="m3")
    assert _ranked([unitless, agreeing], unit="m3") == ["ZZZ-999", "AAA-001"]


def test_region_is_matched_exactly_while_unit_is_case_folded() -> None:
    """A deliberate asymmetry, pinned so a "tidy-up" cannot flip it unseen.

    Units are free text typed by whoever built the catalogue, so they are
    folded. Region codes are canonical identifiers, so ``es_madrid`` is not
    ``ES_MADRID`` and must not be treated as the same place.
    """
    wrong_case = _item("AAA-001", unit="m3", region="es_madrid")
    exact = _item("ZZZ-999", unit="m3", region="ES_MADRID")
    assert _ranked([wrong_case, exact], unit="m3", region="ES_MADRID") == [
        "ZZZ-999",
        "AAA-001",
    ]


# ---------------------------------------------------------------------------
# The fuzzy floor: exactly at it, and one float step either side
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_fuzzy_floor_is_inclusive_at_exactly_the_score(session, monkeypatch) -> None:
    """``score < floor`` refuses; ``score == floor`` accepts.

    The floor decides whether a line gets priced at all, so the comparison's
    strictness is a behaviour, not a detail. Probing only "well above" and "well
    below" leaves ``<`` and ``<=`` indistinguishable, and swapping one for the
    other silently changes which materials come back unpriced.

    The score is injected rather than earned, for two reasons. The real matcher
    caps at 1.0 and returns exactly that for this pair, which leaves no room to
    step upward; and the property under test belongs to the comparison in
    ``resolve_material_cost_item``, not to the scorer, so pinning the value keeps
    the boundary from moving when the scorer is retuned.
    """
    row = await _seed_fuzzy_rival(session)
    score = 0.42

    async def _fake(*_args, **_kwargs):
        return [_match_result(str(row.id), score=score)]

    monkeypatch.setattr("app.modules.costs.matcher.match_cwicr_items", _fake)

    async def _resolve(floor: float):
        return await resolve_material_cost_item(session, _MATERIAL, unit="m2", min_fuzzy_score=floor)

    one_step_below = await _resolve(math.nextafter(score, 0.0))
    assert one_step_below is not None

    at_the_floor = await _resolve(score)
    assert at_the_floor is not None
    assert at_the_floor.method == COST_ITEM_FUZZY
    assert at_the_floor.confidence == D("0.42")

    one_step_above = await _resolve(math.nextafter(score, 1.0))
    assert one_step_above is None


@pytest.mark.asyncio
async def test_two_fuzzy_candidates_scoring_alike_resolve_the_same_way_every_time(
    session,
) -> None:
    """A tie in the fuzzy tier must not price the same line two ways.

    The exact tier has ``_tie_break`` and is covered above. The fuzzy tier has no
    tie-break of its own: ``resolve_material_cost_item`` takes ``matches[0]`` and
    asks nothing further, so whatever order the matcher returns IS the decision.
    Two rows carrying the same description score identically, which is the case
    that would otherwise be settled by whatever order the database felt like
    handing rows back in - the same class of instability the exact tier's
    tie-break exists to remove. The matcher documents "score desc, then code
    asc", so the lower code must win, and must keep winning.
    """
    duplicate_description = "Gypsum plaster board 12mm heavy duty"
    for code in ("MMM-500", "AAA-100", "ZZZ-900"):
        await _seed(session, code=code, description=duplicate_description, unit="m2", rate="9.00")

    query = "Gypsum plaster board 12mm insulated"
    resolved = []
    for _ in range(3):
        match = await resolve_material_cost_item(session, query, unit="m2", min_fuzzy_score=0.1)
        assert match is not None
        assert match.method == COST_ITEM_FUZZY
        resolved.append(match.item.code)

    assert resolved == ["AAA-100", "AAA-100", "AAA-100"]


@pytest.mark.asyncio
async def test_the_floor_does_not_apply_to_the_exact_tier(session) -> None:
    """An impossible floor still prices an exact match - it is not a score."""
    item = await _seed(session, code="EX-001", description="Gypsum plaster", unit="m3")
    match = await resolve_material_cost_item(session, "Gypsum plaster", unit="m3", min_fuzzy_score=2.0)
    assert match is not None
    assert match.item.id == item.id
    assert match.method == COST_ITEM_EXACT


# ---------------------------------------------------------------------------
# The tier ordering as a mechanism, not only as an outcome
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_lexical_matcher_is_never_consulted_once_an_exact_row_exists(
    session,
    monkeypatch,
) -> None:
    """Asserts the fuzzy tier does not RUN, not merely that it does not win.

    The outcome test above stays green if the two tiers are reordered and the
    exact row happens to outscore the rival anyway. This one fails the moment
    the lexical pass is reached at all, which is the property the module's
    docstring actually claims.
    """
    await _seed_exact_row(session)

    async def _explode(*_args, **_kwargs):
        raise AssertionError("the lexical matcher ran even though an exact row existed")

    monkeypatch.setattr("app.modules.costs.matcher.match_cwicr_items", _explode)

    match = await resolve_material_cost_item(session, _MATERIAL, unit="m2", min_fuzzy_score=0.1)

    assert match is not None
    assert match.method == COST_ITEM_EXACT


# ---------------------------------------------------------------------------
# A fuzzy hit that cannot be turned into a row
# ---------------------------------------------------------------------------


def _match_result(cost_item_id: str, *, score: float = 0.9) -> MatchResult:
    return MatchResult(
        cost_item_id=cost_item_id,
        code="FUZ-001",
        description="Gypsum plaster board 12mm heavy duty",
        unit="m2",
        unit_rate=9.0,
        score=score,
    )


@pytest.mark.asyncio
async def test_a_fuzzy_hit_whose_id_is_not_a_uuid_leaves_the_material_unpriced(
    session,
    monkeypatch,
) -> None:
    """The matcher's id is a plain string, so it is not guaranteed to be one.

    Without the guard this raises ``ValueError`` out of a pricing loop rather
    than skipping one material, which turns a bad catalogue row into a failed
    assembly build.
    """

    async def _fake(*_args, **_kwargs):
        return [_match_result("not-a-uuid")]

    monkeypatch.setattr("app.modules.costs.matcher.match_cwicr_items", _fake)

    assert await resolve_material_cost_item(session, _MATERIAL, unit="m2", min_fuzzy_score=0.1) is None


@pytest.mark.asyncio
async def test_a_fuzzy_hit_pointing_at_a_row_that_is_gone_leaves_it_unpriced(
    session,
    monkeypatch,
) -> None:
    """A well-formed id for a row that no longer exists must not price anything."""

    async def _fake(*_args, **_kwargs):
        return [_match_result(str(uuid.uuid4()))]

    monkeypatch.setattr("app.modules.costs.matcher.match_cwicr_items", _fake)

    assert await resolve_material_cost_item(session, _MATERIAL, unit="m2", min_fuzzy_score=0.1) is None


@pytest.mark.asyncio
async def test_a_fuzzy_match_carries_the_matchers_own_score_as_its_confidence(
    session,
    monkeypatch,
) -> None:
    """Confidence is reported, not rounded or rescaled on the way out."""
    row = await _seed_fuzzy_rival(session)

    async def _fake(*_args, **_kwargs):
        return [_match_result(str(row.id), score=0.37)]

    monkeypatch.setattr("app.modules.costs.matcher.match_cwicr_items", _fake)

    match = await resolve_material_cost_item(session, _MATERIAL, unit="m2", min_fuzzy_score=0.1)

    assert match is not None
    assert match.confidence == D("0.37")
    assert match.method == COST_ITEM_FUZZY
    assert match.needs_review is True


# ---------------------------------------------------------------------------
# A material with no comparison key is never priced by either tier
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["", "   ", "\t\n"])
async def test_a_blank_material_name_is_never_priced(session, name) -> None:
    """A blank name stops at both tiers.

    The exact tier refuses an empty comparison key up front, and the lexical
    matcher declines a whitespace-only query before it loads candidates. Covered
    through the whole resolver rather than through ``find_exact_cost_item``
    alone, because it is the fall-through between the tiers that decides whether
    money lands on the line.
    """
    await _seed_fuzzy_rival(session)

    assert await resolve_material_cost_item(session, name, unit="m2", min_fuzzy_score=0.0) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["- - -", "-", "--", "---", "/,.-"])
async def test_a_placeholder_material_name_is_never_priced(session, name) -> None:
    """A name with no comparison key is refused by the lexical tier too.

    The exact tier refuses it on its own - ``normalize_material_name('- - -')``
    is ``""``, and an empty key equals no candidate's - but the same nameless
    string used to be handed straight to the lexical matcher, which does not
    refuse it: it is not whitespace, so it gets scored. ``token_set_ratio``
    reports a full match against any description carrying a standalone hyphen,
    because the query's token set ``{'-'}`` is a subset of the candidate's.
    Measured against a single ``'Sand - washed'`` row at unit m3, ``'- - -'``
    and ``'-'`` both resolved at confidence 1.0, far above the shipped 0.30
    floor, so sand's rate landed on a nameless material at full confidence.
    ``'--'`` and ``'---'`` scored 0.2333 and 0.225 - held by the floor rather
    than by the design, which is why they are parametrized here alongside the
    ones the floor let through: the guard, not the threshold, is what holds
    them now.
    """
    await _seed(session, code="SND-001", description="Sand - washed", unit="m3", rate="18.00")

    assert await resolve_material_cost_item(session, name, unit="m3", min_fuzzy_score=0.30) is None


@pytest.mark.asyncio
@pytest.mark.xfail(
    strict=True,
    reason=(
        "'n/a' is a placeholder that carries a comparison key, so neither the "
        "keyless guard nor the exact tier holds it: normalize_material_name "
        "reduces it to 'na', a real key that simply matches nothing. It reaches "
        "the lexical matcher and scores 0.35 against 'Sand - washed' at unit m3 "
        "- above the shipped 0.30 floor - so sand's rate prices a material "
        "nobody named. Holding it needs a decision this module cannot make on "
        "its own: raising the floor is the lever the module docstring rules out "
        "(it only moves which wrong answers appear), and the alternative is a "
        "vocabulary of placeholder names, which has to be settled across the "
        "platform's locales ('n/a', 's/d', and their siblings) before it can be "
        "written down. Left standing rather than closed with a guess, because "
        "the line still costs real money: a wrong rate, flagged needs_review."
    ),
)
async def test_a_placeholder_that_carries_a_key_is_still_priced(session) -> None:
    await _seed(session, code="SND-001", description="Sand - washed", unit="m3", rate="18.00")

    assert await resolve_material_cost_item(session, "n/a", unit="m3", min_fuzzy_score=0.30) is None
