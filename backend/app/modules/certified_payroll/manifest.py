# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Module manifest for oe_certified_payroll."""

from app.core.module_loader import ModuleManifest
from app.modules.certified_payroll.data_paths import DATA_PATHS

manifest = ModuleManifest(
    name="oe_certified_payroll",
    version="1.0.0",
    display_name="Certified Payroll",
    display_name_i18n={
        "de": "Zertifizierte Lohnliste",
        "ru": "Заверенная ведомость по зарплате",
    },
    description=(
        "Weekly certified payroll for public works: the wage determination on file, the trade classification "
        "each worker works under, the week's hours by day with basic wage and fringe benefit held apart, and "
        "the signed statement of compliance the awarding body reads. Extends the payroll module rather than "
        "duplicating it - the hours and the deductions stay where they already are."
    ),
    author="OpenConstructionERP Core Team",
    category="compliance",
    depends=["oe_payroll", "oe_projects", "oe_resources"],
    # Off unless a user turns it on, matching the regional packs. Most of this
    # platform's users work under no such obligation, and a certified payroll
    # surface on every project would be this module answering a legal question
    # nobody asked it.
    auto_install=False,
    enabled=True,
    data_paths=DATA_PATHS,
)
