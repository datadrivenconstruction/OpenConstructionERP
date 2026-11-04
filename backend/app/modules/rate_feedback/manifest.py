# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Rate-feedback module manifest."""

from app.core.module_loader import InferenceDeclaration, InferenceRole, ModuleManifest

manifest = ModuleManifest(
    name="oe_rate_feedback",
    version="1.0.0",
    display_name="Rate feedback",
    description=(
        "Compares what closed projects really cost and how many man-hours they took against the "
        "rate of the cost item each bill line was priced from, and proposes an updated rate and "
        "hours per unit with a sample size and a confidence score. Nothing changes until an "
        "estimator confirms each proposal."
    ),
    author="OpenConstructionERP Core Team",
    category="business",
    depends=["oe_costs", "oe_boq", "oe_postcalc", "oe_projects"],
    optional_depends=["oe_field_time"],
    auto_install=True,
    enabled=True,
    inference=InferenceDeclaration(
        role=InferenceRole.RULE_BASED,
        what="A suggested cost item rate and hours per unit, from the actuals of closed projects",
        basis=(
            "rate_math.py pools actual over earned labour and material money per cost item with "
            "fixed arithmetic and scores confidence from the project count and the spread between "
            "projects. Nothing is learned and no model is loaded; a person confirms every change."
        ),
    ),
)
