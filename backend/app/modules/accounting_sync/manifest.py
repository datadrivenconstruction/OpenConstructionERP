# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Accounting​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ sync module manifest."""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_accounting_sync",
    version="1.0.0",
    display_name="Accounting Sync",
    description=(
        "Connects the platform to the company's accounting: pushes receivable invoices and interim payment "
        "certificates, subcontractor and supplier bills and guarantee fees with contacts and a project "
        "dimension to Xero or QuickBooks Online and pulls payments back, or exports DATEV EXTF, a generic "
        "journal (CSV, Excel) or OECD SAF-T. Account and tax-code mapping per company from country "
        "templates, idempotent pushes with a sync log, retry and validation."
    ),
    author="OpenConstructionERP Core Team",
    category="business",
    depends=["oe_projects", "oe_finance"],
    optional_depends=["oe_contacts", "oe_guarantees", "oe_notifications", "oe_subcontractors", "oe_procurement"],
    auto_install=True,
    enabled=True,
)
