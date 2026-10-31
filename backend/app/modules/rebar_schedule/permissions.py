# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Rebar schedule permission definitions."""

from app.core.permissions import Role, permission_registry


def register_rebar_schedule_permissions() -> None:
    """Register permissions for the rebar schedule module.

    Reading a schedule is a viewer action. Importing a file and deleting an
    import are called out separately from each other: importing is routine
    editor work, while deleting takes a whole bending schedule out of the
    project's record, and the bending shop may already have worked from it.
    """
    permission_registry.register_module_permissions(
        "rebar_schedule",
        {
            "rebar_schedule.read": Role.VIEWER,
            "rebar_schedule.import": Role.EDITOR,
            "rebar_schedule.edit": Role.EDITOR,
            "rebar_schedule.delete": Role.MANAGER,
        },
    )
