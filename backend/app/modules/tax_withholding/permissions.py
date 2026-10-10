# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Tax withholding permission definitions.

``RequirePermission`` denies a permission nothing registered, and the admin
role short-circuits above that check. A module without this file therefore
ships endpoints that only an admin can reach, and every admin-authenticated
test still passes - so the file is load-bearing rather than paperwork.

Three keys for the schemes, and the split follows who carries the consequence:

* ``tax_withholding.read`` is VIEWER. Knowing what was withheld from a payment
  is part of reading the payment.
* ``tax_withholding.write`` is EDITOR. Recording a party's standing and the
  deduction taken on a payment is ordinary commercial work.
* ``tax_withholding.manage`` is MANAGER, and covers the two things that are
  not. Editing a *scheme* changes the rate every future deduction is taken at,
  across every project at once; deleting a deduction or a standing removes the
  evidence behind a figure that has been remitted to a tax authority.

The statutory tax lines of a payment document have three keys of their own,
because seeing a figure, working on it and signing it are three different acts:

* ``tax_withholding.statutory_view`` is VIEWER. It also covers the category
  picker and the preview, which store nothing.
* ``tax_withholding.statutory_edit`` is EDITOR: choosing a category, marking a
  tax as not applicable, entering an amount with a reason.
* ``tax_withholding.statutory_confirm`` is MANAGER. Confirming freezes the
  figures a certificate and an e-invoice are printed from; reopening and
  voiding undo that, so they sit behind the same key.
"""

from app.core.permissions import Role, permission_registry


def register_tax_withholding_permissions() -> None:
    """Register permissions for the Tax Withholding module."""
    permission_registry.register_module_permissions(
        "tax_withholding",
        {
            "tax_withholding.read": Role.VIEWER,
            "tax_withholding.write": Role.EDITOR,
            "tax_withholding.manage": Role.MANAGER,
            "tax_withholding.statutory_view": Role.VIEWER,
            "tax_withholding.statutory_edit": Role.EDITOR,
            "tax_withholding.statutory_confirm": Role.MANAGER,
        },
    )
