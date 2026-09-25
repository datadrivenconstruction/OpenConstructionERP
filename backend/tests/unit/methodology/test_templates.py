# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Unit tests for the built-in methodology templates and the spec builder.

Covers the PURE parts of :mod:`app.modules.methodology.templates`:

* Catalogue invariants: the expected slugs are present (international default,
  seven popular countries, Uzbekistan, Railway industry), every template is
  internally consistent, and slugs are unique.
* ``build_cascade_spec`` / ``build_cascade_spec_from_template``: every built-in
  template builds into a valid :class:`CascadeSpec` that the pure engine
  accepts, and the produced spec carries the template's currency / decimals /
  composites / steps faithfully.
* Builder error handling: malformed composites / steps raise ``TemplateError``.

These tests import only the pure ``templates`` and ``cascade`` modules (stdlib +
dataclasses), so they run identically on local Python 3.11 and in CI.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

import pytest

from app.modules.methodology import templates as t
from app.modules.methodology.cascade import CascadeSpec, compute_cascade

# The seven popular-country slugs migrated from the hardcoded markup tradition.
_COUNTRY_SLUGS = {
    "germany",
    "united_kingdom",
    "united_states",
    "france",
    "united_arab_emirates",
    "india",
    "australia",
}
# Broader international coverage added on top of the original seven. Pinning
# these keeps the catalogue from silently regressing on reach.
_EXTRA_COUNTRY_SLUGS = {
    "turkey",
    "portugal",
    "belgium",
    "ireland",
    "denmark",
    "finland",
    "greece",
    "czechia",
    "romania",
    "hungary",
    "ukraine",
    "qatar",
    "kuwait",
    "egypt",
    "israel",
    "nigeria",
    "kenya",
    "morocco",
    "indonesia",
    "vietnam",
    "malaysia",
    "thailand",
    "philippines",
    "new_zealand",
    "argentina",
    "chile",
    "colombia",
    "peru",
}
_EXPECTED_SLUGS = (
    _COUNTRY_SLUGS
    | _EXTRA_COUNTRY_SLUGS
    | {
        "international",
        "uzbekistan",
        "mexico",
        "railway_infrastructure",
    }
)


# ── Catalogue invariants ─────────────────────────────────────────────────


def test_catalogue_contains_expected_slugs() -> None:
    slugs = {tpl["slug"] for tpl in t.list_templates()}
    assert slugs >= _EXPECTED_SLUGS


def test_international_is_first_and_default_slug() -> None:
    assert t.INTERNATIONAL_SLUG == "international"
    assert t.list_templates()[0]["slug"] == "international"


def test_slugs_are_unique() -> None:
    slugs = [tpl["slug"] for tpl in t.list_templates()]
    assert len(slugs) == len(set(slugs))


def test_templates_by_slug_round_trips() -> None:
    for tpl in t.list_templates():
        assert t.get_template(tpl["slug"]) is tpl


def test_get_template_unknown_raises() -> None:
    with pytest.raises(t.TemplateError):
        t.get_template("atlantis")


@pytest.mark.parametrize("tpl", t.list_templates(), ids=lambda x: x["slug"])
def test_template_is_internally_consistent(tpl: dict) -> None:
    """Each template has the required keys and structurally valid fields."""
    for key in (
        "slug",
        "name",
        "currency",
        "decimals",
        "hierarchy_levels",
        "dimensions",
        "base_mapping",
        "composites",
        "cascade_steps",
    ):
        assert key in tpl, f"{tpl.get('slug')!r} missing {key!r}"

    assert isinstance(tpl["decimals"], int) and tpl["decimals"] >= 0

    # Hierarchy levels are ordered dicts with key/label.
    for lvl in tpl["hierarchy_levels"]:
        assert "key" in lvl and "label" in lvl

    # Every composite references only declared leaf base tokens.
    base_tokens = set(tpl["base_mapping"].keys())
    for comp_name, members in tpl["composites"].items():
        assert comp_name not in base_tokens, "composite collides with a base"
        for member in members:
            assert member in base_tokens, f"{tpl['slug']}: composite {comp_name} references unknown base {member}"

    # Every step base token is a leaf base, a composite, or an earlier step.
    legal: set[str] = set(base_tokens) | set(tpl["composites"].keys())
    for step in tpl["cascade_steps"]:
        for field in ("key", "kind", "base"):
            assert field in step
        for token in step["base"]:
            assert token in legal, f"{tpl['slug']}: step {step['key']} references unknown token {token}"
        legal.add(step["key"])  # later steps may reference this one


def test_no_emdash_in_template_text() -> None:
    """No em-dash or en-dash in any user-facing template string."""
    for tpl in t.list_templates():
        blob = repr(tpl)
        assert "—" not in blob, f"em-dash in template {tpl['slug']}"
        assert "–" not in blob, f"en-dash in template {tpl['slug']}"


def test_all_template_copy_is_ascii() -> None:
    """Every line of template COPY is plain ASCII: no smart quotes or accents.

    Copy means the English prose a reader sees around the numbers, which is what
    this guard was written for and where a pasted smart quote or a stray accent
    is always a mistake.

    Step labels are excluded and that is deliberate. A template derived from the
    regional markup table carries that table's own line names, so Germany reads
    Baustellengemeinkosten and Japan reads the Japanese term for common
    temporary works. Rendering those in English here would be a second copy of a
    name the canonical table already states, which is the exact duplication the
    derivation removes. The next test pins that the exception is only ever used
    by derived templates.
    """
    copy_fields = ("slug", "name", "description", "currency", "country_code", "industry")
    for tpl in t.list_templates():
        for field in copy_fields:
            value = tpl.get(field)
            if isinstance(value, str):
                assert value.isascii(), f"non-ASCII copy in template {tpl['slug']} field {field}: {value!r}"
        for level in tpl["hierarchy_levels"]:
            assert str(level["label"]).isascii(), f"non-ASCII hierarchy label in {tpl['slug']}"


def test_only_a_derived_template_carries_a_national_step_label() -> None:
    """A hand-written template writes its labels in English. A derived one does not.

    The national terms enter the catalogue through exactly one door, the
    regional markup table, and a label that arrives any other way is somebody
    typing a foreign word into a literal by hand. That is worth catching,
    because a hand-typed national term is a second spelling of a name the table
    already owns.

    Note for whoever reads this after a PDF looks wrong: the bundled DejaVu
    faces cover Latin, Greek and Cyrillic but not CJK, so a Japanese, Chinese or
    Korean label prints blank. That is not new here. A bill seeded for those
    markets has carried the same names for as long as the regional table has
    existed and its exporter has the same gap.
    """
    for tpl in t.list_templates():
        for step in tpl["cascade_steps"]:
            if str(step["label"]).isascii():
                continue
            assert tpl.get("derived_from_region"), (
                f"{tpl['slug']}: step {step['key']} has a non-ASCII label {step['label']!r} "
                f"but is not derived from the regional markup table"
            )


@pytest.mark.parametrize("tpl", t.list_templates(), ids=lambda x: x["slug"])
def test_template_has_all_catalogue_keys(tpl: dict) -> None:
    """Every template carries the full catalogue schema, not just the core keys."""
    for key in (
        "slug",
        "name",
        "description",
        "country_code",
        "industry",
        "currency",
        "decimals",
        "hierarchy_levels",
        "dimensions",
        "column_preset",
        "base_mapping",
        "composites",
        "cascade_steps",
        "vat_rate",
    ):
        assert key in tpl, f"{tpl.get('slug')!r} missing {key!r}"


@pytest.mark.parametrize("tpl", t.list_templates(), ids=lambda x: x["slug"])
def test_country_code_format(tpl: dict) -> None:
    """country_code is either None or an ISO 3166-1 alpha-2 upper-case code."""
    code = tpl["country_code"]
    assert code is None or (isinstance(code, str) and re.fullmatch(r"[A-Z]{2}", code)), (
        f"{tpl['slug']}: bad country_code {code!r}"
    )


@pytest.mark.parametrize("tpl", t.list_templates(), ids=lambda x: x["slug"])
def test_currency_format(tpl: dict) -> None:
    """currency is blank (country-neutral) or an ISO 4217 upper-case code."""
    cur = tpl["currency"]
    assert isinstance(cur, str)
    assert cur == "" or re.fullmatch(r"[A-Z]{3}", cur), f"{tpl['slug']}: bad currency {cur!r}"


@pytest.mark.parametrize("tpl", t.list_templates(), ids=lambda x: x["slug"])
def test_vat_rate_is_none_or_decimal_string(tpl: dict) -> None:
    """vat_rate is None or a Decimal-parseable, non-negative string."""
    vat = tpl["vat_rate"]
    if vat is None:
        return
    assert isinstance(vat, str)
    try:
        value = Decimal(vat)
    except InvalidOperation:  # pragma: no cover - assertion below reports it
        pytest.fail(f"{tpl['slug']}: vat_rate {vat!r} is not a Decimal string")
    assert value >= 0, f"{tpl['slug']}: negative vat_rate {vat!r}"


def test_template_names_are_unique() -> None:
    names = [tpl["name"] for tpl in t.list_templates()]
    assert len(names) == len(set(names))


# Countries that legitimately appear twice, because two costing traditions are
# both in use there and the estimate is read by different people. Chile prices
# an internal budget flat and submits a public tender as an APU. A country not
# on this list appearing twice is a copied template, not a second method.
_DUAL_METHOD_COUNTRIES = {"CL", "CO", "BR"}


def test_country_templates_have_unique_country_codes() -> None:
    """One template per country, unless the country really has two methods."""
    codes = [tpl["country_code"] for tpl in t.list_templates() if tpl["country_code"] is not None]
    duplicated = {code for code in codes if codes.count(code) > 1}

    assert duplicated <= _DUAL_METHOD_COUNTRIES, (
        f"unexpected duplicate country_code: {sorted(duplicated - _DUAL_METHOD_COUNTRIES)}"
    )


def test_a_country_offered_twice_is_offered_two_different_methods() -> None:
    """The exemption above has to buy something, or it is just a copy waved through.

    Two templates for one country are only worth the confusion they cost if
    they compute differently. Identical cascades under two names would be a
    duplicate that this suite had been told to ignore.
    """
    for code in _DUAL_METHOD_COUNTRIES:
        cascades = [
            tuple(step["key"] for step in tpl["cascade_steps"])
            for tpl in t.list_templates()
            if tpl["country_code"] == code
        ]
        assert len(cascades) > 1, f"{code} is exempted from uniqueness but appears once"
        assert len(set(cascades)) == len(cascades), f"{code} has two templates with the same cascade"


def test_catalogue_covers_expected_new_markets() -> None:
    """The broadened international coverage stays present."""
    slugs = {tpl["slug"] for tpl in t.list_templates()}
    assert slugs >= _EXTRA_COUNTRY_SLUGS
    # A sanity floor so a future refactor cannot quietly shrink the catalogue.
    assert len(slugs) >= 45


def test_every_country_template_declares_a_currency() -> None:
    """A country template (country_code set) always names a currency."""
    for tpl in t.list_templates():
        if tpl["country_code"] is not None:
            assert tpl["currency"], f"{tpl['slug']}: country template with blank currency"


@pytest.mark.parametrize("tpl", t.list_templates(), ids=lambda x: x["slug"])
def test_every_template_in_catalogue_builds_a_spec(tpl: dict) -> None:
    """Every catalogue entry (not just the pinned slugs) builds a valid spec."""
    spec = t.build_cascade_spec_from_template(tpl["slug"])
    assert isinstance(spec, CascadeSpec)
    assert len(spec.steps) == len(tpl["cascade_steps"])
    bases = {token: Decimal("1") for token in tpl["base_mapping"].keys()}
    if not bases:
        bases = {"direct": Decimal("1")}
    result = compute_cascade(spec, bases)
    assert result.grand_total >= result.direct_total


# ── build_cascade_spec_from_template ──────────────────────────────────────


@pytest.mark.parametrize("slug", sorted(_EXPECTED_SLUGS))
def test_every_template_builds_a_valid_spec(slug: str) -> None:
    """Each built-in template builds a spec the pure engine accepts."""
    spec = t.build_cascade_spec_from_template(slug)
    assert isinstance(spec, CascadeSpec)
    assert spec.slug == slug
    tpl = t.get_template(slug)
    assert spec.currency == tpl["currency"]
    assert spec.decimals == tpl["decimals"]
    assert len(spec.steps) == len(tpl["cascade_steps"])

    # Build a trivial bases map (one unit per leaf base) and confirm the engine
    # runs end-to-end without raising - i.e. no forward refs / unknown tokens.
    bases = {token: Decimal("1") for token in tpl["base_mapping"].keys()}
    if not bases:
        bases = {"direct": Decimal("1")}
    result = compute_cascade(spec, bases)
    assert result.grand_total >= result.direct_total


def test_uzbekistan_spec_has_smr_composite_and_vat_step() -> None:
    spec = t.build_cascade_spec_from_template("uzbekistan")
    assert "SMR" in spec.composites
    assert spec.composites["SMR"] == ("labor", "machinery", "materials")
    keys = [s.key for s in spec.steps]
    assert keys[-1] == "vat"
    # VAT applies to SMR + equipment + every prior step.
    vat = spec.steps[-1]
    assert "SMR" in vat.base and "equipment" in vat.base


def test_rates_are_decimal_on_built_spec() -> None:
    """Rates survive the str -> Decimal coercion without float contamination."""
    spec = t.build_cascade_spec_from_template("germany")
    for step in spec.steps:
        assert isinstance(step.rate, Decimal)
        assert isinstance(step.amount, Decimal)


# ── build_cascade_spec error handling ─────────────────────────────────────


def test_build_spec_rejects_non_mapping_composites() -> None:
    with pytest.raises(t.TemplateError):
        t.build_cascade_spec(
            slug="x",
            currency="",
            decimals=2,
            composites=[("SMR", ["labor"])],  # type: ignore[arg-type]
            cascade_steps=[],
        )


def test_build_spec_rejects_string_composite_members() -> None:
    with pytest.raises(t.TemplateError):
        t.build_cascade_spec(
            slug="x",
            currency="",
            decimals=2,
            composites={"SMR": "labor"},  # bare string, not a list
            cascade_steps=[],
        )


def test_build_spec_rejects_step_missing_key() -> None:
    with pytest.raises(t.TemplateError):
        t.build_cascade_spec(
            slug="x",
            currency="",
            decimals=2,
            composites={},
            cascade_steps=[{"kind": "percentage", "rate": "5", "base": []}],
        )


def test_build_spec_rejects_non_mapping_step() -> None:
    with pytest.raises(t.TemplateError):
        t.build_cascade_spec(
            slug="x",
            currency="",
            decimals=2,
            composites={},
            cascade_steps=["overhead"],  # type: ignore[list-item]
        )


def test_build_spec_rejects_string_step_base() -> None:
    with pytest.raises(t.TemplateError):
        t.build_cascade_spec(
            slug="x",
            currency="",
            decimals=2,
            composites={},
            cascade_steps=[{"key": "o", "kind": "percentage", "rate": "5", "base": "direct"}],
        )


def test_build_spec_defaults_blank_rate_to_zero() -> None:
    """An empty-string rate (a blank UI field) coerces to Decimal('0')."""
    spec = t.build_cascade_spec(
        slug="x",
        currency="USD",
        decimals=2,
        composites={"d": ["labor"]},
        cascade_steps=[
            {"key": "o", "label": "O", "category": "overhead", "kind": "percentage", "rate": "", "base": ["d"]}
        ],
    )
    assert spec.steps[0].rate == Decimal("0")
