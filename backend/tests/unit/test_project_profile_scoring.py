"""Project setup-wizard scoring engine — pure unit tests (Slice 1).

No DB / no app fixtures: ``profile_presets`` + ``profile_scoring`` are
deterministic pure functions. Asserts every one of the 8 real presets
resolves to a predictable ``must``-tier set (ALWAYS_ON ∪ preset extras
∪ region pack), that scoring tiers honour the documented thresholds,
and that the numbered-route ordinals are assigned correctly.
"""

from __future__ import annotations

import pytest

from app.modules.projects.profile_presets import (
    ALWAYS_ON,
    CROSS_CUTTING,
    PRESETS,
    REGION_PACK,
    preset_modules,
)
from app.modules.projects.profile_scoring import (
    SCORE_CORE,
    SCORE_PRESET,
    THRESHOLD_OPTIONAL,
    THRESHOLD_RECOMMENDED,
    assign_ordinals,
    build_project_modules,
)
from app.modules.projects.profile_service import discover_module_names

REAL_PRESETS = [pid for pid in PRESETS if pid != "custom"]


def _universe() -> list[str]:
    """The module id universe the service feeds the scorer (real folders),
    unioned with every preset's extras so a preset can never reference a
    module the scorer doesn't know about."""
    mods = set(discover_module_names())
    mods |= set(ALWAYS_ON)
    for meta in PRESETS.values():
        mods |= set(meta["modules"])
    for pack in REGION_PACK.values():
        mods.add(pack)
    return sorted(mods)


# ── Preset library invariants ────────────────────────────────────────────


def test_eight_real_presets_plus_custom() -> None:
    assert len(REAL_PRESETS) == 8
    assert "custom" in PRESETS
    # Every preset carries the metadata the wizard card renders.
    for meta in PRESETS.values():
        for field in ("id", "icon", "label_key", "label_en", "blurb_en", "modules"):
            assert field in meta and meta[field] is not None


def test_preset_modules_is_always_on_union_extras() -> None:
    for pid, meta in PRESETS.items():
        resolved = preset_modules(pid)
        assert set(ALWAYS_ON) <= resolved, f"{pid} dropped core"
        assert resolved == set(ALWAYS_ON) | set(meta["modules"])
    # Unknown preset id degrades to just the always-on core.
    assert preset_modules("does-not-exist") == set(ALWAYS_ON)


def test_discover_module_names_is_sane() -> None:
    mods = discover_module_names()
    assert isinstance(mods, tuple) and len(mods) >= 50
    # Discovery must see the real always-on folders (projects/users/...).
    for core in ("projects", "users", "boq", "reporting"):
        assert core in mods


# ── build_project_modules: deterministic spine ───────────────────────────


@pytest.mark.parametrize("preset", REAL_PRESETS)
def test_preset_yields_expected_must_set(preset: str) -> None:
    universe = _universe()
    assigns = build_project_modules(
        all_modules=universe,
        preset=preset,
        activities=[],
        phases=[],
        role="",
        size="",
        region="dach",
    )
    by_name = {a.module_name: a for a in assigns}

    # 1. Every ALWAYS_ON module is must / core / enabled.
    for core in ALWAYS_ON:
        a = by_name[core]
        assert a.tier == "must" and a.enabled and a.source == "core"
        assert a.score == SCORE_CORE

    # 2. Every module the preset explicitly selects is must / preset.
    for mod in PRESETS[preset]["modules"]:
        if mod in ALWAYS_ON:
            continue  # core wins — already asserted above
        a = by_name[mod]
        assert a.tier == "must", f"{preset}:{mod} not must"
        assert a.enabled and a.source == "preset"
        assert a.score == SCORE_PRESET

    # 3. Region pack auto-added as must / region.
    pack = REGION_PACK["dach"]
    assert by_name[pack].tier == "must"
    assert by_name[pack].source == "region" and by_name[pack].enabled

    # 4. Nothing is silently dropped; hidden modules still returned.
    assert set(by_name) == set(universe) | {pack}
    tiers = {a.tier for a in assigns}
    assert tiers <= {"must", "recommended", "optional", "hidden"}


def test_custom_preset_has_no_preset_extras() -> None:
    universe = _universe()
    assigns = build_project_modules(
        all_modules=universe,
        preset="custom",
        activities=[],
        phases=[],
        role="",
        size="",
        region="",
    )
    by_name = {a.module_name: a for a in assigns}
    for core in ALWAYS_ON:
        assert by_name[core].tier == "must" and by_name[core].source == "core"
    # No module is sourced from a preset when preset == custom.
    assert all(a.source != "preset" for a in assigns)


@pytest.mark.parametrize("region,pack", list(REGION_PACK.items()))
def test_region_pack_added_per_region(region: str, pack: str) -> None:
    assigns = build_project_modules(
        all_modules=_universe(),
        preset="custom",
        activities=[],
        phases=[],
        role="",
        size="",
        region=region,
    )
    a = {x.module_name: x for x in assigns}[pack]
    assert a.source == "region" and a.tier == "must" and a.enabled


# ── Scoring thresholds ───────────────────────────────────────────────────


def test_scoring_axis_lifts_relevant_modules() -> None:
    """A cost-estimation activity must push BoQ/takeoff into >= optional."""
    assigns = build_project_modules(
        all_modules=_universe(),
        preset="custom",                 # no preset must-set in the way
        activities=["cost_estimation"],
        phases=["tender"],
        role="cost_engineer",
        size="medium",
        region="",
    )
    by = {a.module_name: a for a in assigns}
    for mod in ("boq", "takeoff", "costs"):
        if mod in by:
            assert by[mod].score >= THRESHOLD_OPTIONAL
            assert by[mod].tier in ("must", "recommended", "optional")


def test_tier_boundaries_match_thresholds() -> None:
    for a in build_project_modules(
        all_modules=_universe(),
        preset="custom",
        activities=["bim_quality_check"],
        phases=["design"],
        role="bim_manager",
        size="large",
        region="uk",
    ):
        assert 0 <= a.score <= 100
        if a.source == "score":
            if a.tier == "recommended":
                assert a.score >= THRESHOLD_RECOMMENDED
            elif a.tier == "optional":
                assert THRESHOLD_OPTIONAL <= a.score < THRESHOLD_RECOMMENDED
            elif a.tier == "hidden":
                assert a.score < THRESHOLD_OPTIONAL


# ── Numbered-route ordinals ──────────────────────────────────────────────


def test_assign_ordinals_numbers_only_enabled_non_crosscutting() -> None:
    assigns = build_project_modules(
        all_modules=_universe(),
        preset="full_construction_lifecycle",
        activities=["construction_execution"],
        phases=["construction"],
        role="general_contractor",
        size="large",
        region="dach",
    )
    ordinals = assign_ordinals(assigns)

    # Cross-cutting modules never get a number even when enabled.
    for a in assigns:
        if a.module_name in CROSS_CUTTING:
            assert ordinals[a.module_name] is None
        if not a.enabled:
            assert ordinals[a.module_name] is None

    numbered = sorted(v for v in ordinals.values() if v is not None)
    # Sequential 1..n with no gaps or dupes.
    assert numbered == list(range(1, len(numbered) + 1))
    assert len(numbered) >= len(ALWAYS_ON) - len(
        set(ALWAYS_ON) & CROSS_CUTTING
    )
