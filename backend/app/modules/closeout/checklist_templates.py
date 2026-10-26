# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Declarative closeout checklist templates per project type.

Pure data - no DB access. ``CHECKLIST_TEMPLATES`` maps a project type to an
ordered list of slot definitions. When a package is created the service seeds
one :class:`CloseoutSlot` row per definition. This is the configurable
per-project-type checklist the design calls for; new project types or custom
checklists drop in here.

Slot definition keys:
    slot_key            stable identifier (unique within a template)
    title               human label (English; UI re-labels via i18n)
    category            grouping bucket for the dashboard table
    discipline          optional discipline hint (matches Document.discipline)
    is_required         counts toward completeness when True
    source_kind         cde_document | generated | external_url | manual_upload
    generated_artifact  cobie_xlsx | punch_closure_report | inspection_cert_pdf
    ordinal             display order within the template
"""

from __future__ import annotations

from typing import Any, TypedDict


class SlotDef(TypedDict, total=False):
    """One checklist slot definition (typed for clarity, plain dict at runtime)."""

    slot_key: str
    title: str
    category: str
    discipline: str | None
    is_required: bool
    source_kind: str
    generated_artifact: str | None
    ordinal: int


# Category buckets surfaced in the UI table.
CATEGORY_AS_BUILT = "as_built"
CATEGORY_OM = "om_manual"
CATEGORY_WARRANTY = "warranty"
CATEGORY_ASSET_REGISTER = "asset_register"
CATEGORY_PUNCH = "punch_closure"
CATEGORY_INSPECTION = "inspection"
CATEGORY_HS = "hs_file"
CATEGORY_COMMISSIONING = "commissioning"
CATEGORY_ACCEPTANCE = "acceptance"
CATEGORY_OTHER = "other"


def _slot(
    slot_key: str,
    title: str,
    category: str,
    *,
    discipline: str | None = None,
    is_required: bool = True,
    source_kind: str = "cde_document",
    generated_artifact: str | None = None,
    ordinal: int = 0,
) -> SlotDef:
    return {
        "slot_key": slot_key,
        "title": title,
        "category": category,
        "discipline": discipline,
        "is_required": is_required,
        "source_kind": source_kind,
        "generated_artifact": generated_artifact,
        "ordinal": ordinal,
    }


# Shared building blocks reused across project types.
_AS_BUILT = _slot("as_built_drawings", "As-built drawing set", CATEGORY_AS_BUILT, ordinal=10)
_OM_MANUAL = _slot("om_manual", "O&M manual", CATEGORY_OM, ordinal=20)
_WARRANTY = _slot("warranty", "Warranties and guarantees", CATEGORY_WARRANTY, ordinal=30)
_COBIE = _slot(
    "cobie_asset_register",
    "COBie / asset register",
    CATEGORY_ASSET_REGISTER,
    source_kind="generated",
    generated_artifact="cobie_xlsx",
    ordinal=40,
)
_PUNCH = _slot(
    "punch_closure",
    "Punch list closure evidence",
    CATEGORY_PUNCH,
    source_kind="generated",
    generated_artifact="punch_closure_report",
    ordinal=50,
)
_FINAL_INSPECTION = _slot(
    "final_inspection_cert",
    "Final inspection certificate",
    CATEGORY_INSPECTION,
    source_kind="generated",
    generated_artifact="inspection_cert_pdf",
    ordinal=60,
)
_HS_FILE = _slot("hs_file", "Health & safety file", CATEGORY_HS, ordinal=70)
_COMMISSIONING = _slot(
    "commissioning_certs",
    "Test and commissioning certificates",
    CATEGORY_COMMISSIONING,
    discipline="mechanical",
    ordinal=80,
)
_ACCEPTANCE = _slot(
    "signed_acceptance",
    "Signed acceptance certificate",
    CATEGORY_ACCEPTANCE,
    ordinal=95,
)


# Slots no template seeds by default; a project's quality concept adds them to its
# closeout package when the chosen documentation set asks for them. Defined here so
# every slot key keeps one owner.
EXTRA_SLOT_DEFS: list[SlotDef] = [
    _slot("fm_asset_dataset", "FM asset dataset", CATEGORY_ASSET_REGISTER, ordinal=45),
    _slot("training_record", "Operator training records", CATEGORY_OTHER, ordinal=85),
    _slot("authority_acceptance", "Authority acceptance certificates", CATEGORY_INSPECTION, ordinal=65),
]


CHECKLIST_TEMPLATES: dict[str, list[SlotDef]] = {
    "commercial": [
        _AS_BUILT,
        _OM_MANUAL,
        _WARRANTY,
        _COBIE,
        _PUNCH,
        _FINAL_INSPECTION,
        _HS_FILE,
        _COMMISSIONING,
        _ACCEPTANCE,
    ],
    "residential": [
        _AS_BUILT,
        _OM_MANUAL,
        _WARRANTY,
        _PUNCH,
        _FINAL_INSPECTION,
        _HS_FILE,
        _ACCEPTANCE,
        _slot(
            "epc_certificate",
            "Energy performance certificate",
            CATEGORY_OTHER,
            is_required=False,
            ordinal=90,
        ),
    ],
    "infrastructure": [
        _AS_BUILT,
        _OM_MANUAL,
        _WARRANTY,
        _COBIE,
        _PUNCH,
        _FINAL_INSPECTION,
        _HS_FILE,
        _COMMISSIONING,
        _ACCEPTANCE,
        _slot(
            "geotechnical_records",
            "Geotechnical and survey records",
            CATEGORY_OTHER,
            discipline="civil",
            is_required=False,
            ordinal=100,
        ),
    ],
    "fitout": [
        _AS_BUILT,
        _OM_MANUAL,
        _WARRANTY,
        _PUNCH,
        _FINAL_INSPECTION,
        _HS_FILE,
        _COMMISSIONING,
        _ACCEPTANCE,
    ],
    # A custom project gets a minimal spine the user extends with add-slot.
    "custom": [
        _AS_BUILT,
        _PUNCH,
        _FINAL_INSPECTION,
    ],
}


def template_for(project_type: str) -> list[SlotDef]:
    """Return the checklist slot definitions for a project type.

    Falls back to the ``commercial`` template for an unknown type so a
    package is never created with an empty checklist.
    """
    return CHECKLIST_TEMPLATES.get(project_type, CHECKLIST_TEMPLATES["commercial"])


def resolve_template_key(project_type: str) -> str:
    """Return the canonical template key actually used for a project type."""
    return project_type if project_type in CHECKLIST_TEMPLATES else "commercial"


# Human-readable category labels (English; UI overrides via i18n).
CATEGORY_LABELS: dict[str, str] = {
    CATEGORY_AS_BUILT: "As-built drawings",
    CATEGORY_OM: "O&M manuals",
    CATEGORY_WARRANTY: "Warranties",
    CATEGORY_ASSET_REGISTER: "Asset register / COBie",
    CATEGORY_PUNCH: "Punch closure",
    CATEGORY_INSPECTION: "Inspection certificates",
    CATEGORY_HS: "Health & safety file",
    CATEGORY_COMMISSIONING: "Commissioning",
    CATEGORY_ACCEPTANCE: "Acceptance",
    CATEGORY_OTHER: "Other",
}


def category_label(category: str) -> str:
    """Human label for a category bucket."""
    return CATEGORY_LABELS.get(category, category.replace("_", " ").title())


def as_public_dict(slot_def: SlotDef) -> dict[str, Any]:
    """Normalise a slot def into a plain dict (defensive copy)."""
    return dict(slot_def)
