"""Unit tests for the company-profile onboarding presets.

The sidebar is gated on ``module_preferences``, which ``modules_for`` builds
from the module set a profile selects. Two behaviours matter and are easy to
regress:

- "Full Enterprise" must light up every functional module.
- A narrow profile must still write an explicit False for the modules it does
  not include, otherwise the sidebar could not hide anything.

This used to say the backend list was authoritative, "so even if a client
catalogue drifts behind the server the whole platform still shows". Measured,
the drift runs the other way and nothing was watching it: the wizard catalogue
in ``frontend/src/features/onboarding/modules.ts`` carries 157 keys, this
module carries 93, and all 64 of the difference are keys the backend has never
heard of. The last test in this file is the gate that was missing.
"""

import ast
import pathlib
import re

import pytest

from app.core.onboarding_presets import (
    _ALL_FUNCTIONAL,
    _ALL_MODULES,
    _CORE_MODULES,
    _REGIONAL,
    COMPANY_PRESETS,
    SIZE_PRESETS,
    get_core_modules,
    get_preset,
    is_core_module,
    is_saveable_company_size,
    is_saveable_company_type,
    modules_for,
)

#: Wizard catalogue keys this module does not carry yet.
#:
#: Named rather than counted on purpose. A bare "allow 64 differences" passes
#: just as happily when someone adds a key and deletes another, and it never
#: tells a reader which modules are affected. Spelled out, the list doubles as
#: the work item: every key removed from here is one module the company-profile
#: system can finally reason about.
#:
#: Do NOT close this gap by appending these keys to ``_ALL_MODULES`` alone.
#: ``modules_for`` writes an explicit ``False`` for every key it knows that the
#: selected profile omits, while the sidebar's ``isModuleEnabled`` is fail-open
#: (``frontend/src/stores/useModuleStore.ts:159``) and shows anything it has no
#: preference for. So these 64 are visible today precisely because the backend
#: stays silent about them, and naming them in a narrow profile would hide
#: working screens. Which profiles should carry which of these is a product
#: decision, not a mechanical one.
KNOWN_MISSING_FROM_BACKEND: frozenset[str] = frozenset(
    {
        "accommodation",
        "ai_estimator",
        "allowances",
        "approval_routes",
        "assets",
        "authority_submission",
        "bcf",
        "bimlv",
        "change_intelligence",
        "claims_evidence",
        "clash",
        "clash_ai_triage",
        "clash_cost_impact",
        "closeout",
        "commissioning",
        "construction_control",
        "coordination_hub",
        # Hyphenated where every other key is snake_case, matching the plugin
        # directory name rather than the backend manifest convention.
        "cost-benchmark",
        "cost_explorer",
        "cost_recovery",
        "cvr",
        "defects_liability",
        "design_options",
        "esg",
        "estimate_basis",
        "estimate_rollup",
        "field_time",
        "formwork",
        "forms",
        "fx",
        "geo_hub",
        "interface_management",
        "labor_rates",
        "methodology",
        "norm_expansion",
        "payment_clock",
        "phonelog",
        "pipelines",
        "plan_room",
        "pointcloud",
        "portfolio",
        "postcalc",
        "prefab",
        "preliminaries",
        "price_index",
        "progress",
        "reconciliation",
        "rom_estimate",
        "signing",
        "site_inventory",
        "site_logistics",
        "site_prep",
        "site_supervision",
        "sustainability",
        "temporary_works",
        "timeline",
        "value",
        "voice",
        "waste_factors",
    }
)

_WIZARD_CATALOGUE = (
    pathlib.Path(__file__).resolve().parents[3] / "frontend" / "src" / "features" / "onboarding" / "modules.ts"
)


def _wizard_catalogue_keys() -> set[str]:
    """Read the wizard's module keys out of the TypeScript catalogue.

    Parsed on every run rather than mirrored as a literal here. A mirrored copy
    is a third registry, and a gate whose expectation drifts with the thing it
    guards cannot fail.
    """
    source = _WIZARD_CATALOGUE.read_text(encoding="utf-8")
    start = source.index("export const ALL_MODULES")
    block = source[start : source.index("\n];", start)]
    keys = re.findall(r"\{\s*key:\s*'([^']+)'", block)
    # A parser that silently returns nothing would make every assertion below
    # pass. Refuse to report rather than certify an empty population.
    assert len(keys) > 100, f"wizard catalogue parser returned {len(keys)} keys - the instrument is broken"
    assert len(keys) == len(set(keys)), "wizard catalogue has duplicate keys"
    return set(keys)


def test_full_enterprise_enables_every_functional_module() -> None:
    """Full Enterprise pins to the backend's own functional list, all on."""
    preset = get_preset("full_enterprise")
    assert preset is not None
    # The preset itself carries the complete functional set.
    assert set(preset.enabled_modules) == set(_ALL_FUNCTIONAL)

    prefs = modules_for(preset.enabled_modules)
    # Every functional module is explicitly enabled - nothing is hidden.
    for key in _ALL_FUNCTIONAL:
        assert prefs[key] is True, f"{key} should be enabled under Full Enterprise"
    # Sidebar routes that an external report flagged as vanishing are present.
    for key in ("bim_hub", "finance", "crm"):
        assert prefs[key] is True


def test_core_modules_are_always_on() -> None:
    """No profile can hide a core module, even an empty selection."""
    prefs = modules_for([])
    for key in _CORE_MODULES:
        assert prefs[key] is True
        assert is_core_module(key) is True


def test_narrow_profile_disables_unselected_modules() -> None:
    """A profile that omits a functional module writes an explicit False."""
    prefs = modules_for(["boq", "costs", "takeoff"])
    assert prefs["boq"] is True
    # A functional module left out of the selection is turned off so the
    # sidebar can hide it.
    assert prefs["finance"] is False
    assert prefs["crm"] is False


def test_every_known_module_gets_an_explicit_flag() -> None:
    """``modules_for`` returns a complete map, never a partial one."""
    prefs = modules_for([])
    expected = set(_CORE_MODULES) | set(_ALL_FUNCTIONAL)
    assert expected.issubset(set(prefs))
    assert all(isinstance(v, bool) for v in prefs.values())


@pytest.mark.skipif(not _WIZARD_CATALOGUE.exists(), reason="frontend tree not checked out")
def test_backend_registry_names_no_module_the_wizard_lacks() -> None:
    """Every backend key must exist in the wizard catalogue.

    This direction has to stay empty. A key the backend writes into
    ``module_preferences`` but the wizard cannot show is a preference no user
    can ever change, and the onboarding screen would not even list it.
    """
    unknown = set(_ALL_MODULES) - _wizard_catalogue_keys()
    assert unknown == set(), f"backend keys absent from the wizard catalogue: {sorted(unknown)}"


@pytest.mark.skipif(not _WIZARD_CATALOGUE.exists(), reason="frontend tree not checked out")
def test_wizard_keys_absent_from_the_backend_match_the_allowlist() -> None:
    """Pin the known gap so it can only shrink, never grow unnoticed.

    Fails in both directions by construction. Add a module to the wizard and
    forget the backend, and ``missing`` grows past the allowlist. Add one of the
    allowlisted keys to ``_ALL_MODULES`` and forget to delete its line here, and
    ``missing`` shrinks below it. Either way the two registries and this file
    are forced back into agreement in the same commit.
    """
    missing = _wizard_catalogue_keys() - set(_ALL_MODULES)
    new_drift = missing - KNOWN_MISSING_FROM_BACKEND
    closed = KNOWN_MISSING_FROM_BACKEND - missing
    assert new_drift == set(), (
        f"wizard modules the backend registry does not know: {sorted(new_drift)}. "
        "Add them to _ALL_MODULES, or add them to KNOWN_MISSING_FROM_BACKEND with a reason."
    )
    assert closed == set(), (
        f"these keys reached the backend registry but are still allowlisted: {sorted(closed)}. "
        "Delete them from KNOWN_MISSING_FROM_BACKEND."
    )


def test_regional_list_matches_the_packs_on_disk() -> None:
    """``_REGIONAL`` names every ``backend/app/modules/*_pack`` and no other.

    It stood at eight while thirteen packs shipped, so five of them were absent
    from the registry and five were written off by every profile, and nothing
    said which half a reader was looking at. Derived from the tree rather than
    from a number, because a count passes just as happily when one pack is
    added and another deleted.
    """
    modules_dir = pathlib.Path(__file__).resolve().parents[2] / "app" / "modules"
    if not modules_dir.exists():  # pragma: no cover - source checkout only
        pytest.skip("backend module tree not present")
    on_disk = {p.name for p in modules_dir.glob("*_pack") if (p / "manifest.py").exists()}
    assert on_disk, "no *_pack modules found, the probe is looking in the wrong place"
    assert set(_REGIONAL) == on_disk, (
        f"only in _REGIONAL: {sorted(set(_REGIONAL) - on_disk)}; only on disk: {sorted(on_disk - set(_REGIONAL))}"
    )


def test_a_company_profile_writes_no_flag_for_a_regional_pack() -> None:
    """A role must not decide a market.

    Every profile used to write ``False`` here, Full Enterprise included, so
    the toggle on ``/modules`` read "off" for a pack ``regional_packs.py``
    imports unconditionally. Absent is the answer, not ``True``: the region
    step and the applied partner pack own these keys, and this function must
    not overwrite either of them in either direction.
    """
    for key, preset in COMPANY_PRESETS.items():
        prefs = modules_for(preset.enabled_modules)
        leaked = sorted(k for k in _REGIONAL if k in prefs)
        assert leaked == [], f"profile {key} writes a flag for regional packs: {leaked}"
    # And the empty selection, which is what a brand new account starts from.
    assert [k for k in _REGIONAL if k in modules_for([])] == []


def test_core_modules_are_handed_out_as_a_copy() -> None:
    """``get_core_modules`` must not hand the caller the live list.

    It feeds a JSON response, and a serialiser that mutated what it was given
    would make a company profile able to hide Projects for everyone who asked
    afterwards, for as long as the process lived.
    """
    snapshot = list(_CORE_MODULES)
    handed_out = get_core_modules()
    assert handed_out == snapshot

    # Identity, not equality. The first version of this test mutated what it
    # was handed and then compared ``get_core_modules()`` against
    # ``list(_CORE_MODULES)``, which is the same mutated object read twice: it
    # passed with the defect in place, because both sides moved together.
    assert handed_out is not _CORE_MODULES

    handed_out.append("not_a_module")
    assert get_core_modules() == snapshot
    assert list(_CORE_MODULES) == snapshot


def test_every_core_module_is_in_the_registry() -> None:
    """A core key outside ``_ALL_MODULES`` would be forced on by nothing."""
    assert set(_CORE_MODULES).issubset(set(_ALL_MODULES))
    assert not set(_CORE_MODULES) & set(_REGIONAL), (
        "a regional pack cannot also be core: core is forced True and regional "
        "is left alone, and the two rules cannot both apply to one key"
    )


# ── Every id a profile names resolves ────────────────────────────────────────
#
# A preset is a list of strings, and nothing between the list and the screen
# checks them. ``modules_for`` walks the registry and asks whether each key was
# chosen, so a key the registry does not carry is dropped without a word: a
# profile listing "fieldreport" would ship with its field reports switched off
# and every test above still green. These close that from both ends, the
# registry the presets draw on and the module packages on disk.

_MODULES_DIR = pathlib.Path(__file__).resolve().parents[2] / "app" / "modules"
_ALL_PRESETS = {**COMPANY_PRESETS, **SIZE_PRESETS}


@pytest.mark.parametrize("key", sorted(_ALL_PRESETS))
def test_every_module_a_preset_names_is_in_the_registry(key: str) -> None:
    preset = _ALL_PRESETS[key]
    unknown = sorted(set(preset.enabled_modules) - set(_ALL_MODULES))
    assert unknown == [], f"preset {key} names modules the registry does not know: {unknown}"
    # And each one survives into the map the sidebar reads, switched on.
    prefs = modules_for(preset.enabled_modules)
    assert all(prefs[m] is True for m in preset.enabled_modules)


def test_every_registry_key_is_a_module_package_on_disk() -> None:
    """Each key is the ``oe_<key>`` manifest of a package under ``app/modules``."""
    if not _MODULES_DIR.exists():  # pragma: no cover - source checkout only
        pytest.skip("backend module tree not present")
    missing: list[str] = []
    misnamed: list[str] = []
    for key in _ALL_MODULES:
        manifest = _MODULES_DIR / key / "manifest.py"
        if not manifest.exists():
            missing.append(key)
            continue
        if f'name="oe_{key}"' not in manifest.read_text(encoding="utf-8"):
            misnamed.append(key)
    assert missing == [], f"registry keys with no module package: {missing}"
    assert misnamed == [], f"module packages whose manifest name is not oe_<key>: {misnamed}"


def test_every_preset_key_is_saveable_and_filed_under_its_own_name() -> None:
    assert not set(COMPANY_PRESETS) & set(SIZE_PRESETS), "a key cannot be both a profile and a size"
    for key, preset in _ALL_PRESETS.items():
        assert preset.key == key
        assert is_saveable_company_type(key)
    for key in SIZE_PRESETS:
        assert is_saveable_company_size(key)
    # A profile is not a size, and nothing outside the two catalogues is either.
    assert not is_saveable_company_size("general_contractor")
    assert not is_saveable_company_type("demolition_contractor")


# ── A profile brings what its modules need ────────────────────────────────────
# A module manifest names the modules it is built on (``depends``). A profile
# that switches a module on and leaves one of those off hands the user a page
# whose links and lookups lead into a module missing from their menu: takeoff
# without the CAD converter that feeds it, reporting without the model it
# reports on. Nothing expands a preset at save time, the list is written as it
# stands (``modules_for``), so the list itself has to be complete.


def _manifest_depends(key: str) -> list[str]:
    """The module keys ``app/modules/<key>/manifest.py`` declares it depends on."""
    tree = ast.parse((_MODULES_DIR / key / "manifest.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.keyword) and node.arg == "depends":
            assert isinstance(node.value, ast.List), f"{key}: depends is not a literal list"
            names = [ast.literal_eval(elt) for elt in node.value.elts]
            return [name.removeprefix("oe_") for name in names]
    return []


def test_the_dependency_reader_sees_the_dependencies_it_is_asked_about() -> None:
    """The instrument, checked on two manifests the presets below lean on."""
    if not _MODULES_DIR.exists():  # pragma: no cover - source checkout only
        pytest.skip("backend module tree not present")
    assert "cad" in _manifest_depends("takeoff")
    assert "bim_hub" in _manifest_depends("reporting")


@pytest.mark.parametrize("key", sorted(_ALL_PRESETS))
def test_every_preset_switches_on_what_its_modules_depend_on(key: str) -> None:
    if not _MODULES_DIR.exists():  # pragma: no cover - source checkout only
        pytest.skip("backend module tree not present")
    # The map the save endpoint writes: core forced on, the preset's list on,
    # every other profile-governed module off. A key the map does not carry is
    # not governed by any profile and is always there.
    prefs = modules_for(_ALL_PRESETS[key].enabled_modules)
    unmet = sorted(
        f"{module} needs {dep}"
        for module, on in prefs.items()
        if on
        for dep in _manifest_depends(module)
        if prefs.get(dep, True) is False
    )
    assert unmet == [], f"preset {key} switches a module on without what it depends on: {unmet}"


#: What a profile's own work cannot do without, beyond what the manifests say.
_PROFILE_MUST_INCLUDE: dict[str, list[str]] = {
    # A trade contractor bills the main contractor through pay applications,
    # which live in contracts.
    "subcontractor": ["contracts"],
    # The owner signs the contract and approves every change to it.
    "owner_client": ["contracts", "changeorders"],
    # Building services work is live electrical, hot work and working at height.
    "mep_contractor": ["safety"],
    # Roads and bridges run on the same RFI, submittal and meeting cycle as a
    # building site.
    "civil_infrastructure": ["rfi", "submittals", "meetings"],
    # An estimator measures from the model and from drawings, and takeoff reads
    # drawings through the CAD converter.
    "estimator": ["bim_hub", "cad"],
}


@pytest.mark.parametrize("key", sorted(_PROFILE_MUST_INCLUDE))
def test_a_profile_carries_the_modules_its_work_needs(key: str) -> None:
    missing = sorted(set(_PROFILE_MUST_INCLUDE[key]) - set(COMPANY_PRESETS[key].enabled_modules))
    assert missing == [], f"preset {key} leaves out {missing}"
