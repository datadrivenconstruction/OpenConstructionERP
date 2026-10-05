# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Cross-module deadline aggregator - query + normalise layer.

Modeled directly on :mod:`app.modules.dashboard.inbox`. Each collector imports
its sibling model **inside** the function, and the caller wraps every collector
in ``try/except`` + ``session.rollback()`` so one disabled or broken source only
blanks its own rows - never the whole register or the sweep. This introduces no
new store: it reads the existing per-module tables and normalises them into the
transport ``DeadlineItem`` shape (see :mod:`schemas`). The pure filter/sort/count
logic lives in :mod:`logic` (DB-free, unit-tested).

Deadline sources, with their pinned terminal (closed) status vocabularies - read
from each source's schema/register layer, never guessed:

* correspondence response deadlines - ``oe_correspondence_correspondence``.
* NCR corrective actions - ``oe_qms_ncr_action`` (project via parent ``QMSNCR``).
* punch items - ``oe_punchlist_item``.
* RFI responses - ``oe_rfi_rfi``.
* submittal returns - ``oe_submittals_submittal``.
* variation decisions - ``oe_variations_request``.
* temporary-works design clearance - ``oe_temp_works_item``.
* temporary-works permit expiry - ``oe_temp_works_permit``.
* defect rectification - ``oe_dlp_defect``.
* scheduled quality inspections - ``oe_inspections_inspection``.
* compliance document expiry - ``oe_compliance_docs_doc``.
* bid submission deadlines - ``oe_bid_management_package``.
* signature session expiry - ``oe_signing_session``.
* payment-plan claims not yet raised - ``oe_contracts_milestone`` (reached, no
  live ``oe_contracts_progress_claim`` names it).
* payment-plan instalments falling due - ``oe_contracts_milestone``
  (``forecast_due_date``).

Inclusion rule: a row belongs on the register when somebody is blocked waiting on
it AND its status vocabulary has a state that closes it. That rule keeps out the
much larger population of ``expires_at`` columns that are session, token, lock or
cache TTLs (portal shares, collaboration locks, resumable uploads, takeoff jobs,
field-diary links, refresh tokens): nobody is waiting on them and nothing closes
them. File approvals already own their overdue sweep via
``approval_routes/sla_monitor.py`` so they are intentionally NOT collected here.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.deadlines.logic import APPROACHING, ON_TIME, OVERDUE, build_register, classify, parse_due
from app.modules.deadlines.schemas import DeadlineItem, DeadlineRegisterResponse
from app.modules.projects.models import Project

logger = logging.getLogger(__name__)

# Cap rows pulled per source so a tenant with tens of thousands of open items
# can't drag the sweep/register down. Ordered by due date ascending so the
# most-overdue rows fall inside the cap (mirror ``inbox.py`` per-source cap).
_PER_SOURCE_CAP = 500

# Per-source terminal (closed) status vocabularies, pinned against each source's
# service layer. Anything NOT in the terminal set is treated as still-open - a
# terminal-EXCLUSION model, so an unknown intermediate status still surfaces an
# overdue item rather than silently dropping it (see logic.classify).
_CORRESPONDENCE_TERMINAL = {"responded", "closed"}
_NCR_ACTION_TERMINAL = {"done", "cancelled"}
_PUNCH_TERMINAL = {"closed", "verified"}

# rfi/schemas.py status pattern: draft|open|answered|closed|void. A draft RFI has
# not been asked yet but still carries the date the answer is needed by, so it
# stays open here; only an answered/closed/void one is settled.
_RFI_TERMINAL = {"answered", "closed", "void"}

# submittals/schemas.py status pattern: draft|submitted|under_review|approved|
# approved_as_noted|revise_and_resubmit|rejected|closed. ``revise_and_resubmit``
# is deliberately NOT terminal - the ball is back with the submitter and the
# required-by date still bites.
_SUBMITTAL_TERMINAL = {"approved", "approved_as_noted", "rejected", "closed"}

# variations/schemas.py _VR_STATUS: draft|submitted|under_review|approved|
# rejected|converted_to_vo. The last three are decisions, so they close the
# response deadline.
_VARIATION_REQUEST_TERMINAL = {"approved", "rejected", "converted_to_vo"}

# temporary_works/register.py:128 ``_DESIGN_CLEARED_STATUSES`` is the module's own
# answer to "is the design check finished", so it is exactly the terminal set for
# a design due date. ``on_hold`` is excluded there and stays open here too.
_TEMP_WORKS_DESIGN_TERMINAL = {
    "design_checked",
    "approved_to_load",
    "loaded",
    "in_use",
    "approved_to_strike",
    "struck",
    "removed",
}

# temporary_works/register.py:121 ``_LIVE_PERMIT_STATUSES`` = {issued, active}:
# only a live permit has an expiry anyone must act on. A draft permit is not yet
# in force and an expired/closed one is already spent.
_TEMP_WORKS_PERMIT_TERMINAL = {"draft", "expired", "closed"}

# defects_liability/register.py:126 ``_OUTSTANDING_DEFECT_STATUSES`` = {open,
# rectifying}; the other three states close the rectification deadline.
_DLP_DEFECT_TERMINAL = {"rectified", "rejected", "closed"}

# inspections/schemas.py status pattern: scheduled|in_progress|completed|failed|
# cancelled. ``failed`` closes the *appointment* (the inspection happened); the
# follow-up work is tracked as an NCR or punch item, which have their own rows.
_INSPECTION_TERMINAL = {"completed", "failed", "cancelled"}

# compliance_docs/schemas.py ``STATUSES``: active|expiring_soon|expired|cancelled|
# void. ``expired`` is NOT terminal - an expired insurance certificate is the most
# urgent row on the register, not a closed one.
_COMPLIANCE_DOC_TERMINAL = {"cancelled", "void"}

# bid_management/schemas.py _PACKAGE_STATUS: draft|published|open|closed|
# cancelled|awarded. Once bidding closed, the submission deadline is spent.
_BID_PACKAGE_TERMINAL = {"closed", "cancelled", "awarded"}

# signing/schemas.py ``SESSION_STATUSES``: draft|awaiting_signatures|
# partially_signed|fully_signed|declined|expired.
_SIGNING_TERMINAL = {"fully_signed", "declined", "expired"}

# contracts/models.py ContractMilestone.status: pending|reached|invoiced|paid.
# The collectors select the open states in SQL; these sets are what is left
# for classify, so a pending or paid row can never surface.
_PLAN_CLAIM_TERMINAL = {"pending", "invoiced", "paid"}
_PLAN_INSTALMENT_TERMINAL = {"pending", "paid"}

# A reached instalment is claimed only on a contract that is in force. Money
# already owed is still owed once the works are complete, so the instalment
# reminder also reads completed contracts; a draft, suspended or terminated
# contract is out of both.
_PLAN_CLAIM_CONTRACT_STATUSES = ("active",)
_PLAN_INSTALMENT_CONTRACT_STATUSES = ("active", "completed")

# Days after an instalment becomes claimable by which the claim should be
# raised, when the contract's ``terms.payment_plan.claim_within_days`` does not
# say otherwise.
DEFAULT_CLAIM_WITHIN_DAYS = 7

# A signature for a source collector.
_Collector = Callable[
    [AsyncSession, "list[uuid.UUID] | None", date, int],
    Awaitable[list[DeadlineItem]],
]


def _iso_date(d: date | None) -> str | None:
    return d.isoformat() if d is not None else None


def _owner_id(*candidates: object) -> str | None:
    """The first candidate that is a real user id, as a string.

    Two shapes have to be absorbed. ``GUID`` hands back a ``uuid.UUID`` when the
    stored value parses and the raw string when it does not (see
    ``database.GUID.process_result_value``), and several columns typed ``GUID()``
    are documented as free text - an RFI's ``ball_in_court`` may be a role label
    such as "Architect". Only a parseable id counts as an owner: a role label
    would render as a permanently unresolved name and would stop the sweep
    falling back to the project managers, who can actually act.
    """
    for value in candidates:
        if value is None:
            continue
        try:
            return str(uuid.UUID(str(value)))
        except (AttributeError, TypeError, ValueError):
            continue
    return None


# ── Source collectors ──────────────────────────────────────────────────────


async def _collect_correspondence(
    session: AsyncSession,
    project_ids: list[uuid.UUID] | None,
    now_date: date,
    approaching_days: int,
) -> list[DeadlineItem]:
    """Open correspondence notices past / approaching their response deadline."""
    from app.modules.correspondence.models import Correspondence  # noqa: PLC0415

    stmt = select(Correspondence).where(
        Correspondence.status.not_in(_CORRESPONDENCE_TERMINAL),
        Correspondence.response_required_by.is_not(None),
    )
    if project_ids is not None:
        stmt = stmt.where(Correspondence.project_id.in_(project_ids))
    stmt = stmt.order_by(Correspondence.response_required_by.asc()).limit(_PER_SOURCE_CAP)
    rows = (await session.execute(stmt)).scalars().all()

    items: list[DeadlineItem] = []
    for r in rows:
        due = parse_due(r.response_required_by)
        cls, days, sev = classify(due, r.status, now_date, _CORRESPONDENCE_TERMINAL, approaching_days)
        if cls == ON_TIME:
            continue
        items.append(
            DeadlineItem(
                id=f"correspondence:{r.id}",
                module="correspondence",
                entity_type="correspondence",
                entity_id=str(r.id),
                project_id=str(r.project_id),
                title=r.subject,
                due_date=_iso_date(due),
                # Correspondence has no true assignee - the creator is the
                # best-effort owner. The sweep falls back to project managers
                # for an actionable recipient (see sweeper).
                owner_user_id=r.created_by,
                status=r.status,
                classification=cls,
                days_overdue=days,
                severity=sev,
                action_url="/correspondence",
            ),
        )
    return items


async def _collect_ncr_actions(
    session: AsyncSession,
    project_ids: list[uuid.UUID] | None,
    now_date: date,
    approaching_days: int,
) -> list[DeadlineItem]:
    """NCR corrective actions past / approaching their due date.

    Project scope comes from the parent ``QMSNCR``; an action whose parent NCR
    is missing is dropped (no project scope -> safe default).
    """
    from app.modules.qms.models import QMSNCR, QMSNCRAction  # noqa: PLC0415

    stmt = (
        select(QMSNCRAction, QMSNCR.project_id, QMSNCR.id)
        .join(QMSNCR, QMSNCR.id == QMSNCRAction.ncr_id)
        .where(
            QMSNCRAction.status.not_in(_NCR_ACTION_TERMINAL),
            QMSNCRAction.due_date.is_not(None),
        )
    )
    if project_ids is not None:
        stmt = stmt.where(QMSNCR.project_id.in_(project_ids))
    stmt = stmt.order_by(QMSNCRAction.due_date.asc()).limit(_PER_SOURCE_CAP)
    rows = (await session.execute(stmt)).all()

    items: list[DeadlineItem] = []
    for action, project_id, ncr_id in rows:
        due = parse_due(action.due_date)
        cls, days, sev = classify(due, action.status, now_date, _NCR_ACTION_TERMINAL, approaching_days)
        if cls == ON_TIME:
            continue
        owner = str(action.responsible_user_id) if action.responsible_user_id else None
        title = (action.description or "").strip()[:200] or "NCR corrective action"
        items.append(
            DeadlineItem(
                id=f"qms_ncr_action:{action.id}",
                module="qms_ncr_action",
                entity_type="qms_ncr_action",
                entity_id=str(action.id),
                project_id=str(project_id),
                title=title,
                due_date=_iso_date(due),
                owner_user_id=owner,
                status=action.status,
                classification=cls,
                days_overdue=days,
                severity=sev,
                # Deep-link to the parent NCR (NCRPage reads ?highlight=<id>).
                action_url=f"/ncr?highlight={ncr_id}",
            ),
        )
    return items


async def _collect_punch_items(
    session: AsyncSession,
    project_ids: list[uuid.UUID] | None,
    now_date: date,
    approaching_days: int,
) -> list[DeadlineItem]:
    """Punch items past / approaching their due date."""
    from app.modules.punchlist.models import PunchItem  # noqa: PLC0415

    stmt = select(PunchItem).where(
        PunchItem.status.not_in(_PUNCH_TERMINAL),
        PunchItem.due_date.is_not(None),
    )
    if project_ids is not None:
        stmt = stmt.where(PunchItem.project_id.in_(project_ids))
    stmt = stmt.order_by(PunchItem.due_date.asc()).limit(_PER_SOURCE_CAP)
    rows = (await session.execute(stmt)).scalars().all()

    items: list[DeadlineItem] = []
    for r in rows:
        # due_date is a real DateTime(tz) column here; parse_due handles it.
        due = parse_due(r.due_date)
        cls, days, sev = classify(due, r.status, now_date, _PUNCH_TERMINAL, approaching_days)
        if cls == ON_TIME:
            continue
        items.append(
            DeadlineItem(
                id=f"punchlist:{r.id}",
                module="punchlist",
                entity_type="punch_item",
                entity_id=str(r.id),
                project_id=str(r.project_id),
                title=r.title,
                due_date=_iso_date(due),
                owner_user_id=r.assigned_to,
                status=r.status,
                classification=cls,
                days_overdue=days,
                severity=sev,
                action_url=f"/punchlist?highlight={r.id}",
            ),
        )
    return items


async def _collect_rfis(
    session: AsyncSession,
    project_ids: list[uuid.UUID] | None,
    now_date: date,
    approaching_days: int,
) -> list[DeadlineItem]:
    """RFIs past / approaching the date their answer is due."""
    from app.modules.rfi.models import RFI  # noqa: PLC0415

    stmt = select(RFI).where(
        RFI.status.not_in(_RFI_TERMINAL),
        RFI.response_due_date.is_not(None),
    )
    if project_ids is not None:
        stmt = stmt.where(RFI.project_id.in_(project_ids))
    stmt = stmt.order_by(RFI.response_due_date.asc()).limit(_PER_SOURCE_CAP)
    rows = (await session.execute(stmt)).scalars().all()

    items: list[DeadlineItem] = []
    for r in rows:
        due = parse_due(r.response_due_date)
        cls, days, sev = classify(due, r.status, now_date, _RFI_TERMINAL, approaching_days)
        if cls == ON_TIME:
            continue
        items.append(
            DeadlineItem(
                id=f"rfi:{r.id}",
                module="rfi",
                entity_type="rfi",
                entity_id=str(r.id),
                project_id=str(r.project_id),
                title=r.subject,
                due_date=_iso_date(due),
                # ``assigned_to`` is the answerer; ``ball_in_court`` is who owes
                # the next move and wins when both are set.
                owner_user_id=_owner_id(r.assigned_to, r.ball_in_court),
                status=r.status,
                classification=cls,
                days_overdue=days,
                severity=sev,
                # RfiDetailPage is mounted at /rfi/:rfiId (App.tsx).
                action_url=f"/rfi/{r.id}",
            ),
        )
    return items


async def _collect_submittals(
    session: AsyncSession,
    project_ids: list[uuid.UUID] | None,
    now_date: date,
    approaching_days: int,
) -> list[DeadlineItem]:
    """Submittals past / approaching the date they must be returned by."""
    from app.modules.submittals.models import Submittal  # noqa: PLC0415

    stmt = select(Submittal).where(
        Submittal.status.not_in(_SUBMITTAL_TERMINAL),
        Submittal.date_required.is_not(None),
    )
    if project_ids is not None:
        stmt = stmt.where(Submittal.project_id.in_(project_ids))
    stmt = stmt.order_by(Submittal.date_required.asc()).limit(_PER_SOURCE_CAP)
    rows = (await session.execute(stmt)).scalars().all()

    items: list[DeadlineItem] = []
    for r in rows:
        due = parse_due(r.date_required)
        cls, days, sev = classify(due, r.status, now_date, _SUBMITTAL_TERMINAL, approaching_days)
        if cls == ON_TIME:
            continue
        items.append(
            DeadlineItem(
                id=f"submittals:{r.id}",
                module="submittals",
                entity_type="submittal",
                entity_id=str(r.id),
                project_id=str(r.project_id),
                title=r.title,
                due_date=_iso_date(due),
                owner_user_id=_owner_id(r.reviewer_id, r.ball_in_court),
                status=r.status,
                classification=cls,
                days_overdue=days,
                severity=sev,
                # SubmittalsPage reads ?create/?container_id only, so link the
                # bare route rather than a query param nothing consumes.
                action_url="/submittals",
            ),
        )
    return items


async def _collect_variation_requests(
    session: AsyncSession,
    project_ids: list[uuid.UUID] | None,
    now_date: date,
    approaching_days: int,
) -> list[DeadlineItem]:
    """Variation requests past / approaching the date a decision is due."""
    from app.modules.variations.models import VariationRequest  # noqa: PLC0415

    stmt = select(VariationRequest).where(
        VariationRequest.status.not_in(_VARIATION_REQUEST_TERMINAL),
        VariationRequest.response_due_date.is_not(None),
    )
    if project_ids is not None:
        stmt = stmt.where(VariationRequest.project_id.in_(project_ids))
    stmt = stmt.order_by(VariationRequest.response_due_date.asc()).limit(_PER_SOURCE_CAP)
    rows = (await session.execute(stmt)).scalars().all()

    items: list[DeadlineItem] = []
    for r in rows:
        due = parse_due(r.response_due_date)
        cls, days, sev = classify(due, r.status, now_date, _VARIATION_REQUEST_TERMINAL, approaching_days)
        if cls == ON_TIME:
            continue
        items.append(
            DeadlineItem(
                id=f"variations:{r.id}",
                module="variations",
                entity_type="variation_request",
                entity_id=str(r.id),
                project_id=str(r.project_id),
                title=r.title or r.code,
                due_date=_iso_date(due),
                owner_user_id=_owner_id(r.ball_in_court),
                status=r.status,
                classification=cls,
                days_overdue=days,
                severity=sev,
                action_url="/variations",
            ),
        )
    return items


async def _collect_temp_works_designs(
    session: AsyncSession,
    project_ids: list[uuid.UUID] | None,
    now_date: date,
    approaching_days: int,
) -> list[DeadlineItem]:
    """Temporary-works items whose independent design check is still outstanding."""
    from app.modules.temporary_works.models import TemporaryWorksItem  # noqa: PLC0415

    stmt = select(TemporaryWorksItem).where(
        TemporaryWorksItem.status.not_in(_TEMP_WORKS_DESIGN_TERMINAL),
        TemporaryWorksItem.design_due_date.is_not(None),
    )
    if project_ids is not None:
        stmt = stmt.where(TemporaryWorksItem.project_id.in_(project_ids))
    stmt = stmt.order_by(TemporaryWorksItem.design_due_date.asc()).limit(_PER_SOURCE_CAP)
    rows = (await session.execute(stmt)).scalars().all()

    items: list[DeadlineItem] = []
    for r in rows:
        due = parse_due(r.design_due_date)
        cls, days, sev = classify(due, r.status, now_date, _TEMP_WORKS_DESIGN_TERMINAL, approaching_days)
        if cls == ON_TIME:
            continue
        items.append(
            DeadlineItem(
                id=f"temporary_works:{r.id}",
                module="temporary_works",
                entity_type="temporary_works_item",
                entity_id=str(r.id),
                project_id=str(r.project_id),
                title=r.title,
                due_date=_iso_date(due),
                owner_user_id=_owner_id(r.twc_user_id),
                status=r.status,
                classification=cls,
                days_overdue=days,
                severity=sev,
                action_url="/temporary-works",
            ),
        )
    return items


async def _collect_temp_works_permits(
    session: AsyncSession,
    project_ids: list[uuid.UUID] | None,
    now_date: date,
    approaching_days: int,
) -> list[DeadlineItem]:
    """Live temporary-works permits at or past the end of their validity window.

    A permit to load that lapses while the works are still bearing load is the
    register's red-flag case, so this reads the permit's own ``project_id``
    column and never walks ``permit.item`` (a default-lazy relationship that
    would fire a lazy load from async context).
    """
    from app.modules.temporary_works.models import TemporaryWorksPermit  # noqa: PLC0415

    stmt = select(TemporaryWorksPermit).where(
        TemporaryWorksPermit.status.not_in(_TEMP_WORKS_PERMIT_TERMINAL),
        TemporaryWorksPermit.valid_to.is_not(None),
    )
    if project_ids is not None:
        stmt = stmt.where(TemporaryWorksPermit.project_id.in_(project_ids))
    stmt = stmt.order_by(TemporaryWorksPermit.valid_to.asc()).limit(_PER_SOURCE_CAP)
    rows = (await session.execute(stmt)).scalars().all()

    items: list[DeadlineItem] = []
    for r in rows:
        due = parse_due(r.valid_to)
        cls, days, sev = classify(due, r.status, now_date, _TEMP_WORKS_PERMIT_TERMINAL, approaching_days)
        if cls == ON_TIME:
            continue
        items.append(
            DeadlineItem(
                id=f"temporary_works_permit:{r.id}",
                module="temporary_works_permit",
                entity_type="temporary_works_permit",
                entity_id=str(r.id),
                project_id=str(r.project_id),
                # ``issued_by`` is free text (the coordinator's name), so the
                # permit number plus its type is the only stable label.
                title=f"{r.permit_number} ({r.permit_type})",
                due_date=_iso_date(due),
                # No user column on a permit - the sweep falls back to the
                # project managers for an actionable recipient.
                owner_user_id=None,
                status=r.status,
                classification=cls,
                days_overdue=days,
                severity=sev,
                action_url="/temporary-works",
            ),
        )
    return items


async def _collect_dlp_defects(
    session: AsyncSession,
    project_ids: list[uuid.UUID] | None,
    now_date: date,
    approaching_days: int,
) -> list[DeadlineItem]:
    """Defect notices past / approaching their rectification date.

    Reads the defect's own denormalised ``project_id`` rather than its parent
    warranty, so no relationship is walked.
    """
    from app.modules.defects_liability.models import DlpDefect  # noqa: PLC0415

    stmt = select(DlpDefect).where(
        DlpDefect.status.not_in(_DLP_DEFECT_TERMINAL),
        DlpDefect.due_date.is_not(None),
    )
    if project_ids is not None:
        stmt = stmt.where(DlpDefect.project_id.in_(project_ids))
    stmt = stmt.order_by(DlpDefect.due_date.asc()).limit(_PER_SOURCE_CAP)
    rows = (await session.execute(stmt)).scalars().all()

    items: list[DeadlineItem] = []
    for r in rows:
        due = parse_due(r.due_date)
        cls, days, sev = classify(due, r.status, now_date, _DLP_DEFECT_TERMINAL, approaching_days)
        if cls == ON_TIME:
            continue
        items.append(
            DeadlineItem(
                id=f"defects_liability:{r.id}",
                module="defects_liability",
                entity_type="dlp_defect",
                entity_id=str(r.id),
                project_id=str(r.project_id),
                title=(r.description or "").strip()[:200] or r.reference,
                due_date=_iso_date(due),
                # ``responsible_party`` is a free-text company name, not a user.
                owner_user_id=None,
                status=r.status,
                classification=cls,
                days_overdue=days,
                severity=sev,
                action_url="/defects-liability",
            ),
        )
    return items


async def _collect_inspections(
    session: AsyncSession,
    project_ids: list[uuid.UUID] | None,
    now_date: date,
    approaching_days: int,
) -> list[DeadlineItem]:
    """Quality inspections booked for a date that has arrived or passed.

    ``inspection_date`` is the date the inspection is booked FOR, not a due date
    on a piece of paperwork. It is read as a deadline because an inspection still
    sitting in ``scheduled`` after its date is work that did not happen, and it
    blocks whatever it was gating.
    """
    from app.modules.inspections.models import QualityInspection  # noqa: PLC0415

    stmt = select(QualityInspection).where(
        QualityInspection.status.not_in(_INSPECTION_TERMINAL),
        QualityInspection.inspection_date.is_not(None),
    )
    if project_ids is not None:
        stmt = stmt.where(QualityInspection.project_id.in_(project_ids))
    stmt = stmt.order_by(QualityInspection.inspection_date.asc()).limit(_PER_SOURCE_CAP)
    rows = (await session.execute(stmt)).scalars().all()

    items: list[DeadlineItem] = []
    for r in rows:
        due = parse_due(r.inspection_date)
        cls, days, sev = classify(due, r.status, now_date, _INSPECTION_TERMINAL, approaching_days)
        if cls == ON_TIME:
            continue
        items.append(
            DeadlineItem(
                id=f"inspections:{r.id}",
                module="inspections",
                entity_type="quality_inspection",
                entity_id=str(r.id),
                project_id=str(r.project_id),
                title=r.title,
                due_date=_iso_date(due),
                owner_user_id=_owner_id(r.inspector_id),
                status=r.status,
                classification=cls,
                days_overdue=days,
                severity=sev,
                # InspectionsPage reads ?highlight=<id> (InspectionsPage.tsx).
                action_url=f"/inspections?highlight={r.id}",
            ),
        )
    return items


async def _collect_compliance_docs(
    session: AsyncSession,
    project_ids: list[uuid.UUID] | None,
    now_date: date,
    approaching_days: int,
) -> list[DeadlineItem]:
    """Insurance / permit / certification documents at or past their expiry."""
    from app.modules.compliance_docs.models import ComplianceDoc  # noqa: PLC0415

    stmt = select(ComplianceDoc).where(
        ComplianceDoc.status.not_in(_COMPLIANCE_DOC_TERMINAL),
        ComplianceDoc.expires_at.is_not(None),
    )
    if project_ids is not None:
        stmt = stmt.where(ComplianceDoc.project_id.in_(project_ids))
    stmt = stmt.order_by(ComplianceDoc.expires_at.asc()).limit(_PER_SOURCE_CAP)
    rows = (await session.execute(stmt)).scalars().all()

    items: list[DeadlineItem] = []
    for r in rows:
        due = parse_due(r.expires_at)
        cls, days, sev = classify(due, r.status, now_date, _COMPLIANCE_DOC_TERMINAL, approaching_days)
        if cls == ON_TIME:
            continue
        items.append(
            DeadlineItem(
                id=f"compliance_docs:{r.id}",
                module="compliance_docs",
                entity_type="compliance_doc",
                entity_id=str(r.id),
                project_id=str(r.project_id),
                title=r.name,
                due_date=_iso_date(due),
                # Best-effort owner: the module tracks documents, not holders.
                owner_user_id=_owner_id(r.created_by),
                status=r.status,
                classification=cls,
                days_overdue=days,
                severity=sev,
                # No standalone route: the compliance register is a tab on the
                # project page and ProjectDetailPage reads ?tab= (App.tsx
                # /projects/:projectId).
                action_url=f"/projects/{r.project_id}?tab=compliance",
            ),
        )
    return items


async def _collect_bid_packages(
    session: AsyncSession,
    project_ids: list[uuid.UUID] | None,
    now_date: date,
    approaching_days: int,
) -> list[DeadlineItem]:
    """Bid packages at or past the deadline for bids to come in."""
    from app.modules.bid_management.models import BidPackage  # noqa: PLC0415

    stmt = select(BidPackage).where(
        BidPackage.status.not_in(_BID_PACKAGE_TERMINAL),
        BidPackage.submission_deadline.is_not(None),
    )
    if project_ids is not None:
        stmt = stmt.where(BidPackage.project_id.in_(project_ids))
    stmt = stmt.order_by(BidPackage.submission_deadline.asc()).limit(_PER_SOURCE_CAP)
    rows = (await session.execute(stmt)).scalars().all()

    items: list[DeadlineItem] = []
    for r in rows:
        due = parse_due(r.submission_deadline)
        cls, days, sev = classify(due, r.status, now_date, _BID_PACKAGE_TERMINAL, approaching_days)
        if cls == ON_TIME:
            continue
        items.append(
            DeadlineItem(
                id=f"bid_management:{r.id}",
                module="bid_management",
                entity_type="bid_package",
                entity_id=str(r.id),
                project_id=str(r.project_id),
                title=r.title or r.code,
                due_date=_iso_date(due),
                owner_user_id=_owner_id(r.created_by),
                status=r.status,
                classification=cls,
                days_overdue=days,
                severity=sev,
                action_url="/bid-management",
            ),
        )
    return items


async def _collect_signing_sessions(
    session: AsyncSession,
    project_ids: list[uuid.UUID] | None,
    now_date: date,
    approaching_days: int,
) -> list[DeadlineItem]:
    """Signature sessions whose window to collect the remaining signatures is closing."""
    from app.modules.signing.models import SigningSession  # noqa: PLC0415

    stmt = select(SigningSession).where(
        SigningSession.status.not_in(_SIGNING_TERMINAL),
        SigningSession.expires_at.is_not(None),
    )
    if project_ids is not None:
        stmt = stmt.where(SigningSession.project_id.in_(project_ids))
    stmt = stmt.order_by(SigningSession.expires_at.asc()).limit(_PER_SOURCE_CAP)
    rows = (await session.execute(stmt)).scalars().all()

    items: list[DeadlineItem] = []
    for r in rows:
        due = parse_due(r.expires_at)
        cls, days, sev = classify(due, r.status, now_date, _SIGNING_TERMINAL, approaching_days)
        if cls == ON_TIME:
            continue
        items.append(
            DeadlineItem(
                id=f"signing:{r.id}",
                module="signing",
                entity_type="signing_session",
                entity_id=str(r.id),
                project_id=str(r.project_id),
                # ``document_ref`` is an opaque reference to the signed thing;
                # this module never opens the document to read a nicer name.
                title=(r.document_ref or "").strip()[:200],
                due_date=_iso_date(due),
                owner_user_id=_owner_id(r.created_by),
                status=r.status,
                classification=cls,
                days_overdue=days,
                severity=sev,
                action_url="/signing",
            ),
        )
    return items


def claim_within_days(terms: object) -> int:
    """Days a contract allows from a claimable instalment to the claim.

    Read from ``terms.payment_plan.claim_within_days``. Anything that is not a
    whole number of days, zero or more, falls back to
    :data:`DEFAULT_CLAIM_WITHIN_DAYS` rather than dropping the reminder.
    """
    plan = terms.get("payment_plan") if isinstance(terms, dict) else None
    raw = plan.get("claim_within_days") if isinstance(plan, dict) else None
    if isinstance(raw, bool):
        return DEFAULT_CLAIM_WITHIN_DAYS
    try:
        days = int(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return DEFAULT_CLAIM_WITHIN_DAYS
    return days if days >= 0 else DEFAULT_CLAIM_WITHIN_DAYS


def plan_claim_due(reached_at: object, lag_days: int | None, terms: object) -> date | None:
    """The day by which a reached instalment should have been claimed.

    Counted from the day the instalment becomes claimable, which is the day
    the milestone was reached plus its ``lag_days`` (the same base
    ``contracts.payment_plan.forecast_dates`` uses). Counting from the reached
    day alone would mark a claim late before the contract allows it to be
    raised whenever the lag is longer than the window.
    """
    reached = parse_due(reached_at)
    if reached is None:
        return None
    return reached + timedelta(days=max(lag_days or 0, 0) + claim_within_days(terms))


def _plan_title(contract_code: str | None, milestone: object) -> str:
    """``<contract code> - <instalment name>``; both halves are user data."""
    label = (getattr(milestone, "name", "") or getattr(milestone, "code", "") or "").strip()
    return " - ".join(part for part in ((contract_code or "").strip(), label) if part)[:200]


async def _collect_plan_claims(
    session: AsyncSession,
    project_ids: list[uuid.UUID] | None,
    now_date: date,
    approaching_days: int,
) -> list[DeadlineItem]:
    """Reached payment-plan instalments that nobody has claimed yet.

    A rejected claim billed nothing, so it does not count as raised (the rule
    ``ProgressClaimRepository.open_claims_for_milestones`` applies). The
    "no live claim" test runs in SQL, before the per-source cap, so claimed
    instalments can never fill the cap and hide unclaimed ones.

    The owner is left empty on purpose: raising a claim is the project
    managers' job, and the sweep falls back to them for an empty owner.
    """
    from app.modules.contracts.models import Contract, ContractMilestone, ProgressClaim  # noqa: PLC0415

    live_claim = (
        select(ProgressClaim.id)
        .where(ProgressClaim.milestone_id == ContractMilestone.id, ProgressClaim.status != "rejected")
        .exists()
    )
    stmt = (
        select(ContractMilestone, Contract.code, Contract.project_id, Contract.terms)
        .join(Contract, Contract.id == ContractMilestone.contract_id)
        .where(
            ContractMilestone.status == "reached",
            ContractMilestone.reached_at.is_not(None),
            Contract.status.in_(_PLAN_CLAIM_CONTRACT_STATUSES),
            ~live_claim,
        )
    )
    if project_ids is not None:
        stmt = stmt.where(Contract.project_id.in_(project_ids))
    stmt = stmt.order_by(ContractMilestone.reached_at.asc()).limit(_PER_SOURCE_CAP)
    rows = (await session.execute(stmt)).all()

    items: list[DeadlineItem] = []
    for m, contract_code, project_id, terms in rows:
        due = plan_claim_due(m.reached_at, m.lag_days, terms)
        cls, days, sev = classify(due, m.status, now_date, _PLAN_CLAIM_TERMINAL, approaching_days)
        if cls == ON_TIME:
            continue
        items.append(
            DeadlineItem(
                id=f"contracts_payment_plan_claim:{m.id}",
                module="contracts_payment_plan_claim",
                entity_type="contract_milestone",
                entity_id=str(m.id),
                project_id=str(project_id),
                title=_plan_title(contract_code, m),
                due_date=_iso_date(due),
                owner_user_id=None,
                status=m.status,
                classification=cls,
                days_overdue=days,
                severity=sev,
                # ContractsPage reads ?highlight=<contract id>.
                action_url=f"/contracts?highlight={m.contract_id}",
            ),
        )
    return items


async def _collect_plan_instalments(
    session: AsyncSession,
    project_ids: list[uuid.UUID] | None,
    now_date: date,
    approaching_days: int,
) -> list[DeadlineItem]:
    """Reached or invoiced payment-plan instalments past / near their due date.

    The due date is the stored ``forecast_due_date`` (indexed, kept fresh by
    the contracts module and healed by the sweep). Only instalments that are
    owed count: a pending one is not due whatever its forecast says, the same
    reading ``contracts.payment_plan.client_status`` gives the client.

    These reminders go to the project managers only. Reminding the client is
    a separate, opt-in behaviour (``terms.payment_plan.client_reminders``) and
    nothing in this module sends it.
    """
    from app.modules.contracts.models import Contract, ContractMilestone  # noqa: PLC0415

    stmt = (
        select(ContractMilestone, Contract.code, Contract.project_id)
        .join(Contract, Contract.id == ContractMilestone.contract_id)
        .where(
            ContractMilestone.status.in_(("reached", "invoiced")),
            ContractMilestone.forecast_due_date.is_not(None),
            Contract.status.in_(_PLAN_INSTALMENT_CONTRACT_STATUSES),
        )
    )
    if project_ids is not None:
        stmt = stmt.where(Contract.project_id.in_(project_ids))
    stmt = stmt.order_by(ContractMilestone.forecast_due_date.asc()).limit(_PER_SOURCE_CAP)
    rows = (await session.execute(stmt)).all()

    items: list[DeadlineItem] = []
    for m, contract_code, project_id in rows:
        due = parse_due(m.forecast_due_date)
        cls, days, sev = classify(due, m.status, now_date, _PLAN_INSTALMENT_TERMINAL, approaching_days)
        if cls == ON_TIME:
            continue
        items.append(
            DeadlineItem(
                id=f"contracts_payment_plan:{m.id}",
                module="contracts_payment_plan",
                entity_type="contract_milestone",
                entity_id=str(m.id),
                project_id=str(project_id),
                title=_plan_title(contract_code, m),
                due_date=_iso_date(due),
                owner_user_id=None,
                status=m.status,
                classification=cls,
                days_overdue=days,
                severity=sev,
                action_url=f"/contracts?highlight={m.contract_id}",
            ),
        )
    return items


# Collector registry: (module_key, collector, owns_overdue_sweep).
#
# ``owns_overdue_sweep`` guards against double-notification (spec risk): a
# source that owns its OWN overdue sweep is dropped from the deadline sweeper's
# notify path (it still shows in the read-only register). Determined per source
# by grepping the module for a notification created on an overdue/expiry
# condition and cross-checking ``app/main.py``'s lifespan for a started loop.
# The only started background sweeps in the app are the approval SLA monitor,
# the risk escalation sweeper, this sweeper, the notification worker, the
# collaboration-lock TTL sweeper and the agent/report schedulers - none of them
# belongs to a source below, so every entry is False.
#
# ``compliance_docs`` is the near miss and needs stating precisely, because the
# obvious reading is wrong. It does publish, on the transition into
# ``expiring_soon``/``expired`` (compliance_docs/service.py::_publish_expiry_alert),
# and it publishes ``compliance_docs.expiry.alert``. What makes False correct is
# one step further on: nothing subscribes to that event, so no notification is
# ever produced from it. Subscribe to it in the notifications module and this
# source starts double-notifying on the transition day. That is a live risk
# rather than a hypothetical - every other wave module got its subscriber the
# same way - so the absence is pinned by
# tests/unit/test_deadlines_imports.py::test_compliance_docs_expiry_alert_has_no_subscriber
# rather than left to this comment.
_COLLECTORS: list[tuple[str, _Collector, bool]] = [
    ("correspondence", _collect_correspondence, False),
    ("qms_ncr_action", _collect_ncr_actions, False),
    ("punchlist", _collect_punch_items, False),
    ("rfi", _collect_rfis, False),
    ("submittals", _collect_submittals, False),
    ("variations", _collect_variation_requests, False),
    ("temporary_works", _collect_temp_works_designs, False),
    ("temporary_works_permit", _collect_temp_works_permits, False),
    ("defects_liability", _collect_dlp_defects, False),
    ("inspections", _collect_inspections, False),
    ("compliance_docs", _collect_compliance_docs, False),
    ("bid_management", _collect_bid_packages, False),
    ("signing", _collect_signing_sessions, False),
    # Nothing in the contracts module notifies when an instalment's claim or
    # payment falls late (its milestone subscribers only move statuses and
    # forecasts), so neither source owns a sweep of its own.
    ("contracts_payment_plan_claim", _collect_plan_claims, False),
    ("contracts_payment_plan", _collect_plan_instalments, False),
]


async def _collect_all(
    session: AsyncSession,
    project_ids: list[uuid.UUID] | None,
    now_date: date,
    approaching_days: int,
    *,
    module: str | None = None,
    for_sweep: bool = False,
) -> list[DeadlineItem]:
    """Run every matching collector, fail-soft per source.

    ``module`` filters to a single source. ``for_sweep`` drops any source that
    owns its own overdue sweep (they still appear in the register but must not
    be double-notified by this sweeper).
    """
    collected: list[DeadlineItem] = []
    for module_key, collector, owns_sweep in _COLLECTORS:
        if module is not None and module != module_key:
            continue
        if for_sweep and owns_sweep:
            continue
        try:
            collected.extend(await collector(session, project_ids, now_date, approaching_days))
        except Exception as exc:  # noqa: BLE001 - one broken/disabled source != broken register
            logger.warning("Deadline source %s failed: %s", module_key, exc, exc_info=True)
            # A failed statement aborts the PG transaction; roll back so the
            # next collector runs on a clean session.
            try:
                await session.rollback()
            except Exception:  # noqa: BLE001
                pass
    return collected


async def _resolve_project_names(session: AsyncSession, items: list[DeadlineItem]) -> None:
    """Fill ``project_name`` on each item from a single Project id->name map."""
    if not items:
        return
    ids: set[uuid.UUID] = set()
    for it in items:
        try:
            ids.add(uuid.UUID(it.project_id))
        except (ValueError, TypeError):
            pass
    if not ids:
        return
    try:
        rows = (await session.execute(select(Project.id, Project.name).where(Project.id.in_(ids)))).all()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Deadline project-name resolve failed: %s", exc, exc_info=True)
        try:
            await session.rollback()
        except Exception:  # noqa: BLE001
            pass
        return
    name_by_id = {pid: name for pid, name in rows}
    for it in items:
        try:
            it.project_name = name_by_id.get(uuid.UUID(it.project_id))
        except (ValueError, TypeError):
            pass


async def _resolve_owner_names(session: AsyncSession, items: list[DeadlineItem]) -> None:
    """Fill ``owner_name`` on each item from one batched party lookup.

    The columns these owners come from are bare id strings with no foreign key,
    and three writers put three different things in them: a contact id when the
    party is external (the demo seeder writes the main contractor onto every
    punch item), a user id when a picker names a teammate, and free text when
    somebody types a name or a role label. Resolving against ``User`` alone left
    ``owner_name`` empty for every row naming a contact, and the register then
    printed "Unassigned" over a row that does name somebody - a false statement
    about the row rather than a merely missing one. The lookup therefore runs
    through :func:`app.core.party_names.resolve_party_names`, which tries
    contacts first and users for whatever is left, still in one pass over the
    whole register rather than per row.

    Two misses are deliberately not treated alike. A value that is not
    id-shaped is echoed, because what was typed is already the name. An
    id-shaped value that resolves to nothing stays empty: this client has no
    fallback to ``owner_user_id`` (unlike the inspections list, which ships and
    renders the stored value), so echoing it here would print a raw UUID under
    a column headed by a person's name. Fail-soft, like every other step: a
    cosmetic lookup must not be able to blank the register.
    """
    if not items:
        return
    # ``_owner_id`` normalises to the canonical lowercase form the resolver
    # keys its result on. Punch items and correspondence hand their column
    # straight through, so an id stored in another case would match inside the
    # WHERE clause and then miss the lookup against the returned map.
    keyed: list[tuple[DeadlineItem, str, bool]] = []
    for it in items:
        raw = (it.owner_user_id or "").strip()
        if not raw:
            continue
        canonical = _owner_id(raw)
        keyed.append((it, canonical or raw, canonical is not None))
    if not keyed:
        return
    try:
        from app.core.party_names import resolve_party_names  # noqa: PLC0415

        names = await resolve_party_names(session, [key for _, key, _ in keyed])
    except Exception as exc:  # noqa: BLE001
        logger.warning("Deadline owner-name resolve failed: %s", exc, exc_info=True)
        try:
            await session.rollback()
        except Exception:  # noqa: BLE001
            pass
        return
    for it, key, is_id in keyed:
        resolved = names.get(key)
        if resolved:
            it.owner_name = resolved
        elif not is_id:
            it.owner_name = key


async def compute_deadlines(
    session: AsyncSession,
    project_ids: list[uuid.UUID] | None,
    *,
    now: datetime | None = None,
    status: str = "all",
    module: str | None = None,
    approaching_days: int = 3,
    limit: int = 200,
) -> DeadlineRegisterResponse:
    """Aggregate overdue + approaching items across sources into one register.

    ``project_ids`` scopes the query (the router passes the caller's verified
    project). Each source is fail-soft, so a disabled module only blanks its
    own rows. Counts are pre-cap (see :func:`logic.build_register`).
    """
    now_dt = now or datetime.now(UTC)
    collected = await _collect_all(
        session,
        project_ids,
        now_dt.date(),
        approaching_days,
        module=module,
    )
    await _resolve_project_names(session, collected)
    await _resolve_owner_names(session, collected)
    return build_register(collected, status=status, limit=limit, now=now_dt)


async def collect_overdue_for_sweep(
    session: AsyncSession,
    *,
    now: datetime | None = None,
    project_ids: list[uuid.UUID] | None = None,
) -> list[DeadlineItem]:
    """All currently-overdue items for the sweeper.

    ``project_ids=None`` scans every project (the timer's global sweep); a list
    scopes it (the manual ``POST /sweep`` on one project). Drops sources that own
    their own overdue sweep, keeps only ``overdue`` rows, and resolves project
    names for the notification context.
    """
    now_dt = now or datetime.now(UTC)
    collected = await _collect_all(
        session,
        project_ids,
        now_dt.date(),
        0,
        for_sweep=True,
    )
    overdue = [it for it in collected if it.classification == OVERDUE]
    await _resolve_project_names(session, overdue)
    return overdue


async def collect_approaching_for_sweep(
    session: AsyncSession,
    module: str,
    approaching_days: int,
    *,
    now: datetime | None = None,
    project_ids: list[uuid.UUID] | None = None,
) -> list[DeadlineItem]:
    """Items of one source due today or within ``approaching_days``, for the sweeper.

    The approaching counterpart of :func:`collect_overdue_for_sweep`, run only
    for the sources the sweeper lists in ``sweeper.APPROACHING_NOTIFY``.
    """
    now_dt = now or datetime.now(UTC)
    collected = await _collect_all(
        session,
        project_ids,
        now_dt.date(),
        approaching_days,
        module=module,
        for_sweep=True,
    )
    approaching = [it for it in collected if it.classification == APPROACHING]
    await _resolve_project_names(session, approaching)
    return approaching


# Linked instalments whose forecast one sweep may recompute. Each costs an
# activity read and an UPDATE; whatever is left over is taken next tick.
_HEAL_BATCH = 100


def _aware(value: object) -> datetime | None:
    """A timestamp as an aware UTC datetime, or None.

    ``forecast_at`` is an ISO string; ``updated_at`` comes back aware on
    PostgreSQL and naive on SQLite. Comparing the two raw raises TypeError.
    """
    if isinstance(value, datetime):
        moment = value
    elif value:
        try:
            moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)


async def heal_stale_plan_forecasts(session: AsyncSession, *, limit: int = _HEAL_BATCH) -> int:
    """Recompute linked instalment forecasts older than their activity's last edit.

    The contracts module refreshes a forecast when the schedule announces a
    move, and an announcement can be lost (published before a commit that
    then failed, or while the subscriber was down). An instalment whose
    ``forecast_at`` is missing, or older than its activity's ``updated_at``,
    is recomputed here through ``ContractsService.recompute_milestone_forecast``
    so the plan cannot stay wrong for good. Never-stamped rows go first, then
    the oldest stamps; at most ``limit`` per call.

    This keeps pending instalments honest for the plan and the portal. It
    does not move any reminder this module sends: a reached or invoiced
    instalment is forecast from the day it was reached, not from the activity.

    Each recompute runs in its own savepoint and a failure is logged and
    skipped. The candidate read is not wrapped here; the caller runs the whole
    call inside a savepoint.

    Returns:
        How many instalments were recomputed.
    """
    try:
        from app.modules.contracts.models import Contract, ContractMilestone  # noqa: PLC0415
        from app.modules.contracts.service import ContractsService  # noqa: PLC0415
        from app.modules.schedule.models import Activity  # noqa: PLC0415
    except ImportError:
        return 0

    rows = (
        await session.execute(
            select(ContractMilestone.id, ContractMilestone.forecast_at, Activity.updated_at)
            .join(Activity, Activity.id == ContractMilestone.activity_id)
            .join(Contract, Contract.id == ContractMilestone.contract_id)
            .where(
                ContractMilestone.status != "paid",
                Contract.status.in_(_PLAN_INSTALMENT_CONTRACT_STATUSES),
            )
        )
    ).all()
    stale: list[tuple[datetime | None, uuid.UUID]] = []
    for milestone_id, forecast_at, activity_updated in rows:
        stamped = _aware(forecast_at)
        moved = _aware(activity_updated)
        if stamped is None or (moved is not None and stamped < moved):
            stale.append((stamped, milestone_id))
    stale.sort(key=lambda pair: (pair[0] is not None, pair[0] or datetime.min.replace(tzinfo=UTC)))

    svc = ContractsService(session)
    healed = 0
    for _stamp, milestone_id in stale[:limit]:
        try:
            async with session.begin_nested():
                milestone = await svc.milestone_repo.get_by_id(milestone_id)
                if milestone is None:
                    continue
                contract = await svc.contract_repo.get_by_id(milestone.contract_id)
                if contract is None:
                    continue
                await svc.recompute_milestone_forecast(milestone, contract=contract)
                healed += 1
        except Exception:  # noqa: BLE001 - one bad instalment must not stop the sweep
            logger.warning("Payment-plan forecast heal failed for milestone %s", milestone_id, exc_info=True)
    return healed
