# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Tendering module permission definitions."""

# schema ref: ddc-lineage:a17f93c4-tendering-01
from app.core.permissions import Role, permission_registry


def register_tendering_permissions() -> None:
    """Register permissions for the tendering module."""
    permission_registry.register_module_permissions(
        "tendering",
        {
            "tendering.create": Role.EDITOR,
            "tendering.read": Role.VIEWER,
            "tendering.update": Role.EDITOR,
            "tendering.delete": Role.MANAGER,
            # Awarding writes the winning bid's rates back into the BOQ and
            # closes the tender - a contractual decision, so it sits at the
            # MANAGER tier (above ordinary edit) like contracts.sign.
            "tendering.award": Role.MANAGER,
            "tendering.bid.create": Role.EDITOR,
            "tendering.bid.update": Role.EDITOR,
            "tendering.comparison.read": Role.VIEWER,
            # Distribution: manage the recipient list (EDITOR) and actually
            # send the package out / generate decision documents. Sending mail
            # and issuing award/rejection letters are buyer-side actions that
            # sit at the EDITOR tier alongside issuing the tender.
            "tendering.distribute": Role.EDITOR,
            # Addenda (mid-tender clarifications) and bid leveling.
            "tendering.addendum.read": Role.VIEWER,
            "tendering.addendum.create": Role.EDITOR,
            "tendering.addendum.publish": Role.EDITOR,
            "tendering.addendum.acknowledge": Role.EDITOR,
            "tendering.leveling.read": Role.VIEWER,
            "tendering.leveling.run": Role.EDITOR,
            # Opening sealed bids reveals every price at once: a manager act.
            "tendering.sealed.open": Role.MANAGER,
            "tendering.sealed.manage": Role.MANAGER,
        },
    )
