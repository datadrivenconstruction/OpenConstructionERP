# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Supplier Catalogs module permission definitions."""

from app.core.permissions import Role, permission_registry


def register_supplier_catalogs_permissions() -> None:
    """Register supplier-catalogs permissions on the global registry."""
    permission_registry.register_module_permissions(
        "supplier_catalogs",
        {
            # Vendor management
            "supplier_catalogs.vendor.read": Role.VIEWER,
            "supplier_catalogs.vendor.write": Role.EDITOR,
            "supplier_catalogs.vendor.admin": Role.MANAGER,
            # Catalog & price lists
            "supplier_catalogs.catalog.read": Role.VIEWER,
            "supplier_catalogs.catalog.write": Role.EDITOR,
            # Contractor discount agreements are commercial terms
            "supplier_catalogs.discount.read": Role.EDITOR,
            "supplier_catalogs.discount.manage": Role.MANAGER,
            # Purchase requisition
            "supplier_catalogs.pr.create": Role.EDITOR,
            "supplier_catalogs.pr.approve": Role.MANAGER,
            # Purchase order
            "supplier_catalogs.po.create": Role.EDITOR,
            "supplier_catalogs.po.send": Role.MANAGER,
            "supplier_catalogs.po.close": Role.MANAGER,
            # Goods receipt
            "supplier_catalogs.gr.post": Role.EDITOR,
            # Invoice
            "supplier_catalogs.invoice.match": Role.MANAGER,
            # Warehouse
            "supplier_catalogs.warehouse.read": Role.VIEWER,
            "supplier_catalogs.warehouse.write": Role.EDITOR,
            "supplier_catalogs.warehouse.manage": Role.MANAGER,
        },
    )
