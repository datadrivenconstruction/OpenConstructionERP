# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Declarative FSM registry for the six core OpenConstructionERP entities.

Each entity declares its full lifecycle here so auditors and frontend
developers can read off every legal status move in a single file. Add new
entities by appending one more :class:`EntityFSM` and exporting it.

Conventions:
    * State names are lowercase snake_case strings.
    * Role gates use the names emitted by :mod:`app.core.permissions`
      (``admin``, ``manager``, ``estimator``, ``viewer``, …). The string
      ``admin`` always passes - admin role bypasses every gate. Use
      ``required_roles=()`` to allow anyone with general write permission.
    * Side effects (event-bus notifications, finance recalculations, …)
      live in module-level functions below the FSM declarations so they
      can be unit-tested in isolation and reused across transitions.

Mapping table (audit findings WF1-WF6):

    BOQ        - draft ↔ revision → final → archived
    Project    - planning → active ↔ on_hold → completed → archived
    Invoice    - draft → sent → paid → credit_note_issued  (paid is terminal
                 except via credit-note; no destructive cancel after pay)
    NCR        - open → in_review → resolved → closed; rejected ← in_review
    RFQ        - draft → published → bids_received → awarded → po_issued
                 → completed
    Submittal  - open → under_review → revise_resubmit → approved |
                 rejected | approved_as_noted
"""

from __future__ import annotations

import logging
from typing import Any

from app.core.fsm.engine import EntityFSM, StateTransition, register_fsm

logger = logging.getLogger(__name__)


# ── Shared side-effect helpers ──────────────────────────────────────────────


async def _publish_status_event(ctx: dict[str, Any], *, event_name: str) -> None:
    """Fire-and-forget event bus emission for a status change.

    Detached so SQLite single-writer lock isn't held during fan-out.
    Tests substitute ``publish_detached`` for a synchronous shim, so the
    same call site works in both environments.
    """
    try:
        from app.core.events import event_bus

        entity = ctx.get("entity")
        ent_id = getattr(entity, "id", None) if entity is not None else None
        project_id = getattr(entity, "project_id", None) if entity is not None else None
        payload = {
            "entity_id": str(ent_id) if ent_id is not None else None,
            "project_id": str(project_id) if project_id is not None else None,
            "from_status": ctx.get("from_status"),
            "to_status": ctx.get("to_status"),
            "actor_id": ctx.get("actor_id"),
            "reason": ctx.get("reason"),
        }
        event_bus.publish_detached(event_name, payload, source_module="fsm")
    except Exception:  # pragma: no cover - events must never block lifecycle
        logger.debug("FSM event publish skipped: %s", event_name)


def _make_event_emitter(event_name: str):
    """Curry ``_publish_status_event`` so it matches the side-effect signature."""

    async def _emit(ctx: dict[str, Any]) -> None:
        await _publish_status_event(ctx, event_name=event_name)

    _emit.__name__ = f"emit_{event_name.replace('.', '_')}"
    return _emit


# ── Shared guard helpers ────────────────────────────────────────────────────


def _require_metadata_field(field: str, *, message: str | None = None):
    """Guard factory: require ``ctx['metadata'][field]`` to be truthy."""

    def _guard(ctx: dict[str, Any]) -> bool:
        meta = ctx.get("metadata") or {}
        return bool(meta.get(field))

    _guard.__name__ = f"require_{field}"
    return _guard


# ── BOQ FSM (WF1) ───────────────────────────────────────────────────────────
# Lifecycle:
#     draft  →  final               (lock)
#     final  →  draft               (unlock; admin/manager only)
#     draft  →  revision            (create_revision - branches a new draft)
#     final  →  archived            (post-project archival; admin only)
#     revision → draft              (alias: a revision IS a draft branch)
#
# We model "revision" as a distinct status node so the audit log can
# distinguish "branched a new estimate" from "edited a fresh draft". The
# create-revision endpoint inserts a NEW BOQ row in status=draft, and the
# original BOQ stays in `final` - so this FSM also lets the cloned row
# move revision→draft when the user starts editing it.

BOQ_FSM = register_fsm(
    EntityFSM(
        name="boq",
        initial="draft",
        terminal=("archived",),
        transitions=[
            StateTransition(
                from_status="draft",
                to_status="final",
                description="Lock BOQ for tender / approval",
                on_transition=(_make_event_emitter("boq.locked"),),
            ),
            StateTransition(
                from_status="final",
                to_status="draft",
                required_roles=("admin", "manager"),
                description="Unlock BOQ to allow further edits",
                on_transition=(_make_event_emitter("boq.unlocked"),),
            ),
            StateTransition(
                from_status="draft",
                to_status="revision",
                description="Branch a revision from a draft",
            ),
            StateTransition(
                from_status="final",
                to_status="revision",
                required_roles=("admin", "manager"),
                description="Branch a revision from a finalised BOQ",
                on_transition=(_make_event_emitter("boq.revision_created"),),
            ),
            StateTransition(
                from_status="revision",
                to_status="draft",
                description="Promote a revision to an editable draft",
            ),
            StateTransition(
                from_status="final",
                to_status="archived",
                required_roles=("admin", "manager"),
                description="Archive a finalised BOQ",
                on_transition=(_make_event_emitter("boq.archived"),),
            ),
            StateTransition(
                from_status="draft",
                to_status="archived",
                required_roles=("admin", "manager"),
                description="Archive an unsubmitted draft",
                on_transition=(_make_event_emitter("boq.archived"),),
            ),
        ],
    )
)


# ── Project FSM (WF2) ───────────────────────────────────────────────────────
# Lifecycle:
#     planning   →  active       (kick-off)
#     active     ↔  on_hold      (pause / resume)
#     active     →  completed    (project hand-over)
#     completed  →  archived     (terminal; soft-deletes the project)
#     active     →  archived     (admin only; emergency archive)
#     planning   →  archived     (cancelled before start)
#
# Legacy demo data carries status="active" with no planning phase; the
# initial state is "planning" only for new rows. Existing "active" rows
# stay valid.

PROJECT_FSM = register_fsm(
    EntityFSM(
        name="project",
        initial="planning",
        terminal=("archived",),
        transitions=[
            StateTransition(
                from_status="planning",
                to_status="active",
                description="Kick off the project",
                on_transition=(_make_event_emitter("project.activated"),),
            ),
            StateTransition(
                from_status="active",
                to_status="on_hold",
                description="Pause project work",
                on_transition=(_make_event_emitter("project.on_hold"),),
            ),
            StateTransition(
                from_status="on_hold",
                to_status="active",
                description="Resume project work",
                on_transition=(_make_event_emitter("project.activated"),),
            ),
            StateTransition(
                from_status="active",
                to_status="completed",
                required_roles=("admin", "manager"),
                description="Mark the project complete after hand-over",
                on_transition=(_make_event_emitter("project.completed"),),
            ),
            StateTransition(
                from_status="completed",
                to_status="archived",
                required_roles=("admin", "manager"),
                description="Archive a completed project",
                on_transition=(_make_event_emitter("project.archived"),),
            ),
            StateTransition(
                from_status="active",
                to_status="archived",
                required_roles=("admin",),
                description="Emergency archive of an active project",
                on_transition=(_make_event_emitter("project.archived"),),
            ),
            StateTransition(
                from_status="on_hold",
                to_status="archived",
                required_roles=("admin", "manager"),
                description="Archive a paused project",
                on_transition=(_make_event_emitter("project.archived"),),
            ),
            StateTransition(
                from_status="planning",
                to_status="archived",
                required_roles=("admin", "manager"),
                description="Cancel a project before it starts",
                on_transition=(_make_event_emitter("project.archived"),),
            ),
            StateTransition(
                from_status="archived",
                to_status="active",
                required_roles=("admin",),
                description="Restore an archived project",
                on_transition=(_make_event_emitter("project.restored"),),
            ),
        ],
    )
)


# ── Invoice FSM (WF3) ───────────────────────────────────────────────────────
# Lifecycle (FIDIC / IFRS-15 aware):
#     draft               →  sent
#     sent                →  paid
#     paid                →  credit_note_issued  (irreversible; no destructive cancel)
#     draft               →  cancelled           (only before send)
#     sent                →  cancelled           (uncollectible AR / clerical error)
#     cancelled           →  draft               (re-open for re-issue)
#
# The legacy "approved" status (from earlier service-level FSM) is mapped
# in the data migration to "sent": invoices that were "draft" → "approved"
# → "paid" now read as "draft" → "sent" → "paid".

INVOICE_FSM = register_fsm(
    EntityFSM(
        name="invoice",
        initial="draft",
        terminal=("credit_note_issued",),
        transitions=[
            StateTransition(
                from_status="draft",
                to_status="sent",
                description="Issue the invoice to the counterparty",
                on_transition=(_make_event_emitter("invoice.sent"),),
            ),
            StateTransition(
                from_status="sent",
                to_status="paid",
                description="Mark invoice as fully paid",
                on_transition=(_make_event_emitter("invoice.paid"),),
            ),
            StateTransition(
                from_status="paid",
                to_status="credit_note_issued",
                required_roles=("admin", "manager"),
                description="Reverse a paid invoice via credit note",
                on_transition=(_make_event_emitter("invoice.credit_note_issued"),),
            ),
            StateTransition(
                from_status="draft",
                to_status="cancelled",
                description="Cancel a draft invoice (clerical)",
            ),
            StateTransition(
                from_status="sent",
                to_status="cancelled",
                required_roles=("admin", "manager"),
                description="Cancel a sent invoice (uncollectible)",
                on_transition=(_make_event_emitter("invoice.cancelled"),),
            ),
            StateTransition(
                from_status="cancelled",
                to_status="draft",
                description="Re-open a cancelled invoice as a draft",
            ),
            # Backward-compat: a "pending" status used by older code paths is
            # routed through the same edges. The data migration rewrites
            # legacy "pending"/"approved" rows to either "draft" or "sent".
        ],
    )
)


# ── NCR FSM (WF4) ───────────────────────────────────────────────────────────
# Lifecycle (ISO 9001 §10.2):
#     open         →  in_review
#     in_review    →  resolved
#     in_review    →  rejected   (root cause does not justify NCR)
#     resolved     →  closed     (verification passed; terminal)
#     resolved     →  in_review  (verification failed; back to review)
#     rejected     →  closed     (terminal - dismiss)
#     open         →  closed     (admin only - emergency close)

NCR_FSM = register_fsm(
    EntityFSM(
        name="ncr",
        initial="open",
        terminal=("closed",),
        transitions=[
            StateTransition(
                from_status="open",
                to_status="in_review",
                description="Begin reviewing the non-conformance",
                on_transition=(_make_event_emitter("ncr.in_review"),),
            ),
            StateTransition(
                from_status="in_review",
                to_status="resolved",
                description="Resolve the NCR (corrective action complete)",
                guards=(
                    _require_metadata_field(
                        "corrective_action",
                        message="Cannot resolve an NCR without a corrective action.",
                    ),
                ),
                on_transition=(_make_event_emitter("ncr.resolved"),),
            ),
            StateTransition(
                from_status="in_review",
                to_status="rejected",
                required_roles=("admin", "manager"),
                description="Reject the NCR after investigation",
                on_transition=(_make_event_emitter("ncr.rejected"),),
            ),
            StateTransition(
                from_status="resolved",
                to_status="closed",
                description="Close the NCR after verification",
                on_transition=(_make_event_emitter("ncr.closed"),),
            ),
            StateTransition(
                from_status="resolved",
                to_status="in_review",
                description="Re-open verification (corrective action failed)",
                on_transition=(_make_event_emitter("ncr.reopened"),),
            ),
            StateTransition(
                from_status="rejected",
                to_status="closed",
                description="Close a rejected NCR",
                on_transition=(_make_event_emitter("ncr.closed"),),
            ),
            StateTransition(
                from_status="open",
                to_status="closed",
                required_roles=("admin",),
                description="Emergency-close an unreviewed NCR",
                on_transition=(_make_event_emitter("ncr.closed"),),
            ),
            StateTransition(
                from_status="open",
                to_status="rejected",
                required_roles=("admin", "manager"),
                description="Reject an NCR before review",
                on_transition=(_make_event_emitter("ncr.rejected"),),
            ),
        ],
    )
)


# ── RFQ FSM (WF5) ───────────────────────────────────────────────────────────
# Lifecycle (procurement):
#     draft          →  published
#     published      →  bids_received
#     bids_received  →  awarded
#     awarded        →  po_issued
#     po_issued      →  completed     (terminal)
#     draft          →  cancelled
#     published      →  cancelled     (no bidders / scope change)
#     bids_received  →  cancelled
#     cancelled      →  draft          (re-open for re-publish)

RFQ_FSM = register_fsm(
    EntityFSM(
        name="rfq",
        initial="draft",
        terminal=("completed",),
        transitions=[
            StateTransition(
                from_status="draft",
                to_status="published",
                description="Publish the RFQ to invited bidders",
                on_transition=(_make_event_emitter("rfq.published"),),
            ),
            StateTransition(
                from_status="published",
                to_status="bids_received",
                description="Bidding window closed; review bids",
                on_transition=(_make_event_emitter("rfq.bids_received"),),
            ),
            StateTransition(
                from_status="bids_received",
                to_status="awarded",
                required_roles=("admin", "manager"),
                description="Award the RFQ to a bidder",
                on_transition=(_make_event_emitter("rfq.awarded"),),
            ),
            StateTransition(
                from_status="awarded",
                to_status="po_issued",
                required_roles=("admin", "manager"),
                description="Issue the purchase order against the award",
                on_transition=(_make_event_emitter("rfq.po_issued"),),
            ),
            StateTransition(
                from_status="po_issued",
                to_status="completed",
                description="Mark the RFQ lifecycle complete after PO closes",
                on_transition=(_make_event_emitter("rfq.completed"),),
            ),
            StateTransition(
                from_status="draft",
                to_status="cancelled",
                description="Cancel a draft RFQ",
            ),
            StateTransition(
                from_status="published",
                to_status="cancelled",
                required_roles=("admin", "manager"),
                description="Cancel a published RFQ (no bidders / scope change)",
                on_transition=(_make_event_emitter("rfq.cancelled"),),
            ),
            StateTransition(
                from_status="bids_received",
                to_status="cancelled",
                required_roles=("admin", "manager"),
                description="Cancel after bids received (all rejected)",
                on_transition=(_make_event_emitter("rfq.cancelled"),),
            ),
            StateTransition(
                from_status="cancelled",
                to_status="draft",
                description="Re-open a cancelled RFQ for republishing",
            ),
            # Backward-compat: the legacy code wrote ``status="issued"``;
            # data migration rewrites those rows to ``published``.
        ],
    )
)


# ── Submittal FSM (WF6) ─────────────────────────────────────────────────────
# Lifecycle (construction submittal review):
#     open               →  under_review
#     under_review       →  approved
#     under_review       →  approved_as_noted
#     under_review       →  revise_resubmit
#     under_review       →  rejected
#     revise_resubmit    →  under_review     (after resubmission)
#     revise_resubmit    →  open             (returned to author)
#     rejected           →  open             (re-submit clean)
#     approved           →  closed
#     approved_as_noted  →  closed
#     rejected           →  closed           (terminal - dismissed)

SUBMITTAL_FSM = register_fsm(
    EntityFSM(
        name="submittal",
        initial="open",
        terminal=("closed",),
        transitions=[
            StateTransition(
                from_status="open",
                to_status="under_review",
                description="Submit for review",
                on_transition=(_make_event_emitter("submittal.under_review"),),
            ),
            StateTransition(
                from_status="under_review",
                to_status="approved",
                required_roles=("admin", "manager"),
                description="Approve the submittal",
                on_transition=(_make_event_emitter("submittal.approved"),),
            ),
            StateTransition(
                from_status="under_review",
                to_status="approved_as_noted",
                required_roles=("admin", "manager"),
                description="Approve with reviewer notes",
                on_transition=(_make_event_emitter("submittal.approved_as_noted"),),
            ),
            StateTransition(
                from_status="under_review",
                to_status="revise_resubmit",
                required_roles=("admin", "manager"),
                description="Reviewer requests revisions",
                on_transition=(_make_event_emitter("submittal.revise_resubmit"),),
            ),
            StateTransition(
                from_status="under_review",
                to_status="rejected",
                required_roles=("admin", "manager"),
                description="Reject the submittal",
                on_transition=(_make_event_emitter("submittal.rejected"),),
            ),
            StateTransition(
                from_status="revise_resubmit",
                to_status="under_review",
                description="Resubmit after revisions",
                on_transition=(_make_event_emitter("submittal.under_review"),),
            ),
            StateTransition(
                from_status="revise_resubmit",
                to_status="open",
                description="Return to author for major rework",
            ),
            StateTransition(
                from_status="rejected",
                to_status="open",
                description="Re-create submittal after rejection",
            ),
            StateTransition(
                from_status="approved",
                to_status="closed",
                description="Close approved submittal",
                on_transition=(_make_event_emitter("submittal.closed"),),
            ),
            StateTransition(
                from_status="approved_as_noted",
                to_status="closed",
                description="Close approved-as-noted submittal",
                on_transition=(_make_event_emitter("submittal.closed"),),
            ),
            StateTransition(
                from_status="rejected",
                to_status="closed",
                description="Close rejected submittal (terminal)",
                on_transition=(_make_event_emitter("submittal.closed"),),
            ),
        ],
    )
)


__all__ = [
    "BOQ_FSM",
    "INVOICE_FSM",
    "NCR_FSM",
    "PROJECT_FSM",
    "RFQ_FSM",
    "SUBMITTAL_FSM",
]
