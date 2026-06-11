"""‌⁠‍Finance module permission definitions."""

from app.core.permissions import Role, permission_registry


def register_finance_permissions() -> None:
    """‌⁠‍Register permissions for the finance module.

    R7 audit (2026-05-24):
        Three new permission keys split off from the generic
        ``finance.update`` so financial commitments require MANAGER:

        * ``finance.approve`` - invoice approval (draft → sent). The
          legacy route used ``finance.update`` (EDITOR), which let any
          estimator move an invoice to a payable state.
        * ``finance.pay`` - mark invoice paid. Same rationale: paying
          an invoice is a binding financial action, not a CRUD edit.
        * ``finance.record_payment`` - recording a payment row against
          an invoice. EDITOR can no longer fabricate ledger entries.
    """
    permission_registry.register_module_permissions(
        "finance",
        {
            "finance.create": Role.EDITOR,
            "finance.read": Role.VIEWER,
            "finance.update": Role.EDITOR,
            "finance.delete": Role.MANAGER,
            # R7 (2026-05-24): financial-commitment surfaces are MANAGER-only.
            "finance.approve": Role.MANAGER,
            "finance.pay": Role.MANAGER,
            "finance.record_payment": Role.MANAGER,
            # Gap E (Wave 6): manually raising the receivable from a certified
            # claim is a financial commitment (it books revenue against the
            # client), so it sits at MANAGER alongside approve/pay. The event
            # subscriber path is system-driven and bypasses the permission gate.
            "finance.invoice_from_claim": Role.MANAGER,
            # TOP-30 #4: ERP / accounting connectors. Reading the catalogue
            # and sync history is VIEWER; managing configs (which touch
            # encrypted credentials) and triggering a live sync (which mutates
            # external systems / writes ledger rows) are MANAGER, consistent
            # with the R7 escalation above.
            "finance.connector.read": Role.VIEWER,
            "finance.connector.manage": Role.MANAGER,
            "finance.connector.sync": Role.MANAGER,
            # Task #77: GAAP general ledger + financial reporting.
            # Reading the chart of accounts, the trial balance and the
            # financial statements is VIEWER. Managing the chart (which shapes
            # how every statement is classified) and posting a journal entry
            # (a binding double-entry ledger write) are MANAGER, consistent
            # with the R7 escalation that put record_payment / approve / pay at
            # MANAGER. Statements are derived read models, so they sit at
            # finance.read.
            "finance.gl.read": Role.VIEWER,
            "finance.gl.manage_accounts": Role.MANAGER,
            "finance.gl.post_journal": Role.MANAGER,
        },
    )
