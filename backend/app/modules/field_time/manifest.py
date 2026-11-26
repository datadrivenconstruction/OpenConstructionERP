# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""Field Time module manifest."""

from app.core.module_loader import ModuleManifest
from app.modules.field_time.data_paths import DATA_PATHS

manifest = ModuleManifest(
    name="oe_field_time",
    version="1.0.0",
    display_name="Field Time",
    description=(
        "Cost-coded, signed field timesheets for labour and plant. The foreman's "
        "end-of-day record of who and which machine worked, how long, and against "
        "which BOQ cost code - the authoritative source of actual labour and plant "
        "hours for payroll and the cost / EVM model."
    ),
    author="OpenConstructionERP Core Team",
    category="business",
    # Real foreign keys into projects (owner), resources (labour), equipment
    # (plant) and variations (daywork order). Declaring them as hard
    # dependencies keeps the load order correct and stops any of those tables
    # from being disabled while a timesheet still references them.
    #
    # Field diary owns the shared field sync ledger, the table that remembers
    # which offline entry keys have already been applied. Without it a day
    # recorded on a phone would be booked again on every replay, so it is a hard
    # dependency and not a best-effort read.
    depends=[
        "oe_projects",
        "oe_resources",
        "oe_equipment",
        "oe_variations",
        "oe_field_diary",
    ],
    auto_install=True,
    enabled=True,
    data_paths=DATA_PATHS,
)
