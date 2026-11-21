# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Interface-register module manifest."""

from app.core.module_loader import ModuleManifest
from app.modules.interface_management.data_paths import DATA_PATHS

manifest = ModuleManifest(
    name="oe_interface_management",
    version="1.0.0",
    display_name="Interface Register",
    description=(
        "Coordination register for the interfaces (handshakes) between work "
        "packages, contractors and disciplines on a project - the standard tool "
        "on multi-package and multi-contractor jobs. Each interface records who "
        "OWNS it, who ACCEPTS or depends on it, the date it must be agreed by, "
        "its type (physical, functional, contractual, spatial, information, "
        "schedule) and its status (identified, open, in progress, agreed, closed, "
        "disputed, on hold), alongside the actions needed to close it. The module "
        "derives the per-status, per-priority and per-type counts, the overdue "
        "and disputed lists, the agreed percentage, the open action load, a "
        "per-work-package health view and a single overall health score, so a "
        "coordinator can see at a glance where the coordination risk sits."
    ),
    author="OpenConstructionERP Core Team",
    category="business",
    # Hard dep supplies the project scope every table foreign-keys into.
    depends=["oe_projects"],
    auto_install=True,
    enabled=True,
    data_paths=DATA_PATHS,
)
