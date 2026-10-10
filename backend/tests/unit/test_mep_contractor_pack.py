"""The Turkey MEP contractor pack, and the manifest field it is built around.

Three things are locked here.

A pack can name the company profile its users start in
(``default_company_profile``). The field is checked against the profile
catalogue when the manifest is built, and it travels in the public manifest,
which is the path ``default_locale`` already takes to every signed-in user.

The pack is derived from the Türkiye country pack and copies none of it. One
installation runs one pack, so the country configuration has to come along,
and a copy would go stale the first time the country pack is corrected. The
comparison is made field by field against the country manifest as it is on
disk now, so it fails when the two drift.

The pack switches modules off, which no shipped pack did before. Every name
has to be a module the loader can switch off without taking a dependency away
from a module that stays on, in the order the loader is asked.
"""

from __future__ import annotations

import ast
import importlib.util
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from app.core.onboarding_presets import COMPANY_PRESETS, SIZE_PRESETS
from app.core.partner_pack.manifest import PartnerPackManifest

REPO_ROOT = Path(__file__).resolve().parents[3]
MODULES_DIR = REPO_ROOT / "backend" / "app" / "modules"
PACKS_DIR = REPO_ROOT / "packs"
PACK_MANIFEST = PACKS_DIR / "turkey-tr-mep" / "src" / "openconstructionerp_turkey_tr_mep" / "manifest.py"
COUNTRY_MANIFEST = PACKS_DIR / "turkey-tr" / "src" / "openconstructionerp_turkey_tr" / "manifest.py"

pytestmark = pytest.mark.skipif(not PACK_MANIFEST.is_file(), reason="pack tree not present")


def _load(path: Path, name: str) -> PartnerPackManifest:
    """Load a pack manifest by file, the way discovery does."""
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader, f"{path} cannot be loaded as a module"
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module.MANIFEST


@lru_cache(maxsize=1)
def _pack() -> PartnerPackManifest:
    return _load(PACK_MANIFEST, "_test_turkey_tr_mep_manifest")


@lru_cache(maxsize=1)
def _country() -> PartnerPackManifest:
    return _load(COUNTRY_MANIFEST, "_test_turkey_tr_manifest")


# ── The manifest field ────────────────────────────────────────────────────────


def _minimal(**fields: Any) -> PartnerPackManifest:
    return PartnerPackManifest(slug="some-pack", partner_name="Some Pack", **fields)


def test_a_pack_says_nothing_about_a_profile_by_default() -> None:
    manifest = _minimal()
    assert manifest.default_company_profile is None
    assert manifest.to_public_dict()["default_company_profile"] is None


@pytest.mark.parametrize("key", ["mep_contractor", "site_records", "general_contractor"])
def test_a_pack_may_name_any_company_profile(key: str) -> None:
    manifest = _minimal(default_company_profile=key)
    assert manifest.default_company_profile == key
    # The public manifest is what every signed-in user's browser reads.
    assert manifest.to_public_dict()["default_company_profile"] == key


@pytest.mark.parametrize("key", ["mep", "MEP_CONTRACTOR", "oe_contracts", "", "size_small"])
def test_a_profile_key_the_catalogue_does_not_carry_is_refused(key: str) -> None:
    assert key not in COMPANY_PRESETS
    with pytest.raises(ValidationError, match="default_company_profile"):
        _minimal(default_company_profile=key)


def test_a_size_tier_is_not_a_company_profile() -> None:
    """The refusal above must not be an accident of the two catalogues' keys."""
    assert "size_small" in SIZE_PRESETS


def test_the_apply_preview_names_the_profile() -> None:
    from app.core.partner_pack.apply import _plan

    plan = _plan(_minimal(default_company_profile="mep_contractor"), strict_rule_sets=False)
    assert plan["default_company_profile"] == "mep_contractor"
    assert any("mep_contractor" in warning for warning in plan["warnings"])

    silent = _plan(_minimal(), strict_rule_sets=False)
    assert silent["default_company_profile"] is None
    assert not any("Company profile" in warning for warning in silent["warnings"])


# ── The pack ──────────────────────────────────────────────────────────────────


def test_the_pack_loads_and_is_filed_as_an_industry_pack_for_one_market() -> None:
    pack = _pack()
    assert pack.slug == "turkey-tr-mep"
    assert pack.type == "industry"
    # The market is stated even though the type is not "country": projects,
    # the calendar and number grouping read the country, not the type.
    assert pack.market_country_code == "TR"


def test_the_pack_sorts_after_the_country_pack() -> None:
    """The first-run offer takes the first pack of the reader's country.

    Packs are listed by slug, so a slug that sorted ahead of ``turkey-tr``
    would be offered to every Turkish first run in place of the country pack.
    """
    assert sorted([_pack().slug, _country().slug]) == [_country().slug, _pack().slug]


#: The fields this pack states for itself. Everything else is the country's.
_OWN_FIELDS = frozenset(
    {
        "slug",
        "partner_name",
        "pack_version",
        "pack_type",
        "description",
        "default_company_profile",
        "default_modules",
        "hidden_modules",
        "branding",
        "onboarding_script_path",
        "metadata",
    }
)


def test_everything_the_pack_does_not_state_is_the_country_packs() -> None:
    pack, country = _pack().model_dump(), _country().model_dump()
    assert set(pack) == set(country)
    drifted = sorted(field for field in set(pack) - _OWN_FIELDS if pack[field] != country[field])
    assert drifted == [], f"copied instead of derived, or overridden without saying so: {drifted}"


def test_the_country_fields_that_matter_are_actually_set() -> None:
    """A comparison of two empty values would pass the test above."""
    pack = _pack()
    assert pack.default_locale == "tr"
    assert pack.default_currency == "TRY"
    assert pack.default_methodology
    assert pack.validation_rule_sets
    assert pack.validation_rule_packs
    assert pack.cwicr_regions
    assert pack.demo_template_ids


def test_the_market_metadata_is_the_country_packs_with_the_trade_added() -> None:
    pack, country = _pack().metadata, _country().metadata
    added = {"industry", "industry_name_en", "industry_name_tr", "derived_from"}
    assert set(pack) - set(country) == added
    assert {key: pack[key] for key in country} == country
    assert pack["derived_from"] == _country().slug


def test_the_manifest_file_states_no_country_value_of_its_own() -> None:
    """Derived, not copied: the country's values do not appear as literals."""
    text = PACK_MANIFEST.read_text(encoding="utf-8")
    country = _country()
    literals = {node.value for node in ast.walk(ast.parse(text)) if isinstance(node, ast.Constant)}
    copied = sorted(
        value
        for value in [
            country.default_currency,
            country.default_methodology,
            *country.validation_rule_sets,
            *country.validation_rule_packs,
            *country.cwicr_regions,
            *country.demo_template_ids,
        ]
        if value in literals
    )
    assert copied == []


def test_the_reference_documents_exist_in_the_country_pack() -> None:
    """The ids are inherited; the files stay where they are and must be there."""
    rule_packs = COUNTRY_MANIFEST.parent / "rule_packs"
    missing = [name for name in _pack().validation_rule_packs if not (rule_packs / f"{name}.json").is_file()]
    assert missing == []


def test_the_pack_promises_no_file_it_does_not_carry() -> None:
    pack = _pack()
    assert pack.onboarding_script_path is None
    assert pack.branding.logo_path is None
    assert pack.branding.favicon_path is None
    assert pack.additional_locales == {}


def test_the_pack_names_the_installers_profile() -> None:
    pack = _pack()
    assert pack.default_company_profile == "mep_contractor"
    assert pack.to_public_dict()["default_company_profile"] == "mep_contractor"


def test_version_is_stated_once_in_each_place_and_agrees() -> None:
    pyproject = (PACKS_DIR / "turkey-tr-mep" / "pyproject.toml").read_text(encoding="utf-8")
    assert f'version = "{_pack().pack_version}"' in pyproject
    assert f'"openconstructionerp-turkey-tr>={_country().pack_version}"' in pyproject


# ── The module lists ──────────────────────────────────────────────────────────


def _keyword(tree: ast.AST, name: str) -> Any:
    for node in ast.walk(tree):
        if isinstance(node, ast.keyword) and node.arg == name:
            return ast.literal_eval(node.value)
    return None


@lru_cache(maxsize=1)
def _modules() -> dict[str, tuple[str, list[str]]]:
    """``{manifest name: (category, depends)}`` for every module on disk."""
    out: dict[str, tuple[str, list[str]]] = {}
    for path in sorted(MODULES_DIR.glob("*/manifest.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        out[_keyword(tree, "name")] = (_keyword(tree, "category"), _keyword(tree, "depends") or [])
    return out


def test_the_module_reader_sees_the_tree_it_is_asked_about() -> None:
    modules = _modules()
    assert len(modules) > 150
    assert modules["oe_projects"][0] == "core"
    assert "oe_us_pack" in modules["oe_us_tx_pack"][1]
    assert "oe_boq" in modules["oe_variations"][1]


def test_the_two_lists_are_non_empty_distinct_and_disjoint() -> None:
    pack = _pack()
    assert len(pack.hidden_modules) == 24
    assert pack.default_modules
    assert len(set(pack.hidden_modules)) == len(pack.hidden_modules)
    assert len(set(pack.default_modules)) == len(pack.default_modules)
    assert not set(pack.hidden_modules) & set(pack.default_modules)


@pytest.mark.parametrize("field", ["hidden_modules", "default_modules"])
def test_every_listed_module_exists_and_is_not_core(field: str) -> None:
    modules = _modules()
    listed: list[str] = getattr(_pack(), field)
    unknown = [name for name in listed if name not in modules]
    assert unknown == [], f"{field} names modules that are not on disk: {unknown}"
    # The loader refuses to switch a core module off, and one that cannot be
    # off needs no switching on.
    core = [name for name in listed if modules[name][0] == "core"]
    assert core == [], f"{field} names core modules: {core}"


def test_no_module_that_stays_on_depends_on_a_hidden_one() -> None:
    modules = _modules()
    hidden = set(_pack().hidden_modules)
    broken = sorted(
        f"{name} needs {dep}"
        for name, (_category, depends) in modules.items()
        if name not in hidden
        for dep in depends
        if dep in hidden
    )
    assert broken == []


def test_hidden_modules_are_listed_dependents_first() -> None:
    """They are switched off in list order, and the loader refuses a module
    that one still on depends on."""
    modules = _modules()
    hidden = _pack().hidden_modules
    position = {name: index for index, name in enumerate(hidden)}
    late = sorted(
        f"{name} is listed before {dependent}, which depends on it"
        for name in hidden
        for dependent, (_category, depends) in modules.items()
        if name in depends and dependent in position and position[dependent] > position[name]
    )
    assert late == []


def test_no_hidden_module_serves_a_market_the_contractor_works_in() -> None:
    """The regional data packs each declare their countries."""
    for name in _pack().hidden_modules:
        config = MODULES_DIR / name.removeprefix("oe_") / "config.py"
        if not name.endswith("_pack") or not config.is_file():
            continue
        countries = _keyword(ast.parse(config.read_text(encoding="utf-8")), "countries")
        if countries is None:
            # Declared as a dict entry rather than a keyword.
            text = config.read_text(encoding="utf-8")
            start = text.index('"countries"')
            countries = ast.literal_eval(text[text.index("[", start) : text.index("]", start) + 1])
        assert not {"TR", "HU", "ES"} & set(countries), f"{name} serves {countries}"


def test_the_profile_is_not_cut_off_by_the_hidden_list() -> None:
    """No module the pack's profile switches on is one the pack switches off."""
    profile = COMPANY_PRESETS[_pack().default_company_profile or ""]
    cut = sorted(f"oe_{key}" for key in profile.enabled_modules if f"oe_{key}" in set(_pack().hidden_modules))
    assert cut == []


class _FakeLoader:
    """Stands in for the module loader with the real categories and depends."""

    def __init__(self) -> None:
        self._manifests = _modules()
        self.disabled: list[str] = []
        self.enabled: list[str] = []

    async def enable_module(self, name: str, _app: object) -> None:
        self.enabled.append(name)

    async def disable_module(self, name: str, _app: object) -> None:
        category, _depends = self._manifests[name]
        if category == "core":
            raise ValueError(f"{name} is core")
        dependents = [
            other for other, (_c, depends) in self._manifests.items() if name in depends and other not in self.disabled
        ]
        if dependents:
            raise ValueError(f"{name} is required by {dependents}")
        self.disabled.append(name)


@pytest.mark.parametrize("confirm", [True, False])
async def test_applying_switches_the_modules_off_only_when_confirmed(
    confirm: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core.partner_pack import apply as apply_module

    pack = _pack()
    loader = _FakeLoader()
    saved: list[Any] = []
    monkeypatch.setattr(apply_module, "module_loader", loader)
    monkeypatch.setattr(apply_module, "get_pack_by_slug", lambda _slug: pack)
    monkeypatch.setattr(apply_module, "save_applied_state", saved.append)
    monkeypatch.setattr(apply_module, "reset_cache", lambda: None)
    # The rule registry is filled at start-up, which a unit test does not run.
    monkeypatch.setattr(
        apply_module, "resolve_declared_rule_sets", lambda m, *, strict=False: list(m.validation_rule_sets)
    )

    result = await apply_module.apply_pack(pack.slug, confirm_disables=confirm, install_demo=False, app=object())

    assert result["applied"] is True
    assert result["effects"]["modules_failed"] == []
    assert result["effects"]["modules_enabled"] == pack.default_modules
    if confirm:
        assert result["effects"]["modules_disabled"] == pack.hidden_modules
        assert result["skipped_disables"] == []
    else:
        assert result["effects"]["modules_disabled"] == []
        assert result["skipped_disables"] == pack.hidden_modules
        assert loader.disabled == []
    assert saved and saved[0].manifest_snapshot["default_company_profile"] == "mep_contractor"
