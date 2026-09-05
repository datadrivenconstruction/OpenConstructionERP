# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""Post-calculation module manifest."""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_postcalc",
    version="1.0.0",
    display_name="Post-calculation",
    description=(
        "Reconciles the estimate against site actuals into planned-vs-actual "
        "labour productivity and material cost: a factor per BoQ line and per "
        "resource category, the material really consumed against what the "
        "estimate allowed, a project rollup, a ranked list of productivity "
        "factors to feed back into estimating, and the same comparison rolled "
        "up per production norm so a norm library can be corrected from what "
        "the jobs priced with it actually cost. Reads existing BoQ positions, "
        "field timesheets, progress readings and the site material ledger; a "
        "stateless analysis layer that adds no table."
    ),
    author="OpenConstructionERP Core Team",
    category="business",
    # The estimate side (BoQ positions and their stored resource split) is
    # required. The per-norm rollup reads its measured side through the cost
    # model's position-actuals assembler rather than reimplementing the join
    # between the money spine and the physical one, so that is required too.
    # Field-time, progress and the site material ledger supply the actuals, and
    # the norm library supplies the live predicted side; they are optional so
    # the report still renders when any of them is absent or disabled, saying it
    # does not know rather than reporting a zero.
    depends=["oe_boq", "oe_costmodel"],
    optional_depends=[
        "oe_field_time",
        "oe_progress",
        "oe_site_inventory",
        "oe_norm_expansion",
    ],
    auto_install=True,
    enabled=True,
)
