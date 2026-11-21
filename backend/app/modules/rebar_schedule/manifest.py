# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Rebar schedule module manifest."""

from app.core.module_loader import ModuleManifest
from app.modules.rebar_schedule.data_paths import DATA_PATHS

manifest = ModuleManifest(
    name="oe_rebar_schedule",
    version="1.0.0",
    display_name="Rebar Schedule",
    description=(
        "Reinforcement bending schedules in the ABS interchange format - import "
        "the .abs file a CAD system writes alongside the printed schedule, "
        "validate every shape against the format's own rules, read the shapes "
        "back as bars, meshes, helices and lattice girders, summarise steel by "
        "bar diameter, and export the file the bending shop receives."
    ),
    author="OpenConstructionERP Core Team",
    category="business",
    depends=["oe_users", "oe_projects"],
    display_name_i18n={
        "de": "Biegeliste",
        "ru": "Ведомость арматуры",
        "es": "Despiece de armaduras",
    },
    auto_install=True,
    enabled=True,
    data_paths=DATA_PATHS,
)
