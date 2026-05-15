# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Project-profile → modules scoring engine (concept doc §2).

Weighted scoring over five axes (Activity 0.35 · Role 0.25 · Phase 0.20
· Size 0.10 · Region 0.10). The preset's explicit set is always
``must`` (deterministic); scoring decides the *recommended* /
*optional* tiers for everything else and explains "why" so the UI can
show a match score.

Design choices vs the doc:

* Per-module 5-axis YAML tags for all 88 modules are explicitly a
  later calibration task (doc CAVEAT #3). For Slice 1 the **activity**
  axis is *derived from preset membership* — a module that appears in
  preset P is by definition highly relevant to P's activity. That is
  data-driven, needs no hand-tuning, and stays correct as presets
  evolve. Role / phase / size use small curated maps with sensible
  defaults; region only gates the regional pack.
* Weights and thresholds are the doc's starting hypothesis; they live
  in module-level constants so calibration after real setup sessions
  is a one-line change.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.modules.projects.profile_presets import (
    ALWAYS_ON,
    CROSS_CUTTING,
    PRESETS,
    REGION_PACK,
    preset_modules,
)

Tier = Literal["must", "recommended", "optional", "hidden"]

AXIS_WEIGHTS: dict[str, float] = {
    "activity": 0.35,
    "role": 0.25,
    "phase": 0.20,
    "size": 0.10,
    "region": 0.10,
}

# Tier thresholds on the 0–100 aggregate (doc §2.4).
THRESHOLD_RECOMMENDED = 40
THRESHOLD_OPTIONAL = 20

# An explicit preset / always-on selection lands here.
SCORE_CORE = 100
SCORE_PRESET = 90

# ── Activity → representative preset(s) ──────────────────────────────────
# The activity axis score for module m under activity a is 100 when m is
# in the preset that embodies a, else 0. Multi-activity profiles take the
# max across their activities (doc §2.3 multi-select rule).
ACTIVITY_PRESET: dict[str, str] = {
    "bim_quality_check": "bim_quality_check",
    "cost_estimation": "cost_estimation_only",
    "tender_preparation": "tender_preparation",
    "construction_execution": "full_construction_lifecycle",
    "property_development": "property_development",
    "site_management": "site_management",
    "consulting": "bim_consulting",
    "facility_management": "facility_management",
}

# ── Role → modules that role leans on (curated, doc §2.2 spirit) ─────────
ROLE_AFFINITY: dict[str, frozenset[str]] = {
    "client_owner": frozenset(
        {"portal", "finance", "risk", "reporting", "project_intelligence"}
    ),
    "general_contractor": frozenset(
        {
            "procurement", "subcontractors", "schedule", "schedule_advanced",
            "fieldreports", "daily_diary", "finance", "changeorders",
            "safety", "hse_advanced",
        }
    ),
    "bim_consultant": frozenset(
        {
            "bim_hub", "bim_requirements", "validation", "compliance",
            "compliance_ai", "compliance_docs", "cde", "opencde_api",
            "markups", "match_elements",
        }
    ),
    "bim_manager": frozenset(
        {
            "bim_hub", "bim_requirements", "validation", "cde",
            "match_elements", "markups", "ncr", "inspections",
        }
    ),
    "designer_architect": frozenset(
        {"bim_hub", "bim_requirements", "validation", "markups", "cde"}
    ),
    "subcontractor": frozenset(
        {"tendering", "rfq_bidding", "bid_management", "fieldreports", "rfi"}
    ),
    "cost_engineer": frozenset(
        {
            "boq", "catalog", "costs", "costmodel", "assemblies",
            "cost_match", "ai", "takeoff", "dwg_takeoff", "match_elements",
            "tendering",
        }
    ),
    "developer": frozenset(
        {
            "property_dev", "crm", "finance", "portal", "variations",
            "project_intelligence", "carbon",
        }
    ),
}

# ── Phase → modules typically active in that lifecycle phase ─────────────
PHASE_AFFINITY: dict[str, frozenset[str]] = {
    "concept": frozenset({"project_intelligence", "crm", "property_dev"}),
    "design": frozenset(
        {
            "bim_hub", "bim_requirements", "validation", "compliance",
            "compliance_ai", "compliance_docs", "cde", "markups",
            "match_elements", "requirements",
        }
    ),
    "tender": frozenset(
        {
            "tendering", "bid_management", "rfq_bidding", "boq", "catalog",
            "costs", "costmodel", "assemblies", "ai", "takeoff",
            "dwg_takeoff", "cost_match", "contracts", "submittals",
        }
    ),
    "procurement": frozenset(
        {"procurement", "subcontractors", "contracts", "correspondence"}
    ),
    "construction": frozenset(
        {
            "schedule", "schedule_advanced", "finance", "changeorders",
            "fieldreports", "daily_diary", "inspections", "ncr",
            "punchlist", "safety", "hse_advanced", "meetings", "rfi",
            "equipment", "resources", "jobs", "eac", "full_evm",
            "transmittals", "variations",
        }
    ),
    "handover": frozenset(
        {"service", "qms", "carbon", "opencde_api", "submittals"}
    ),
}

# Canonical phase order for global numbering (doc §3.2).
PHASE_ORDER: tuple[str, ...] = (
    "setup",
    "concept",
    "design",
    "tender",
    "procurement",
    "construction",
    "handover",
)

# Enterprise-tier modules only make sense at scale (size axis).
ENTERPRISE_MODULES: frozenset[str] = frozenset(
    {"full_evm", "enterprise_workflows", "rfq_bidding", "eac"}
)

SIZE_BASE: dict[str, int] = {
    "small": 30,
    "medium": 60,
    "large": 80,
    "enterprise": 100,
}


@dataclass(frozen=True)
class ModuleAssignment:
    """One row the service persists into ``oe_project_module``."""

    module_name: str
    enabled: bool
    tier: Tier
    score: int
    phase: str
    source: str  # core | region | preset | score | manual
    why: str


def _axis_score_activity(module: str, activities: list[str]) -> int:
    best = 0
    for a in activities:
        preset_id = ACTIVITY_PRESET.get(a)
        if preset_id and module in preset_modules(preset_id):
            best = max(best, 100)
    return best


def _axis_score_role(module: str, role: str) -> int:
    aff = ROLE_AFFINITY.get(role, frozenset())
    return 100 if module in aff else 30


def _axis_score_phase(module: str, phases: list[str]) -> int:
    best = 0
    for p in phases:
        if module in PHASE_AFFINITY.get(p, frozenset()):
            best = max(best, 100)
    return best


def _axis_score_size(module: str, size: str) -> int:
    base = SIZE_BASE.get(size, 50)
    if module in ENTERPRISE_MODULES:
        # Enterprise modules scale hard with size.
        return base
    return 60  # size-neutral for the rest


def _axis_score_region(module: str, region: str) -> int:
    # Only the regional pack is region-sensitive; everything else is
    # region-neutral so region never suppresses a real module.
    if module == REGION_PACK.get(region):
        return 100
    return 50


def compute_module_score(
    module: str,
    activities: list[str],
    role: str,
    phases: list[str],
    size: str,
    region: str,
) -> int:
    """Weighted 0–100 aggregate for one module under a profile (doc §2.3)."""

    parts = {
        "activity": _axis_score_activity(module, activities),
        "role": _axis_score_role(module, role),
        "phase": _axis_score_phase(module, phases),
        "size": _axis_score_size(module, size),
        "region": _axis_score_region(module, region),
    }
    return round(sum(parts[a] * w for a, w in AXIS_WEIGHTS.items()))


def _phase_of(module: str) -> str:
    if module in ALWAYS_ON:
        return "setup"
    for phase in PHASE_ORDER:
        if module in PHASE_AFFINITY.get(phase, frozenset()):
            return phase
    return "construction"  # sensible default bucket


def build_project_modules(
    *,
    all_modules: list[str],
    preset: str,
    activities: list[str],
    phases: list[str],
    role: str,
    size: str,
    region: str,
) -> list[ModuleAssignment]:
    """Resolve a profile into the full per-project module assignment list.

    Deterministic spine:
      1. ALWAYS_ON  → must / core
      2. region pack → must / region
      3. preset set  → must / preset
    Then a scoring pass tags every *other* known module recommended /
    optional / hidden. Hidden modules are still returned (enabled=False,
    tier=hidden) so the "Available more / Advanced" view can list them
    without a second source of truth.
    """

    chosen: dict[str, ModuleAssignment] = {}

    for m in ALWAYS_ON:
        chosen[m] = ModuleAssignment(
            module_name=m, enabled=True, tier="must", score=SCORE_CORE,
            phase="setup", source="core", why="Core infrastructure",
        )

    pack = REGION_PACK.get(region)
    if pack:
        chosen[pack] = ModuleAssignment(
            module_name=pack, enabled=True, tier="must", score=SCORE_CORE,
            phase="setup", source="region",
            why=f"Regional pack for {region}",
        )

    if preset and preset != "custom":
        for m in PRESETS.get(preset, {}).get("modules", ()):  # type: ignore[call-overload]
            if m in chosen:
                continue
            chosen[m] = ModuleAssignment(
                module_name=m, enabled=True, tier="must", score=SCORE_PRESET,
                phase=_phase_of(m), source="preset",
                why=f"Selected by preset “{preset}”",
            )

    for m in all_modules:
        if m in chosen:
            continue
        score = compute_module_score(m, activities, role, phases, size, region)
        if score >= THRESHOLD_RECOMMENDED:
            tier: Tier = "recommended"
            enabled = True
        elif score >= THRESHOLD_OPTIONAL:
            tier = "optional"
            enabled = False
        else:
            tier = "hidden"
            enabled = False
        chosen[m] = ModuleAssignment(
            module_name=m, enabled=enabled, tier=tier, score=score,
            phase=_phase_of(m), source="score",
            why=f"Score {score} (activity/role/phase/size/region)",
        )

    return sorted(
        chosen.values(),
        key=lambda a: (PHASE_ORDER.index(a.phase) if a.phase in PHASE_ORDER else 99, -a.score, a.module_name),
    )


def assign_ordinals(
    assignments: list[ModuleAssignment],
) -> dict[str, int | None]:
    """Global sequential numbering (doc §3.2) over *enabled, non
    cross-cutting* modules, in phase order. Cross-cutting + disabled get
    ``None`` (no number — they live in the "Сквозные" / "Available more"
    sections)."""

    ordinals: dict[str, int | None] = {}
    n = 0
    for a in assignments:
        if a.enabled and a.module_name not in CROSS_CUTTING:
            n += 1
            ordinals[a.module_name] = n
        else:
            ordinals[a.module_name] = None
    return ordinals
