# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Professional-credentials registry module manifest."""

from app.core.module_loader import ModuleManifest
from app.modules.credentials.data_paths import DATA_PATHS

manifest = ModuleManifest(
    name="oe_credentials",
    version="0.2.0",
    display_name="Credentials Registry",
    description=(
        "Project register of the professional credentials a delivery relies "
        "on - licences, certifications, statutory memberships, professional "
        "indemnity, registrations and training - with validity windows, "
        "renewal reminders and optional statutory-notification obligations. "
        "Records what the project requires of whom, and reports who may not "
        "work today: which credentials are missing, which have lapsed past "
        "their grace period, and which expire in the days ahead. "
        "Jurisdiction-neutral: the register tracks what a credential is and "
        "when it is valid; regional packs supply the country-specific "
        "vocabularies."
    ),
    author="OpenConstructionERP Core Team",
    category="core",
    depends=["oe_users", "oe_projects"],
    auto_install=True,
    enabled=True,
    data_paths=DATA_PATHS,
)
