# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Payment release permission definitions.

* ``payment_release.read`` is VIEWER: reading the ledger and the register is part of reading the project's costs.
* ``payment_release.write`` is EDITOR: payment terms, an invoice's kind, contract and deductions are commercial
  data entry.
* ``payment_release.release`` is MANAGER: confirming a release, reopening it and posting retention paid back
  commit money, so they sit behind the key a person signs for.
"""

from app.core.permissions import Role, permission_registry


def register_payment_release_permissions() -> None:
    """Register permissions for the Payment Release module."""
    permission_registry.register_module_permissions(
        "payment_release",
        {
            "payment_release.read": Role.VIEWER,
            "payment_release.write": Role.EDITOR,
            "payment_release.release": Role.MANAGER,
        },
    )
