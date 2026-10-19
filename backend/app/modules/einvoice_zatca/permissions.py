# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""ZATCA EGS unit permissions.

``RequirePermission`` denies a key no module registered, so without this file
the onboarding endpoints are admin-only in production while every admin test
still passes.

* ``read`` lists units and the module's facts; it never returns a key or a secret.
* ``manage`` creates a unit and prepares its CSR. Reversible: a unit that has not
  been issued a CSID can be revoked.
* ``onboard`` spends the taxpayer's one-time password and obtains, renews or
  revokes a certificate. MANAGER, because the certificate is what makes a
  document legally the taxpayer's.
"""

from app.core.permissions import Role, permission_registry


def register_einvoice_zatca_permissions() -> None:
    """Register permissions for the ZATCA module."""
    permission_registry.register_module_permissions(
        "einvoice_zatca",
        {
            "einvoice_zatca.read": Role.VIEWER,
            "einvoice_zatca.manage": Role.EDITOR,
            "einvoice_zatca.onboard": Role.MANAGER,
        },
    )


__all__ = ["register_einvoice_zatca_permissions"]
