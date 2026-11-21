# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Module builder manifest."""

from app.core.data_paths import DataPaths
from app.core.module_loader import InferenceDeclaration, InferenceRole, ModuleManifest

manifest = ModuleManifest(
    name="oe_module_builder",
    version="1.0.0",
    display_name="Module Builder",
    description="Describe a module in a few steps and have the platform build and install it.",
    author="OpenConstructionERP Core Team",
    category="core",
    depends=[],
    auto_install=True,
    enabled=True,
    inference=InferenceDeclaration(
        role=InferenceRole.CALLS_MODEL,
        what="A module specification - tables, fields, relations - inferred from a sentence the user typed",
        basis=(
            "service.py sends the description to the shared provider layer and parses a specification "
            "out of what comes back. The model never writes Python: the generator turns the "
            "specification into files by template, the person reads every file on the review step, and "
            "nothing is written to disk until they press install. Worth saying twice because this "
            "module is how somebody else's module comes to exist, and a module installed at runtime "
            "is outside the register this field feeds. The generator therefore writes a declaration "
            "into every module it produces, so a built module arrives declared rather than silent"
        ),
    ),
    data_paths=DataPaths(reason="Generates and installs new modules; owns no project records of its own"),
)
