# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Payroll module manifest."""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_payroll",
    version="0.1.0",
    display_name="Payroll",
    description=(
        "Draft payroll batches from field labour - aggregates site workforce "
        "and field-diary hours per worker/date into entries (hours x rate). Export periods "
        "turn approved timesheets into pay lines by country overtime and allowance rules, lock "
        "against edits, export CSV, Excel, LODAS or JSON and post labour cost with burden."
    ),
    author="OpenConstructionERP Core Team",
    category="core",
    depends=["oe_projects", "oe_fieldreports", "oe_resources"],
    optional_depends=["oe_field_time", "oe_costmodel", "oe_notifications", "oe_certified_payroll"],
    auto_install=True,
    enabled=True,
)
