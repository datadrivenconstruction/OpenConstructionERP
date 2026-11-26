# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Production-norm expansion module manifest."""

from app.core.module_loader import InferenceDeclaration, InferenceRole, ModuleManifest
from app.modules.norm_expansion.data_paths import DATA_PATHS

manifest = ModuleManifest(
    name="oe_norm_expansion",
    version="0.1.0",
    display_name="Production-Norm Expansion",
    description=(
        "Expands a work item and its quantity into unpriced resource demand - "
        "labor-hours, machine-hours and material quantities - from a library of "
        "production-norm coefficients, before any pricing is applied."
    ),
    author="OpenConstructionERP Core Team",
    category="core",
    depends=[],
    auto_install=True,
    enabled=True,
    inference=InferenceDeclaration(
        role=InferenceRole.CONSUMES_RESULT,
        what="The catalogue item behind a material name, which it asks oe_costs for",
        basis=(
            "Its own two tiers are an exact match on a normalised name, which is an identity test "
            "rather than a guess, and a fuzzy lexical score. Neither is a model. Where the name does "
            "not resolve it calls the matcher in oe_costs, and that matcher may run an embedder, so "
            "the model behind an answer this module reports belongs to oe_costs and so does the "
            "obligation for it"
        ),
    ),
    data_paths=DATA_PATHS,
)
