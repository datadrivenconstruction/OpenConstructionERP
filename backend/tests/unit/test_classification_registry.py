# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The classification registry answers by country, not by string shape.

The defect these tests exist for: ``PL`` resolved to DIN 276 while
``PL_WARSAW`` resolved to MasterFormat. Sixteen countries answered two
ways depending on whether a city happened to be appended, because the
city-suffix safety net in the old resolver only fired when the whole
region string missed the lookup, and a catalogue region id never missed
it - the catalogue loop had already inserted it with a default standard.

So the test that matters here is not a roster of expected answers. It is
an invariant driven from the registry and from the shipped catalogues,
which means a country added tomorrow is covered without anyone
remembering to add a case.
"""

from __future__ import annotations

import ast
import logging
import re
from pathlib import Path

import pytest

from app.core.classification_registry import (
    CLASSIFICATION_STANDARD_LABELS,
    COUNTRY_TO_STANDARD,
    DEFAULT_CLASSIFICATION_STANDARD,
    KNOWN_CLASSIFICATION_STANDARDS,
    REGION_ALIAS_TO_COUNTRY,
    classification_order,
    normalise_region,
    resolve_standard,
    standard_for_country,
)
from app.modules.costs.cwicr_v3_catalogue import CWICR_V3_CATALOGUES

# City qualifiers appended to a bare country code. Deliberately varied in
# shape - a separator that is not an underscore, a multi-word city, a
# lower-case one - because the normaliser is the only thing standing
# between these and a different answer.
_CITY_SUFFIXES = ("WARSAW", "SOMECITY", "SAO PAULO", "north-region", "Berlin")


def _head(region: str) -> str:
    """The standard a region resolves to, ignoring the rest of the order."""
    return resolve_standard(None, region).standard


# ── The invariant ────────────────────────────────────────────────────────


@pytest.mark.parametrize("country", sorted(COUNTRY_TO_STANDARD))
def test_a_city_suffix_never_changes_the_country_s_answer(country: str) -> None:
    """Every country the registry knows answers the same with a city on it.

    Driven from the registry itself, so a country added tomorrow is
    covered without anyone adding a case for it.
    """
    bare = _head(country)
    for suffix in _CITY_SUFFIXES:
        suffixed = f"{country}_{suffix}"
        assert _head(suffixed) == bare, (
            f"{suffixed!r} resolves to {_head(suffixed)!r} but {country!r} resolves to {bare!r}; "
            "one country cannot hold two standards"
        )
        assert normalise_region(suffixed) == country


@pytest.mark.parametrize(
    "catalogue",
    CWICR_V3_CATALOGUES,
    ids=[c.region for c in CWICR_V3_CATALOGUES],
)
def test_a_shipped_catalogue_region_answers_as_its_own_country(catalogue) -> None:
    """A catalogue region id and its country resolve identically.

    This is the form that was actually broken. The synthetic suffixes
    above were not: an invented ``PL_SOMECITY`` missed the old lookup and
    so reached the city-suffix net, while the real ``PL_WARSAW`` hit it
    and never did. Driving from ``CWICR_V3_CATALOGUES`` is what makes
    this red on the pre-change code.

    It also pins the four rows whose region id does not begin with their
    country - ``SV_STOCKHOLM`` is Sweden, ``ZH_CHINA`` is China,
    ``VI_HANOI`` is Vietnam and ``USA_USD`` is the United States - which
    is why resolution goes through the declared ``country_iso`` rather
    than splitting the id on its underscore.
    """
    country = catalogue.country_iso.upper()
    resolved = resolve_standard(None, catalogue.region)
    by_country = resolve_standard(None, country)

    assert normalise_region(catalogue.region) == normalise_region(country), (
        f"catalogue region {catalogue.region!r} normalises to {normalise_region(catalogue.region)!r} "
        f"but its declared country {country!r} normalises to {normalise_region(country)!r}"
    )
    assert resolved.standard == by_country.standard, (
        f"{catalogue.region!r} resolves to {resolved.standard!r} while {country!r} resolves to "
        f"{by_country.standard!r}; the same country is being classified two ways"
    )
    assert resolved.matched, (
        f"{catalogue.region!r} falls through to the default; the product ships a catalogue for "
        f"{country!r} and the registry names no standard for it"
    )


def test_the_reported_defect_stays_fixed() -> None:
    """The exact pair from the bug report, named so it cannot be lost.

    The defect was that the two spellings disagreed. What they agree on moved
    from DIN 276 to KNR when Poland got its own line coding; the agreement is
    the point.
    """
    assert _head("PL") == _head("PL_WARSAW") == "knr"


# ── Agreement and disjointness between the sources ───────────────────────


def test_every_shipped_catalogue_country_is_in_the_one_table() -> None:
    """The registry covers every country the product ships a catalogue for.

    A ratchet on a property of the registry alone: it is not an allowlist
    of countries, it is the statement that shipping a catalogue without a
    standard for its country is not a thing we do.
    """
    countries = {c.country_iso.upper() for c in CWICR_V3_CATALOGUES}
    missing = {c for c in countries if normalise_region(c) not in COUNTRY_TO_STANDARD}
    assert not missing, f"catalogues ship for {sorted(missing)} but the registry names no standard for them"


@pytest.mark.parametrize(
    "catalogue",
    CWICR_V3_CATALOGUES,
    ids=[c.region for c in CWICR_V3_CATALOGUES],
)
def test_the_catalogue_no_longer_holds_an_opinion_of_its_own(catalogue) -> None:
    """Equality between the two sources, asserted directly.

    ``default_classification_standard`` used to be a stored field and it
    disagreed with the match pipeline for Australia, India, South Africa,
    Brazil, Morocco and Tunisia. It is derived now, so this asserts a
    property rather than a synchronisation: the catalogue cannot answer
    differently because it no longer answers at all.
    """
    assert catalogue.default_classification_standard == standard_for_country(catalogue.country_iso)


def test_a_token_is_either_a_country_or_an_alias_and_never_both() -> None:
    """The two lookup tables are disjoint, so neither can shadow the other."""
    overlap = set(COUNTRY_TO_STANDARD) & set(REGION_ALIAS_TO_COUNTRY)
    assert not overlap, f"{sorted(overlap)} are keyed as both a country and an alias for another country"


def test_every_alias_points_at_a_country_the_table_knows() -> None:
    """An alias cannot resolve to a country that has no standard."""
    dangling = {a: c for a, c in REGION_ALIAS_TO_COUNTRY.items() if c not in COUNTRY_TO_STANDARD}
    assert not dangling, f"aliases point at countries with no entry: {dangling}"


def test_every_standard_the_table_names_can_be_rendered() -> None:
    """The section-path renderer indexes the labels, so a gap is a crash."""
    named = set(COUNTRY_TO_STANDARD.values()) | set(KNOWN_CLASSIFICATION_STANDARDS)
    unlabelled = named - set(CLASSIFICATION_STANDARD_LABELS)
    assert not unlabelled, f"{sorted(unlabelled)} have no display label; section-path rendering would KeyError"


def test_every_region_the_product_ships_resolves_to_a_country() -> None:
    """Driven from the shipped demo and seed data, not from a list here.

    The demo projects do not all speak in ISO codes. Three of them carry
    a long-form region - ``France``, ``Middle East``, ``United States`` -
    and ``France`` used to resolve to nothing at all, so the French demo
    rendered its section paths against DIN 276. A demo pack added
    tomorrow with a region nobody taught the registry fails here rather
    than shipping a quietly wrong standard.
    """
    app_root = Path(__file__).resolve().parents[2] / "app"
    declaration = re.compile(r"\bregion=[\"']([^\"']+)[\"']")
    sources = [app_root / "core" / "demo_projects.py", *sorted((app_root / "core" / "demo_packs").glob("*.py"))]
    sources += sorted((app_root / "scripts").glob("seed_*.py"))

    shipped: set[str] = set()
    for path in sources:
        if path.exists():
            shipped.update(declaration.findall(path.read_text(encoding="utf-8", errors="replace")))

    assert shipped, "found no shipped region declarations; the scan has lost its target"
    unresolved = sorted(r for r in shipped if normalise_region(r) is None)
    assert not unresolved, f"the product ships projects in {unresolved} and the registry resolves none of them"


def test_the_registry_is_the_only_country_to_standard_table_in_the_backend() -> None:
    """No module outside the registry defines a region to standard map.

    Structural rather than an allowlist of file paths, so it does not
    break the next time somebody adds a legitimate module. It looks for
    the shape the copies all had: a dict literal keyed by alpha-2 country
    codes whose values are classification-standard slugs.
    """
    slugs = set(CLASSIFICATION_STANDARD_LABELS)
    registry = Path(__file__).resolve().parents[2] / "app" / "core" / "classification_registry.py"
    offenders: list[str] = []

    for path in sorted((registry.parents[1]).rglob("*.py")):
        if path == registry:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (SyntaxError, UnicodeDecodeError):  # pragma: no cover - defensive
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Dict):
                continue
            keys = [k.value for k in node.keys if isinstance(k, ast.Constant) and isinstance(k.value, str)]
            values = [v.value for v in node.values if isinstance(v, ast.Constant) and isinstance(v.value, str)]
            iso_keys = [k for k in keys if len(k) == 2 and k.isalpha() and k.isupper()]
            slug_values = [v for v in values if v in slugs]
            if len(iso_keys) >= 5 and len(slug_values) >= 3:
                offenders.append(f"{path.name}:{node.lineno}")

    assert not offenders, (
        "a second country to classification-standard table has appeared at "
        f"{offenders}; the registry is meant to be the only one"
    )


# ── The unresolvable case ────────────────────────────────────────────────


def test_an_empty_region_is_reported_as_a_default_not_as_a_match() -> None:
    """The ProjectCreate default lands here, so it must be legible."""
    resolved = resolve_standard("", "")
    assert resolved.standard == DEFAULT_CLASSIFICATION_STANDARD
    assert resolved.source == "default"
    assert resolved.matched is False
    assert resolved.country is None
    assert resolve_standard(None, None).source == "default"


def test_an_unresolvable_region_is_reported_as_a_default() -> None:
    """A region that was filled in and still matched nothing."""
    resolved = resolve_standard(None, "ZZ_FAKE_REGION")
    assert resolved.standard == DEFAULT_CLASSIFICATION_STANDARD
    assert resolved.matched is False


def test_a_default_is_logged_rather_than_swallowed(caplog: pytest.LogCaptureFixture) -> None:
    """Silently defaulting is what made the wrong standard invisible.

    A filled-in region that resolves to nothing is a data problem and
    logs at warning; a blank one is the schema default and logs at info.
    Both are deduplicated per process, so the fixture clears the record
    of what has already been reported.
    """
    from app.core import classification_registry

    classification_registry._reported_defaults.clear()
    with caplog.at_level(logging.INFO, logger=classification_registry.__name__):
        resolve_standard(None, "NOWHERE_AT_ALL")
        resolve_standard(None, "")
    classification_registry._reported_defaults.clear()

    levels = {record.levelno for record in caplog.records}
    assert logging.WARNING in levels, "an unresolvable region defaulted with no warning anywhere"
    assert logging.INFO in levels, "a blank region defaulted with no record at all"
    assert any("NOWHERE_AT_ALL" in record.getMessage() for record in caplog.records), (
        "the warning does not name the region that failed to resolve"
    )


def test_a_match_is_not_logged_as_a_default(caplog: pytest.LogCaptureFixture) -> None:
    """The negative half: a resolvable region must stay quiet."""
    from app.core import classification_registry

    classification_registry._reported_defaults.clear()
    with caplog.at_level(logging.INFO, logger=classification_registry.__name__):
        assert resolve_standard(None, "PL_WARSAW").matched
    classification_registry._reported_defaults.clear()

    assert not caplog.records, f"a matched region logged a fall-through: {[r.getMessage() for r in caplog.records]}"


# ── Explicit choice and ordering ─────────────────────────────────────────


def test_an_explicit_standard_beats_the_region() -> None:
    """A UK firm working in the US keeps its own template."""
    resolved = resolve_standard("nrm", "US")
    assert resolved.standard == "nrm"
    assert resolved.source == "explicit"


def test_an_unrenderable_explicit_standard_falls_through_to_the_region() -> None:
    """A standard the product cannot render is not an answer."""
    assert resolve_standard("something-we-do-not-render", "US").standard == "masterformat"


def test_the_order_covers_every_standard_exactly_once() -> None:
    """The tail is what lets a section path resolve on a partial CostItem."""
    order = classification_order(None, "DACH")
    assert order[0] == "din276"
    assert sorted(order) == sorted(set(KNOWN_CLASSIFICATION_STANDARDS))
    assert {"din276", "masterformat", "nrm"}.issubset(set(order))


# ── Negative control ─────────────────────────────────────────────────────


def test_the_invariant_is_actually_watching_the_normaliser(monkeypatch: pytest.MonkeyPatch) -> None:
    """Break the mechanism at the one point unique to it, expect red.

    The fix is "normalise once, then look up once". Removing the
    normalisation - resolving a region only when it is already exactly a
    country code - is a break that nothing else in this module could
    produce. If the catalogue invariant above can still pass under it,
    that invariant is passing for some other reason and proves nothing.

    ``resolve_standard`` looks ``normalise_region`` up in its own module
    namespace at call time, so patching the attribute is enough.
    """
    from app.core import classification_registry

    def _no_normalisation(raw: str | None) -> str | None:
        token = (raw or "").upper().strip()
        return token if token in COUNTRY_TO_STANDARD else None

    monkeypatch.setattr(classification_registry, "normalise_region", _no_normalisation)
    classification_registry._reported_defaults.clear()

    broken = [
        c.region
        for c in CWICR_V3_CATALOGUES
        if classification_registry.resolve_standard(None, c.region).standard
        != classification_registry.resolve_standard(None, c.country_iso.upper()).standard
    ]
    classification_registry._reported_defaults.clear()

    assert broken, (
        "removing the normaliser changed no catalogue region's answer, so the invariant "
        "above is not testing the normaliser and would stay green through the original defect"
    )
