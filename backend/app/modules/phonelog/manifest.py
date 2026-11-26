# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Phone-log module manifest."""

from app.core.module_loader import InferenceDeclaration, InferenceRole, ModuleManifest
from app.modules.phonelog.data_paths import DATA_PATHS

manifest = ModuleManifest(
    name="oe_phonelog",
    version="0.1.0",
    display_name="Phone Log",
    description=(
        "Capture phone calls, voice notes, and verbal instructions as dispute-ready records - "
        "parties, direction, duration, a short summary, and the instruction-bearing sentences "
        "pulled out of the transcript - so a spoken instruction is on the project record"
    ),
    author="OpenConstructionERP Core Team",
    category="core",
    depends=["oe_users", "oe_projects"],
    auto_install=True,
    enabled=True,
    inference=InferenceDeclaration(
        role=InferenceRole.CALLS_MODEL,
        what=(
            "A recording of a call or a site conversation into a transcript, and that transcript "
            "into a draft protocol: participants, a summary, decisions, and action items with an "
            "owner and a due date"
        ),
        basis=(
            "transcription.py posts the audio straight to a hosted speech-to-text endpoint, which "
            "is a call that a survey rooted at the shared provider layer would not see, and the "
            "extraction pass after it goes through oe_ai. Everything produced is a draft the user "
            "edits before it becomes a record. The module name describes filing, not inference"
        ),
    ),
    data_paths=DATA_PATHS,
)
