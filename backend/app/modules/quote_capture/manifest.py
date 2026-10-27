# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Quote​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ capture module manifest."""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_quote_capture",
    version="1.0.0",
    display_name="Quote Capture and Levelling",
    description=(
        "Reads supplier and subcontractor quotes from PDF, scanned PDF, Excel or email text: header, line items "
        "and conditions, each value with a confidence score and a source anchor shown beside the document. Matches "
        "the lines to the tender package scope, normalises units and number formats per locale, flags exclusions, "
        "qualifications and escalation clauses, and levels several quotes against the scope with plug rates for "
        "scope gaps. After human review a quote becomes a bid in the tender comparison, a supplier price list or "
        "a draft purchase order, with the trail of machine against human values. Works without AI on a rules "
        "parser; uses the configured AI provider when there is one."
    ),
    author="OpenConstructionERP Core Team",
    category="business",
    depends=["oe_projects", "oe_tendering"],
    optional_depends=["oe_ai", "oe_boq", "oe_procurement", "oe_supplier_catalogs"],
    auto_install=True,
    enabled=True,
)
