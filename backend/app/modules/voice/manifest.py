# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Voice-capture module manifest."""

from app.core.module_loader import ModuleManifest
from app.modules.voice.data_paths import DATA_PATHS

manifest = ModuleManifest(
    name="oe_voice",
    version="0.1.0",
    display_name="Voice Capture",
    description=(
        "Turn a spoken or typed site note into a structured draft - a daily-diary note, a "
        "defect, or a task - that the worker reviews and confirms before it is saved. Records "
        "in the browser, transcribes and translates, and degrades gracefully with no AI keys."
    ),
    author="OpenConstructionERP Core Team",
    category="core",
    depends=["oe_users", "oe_projects", "oe_phonelog"],
    auto_install=True,
    enabled=True,
    data_paths=DATA_PATHS,
)
