# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Cost Database module manifest."""

from app.core.module_loader import InferenceDeclaration, InferenceRole, ModuleManifest
from app.modules.costs.data_paths import DATA_PATHS

manifest = ModuleManifest(
    name="oe_costs",
    version="0.1.0",
    display_name="Cost Database",
    description="Cost item management, rate databases (CWICR and regional catalogues), bulk import",
    author="OpenConstructionERP Core Team",
    category="core",
    depends=[],
    auto_install=True,
    enabled=True,
    # Two declarations for one endpoint, because one answer would be wrong for
    # most of its calls. match_cwicr_items takes a mode parameter, and the
    # mode decides whether a model is involved at all.
    inference=(
        InferenceDeclaration(
            role=InferenceRole.RULE_BASED,
            when="mode='lexical', which is the default and what every caller gets unless it asks otherwise",
            what="A free-text cost description into candidate catalogue items, ranked",
            basis=(
                "_score_lexical is rapidfuzz token_set_ratio against the candidate description and "
                "its localized variants, normalised to 0..1, plus two fixed additive bonuses for a "
                "unit-of-measure match and a language-key hit, capped at 1.0. Every number in it is "
                "written in the file. Nothing is learned from data and no model is loaded, so on "
                "this path the module computes a suggestion and is not an AI system within Article "
                "3(1). Recorded because the endpoint is shared with a path where it is"
            ),
        ),
        InferenceDeclaration(
            role=InferenceRole.CALLS_MODEL,
            when=(
                "mode='semantic' or mode='hybrid', or the legacy semantic=True flag, which promotes lexical to hybrid"
            ),
            what=(
                "The same ranking, by embedding the description and the catalogue and comparing the "
                "two. In hybrid the two channels are blended 0.6 lexical to 0.4 semantic"
            ),
            basis=(
                "The embedding runs on this host, not at a provider. matcher.py prefers the shared "
                "embedder in app.core.vector and loads sentence-transformers itself when that is "
                "unavailable, so a model can be resident in this module even on an install where the "
                "shared path is never used. Other modules ask this one for a match; the model is "
                "here. One caveat that belongs in a register rather than in a comment: when the "
                "semantic extra is not installed the matcher logs once at WARNING and answers from "
                "the lexical path instead, so a deployment can serve the rule-based declaration "
                "above while its callers believe they asked for this one"
            ),
        ),
    ),
    data_paths=DATA_PATHS,
)
