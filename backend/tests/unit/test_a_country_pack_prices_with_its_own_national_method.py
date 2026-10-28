# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠A pack that sells a country must price with that country's method.

The platform already knows how to price a bill nationally. ``markup_templates``
states the national markup stacks, ``REGION_BY_COUNTRY`` says which country
reads which stack, and the methodology catalogue rewrites a flat country
template from that stack so a country cannot be priced two ways by two engines.
That machinery works. What nothing checked is whether a pack that sells a
country actually asks for it.

Two packs did not. ``brazil-sinapi`` shipped the SINAPI cost base and the NBR
rule sets and left ``default_methodology`` empty, and ``saudi-vision2030``
shipped the Saudi Building Code and the Aramco approval stack and did the same.
An empty field is not an absent one: the manifest documents it as "keeps the
platform flat international default", so both packs priced their bills with a
method belonging to no market while advertising a national one all around it.
The Brazilian and Saudi templates existed the whole time and were derived from
the BR and GULF stacks; nothing was naming them.

That defect is invisible from every side. The pack applies cleanly, the plan in
``partner_pack.apply`` reports no warning because there is no unknown slug to
warn about, the project is created, and the bill is priced. A reader comparing
the pack against the catalogue would have to already suspect the field to look
at it.

Why the check is shaped in two tiers. The strict tier fires only where a
national method demonstrably exists, which is the one condition that makes
silence about a national method wrong. The markup table's own header is
explicit that a country's absence from ``REGION_BY_COUNTRY`` is the honest
answer that we ship the neutral international method for that market, so
demanding a NATIONAL method from every pack would convict packs for telling
the truth and would be red from birth.

The second tier exists because the first one let three packs through while
they were doing something plainly wrong. Canada, New Zealand and South Africa
have no national stack, so nothing above could fire on them, and all three
shipped no methodology at all. That is not the same as having no national
convention to name: the catalogue has a template for each of those countries,
carrying the right currency and the right consumption-tax rate and saying of
itself that it is the neutral method rather than a national convention. Naming
it is strictly better than the flat international default, which carries
neither. So the weaker tier asks only this: a pack that sells a country the
catalogue has any template for must name that template. It upgrades itself for
free, because the moment the markup table states that country's stack the
template is rewritten from it and the pack is already pointing at the result.

Between them the tiers cover every pack in the tree that names a market. What
neither fires on is a pack that names no country at all, which is the sector
packs and the one industry pack, correctly.

The population is printed beside the verdict on purpose. A gate over pack
manifests that silently found none would pass, and this is a file that could
easily find none: it reads the source tree, and an installed layout has the
manifests somewhere else entirely.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

import pytest

from app.modules.boq.markup_templates import REGION_BY_COUNTRY
from app.modules.methodology.templates import TEMPLATES_BY_SLUG

# backend/tests/unit/<this file> -> repo root.
_REPO_ROOT = Path(__file__).resolve().parents[3]
_PACKS_DIR = _REPO_ROOT / "packs"

# The cross-region marker the sector packs carry instead of a real ISO code.
# ``renewables-epc`` and ``modular-prefab`` are industry packs that name no
# market, so they have no national method to be missing.
_CROSS_REGION = "XX"


def _manifest_paths() -> list[Path]:
    """Every pack manifest in the source tree, sorted for stable test ids."""
    if not _PACKS_DIR.is_dir():
        return []
    found: list[Path] = []
    for pack_dir in sorted(d for d in _PACKS_DIR.iterdir() if d.is_dir()):
        if any(pack_dir.rglob("DEPRECATED.txt")):
            continue
        for pkg_dir in sorted((pack_dir / "src").glob("openconstructionerp_*")):
            candidate = pkg_dir / "manifest.py"
            if candidate.is_file():
                found.append(candidate)
                break
    return found


def _manifest_call(path: Path) -> ast.Call:
    """The ``PartnerPackManifest(...)`` call node, without executing the module.

    Parsed rather than imported for the same reason the packaging test parses:
    reading two keywords out of twenty manifests should not run twenty modules,
    and this file has to stay runnable with no database behind it.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "PartnerPackManifest":
            return node
    raise AssertionError(f"{path} contains no PartnerPackManifest(...) call")


def _keyword(call: ast.Call, name: str) -> Any:
    """Literal value of one manifest keyword, or ``None`` when it is absent.

    Anything that is not a literal raises rather than being guessed at. Both
    keywords this file reads decide a verdict, and a reader that quietly
    returned ``None`` for an expression it could not evaluate would report a
    pack as declaring nothing when it declares something computed.
    """
    for keyword in call.keywords:
        if keyword.arg != name:
            continue
        try:
            return ast.literal_eval(keyword.value)
        except ValueError as exc:  # pragma: no cover - guards a future manifest
            raise AssertionError(
                f"cannot evaluate {name} in this manifest ({ast.dump(keyword.value)[:120]}). "
                f"Extend the reader rather than letting it read as absent."
            ) from exc
    return None


def _metadata_country(call: ast.Call) -> str:
    """The ISO-2 code in ``metadata["country"]``, or ``""`` when there is none.

    Only that one key is evaluated, deliberately. At least one manifest builds
    a metadata value from a module-level constant, so ``literal_eval`` on the
    whole dict raises on a pack that is perfectly well formed. Reading the one
    key this file needs keeps a neighbouring non-literal from deciding whether
    a pack gets checked.
    """
    for keyword in call.keywords:
        if keyword.arg != "metadata" or not isinstance(keyword.value, ast.Dict):
            continue
        for key, value in zip(keyword.value.keys, keyword.value.values, strict=True):
            if isinstance(key, ast.Constant) and key.value == "country" and isinstance(value, ast.Constant):
                return str(value.value or "").strip().upper()
    return ""


def _packs() -> list[tuple[str, str, str | None]]:
    """``(slug, country, declared methodology)`` for every pack in the tree."""
    rows: list[tuple[str, str, str | None]] = []
    for path in _manifest_paths():
        call = _manifest_call(path)
        slug = _keyword(call, "slug") or path.parent.name
        rows.append((str(slug), _metadata_country(call), _keyword(call, "default_methodology")))
    return rows


_PACK_ROWS = _packs()

# Packs that sell a market the markup table states a national method for. These
# are the only ones the main assertion can fire on, and the id carries the
# country so a failure names the market rather than a directory.
_NATIONAL = [row for row in _PACK_ROWS if row[1] and row[1] != _CROSS_REGION and row[1] in REGION_BY_COUNTRY]


def test_the_pack_tree_was_actually_found() -> None:
    """Without this, an empty tree passes every assertion below in silence."""
    assert len(_PACK_ROWS) >= 15, (
        f"only {len(_PACK_ROWS)} pack manifests found under {_PACKS_DIR}. This file reads the "
        f"source tree, so an installed layout finds none and every check below goes vacuous."
    )


def test_some_pack_sells_a_country_with_a_national_method() -> None:
    """The population the main assertion runs over must not be empty either.

    The filter is two joins deep - a pack's country against the region map -
    and either side breaking would leave a green file that checks nothing.
    """
    assert len(_NATIONAL) >= 8, (
        f"only {len(_NATIONAL)} of {len(_PACK_ROWS)} packs name a country with a national markup "
        f"stack. Either REGION_BY_COUNTRY shrank or the manifests stopped declaring metadata.country."
    )


@pytest.mark.parametrize(("slug", "country", "declared"), _NATIONAL, ids=[f"{r[0]}-{r[1]}" for r in _NATIONAL])
def test_a_pack_declares_the_national_methodology_its_country_has(
    slug: str, country: str, declared: str | None
) -> None:
    """A pack whose market has a national stack must ask for it by name."""
    region = REGION_BY_COUNTRY[country]
    expected = sorted(
        template_slug
        for template_slug, template in TEMPLATES_BY_SLUG.items()
        if str(template.get("country_code") or "").upper() == country and template.get("derived_from_region") == region
    )
    if not expected:
        pytest.skip(f"{country} has the {region} stack but no methodology template derives from it")

    assert declared, (
        f"{slug} sells {country}, whose national method the catalogue already builds from the "
        f"{region} markup stack as {expected}, and declares no default_methodology. That is not "
        f"the same as declaring nothing is known: an empty field puts every project created under "
        f"this pack on the flat international default, so the pack ships a national cost base and "
        f"national rules and then prices the bill with a method belonging to no market."
    )
    assert declared in expected, (
        f"{slug} sells {country} and declares methodology {declared!r}, which is not one of the "
        f"templates built for {country} from the {region} stack ({expected}). A methodology from "
        f"another market prices this pack's bills with another market's cascade."
    )


@pytest.mark.parametrize(
    ("slug", "declared"),
    [(row[0], row[2]) for row in _PACK_ROWS if row[2]],
    ids=[row[0] for row in _PACK_ROWS if row[2]],
)
def test_a_declared_methodology_exists_in_the_catalogue(slug: str, declared: str) -> None:
    """An unknown slug is a warning at apply time, which nobody reads.

    ``partner_pack.apply`` validates this field against the live catalogue and
    reports a miss as a warning rather than an error, deliberately, so that a
    pack built against a newer core still applies. That is right at apply time
    and useless here: a typo would ship, the warning would scroll past in the
    preview panel, and the project would quietly get the flat default.
    """
    assert declared in TEMPLATES_BY_SLUG, (
        f"{slug} declares default_methodology={declared!r}, which is not in the methodology "
        f"catalogue. Applying the pack reports this as a warning and carries on, so the only "
        f"visible symptom is a bill priced with the flat international default."
    )


# Packs that sell a market the catalogue has a template for but the markup
# table states no national stack for. The strict assertion above cannot fire on
# these, and before the second tier existed nothing else did either.
_NEUTRAL_TIER = [
    row
    for row in _PACK_ROWS
    if row[1]
    and row[1] != _CROSS_REGION
    and row[1] not in REGION_BY_COUNTRY
    and any(str(t.get("country_code") or "").upper() == row[1] for t in TEMPLATES_BY_SLUG.values())
]


def test_every_pack_that_names_a_market_is_checked_by_one_tier_or_the_other() -> None:
    """The two populations together, because either alone will move.

    A floor on the second tier alone would be wrong in the good direction: as
    the markup table gains national stacks, packs move OUT of this tier and
    into the strict one above, and a tier that legitimately empties would read
    as a broken gate. What must not shrink is the sum, which is the number of
    packs naming a market the catalogue can serve at all.
    """
    covered = len(_NATIONAL) + len(_NEUTRAL_TIER)
    print(
        f"{len(_NATIONAL)} packs in the national tier, {len(_NEUTRAL_TIER)} in the neutral tier, {len(_PACK_ROWS)} packs total"
    )
    assert covered >= 15, (
        f"only {covered} of {len(_PACK_ROWS)} packs are checked by either tier. Either the packs "
        f"stopped declaring metadata.country or the methodology catalogue stopped covering their "
        f"markets, and in both cases most of this file has gone vacuous."
    )


@pytest.mark.parametrize(
    ("slug", "country", "declared"),
    _NEUTRAL_TIER,
    ids=[f"{r[0]}-{r[1]}" for r in _NEUTRAL_TIER],
)
def test_a_pack_names_its_own_countrys_template_even_when_it_is_the_neutral_one(
    slug: str, country: str, declared: str | None
) -> None:
    """A country pack must point at its own country, national stack or not."""
    expected = sorted(
        template_slug
        for template_slug, template in TEMPLATES_BY_SLUG.items()
        if str(template.get("country_code") or "").upper() == country
    )
    assert declared, (
        f"{slug} sells {country} and declares no default_methodology, so every project created "
        f"under it opens on the flat international default. The catalogue has {expected} for "
        f"{country}, carrying that country's currency and consumption-tax rate. That template is "
        f"currently the neutral method rather than a national convention, and naming it is still "
        f"strictly better than a method that carries no country at all."
    )
    assert declared in expected, (
        f"{slug} sells {country} and declares methodology {declared!r}, which belongs to another "
        f"market. The catalogue's templates for {country} are {expected}."
    )
