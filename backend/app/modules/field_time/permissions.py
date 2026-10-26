# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""Field Time module permission definitions."""

from app.core.permissions import Role, permission_registry


def register_field_time_permissions() -> None:
    """Register permissions for the field time module.

    Reading a timesheet needs viewer access; creating / editing a draft needs
    editor; approving (which posts hours to payroll / cost actuals and, for
    daywork, mints a signed daywork sheet) and reversing an approved timesheet
    are manager-level actions.
    """
    permission_registry.register_module_permissions(
        "field_time",
        {
            "field_time.create": Role.EDITOR,
            "field_time.read": Role.VIEWER,
            "field_time.update": Role.EDITOR,
            "field_time.delete": Role.MANAGER,
            "field_time.approve": Role.MANAGER,
            # Time clock: a clock-in is a field write; drawing site fences,
            # retention and approving flagged clocks are a supervisor's job.
            "field_time.clock": Role.EDITOR,
            "field_time.clock_admin": Role.MANAGER,
        },
    )
