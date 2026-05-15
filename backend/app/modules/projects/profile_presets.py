# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Project-creation wizard — preset library + core/region maps.

This is the *deterministic* layer of the profile→modules mapping. A
preset is a named set of module folder names (the real
``app/modules/<name>`` ids). The scoring engine (:mod:`profile_scoring`)
layers *recommended/optional* suggestions on top, but the preset's
explicit set is always ``must``-tier so the result is predictable and
testable — the Jira-template model the design doc settled on
("preset = a set of feature flags you can change later").

Module-name mapping note: the concept doc uses friendly names
(``ai_estimation``, ``cost_database``, ``schedule_4d`` …). Here they
are mapped to the actual module folder ids:

    ai_estimation   → ai          cost_database   → costs
    cost_model_5d   → costmodel   field_reports   → fieldreports
    schedule_4d     → schedule    change_orders   → changeorders
    compliance_dsl  → compliance  eac_v2          → eac
    evm             → full_evm    i18n            → i18n_foundation
    punch_list      → punchlist

Numbers in the doc (12 / 14 / 38 …) are explicitly *targets, not spec*
(doc CAVEAT #2); the real count is ``len(ALWAYS_ON ∪ extras ∪ region)``.
"""

from __future__ import annotations

from typing import TypedDict

# ── Always-on core (doc §2.6) — infrastructure every project gets ────────
ALWAYS_ON: tuple[str, ...] = (
    "projects",
    "users",
    "teams",
    "contacts",
    "dashboards",
    "notifications",
    "search",
    "documents",
    "uploads",
    "tasks",
    "collaboration",
    "erp_chat",
    "i18n_foundation",
    "admin",
    "reporting",
)

# ── Cross-cutting (doc §3.3) — shown in the "Сквозные ∞" section, no
# numbered position. Included when the profile/preset selects them.
CROSS_CUTTING: frozenset[str] = frozenset(
    {"finance", "risk", "safety", "carbon"}
)

# ── Region → regional pack module (doc §2.6, auto-added) ─────────────────
REGION_PACK: dict[str, str] = {
    "dach": "dach_pack",
    "uk": "uk_pack",
    "us": "us_pack",
    "russia_cis": "russia_pack",
    "latam": "latam_pack",
    "mena": "middle_east_pack",
    "asia_pacific": "asia_pac_pack",
    "india": "india_pack",
}


class PresetMeta(TypedDict):
    id: str
    icon: str
    label_key: str
    label_en: str
    blurb_en: str
    modules: tuple[str, ...]


# ── The 8 presets (doc §2.7), mapped to real module folder ids ───────────
# ``modules`` lists only the *extra* modules — ALWAYS_ON is unioned in by
# the service so a preset author never has to repeat the 15 core ids.
PRESETS: dict[str, PresetMeta] = {
    "bim_quality_check": {
        "id": "bim_quality_check",
        "icon": "ScanLine",
        "label_key": "project_wizard.preset.bim_quality_check",
        "label_en": "BIM Quality Check",
        "blurb_en": "Check BIM model quality: clash detection, validation, compliance.",
        "modules": (
            "bim_hub", "bim_requirements", "validation", "compliance_ai",
            "compliance_docs", "match_elements", "markups", "cde", "eac",
            "ncr", "inspections", "opencde_api",
        ),
    },
    "cost_estimation_only": {
        "id": "cost_estimation_only",
        "icon": "Calculator",
        "label_key": "project_wizard.preset.cost_estimation_only",
        "label_en": "Cost Estimation Only",
        "blurb_en": "BoQ, takeoff and estimates without construction management.",
        "modules": (
            "boq", "catalog", "ai", "takeoff", "dwg_takeoff", "costs",
            "costmodel", "assemblies", "cost_match", "tendering",
            "changeorders", "requirements", "match_elements",
        ),
    },
    "tender_preparation": {
        "id": "tender_preparation",
        "icon": "Gavel",
        "label_key": "project_wizard.preset.tender_preparation",
        "label_en": "Tender Preparation",
        "blurb_en": "Prepare and submit tenders, manage RFQs.",
        "modules": (
            "tendering", "bid_management", "rfq_bidding", "boq", "catalog",
            "contracts", "subcontractors", "correspondence", "transmittals",
            "submittals", "requirements", "ai", "costmodel",
        ),
    },
    "full_construction_lifecycle": {
        "id": "full_construction_lifecycle",
        "icon": "Building2",
        "label_key": "project_wizard.preset.full_construction_lifecycle",
        "label_en": "Full Construction Lifecycle",
        "blurb_en": "Full cycle from tender to handover.",
        "modules": (
            "bim_hub", "boq", "catalog", "costs", "costmodel", "schedule",
            "schedule_advanced", "finance", "procurement", "changeorders",
            "fieldreports", "daily_diary", "inspections", "ncr",
            "punchlist", "safety", "hse_advanced", "risk", "meetings",
            "rfi", "transmittals", "submittals", "equipment", "resources",
            "jobs", "eac", "full_evm", "tendering", "subcontractors",
            "contracts", "validation", "match_elements",
        ),
    },
    "property_development": {
        "id": "property_development",
        "icon": "Landmark",
        "label_key": "project_wizard.preset.property_development",
        "label_en": "Property Development",
        "blurb_en": "Development: finance, sales, portfolio.",
        "modules": (
            "property_dev", "crm", "finance", "contracts", "portal",
            "variations", "schedule_advanced", "risk", "carbon",
            "costmodel", "procurement", "tendering", "project_intelligence",
            "bid_management", "subcontractors",
        ),
    },
    "site_management": {
        "id": "site_management",
        "icon": "HardHat",
        "label_key": "project_wizard.preset.site_management",
        "label_en": "Site Management",
        "blurb_en": "Field work: daily diary, inspections, NCR.",
        "modules": (
            "fieldreports", "daily_diary", "inspections", "ncr",
            "punchlist", "safety", "hse_advanced", "markups", "equipment",
            "jobs", "meetings", "rfi", "schedule",
        ),
    },
    "bim_consulting": {
        "id": "bim_consulting",
        "icon": "GraduationCap",
        "label_key": "project_wizard.preset.bim_consulting",
        "label_en": "BIM Consulting",
        "blurb_en": "BIM consulting: EIR / BEP / audit.",
        "modules": (
            "bim_hub", "bim_requirements", "validation", "compliance",
            "compliance_ai", "compliance_docs", "cde", "markups",
            "opencde_api", "match_elements",
        ),
    },
    "facility_management": {
        "id": "facility_management",
        "icon": "Wrench",
        "label_key": "project_wizard.preset.facility_management",
        "label_en": "Facility Management / Operations",
        "blurb_en": "Operations and asset management.",
        "modules": (
            "service", "equipment", "inspections", "safety", "carbon",
            "cde", "bim_hub", "opencde_api", "qms",
        ),
    },
    "custom": {
        "id": "custom",
        "icon": "Plus",
        "label_key": "project_wizard.preset.custom",
        "label_en": "Empty / Custom",
        "blurb_en": "Start from core only and add modules as you go.",
        "modules": (),
    },
}


def preset_modules(preset_id: str) -> set[str]:
    """Full module set for a preset: ALWAYS_ON ∪ the preset's extras.

    Unknown / "custom" preset → just the always-on core.
    """

    meta = PRESETS.get(preset_id)
    base = set(ALWAYS_ON)
    if meta is None:
        return base
    return base | set(meta["modules"])
