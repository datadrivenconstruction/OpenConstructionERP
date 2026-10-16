# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Property Development module permission definitions.

R6 (task #137) extends the original coarse set with fine-grained
permissions for the Lead / Reservation / SalesContract /
PaymentSchedule / Instalment / ContractParty pipeline. The original
permissions are kept verbatim so existing routes don't churn.
"""

from app.core.permissions import Role, permission_registry

PROPERTY_DEV_PERMISSIONS: dict[str, Role] = {
    # ── Foundation (v3018) ──────────────────────────────────────────
    "property_dev.read": Role.VIEWER,
    "property_dev.create": Role.EDITOR,
    "property_dev.update": Role.EDITOR,
    "property_dev.delete": Role.MANAGER,
    # Deleting is guarded by two different arrangements, so it needs two
    # permissions. Measured over router.py: 24 routes were gated by
    # ``property_dev.delete``. On 19 of them the handler also calls a
    # ``_verify_owner_via_*`` helper, and that project-access check is strict -
    # only the project owner or a project team member passes (see
    # access.py), the global admin role included. On
    # the remaining 5 the permission is the only wall there is.
    #
    # No single level is correct for both halves. At MANAGER the 19 are
    # unusable by anyone whenever the owning project belongs to an editor:
    # the owner holds no permission and everyone holding the permission
    # fails the owner check, so the row can never be removed. At EDITOR the
    # 5 would lose their only protection.
    #
    # Hence the split below. ``owner_scoped_delete`` is deliberately NOT
    # named as a variant of ``delete``: it is not a weaker delete, it is a
    # delete whose real wall is ownership rather than role. It is only safe
    # while every route carrying it also calls an owner helper, which is an
    # invariant a test enforces - see
    # tests/modules/property_dev/test_owner_scoped_delete_invariant.py.
    "property_dev.owner_scoped_delete": Role.EDITOR,
    "property_dev.reserve_plot": Role.EDITOR,
    # Lowered from MANAGER: every route carrying these permissions also calls
    # a ``_verify_owner_via_*`` helper, so the real access gate is ownership,
    # not role level. At MANAGER the routes were dead: the project owner
    # (EDITOR) could never pass RBAC, and a MANAGER would pass RBAC but fail
    # the ownership check. Same split logic as ``owner_scoped_delete`` above.
    # Invariant enforced in test_owner_scoped_delete_invariant.py.
    "property_dev.contract_buyer": Role.EDITOR,
    "property_dev.lock_selection": Role.EDITOR,
    "property_dev.handover": Role.EDITOR,
    "property_dev.fix_snag": Role.EDITOR,
    "property_dev.process_warranty": Role.EDITOR,
    # ── R6 (task #137) - Lead ───────────────────────────────────────
    "property_dev.lead.create": Role.EDITOR,
    "property_dev.lead.read": Role.VIEWER,
    "property_dev.lead.update": Role.EDITOR,
    "property_dev.lead.delete": Role.EDITOR,
    "property_dev.lead.assign": Role.MANAGER,
    "property_dev.lead.convert": Role.EDITOR,
    # ── R6 (task #137) - Reservation ────────────────────────────────
    "property_dev.reservation.create": Role.EDITOR,
    "property_dev.reservation.read": Role.VIEWER,
    "property_dev.reservation.update": Role.EDITOR,
    "property_dev.reservation.cancel": Role.EDITOR,
    "property_dev.reservation.expire": Role.MANAGER,
    # Split: ``expire`` is used by both a batch admin/cron endpoint (no owner
    # check, correctly MANAGER) and a single-reservation endpoint that does
    # call ``_verify_owner_via_reservation``. The latter gets the owner-scoped
    # variant so the project owner (EDITOR) can actually reach it.
    "property_dev.owner_scoped_reservation_expire": Role.EDITOR,
    # ── R6 (task #137) - Sales Contract (SPA) ───────────────────────
    "property_dev.spa.draft": Role.EDITOR,
    "property_dev.spa.send": Role.EDITOR,
    "property_dev.spa.sign": Role.EDITOR,
    "property_dev.spa.cancel": Role.EDITOR,
    # ── R6 (task #137) - Payment Schedule ───────────────────────────
    "property_dev.payment_schedule.activate": Role.EDITOR,
    "property_dev.payment_schedule.suspend": Role.EDITOR,
    # ── R6 (task #137) - Instalment ─────────────────────────────────
    "property_dev.instalment.mark_paid": Role.EDITOR,
    "property_dev.instalment.issue_demand": Role.EDITOR,
    "property_dev.instalment.waive": Role.MANAGER,
    # Split: ``waive`` is used by both a single-instalment endpoint that
    # calls ``_verify_owner_via_instalment`` and a batch admin/cron endpoint
    # (accrue-late-fees) with no owner check. The single-instalment route
    # gets the owner-scoped variant; the batch stays MANAGER.
    "property_dev.owner_scoped_instalment_waive": Role.EDITOR,
    # ── R6 (task #137) - Contract Party (multi-buyer junction) ──────
    "property_dev.contract_party.add": Role.EDITOR,
    "property_dev.contract_party.remove": Role.EDITOR,
    "property_dev.contract_party.update_ownership": Role.EDITOR,
    # ── Task #138: Broker / Commission / Escrow / PriceMatrix / Reports ──
    # Brokers + agreements: EDITOR can CRUD master records but only
    # MANAGER+ can verify KYC (legal/compliance step).
    "property_dev.broker.kyc_verify": Role.MANAGER,
    # Commissions: accrual creation is event-driven and bypasses the
    # endpoint gates; the lifecycle (approve + pay) is MANAGER+.
    "property_dev.commission.approve": Role.MANAGER,
    "property_dev.commission.pay": Role.MANAGER,
    # Escrow: balance/list = VIEWER+; reconciliation lowered to EDITOR
    # because every route calls _verify_owner_via_escrow_transaction.
    "property_dev.escrow.reconcile": Role.EDITOR,
    # PriceMatrix lifecycle changes (activate + bulk-recompute) lowered to
    # EDITOR because every route calls _verify_owner_via_price_matrix.
    "property_dev.price_matrix.activate": Role.EDITOR,
    "property_dev.price_matrix.bulk_recompute": Role.EDITOR,
    # Regulator reports lowered to EDITOR because every route calls
    # _verify_owner_via_development. Ownership is the real gate.
    "property_dev.regulator_report.generate": Role.EDITOR,
    # ── Bulk admin operations (sales-ops console) ──────────────────────────
    # All bulk endpoints are MANAGER+ because each touches potentially
    # hundreds of rows in a single transaction (status flips that release
    # plots from reservation, expiry extensions that block other buyers,
    # CSV imports that fan out into Lead rows, doc regen that overwrites
    # signed-PDF blobs, and buyer-merge that re-points FK references on
    # reservations / sales_contracts / payments). Atomicity is enforced
    # via SAVEPOINT (see procurement R7 PO → invoice pattern); RBAC
    # gating is the FIRST line of defense before the IDOR per-entity gate.
    "property_dev.bulk.plot_status_change": Role.MANAGER,
    "property_dev.bulk.reservation_extend": Role.MANAGER,
    "property_dev.bulk.document_regenerate": Role.MANAGER,
    "property_dev.bulk.lead_import": Role.MANAGER,
    "property_dev.bulk.buyer_merge": Role.MANAGER,
}


def register_property_dev_permissions() -> None:
    """Register permissions for the property_dev module."""
    permission_registry.register_module_permissions(
        "property_dev",
        PROPERTY_DEV_PERMISSIONS,
    )
