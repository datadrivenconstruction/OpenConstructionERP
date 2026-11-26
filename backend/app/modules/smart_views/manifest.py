# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Smart Views module manifest."""

from app.core.module_loader import InferenceDeclaration, InferenceRole, ModuleManifest
from app.modules.smart_views.data_paths import DATA_PATHS

manifest = ModuleManifest(
    name="oe_smart_views",
    version="1.0.0",
    display_name="Smart Views",
    description=(
        "Rule-based, re-evaluating BIM viewer presets. Selectors run "
        "against canonical element properties at view-load time so a "
        "view authored on one model revision keeps working after the "
        "geometry has been re-imported - and the same view can be "
        "applied to any model that exposes the right properties."
    ),
    author="OpenConstructionERP Core Team",
    category="core",
    depends=["oe_projects", "oe_users", "oe_bim_hub"],
    auto_install=True,
    enabled=True,
    inference=InferenceDeclaration(
        role=InferenceRole.RULE_BASED,
        what="Assigns a colour and a visibility state to every element of a model, from rules the user wrote",
        basis=(
            "evaluator.py is a pure function of the rules and the element properties. Every operator "
            "is a hard-coded predicate, there is no eval and no exec, and every getattr in the file "
            "names a literal attribute, so nothing a user writes in a rule selects code. Rule order "
            "is explicit and ties resolve by stable id, so the same rules over the same elements give "
            "the same answer on every run. Nothing is learned from data and no model is loaded or "
            "called. The word Smart in the name is the only thing here that suggests otherwise, which "
            "is exactly why this module is declared rather than left to be read by its name"
        ),
    ),
    data_paths=DATA_PATHS,
)
