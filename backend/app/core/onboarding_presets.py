"""Company-type presets for the onboarding wizard.

Each preset defines which modules are enabled by default for a given
company profile.  The frontend sends the chosen ``company_type`` key
and receives the corresponding module list, which the user can then
customise before saving.

The module identifiers match the keys used in the frontend
``useModuleStore`` (e.g. ``"schedule"``, ``"tendering"``).
"""

from __future__ import annotations

from typing import Any

# ── Module identifiers ────────────────────────────────────────────────────────
# Keep in sync with frontend sidebar moduleKey / _registry module IDs.

_ALL_MODULES: list[str] = [
    # Core estimation
    "boq",
    "projects",
    "costs",
    "assemblies",
    "catalog",
    "templates",
    "validation",
    # Takeoff & AI
    "takeoff",
    "pdf-takeoff",
    "ai-estimate",
    "advisor",
    "data-explorer",
    "bim",
    # Planning
    "schedule",
    "5d",
    "tasks",
    # Finance & Procurement
    "finance",
    "procurement",
    "tendering",
    "changeorders",
    # Communication
    "contacts",
    "meetings",
    "rfi",
    "submittals",
    "transmittals",
    "correspondence",
    # Documents
    "documents",
    "cde",
    "photos",
    "markups",
    # Quality & Safety
    "inspections",
    "ncr",
    "safety",
    "punchlist",
    "risks",
    # Field
    "field-reports",
    "requirements",
    # Reports & Analytics
    "reports",
    "reporting",
    "analytics",
    # Modules & Integrations
    "sustainability",
    "cost-benchmark",
    "collaboration",
    "risk-analysis",
]

# ── Preset definitions ────────────────────────────────────────────────────────


class CompanyPreset:
    """Immutable descriptor for a company-type onboarding preset."""

    __slots__ = ("key", "label", "description", "icon", "enabled_modules")

    def __init__(
        self,
        key: str,
        label: str,
        description: str,
        icon: str,
        enabled_modules: list[str],
    ) -> None:
        self.key = key
        self.label = label
        self.description = description
        self.icon = icon
        self.enabled_modules = enabled_modules

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "description": self.description,
            "icon": self.icon,
            "enabled_modules": self.enabled_modules,
            "module_count": len(self.enabled_modules),
        }


COMPANY_PRESETS: dict[str, CompanyPreset] = {
    "general_contractor": CompanyPreset(
        key="general_contractor",
        label="General Contractor",
        description="We build projects — estimation, procurement, site management",
        icon="Building2",
        enabled_modules=[
            "boq",
            "projects",
            "costs",
            "assemblies",
            "catalog",
            "templates",
            "schedule",
            "finance",
            "procurement",
            "safety",
            "inspections",
            "punchlist",
            "field-reports",
            "tasks",
            "meetings",
            "documents",
            "risks",
            "changeorders",
            "contacts",
            "reports",
            "reporting",
            "analytics",
            "validation",
            "photos",
            "ncr",
            "requirements",
        ],
    ),
    "estimator": CompanyPreset(
        key="estimator",
        label="Estimator / Cost Consultant",
        description="We focus on cost estimation and quantity takeoff",
        icon="Calculator",
        enabled_modules=[
            "boq",
            "projects",
            "costs",
            "assemblies",
            "catalog",
            "templates",
            "takeoff",
            "pdf-takeoff",
            "ai-estimate",
            "advisor",
            "validation",
            "reports",
            "reporting",
            "analytics",
            "data-explorer",
            "documents",
            "cost-benchmark",
        ],
    ),
    "project_management": CompanyPreset(
        key="project_management",
        label="Project Management Firm",
        description="We manage large projects — planning, communication, documents",
        icon="ClipboardList",
        enabled_modules=[
            "projects",
            "schedule",
            "tasks",
            "meetings",
            "finance",
            "procurement",
            "documents",
            "cde",
            "transmittals",
            "rfi",
            "submittals",
            "correspondence",
            "risks",
            "changeorders",
            "reporting",
            "contacts",
            "reports",
            "analytics",
            "markups",
            "photos",
            "field-reports",
            "requirements",
            "inspections",
        ],
    ),
    "architecture_engineering": CompanyPreset(
        key="architecture_engineering",
        label="Architecture / Engineering Office",
        description="We design buildings — BIM, documents, CDE",
        icon="Pencil",
        enabled_modules=[
            "projects",
            "documents",
            "cde",
            "bim",
            "transmittals",
            "rfi",
            "submittals",
            "correspondence",
            "takeoff",
            "pdf-takeoff",
            "boq",
            "costs",
            "data-explorer",
            "markups",
            "photos",
            "reports",
            "validation",
            "sustainability",
        ],
    ),
    "full_enterprise": CompanyPreset(
        key="full_enterprise",
        label="Full Enterprise",
        description="We need everything — full construction lifecycle",
        icon="Boxes",
        enabled_modules=list(_ALL_MODULES),
    ),
}


def get_preset(company_type: str) -> CompanyPreset | None:
    """Return a preset by key, or ``None`` if unknown."""
    return COMPANY_PRESETS.get(company_type)


def get_all_presets() -> list[dict[str, Any]]:
    """Return all presets as serialisable dicts (for the GET endpoint)."""
    return [p.to_dict() for p in COMPANY_PRESETS.values()]
