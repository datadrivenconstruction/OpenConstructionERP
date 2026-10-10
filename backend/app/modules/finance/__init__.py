# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Finance module.

Provides invoicing, payments, budgets, and Earned Value Management (EVM)
workflows for construction projects.
"""


async def on_startup() -> None:
    """Module startup hook - register permissions and cross-module subscribers."""
    from app.modules.finance.connector_events import (
        register_connector_job_handler,
        register_connector_subscribers,
    )
    from app.modules.finance.connectors.registry import register_builtin_connectors
    from app.modules.finance.events import register_finance_subscribers
    from app.modules.finance.permissions import register_finance_permissions

    register_finance_permissions()
    register_finance_subscribers()
    # TOP-30 #4: ERP / accounting connectors.
    register_builtin_connectors()
    register_connector_subscribers()
    register_connector_job_handler()

    from app.modules.finance.validators import register_finance_rules

    register_finance_rules()
    _register_invoice_tax_source()


async def _invoice_project(session: object, source_id: object) -> object:
    """The project an invoice belongs to, ``None`` when there is no such invoice."""
    from app.modules.finance.models import Invoice

    invoice = await session.get(Invoice, source_id)  # type: ignore[attr-defined]
    return invoice.project_id if invoice is not None else None


def _register_invoice_tax_source() -> None:
    """Tell the tax module that finance owns the documents of source kind ``invoice``.

    The statutory tax routes refuse a source kind nobody owns, so without this
    the taxes of a standalone invoice could not be stored. The tax module is
    optional: where it is absent there is nothing to register with.
    """
    try:
        from app.modules.tax_withholding.source_owners import register_source_owner
    except ImportError:
        return
    register_source_owner("invoice", _invoice_project)
