# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Installing a country pack has to leave the workspace knowing which country.

A project created while a country pack is active inherited the pack's
estimating methodology and nothing else. Everything else in the product that
is country-specific reads ``Project.country_code``: the markup region a bill is
seeded with, the CPM working calendar, the compliance-pack resolver and the
measurement system. All four answer "no opinion" when that column is unset. So
installing the Hungarian pack fitted out the cascade and left every one of them
saying nothing was known about the market, on a workspace that had just been
told which market it was for.

The fix is one line of intent: when a country pack is active and the person
creating the project named no country, the pack's country is the answer. An
explicit choice always wins, and this only ever fills a blank.

Three things have to hold together for that to be safe, and this file gates
each of them:

* the pack has to state a market unambiguously, which is what
  ``market_country_code`` is for, including saying ``None`` clearly for the
  packs that name no country;
* the fill must never overwrite a country the user chose;
* the country it fills in must actually reach the thing this was for, which is
  the markup region the bill is seeded with.

The last one is the point of the whole change and the easiest to lose: a pack
could set a country that no national stack covers, and the bill would still be
priced with the neutral method while every check above passed.
"""

from __future__ import annotations

import ast
import inspect
import textwrap

import pytest

from app.core.partner_pack.manifest import PartnerPackManifest
from app.modules.boq.markup_templates import region_key_for_country

#: Packs whose market the user asked to be worked through in depth. Named
#: individually because a population floor stays green while any one of them
#: quietly stops declaring a country.
PRIORITY_PACK_COUNTRIES = ("HU", "CN", "GB", "US", "DE", "ES", "IT", "RU", "BR")


def _manifest(**overrides: object) -> PartnerPackManifest:
    """A minimal valid manifest, with only the fields under test varied."""
    fields: dict[str, object] = {
        "slug": "test-pack",
        "partner_name": "Test partner",
    }
    fields.update(overrides)
    return PartnerPackManifest(**fields)  # type: ignore[arg-type]


def test_a_country_pack_states_its_market() -> None:
    """The ordinary case, plus the normalisation the column does not do."""
    assert _manifest(metadata={"country": "HU"}).market_country_code == "HU"
    assert _manifest(metadata={"country": "hu"}).market_country_code == "HU"
    assert _manifest(metadata={"country": " hu "}).market_country_code == "HU"


@pytest.mark.parametrize(
    ("country", "why"),
    [
        (None, "a partner pack names no market at all"),
        ("", "an empty string is not a country"),
        ("   ", "nor is whitespace"),
        ("XX", "the cross-region marker means explicitly not one country"),
        ("xx", "and it means that in either case"),
        ("USA", "alpha-3 is not the column's alphabet"),
        ("U", "one letter is not a country code"),
        ("1X", "and neither is a digit"),
    ],
)
def test_a_pack_that_names_no_single_market_says_so(country: object, why: str) -> None:
    """Every one of these must be None, and for the same reason.

    They are not the same mistake, but they carry the same information: this
    pack does not name one country. Returning a plausible-looking value for any
    of them would put a country on a project that nobody chose and no pack
    claimed, which is the failure the nullable column exists to prevent.
    """
    metadata = {} if country is None else {"country": country}
    assert _manifest(metadata=metadata).market_country_code is None, why


def test_a_pack_with_no_metadata_at_all_says_so() -> None:
    """The default manifest, which is what a partner pack usually is."""
    assert _manifest().market_country_code is None


def _create_source() -> str:
    """The project-creation method's source, from the live function object."""
    from app.modules.projects.service import ProjectService

    return inspect.getsource(ProjectService.create_project)


def _country_assignment_guards() -> list[str]:
    """Every ``if`` condition that stands between the method and the write.

    Read from source rather than exercised through the ORM because the guard is
    the whole safety property, and a test that creates one project proves it
    for one project.

    The whole chain rather than the nearest branch, and that detail is what
    makes this file honest. The assignment sits several branches deep - inside
    the pack lookup, inside the pack-is-active check, inside the fill guard -
    and picking any single one of those gives an answer that depends on how the
    code happens to be nested rather than on whether the caller's choice is
    respected. Collecting them all lets the assertion ask the real question:
    somewhere on the way in, does anything consult what the caller asked for.

    The statement is found by what it *reads* - the pack's
    ``market_country_code`` - rather than by where it lands. It used to be
    found by its target, ``project.country_code``, and that stopped being the
    target when the country was moved ahead of the compliance-pack resolution:
    the market is now settled into a local that the ``Project`` constructor is
    given, because resolving the pack from a country the method had not decided
    yet is what made a Hungarian project enforce the cross-market baseline.
    Keying on the target would have made this gate red for a change that
    strengthened exactly the property it guards, and keying on the read asks
    the same question of either shape.

    Finding no assignment at all is a failure rather than a skip: it means the
    inheritance is gone, or moved somewhere this file no longer watches.
    """
    tree = ast.parse(textwrap.dedent(_create_source()))
    parents: dict[ast.AST, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[child] = node

    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if "market_country_code" not in ast.unparse(node.value):
            continue
        conditions: list[str] = []
        walker: ast.AST | None = parents.get(node)
        while walker is not None:
            if isinstance(walker, ast.If):
                conditions.append(ast.unparse(walker.test))
            walker = parents.get(walker)
        return conditions

    raise AssertionError(
        "no statement in ProjectService.create_project reads the active pack's "
        "market_country_code. Either the pack inheritance is gone, or it moved somewhere this "
        "gate no longer watches."
    )


def test_the_pack_country_never_overwrites_a_chosen_one() -> None:
    """The fill has to be guarded on the creator having named nothing.

    This is the assertion that matters most. An unguarded version of this
    change would silently relabel the market of every project created while a
    pack is active, including the ones whose owner deliberately picked a
    different country, and the symptom would be a bill priced for the wrong
    country with the right-looking pack installed.
    """
    conditions = _country_assignment_guards()
    assert conditions, (
        "project.country_code is assigned from the pack unconditionally, so every project created "
        "while a pack is active has its market relabelled."
    )
    consulted = [c for c in conditions if "data.country_code" in c]
    assert consulted, (
        f"project.country_code is assigned under the conditions {conditions}, none of which "
        "consults what the caller asked for. The pack must only ever fill a blank."
    )
    assert any(c.strip().startswith("not ") for c in consulted), (
        f"the guards that mention the caller's country are {consulted}. The fill has to happen only "
        "when the caller named NO country; as written it may be filling in over a choice."
    )


def test_the_service_asks_the_pack_rather_than_reading_metadata_itself() -> None:
    """The market has to come from the one place that decides what a market is.

    A copy of the ``metadata["country"]`` reading here would drift from the
    property the moment either learns something the other does not - most
    obviously the ``XX`` marker, which reads like a country code and means the
    opposite of one, and which a hand-rolled copy is exactly the thing to miss.
    """
    source = _create_source()
    assert "market_country_code" in source, (
        "ProjectService.create_project no longer asks the manifest for its market. If it is reading "
        "metadata['country'] directly, it owns a second definition of what counts as a country."
    )


def test_the_inherited_country_is_recorded_as_inherited() -> None:
    """A country the product filled in is not a country the user typed.

    The whole point of making the column nullable was that those two stop being
    the same row. Writing the pack's country into it without a note would put
    the ambiguity straight back, one layer up.
    """
    source = _create_source()
    assert "country_from_pack" in source, (
        "the pack's country is written to the column without recording that it came from the pack. "
        "That is the same conflation the nullable column was introduced to end."
    )


@pytest.mark.parametrize("country", PRIORITY_PACK_COUNTRIES)
def test_an_inherited_country_reaches_a_national_markup_stack(country: str) -> None:
    """The end of the chain, which is what the change was for.

    Pack states a market, project inherits it, bill is seeded from it. If the
    last hop lands on DEFAULT the first two are decoration: the workspace would
    carry a national methodology, a national cost base and national rules, and
    still quote the bill with the neutral international stack.
    """
    region = region_key_for_country(country)
    assert region != "DEFAULT", (
        f"a project inheriting {country} from its pack is still seeded with the neutral "
        f"international markup stack, so installing that pack does not change what the bill costs."
    )


def test_the_shipped_packs_still_state_their_markets() -> None:
    """Read the real manifests, not constructed ones, and print the population.

    Everything above is exercised on manifests this file builds, which proves
    the property and proves nothing about what we ship. This walks the packs
    themselves.
    """
    from app.core.partner_pack.discovery import discover_packs

    packs = discover_packs()
    with_market = [p for p in packs if p.market_country_code]
    print(f"{len(with_market)} of {len(packs)} discovered packs name a single market")
    assert len(packs) >= 15, (
        f"only {len(packs)} packs were discovered. This test reads the installed distributions, so "
        f"a tree that has not been installed finds few and every count here goes vacuous."
    )
    assert len(with_market) >= 10, (
        f"only {len(with_market)} of {len(packs)} packs name a market. A country pack that stops "
        f"declaring metadata.country stops filling in the country, silently."
    )
    for pack in with_market:
        code = pack.market_country_code
        assert code is not None and code.isalpha() and len(code) == 2 and code.isupper(), (
            f"pack {pack.slug} reports market_country_code={code!r}, which is not a normalised alpha-2"
        )
