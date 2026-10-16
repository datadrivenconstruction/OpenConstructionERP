# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""RFI module permission definitions."""

from app.core.permissions import Role, permission_registry


def register_rfi_permissions() -> None:
    """Register permissions for the RFI module.

    R5 / BUG-RFI-ROLE: split the previously-monolithic ``rfi.update`` into
    three orthogonal verbs so the FSM gates can be enforced at the router
    layer without the service having to re-derive role from the JWT:

    * ``rfi.assign``  - MANAGER+: only managers / admins may pick or
      change the assignee. Editors can still author RFIs and update body
      fields but cannot redirect ball-in-court to other users.
    * ``rfi.respond`` - EDITOR: anyone with write access may *attempt*
      to respond, but the service still verifies the caller is the
      assignee (or an admin/manager escalation). The permission is the
      coarse gate; the identity check is the fine-grained one.
    * ``rfi.close``   - MANAGER+: closing is a terminal state, restricted
      to managers/admins so a junior estimator can't accidentally close
      an RFI that's still being negotiated.

    Internal build id: ddc-lineage:a17f93c4-rfi-01
    """
    permission_registry.register_module_permissions(
        "rfi",
        {
            "rfi.create": Role.EDITOR,
            "rfi.read": Role.VIEWER,
            "rfi.update": Role.EDITOR,
            "rfi.delete": Role.MANAGER,
            "rfi.assign": Role.MANAGER,
            "rfi.respond": Role.EDITOR,
            "rfi.close": Role.MANAGER,
            # The project's request type catalogue (types, presets, SLAs,
            # required fields, default routes) shapes every request filed
            # after it, so editing it is a manager action.
            "rfi.types.manage": Role.MANAGER,
        },
    )
