# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Change-intelligence service - the thin database layer over the pure engines.

Gathers the current state of every change-family record for a project (change
orders, variation notices / requests / orders, MoC entries) and feeds it to the
pure :mod:`cycle_time` engine to produce the "waiting on whom" board. Only the
columns the engine needs are selected (no relationship loading), so a project
with many change records stays cheap to summarise.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.change_intelligence.action_register import (
    SOURCE_CHANGE_ORDER as REGISTER_SOURCE_CHANGE_ORDER,
)
from app.modules.change_intelligence.action_register import (
    SOURCE_MEETING_ACTION,
    SOURCE_RFI,
    SOURCE_RISK_ACTION,
    SOURCE_SUBMITTAL,
    CommitmentRegister,
    RegisterItem,
    build_register,
)
from app.modules.change_intelligence.change_drivers import (
    SOURCE_CHANGE_ORDER as DRIVER_SOURCE_CHANGE_ORDER,
)
from app.modules.change_intelligence.change_drivers import (
    SOURCE_DISRUPTION_CLAIM,
    SOURCE_EOT_CLAIM,
    SOURCE_RISK,
    DriverAnalytics,
    DriverRecord,
    build_driver_analytics,
)
from app.modules.change_intelligence.change_run_rate import (
    KIND_CHANGE_ORDER as RUNRATE_KIND_CHANGE_ORDER,
)
from app.modules.change_intelligence.change_run_rate import (
    KIND_VARIATION_ORDER as RUNRATE_KIND_VARIATION_ORDER,
)
from app.modules.change_intelligence.change_run_rate import (
    KIND_VARIATION_REQUEST as RUNRATE_KIND_VARIATION_REQUEST,
)
from app.modules.change_intelligence.change_run_rate import (
    ChangeEvent,
    RunRate,
    build_run_rate,
    classify_change_bucket,
    resolve_effective_date,
)
from app.modules.change_intelligence.clarifier import ClarifiedRequest, analyze_change_note
from app.modules.change_intelligence.coordination import (
    ActionItem,
    CoordinationPlan,
    build_plan,
    parse_date,
)
from app.modules.change_intelligence.cycle_time import (
    KIND_CHANGE_ORDER,
    KIND_MOC_ENTRY,
    KIND_VARIATION_NOTICE,
    KIND_VARIATION_ORDER,
    KIND_VARIATION_REQUEST,
    UNASSIGNED,
    ChangeItem,
    CycleTimeBoard,
    ItemAging,
    build_board,
    is_open_status,
    parse_due,
)
from app.modules.change_intelligence.decision_impact import (
    ChangeImpact,
    DecisionImpact,
    project_with_pending,
)
from app.modules.change_intelligence.delay_risk import (
    DelayRiskInput,
    DelayRiskResult,
)
from app.modules.change_intelligence.delay_risk import (
    rank as rank_delay_risk,
)
from app.modules.change_intelligence.dispute_risk import (
    DisputeExposureSummary,
    DisputeRiskInput,
    DisputeRiskItem,
    rank_dispute_exposure,
    summarize_dispute_exposure,
)
from app.modules.change_intelligence.impact_projection import (
    KIND_CHANGE_ORDER as IMPACT_KIND_CHANGE_ORDER,
)
from app.modules.change_intelligence.impact_projection import (
    KIND_VARIATION_ORDER as IMPACT_KIND_VARIATION_ORDER,
)
from app.modules.change_intelligence.impact_projection import (
    ApprovedChange,
    ImpactProjection,
    project_impacts,
)
from app.modules.change_intelligence.intake_normalizer import (
    BUILTIN_PROFILES,
    CANONICAL_FIELDS,
    IntakeMapping,
    NormalizationResult,
)
from app.modules.change_intelligence.intake_normalizer import (
    normalize as normalize_intake,
)
from app.modules.change_intelligence.ownership_chain import (
    HandoffRow,
    OwnershipChain,
    build_ownership_chain,
)
from app.modules.change_intelligence.thread_digest import (
    DIRECTION_INBOUND,
    DIRECTION_OUTBOUND,
    CommsDigest,
    Message,
    build_digest,
)
from app.modules.change_intelligence.watch import (
    WatchItem,
    WatchSummary,
    build_watch,
)
from app.modules.changeorders.models import ChangeOrder
from app.modules.claims_evidence.provability import (
    ProvabilitySignals,
    band_for,
    compute_provability,
)
from app.modules.correspondence.models import Correspondence
from app.modules.cost_recovery.back_charge import BackChargeItem
from app.modules.cost_recovery.models import BackCharge
from app.modules.meetings.models import Meeting
from app.modules.moc.models import MoCEntry
from app.modules.projects.models import Project
from app.modules.rfi.models import RFI
from app.modules.risk.models import RiskItem
from app.modules.submittals.models import Submittal
from app.modules.variations.models import (
    DisruptionClaim,
    ExtensionOfTimeClaim,
    Notice,
    VariationOrder,
    VariationRequest,
)

# Each change-family source table mapped to its engine kind token. Every model
# carries the same shape we read: id / code / title / status / ball_in_court /
# response_due_date plus created_at + updated_at from the shared Base.
_SOURCES: tuple[tuple[type, str], ...] = (
    (ChangeOrder, KIND_CHANGE_ORDER),
    (Notice, KIND_VARIATION_NOTICE),
    (VariationRequest, KIND_VARIATION_REQUEST),
    (VariationOrder, KIND_VARIATION_ORDER),
    (MoCEntry, KIND_MOC_ENTRY),
)


async def gather_change_items(session: AsyncSession, project_id: uuid.UUID) -> list[ChangeItem]:
    """Read every change-family record for *project_id* as engine ChangeItems."""
    items: list[ChangeItem] = []
    for model, kind in _SOURCES:
        stmt = select(
            model.id,
            model.code,
            model.title,
            model.status,
            model.ball_in_court,
            model.response_due_date,
            model.created_at,
            model.updated_at,
        ).where(model.project_id == project_id)
        result = await session.execute(stmt)
        for row in result.all():
            items.append(
                ChangeItem(
                    id=str(row.id),
                    kind=kind,
                    code=row.code or "",
                    title=(row.title or "").strip(),
                    status=row.status or "",
                    is_open=is_open_status(kind, row.status),
                    ball_in_court=row.ball_in_court,
                    response_due_date=row.response_due_date,
                    opened_at=row.created_at,
                    last_activity_at=row.updated_at,
                )
            )
    return items


async def build_project_board(
    session: AsyncSession,
    project_id: uuid.UUID,
    *,
    now: datetime | None = None,
) -> CycleTimeBoard:
    """Build the cycle-time board for one project from its live change records."""
    moment = now or datetime.now(UTC)
    items = await gather_change_items(session, project_id)
    return build_board(items, moment)


# --- Approved-change cost / schedule impact (materialized view) ------------

#: Change-order statuses whose cost and schedule impact is committed.
_CO_APPROVED_STATUSES = frozenset({"approved", "executed"})
#: Variation-order statuses that represent an agreed, in-force order.
_VO_AGREED_STATUSES = frozenset({"issued", "in_progress", "completed"})

#: Metadata key a change order carries when it mirrors a variation order.
_MIRRORED_VO_KEY = "variation_order_id"


def _mirrored_variation_order_id(metadata: object) -> str | None:
    """The variation order a change order mirrors, or ``None`` when it mirrors none.

    Promoting a variation request creates a change order alongside the
    variation order and stamps this link on it
    (``VariationsService.convert_vr_to_vo``, which also records an ``origin``),
    so every converted variation exists once in each family. Both families feed
    the views below, and the two rows carry the same money, so counting both
    counts one agreed change twice.

    Read from the change order rather than from
    ``VariationOrder.reference_change_order_id``: that column also holds a
    change order a variation merely refers to - the demo data anchors a
    variation order to an independently raised CO-001 - so keying on it would
    drop a change order that carries value of its own. This is the same link
    the contracts money subscriber keys its posting identity on
    (``_on_changeorder_approved_contract``), so "mirrors a variation order" has
    one meaning across the tree.
    """
    if not isinstance(metadata, dict):
        return None
    mirrored = metadata.get(_MIRRORED_VO_KEY)
    return str(mirrored) if mirrored else None


async def gather_approved_changes(session: AsyncSession, project_id: uuid.UUID) -> list[ApprovedChange]:
    """Read the approved change orders and agreed variation orders for a project.

    Only changes whose cost is committed count toward the earned-value view: a
    change order that has been approved or executed, and a variation order that
    has been issued or beyond. Each is projected to an engine ApprovedChange.

    A change order mirroring a variation order that is itself counted here is
    the same committed change and is left out, so a converted variation
    contributes its value once. The mirror is dropped only while its variation
    order counts: a voided variation contributes nothing, and its mirror -
    which can be approved on its own - is then the only record of the change.
    """
    changes: list[ApprovedChange] = []

    vo_stmt = select(
        VariationOrder.id,
        VariationOrder.final_cost_impact,
        VariationOrder.final_schedule_days,
        VariationOrder.currency,
        VariationOrder.status,
        VariationOrder.agreed_at,
    ).where(VariationOrder.project_id == project_id)
    vo_rows = [
        row
        for row in (await session.execute(vo_stmt)).all()
        if (row.status or "").strip().lower() in _VO_AGREED_STATUSES
    ]
    counted_vo_ids = {str(row.id) for row in vo_rows}

    co_stmt = select(
        ChangeOrder.id,
        ChangeOrder.cost_impact,
        ChangeOrder.schedule_impact_days,
        ChangeOrder.currency,
        ChangeOrder.status,
        ChangeOrder.approved_at,
        ChangeOrder.metadata_.label("co_metadata"),
    ).where(ChangeOrder.project_id == project_id)
    for row in (await session.execute(co_stmt)).all():
        if (row.status or "").strip().lower() not in _CO_APPROVED_STATUSES:
            continue
        if _mirrored_variation_order_id(row.co_metadata) in counted_vo_ids:
            continue
        changes.append(
            ApprovedChange(
                ref_id=str(row.id),
                kind=IMPACT_KIND_CHANGE_ORDER,
                cost_impact=row.cost_impact if row.cost_impact is not None else Decimal("0"),
                schedule_impact_days=row.schedule_impact_days or 0,
                currency=row.currency or "",
                status=row.status or "",
                approved_at=row.approved_at,
            )
        )

    for row in vo_rows:
        changes.append(
            ApprovedChange(
                ref_id=str(row.id),
                kind=IMPACT_KIND_VARIATION_ORDER,
                cost_impact=row.final_cost_impact if row.final_cost_impact is not None else Decimal("0"),
                schedule_impact_days=row.final_schedule_days or 0,
                currency=row.currency or "",
                status=row.status or "",
                approved_at=row.agreed_at,
            )
        )

    return changes


async def build_impact_projection(session: AsyncSession, project_id: uuid.UUID) -> ImpactProjection:
    """Project the committed cost and schedule impact of a project's changes."""
    changes = await gather_approved_changes(session, project_id)
    return project_impacts(changes)


# --- Change-request clarifier (co-pilot helper) ----------------------------


def clarify_change_note(note: str, contract_standard: str = "") -> ClarifiedRequest:
    """Turn a rough change note into a structured, well-formed request draft."""
    return analyze_change_note(note, contract_standard=contract_standard)


# --- Action coordination co-pilot ------------------------------------------


async def build_coordination_plan(
    session: AsyncSession,
    project_id: uuid.UUID,
    *,
    now: datetime | None = None,
) -> CoordinationPlan:
    """Rank a project's open change-family items into a "what to act on first" plan.

    Reuses :func:`gather_change_items`, keeps only the open ones, and feeds them
    to the pure :mod:`coordination` engine, which buckets each by urgency
    (overdue / due soon / upcoming / no date) against *now* and pairs it with a
    recommended action.
    """
    moment = now or datetime.now(UTC)
    items = await gather_change_items(session, project_id)
    actions = [
        ActionItem(
            ref_id=item.id,
            kind=item.kind,
            title=item.title,
            ball_in_court=(item.ball_in_court or "").strip() or UNASSIGNED,
            status=item.status,
            due_date=item.response_due_date,
        )
        for item in items
        if item.is_open
    ]
    return build_plan(actions, moment)


# --- Correspondence consolidator co-pilot ----------------------------------


async def build_comms_digest_for_project(
    session: AsyncSession,
    project_id: uuid.UUID,
    *,
    now: datetime | None = None,
) -> CommsDigest:
    """Group a project's correspondence into threads and flag who owes a reply.

    The correspondence module records direction as incoming / outgoing; that
    maps to the engine's inbound / outbound. A thread is keyed by a linked RFI
    when one is set so an RFI conversation folds together, otherwise by the
    normalized subject. Whether a message still expects a reply is read from its
    metadata (defaulting to true) so an informational item can be flagged as
    closing the loop.
    """
    moment = now or datetime.now(UTC)
    stmt = select(
        Correspondence.id,
        Correspondence.subject,
        Correspondence.direction,
        Correspondence.from_contact_id,
        Correspondence.date_sent,
        Correspondence.date_received,
        Correspondence.linked_rfi_id,
        Correspondence.metadata_.label("meta"),
    ).where(Correspondence.project_id == project_id)

    messages: list[Message] = []
    for row in (await session.execute(stmt)).all():
        is_incoming = (row.direction or "").strip().lower().startswith("in")
        direction = DIRECTION_INBOUND if is_incoming else DIRECTION_OUTBOUND
        meta = row.meta or {}
        requires_reply = bool(meta.get("requires_reply", True))
        messages.append(
            Message(
                ref_id=str(row.id),
                subject=row.subject or "",
                sender=row.from_contact_id or "",
                sent_at=row.date_sent or row.date_received,
                direction=direction,
                requires_reply=requires_reply,
                thread_key=row.linked_rfi_id or "",
            )
        )
    return build_digest(messages, moment)


# --- Ownership hand-off chain (accountability reconstruction) ---------------
#
# Each change-family record stores ``ball_in_court`` as one mutable string with
# no history. The service layer records every change of that field as an
# ``oe_activity_log`` row (``action="ownership_handoff"``) carrying the old and
# new holder; status moves are already recorded as ``action="status_changed"``.
# This read resolves both row sets for one record and feeds them to the pure
# :mod:`ownership_chain` engine, which rebuilds who held the ball, in what order,
# and for how long.
#
# The audit ``entity_type`` written for each family is identical to its engine
# kind token (``change_order`` / ``variation_notice`` / ``variation_request`` /
# ``variation_order`` / ``moc_entry``), so the same token resolves the source
# record and filters the activity rows - the read can never drift from the
# write.
_KIND_TO_MODEL: dict[str, type] = {kind: model for model, kind in _SOURCES}

#: Activity-log action verbs the chain reads back (kept in sync with the write
#: side: ``log_ownership_handoff`` and each module's status-transition audit).
_ACTION_OWNERSHIP_HANDOFF = "ownership_handoff"
_ACTION_STATUS_CHANGED = "status_changed"


async def build_ownership_chain_for(
    session: AsyncSession,
    kind: str,
    entity_id: uuid.UUID,
    *,
    now: datetime | None = None,
) -> tuple[OwnershipChain, uuid.UUID]:
    """Reconstruct the ownership chain for one change record.

    Resolves the record by ``kind`` + ``entity_id`` (to fetch its project for the
    caller's access check and its current ball-in-court), gathers the recorded
    hand-off and status-transition rows, and feeds them to the pure engine.

    Returns the :class:`OwnershipChain` together with the record's
    ``project_id`` so the router can run :func:`verify_project_access` against
    the resolved owner. Raises a 404-style :class:`KeyError` for an unknown kind
    and a 404 ``HTTPException`` (via the caller) is expected when the record is
    missing - here a missing record raises ``LookupError`` which the router maps
    to 404.

    Synthesis: when no hand-off rows exist yet but the record still names a
    current ball-in-court, a single open segment is synthesized from the record
    itself (opened at its ``created_at``) so a change that was assigned once and
    never handed off still reports its current holder rather than an empty chain.
    """
    moment = now or datetime.now(UTC)
    model = _KIND_TO_MODEL.get(kind)
    if model is None:
        raise KeyError(kind)

    # Resolve the source record: project (for access) + current holder + opened.
    rec_stmt = select(
        model.id,
        model.project_id,
        model.ball_in_court,
        model.created_at,
    ).where(model.id == entity_id)
    rec = (await session.execute(rec_stmt)).one_or_none()
    if rec is None:
        raise LookupError(kind)
    project_id: uuid.UUID = rec.project_id
    current_ball: str | None = rec.ball_in_court

    # Local import keeps the engine read decoupled from the audit model at import
    # time (mirrors the module services' lazy import of the audit helpers).
    from app.core.audit_log import ActivityLog

    rows = (
        await session.execute(
            select(
                ActivityLog.action,
                ActivityLog.from_status,
                ActivityLog.to_status,
                ActivityLog.actor_id,
                ActivityLog.reason,
                ActivityLog.created_at,
            )
            .where(ActivityLog.entity_type == kind)
            .where(ActivityLog.entity_id == str(entity_id))
            .where(ActivityLog.action.in_((_ACTION_OWNERSHIP_HANDOFF, _ACTION_STATUS_CHANGED)))
            .order_by(ActivityLog.created_at.asc())
        )
    ).all()

    handoffs: list[HandoffRow] = []
    status_transition_times: list[datetime] = []
    for row in rows:
        if row.action == _ACTION_OWNERSHIP_HANDOFF:
            handoffs.append(
                HandoffRow(
                    at=row.created_at,
                    from_party=row.from_status,
                    to_party=row.to_status,
                    set_by=str(row.actor_id) if row.actor_id is not None else None,
                    reason=row.reason,
                )
            )
        elif row.action == _ACTION_STATUS_CHANGED:
            status_transition_times.append(row.created_at)

    # Never handed off but currently assigned: synthesize one open segment from
    # the record so the current holder is still reported.
    if not handoffs and current_ball is not None:
        handoffs.append(
            HandoffRow(
                at=rec.created_at,
                from_party=None,
                to_party=current_ball,
                set_by=None,
                reason=None,
            )
        )

    chain = build_ownership_chain(
        handoffs,
        now=moment,
        status_transition_times=status_transition_times or None,
    )
    return chain, project_id


# --- Dispute-exposure radar (#7) -------------------------------------------
#
# Composes five sibling signals into the pure :mod:`dispute_risk` engine for
# every open change: provability (from :mod:`claims_evidence.provability`),
# overdue age (from the cycle-time aging math), an approval-SLA breach flag,
# ownership ambiguity (from the ownership-chain engine), and the money at risk
# (from the cost-recovery back-charge ledger). The engine's defaults are
# deliberately conservative, so a signal that is not cheaply available per
# change is passed at its safe (high-risk) default rather than fabricated:
#
# * notice / acknowledgement / linked-instruction / dated-record provability
#   signals are left at their conservative defaults - they need a per-change
#   evidence-pack join that this read does not perform - so a change with a
#   clean custody chain still scores in the weak band unless its evidence is
#   wired elsewhere. This is the documented "score an unwired change as if it
#   were weak" behaviour, not an error.
# * the approval-SLA breach flag is passed False: an approval instance is not
#   cheaply linkable to an arbitrary change-family record here. The overdue-age
#   factor still captures lateness from the response-due date the board uses.
#
# Money is taken from back-charges whose ``source_ref`` is the change id (the
# free reference the cost-recovery module stores), summed per change as the
# outstanding and committed-at-risk basis.


async def _back_charges_by_source(session: AsyncSession, project_id: uuid.UUID) -> dict[str, list[BackCharge]]:
    """Index a project's back-charges by their ``source_ref`` (the change id)."""
    rows = (await session.execute(select(BackCharge).where(BackCharge.project_id == project_id))).scalars().all()
    by_source: dict[str, list[BackCharge]] = {}
    for bc in rows:
        key = (bc.source_ref or "").strip()
        if not key:
            continue
        by_source.setdefault(key, []).append(bc)
    return by_source


def _overdue_days_for(response_due_date: str | None, now: datetime) -> float:
    """Days a change is past its response-due date; 0 when not overdue / no date.

    Mirrors the cycle-time board's overdue math (it parses the same stored
    string with :func:`parse_due` and measures against the same ``now``).
    """
    due = parse_due(response_due_date)
    if due is None:
        return 0.0
    seconds = (now - due).total_seconds()
    if seconds <= 0:
        return 0.0
    return round(seconds / 86400.0, 2)


async def build_dispute_risk_board(
    session: AsyncSession,
    project_id: uuid.UUID,
    *,
    now: datetime | None = None,
) -> tuple[list[DisputeRiskItem], DisputeExposureSummary]:
    """Rank a project's open changes by dispute exposure and summarise them.

    Enumerates the same change set the cycle-time board uses
    (:func:`gather_change_items`), keeps the open ones, and for each composes a
    :class:`DisputeRiskInput` from the provability, overdue-age, SLA, ownership
    and cost-recovery signals, then feeds them through the pure engine's
    :func:`rank_dispute_exposure` + :func:`summarize_dispute_exposure`.
    """
    moment = now or datetime.now(UTC)
    items = await gather_change_items(session, project_id)
    by_source = await _back_charges_by_source(session, project_id)

    inputs: list[DisputeRiskInput] = []
    for item in items:
        if not item.is_open:
            continue

        # Ownership ambiguity + chain-present / inconsistent flags from the
        # sibling engine (one read per open change, mirroring the single-change
        # ownership endpoint).
        ownership_ambiguous = False
        chain_present = False
        chain_inconsistent = False
        try:
            chain, _pid = await build_ownership_chain_for(session, item.kind, uuid.UUID(item.id), now=moment)
        except (KeyError, LookupError, ValueError):
            chain = None
        if chain is not None:
            ownership_ambiguous = chain.ownership_ambiguous
            chain_present = chain.total_handoffs > 0
            chain_inconsistent = chain.chain_inconsistent

        # Provability: wire the ownership signals; leave the notice / ack /
        # instruction / dated-record signals at their conservative defaults
        # (not cheaply available per change without an evidence-pack join).
        provability = compute_provability(
            ProvabilitySignals(
                ownership_chain_present=chain_present,
                ownership_ambiguous=ownership_ambiguous,
                ownership_chain_inconsistent=chain_inconsistent,
            )
        )

        days_overdue = _overdue_days_for(item.response_due_date, moment)

        # Money at risk: sum the outstanding and committed-at-risk basis across
        # this change's back-charges (matched by source_ref == change id). All
        # amounts share the engine's currency, so the first non-empty currency
        # wins; the engine never blends currencies in its summary anyway.
        outstanding = Decimal("0")
        committed_at_risk = Decimal("0")
        currency = ""
        for bc in by_source.get(item.id, ()):  # type: ignore[arg-type]
            bc_item = BackChargeItem(
                ref_id=str(bc.id),
                responsible_party=bc.responsible_party or "",
                description=bc.description or "",
                basis=bc.basis or "",
                gross_amount=bc.gross_amount if bc.gross_amount is not None else Decimal("0"),
                # Missing percentage means fully chargeable (1), matching the
                # column server_default and cost_recovery.to_back_charge_item.
                # Defaulting to 0 here would silently zero a row's chargeable
                # amount and understate committed_at_risk / dispute exposure.
                chargeable_pct=bc.chargeable_pct if bc.chargeable_pct is not None else Decimal("1"),
                currency=bc.currency or "",
                status=bc.status or "",
                recovered_amount=bc.recovered_amount if bc.recovered_amount is not None else Decimal("0"),
            )
            outstanding += bc_item.outstanding
            committed_at_risk += bc_item.chargeable_amount
            if not currency and bc.currency:
                currency = bc.currency

        inputs.append(
            DisputeRiskInput(
                change_id=item.id,
                change_ref=item.code,
                kind=item.kind,
                title=item.title,
                provability_score=provability.score,
                provability_band=band_for(provability.score),
                days_overdue=days_overdue,
                sla_breached=False,
                ownership_ambiguous=ownership_ambiguous,
                outstanding_amount=outstanding,
                currency=currency,
                committed_cost_at_risk=committed_at_risk if committed_at_risk > Decimal("0") else None,
            )
        )

    ranked = rank_dispute_exposure(inputs)
    summary = summarize_dispute_exposure(ranked)
    return ranked, summary


# --- Decision-time impact preview (#13) ------------------------------------
#
# Gathers the committed CO / VO cost+schedule impacts for a project as the
# baseline and the one candidate change under decision, and feeds them to the
# pure :mod:`decision_impact` engine. A change counts toward the baseline only
# when its status is committed for its own family: a change order once approved
# or executed, a variation order once issued and not voided. The candidate is
# always applied as a signed delta regardless of its own status.

#: Each change-family kind mapped to the (cost, days, currency, status) column
#: names this preview reads off its row. Mirrors the per-module money columns.
_IMPACT_COLUMNS: dict[str, tuple[str, str, str, str]] = {
    KIND_CHANGE_ORDER: ("cost_impact", "schedule_impact_days", "currency", "status"),
    KIND_VARIATION_REQUEST: ("estimated_cost_impact", "estimated_schedule_days", "currency", "status"),
    KIND_VARIATION_ORDER: ("final_cost_impact", "final_schedule_days", "currency", "status"),
    KIND_MOC_ENTRY: ("cost_impact", "schedule_delta_days", "currency", "status"),
}


def _change_impact_from_row(model: type, kind: str, row) -> ChangeImpact:  # noqa: ANN001 - SQLAlchemy Row
    """Project one change-family row onto a :class:`ChangeImpact`."""
    cost_col, days_col, _cur_col, _status_col = _IMPACT_COLUMNS[kind]
    cost = getattr(row, cost_col, None)
    days = getattr(row, days_col, None)
    return ChangeImpact(
        kind=kind,
        currency=getattr(row, "currency", "") or "",
        cost_impact=cost if cost is not None else Decimal("0"),
        schedule_impact_days=Decimal(str(days)) if days is not None else Decimal("0"),
        status=getattr(row, "status", "") or "",
    )


async def build_decision_impact(
    session: AsyncSession,
    project_id: uuid.UUID,
    candidate_change_id: uuid.UUID,
) -> tuple[DecisionImpact, ChangeImpact]:
    """Preview what approving *candidate_change_id* adds to the committed baseline.

    Reads the committed CO / VO impacts for the project as the baseline and
    resolves the candidate from any change-family table by id, then calls the
    pure engine's :func:`project_with_pending`. Returns the projection together
    with the resolved candidate :class:`ChangeImpact` (so the router can echo
    the candidate's kind and currency). Raises :class:`LookupError` when the
    candidate id is not found in any change-family table.
    """
    # Committed baseline: only the kinds that carry committed cost (CO + VO),
    # filtered by the engine against each row's own (kind, status) pair.
    committed: list[ChangeImpact] = []
    for kind in (KIND_CHANGE_ORDER, KIND_VARIATION_ORDER):
        model = _KIND_TO_MODEL[kind]
        cost_col, days_col, _cur, _st = _IMPACT_COLUMNS[kind]
        stmt = select(
            getattr(model, cost_col),
            getattr(model, days_col),
            model.currency,
            model.status,
        ).where(model.project_id == project_id)
        for row in (await session.execute(stmt)).all():
            committed.append(_change_impact_from_row(model, kind, row))

    # Resolve the candidate from whichever change-family table holds it.
    candidate: ChangeImpact | None = None
    for kind, model in _KIND_TO_MODEL.items():
        if kind not in _IMPACT_COLUMNS:
            continue
        cost_col, days_col, _cur, _st = _IMPACT_COLUMNS[kind]
        stmt = (
            select(
                getattr(model, cost_col),
                getattr(model, days_col),
                model.currency,
                model.status,
            )
            .where(model.project_id == project_id)
            .where(model.id == candidate_change_id)
        )
        row = (await session.execute(stmt)).one_or_none()
        if row is not None:
            candidate = _change_impact_from_row(model, kind, row)
            break

    if candidate is None:
        raise LookupError(str(candidate_change_id))

    return project_with_pending(committed, candidate), candidate


# --- Proactive change watch (#18) ------------------------------------------
#
# Classifies every change against the watch failure modes (stalled / incomplete
# / lost). Each :class:`WatchItem` is built from present state: status drives
# the closed check, ``created_at`` is the opened baseline, ``updated_at`` the
# last movement, the response-due string the due instant, and the ball-in-court
# the owner flag. Completeness is not cheaply available per stored change here
# (the clarifier reads free text, not a persisted score), so it is passed at
# the engine's "complete" sentinel (1.0) - the incomplete rule is therefore not
# triggered by this read; the stalled / lost rules carry the watch.


async def build_change_watch(
    session: AsyncSession,
    project_id: uuid.UUID,
    *,
    now: datetime | None = None,
) -> WatchSummary:
    """Classify a project's changes into the proactive watch summary.

    Reuses :func:`gather_change_items` for the same change set the other boards
    read, projects each onto a :class:`WatchItem`, and feeds them to the pure
    :func:`build_watch`.
    """
    moment = now or datetime.now(UTC)
    items = await gather_change_items(session, project_id)
    watch_items = [
        WatchItem(
            change_id=item.id,
            kind=item.kind,
            status=item.status,
            opened_at=item.opened_at,
            last_movement_at=item.last_activity_at,
            due_at=parse_due(item.response_due_date),
            # Completeness is not persisted per change here; pass the engine's
            # "complete enough" sentinel so the incomplete rule does not fire on
            # a stored change. Stalled / lost still classify from age + owner.
            completeness_score=1.0,
            has_owner=bool((item.ball_in_court or "").strip()),
        )
        for item in items
    ]
    return build_watch(watch_items, now=moment)


# --- Multi-source change-request intake (#14) ------------------------------


def list_intake_profiles() -> list[IntakeMapping]:
    """Return the available intake mapping profiles (built-in presets today)."""
    return list(BUILTIN_PROFILES.values())


def intake_canonical_fields() -> list[str]:
    """The canonical change-request fields every intake profile targets."""
    return list(CANONICAL_FIELDS)


def preview_intake(profile_name: str, record: dict) -> NormalizationResult:
    """Normalize one foreign change-request *record* with the named profile.

    Pure and stateless: resolves the built-in profile by name and runs the
    record through the intake engine. Raises :class:`LookupError` when no profile
    of that name exists, so the router can turn it into a 404.
    """
    mapping = BUILTIN_PROFILES.get(profile_name)
    if mapping is None:
        raise LookupError(profile_name)
    return normalize_intake(record, mapping)


# --- Predictive delay / overrun risk (#19) ---------------------------------

#: Each cost-bearing change family mapped to the cost column the size factor
#: reads (the cost slot of :data:`_IMPACT_COLUMNS`). Variation notices carry no
#: cost and are absent, so they simply contribute no size signal.
_COST_COLUMNS: dict[str, str] = {kind: cols[0] for kind, cols in _IMPACT_COLUMNS.items()}

#: Reverse of :data:`_SOURCES`: the change-family kind token to its ORM model.
_KIND_TO_MODEL: dict[str, type] = {kind: model for model, kind in _SOURCES}


def _parse_positive_money(value: object) -> Decimal | None:
    """Parse a stored money value to a positive :class:`Decimal`, or ``None``.

    Contract value is stored as a string and the per-change cost columns read
    back as ``Decimal``; either may be blank, zero, negative or unparseable. A
    non-positive or unusable value yields ``None`` so the size factor stays
    unwired for that record rather than skewing the blend on bad data.
    """
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        amount = Decimal(text)
    except (InvalidOperation, ValueError):
        return None
    return amount if amount > 0 else None


async def _project_contract_value(session: AsyncSession, project_id: uuid.UUID) -> Decimal | None:
    """Return a project's contract value as a positive Decimal, or ``None``."""
    raw = (await session.execute(select(Project.contract_value).where(Project.id == project_id))).scalar_one_or_none()
    return _parse_positive_money(raw)


async def _change_costs_by_id(session: AsyncSession, project_id: uuid.UUID) -> dict[str, Decimal]:
    """Map each cost-bearing change record id to its own positive cost impact.

    Reads only the per-kind cost column (no relationships) for the cost-bearing
    change families; variation notices have no cost column and are skipped. A
    record with no, zero or unparseable cost is omitted, so it contributes no
    size signal to the delay-risk blend.
    """
    costs: dict[str, Decimal] = {}
    for kind, cost_col in _COST_COLUMNS.items():
        model = _KIND_TO_MODEL[kind]
        column = getattr(model, cost_col, None)
        if column is None:
            continue
        rows = await session.execute(select(model.id, column).where(model.project_id == project_id))
        for change_id, amount in rows.all():
            parsed = _parse_positive_money(amount)
            if parsed is not None:
                costs[str(change_id)] = parsed
    return costs


async def build_delay_risk_board(
    session: AsyncSession,
    project_id: uuid.UUID,
    *,
    now: datetime | None = None,
) -> tuple[list[DelayRiskResult], dict[str, ItemAging]]:
    """Rank a project's open changes by predicted delay / overrun risk.

    Reuses the cycle-time board (one read) for each change's dwell and its
    holder's load and overdue rate, reads each change's own cost for the size
    factor against the project contract value, composes a :class:`DelayRiskInput`
    per open change and feeds them to the pure engine's :func:`rank`. Returns the
    ranked results (highest risk first) together with the aging row per change id
    so the caller can show each change's code / title / party next to its risk.

    Factor sourcing (each documented; a signal that is not cheaply available
    stays at a neutral default rather than being guessed, mirroring the
    dispute-risk board):

    * dwell pressure - actual elapsed age against the change's own allowed
      response window (the span between opening and its response-due date); a
      change with no due date contributes no dwell signal.
    * holder overdue rate - the fraction of the holder's open changes currently
      overdue, a present-state proxy for the historical rate (a recorded
      hand-off history is a later refinement).
    * change size - the change's cost as a fraction of the project contract
      value; unwired (no signal) when either is absent.
    * holder load - how many open changes sit with the same holder.
    """
    moment = now or datetime.now(UTC)
    board = await build_project_board(session, project_id, now=moment)
    costs = await _change_costs_by_id(session, project_id)
    contract_value = await _project_contract_value(session, project_id)
    party_by_name = {p.party: p for p in board.parties}

    inputs: list[DelayRiskInput] = []
    for item in board.items:  # build_board already keeps only open items
        party = party_by_name.get(item.party)
        open_count = party.open_count if party is not None else 0
        overdue_rate = party.overdue_count / party.open_count if party is not None and party.open_count else 0.0

        if item.days_to_due is None:
            # No due date -> no deadline-pressure signal: a zero dwell against a
            # unit window yields a 0 sub-score, avoiding a false alarm.
            dwell_days = 0.0
            sla_days = 1.0
        else:
            # The allowed window is (due - opened) = age so far + time still to
            # due; elapsed age is the dwell measured against it.
            dwell_days = item.age_days
            sla_days = item.age_days + item.days_to_due

        size_ratio = 0.0
        cost = costs.get(item.id)
        if contract_value is not None and cost is not None:
            size_ratio = float(cost / contract_value)

        inputs.append(
            DelayRiskInput(
                change_id=item.id,
                step_mean_dwell_days=dwell_days,
                step_sla_days=sla_days,
                holder_overdue_rate=overdue_rate,
                change_size_ratio=size_ratio,
                holder_open_change_count=open_count,
            )
        )

    ranked = rank_delay_risk(inputs)
    items_by_id = {item.id: item for item in board.items}
    return ranked, items_by_id


# --- Cross-source commitment / action register -----------------------------
#
# Consolidates every open commitment a project carries across five source
# modules into one owner-ranked, overdue-first register. Meeting action items
# and risk mitigation actions live as JSON arrays on their parent record (each
# entry carries its own description / owner / due date / status), while change
# orders, RFIs and submittals each carry a ball-in-court owner and a response /
# required date on the row. All are projected onto the pure engine's
# :class:`RegisterItem`, which decides open-ness per source and ranks the result.


def _first_nonempty_str(*values: object) -> str:
    """First value that stringifies to a non-empty, stripped string, else ``""``."""
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def _finite_decimal_or_zero(value: object) -> Decimal:
    """Parse *value* to a finite :class:`Decimal`, or ``Decimal("0")``.

    Costs read back from the ORM are already :class:`Decimal`; risk impact cost
    is a stored string. A blank, unparseable or non-finite (NaN / Infinity)
    value yields zero so one bad row can never poison a Pareto or a curve sum.
    """
    if value is None:
        return Decimal("0")
    if isinstance(value, Decimal):
        return value if value.is_finite() else Decimal("0")
    text = str(value).strip()
    if not text:
        return Decimal("0")
    try:
        amount = Decimal(text)
    except (InvalidOperation, ValueError):
        return Decimal("0")
    return amount if amount.is_finite() else Decimal("0")


def _month_of(moment: datetime) -> str:
    """The ``YYYY-MM`` bucket a timestamp falls in."""
    return f"{moment.year:04d}-{moment.month:02d}"


def _json_actions(value: object) -> list[dict]:
    """Return *value* as a list of action dicts, tolerating legacy / bad JSON."""
    if not isinstance(value, list):
        return []
    return [entry for entry in value if isinstance(entry, dict)]


async def build_commitment_register(
    session: AsyncSession,
    project_id: uuid.UUID,
    *,
    now: datetime | None = None,
) -> CommitmentRegister:
    """Build the consolidated open-commitment register for one project.

    Reads meeting action items and risk mitigation actions (both JSON arrays),
    plus the open change orders, RFIs and submittals, projects each onto a
    :class:`RegisterItem`, and feeds them to the pure :func:`build_register`,
    which filters to open commitments and ranks them overdue-first with a
    per-owner load summary.
    """
    moment = now or datetime.now(UTC)
    items: list[RegisterItem] = []

    # Meeting action items: [{description, owner_id, due_date, status}].
    meeting_rows = await session.execute(
        select(Meeting.id, Meeting.meeting_number, Meeting.action_items, Meeting.created_at).where(
            Meeting.project_id == project_id
        )
    )
    for row in meeting_rows.all():
        for idx, action in enumerate(_json_actions(row.action_items)):
            items.append(
                RegisterItem(
                    source=SOURCE_MEETING_ACTION,
                    ref_id=f"{row.id}:{idx}",
                    code=row.meeting_number or "",
                    title=_first_nonempty_str(action.get("description"), action.get("title"), action.get("action")),
                    owner=_first_nonempty_str(action.get("owner_id"), action.get("owner"), action.get("assigned_to")),
                    status=_first_nonempty_str(action.get("status")) or None,
                    due_date=_first_nonempty_str(action.get("due_date"), action.get("due")) or None,
                    opened_at=row.created_at,
                )
            )

    # Risk mitigation actions: [{description, responsible_id, due_date, status}].
    risk_rows = await session.execute(
        select(RiskItem.id, RiskItem.code, RiskItem.mitigation_actions, RiskItem.created_at).where(
            RiskItem.project_id == project_id
        )
    )
    for row in risk_rows.all():
        for idx, action in enumerate(_json_actions(row.mitigation_actions)):
            items.append(
                RegisterItem(
                    source=SOURCE_RISK_ACTION,
                    ref_id=f"{row.id}:{idx}",
                    code=row.code or "",
                    title=_first_nonempty_str(action.get("description"), action.get("title"), action.get("action")),
                    owner=_first_nonempty_str(
                        action.get("responsible_id"), action.get("owner_id"), action.get("owner")
                    ),
                    status=_first_nonempty_str(action.get("status")) or None,
                    due_date=_first_nonempty_str(action.get("due_date"), action.get("due")) or None,
                    opened_at=row.created_at,
                )
            )

    # Change orders: the ball-in-court owes the next action by response_due_date.
    co_rows = await session.execute(
        select(
            ChangeOrder.id,
            ChangeOrder.code,
            ChangeOrder.title,
            ChangeOrder.status,
            ChangeOrder.ball_in_court,
            ChangeOrder.response_due_date,
            ChangeOrder.created_at,
        ).where(ChangeOrder.project_id == project_id)
    )
    for row in co_rows.all():
        items.append(
            RegisterItem(
                source=REGISTER_SOURCE_CHANGE_ORDER,
                ref_id=str(row.id),
                code=row.code or "",
                title=(row.title or "").strip(),
                owner=_first_nonempty_str(row.ball_in_court),
                status=row.status or None,
                due_date=row.response_due_date,
                opened_at=row.created_at,
            )
        )

    # RFIs: owner is the ball-in-court (then the assignee); due is the response
    # due date (then the date required).
    rfi_rows = await session.execute(
        select(
            RFI.id,
            RFI.rfi_number,
            RFI.subject,
            RFI.status,
            RFI.ball_in_court,
            RFI.assigned_to,
            RFI.response_due_date,
            RFI.date_required,
            RFI.created_at,
        ).where(RFI.project_id == project_id)
    )
    for row in rfi_rows.all():
        items.append(
            RegisterItem(
                source=SOURCE_RFI,
                ref_id=str(row.id),
                code=row.rfi_number or "",
                title=(row.subject or "").strip(),
                owner=_first_nonempty_str(row.ball_in_court, row.assigned_to),
                status=row.status or None,
                due_date=_first_nonempty_str(row.response_due_date, row.date_required) or None,
                opened_at=row.created_at,
            )
        )

    # Submittals: owner is the ball-in-court (then the reviewer); due is the
    # date required for the review to return.
    sub_rows = await session.execute(
        select(
            Submittal.id,
            Submittal.submittal_number,
            Submittal.title,
            Submittal.status,
            Submittal.ball_in_court,
            Submittal.reviewer_id,
            Submittal.date_required,
            Submittal.created_at,
        ).where(Submittal.project_id == project_id)
    )
    for row in sub_rows.all():
        items.append(
            RegisterItem(
                source=SOURCE_SUBMITTAL,
                ref_id=str(row.id),
                code=row.submittal_number or "",
                title=(row.title or "").strip(),
                owner=_first_nonempty_str(row.ball_in_court, row.reviewer_id),
                status=row.status or None,
                due_date=row.date_required,
                opened_at=row.created_at,
            )
        )

    return build_register(items, moment)


# --- Change-driver Pareto analytics ----------------------------------------
#
# Aggregates the full population of change-bearing records by their originating
# cause and (via a transparent fault allocation of the cause taxonomy) by
# responsible party. Change orders carry a reason category and a signed cost;
# disruption claims a free-text root cause and a cost; extension-of-time claims a
# root-cause category and no cost (time only); risk-register entries a category
# and a stored (string) impact cost. It does not filter by approval status, so it
# reflects total change pressure - the impact projection is the committed view.


async def build_change_drivers(session: AsyncSession, project_id: uuid.UUID) -> DriverAnalytics:
    """Build the change-driver Pareto + trend for one project."""
    records: list[DriverRecord] = []

    co_rows = await session.execute(
        select(
            ChangeOrder.reason_category,
            ChangeOrder.cost_impact,
            ChangeOrder.currency,
            ChangeOrder.created_at,
        ).where(ChangeOrder.project_id == project_id)
    )
    for row in co_rows.all():
        records.append(
            DriverRecord(
                source=DRIVER_SOURCE_CHANGE_ORDER,
                cause=row.reason_category or "",
                cost=_finite_decimal_or_zero(row.cost_impact),
                currency=row.currency or "",
                month=_month_of(row.created_at),
            )
        )

    disruption_rows = await session.execute(
        select(
            DisruptionClaim.root_cause,
            DisruptionClaim.cost_amount,
            DisruptionClaim.currency,
            DisruptionClaim.created_at,
        ).where(DisruptionClaim.project_id == project_id)
    )
    for row in disruption_rows.all():
        records.append(
            DriverRecord(
                source=SOURCE_DISRUPTION_CLAIM,
                cause=row.root_cause or "",
                cost=_finite_decimal_or_zero(row.cost_amount),
                currency=row.currency or "",
                month=_month_of(row.created_at),
            )
        )

    # Extension-of-time claims carry no cost column (they are a time remedy), so
    # they contribute to the count and the trend at zero cost.
    eot_rows = await session.execute(
        select(
            ExtensionOfTimeClaim.root_cause_category,
            ExtensionOfTimeClaim.created_at,
        ).where(ExtensionOfTimeClaim.project_id == project_id)
    )
    for row in eot_rows.all():
        records.append(
            DriverRecord(
                source=SOURCE_EOT_CLAIM,
                cause=row.root_cause_category or "",
                cost=Decimal("0"),
                currency="",
                month=_month_of(row.created_at),
            )
        )

    risk_rows = await session.execute(
        select(
            RiskItem.category,
            RiskItem.impact_cost,
            RiskItem.currency,
            RiskItem.created_at,
        ).where(RiskItem.project_id == project_id)
    )
    for row in risk_rows.all():
        records.append(
            DriverRecord(
                source=SOURCE_RISK,
                cause=row.category or "",
                cost=_finite_decimal_or_zero(row.impact_cost),
                currency=row.currency or "",
                month=_month_of(row.created_at),
            )
        )

    return build_driver_analytics(records)


# --- Change run-rate / cumulative change curve -----------------------------
#
# Places every change order and variation on the timeline at its effective date,
# buckets it approved or pending by status, and feeds the pure engine, which
# builds the month-by-month cumulative change value against the original contract
# value, the intake rate, and a linear burn-rate forecast of the final change
# percentage at completion. Variation requests only contribute pending pipeline
# value while undecided (once decided the downstream variation order carries it),
# so the curve never double counts a request and its order. The same holds one
# step further along: promoting a request also mirrors the resulting variation
# order into a change order, so the pair is collapsed below before the curve is
# built.

#: Each run-rate change family mapped to (model, kind, cost column). Variation
#: notices carry no cost and are absent - the curve is value over time.
_RUNRATE_SOURCES: tuple[tuple[type, str, str], ...] = (
    (ChangeOrder, RUNRATE_KIND_CHANGE_ORDER, "cost_impact"),
    (VariationRequest, RUNRATE_KIND_VARIATION_REQUEST, "estimated_cost_impact"),
    (VariationOrder, RUNRATE_KIND_VARIATION_ORDER, "final_cost_impact"),
)


async def build_change_run_rate(
    session: AsyncSession,
    project_id: uuid.UUID,
    *,
    now: datetime | None = None,
) -> RunRate:
    """Build the change run-rate curve and forecast for one project.

    Reads the change orders and variation requests / orders, classifies each
    into an approved or pending bucket (skipping dead records), resolves the
    date it lands on the timeline, and feeds them to the pure
    :func:`build_run_rate` together with the project's original contract value
    and planned start / end dates for the burn-rate forecast.
    """
    moment = (now or datetime.now(UTC)).date()

    events: list[ChangeEvent] = []
    #: Change order id -> the variation order it mirrors, for the pass below.
    #: Only the change-order family is asked for its metadata; the other two
    #: never carry the link and fetching it would be a column thrown away.
    mirrored_by_co: dict[str, str] = {}
    for model, kind, cost_col in _RUNRATE_SOURCES:
        submitted_col = getattr(model, "submitted_at", None)
        approved_col = getattr(model, "approved_at", None) or getattr(model, "agreed_at", None)
        columns = [
            model.id,
            getattr(model, cost_col),
            model.currency,
            model.status,
            model.created_at,
        ]
        submitted_idx = approved_idx = metadata_idx = None
        if submitted_col is not None:
            submitted_idx = len(columns)
            columns.append(submitted_col.label("submitted_ts"))
        if approved_col is not None:
            approved_idx = len(columns)
            columns.append(approved_col.label("approved_ts"))
        if kind == RUNRATE_KIND_CHANGE_ORDER:
            metadata_idx = len(columns)
            columns.append(ChangeOrder.metadata_.label("co_metadata"))

        rows = await session.execute(select(*columns).where(model.project_id == project_id))
        for row in rows.all():
            bucket = classify_change_bucket(kind, row.status)
            if bucket is None:
                continue
            if metadata_idx is not None:
                mirrored = _mirrored_variation_order_id(row[metadata_idx])
                if mirrored:
                    mirrored_by_co[str(row.id)] = mirrored
            submitted = parse_date(row[submitted_idx]) if submitted_idx is not None else None
            approved = parse_date(row[approved_idx]) if approved_idx is not None else None
            at = resolve_effective_date(bucket, row.created_at.date(), submitted, approved)
            events.append(
                ChangeEvent(
                    ref_id=str(row.id),
                    kind=kind,
                    bucket=bucket,
                    cost=_finite_decimal_or_zero(getattr(row, cost_col)),
                    currency=row.currency or "",
                    at=at,
                )
            )

    # A converted variation is on the curve twice - the in-force variation
    # order in the approved bucket and its draft mirror in the pending one -
    # for the same money, which inflates both the cumulative value and the
    # intake rate on every conversion. Drop the mirror, and only while its
    # variation order is on the curve: a dead variation never got here, so its
    # mirror is the sole record of that change and carries the value alone.
    on_curve_vo_ids = {e.ref_id for e in events if e.kind == RUNRATE_KIND_VARIATION_ORDER}
    events = [
        e
        for e in events
        if not (e.kind == RUNRATE_KIND_CHANGE_ORDER and mirrored_by_co.get(e.ref_id) in on_curve_vo_ids)
    ]

    proj = (
        await session.execute(
            select(
                Project.contract_value,
                Project.planned_start_date,
                Project.planned_end_date,
            ).where(Project.id == project_id)
        )
    ).one_or_none()
    contract_value = _parse_positive_money(proj.contract_value) if proj is not None else None
    project_start = parse_date(proj.planned_start_date) if proj is not None else None
    project_end = parse_date(proj.planned_end_date) if proj is not None else None

    return build_run_rate(
        events,
        contract_value=contract_value,
        project_start=project_start,
        project_end=project_end,
        now=moment,
    )
